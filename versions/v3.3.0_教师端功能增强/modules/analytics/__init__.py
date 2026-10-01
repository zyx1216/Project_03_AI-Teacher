# -*- coding: utf-8 -*-
"""学情模块入口：新包结构与旧 modules.analysis 兼容。"""
from __future__ import annotations
import streamlit as st
from modules import analysis as _impl
_VIEWS = {
    "学生管理": _impl.tab_students,
    "成绩管理": _impl.tab_scores,
    "考试分析": _impl.tab_exam_analysis,
    "趋势分析": _impl.tab_trends,
    "学生画像": _impl.tab_profile,
    "🔍 AI教学诊断": _impl.tab_diagnosis,
}
def show(tab: str | None = None) -> None:
    selected = tab or st.session_state.get("analysis_tab") or "学生管理"
    _VIEWS.get(selected, _impl.tab_students)()
def __getattr__(name):
    return getattr(_impl, name)
