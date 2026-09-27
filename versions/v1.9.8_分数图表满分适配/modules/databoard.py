# -*- coding: utf-8 -*-
"""教学数据可视化大屏（v1.9.8）。"""

from __future__ import annotations

import streamlit as st
import plotly.graph_objects as go

from utils.db import SessionLocal
from utils import (chart_service, databoard_service, full_score_service,
                   knowledge_graph_service)


def show():
    """渲染数据看板。"""
    st.title("📊 教学数据看板")

    with SessionLocal() as session:
        classes = _all_classes(session)
        subjects = _all_subjects(session)
        class_pick = st.multiselect(
            "班级（默认全部）", classes, key="databoard_classes")
        c1, c2, c3 = st.columns(3)
        subject = c1.selectbox(
            "学科", ["总分"] + subjects, key="databoard_subject")
        start = c2.date_input("开始日期", value=None, key="databoard_start")
        end = c3.date_input("结束日期", value=None, key="databoard_end")

        subject_arg = None if subject == "总分" else subject
        data = databoard_service.board_data(
            session,
            class_names=class_pick or None,
            subject=subject_arg,
            start_date=start or None,
            end_date=end or None)
        mastery = knowledge_graph_service.build_mastery(
            session, subject_arg or "数学",
            class_names=class_pick or None)

    if not data["has_data"]:
        st.info("当前筛选范围内暂无成绩数据。")
        return

    _metric_cards(data["metrics"])
    st.plotly_chart(_class_trend_fig(data["class_trend"]), width="stretch")
    st.plotly_chart(
        _subject_compare_fig(data["subject_compare"]), width="stretch")

    c1, c2 = st.columns(2)
    c1.plotly_chart(_bands_fig(data["score_bands"]), width="stretch")
    if mastery.get("students") and mastery.get("knowledge_points"):
        c2.plotly_chart(_heatmap_fig(mastery), width="stretch")
    else:
        c2.info("📊 知识点掌握热力图需要作业答题数据\n\n当前暂无学生在线作业答题记录，布置在线作业后可查看。")

    c1, c2 = st.columns(2)
    c1.plotly_chart(_ranking_fig(data["ranking"]), width="stretch")
    c2.plotly_chart(_radar_fig(data["subject_compare"]), width="stretch")


def _all_classes(session):
    from utils import student_service
    return student_service.list_classes(session)


def _all_subjects(session):
    from models.models import Score
    rows = session.query(Score.subject).distinct().all()
    return sorted({r[0] for r in rows if r[0]})


def _metric_cards(m):
    """5 个指标卡；跨满分比较使用得分率。"""
    cols = st.columns(5)
    cards = [
        ("学生总数", m["student_count"]),
        ("考试场数", m["exam_count"]),
        ("平均得分率", f'{m["average_rate"]}%'),
        ("及格率", f'{m["pass_rate"]}%'),
        ("优秀率", f'{m["excellent_rate"]}%'),
    ]
    for col, (label, value) in zip(cols, cards):
        col.metric(label, value)


def _point_label(point):
    date_text = point.get("date") or ""
    short_date = date_text[5:10] if len(date_text) >= 10 else date_text
    return f'{point.get("exam_name", "")}({short_date})' if short_date else point.get("exam_name", "")


def _point_hover(point):
    return (f'{_point_label(point)}<br>原始分：{point["average"]:g}'
            f'<br>满分：{point["full_score"]:g}'
            f'<br>得分率：{point["rate"] if point["rate"] is not None else "—"}%')


def _class_trend_fig(series):
    """班级成绩趋势，可切换原始分和得分率。"""
    score_mode = st.radio(
        "班级趋势显示", ["原始分", "得分率"], horizontal=True,
        key="databoard_trend_score_mode")
    fig = go.Figure()
    for class_name, points in series.items():
        labels = [_point_label(p) for p in points]
        y_values = [p["rate"] if score_mode == "得分率" else p["average"]
                    for p in points]
        hover_texts = [_point_hover(p) for p in points]
        fig.add_trace(go.Scatter(
            x=labels, y=y_values, mode="lines+markers",
            name=str(class_name), text=hover_texts,
            hovertemplate="%{text}<extra></extra>"))
    y_title = "得分率(%)" if score_mode == "得分率" else "平均分"
    fig.update_layout(
        title="班级成绩趋势", xaxis_title="考试（含日期）",
        yaxis_title=y_title, height=400, xaxis_tickangle=-30)
    if score_mode == "得分率":
        fig.update_layout(yaxis=dict(range=[0, 100]))
    st.caption("各次考试满分可能不同；悬停可查看原始分、满分和得分率。")
    return fig


def _subject_compare_fig(rows):
    """各学科得分率柱状图。"""
    fig = go.Figure(go.Bar(
        x=[r["subject"] for r in rows],
        y=[r.get("rate") or 0 for r in rows],
        text=[f'{r["average"]:g}/{r.get("full_score", 100):g}' for r in rows],
        hovertemplate="%{x}<br>得分率：%{y}%<br>原始分/满分：%{text}<extra></extra>"))
    fig.update_layout(
        title="各学科得分率对比", xaxis_title="学科",
        yaxis_title="得分率(%)", yaxis=dict(range=[0, 100]), height=380)
    return fig


def _bands_fig(rows):
    """得分率分段分布。"""
    fig = go.Figure(go.Bar(
        x=[r["band"] for r in rows], y=[r["count"] for r in rows],
        text=[r["count"] for r in rows]))
    fig.update_layout(
        title="得分率分布", xaxis_title="得分率分段",
        yaxis_title="人数", height=360)
    return fig


def _heatmap_fig(mastery):
    """学生 × 知识点掌握度热力图。"""
    students = mastery.get("students") or []
    kps = mastery.get("knowledge_points") or []
    matrix = mastery.get("matrix") or {}
    labels = [s["name"] for s in students]
    z = [[matrix.get(s["student_id"], {}).get(kp) for kp in kps]
         for s in students]
    fig = go.Figure(go.Heatmap(
        z=z, x=kps, y=labels, colorscale="RdYlGn", zmin=0, zmax=100,
        hovertemplate="%{y}·%{x}：%{z}%<extra></extra>"))
    fig.update_layout(title="知识点掌握热力图", height=360)
    return fig


def _ranking_fig(rows):
    """学生平均得分率排名条形图。"""
    ordered = list(reversed(rows))
    texts = [f'{r["average"]:g}/{r["full_score"]:g}' for r in ordered]
    fig = go.Figure(go.Bar(
        y=[r["name"] for r in ordered],
        x=[r.get("rate") or 0 for r in ordered],
        orientation="h", text=texts))
    fig.update_layout(
        title="学生平均得分率排名（前20）", xaxis_title="得分率(%)",
        yaxis_title="学生", xaxis=dict(range=[0, 100]), height=360)
    return fig


def _radar_fig(subject_rows):
    """各学科能力雷达图，使用实际满分。"""
    subjects = [r["subject"] for r in subject_rows]
    full_scores = {r["subject"]: r.get("full_score", 100)
                   for r in subject_rows}
    row = {"name": "全体平均"}
    for r in subject_rows:
        row[r["subject"]] = r["average"]
    return chart_service.ability_radar([row], subjects, full_scores=full_scores)
