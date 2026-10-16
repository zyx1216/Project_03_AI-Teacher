# -*- coding: utf-8 -*-
"""缓存机制（v2.8.0）。

- LLM 响应缓存：内存 LRU + llm_cache 表；默认 TTL 24h；记录命中次数；
- 查询缓存：内存按 tag + TTL；写入后可 invalidate(tag)；
- 文件解析缓存：按（文件名+大小+哈希）避免重复解析。
不引入 Redis，全部标准库实现。
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from datetime import datetime, timedelta

_MEM_MAX = 200
_llm_mem: "OrderedDict[str, tuple[str, float]]" = OrderedDict()
_query_mem: dict[tuple[str, str], tuple[object, float]] = {}
_file_mem: dict[str, object] = {}
_lock = threading.Lock()

DEFAULT_LLM_TTL = 24 * 3600
SHORT_TTL = 5 * 60
LONG_TTL = 60 * 60


# ---------------------------------------------------------------------------
# LLM 响应缓存
# ---------------------------------------------------------------------------

def make_llm_key(system_prompt: str, user_prompt: str, temperature,
                 model: str = "", base_url: str = "") -> str:
    """缓存键 = sha256(模型+参数+prompt)。"""
    payload = "\x1f".join([
        str(model or ""), str(base_url or ""), str(temperature),
        str(system_prompt or ""), str(user_prompt or "")])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _mem_get(key: str) -> str | None:
    with _lock:
        item = _llm_mem.get(key)
        if item is None:
            return None
        value, expire_at = item
        if expire_at and expire_at < time.time():
            _llm_mem.pop(key, None)
            return None
        _llm_mem.move_to_end(key)
        return value


def _mem_set(key: str, value: str, ttl: int) -> None:
    with _lock:
        _llm_mem[key] = (value, time.time() + ttl)
        _llm_mem.move_to_end(key)
        while len(_llm_mem) > _MEM_MAX:
            _llm_mem.popitem(last=False)


def get_llm_cache(key: str) -> str | None:
    """查缓存：先内存，再 llm_cache 表（命中则回填内存并累加 hit_count）。"""
    value = _mem_get(key)
    if value is not None:
        _bump_hit(key)
        return value
    try:
        from utils.db import SessionLocal
        from models.models import LLMCache
        with SessionLocal() as session:
            row = session.query(LLMCache).filter(
                LLMCache.cache_key == key).first()
            if row is None:
                return None
            if row.expires_at and row.expires_at < datetime.now():
                session.delete(row)
                session.commit()
                return None
            row.hit_count = int(row.hit_count or 0) + 1
            session.commit()
            _mem_set(key, row.response or "", DEFAULT_LLM_TTL)
            return row.response or ""
    except Exception:  # noqa: BLE001 —— 缓存失败不影响主流程
        return None


def _bump_hit(key: str) -> None:
    try:
        from utils.db import SessionLocal
        from models.models import LLMCache
        with SessionLocal() as session:
            row = session.query(LLMCache).filter(
                LLMCache.cache_key == key).first()
            if row is not None:
                row.hit_count = int(row.hit_count or 0) + 1
                session.commit()
    except Exception:  # noqa: BLE001
        pass


def set_llm_cache(key: str, response: str, model: str = "",
                  prompt_hash: str = "", ttl: int = DEFAULT_LLM_TTL) -> None:
    """写缓存（内存 + 表）。"""
    _mem_set(key, response, ttl)
    try:
        from utils.db import SessionLocal
        from models.models import LLMCache
        with SessionLocal() as session:
            row = session.query(LLMCache).filter(
                LLMCache.cache_key == key).first()
            expires = datetime.now() + timedelta(seconds=ttl)
            if row is None:
                session.add(LLMCache(
                    cache_key=key, prompt_hash=prompt_hash or "",
                    model_name=model or "", response=response,
                    created_at=datetime.now(), expires_at=expires,
                    hit_count=0))
            else:
                row.response = response
                row.expires_at = expires
            session.commit()
    except Exception:  # noqa: BLE001 —— 缓存失败不影响主流程
        pass


def cache_stats() -> dict:
    """缓存统计：条目数、命中总数、命中率（按 hit_count / (hit+miss) 近似）。"""
    total, hits = 0, 0
    try:
        from utils.db import SessionLocal
        from models.models import LLMCache
        with SessionLocal() as session:
            rows = session.query(LLMCache).all()
            total = len(rows)
            hits = sum(int(r.hit_count or 0) for r in rows)
    except Exception:  # noqa: BLE001
        pass
    with _lock:
        mem = len(_llm_mem)
    return {"entries": total, "hits": hits, "memory_entries": mem}


def clear_llm_cache() -> int:
    """清空 LLM 缓存，返回删除条数。"""
    with _lock:
        _llm_mem.clear()
    removed = 0
    try:
        from utils.db import SessionLocal
        from models.models import LLMCache
        with SessionLocal() as session:
            removed = session.query(LLMCache).delete()
            session.commit()
    except Exception:  # noqa: BLE001
        removed = 0
    return int(removed or 0)


def purge_expired() -> int:
    """清理过期缓存条目。"""
    removed = 0
    try:
        from utils.db import SessionLocal
        from models.models import LLMCache
        with SessionLocal() as session:
            removed = (session.query(LLMCache)
                       .filter(LLMCache.expires_at < datetime.now())
                       .delete())
            session.commit()
    except Exception:  # noqa: BLE001
        removed = 0
    return int(removed or 0)


# ---------------------------------------------------------------------------
# 查询缓存（内存 tag + TTL）
# ---------------------------------------------------------------------------

def cached_query(tag: str, name: str, fn, ttl: int = SHORT_TTL):
    """按 (tag, name) 缓存 fn() 的结果；命中直接返回。"""
    key = (str(tag), str(name))
    now = time.time()
    hit = _query_mem.get(key)
    if hit is not None and hit[1] > now:
        return hit[0]
    value = fn()
    _query_mem[key] = (value, now + ttl)
    return value


def invalidate(tag: str) -> int:
    """按 tag 清缓存，返回清理条数（数据变更后调用）。"""
    removed = 0
    for key in list(_query_mem):
        if key[0] == str(tag):
            _query_mem.pop(key, None)
            removed += 1
    return removed


def clear_query_cache() -> int:
    n = len(_query_mem)
    _query_mem.clear()
    return n


# ---------------------------------------------------------------------------
# 文件解析缓存
# ---------------------------------------------------------------------------

def file_signature(name: str, data: bytes) -> str:
    """文件名 + 大小 + 内容哈希，作为解析缓存键。"""
    digest = hashlib.sha256(data or b"").hexdigest()
    return hashlib.sha256(
        f"{name}:{len(data or b'')}:{digest}".encode("utf-8")).hexdigest()


def get_file_cache(signature: str):
    return _file_mem.get(signature)


def set_file_cache(signature: str, value) -> None:
    if len(_file_mem) > _MEM_MAX:
        _file_mem.clear()
    _file_mem[signature] = value
