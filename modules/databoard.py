# -*- coding: utf-8 -*-
"""教学数据可视化大屏（v1.9.7）。"""

from __future__ import annotations

import streamlit as st
import plotly.graph_objects as go

from utils.db import SessionLocal
from utils import chart_service, databoard_service, knowledge_graph_service


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
        start = c2.date_input("开始日期", value=None,
                              key="databoard_start")
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
    st.plotly_chart(_class_trend_fig(data["class_trend"]),
                    use_container_width=True)
    st.plotly_chart(_subject_compare_fig(data["subject_compare"]),
                    use_container_width=True)

    c1, c2 = st.columns(2)
    c1.plotly_chart(_bands_fig(data["score_bands"]),
                    use_container_width=True)
    if mastery.get("students") and mastery.get("knowledge_points"):
        c2.plotly_chart(_heatmap_fig(mastery), use_container_width=True)
    else:
        c2.info("📊 知识点掌握热力图需要作业答题数据\n\n当前暂无学生在线作业答题记录，布置在线作业后可查看。")

    c1, c2 = st.columns(2)
    c1.plotly_chart(_ranking_fig(data["ranking"]),
                    use_container_width=True)
    c2.plotly_chart(_radar_fig(data["subject_compare"]),
                    use_container_width=True)


def _all_classes(session):
    from utils import student_service
    return student_service.list_classes(session)


def _all_subjects(session):
    from models.models import Score
    rows = session.query(Score.subject).distinct().all()
    return sorted({r[0] for r in rows if r[0]})


def _metric_cards(m):
    """5 个指标卡。"""
    cols = st.columns(5)
    cards = [
        ("学生总数", m["student_count"]),
        ("考试场数", m["exam_count"]),
        ("平均分", m["average"]),
        ("及格率", f'{m["pass_rate"]}%'),
        ("优秀率", f'{m["excellent_rate"]}%'),
    ]
    for col, (label, value) in zip(cols, cards):
        col.metric(label, value)


def _class_trend_fig(series):
    """班级成绩趋势折线图。x轴用"考试名(日期)"区分同名考试。"""
    from collections import Counter
    fig = go.Figure()
    # 收集所有考试点，处理同名同日加序号
    all_points = []
    for class_name, points in series.items():
        for p in points:
            all_points.append((p.get("exam_name", ""), p.get("date", "")))
    # 统计同名同日出现次数
    name_date_counter = Counter(all_points)
    seen = {}
    def make_label(name, date_str):
        key = (name, date_str)
        idx = seen.get(key, 0) + 1
        seen[key] = idx
        total = name_date_counter.get(key, 1)
        if date_str:
            try:
                short_date = date_str[5:10]  # MM-DD
            except Exception:
                short_date = date_str
            label = f"{name}({short_date})"
        else:
            label = name
        if total > 1:
            label += f"{'①②③④⑤⑥⑦⑧⑨⑩'[idx-1] if idx <= 10 else idx}"
        return label
    for class_name, points in series.items():
        seen_local = {}
        x_labels = []
        for p in points:
            key = (p.get("exam_name", ""), p.get("date", ""))
            idx = seen_local.get(key, 0) + 1
            seen_local[key] = idx
            total = name_date_counter.get(key, 1)
            name = p.get("exam_name", "")
            date_str = p.get("date", "")
            if date_str:
                try:
                    short_date = date_str[5:10]
                except Exception:
                    short_date = date_str
                label = f"{name}({short_date})"
            else:
                label = name
            if total > 1:
                label += f"{'①②③④⑤⑥⑦⑧⑨⑩'[idx-1] if idx <= 10 else idx}"
            x_labels.append(label)
        fig.add_trace(go.Scatter(
            x=x_labels,
            y=[p["average"] for p in points],
            mode="lines+markers", name=str(class_name),
            hovertemplate="%{x}<br>平均分：%{y}<extra></extra>"))
    fig.update_layout(
        title="班级成绩趋势", xaxis_title="考试（含日期）", yaxis_title="平均分",
        height=380, xaxis_tickangle=-30)
    return fig


def _subject_compare_fig(rows):
    """各科平均分柱状图。"""
    fig = go.Figure(go.Bar(
        x=[r["subject"] for r in rows],
        y=[r["average"] for r in rows],
        text=[r["average"] for r in rows]))
    fig.update_layout(
        title="各学科平均分对比", xaxis_title="学科", yaxis_title="平均分",
        height=380)
    return fig


def _bands_fig(rows):
    """分数段分布直方图。"""
    fig = go.Figure(go.Bar(
        x=[r["band"] for r in rows], y=[r["count"] for r in rows],
        text=[r["count"] for r in rows]))
    fig.update_layout(
        title="分数段分布", xaxis_title="分数段", yaxis_title="人数",
        height=360)
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
    """学生平均分排名条形图。"""
    ordered = list(reversed(rows))
    fig = go.Figure(go.Bar(
        y=[r["name"] for r in ordered], x=[r["average"] for r in ordered],
        orientation="h", text=[r["average"] for r in ordered]))
    fig.update_layout(
        title="学生平均分排名（前20）", xaxis_title="平均分",
        height=360)
    return fig


def _radar_fig(subject_rows):
    """各学科能力雷达图（全体平均）。"""
    subjects = [r["subject"] for r in subject_rows]
    row = {"name": "全体平均"}
    for r in subject_rows:
        row[r["subject"]] = r["average"]
    return chart_service.ability_radar([row], subjects)
