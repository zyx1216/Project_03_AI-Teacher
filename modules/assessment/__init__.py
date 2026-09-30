# -*- coding: utf-8 -*-
"""学业测评模块入口：新包结构与旧 modules.homework 兼容。"""
from __future__ import annotations
import streamlit as st
from modules import homework as _impl
_VIEWS = {
    "作业管理": _impl.tab_manage,
    "🤖 智能组卷": _impl.tab_smart_compose,
    "✏️ 批改与分析": _impl.tab_grading_analysis,
    "📚 分层作业": _impl.tab_tiered_homework,
    "错题本": _impl.tab_wrong_book,
}
def show(tab: str | None = None) -> None:
    selected = tab or st.session_state.get("homework_tab") or "作业管理"
    _VIEWS.get(selected, _impl.tab_manage)()
def __getattr__(name):
    return getattr(_impl, name)
