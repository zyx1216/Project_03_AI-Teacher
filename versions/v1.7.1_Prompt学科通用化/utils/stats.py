# -*- coding: utf-8 -*-
"""
成绩统计纯逻辑层。

这里的函数都不依赖 Streamlit、不碰数据库，只接收普通 list/dict 做计算，
方便单元测试，也方便页面和 AI 总结复用同一套口径。

口径约定：
- 默认及格线 = 满分 × 60%，优秀线 = 满分 × 85%
- 名次用"并列同名次"的竞赛排名（如 1,2,2,4），缺考(None)不参与
"""

from __future__ import annotations

import math
from typing import Optional

# 成绩层次阈值（按平均得分率，0~1）
LEVEL_EXCELLENT = 0.85
LEVEL_GOOD = 0.70
LEVEL_MEDIUM = 0.60

# 趋势判定阈值：平均每场得分率变化达到 2 个百分点算明显
TREND_SLOPE_THRESHOLD = 0.02

# 强弱科阈值：某科得分率与本人各科均值差 5 个百分点
SUBJECT_STRENGTH_GAP = 0.05


def clean_values(values) -> list[float]:
    """去掉 None 和不能转成数字的成绩，返回 float 列表（缺考不参与统计）。"""
    result = []
    for v in values:
        if v is None or v == "":
            continue
        try:
            result.append(float(v))
        except (TypeError, ValueError):
            continue
    return result


def describe(values) -> dict:
    """计算一组分数的基础指标：人数、均分、中位数、标准差、最高、最低。"""
    data = clean_values(values)
    n = len(data)
    if n == 0:
        return {"count": 0, "mean": None, "median": None, "std": None,
                "max": None, "min": None}
    mean = sum(data) / n
    sorted_data = sorted(data)
    mid = n // 2
    if n % 2 == 1:
        median = sorted_data[mid]
    else:
        median = (sorted_data[mid - 1] + sorted_data[mid]) / 2
    variance = sum((x - mean) ** 2 for x in data) / n
    return {
        "count": n,
        "mean": round(mean, 2),
        "median": round(median, 2),
        "std": round(math.sqrt(variance), 2),
        "max": max(data),
        "min": min(data),
    }


def competition_rank(values) -> list[Optional[int]]:
    """并列同名次排名，缺考返回 None。例：[90, 90, 80] -> [1, 1, 3]。"""
    scored = [(i, float(v)) for i, v in enumerate(values)
              if v is not None and v != ""]
    scored.sort(key=lambda x: x[1], reverse=True)
    ranks: list[Optional[int]] = [None] * len(values)
    rank = 0
    prev_score = None
    for position, (index, score) in enumerate(scored, start=1):
        if prev_score is None or score != prev_score:
            rank = position
            prev_score = score
        ranks[index] = rank
    return ranks


def ratio_counts(values, full_score: float, ratio: float) -> int:
    """统计达到满分某比例（含）以上的人数。"""
    if not full_score or full_score <= 0:
        return 0
    line = full_score * ratio
    return sum(1 for v in clean_values(values) if v >= line)


def pass_and_excellent(values, full_score: float,
                       pass_ratio: float = 0.6,
                       excellent_ratio: float = 0.85) -> dict:
    """按自定义比例统计及格率、优秀率；无数据返回 None。"""
    data = clean_values(values)
    n = len(data)
    if n == 0 or not full_score or full_score <= 0:
        return {"pass_rate": None, "excellent_rate": None,
                "pass_count": 0, "excellent_count": 0, "count": n}
    if not (0 < pass_ratio < 1 and 0 < excellent_ratio < 1):
        raise ValueError("及格线和优秀线比例必须在 0 到 1 之间。")
    if excellent_ratio <= pass_ratio:
        raise ValueError("优秀线必须高于及格线。")
    pass_count = ratio_counts(data, full_score, pass_ratio)
    excellent_count = ratio_counts(data, full_score, excellent_ratio)
    return {
        "pass_rate": round(pass_count / n, 4),
        "excellent_rate": round(excellent_count / n, 4),
        "pass_count": pass_count,
        "excellent_count": excellent_count,
        "count": n,
    }


def default_band_edges(full_score: float) -> list[float]:
    """旧版五段分数段边界，保留给作业等非考试分析使用。"""
    return [
        0.0,
        full_score * 0.6,
        full_score * 0.7,
        full_score * 0.8,
        full_score * 0.9,
        full_score + 1.0,
    ]


DEFAULT_BAND_LABELS = ["不及格(<60%)", "及格(60-69%)", "中等(70-79%)",
                       "良好(80-89%)", "优秀(≥90%)"]


