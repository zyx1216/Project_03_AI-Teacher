# -*- coding: utf-8 -*-
"""备课区模块入口：新包结构与旧 modules.lesson_plan 兼容。"""
from __future__ import annotations
from typing import Callable
import streamlit as st
from modules import lesson_plan as _impl

_VIEWS = {
    "资料管理": _impl.tab_materials,
    "AI 备课": _impl.tab_lesson,
    "AI 出题": _impl.tab_question_gen,
    "📚 单元整体设计": _impl.tab_unit_design,
    "题库管理": _impl.tab_bank,
}

def show(tab: str | None = None) -> None:
    """按显式参数或当前 session_state 分发备课子功能。"""
    selected = tab or st.session_state.get("lesson_plan_tab") or "资料管理"
    _VIEWS.get(selected, _impl.tab_materials)()

def __getattr__(name):
    return getattr(_impl, name)
