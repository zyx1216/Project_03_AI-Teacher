# -*- coding: utf-8 -*-
"""RAG 课本智能问答服务（v1.9.6）。

不新建向量存储：检索底座复用 utils/vector_store.py 的 ChromaDB 向量层
（云端 embedding → 本地 ONNX → 关键词三级降级）与现有分块函数。
本服务只补“多资料检索 → 归并 → 拼上下文 → LLM 生成 → 来源引用”的编排。

置信度为确定性规则判定，不由模型自报；无命中/仅关键词兜底时明确给低置信度。
LLM 调用沿用现有超时与异常类型。
"""

from __future__ import annotations

import json

import config
from models.models import Textbook
from utils import llm_client, material_service, vector_store

RAG_CONFIG_PATH = config.DATA_DIR / "rag_config.json"

# 相似度阈值（cosine similarity，1 - chroma cosine distance）。
HIGH_SIM = 0.75
MID_SIM = 0.55
# 关键词兜底命中给一个低的名义相似度，保证排序在向量命中之后。
KEYWORD_NOMINAL_SIM = 0.30


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

def default_config() -> dict:
    """RAG 配置默认值。"""
    return {"top_k": 5, "show_sources": True}


def load_config() -> dict:
    """加载配置；缺失自建，损坏回退默认且不覆盖原文件。"""
    path = RAG_CONFIG_PATH
    try:
        if not path.exists():
            cfg = default_config()
            save_config(cfg)
            return cfg
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return default_config()
    except (json.JSONDecodeError, OSError):
        return default_config()
    cfg = default_config()
    try:
        top_k = int(data.get("top_k", cfg["top_k"]))
    except (TypeError, ValueError):
        top_k = cfg["top_k"]
    cfg["top_k"] = max(1, min(top_k, 10))
    cfg["show_sources"] = bool(data.get("show_sources", True))
    return cfg


def save_config(cfg: dict) -> None:
    """持久化 RAG 配置，UTF-8、ensure_ascii=False。"""
    RAG_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    RAG_CONFIG_PATH.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# 切块与索引
# ---------------------------------------------------------------------------

def _text_path(textbook_id: int):
    """资料保存的纯文本路径（与 lesson_plan.TEXT_DIR 口径一致）。"""
    return config.UPLOAD_DIR / "text" / f"{textbook_id}.txt"


def load_chunks_for(session, textbook_id: int) -> list[dict]:
    """从保存文本重建切块；缺文本返回空列表。"""
    path = _text_path(textbook_id)
    try:
        if not path.exists():
            return []
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    chapters = material_service.split_chapters(text)
    return material_service.chunk_chapters(chapters)


def ensure_index(session, textbook_id: int) -> dict:
    """未建索引则建立；返回 {textbook_id, indexed, method}。

    method="keyword" 不算真正的向量索引，indexed 仍为 False。
    """
    if vector_store.has_vector_index(textbook_id):
        return {"textbook_id": textbook_id, "indexed": True, "method": "vector"}
    chunks = load_chunks_for(session, textbook_id)
    if not chunks:
        return {"textbook_id": textbook_id, "indexed": False, "method": "empty"}
    method = vector_store.build_index(int(textbook_id), chunks)
    indexed = method != "keyword"
    return {"textbook_id": textbook_id, "indexed": indexed, "method": method}


# ---------------------------------------------------------------------------
# 多资料检索归并
# ---------------------------------------------------------------------------

def _similarity_of(result) -> float:
    """把检索结果换算成 cosine 相似度；关键词兜底给名义低值。"""
    if result.method == "keyword":
        return KEYWORD_NOMINAL_SIM
    sim = 1.0 - float(getattr(result, "distance", 0.0) or 0.0)
    return round(max(0.0, min(1.0, sim)), 4)


def retrieve(session, query: str, textbook_ids: list[int],
             top_k: int | None = None) -> list[dict]:
    """跨多资料检索并全局归并排序，返回 JSON 安全的 top_k 结果。

    每条：{textbook_id, textbook_name, chapter, text, method, similarity}
    向量命中（cloud/local，相似度高者）排在关键词兜底之前。
    """
    top_k = top_k or load_config()["top_k"]
    candidates: list[dict] = []
    for tb_id in dict.fromkeys(int(x) for x in textbook_ids):
        tb = session.get(Textbook, tb_id)
        if tb is None:
            continue
        chunks = load_chunks_for(session, tb.id)
        if not chunks:
            continue
        results = vector_store.search(tb.id, chunks, query, top_k=top_k)
        for r in results:
            candidates.append({
                "textbook_id": tb.id,
                "textbook_name": tb.name,
                "chapter": r.chapter or "",
                "text": r.text,
                "method": r.method,
                "similarity": _similarity_of(r),
            })
    is_vector = lambda c: c["method"] != "keyword"
    vector_hits = sorted(
        (c for c in candidates if is_vector(c)),
        key=lambda c: (-c["similarity"], c["textbook_id"]))
    keyword_hits = sorted(
        (c for c in candidates if not is_vector(c)),
        key=lambda c: c["textbook_id"])
    return (vector_hits + keyword_hits)[:top_k]


def _confidence(hits: list[dict]) -> str:
    """按命中结构确定性判定置信度：高/中/低。"""
    vector_hits = [h for h in hits if h["method"] != "keyword"]
    if not vector_hits:
        return "低"
    top = vector_hits[0]["similarity"]
    distinct_sources = {(h["chapter"] or h["text"][:20]) for h in vector_hits}
    if top >= HIGH_SIM and len(distinct_sources) >= 2:
        return "高"
    if top >= MID_SIM or len(vector_hits) >= 2:
        return "中"
    return "低"


# ---------------------------------------------------------------------------
# RAG 生成
# ---------------------------------------------------------------------------

_RAG_SYSTEM = (
    "你是严谨的教学资料问答助手。只根据“参考资料”回答老师的问题，"
    "不要使用资料外的知识，也不要编造。资料中找不到依据时，"
    "直接说明“资料中没有相关内容”。回答用简体中文，条理清楚。")


def rag_answer(session, query: str, textbook_ids: list[int]) -> dict:
    """检索 → 拼参考 → LLM 生成；返回 {answer, sources, confidence}。"""
    query = str(query or "").strip()
    if not query:
        raise ValueError("问题内容为空。")
    if not textbook_ids:
        raise ValueError("请先选择至少一份资料。")

    hits = retrieve(session, query, textbook_ids)
    confidence = _confidence(hits)
    if not hits:
        return {
            "answer": "所选资料中没有可用于回答的内容。",
            "sources": [], "confidence": "低",
        }

    context = vector_store.format_context([
        vector_store.RetrievalResult(
            h["text"], h["chapter"], h["method"]) for h in hits])
    user_text = f"参考资料：\n{context}\n\n老师的问题：{query}"
    answer = llm_client.chat_content(
        _RAG_SYSTEM, user_text, temperature=0.3)
    return {
        "answer": str(answer).strip(),
        "sources": [_source_brief(h) for h in hits],
        "confidence": confidence,
    }


def _source_brief(hit: dict) -> dict:
    """来源引用的轻量结构。"""
    return {
        "textbook_id": hit["textbook_id"],
        "textbook_name": hit["textbook_name"],
        "chapter": hit["chapter"],
        "similarity": hit["similarity"],
    }
