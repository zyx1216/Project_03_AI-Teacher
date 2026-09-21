# -*- coding: utf-8 -*-
"""教学日历页面（v1.5.2）：自绘月历、当天安排、本周概览。"""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import streamlit as st

from models.models import HomeworkScore
from utils.db import SessionLocal
from utils import calendar_service as cal_svc

WEEKDAY_CN = ["一", "二", "三", "四", "五", "六", "日"]
MONTH_LABEL_CAP = "教学日历按日期显示考试、作业和备课；作业和备课日期取创建当天。"


def show():
    """渲染教学日历页。"""
    st.title("📅 教学日历")
    st.caption(MONTH_LABEL_CAP)

    today = date.today()
    if "cal_year" not in st.session_state:
        st.session_state["cal_year"] = today.year
    if "cal_month" not in st.session_state:
        st.session_state["cal_month"] = today.month

    # 月份切换（固定 key，不用动态 key）
    cc1, cc2, cc3 = st.columns([1, 1, 3])
    if cc1.button("⬅️ 上一月", key="cal_prev_month"):
        _shift_month(-1)
    if cc2.button("下一月 ➡️", key="cal_next_month"):
        _shift_month(1)
    cc3.caption(f"当前查看月份：{st.session_state['cal_year']} 年 "
                f"{st.session_state['cal_month']} 月")

    year = st.session_state["cal_year"]
    month = st.session_state["cal_month"]
    start = date(year, month, 1)
    end = cal_svc.month_weeks(year, month)[-1]
    end_day = next(d for d in reversed(end) if d is not None)

    with SessionLocal() as session:
        events = cal_svc.collect_events(session, start, end_day)

    _render_month(year, month, events)

    st.divider()
    _render_day_detail(events, today)

    st.divider()
    with SessionLocal() as session:
        _render_week_overview(session, today)


def _shift_month(delta: int) -> None:
    year = st.session_state["cal_year"]
    month = st.session_state["cal_month"] + delta
    if month < 1:
        month, year = 12, year - 1
    elif month > 12:
        month, year = 1, year + 1
    st.session_state["cal_year"] = year
    st.session_state["cal_month"] = month


def _cell_text(day: date | None, events: dict) -> str:
    if day is None:
        return ""
    parts = [f"**{day.day}**"]
    for item in events.get(day, []):
        parts.append(f"{item['icon']}{_truncate(item['title'], 8)}")
    return "  \n".join(parts)


def _truncate(text: str, n: int) -> str:
    return text if len(text) <= n else text[:n] + "…"


def _render_month(year, month, events) -> None:
    grid = cal_svc.month_weeks(year, month)
    header = {f"周{w}": [] for w in WEEKDAY_CN}
    cols = list(header.keys())
    today = date.today()
    for week in grid:
        for col, day in zip(cols, week):
            text = _cell_text(day, events)
            if day == today:
                text = f"🔵{text}"
            header[col].append(text)
    st.dataframe(pd.DataFrame(header), hide_index=True, width="stretch")


def _render_day_detail(events, today) -> None:
    st.subheader("查看某天")
    # 有事项的日期优先列在说明里
    busy_dates = sorted(events.keys())
    if busy_dates:
        st.caption("本月有安排的日期：" +
                   "、".join(d.strftime("%m月%d日") for d in busy_dates))
    chosen = st.date_input("选择日期", value=today, key="cal_picked_day")
    items = events.get(chosen, [])
    if not items:
        st.info("这一天没有安排。")
    else:
        kind_cn = {"exam": "考试", "homework": "作业", "lesson": "备课"}
        for item in items:
            st.write(f"{item['icon']} {kind_cn.get(item['kind'], item['kind'])}：{item['title']}")

    st.write("**快捷前往**")
    b1, b2, b3 = st.columns(3)
    if b1.button("📝 去新建作业", key="cal_go_homework", use_container_width=True):
        _goto_page("📝 作业")
    if b2.button("📊 去新建考试", key="cal_go_exam", use_container_width=True):
        _goto_page("📊 学情")
    if b3.button("📚 去备课", key="cal_go_lesson", use_container_width=True):
        _goto_page("📚 备课")


def _goto_page(page: str) -> None:
    """请求跨主导航跳转，由 app.py 在渲染前应用（不自动开弹窗）。"""
    st.session_state["_pending_main_page"] = page
    st.rerun()


def _render_week_overview(session, today) -> None:
    st.subheader("本周概览")
    monday, sunday = cal_svc.week_range(today)
    events = cal_svc.collect_events(session, monday, sunday)
    if not events:
        st.info("本周没有考试、作业或备课安排。")
    else:
        for day in sorted(events):
            line = "、".join(f"{e['icon']}{e['title']}" for e in events[day])
            st.write(f"**{day.strftime('%m月%d日（周')}"
                     f"{WEEKDAY_CN[day.weekday()]}）**：{line}")

    st.write("**待办提醒**")
    upcoming = cal_svc.upcoming_exams(session, today, 7)
    if upcoming:
        for exam in upcoming:
            st.write(f"📊 {exam['date'].strftime('%m月%d日')} 有考试：{exam['title']}")
    else:
        st.caption("未来 7 天没有考试。")

    # 本周作业里仍有学生缺成绩的，提醒去录入
    missing = _homeworks_missing_scores(session, events)
    if missing:
        for title, n in missing:
            st.write(f"📝 作业「{title}」还有 {n} 名学生未录成绩。")


def _homeworks_missing_scores(session, week_events) -> list[tuple]:
    result = []
    for day, items in week_events.items():
        for item in items:
            if item["kind"] != "homework":
                continue
            recorded = (session.query(HomeworkScore)
                        .filter(HomeworkScore.homework_id == item["id"]).count())
            # 以该作业适用班级名册人数为准；无班级时无法核对，跳过
            from models.models import Homework
            hw = session.get(Homework, item["id"])
            if not hw or not hw.class_name:
                continue
            from utils import student_service
            total = student_service.list_students(
                session, class_name=hw.class_name)
            n = len(total) - recorded
            if n > 0:
                result.append((item["title"], n))
    return result
