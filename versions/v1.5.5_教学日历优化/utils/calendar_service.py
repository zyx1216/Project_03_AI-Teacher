# -*- coding: utf-8 -*-
"""教学日历服务层（v1.5.2）。

- month_weeks：自绘月历所需的按周切分日期网格（纯函数）；
- collect_events：按日期合并考试 / 作业 / 教案。

约定（已锁定）：考试用 exam_date，作业和教案用 created_at；不新增日期字段。
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta

from models.models import Exam, Homework, LessonPlan


def month_weeks(year: int, month: int) -> list[list[date | None]]:
    """
    返回某年某月按周切分的日期网格（周一开头）。
    每格是一个 date；月首/月末不足整周用 None 补位，便于自绘月历。
    """
    first = date(year, month, 1)
    # calendar.monthcalendar：周一开头，补位用 0
    weeks = calendar.Calendar(firstweekday=0).monthdayscalendar(year, month)
    grid: list[list[date | None]] = []
    for week in weeks:
        row: list[date | None] = []
        for day in week:
            row.append(date(year, month, day) if day != 0 else None)
        grid.append(row)
    return grid


def week_range(day: date) -> tuple[date, date]:
    """返回 day 所在周的周一和周日。"""
    monday = day - timedelta(days=day.weekday())
    return monday, monday + timedelta(days=6)


def _as_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def _in_range(day: date | None, start: date, end: date) -> bool:
    return day is not None and start <= day <= end


def collect_events(session, start: date, end: date) -> dict[date, list[dict]]:
    """
    收集 [start, end] 内的事项，按日期归并：
    📊 考试（exam_date）、📝 作业（created_at）、📚 教案（created_at）。
    返回 {日期: [{"kind","icon","title","id"}, ...]}，每天内部按类型排序。
    """
    result: dict[date, list[dict]] = {}

    def add(day: date | None, item: dict):
        if day and _in_range(day, start, end):
            result.setdefault(day, []).append(item)

    for exam in session.query(Exam).all():
        add(_as_date(exam.exam_date), {
            "kind": "exam", "icon": "📊", "id": exam.id,
            "title": exam.name})
    for hw in session.query(Homework).filter(Homework.is_template.is_(False)):
        add(_as_date(hw.created_at), {
            "kind": "homework", "icon": "📝", "id": hw.id,
            "title": hw.name})
    for plan in session.query(LessonPlan).all():
        add(_as_date(plan.created_at), {
            "kind": "lesson", "icon": "📚", "id": plan.id,
            "title": plan.title})

    order = {"exam": 0, "homework": 1, "lesson": 2}
    for day in result:
        result[day].sort(key=lambda e: (order[e["kind"]], e["title"]))
    return dict(sorted(result.items()))


def upcoming_exams(session, start: date, days: int = 7) -> list[dict]:
    """未来 days 天内（含 start）的考试，按日期升序，用于待办提醒。"""
    end = start + timedelta(days=days - 1)
    events = collect_events(session, start, end)
    exams = []
    for day, items in events.items():
        for item in items:
            if item["kind"] == "exam":
                exams.append({"date": day, **item})
    return sorted(exams, key=lambda e: (e["date"], e["title"]))

def week_preview_rows(session, day: date) -> list[dict]:
    """返回本周 7 天的首页预览数据：考试、普通作业、教案。"""
    monday, sunday = week_range(day)
    events = collect_events(session, monday, sunday)
    labels = ["一", "二", "三", "四", "五", "六", "日"]
    rows = []
    for index, current in enumerate([
        monday + timedelta(days=i) for i in range(7)
    ], start=1):
        items = events.get(current, [])
        def titles(kind):
            return "、".join(item["title"] for item in items if item["kind"] == kind)
        rows.append({
            "日期": ("🔵 " if current == day else "") + current.strftime("%m月%d日"),
            "星期": "周" + labels[index - 1],
            "状态": "今天" if current == day else "",
            "考试": titles("exam"),
            "作业": titles("homework"),
            "教案": titles("lesson"),
        })
    return rows
