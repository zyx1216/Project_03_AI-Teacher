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


def ability_radar(rows, subjects, full_scores=None) -> go.Figure:
    """多学科能力雷达图。

    rows：[{学科: 原始分数}]，多条线对比多个学生/班级；
    subjects：参与对比的学科名（雷达轴）；
    full_scores：{学科: 满分}，用于将原始分数转为得分率；缺省按100分制。
    """
    # 各科满分默认值（初中/高中常见满分）
    DEFAULT_FULL = {"语文": 150, "数学": 150, "英语": 150,
                    "物理": 100, "化学": 100, "生物": 100,
                    "政治": 100, "历史": 100, "地理": 100}
    full_scores = full_scores or DEFAULT_FULL
    fig = go.Figure()
    all_rates = []
    for i, row in enumerate(rows):
        rates = []
        raw_scores = []
        for s in subjects:
            v = row.get(s)
            if v is None:
                rates.append(None)
                raw_scores.append(None)
            else:
                full = full_scores.get(s, 100)
                rate = (v / full * 100) if full > 0 else 0
                rates.append(min(rate, 100))  # 得分率不超过100%
                raw_scores.append(v)
                if rate is not None:
                    all_rates.append(rate)
        name = row.get("name") or f"对象{i + 1}"
        # 闭合雷达图：首尾相连
        r_vals = list(rates) + [rates[0]] if rates else rates
        theta_vals = list(subjects) + [subjects[0]] if subjects else []
        # 自定义悬停模板：显示学科、原始分、满分、得分率
        hover_texts = []
        for s, raw, rate in zip(subjects, raw_scores, rates):
            if raw is None:
                hover_texts.append(f"{s}：无数据")
            else:
                full = full_scores.get(s, 100)
                hover_texts.append(f"{s}：{raw:.1f}/{full}分（{rate:.0f}%）")
        hover_texts.append(hover_texts[0] if hover_texts else "")
        fig.add_trace(go.Scatterpolar(
            r=r_vals,
            theta=theta_vals,
            mode="lines+markers",
            fill="toself",
            name=str(name),
            marker=dict(size=8),
            hovertemplate="%{text}<extra>" + str(name) + "</extra>",
            text=hover_texts))
    # 动态调整径向轴范围
    max_rate = max(all_rates) if all_rates else 100
    radial_max = max(100, int(max_rate / 10) * 10 + 10)
    fig.update_layout(
        polar=dict(
            radialaxis=dict(visible=True, range=[0, radial_max],
                            title="得分率(%)"),
            angularaxis=dict(rotation=90, direction="clockwise")),
        showlegend=True, title="多学科能力对比（得分率）", height=420,
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

# ---------------------------------------------------------------------------
# v1.9.9 趋势折线图统一工具
# ---------------------------------------------------------------------------

def trend_header(index, exam_name, date_text, full_score=None):
    """构造趋势点在 x 轴上的类目串（也是悬停头部公共信息）。

    用 <br> 换行（禁止 \n），包含：第N次考试 / 考试名 / 日期 / 满分。
    full_score 为空时省略满分行；date_text 为空显示“未知”。
    """
    date_display = str(date_text)[:10] if date_text else "未知"
    lines = [
        f"第{index}次考试",
        f"考试：{exam_name}",
        f"日期：{date_display}",
    ]
    if full_score is not None:
        try:
            lines.append(f"满分：{float(full_score):g}")
        except (TypeError, ValueError):
            lines.append(f"满分：{full_score}")
    return "<br>".join(lines)


def build_trend_figure(lines, headers, *, title, y_title,
                       fixed_percent=False, show_value_labels=False,
                       rate_only=False):
    """生成统一样式的趋势折线图。

    headers：显示范围内排序后的 x 类目（trend_header 的结果），用于多线对齐；
    lines：每条线 {"name", "points": {header: {"score","full","rate"}}}；
    fixed_percent：y 轴固定 0–100；
    show_value_labels：在数据点上显示数值；
    rate_only：True 时画 rate，每条线悬停只显示“名称：得分率%”，
               False 时画 score，悬停显示“名称：原始分（得分率%）”。
    """
    fig = go.Figure()
    for line in lines:
        name = line["name"]
        points = line["points"]
        xs = [h for h in headers if h in points]
        y_values, label_texts, hover_lines = [], [], []
        for h in xs:
            point = points[h]
            rate = point.get("rate")
            if rate_only:
                y_values.append(rate)
                label_texts.append(f"{rate:g}" if rate is not None else "")
                hover_lines.append(f"{name}：{rate:g}%")
            else:
                score = point.get("score")
                y_values.append(score)
                label_texts.append(f"{score:g}" if score is not None else "")
                rate_text = f"{rate:g}%" if rate is not None else "—"
                hover_lines.append(
                    f"{name}：{format(score, 'g') if score is not None else '—'}"
                    f"（{rate_text}）")
        mode = ("lines+markers+text" if show_value_labels
                else "lines+markers")
        fig.add_trace(go.Scatter(
            x=xs, y=y_values, mode=mode, name=str(name),
            text=label_texts, textposition="top center",
            customdata=hover_lines,
            hovertemplate="%{customdata}<extra></extra>",
            line=dict(width=3), marker=dict(size=10),
            connectgaps=False, hoverlabel=dict(namelength=-1)))

    layout = dict(
        title=title, xaxis_title="考试次数", yaxis_title=y_title,
        height=420,
        xaxis=dict(showticklabels=False, showgrid=True, zeroline=True),
        hovermode="x unified",
        hoverlabel=dict(align="left", font_size=13),
        margin=dict(l=60, r=30, t=60, b=40))
    fig.update_layout(**layout)
    if fixed_percent:
        fig.update_layout(yaxis=dict(range=[0, 100]))
    return fig

