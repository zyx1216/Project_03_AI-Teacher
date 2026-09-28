# -*- coding: utf-8 -*-
"""文本课堂实录服务（v2.1.0）。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
import uuid

import config

RECORDING_PATH = Path(config.DATA_DIR) / "class_records.json"

_DEFAULT = {"records": []}


def load_recordings() -> dict:
    """读取课堂实录；文件缺失或损坏时返回默认结构。"""
    if not RECORDING_PATH.exists():
        return {"records": []}
    try:
        with open(RECORDING_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"records": []}
    if not isinstance(data, dict) or not isinstance(data.get("records"), list):
        return {"records": []}
    return data


def summarize_transcript(transcript, context=None) -> dict:
    """根据文本逐字稿生成结构化课堂纪要。"""
    text = str(transcript or "").strip()
    if not text:
        raise ValueError("请先填写课堂逐字稿。")
    system = (
        "你是课堂教学分析助手。只输出 JSON："
        "{\"summary\":\"课堂摘要\",\"key_points\":[\"重点知识\"],"
        "\"interaction\":\"学生互动情况\",\"highlights\":[\"课堂亮点\"],"
        "\"problems\":[\"问题\"],\"suggestions\":[\"后续建议\"]}。")
    user = f"背景：{context or '未提供'}\n逐字稿：{text[:12000]}"
    try:
        from utils import llm_client
        data = json.loads(llm_client.chat_content(system, user, 0.2))
        return _normalize_summary(data)
    except Exception:
        sentences = [item.strip() for item in text.replace("？", "。").split("。")
                     if item.strip()]
        return {
            "summary": "；".join(sentences[:2]) or "已记录课堂内容。",
            "key_points": ["AI 不可用，请从逐字稿中人工提炼重点。"],
            "interaction": "未能自动分析。",
            "highlights": [],
            "problems": [],
            "suggestions": ["请教师查看原始逐字稿。"],
            "ai_available": False,
        }


def _normalize_summary(data) -> dict:
    if not isinstance(data, dict):
        raise ValueError("课堂纪要格式不正确。")
    def as_list(key):
        value = data.get(key) or []
        if isinstance(value, str):
            value = [value]
        return [str(item).strip() for item in value if str(item).strip()]
    return {
        "summary": str(data.get("summary", "")).strip(),
        "key_points": as_list("key_points"),
        "interaction": str(data.get("interaction", "")).strip(),
        "highlights": as_list("highlights"),
        "problems": as_list("problems"),
        "suggestions": as_list("suggestions"),
        "ai_available": True,
    }


def save_recording(data) -> dict:
    """保存一条课堂实录和纪要。"""
    payload = dict(data or {})
    record_id = payload.pop("id", None) or str(uuid.uuid4())[:8]
    record = {
        "id": record_id,
        "title": str(payload.get("title", "未命名课堂")).strip(),
        "transcript": str(payload.get("transcript", "")).strip(),
        "summary": payload.get("summary", {}),
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    store = load_recordings()
    store["records"] = [item for item in store["records"]
                        if item.get("id") != record_id]
    store["records"].insert(0, record)
    RECORDING_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RECORDING_PATH, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)
    return record


def delete_recording(recording_id) -> None:
    """删除指定课堂实录。"""
    store = load_recordings()
    store["records"] = [item for item in store["records"]
                        if item.get("id") != str(recording_id)]
    with open(RECORDING_PATH, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)
