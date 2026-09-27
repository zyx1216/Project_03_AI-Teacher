# -*- coding: utf-8 -*-
"""v1.5.2 教学日历服务层测试。"""
from datetime import date, datetime

from models.models import Exam, Homework, LessonPlan
from utils import calendar_service as cs


def test_month_weeks_leading_and_trailing_padding():
    # 2026-09：9月1日是周二 → 第一行周一补 None
    grid = cs.month_weeks(2026, 9)
    assert all(len(w) == 7 for w in grid)
    assert grid[0][0] is None
    assert grid[0][1] == date(2026, 9, 1)
    # 月内日期都在9月
    for week in grid:
        for d in week:
            if d is not None:
                assert d.year == 2026 and d.month == 9
    # 2026-02：2月1日周日 → 前6格 None，最后一天28
    g2 = cs.month_weeks(2026, 2)
    assert g2[0][:6] == [None] * 6 and g2[0][6] == date(2026, 2, 1)


def test_week_range():
    mon, sun = cs.week_range(date(2026, 9, 21))  # 周一
    assert mon == date(2026, 9, 21) and sun == date(2026, 9, 27)
    mon2, sun2 = cs.week_range(date(2026, 9, 23))  # 周三
    assert mon2 == date(2026, 9, 21) and sun2 == date(2026, 9, 27)


def test_collect_events_merge_and_filter(session):
    session.add_all([
        Exam(name="月考", exam_date=date(2026, 9, 10)),
        Homework(name="作业甲", is_template=False,
                 created_at=datetime(2026, 9, 10, 8, 0)),
        LessonPlan(title="教案乙", created_at=datetime(2026, 9, 12, 9, 0)),
        # 模板不应出现；范围外事件不应出现
        Homework(name="模板", is_template=True,
                 created_at=datetime(2026, 9, 10)),
        Exam(name="范围外", exam_date=date(2026, 10, 1)),
    ])
    session.commit()
    events = cs.collect_events(session, date(2026, 9, 1), date(2026, 9, 30))
    # 9月10日：考试 + 作业，按 exam 先 homework 后排序
    titles = [(e["icon"], e["title"]) for e in events[date(2026, 9, 10)]]
    assert titles == [("📊", "月考"), ("📝", "作业甲")]
    # 9月12日：教案
    assert [e["title"] for e in events[date(2026, 9, 12)]] == ["教案乙"]
    assert date(2026, 10, 1) not in events


def test_upcoming_exams(session):
    session.add_all([
        Exam(name="近", exam_date=date(2026, 9, 23)),
        Exam(name="远", exam_date=date(2026, 10, 20)),
        Exam(name="边界", exam_date=date(2026, 9, 21)),
    ])
    session.commit()
    up = cs.upcoming_exams(session, date(2026, 9, 21), 7)
    assert [e["title"] for e in up] == ["边界", "近"]
