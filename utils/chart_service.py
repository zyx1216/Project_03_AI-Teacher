# -*- coding: utf-8 -*-
"""可视化图表服务（v1.9.0）。

集中提供四类复用 Plotly 图：
- score_box：成绩箱线图；
- ability_radar：多学科能力雷达图；
- rate_gauge：及格率/优秀率等仪表盘；
- knowledge_gauges：知识点掌握度仪表盘（红黄绿分级）。
"""

from __future__ import annotations

import plotly.graph_objects as go


def score_box(rows, score_key: str = "total",
              group_key: str | None = None) -> go.Figure:
    """成绩箱线图。

    rows：[{score_key: 分数, group_key?: 分组名}]；
    传 group_key 时按班级等分组各画一个箱子。
    """
    fig = go.Figure()
    if group_key:
        groups = {}
        for r in rows:
            groups.setdefault(r.get(group_key) or "未分组", []).append(
                r.get(score_key))
        for name, values in groups.items():
            fig.add_trace(go.Box(y=[v for v in values if v is not None],
                                 name=str(name), boxmean=True))
    else:
        fig.add_trace(go.Box(
            y=[r.get(score_key) for r in rows if r.get(score_key) is not None],
            name="全体", boxmean=True))
    fig.update_layout(title="成绩分布箱线图", yaxis_title="分数",
                      showlegend=True, height=380, margin=dict(l=10, r=10, t=50, b=10))
    return fig


def ability_radar(rows, subjects) -> go.Figure:
    """多学科能力雷达图。

    rows：[{学科: 得分率(0-1或0-100)}]，多条线对比多个学生/班级；
    subjects：参与对比的学科名（雷达轴）。
    """
    fig = go.Figure()
    for i, row in enumerate(rows):
        values = []
        for s in subjects:
            v = row.get(s)
            if v is None:
                values.append(None)
            else:
                values.append(v * 100 if v <= 1 else v)
        name = row.get("name") or f"对象{i + 1}"
        # 闭合雷达图：首尾相连
        r_vals = list(values) + [values[0]] if values else values
        theta_vals = list(subjects) + [subjects[0]] if subjects else []
        # 自定义悬停模板：显示学科、分数、得分率
        hover_texts = []
        for s, v in zip(subjects, values):
            if v is None:
                hover_texts.append(f"{s}：无数据")
            else:
                hover_texts.append(f"{s}：{v:.1f}分（{v:.0f}%）")
        hover_texts.append(hover_texts[0] if hover_texts else "")
        fig.add_trace(go.Scatterpolar(
            r=r_vals,
            theta=theta_vals,
            mode="lines+markers",  # 显示连线和连接点
            fill="toself",
            name=str(name),
            marker=dict(size=8),  # 连接点大小
            hovertemplate="%{text}<extra>" + str(name) + "</extra>",
            text=hover_texts))
    fig.update_layout(
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 100], title="得分率(%)"),
            angularaxis=dict(rotation=90, direction="clockwise")),
        showlegend=True, title="多学科能力对比", height=420,
        margin=dict(l=20, r=20, t=50, b=20))
    return fig


def rate_gauge(value, title) -> go.Figure:
    """单个比率仪表盘；value 传 0-100 的百分值。"""
    value = float(value or 0)
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=value,
        number={"suffix": "%"},
        gauge={"axis": {"range": [0, 100]},
               "bar": {"color": "#1F4E79"},
               "steps": [
                   {"range": [0, 60], "color": "#F8D7DA"},
                   {"range": [60, 80], "color": "#FFF3CD"},
                   {"range": [80, 100], "color": "#D4EDDA"}],
               "threshold": {"line": {"color": "#C0392B", "width": 3},
                             "thickness": 0.8, "value": 60}}))
    fig.update_layout(title=title, height=260,
                      margin=dict(l=20, r=20, t=50, b=10))
    return fig


def knowledge_gauges(items) -> list[go.Figure]:
    """知识点掌握度仪表盘列表。

    items：[{knowledge_point, rate(0-100)}]
    """
    return [rate_gauge(item.get("rate", 0),
                       item.get("knowledge_point") or "知识点")
            for item in items]
