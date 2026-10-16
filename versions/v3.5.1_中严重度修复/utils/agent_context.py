# -*- coding: utf-8 -*-
"""AI 助手上下文记忆服务。

上下文落 data/agent_context.json，用来记住老师当前教学范围。
注意：年级字段保存界面口径，如“高一/初二/三年级”。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import config
from utils.app_config import (
    DISPLAY_GRADE_CHOICES, SUBJECT_NAMES, is_valid_subject,
)

AGENT_CONTEXT_PATH = config.DATA_DIR / "agent_context.json"
CONTEXT_TTL_DAYS = 30

_FIELDS = (
    "subject", "grade", "class_name", "current_chapter",
    "last_action", "last_action_params", "updated_at",
)


def empty_context() -> dict:
    """返回空上下文结构。"""
    return {
        "subject": "",
        "grade": "",
        "class_name": "",
        "current_chapter": "",
        "last_action": "",
        "last_action_params": {},
        "updated_at": "",
    }


def load_context() -> dict:
    """加载上下文；文件缺失或损坏时回退空上下文，且不覆盖原文件。"""
    path = AGENT_CONTEXT_PATH
    if not path.exists():
        return empty_context()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return empty_context()
    if not isinstance(data, dict):
        return empty_context()
    context = empty_context()
    context.update({k: data.get(k) for k in _FIELDS if k in data})
    if context.get("last_action_params") is None or not isinstance(
            context["last_action_params"], dict):
        context["last_action_params"] = {}
    updated_at = str(context.get("updated_at") or "")
    if updated_at and _is_expired(updated_at):
        return empty_context()
    return _sanitize(context, strict=False)


def save_context(context: dict) -> None:
    """保存合法上下文；文件不存在时自动创建。"""
    clean = _sanitize(context, strict=False)
    clean["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    AGENT_CONTEXT_PATH.parent.mkdir(parents=True, exist_ok=True)
    AGENT_CONTEXT_PATH.write_text(
        json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")


def update_context(**kwargs) -> dict:
    """按非空字段更新上下文，返回保存后的完整上下文。"""
    current = load_context()
    patch = {key: kwargs[key] for key in _FIELDS if key in kwargs}
    current.update(patch)
    save_context(current)
    return load_context()


def clear_context() -> dict:
    """清空上下文，并返回空结构。"""
    try:
        AGENT_CONTEXT_PATH.write_text(
            json.dumps(empty_context(), ensure_ascii=False, indent=2),
            encoding="utf-8")
    except OSError:
        pass
    return empty_context()


def fill_intent_params(raw_params: dict, context: dict | None = None) -> dict:
    """用上下文补全意图参数中缺失的字段，不覆盖用户明确给出的值。"""
    context = context or load_context()
    params = dict(raw_params or {})

    def missing(key):
        value = params.get(key)
        if value is None:
            return True
        if isinstance(value, str):
            return not value.strip()
        if isinstance(value, (list, tuple, dict, set)):
            return not value
        return False

    for key in ("subject", "grade", "class_name", "current_chapter"):
        if missing(key) and context.get(key):
            params[key] = context[key]
    if missing("chapter") and context.get("current_chapter"):
        params["chapter"] = context["current_chapter"]
    if missing("knowledge_points") and context.get("current_chapter"):
        # 章节不是知识点，只补章节，不臆造知识点。
        pass
    return params


def extract_context_from_instruction(text: str) -> dict:
    """从“教高二物理、高一1班”这类指令中提取明确上下文。

    这里不用 LLM，避免一次简单记忆操作额外消耗请求。
    """
    content = str(text or "")
    patch = {}

    # 学科优先按完整名称匹配，避免“物理科”漏识别。
    for subject in SUBJECT_NAMES:
        if subject in content:
            patch["subject"] = subject
            break

    grade = _detect_grade(content)
    if grade:
        patch["grade"] = grade

    class_name = _detect_class_name(content)
    if class_name:
        patch["class_name"] = class_name

    chapter = _detect_chapter(content)
    if chapter:
        patch["current_chapter"] = chapter

    return patch


def remember_execution(action: str, params: dict) -> dict:
    """执行业务后记录最近操作和当前教学范围。"""
    params = params or {}
    patch = {"last_action": action, "last_action_params": _jsonable(params)}
    for source, target in (
        ("subject", "subject"),
        ("grade", "grade"),
        ("class_name", "class_name"),
        ("chapter", "current_chapter"),
    ):
        value = params.get(source)
        if value not in (None, ""):
            patch[target] = value
    return update_context(**patch)


def context_label(context: dict | None = None) -> str:
    """生成侧边栏上下文短标签。"""
    context = context or load_context()
    parts = [context.get("subject"), context.get("grade"), context.get("class_name")]
    parts = [str(x).strip() for x in parts if str(x or "").strip()]
    return "·".join(parts) if parts else "未设置教学上下文"


def _sanitize(context: dict, strict: bool = False) -> dict:
    """清理非法上下文字段；strict 用于阻断含空必填值的保存。"""
    clean = empty_context()
    subject = str(context.get("subject") or "").strip()
    grade = str(context.get("grade") or "").strip()
    class_name = str(context.get("class_name") or "").strip()
    chapter = str(context.get("current_chapter") or "").strip()
    last_action = str(context.get("last_action") or "").strip()

    if is_valid_subject(subject):
        clean["subject"] = subject
    elif strict:
        raise ValueError("上下文学科不合法。")

    if grade in DISPLAY_GRADE_CHOICES or (grade and grade in DISPLAY_GRADE_CHOICES):
        clean["grade"] = grade
    elif grade and grade not in DISPLAY_GRADE_CHOICES and strict:
        raise ValueError("上下文年级不合法。")

    clean["class_name"] = class_name
    clean["current_chapter"] = chapter
    clean["last_action"] = last_action
    clean["last_action_params"] = _jsonable(context.get("last_action_params") or {})
    clean["updated_at"] = str(context.get("updated_at") or "").strip()
    return clean


def _detect_grade(text: str) -> str:
    """识别界面年级。"""
    for grade in DISPLAY_GRADE_CHOICES:
        if grade in text:
            return grade
    compact = {
        "高一": "高一", "高二": "高二", "高三": "高三",
        "初一": "初一", "初二": "初二", "初三": "初三",
    }
    for key, value in compact.items():
        if key in text:
            return value
    return ""


def _detect_class_name(text: str) -> str:
    """提取常见班级名，如“高一1班/初二（3）班”。"""
    patterns = [
        r"([\u4e00-\u9fa5]{1,3}\d{1,2}班)",
        r"([\u4e00-\u9fa5]{1,3}[（(]\d{1,2}[）)]班)",
        r"(\d{1,2}班)",
    ]
    import re
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).replace("(", "（").replace(")", "）")
    return ""


def _detect_chapter(text: str) -> str:
    """识别“第X章/单元”的章节范围。"""
    import re
    patterns = [
        r"第[一二三四五六七八九十百\d]+章[^\s，。；;]*",
        r"第[一二三四五六七八九十百\d]+单元[^\s，。；;]*",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(0).strip()
    return ""


def _is_expired(updated_at: str) -> bool:
    """判断上下文是否超过保留期。"""
    try:
        updated = datetime.strptime(updated_at, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return False
    return datetime.now() - updated > timedelta(days=CONTEXT_TTL_DAYS)


def _jsonable(value):
    """把参数转成 JSON 安全结构，防止 datetime 写入失败。"""
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (datetime, )):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if hasattr(value, "isoformat") and call_back(value):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    return value


def call_back(value):
    """简单日期对象判断，避免直接导入过多类型。"""
    return hasattr(value, "year") and hasattr(value, "month") and hasattr(value, "day")
