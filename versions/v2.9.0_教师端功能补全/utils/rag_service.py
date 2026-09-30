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


# ---------------------------------------------------------------------------
# v2.7.0：混合检索增强 + 图谱问答
# ---------------------------------------------------------------------------

def _mastery_rates(session, subject: str | None) -> dict:
    """取知识点掌握率 {知识点: rate}（来自逐题作答，失败返回空）。"""
    if not subject:
        return {}
    try:
        from utils import knowledge_graph_service as kgs
        matrix = kgs.build_mastery(session, subject)
        out = {}
        for row in (matrix.get("kps") or []):
            name = row.get("knowledge_point") or row.get("name")
            if name is not None:
                out[str(name)] = row.get("rate")
        return out
    except Exception:  # noqa: BLE001 —— 掌握度缺失不影响检索
        return {}


def hybrid_retrieve(session, query: str, textbook_ids: list[int],
                    top_k: int | None = None,
                    subject: str | None = None,
                    material_id: int | None = None) -> list[dict]:
    """混合检索：关键词 + 向量 + 图谱邻居，并按相关性×重要性×掌握度重排。

    在 retrieve 结果基础上补充图谱邻居命中，返回 JSON 安全列表。
    """
    base = retrieve(session, query, textbook_ids, top_k=top_k)
    top_k = top_k or load_config()["top_k"]
    rates = _mastery_rates(session, subject)
    # 图谱邻居：命中知识点若关联前置/递进，补充其来源章节文本
    extra = []
    if material_id:
        try:
            from utils import knowledge_graph_service as kgs
            nodes = kgs.list_nodes(session, material_id)
            hit_names = [n["name"] for n in nodes
                         if n["name"] and n["name"] in str(query)]
            for name in hit_names:
                for pre in kgs.prerequisites_of(session, material_id, name):
                    for tb_id in dict.fromkeys(int(x) for x in textbook_ids):
                        for chunk in load_chunks_for(session, tb_id):
                            if pre and pre in str(chunk.get("text") or ""):
                                extra.append({
                                    "textbook_id": tb_id,
                                    "textbook_name": getattr(
                                        session.get(Textbook, tb_id), "name", ""),
                                    "chapter": (chunk.get("chapter_title")
                                                or chunk.get("chapter") or ""),
                                    "text": chunk.get("text") or "",
                                    "method": "graph",
                                    "similarity": KEYWORD_NOMINAL_SIM,
                                    "graph_via": pre,
                                })
                                break
        except Exception:  # noqa: BLE001 —— 图谱缺失不影响检索
            extra = []

    merged = base + extra
    for item in merged:
        rel = float(item.get("similarity") or 0)
        # 重要性：命中文本含知识点关键词时略加权
        imp = 1.0
        rate = None
        for kp, r in rates.items():
            if kp and kp in str(item.get("text") or ""):
                imp = 1.1
                rate = r
                break
        mastery_w = 1.0 if rate is None else (1.0 + (1.0 - float(rate)) * 0.2)
        item["rerank_score"] = round(rel * imp * mastery_w, 4)
    merged.sort(key=lambda c: (-c["rerank_score"], c["textbook_id"]))
    return merged[:top_k]


def compare_documents(session, knowledge_point: str,
                      textbook_ids: list[int]) -> list[dict]:
    """多文档对比：同一知识点在不同资料中的表述。"""
    kp = str(knowledge_point or "").strip()
    if not kp:
        return []
    out = []
    for tb_id in dict.fromkeys(int(x) for x in textbook_ids):
        tb = session.get(Textbook, tb_id)
        if tb is None:
            continue
        for chunk in load_chunks_for(session, tb.id):
            text = str(chunk.get("text") or "")
            if kp in text:
                out.append({"textbook_id": tb.id, "textbook_name": tb.name,
                            "chapter": chunk.get("chapter") or "",
                            "excerpt": text[:200]})
                break
    return out


_GRAPH_SYSTEM = (
    "你是知识图谱问答助手。只依据给出的图谱关系回答，不要编造。"
    "资料没有的关系就明确说明“图谱中没有该信息”。回答用简体中文。")

GRAPH_QUESTION_HINTS = {
    "前置": ["前置", "先掌握", "先学", "需要哪些"],
    "对比": ["区别", "联系", "对比", "有什么不同"],
    "路径": ["学习路径", "怎么学", "需要先掌握哪些", "想学好"],
}


def classify_graph_question(query: str) -> str:
    """判断图谱问题类型：前置 / 对比 / 路径 / 其它。"""
    text = str(query or "")
    for kind in ("路径", "对比", "前置"):
        if any(h in text for h in GRAPH_QUESTION_HINTS[kind]):
            return kind
    return "其它"


def graph_answer(session, query: str, material_id: int,
                 chat_func=None) -> dict:
    """图谱问答：前置知识 / 对比 / 路径推荐。

    返回 {"answer","question_type","evidence","source"}。
    """
    from utils import knowledge_graph_service as kgs
    query = str(query or "").strip()
    if not query:
        raise ValueError("问题内容为空。")
    nodes = kgs.list_nodes(session, material_id)
    if not nodes:
        return {"answer": "该资料还没有知识图谱，请先「构建图谱」。",
                "question_type": "其它", "evidence": [], "source": "empty"}
    names = [n["name"] for n in nodes]
    mentioned = [n for n in names if n and n in query]
    kind = classify_graph_question(query)
    evidence = []
    if kind == "路径" and mentioned:
        evidence = kgs.learning_path(session, material_id, mentioned[0])
        fallback = ("学习路径（先学→后学）：" + " → ".join(evidence)
                    if evidence else "图谱中没有该知识点的前置关系。")
    elif kind == "前置" and mentioned:
        evidence = kgs.prerequisites_of(session, material_id, mentioned[0])
        fallback = (f"「{mentioned[0]}」的前置知识：" + "、".join(evidence)
                    if evidence else f"图谱中没有「{mentioned[0]}」的前置关系。")
    elif kind == "对比" and len(mentioned) >= 2:
        a, b = mentioned[0], mentioned[1]
        related = [e for e in kgs.list_edges(session, material_id)
                   if e.get("relation_type")]
        evidence = [f"{a} 与 {b} 的关系需结合图谱边判断"]
        fallback = f"已定位到「{a}」和「{b}」，图中存在 {len(related)} 条关系边。"
    else:
        fallback = ("暂不支持该问题的图谱回答，可问：某知识点的前置知识、"
                    "两个知识点的区别与联系、某知识点的学习路径。")

    if chat_func is None:
        try:
            from utils import llm_client
            if not llm_client.is_configured():
                return {"answer": fallback, "question_type": kind,
                        "evidence": evidence, "source": "template"}
            chat_func = lambda s, u: llm_client.chat_content(s, u)
        except Exception:  # noqa: BLE001
            return {"answer": fallback, "question_type": kind,
                    "evidence": evidence, "source": "template"}
    try:
        edges = [e for e in kgs.list_edges(session, material_id)]
        payload = (f"问题：{query}\n知识点：{names}\n"
                   f"关系边：{edges}\n参考结论：{fallback}")
        answer = str(chat_func(_GRAPH_SYSTEM, payload) or "").strip() or fallback
        return {"answer": answer, "question_type": kind,
                "evidence": evidence, "source": "ai"}
    except Exception as exc:  # noqa: BLE001
        return {"answer": fallback + f"（AI 不可用：{exc}）",
                "question_type": kind, "evidence": evidence,
                "source": "template"}
