# -*- coding: utf-8 -*-
"""资料类型定义（v2.5.1）。

资料按用途分类，便于筛选与题目提取；默认课本，历史数据缺省按课本处理。
"""

from __future__ import annotations

MATERIAL_TYPES = {
    "textbook": {"label": "📖 课本", "icon": "📖", "desc": "正规教材"},
    "workbook": {"label": "📚 练习册", "icon": "📚", "desc": "练习题集"},
    "exam_collection": {"label": "📄 试卷集", "icon": "📄", "desc": "试卷汇编"},
    "lesson_plan": {"label": "📋 教案", "icon": "📋", "desc": "教学设计"},
    "knowledge_summary": {"label": "📝 知识点总结", "icon": "📝", "desc": "知识梳理"},
}

DEFAULT_MATERIAL_TYPE = "textbook"


def normalize_type(value) -> str:
    """把资料类型归一到合法值；未知或空返回默认课本。"""
    key = str(value or "").strip()
    return key if key in MATERIAL_TYPES else DEFAULT_MATERIAL_TYPE


def type_label(value) -> str:
    """返回带图标的中文标签，如「📖 课本」。"""
    return MATERIAL_TYPES[normalize_type(value)]["label"]


def type_icon(value) -> str:
    """返回类型图标。"""
    return MATERIAL_TYPES[normalize_type(value)]["icon"]


def type_desc(value) -> str:
    """返回类型说明。"""
    return MATERIAL_TYPES[normalize_type(value)]["desc"]
