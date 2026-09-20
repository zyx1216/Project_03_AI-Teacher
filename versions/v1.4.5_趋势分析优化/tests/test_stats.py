# -*- coding: utf-8 -*-
"""utils/stats.py 统计口径单元测试。"""

import math

from utils import stats as st


def test_clean_values_drops_invalid():
    assert st.clean_values([90, None, "", "abc", "88.5", -5]) == [90, 88.5, -5.0]
    assert st.clean_values([None, ""]) == []


def test_describe_basic():
    d = st.describe([100, 90, 80, 70])
    assert d["count"] == 4
    assert d["mean"] == 85.0
    assert d["median"] == 85.0          # 偶数个取中间两个均值
    assert d["max"] == 100 and d["min"] == 70
    # 总体标准差：方差 = ((15)^2+(5)^2+(-5)^2+(-15)^2)/4 = 125
    assert math.isclose(d["std"], round(math.sqrt(125), 2))


def test_describe_empty():
    d = st.describe([None, ""])
    assert d["count"] == 0 and d["mean"] is None


def test_describe_median_odd():
    assert st.describe([1, 2, 3])["median"] == 2


def test_competition_rank_ties():
    # 两个并列第一，下一个是第三名
    assert st.competition_rank([90, 90, 80]) == [1, 1, 3]
    # 缺考不参与，名次为 None
    ranks = st.competition_rank([80, None, 90])
    assert ranks == [2, None, 1]
    assert st.competition_rank([]) == []


def test_pass_and_excellent_rates():
    # 满分 100：及格线 60，优秀线 85
    values = [100, 90, 85, 60, 59]
    r = st.pass_and_excellent(values, 100)
    assert r["pass_count"] == 4          # 59 不及格
    assert r["excellent_count"] == 3     # 100,90,85
    assert r["pass_rate"] == 0.8
    assert r["excellent_rate"] == 0.6


def test_pass_and_excellent_scaled_full_score():
    # 满分 120：及格 72，优秀 102
    values = [120, 102, 72, 71]
    r = st.pass_and_excellent(values, 120)
    assert r["pass_count"] == 3
    assert r["excellent_count"] == 2


def test_score_bands_default():
    # 满分 100：<60, 60-69, 70-79, 80-89, >=90
    values = [55, 65, 75, 85, 95, 100]
    bands = st.score_bands(values, 100)
    counts = [b["count"] for b in bands]
    assert counts == [1, 1, 1, 1, 2]
    assert [b["label"] for b in bands] == st.DEFAULT_BAND_LABELS


def test_score_bands_scaled():
    # 满分 120：段边界 72 / 84 / 96 / 108
    values = [70, 72, 90, 100, 110]
    bands = st.score_bands(values, 120)
    counts = [b["count"] for b in bands]
    assert counts == [1, 1, 1, 1, 1]


def test_score_deltas():
    # 上次 90/80，本次 85/90
    current = {"甲": 85, "乙": 90}
    previous = {"甲": 90, "乙": 80}
    d = st.score_deltas(current, previous)
    assert d["甲"]["score_delta"] == -5
    assert d["乙"]["score_delta"] == 10
    # 名次：甲从第1掉到第2 → rank_delta = 1-2 = -1（退步）
    assert d["甲"]["rank_delta"] == -1
    assert d["乙"]["rank_delta"] == 1


def test_score_deltas_ignores_missing_previous():
    d = st.score_deltas({"甲": 80}, {"乙": 70})
    assert d == {}


def test_linear_slope():
    # 严格递增，每场 +2
    assert st.linear_slope([2, 4, 6, 8]) == 2
    assert st.linear_slope([5]) is None
    assert st.linear_slope([None, None]) is None


def test_trend_label():
    # 得分率每场涨超过 2 个百分点
    assert st.trend_label([0.60, 0.65, 0.70]) == "进步明显"
    # 基本持平
    assert st.trend_label([0.70, 0.705, 0.71]) == "稳定"
    # 明显下滑
    assert st.trend_label([0.80, 0.70, 0.60]) == "需关注"
    assert st.trend_label([0.7]) == "数据不足"


def test_level_tag():
    assert st.level_tag(0.9) == "优秀"
    assert st.level_tag(0.85) == "优秀"
    assert st.level_tag(0.75) == "良好"
    assert st.level_tag(0.65) == "中等"
    assert st.level_tag(0.5) == "待提高"
    assert st.level_tag(None) == "数据不足"


def test_subject_strength():
    # 三科均值约 0.7；数学明显高是强项，英语明显低是弱项
    rates = {"数学": 0.9, "语文": 0.7, "英语": 0.5}
    result = st.subject_strength(rates)
    assert result["数学"] == "强项"
    assert result["英语"] == "弱项"
    assert result["语文"] == "正常"


def test_subject_summary_combines():
    s = st.subject_summary([100, 50], 100)
    assert s["mean"] == 75
    assert s["pass_rate"] == 0.5
    assert len(s["bands"]) == 5
    assert s["full_score"] == 100
