# -*- coding: utf-8 -*-
"""v1.8.2 折叠导航的跨子功能跳转工具。

lesson_plan_tab / homework_tab / analysis_tab 现在是侧边栏子 radio 的
widget key，内容区按钮在 widget 创建后直接写这些 key 会报
StreamlitWidgetAlreadyInstantiatedError。统一改成写一次性 pending key，
由 app.py 在导航控件创建前消费。
"""
import streamlit as st

GROUP_SUB_KEY = {
    # v3.4.1：新增资源中心/教学工具两个折叠组。
    "📂 资源中心": "resource_tab",
    "🎓 教学工具": "teaching_tab",
    "📚 备课": "lesson_plan_tab",
    "📝 学业测评": "homework_tab",
    "📊 学情": "analysis_tab",
}


def goto_group(group: str, sub: str | None = None, **extra) -> None:
    """跳转到某个折叠组；给定 sub 时同时选中组内子功能。"""
    st.session_state["_pending_app_route"] = group
    if sub is not None:
        st.session_state["_pending_app_sub"] = sub
        st.session_state["_pending_app_sub_key"] = GROUP_SUB_KEY[group]
    for key, value in extra.items():
        st.session_state[key] = value
    st.rerun()
