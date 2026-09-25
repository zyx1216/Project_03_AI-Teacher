# -*- coding: utf-8 -*-
"""首页数据服务。

集中处理首页需要的真实统计：本学期教案、本月作业、最近考试均分、
待批改作业、最近动态。页面层不直接拼 ORM 查询。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import func

from models.models import Exam, Homework, HomeworkScore, LessonPlan
from utils import exam_service
from utils import homework_score_service as hscore
from utils import homework_service as hw_svc


def semester_bounds(today: date) -> tuple[date, date]:
    """返回当前学期起止日期；结束日期为开区间。"""
    if today.month >= 9:
        return date(today.year, 9, 1), date(today.year + 1, 2, 1)
    if today.month <= 1:
        return date(today.year - 1, 9, 1), date(today.year, 2, 1)
    return date(today.year, 2, 1), date(today.year, 9, 1)


def month_bounds(today: date) -> tuple[date, date]:
    if today.month == 12:
        return date(today.year, 12, 1), date(today.year + 1, 1, 1)
    return date(today.year, today.month, 1), date(today.year, today.month + 1, 1)


def _created_date(value: datetime | date | None) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    return value if isinstance(value, date) else None


def _exam_average(session, exam: Exam) -> float | None:
    wide = exam_service.analyze_exam(session, exam.id)
    rows = wide.get("rows", []) if isinstance(wide, dict) else []
    totals = [r["total"] for r in rows if r.get("total") is not None]
    return round(sum(totals) / len(totals), 2) if totals else None


def _recent_exams(session) -> list[dict[str, Any]]:
    """按日期升序组装考试均分；首页最近动态只取最后三场。"""
    result: list[dict[str, Any]] = []
    previous_avg: float | None = None
    for exam in exam_service.list_exams(session):
        avg = _exam_average(session, exam)
        delta = None if avg is None or previous_avg is None else round(avg - previous_avg, 2)
        result.append({
            "日期": exam.exam_date, "考试": exam.name,
            "平均分": avg, "变化": delta})
        if avg is not None:
            previous_avg = avg
    return result


def _pending_items(session, homeworks: list[Homework]) -> list[dict[str, Any]]:
    """待批改作业；有班级按班级名册核对，无班级只认完全未录。"""
    items: list[dict[str, Any]] = []
    for hw in homeworks:
        if hw.class_name:
            rows = hscore.score_rows(session, hw.id, hw.class_name)
            missing = sum(1 for r in rows if r.get("score") is None)
            if missing > 0:
                items.append({"作业": hw.name, "未录人数": missing})
        else:
            count = (session.query(func.count(HomeworkScore.id))
                     .filter(HomeworkScore.homework_id == hw.id).scalar())
            if not count:
                items.append({"作业": hw.name, "未录人数": None})
    return items


def dashboard_data(session, today: date | None = None) -> dict[str, Any]:
    """返回首页展示所需的完整数据。"""
    today = today or date.today()
    term_start, term_end = semester_bounds(today)
    month_start, month_end = month_bounds(today)

    homeworks = hw_svc.list_homeworks(session, templates=False)
    lesson_count = (session.query(func.count(LessonPlan.id))
                    .filter(LessonPlan.created_at >= term_start,
                            LessonPlan.created_at < term_end).scalar())
    monthly_hw_count = sum(
        1 for hw in homeworks
        if month_start <= (_created_date(hw.created_at) or date.min) < month_end
    )

    exam_rows = _recent_exams(session)
    latest_exam = next((r for r in reversed(exam_rows) if r["平均分"] is not None), None)
    pending = _pending_items(session, homeworks)

    recent_homeworks = [{
        "名称": hw.name,
        "学科": hw.subject or "数学",
        "类型": hw_svc.type_label(hw.homework_type),
        "班级": hw.class_name or "—",
        "创建日期": _created_date(hw.created_at),
    } for hw in homeworks[:3]]

    return {
        "date": today,
        "lesson_count": int(lesson_count or 0),
        "monthly_homework_count": monthly_hw_count,
        "latest_average": latest_exam["平均分"] if latest_exam else None,
        "pending_count": len(pending),
        "recent_exams": list(reversed(exam_rows[-3:])),
        "recent_homeworks": recent_homeworks,
        "pending_items": pending,
    }
