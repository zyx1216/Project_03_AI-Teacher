# -*- coding: utf-8 -*-
"""学科、年级常量与校验。

v1.3.0 起不再保存“全局当前学科”；各功能自己的选择由 feature_subjects 管理。
v1.6.3 起初中年级在界面统一显示为“初一/初二/初三”，数据库仍存“七/八/九年级”，
由本模块的双向映射函数负责转换，不批量改库。
"""

from __future__ import annotations

from typing import Any

DEFAULT_SUBJECT = "数学"

SUBJECT_NAMES = ALL_SUBJECTS = [
    "语文", "数学", "英语", "物理", "化学", "生物", "政治", "历史", "地理",
]

# 数据库存储口径：一至九年级 + 未指定
GRADE_NAMES = [f"{n}年级" for n in ("一", "二", "三", "四", "五", "六", "七", "八", "九")]
GRADE_CHOICES = GRADE_NAMES + ["未指定"]
DEFAULT_GRADE = "八年级"

# 界面显示口径：小学仍为 X 年级，初中改为 初一/初二/初三，高中为 高一/高二/高三
_STORAGE_TO_DISPLAY = {
    "七年级": "初一", "八年级": "初二", "九年级": "初三",
}
_DISPLAY_TO_STORAGE = {v: k for k, v in _STORAGE_TO_DISPLAY.items()}

# 界面可选年级（含高中）；小学与未指定保持原样
DISPLAY_GRADE_NAMES = (
    GRADE_NAMES[:6]
    + ["初一", "初二", "初三"]
    + ["高一", "高二", "高三"]
)
DISPLAY_GRADE_CHOICES = DISPLAY_GRADE_NAMES + ["未指定"]


def to_display_grade(grade: Any) -> str:
    """把数据库里的年级名转成界面显示名；非初中原样返回。"""
    if not isinstance(grade, str):
        return ""
    return _STORAGE_TO_DISPLAY.get(grade, grade)


def to_storage_grade(grade: Any) -> str:
    """把界面显示名转回数据库存储名；非初中显示名原样返回。"""
    if not isinstance(grade, str):
        return ""
    return _DISPLAY_TO_STORAGE.get(grade, grade)


def is_valid_subject(subject: Any) -> bool:
    """判断学科是否受支持。"""
    return isinstance(subject, str) and subject in SUBJECT_NAMES


def is_valid_grade(grade: Any) -> bool:
    """判断年级是否受支持；“未指定”也是合法选项（按存储口径）。"""
    return isinstance(grade, str) and grade in GRADE_CHOICES