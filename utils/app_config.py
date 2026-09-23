# -*- coding: utf-8 -*-
"""学科、年级常量与校验。

v1.3.0 起不再保存"全局当前学科"；各功能自己的选择由 feature_subjects 管理。
v1.6.3 起初中年级在界面统一显示为"初一/初二/初三"，数据库仍存"七/八/九年级"，
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
    """判断年级是否受支持；"未指定"也是合法选项（按存储口径）。"""
    return isinstance(grade, str) and grade in GRADE_CHOICES


def detect_grade_from_title(title: str) -> str:
    """
    根据资料标题自动判定年级，返回界面显示名（如"三年级"、"初一"、"高一"）。
    无法判定时返回空字符串。

    支持的标题格式：
    - 小学：一年级、二年级...六年级，1年级、2年级...6年级
    - 初中：初一/七年级、初二/八年级、初三/九年级，7年级、8年级、9年级
    - 高中：高一、高二、高三，十年级、十一年级、十二年级，10年级、11年级、12年级
    - 上册/下册不影响年级判定
    """
    if not isinstance(title, str) or not title.strip():
        return ""

    text = title.strip()

    # 高中判定（优先，避免"高一"被误判）
    high_school_map = {
        "高一": "高一", "高二": "高二", "高三": "高三",
        "十年级": "高一", "十一年级": "高二", "十二年级": "高三",
        "10年级": "高一", "11年级": "高二", "12年级": "高三",
    }
    for keyword, grade in high_school_map.items():
        if keyword in text:
            return grade

    # 初中判定
    junior_high_map = {
        "初一": "初一", "初二": "初二", "初三": "初三",
        "七年级": "初一", "八年级": "初二", "九年级": "初三",
        "7年级": "初一", "8年级": "初二", "9年级": "初三",
    }
    for keyword, grade in junior_high_map.items():
        if keyword in text:
            return grade

    # 小学判定（中文数字）
    primary_map_cn = {
        "一年级": "一年级", "二年级": "二年级", "三年级": "三年级",
        "四年级": "四年级", "五年级": "五年级", "六年级": "六年级",
    }
    for keyword, grade in primary_map_cn.items():
        if keyword in text:
            return grade

    # 小学判定（阿拉伯数字）
    primary_map_num = {
        "1年级": "一年级", "2年级": "二年级", "3年级": "三年级",
        "4年级": "四年级", "5年级": "五年级", "6年级": "六年级",
    }
    for keyword, grade in primary_map_num.items():
        if keyword in text:
            return grade

    return ""