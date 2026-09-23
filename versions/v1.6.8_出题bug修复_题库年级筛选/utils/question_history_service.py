# -*- coding: utf-8 -*-
"""AI 出题历史：保存、读取、50 条上限和配置回填。"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path

import config

HISTORY_PATH = config.DATA_DIR / "question_generation_history.json"
MAX_HISTORY = 50

_LOCK = threading.RLock()
_CORRUPT = False
_MEMORY: dict = {}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _load() -> dict:
    """文件缺失自动建空结构；损坏文件只回退内存状态且不覆盖。"""
    global _CORRUPT
    if _CORRUPT:
        return dict(_MEMORY)
    try:
        data = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"items": []}
    except FileNotFoundError:
        return {"items": []}
    except (json.JSONDecodeError, OSError):
        _CORRUPT = True
        return dict(_MEMORY)


def _write(data: dict) -> None:
    """UTF-8、中文不转义，自动保留最近 50 条。"""
    global _CORRUPT
    items = [item for item in data.get("items", []) if isinstance(item, dict)]
    items = items[-MAX_HISTORY:]
    data = {"items": items}
    if _CORRUPT:
        _MEMORY.clear()
        _MEMORY.update(data)
        return
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                            encoding="utf-8")


def list_history() -> list[dict]:
    """按时间正序返回历史记录。"""
    with _LOCK:
        return list(_load().get("items", []))


def add_history(config_data: dict, success_count: int,
                failure_count: int = 0, question_snapshot: list | None = None) -> dict:
    """追加一条出题历史。

    question_snapshot：当次生成题目的快照（题型/难度/题干/答案），
    供历史“查看题目”；不传则该历史不保存题目正文。
    """
    item = {
        "id": uuid_id(),
        "grade": config_data.get("grade", ""),
        "subjects": list(config_data.get("subjects", [])),
        "config": dict(config_data),
        "success_count": int(success_count),
        "failure_count": int(failure_count),
        "created_at": _now(),
    }
    snapshot = []
    for q in question_snapshot or []:
        if not isinstance(q, dict):
            continue
        snapshot.append({
            "subject": q.get("subject", ""),
            "question_type": q.get("question_type", ""),
            "difficulty": q.get("difficulty", 2),
            "content": q.get("content", ""),
            "answer": q.get("answer", ""),
        })
    if snapshot:
        item["question_snapshot"] = snapshot
    with _LOCK:
        data = _load()
        items = list(data.get("items", []))
        items.append(item)
        _write({"items": items})
    return item


def get_history(history_id: str) -> dict | None:
    """读取单条历史。"""
    for item in list_history():
        if item.get("id") == str(history_id):
            return dict(item)
    return None


def restore_config(history_id: str) -> dict:
    """把历史出题配置带回页面，不自动调用模型。"""
    item = get_history(history_id)
    if item is None:
        raise ValueError("出题历史不存在。")
    return dict(item.get("config") or {})


def uuid_id() -> str:
    import uuid
    return uuid.uuid4().hex
