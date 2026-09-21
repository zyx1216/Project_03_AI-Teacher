# -*- coding: utf-8 -*-
"""学科、年级常量与校验。

v1.3.0 起不再保存“全局当前学科”；各功能自己的选择由 feature_subjects 管理。
"""

from __future__ import annotations

from typing import Any

DEFAULT_SUBJECT = "数学"

SUBJECT_NAMES = ALL_SUBJECTS = [
    "语文", "数学", "英语", "物理", "化学", "生物", "政治", "历史", "地理",
]

GRADE_NAMES = [f"{n}年级" for n in ("一", "二", "三", "四", "五", "六", "七", "八", "九")]
GRADE_CHOICES = GRADE_NAMES + ["未指定"]
DEFAULT_GRADE = "八年级"


def is_valid_subject(subject: Any) -> bool:
    """判断学科是否受支持。"""
    return isinstance(subject, str) and subject in SUBJECT_NAMES


def is_valid_grade(grade: Any) -> bool:
    """判断年级是否受支持；“未指定”也是合法选项。"""
    return isinstance(grade, str) and grade in GRADE_CHOICES
