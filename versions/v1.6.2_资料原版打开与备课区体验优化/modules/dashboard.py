# -*- coding: utf-8 -*-
"""首页 Dashboard 页面。"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from utils.db import SessionLocal
from utils import calendar_service as cal_svc
from utils import class_service
from utils import dashboard_service as svc
from utils import schedule_service


def _metric_or_dash(value) -> str:
    return "—" if value is None else str(value)


def _quick_actions() -> None:
    st.subheader("快捷入口")
    c1, c2, c3 = st.columns(3)
    if c1.button("📝 新建作业", key="dash_new_homework", use_container_width=True):
        st.session_state["_pending_main_page"] = "📝 作业"
        st.session_state["hw_new_dialog_open"] = True
        st.rerun()
    if c2.button("📥 上传成绩", key="dash_upload_score", use_container_width=True):
        st.session_state["_pending_main_page"] = "📊 学情"
        st.session_state["analysis_tab"] = "成绩管理"
        st.session_state["score_import_expander"] = True
        st.rerun()
    if c3.button("📚 AI 备课", key="dash_ai_lesson", use_container_width=True):
        st.session_state["_pending_main_page"] = "📚 备课"
        st.session_state["lesson_plan_tab"] = "AI 备课"
        st.rerun()


def _overview_cards(data: dict) -> None:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("本学期备课次数", data["lesson_count"])
    c2.metric("本月布置作业次数", data["monthly_homework_count"])
    c3.metric("最近考试平均分", _metric_or_dash(data["latest_average"]))
    c4.metric("待批改作业数", data["pending_count"])


def _recent_exams(data: dict) -> None:
    st.markdown("#### 最近 3 场考试")
    if not data["recent_exams"]:
        st.info("还没有考试成绩。可通过上方“上传成绩”导入。")
        return
    rows = []
    for item in data["recent_exams"]:
        delta_text = "—" if item["变化"] is None else f"{item['变化']:+.1f}"
        rows.append({
            "日期": item["日期"] or "—", "考试": item["考试"],
            "平均分": _metric_or_dash(item["平均分"]), "较上一场": delta_text})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def _recent_homeworks(data: dict) -> None:
    st.markdown("#### 最近布置的 3 次作业")
    if not data["recent_homeworks"]:
        st.info("还没有作业。可通过上方“新建作业”创建。")
        return
    st.dataframe(pd.DataFrame(data["recent_homeworks"]), hide_index=True, width="stretch")


def _todo(data: dict) -> None:
    st.markdown("#### 待办事项")
    if not data["pending_items"]:
        st.success("当前没有待批改作业。")
        return
    rows = []
    for item in data["pending_items"]:
        rows.append({
            "作业": item["作业"],
            "未录成绩人数": "未录（无班级作业）" if item["未录人数"] is None else item["未录人数"]})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def _calendar_preview(session, today) -> None:
    st.subheader("本周日历预览")
    rows = cal_svc.week_preview_rows(session, today)
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    if st.button("📅 打开完整教学日历", key="dash_open_calendar"):
        st.session_state["_pending_main_page"] = "📅 教学日历"
        st.rerun()


def _home_schedule(session) -> None:
    st.subheader("本周课程表（每周重复）")
    classes = class_service.list_class_names(session)
    if not classes:
        st.info("还没有班级。先在“学情 → 学生管理 → 班级管理”创建班级。")
        return

    selected = st.selectbox(
        "选择班级", options=classes, key="home_schedule_class")
    grid = schedule_service.week_grid(selected)
    entries = schedule_service.list_entries(selected)
    if not entries:
        st.info("这个班还没有课程安排，可在完整教学日历页维护。")
    st.dataframe(pd.DataFrame(grid), hide_index=True, width="stretch")


def show() -> None:
    """渲染首页。"""
    st.title("🏠 首页")
    with SessionLocal() as session:
        data = svc.dashboard_data(session)
        st.caption(f"今天是 {data['date'].strftime('%Y年%m月%d日')}，星期一"
                   if data['date'].weekday() == 0 else
                   f"今天是 {data['date'].strftime('%Y年%m月%d日')}")
        st.write("### 老师好，欢迎回来")
        _overview_cards(data)
        st.divider()
        left, right = st.columns(2)
        with left:
            _recent_exams(data)
        with right:
            _todo(data)
        st.divider()
        _recent_homeworks(data)
        st.divider()
        _quick_actions()
        st.divider()
        _calendar_preview(session, data["date"])
        st.divider()
        _home_schedule(session)
