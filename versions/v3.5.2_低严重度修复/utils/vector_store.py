# -*- coding: utf-8 -*-
"""
课本向量检索层（ChromaDB），带三级降级，保证任何情况下备课不被阻断：

1. 云端中文 embedding（设置页配置 embed_base_url/embed_model）；
2. 云端不可用时回退 ChromaDB 默认本地 ONNX 模型（首次需联网下载，英文模型，
   中文效果一般，仅兜底）；
3. 本地模型也不可用时，直接用关键词重叠检索（零依赖、离线可用）。

每份教学资料一个 collection；检索返回带来源章节的 Top-K 片段。
检索到的片段在业务层作为"用户消息数据"注入模型，不拼进 system prompt。
"""

from __future__ import annotations

import re
from typing import Optional

import config
from utils import llm_client

TOP_K = 3
_COLLECTION_PREFIX = "textbook_"


def collection_name(textbook_id: int) -> str:
    """Chroma collection 名只接受特定字符，用固定前缀+id。"""
    return f"{_COLLECTION_PREFIX}{textbook_id}"


class RetrievalResult:
    """一条检索结果：片段文本 + 所属章节 + 命中方式。"""

    def __init__(self, text: str, chapter: str, method: str, distance: float = 0.0):
        self.text = text
        self.chapter = chapter
        self.method = method      # cloud / local / keyword
        self.distance = distance

    def to_dict(self) -> dict:
        return {"text": self.text, "chapter": self.chapter, "method": self.method}


# ---------------------------------------------------------------------------
# 关键词兜底检索（不依赖任何模型）
# ---------------------------------------------------------------------------

def _keywords(query: str) -> list[str]:
    """非常轻量的中文关键词切分：按非字母数字汉字切，再补充 2-3 字滑窗。"""
    tokens = re.findall(r"[0-9A-Za-z]+|[一-龥]{2,}", query)
    words = list(tokens)
    for seg in re.findall(r"[一-龥]{4,}", query):
        for n in (2, 3):
            for i in range(len(seg) - n + 1):
                words.append(seg[i:i + n])
    # 去重保序，过滤太通用的单字
    seen = set()
    result = []
    for w in words:
        if len(w) >= 2 and w not in seen:
            seen.add(w)
            result.append(w)
    return result


def keyword_search(chunks: list[dict], query: str, top_k: int = TOP_K) -> list[RetrievalResult]:
    """按关键词命中次数给片段打分排序。"""
    words = _keywords(query)
    scored = []
    for idx, chunk in enumerate(chunks):
        text = chunk.get("text", "")
        score = sum(text.count(w) for w in words)
        if score > 0:
            scored.append((score, idx, chunk))
    if not scored:
        # 一个词都没命中时，退而返回前几块，至少给模型一点上下文
        scored = [(0, idx, chunk) for idx, chunk in enumerate(chunks[:top_k])]
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [RetrievalResult(c["text"], c.get("chapter_title", ""), "keyword")
            for _, _, c in scored[:top_k]]


# ---------------------------------------------------------------------------
# Chroma 向量检索
# ---------------------------------------------------------------------------

def _get_client():
    """获取持久化 Chroma 客户端。"""
    import chromadb
    config.ensure_dirs()
    return chromadb.PersistentClient(path=str(config.CHROMA_DIR))


def _embed_function():
    """
    返回 (embedding 函数, 方式)。
    优先云端中文 embedding；未配置或构造失败返回 None，由上层走关键词。
    """
    if not llm_client.embedding_config_ready() or not llm_client.get_api_key():
        return None, None

    def _call(input):  # chroma 的 embedding function 协议：可调用对象
        return llm_client.embed_texts(list(input))

    _call.__name__ = "cloud_embedding"
    return _call, "cloud"


def build_index(textbook_id: int, chunks: list[dict]) -> str:
    """
    为一份资料建立索引。返回实际使用的索引方式：cloud / local / keyword。
    chunks: material_service.chunk_chapters 的输出。
    """
    if not chunks:
        raise ValueError("没有可索引的内容")

    embed_fn, method = _embed_function()
    try:
        client = _get_client()
        col = client.get_or_create_collection(
            name=collection_name(textbook_id),
            embedding_function=embed_fn,
            metadata={"hnsw:space": "cosine"},
        )
        # 重建索引：先清空旧内容
        try:
            col.delete(where={"_id": {"$ne": ""}})  # 兼容写法，多数版本直接忽略
        except Exception:
            pass
        col.upsert(
            ids=[f"{textbook_id}_{i}" for i in range(len(chunks))],
            documents=[c["text"] for c in chunks],
            metadatas=[{"chapter": c.get("chapter_title", "")} for c in chunks],
        )
        return method or "local"
    except Exception:
        # 云端 embedding 调用失败（如模型 ID 错、网络不通）时，不带 embedding 重建，
        # 让 chroma 用默认本地函数；再失败则整体回退关键词。
        try:
            client = _get_client()
            col = client.get_or_create_collection(
                name=collection_name(textbook_id))
            col.upsert(
                ids=[f"{textbook_id}_{i}" for i in range(len(chunks))],
                documents=[c["text"] for c in chunks],
                metadatas=[{"chapter": c.get("chapter_title", "")} for c in chunks],
            )
            return "local"
        except Exception:
            return "keyword"


def has_vector_index(textbook_id: int) -> bool:
    """这份资料是否已在 Chroma 里建好向量索引。"""
    try:
        client = _get_client()
        col = client.get_collection(collection_name(textbook_id))
        return col.count() > 0
    except Exception:
        return False


def drop_index(textbook_id: int) -> None:
    """删除一份资料的向量集合；不存在或删除失败时静默，不阻断资料删除。"""
    try:
        client = _get_client()
        client.delete_collection(collection_name(textbook_id))
    except Exception:
        pass


def search(textbook_id: int, chunks: list[dict], query: str,
           top_k: int = TOP_K) -> list[RetrievalResult]:
    """
    检索与课题最相关的片段。优先向量库，失败/未建索引时走关键词兜底。
    chunks 也要传入，保证关键词兜底和向量库不可用时仍能检索。
    """
    # 先尝试向量检索
    if chunks:
        try:
            client = _get_client()
            embed_fn, method = _embed_function()
            kwargs = {}
            if embed_fn is not None:
                kwargs["embedding_function"] = embed_fn
            col = client.get_collection(collection_name(textbook_id), **kwargs)
            if col.count() > 0:
                res = col.query(query_texts=[query], n_results=top_k)
                docs = (res.get("documents") or [[]])[0]
                metas = (res.get("metadatas") or [[]])[0]
                dists = (res.get("distances") or [[]])[0]
                if docs:
                    return [
                        RetrievalResult(
                            docs[i],
                            (metas[i] or {}).get("chapter", "") if i < len(metas) else "",
                            method or "local",
                            float(dists[i]) if i < len(dists) else 0.0,
                        )
                        for i in range(len(docs))
                    ]
        except Exception:
            pass  # 静默降级到关键词，保证主流程不中断
    return keyword_search(chunks, query, top_k)


def format_context(results: list[RetrievalResult]) -> str:
    """把检索结果拼成给模型看的参考材料文本（带来源章节）。"""
    if not results:
        return "（未检索到相关课本内容）"
    blocks = []
    for i, r in enumerate(results, start=1):
        source = f"（来源：{r.chapter}）" if r.chapter else ""
        blocks.append(f"[参考{i}]{source}\n{r.text}")
    return "\n\n".join(blocks)