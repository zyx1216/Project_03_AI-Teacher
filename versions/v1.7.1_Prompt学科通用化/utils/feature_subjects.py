# -*- coding: utf-8 -*-
"""各功能独立的学科选择状态。

和 v1.2 的全局 current_subject 不同，这里每个页面功能一个 key，互不影响。
状态文件位于 data/feature_subjects.json，data 目录不入库；测试可 monkeypatch
FEATURE_SUBJECTS_PATH 指向临时文件。
"""

from __future__ import annotations

import json
from typing import Any

import config
from utils.app_config import DEFAULT_SUBJECT, SUBJECT_NAMES, is_valid_subject

FEATURE_SUBJECTS_PATH = config.DATA_DIR / "feature_subjects.json"

MATERIALS_SUBJECT = "materials_subject"
LESSON_PLAN_SUBJECT = "lesson_plan_subject"
QUESTION_GEN_SUBJECT = "question_gen_subject"
QUESTION_BANK_SUBJECT = "question_bank_subject"
PPT_SUBJECT = "ppt_subject"
HOMEWORK_LIST_SUBJECT = "homework_list_subject"
HOMEWORK_NEW_SUBJECT = "homework_new_subject"
WRONG_BOOK_SUBJECT = "wrong_book_subject"

FEATURE_KEYS = [
    MATERIALS_SUBJECT,
    LESSON_PLAN_SUBJECT,
    QUESTION_GEN_SUBJECT,
    QUESTION_BANK_SUBJECT,
    PPT_SUBJECT,
    HOMEWORK_LIST_SUBJECT,
    HOMEWORK_NEW_SUBJECT,
    WRONG_BOOK_SUBJECT,
]


def default_states() -> dict[str, str]:
    """所有功能默认数学。"""
    return {key: DEFAULT_SUBJECT for key in FEATURE_KEYS}


def _normalize(data: Any) -> dict[str, str]:
    states = default_states()
    if isinstance(data, dict):
        for key in FEATURE_KEYS:
            value = data.get(key)
            if is_valid_subject(value):
                states[key] = value
    return states


def load_feature_subjects() -> dict[str, str]:
    """读取功能学科；文件缺失时创建，损坏时回退默认且不覆盖原文件。"""
    try:
        raw = FEATURE_SUBJECTS_PATH.read_text(encoding="utf-8")
        return _normalize(json.loads(raw))
    except FileNotFoundError:
        states = default_states()
        save_feature_subjects(states)
        return states
    except (json.JSONDecodeError, OSError, TypeError, AttributeError):
        return default_states()


def save_feature_subjects(states: dict[str, str]) -> None:
    """保存完整功能学科状态，遇到非法值直接报错。"""
    normalized = _normalize(states)
    for key, value in states.items():
        if key in FEATURE_KEYS and not is_valid_subject(value):
            raise ValueError(f"不支持的学科：{value}")
    FEATURE_SUBJECTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    FEATURE_SUBJECTS_PATH.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")


def get_feature_subject(key: str) -> str:
    """读取某个功能的学科；未知 key 按数学处理。"""
    if key not in FEATURE_KEYS:
        return DEFAULT_SUBJECT
    return load_feature_subjects().get(key, DEFAULT_SUBJECT)


def set_feature_subject(key: str, subject: str) -> None:
    """只更新某个功能的学科，不影响其他功能。"""
    if key not in FEATURE_KEYS:
        raise ValueError(f"未知的功能学科 key：{key}")
    if not is_valid_subject(subject):
        raise ValueError(f"不支持的学科：{subject}")
    states = load_feature_subjects()
    states[key] = subject
    save_feature_subjects(states)
