# -*- coding: utf-8 -*-
"""Agent 长期记忆：教师稳定偏好的读写。"""

from __future__ import annotations

import re
from datetime import datetime

from models.models import AgentMemory

PREFERENCE_TYPE = "preference"

# 只有允许列表里的偏好可自动影响业务参数；其它偏好仅供回答组织参考。
ALLOWED_AUTO_KEYS = {
    "default_difficulty": "默认难度",
    "lesson_style": "教案风格",
    "homework_style": "作业风格",
    "default_question_count": "默认题量",
    "common_question_types": "常用题型",
    "confirm_high_risk": "高风险操作是否再次确认",
}

SENSITIVE_WORDS = ("密码", "口令", "token", "api key", "apikey", "密钥",
                   "secret", "凭据", "private key", "私钥")


def _now() -> datetime:
    return datetime.now()


def remember_preference(session, key, value, category="general",
                        importance=5) -> AgentMemory:
    """新增或更新偏好。同一 (type,key,category) 更新值并增加使用次数。"""
    memory_key = str(key or "").strip()
    if not memory_key:
        raise ValueError("记忆键不能为空。")
    if value is None or str(value).strip() == "":
        raise ValueError("记忆内容不能为空。")
    category = str(category or "general").strip()
    importance = min(10, max(1, int(importance)))
    row = (session.query(AgentMemory)
           .filter(AgentMemory.memory_type == PREFERENCE_TYPE,
                   AgentMemory.key == memory_key,
                   AgentMemory.category == category).first())
    now = _now()
    if row is None:
        row = AgentMemory(
            memory_type=PREFERENCE_TYPE, key=memory_key,
            value=str(value), category=category, importance=importance,
            created_at=now, last_used_at=now, use_count=0)
        session.add(row)
    else:
        row.value = str(value)
        row.importance = importance
        row.last_used_at = now
        row.use_count = (row.use_count or 0) + 1
    session.flush()
    return row


def recall_preference(session, key, category=None):
    """回忆一个偏好；找到时刷新最近使用时间。"""
    memory_key = str(key or "").strip()
    q = session.query(AgentMemory).filter(
        AgentMemory.memory_type == PREFERENCE_TYPE,
        AgentMemory.key == memory_key)
    if category:
        q = q.filter(AgentMemory.category == str(category))
    row = q.order_by(AgentMemory.importance.desc(), AgentMemory.id.desc()).first()
    if row is None:
        return None
    row.last_used_at = _now()
    row.use_count = (row.use_count or 0) + 1
    session.flush()
    return row


def forget_preference(session, key, category=None) -> int:
    """删除一个或同 key 的多个偏好，返回删除数。"""
    q = session.query(AgentMemory).filter(
        AgentMemory.memory_type == PREFERENCE_TYPE,
        AgentMemory.key == str(key or "").strip())
    if category:
        q = q.filter(AgentMemory.category == str(category))
    rows = q.all()
    for row in rows:
        session.delete(row)
    session.flush()
    return len(rows)


def get_all_preferences(session, category=None) -> list[AgentMemory]:
    """按分类列出偏好，按重要性和最近使用时间排序。"""
    q = session.query(AgentMemory).filter(
        AgentMemory.memory_type == PREFERENCE_TYPE)
    if category:
        q = q.filter(AgentMemory.category == category)
    return q.order_by(AgentMemory.importance.desc(),
                      AgentMemory.last_used_at.desc(),
                      AgentMemory.id.desc()).all()


def preference_to_dict(row: AgentMemory) -> dict:
    return {
        "id": row.id, "key": row.key, "value": row.value,
        "category": row.category, "importance": row.importance,
        "use_count": row.use_count or 0,
        "last_used_at": row.last_used_at.strftime("%Y-%m-%d %H:%M:%S"),
        "auto_applied": row.key in ALLOWED_AUTO_KEYS,
    }


def auto_applied_preferences(session) -> dict:
    """读取允许自动生效的偏好。"""
    result = {}
    for row in get_all_preferences(session):
        if row.key in ALLOWED_AUTO_KEYS:
            result[row.key] = row.value
    return result


def _is_sensitive(text: str) -> bool:
    lower = str(text).lower()
    return any(word in lower for word in SENSITIVE_WORDS)


def auto_extract_preferences(session, conversation_history) -> list[AgentMemory]:
    """从对话中提取明确稳定偏好；敏感内容不保存。

    输入形如 [{"role":"user","content":"以后教案都写得简洁一点"}]。
    """
    patterns = {
        "default_difficulty": r"(?:以后|默认|一般).{0,6}(难度|题目).{0,8}(基础|简单|中等|拓展|难)",
        "lesson_style": r"教案.{0,8}(?:风格|写得|要)(.{0,12}?)(?:一点|风格)?",
        "default_question_count": r"(?:每次|默认|一般).{0,8}(?:出|出卷|题目|题量).{0,4}(\d+)\s*道?",
    }
    saved = []
    for message in conversation_history or []:
        content = str(message.get("content") if isinstance(message, dict)
                      else message)
        if _is_sensitive(content):
            continue
        if not re.search(r"以后|默认|每次|我喜欢|我习惯|不要再", content):
            continue
        for key, pattern in patterns.items():
            match = re.search(pattern, content)
            if match:
                value = match.group(1)
                if _is_sensitive(value):
                    continue
                saved.append(remember_preference(
                    session, key, value, category="auto", importance=6))
    return saved


