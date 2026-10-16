# -*- coding: utf-8 -*-
"""性能监控（v2.8.0）。

记录页面加载 / API / LLM / DB 查询耗时（内存环形缓冲），提供 P50/P95 聚合。
纯标准库，不落库、不引入依赖。
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from contextlib import contextmanager

_MAX_SAMPLES = 500
_lock = threading.Lock()
_samples: dict[str, deque] = defaultdict(lambda: deque(maxlen=_MAX_SAMPLES))
_counters: dict[str, int] = defaultdict(int)

KINDS = ("page", "api", "llm", "db")


def record_metric(kind: str, name: str, elapsed_ms: float) -> None:
    """记录一次耗时（毫秒）。"""
    key = f"{kind}:{name}"
    with _lock:
        _samples[key].append(float(elapsed_ms))
        _counters[key] += 1


@contextmanager
def track(kind: str, name: str):
    """with track("llm", "chat_content"): ... 自动记录耗时。"""
    start = time.perf_counter()
    try:
        yield
    finally:
        record_metric(kind, name, (time.perf_counter() - start) * 1000)


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round((pct / 100.0) * (len(ordered) - 1))))
    return round(ordered[idx], 1)


def stats(kind: str | None = None) -> list[dict]:
    """返回各指标 {kind,name,count,p50,p95,max}，可按 kind 过滤。"""
    out = []
    with _lock:
        for key, values in _samples.items():
            k, _, name = key.partition(":")
            if kind and k != kind:
                continue
            vals = list(values)
            out.append({"kind": k, "name": name, "count": _counters.get(key, 0),
                        "p50": _percentile(vals, 50),
                        "p95": _percentile(vals, 95),
                        "max": round(max(vals), 1) if vals else 0.0})
    out.sort(key=lambda r: r["p95"], reverse=True)
    return out


def summary() -> dict:
    """按 kind 汇总的概览。"""
    result = {}
    for row in stats():
        bucket = result.setdefault(row["kind"], {"count": 0, "p95": 0.0})
        bucket["count"] += row["count"]
        bucket["p95"] = max(bucket["p95"], row["p95"])
    return result


def reset() -> None:
    """清空监控数据。"""
    with _lock:
        _samples.clear()
        _counters.clear()


def memory_usage_mb() -> float:
    """当前进程内存占用（MB）；取不到返回 0。"""
    try:
        import os
        import resource  # noqa: F401 —— Unix
        return 0.0
    except Exception:  # noqa: BLE001
        pass
    try:
        import os
        import ctypes
        class _PMC(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_ulong),
                        ("PageFaultCount", ctypes.c_ulong),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t)]
        pmc = _PMC()
        pmc.cb = ctypes.sizeof(_PMC)
        if ctypes.windll.psapi.GetProcessMemoryInfo(
                ctypes.windll.kernel32.GetCurrentProcess(),
                ctypes.byref(pmc), pmc.cb):
            return round(pmc.WorkingSetSize / (1024 * 1024), 1)
    except Exception:  # noqa: BLE001
        pass
    return 0.0
