# -*- coding: utf-8 -*-
"""对话式备课服务（v2.6.0）。

- 会话历史保存到 data/lesson_chat.json（缺失自建、损坏回退且不覆盖原文件）；
- 主动澄清最多 3 问，教师可跳过；
- 反馈迭代优化教案（失败给中文原因，不吞异常）。
"""

from __future__ import annotations

import json
from datetime import datetime

import config

_EMPTY = {"sessions": [], "current_id": ""}


def _path():
    return config.DATA_DIR / "lesson_chat.json"


def load_store() -> dict:
    """读取对话存储；文件缺失自建、损坏回退默认且不覆盖原文件。"""
    path = _path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return dict(_EMPTY)
    if not path.exists():
        try:
            path.write_text(json.dumps(_EMPTY, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        except OSError:
            pass
        return dict(_EMPTY)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise TypeError("结构非法")
        data.setdefault("sessions", [])
        data.setdefault("current_id", "")
        return data
    except (json.JSONDecodeError, OSError, TypeError, AttributeError):
        # 损坏：回退默认，但不覆盖用户原文件
        return dict(_EMPTY)


def save_store(data: dict) -> None:
    """写回对话存储。"""
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def new_session(title: str = "") -> dict:
    """新建一个备课对话会话并设为当前。"""
    data = load_store()
    sid = datetime.now().strftime("%Y%m%d%H%M%S%f")
    session = {"session_id": sid,
               "title": title or f"备课对话 {datetime.now():%m-%d %H:%M}",
               "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
               "messages": []}
    data["sessions"] = ([session] + list(data.get("sessions") or []))[:20]
    data["current_id"] = sid
    save_store(data)
    return session


def get_session(session_id: str) -> dict | None:
    for item in load_store().get("sessions") or []:
        if item.get("session_id") == session_id:
            return item
    return None


def append_message(session_id: str, role: str, content: str,
                   meta: dict | None = None) -> dict | None:
    """给会话追加一条消息（role: user/assistant）。"""
    data = load_store()
    for item in data.get("sessions") or []:
        if item.get("session_id") == session_id:
            item.setdefault("messages", []).append({
                "role": role, "content": str(content or ""),
                "meta": meta or {},
                "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
            save_store(data)
            return item
    return None


def last_session() -> dict | None:
    """取最近一次会话（用于“继续上次的备课对话”）。"""
    sessions = load_store().get("sessions") or []
    return sessions[0] if sessions else None


def build_clarify_questions(context: dict, max_n: int = 3) -> list[dict]:
    """根据缺失信息生成主动澄清问题，最多 max_n 个。

    返回 [{"field","question","default"}]；信息齐全时返回空列表。
    """
    context = context or {}
    questions = []
    if not str(context.get("grade") or "").strip():
        questions.append({"field": "grade", "question": "请问是哪个年级的？",
                          "default": "初一"})
    if not str(context.get("subject") or "").strip():
        questions.append({"field": "subject", "question": "是哪一门学科？",
                          "default": "数学"})
    if not str(context.get("chapter") or "").strip():
        questions.append({"field": "chapter", "question": "这节课讲哪个章节/知识点？",
                          "default": "第一章"})
    if not context.get("hours"):
        questions.append({"field": "hours", "question": "这节课需要多长时间（课时）？",
                          "default": 1})
    if "include_practice" not in context:
        questions.append({"field": "include_practice",
                          "question": "需要包含课堂练习吗？", "default": True})
    return questions[:max(0, int(max_n))]


def apply_feedback(plan: dict, feedback: str, chat_func=None) -> dict:
    """按教师反馈迭代优化教案。

    返回 {"plan": 新教案, "changed": bool, "reason": str}。
    chat_func 缺省走 llm_client；失败返回原教案并给中文原因。
    """
    feedback = str(feedback or "").strip()
    if not feedback:
        return {"plan": plan, "changed": False, "reason": "反馈为空，未做修改。"}
    system = (
        "你是资深教研助手。根据教师反馈修改教案 JSON，保持原有结构："
        "title, objectives, key_points, difficulties, process, board_design, homework。"
        "只输出修改后的完整 JSON，不要解释。")
    user = (f"当前教案：{json.dumps(plan, ensure_ascii=False)}\n"
            f"教师反馈：{feedback}")
    try:
        if chat_func is None:
            from utils import llm_client
            raw = llm_client.chat_content(system, user)
        else:
            raw = chat_func(system, user)
        text = str(raw).strip()
        if text.startswith("```"):
            text = text.strip("`")
            text = text.split("\n", 1)[1] if "\n" in text else text
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("返回不是 JSON 对象")
        return {"plan": data, "changed": True, "reason": "已按反馈优化。"}
    except Exception as exc:  # noqa: BLE001 —— 失败给中文原因，不吞异常类型
        return {"plan": plan, "changed": False,
                "reason": f"AI 优化失败：{exc}"}