# ---------------------------------------------------------------------------
# v2.6.0：教师风格学习与个性化推荐
# ---------------------------------------------------------------------------

# 允许记录/推荐的风格信号类型
STYLE_KINDS = {"subject", "grade", "lesson_style", "difficulty",
               "method", "edit_field", "add_content", "del_content"}

# 偏好面板对应的记忆 key（允许列表，供自动应用）
PREFERENCE_KEYS = {
    "lesson_style": "教案风格",
    "difficulty_pref": "题目难度偏好",
    "proactivity": "AI主动性",
    "method_pref": "教学方法偏好",
}


def record_style_signal(session, kind: str, payload: str,
                        weight: int = 1) -> None:
    """记录一次教师风格信号（使用习惯/修改行为）。

    同 key 累加使用次数，便于统计“常用”与“常改”。
    kind 不在允许列表时忽略（避免记录任意文本）。
    """
    kind = str(kind or "").strip()
    payload = str(payload or "").strip()
    if kind not in STYLE_KINDS or not payload:
        return
    key = f"{kind}:{payload}"
    existing = (session.query(AgentMemory)
                .filter(AgentMemory.memory_type == "style",
                        AgentMemory.key == key).first())
    if existing is not None:
        existing.value = str(int(existing.value or 0) + int(weight or 1))
        existing.use_count = int(existing.use_count or 0) + 1
        existing.last_used_at = _now()
    else:
        session.add(AgentMemory(
            memory_type="style", key=key, value=str(int(weight or 1)),
            category="style", importance=3, created_at=_now(),
            last_used_at=_now(), use_count=1))
    session.flush()


def top_style_signals(session, kind: str, n: int = 3) -> list[dict]:
    """取某类信号里次数最高的前 n 条。"""
    rows = (session.query(AgentMemory)
            .filter(AgentMemory.memory_type == "style",
                    AgentMemory.key.like(f"{kind}:%"))
            .order_by(AgentMemory.value.desc()).limit(n).all())
    out = []
    for r in rows:
        label = str(r.key).split(":", 1)[1] if ":" in str(r.key) else str(r.key)
        out.append({"value": label, "count": int(r.value or 0)})
    return out


def recommend_for(session, kind: str) -> dict:
    """按历史信号给出个性化推荐。

    kind: lesson_template / question_type / next_content / teaching_focus。
    返回 {"recommendation": str, "source": "history|default", "evidence": [...]}。
    """
    if kind == "lesson_template":
        sig = top_style_signals(session, "lesson_style", 1)
        if sig:
            return {"recommendation": sig[0]["value"], "source": "history",
                    "evidence": sig}
        return {"recommendation": "标准", "source": "default", "evidence": []}
    if kind == "question_type":
        sig = top_style_signals(session, "difficulty", 1)
        if sig:
            return {"recommendation": sig[0]["value"], "source": "history",
                    "evidence": sig}
        return {"recommendation": "中等", "source": "default", "evidence": []}
    if kind == "next_content":
        sig = top_style_signals(session, "subject", 1)
        rec = sig[0]["value"] if sig else "数学"
        return {"recommendation": rec, "source": "history" if sig else "default",
                "evidence": sig}
    if kind == "teaching_focus":
        sig = top_style_signals(session, "edit_field", 3)
        names = [s["value"] for s in sig]
        return {"recommendation": "、".join(names) if names else "重点环节",
                "source": "history" if names else "default", "evidence": sig}
    return {"recommendation": "", "source": "default", "evidence": []}


def save_ai_preferences(session, lesson_style: str = None,
                        difficulty_pref: str = None, proactivity: str = None,
                        method_pref: str = None) -> list[dict]:
    """保存 AI 偏好设置（写入允许列表 key，供生成类功能自动应用）。"""
    import json as _json
    pairs = [("lesson_style", lesson_style),
             ("difficulty_pref", difficulty_pref),
             ("proactivity", proactivity),
             ("method_pref", method_pref)]
    saved = []
    for key, value in pairs:
        if value is None:
            continue
        val = _json.dumps(value, ensure_ascii=False)
        remember_preference(session, key, val, category="ai_preference",
                            importance=8)
        saved.append({"key": key, "label": PREFERENCE_KEYS[key], "value": value})
    return saved


def load_ai_preferences(session) -> dict:
    """读取 AI 偏好设置（返回原始值，未设置则 None）。"""
    import json as _json
    out = {}
    for key, label in PREFERENCE_KEYS.items():
        row = recall_preference(session, key, category="ai_preference")
        if row is None:
            out[key] = None
            continue
        try:
            out[key] = _json.loads(row.value)
        except (ValueError, TypeError):
            out[key] = row.value
    return out