def threshold_band_edges(full_score: float, pass_ratio: float,
                         excellent_ratio: float) -> list[float]:
    """考试分析自定义三段边界：未及格 / 及格 / 优秀。"""
    return [0.0, full_score * pass_ratio,
            full_score * excellent_ratio, full_score + 1.0]


def threshold_band_labels(pass_ratio: float, excellent_ratio: float) -> list[str]:
    """三段分数段显示名。"""
    return [
        f"未及格（<{pass_ratio * 100:g}%）",
        f"及格（{pass_ratio * 100:g}%–{excellent_ratio * 100:g}%）",
        f"优秀（≥{excellent_ratio * 100:g}%）",
    ]


def score_bands(values, full_score: float, edges=None, labels=None) -> list[dict]:
    """按给定边界统计人数，edges 为升序左闭右开边界，末段兜底到满分。"""
    if edges is None:
        edges = default_band_edges(full_score)
    if labels is None:
        labels = DEFAULT_BAND_LABELS
    data = clean_values(values)
    counts = [0] * (len(edges) - 1)
    for v in data:
        for i in range(len(edges) - 1):
            if edges[i] <= v < edges[i + 1]:
                counts[i] += 1
                break
        else:
            counts[-1] += 1
    return [{"label": labels[i], "count": counts[i]}
            for i in range(len(labels))]


def score_deltas(current: dict, previous: dict) -> dict:
    """计算两次考试的分数和名次变化。"""
    cur_rank = dict(zip(current.keys(),
                        competition_rank(list(current.values()))))
    prev_rank = dict(zip(previous.keys(),
                         competition_rank(list(previous.values()))))
    result = {}
    for key, cur_score in current.items():
        if key not in previous or previous[key] is None:
            continue
        score_delta = round(float(cur_score) - float(previous[key]), 2)
        rank_delta = None
        if prev_rank.get(key) is not None and cur_rank.get(key) is not None:
            rank_delta = prev_rank[key] - cur_rank[key]
        result[key] = {"score_delta": score_delta, "rank_delta": rank_delta}
    return result


def linear_slope(ys) -> Optional[float]:
    """对按时间顺序的数值做最小二乘，返回斜率；点数不足返回 None。"""
    data = [float(y) for y in ys if y is not None and y != ""]
    n = len(data)
    if n < 2:
        return None
    xs = list(range(n))
    x_mean = sum(xs) / n
    y_mean = sum(data) / n
    denominator = sum((x - x_mean) ** 2 for x in xs)
    if denominator == 0:
        return None
    return sum((xs[i] - x_mean) * (data[i] - y_mean) for i in range(n)) / denominator


def trend_label(rates, threshold: float = TREND_SLOPE_THRESHOLD) -> str:
    """根据得分率斜率判定趋势。"""
    slope = linear_slope(rates)
    if slope is None:
        return "数据不足"
    if slope >= threshold:
        return "进步明显"
    if slope <= -threshold:
        return "需关注"
    return "稳定"


def level_tag(avg_rate: Optional[float]) -> str:
    """按平均得分率给成绩层次标签。"""
    if avg_rate is None:
        return "数据不足"
    if avg_rate >= LEVEL_EXCELLENT:
        return "优秀"
    if avg_rate >= LEVEL_GOOD:
        return "良好"
    if avg_rate >= LEVEL_MEDIUM:
        return "中等"
    return "待提高"


def subject_strength(subject_rates: dict, gap: float = SUBJECT_STRENGTH_GAP) -> dict:
    """标出相对本人均值的强项/弱项/正常。"""
    valid = {k: float(v) for k, v in subject_rates.items()
             if v is not None and v != ""}
    if not valid:
        return {}
    own_mean = sum(valid.values()) / len(valid)
    result = {}
    for subject, rate in valid.items():
        if rate - own_mean >= gap:
            result[subject] = "强项"
        elif own_mean - rate >= gap:
            result[subject] = "弱项"
        else:
            result[subject] = "正常"
    return result


def subject_summary(values, full_score: float,
                    pass_ratio: float = 0.6,
                    excellent_ratio: float = 0.85,
                    custom_bands: bool = False) -> dict:
    """单科/总分汇总；custom_bands=True 时按自定义考试线输出三段。"""
    base = describe(values)
    rates = pass_and_excellent(values, full_score, pass_ratio, excellent_ratio)
    if custom_bands:
        bands = score_bands(
            values, full_score,
            threshold_band_edges(full_score, pass_ratio, excellent_ratio),
            threshold_band_labels(pass_ratio, excellent_ratio))
    else:
        bands = score_bands(values, full_score)
    base.update(rates)
    base["bands"] = bands
    base["full_score"] = full_score
    return base
