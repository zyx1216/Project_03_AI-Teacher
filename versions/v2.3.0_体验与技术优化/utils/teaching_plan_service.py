# -*- coding: utf-8 -*-
"""学期/周教学计划生成与进度跟踪。"""

from __future__ import annotations

from copy import deepcopy
from datetime import date

from models.models import TeachingProgress
from utils import calendar_service


def _chapter_name(item, index: int) -> str:
    if isinstance(item, dict):
        return str(item.get("name") or item.get("chapter")
                   or f"第{index + 1}章").strip()
    return str(item or f"第{index + 1}章").strip()


def _chapter_hours(chapters: list[str], weekly_hours: int) -> list[dict]:
    """按章节和每周课时均匀分配，不依赖 AI。"""
    total = max(1, len(chapters))
    base = max(1, weekly_hours)
    result = []
    for name in chapters:
        result.append({"chapter": name, "hours": base})
    return result


def generate_semester_plan(subject, grade, semester, weekly_hours,
                           textbook_chapters) -> dict:
    """生成 20 周学期计划。AI 不可用时也能均匀分配。"""
    try:
        hours = max(1, int(weekly_hours))
    except (TypeError, ValueError):
        hours = 4
    chapters = [_chapter_name(x, i) for i, x in enumerate(textbook_chapters or [])]
    if not chapters:
        chapters = ["第一单元", "第二单元", "第三单元", "第四单元"]

    chapter_hours = _chapter_hours(chapters, hours)
    weekly_plan = []
    cursor = 0
    for week in range(1, 21):
        if week <= 16:
            take = max(1, len(chapters) // 16 + (1 if cursor < len(chapters) % 16 else 0))
            current = chapters[cursor:cursor + take]
            if not current and cursor < len(chapters):
                current = [chapters[cursor]]
            cursor += take
            content = "、".join(current) if current else "机动与巩固"
            note = "新授"
        elif week == 17:
            content = "专项复习"
            note = "期末复习"
        elif week == 18:
            content = "综合模拟与讲评"
            note = "期末复习"
        elif week == 19:
            content = "期末考试与试卷讲评"
            note = "考试"
        else:
            content = "学期总结与假期安排"
            note = "总结"
        weekly_plan.append({
            "week_number": week,
            "start_date": "",
            "end_date": "",
            "content": content,
            "hours": hours if week <= 18 else 1,
            "note": note,
        })

    return {
        "meta": {
            "subject": str(subject or "数学"),
            "grade": str(grade or ""),
            "semester": str(semester or ""),
            "weekly_hours": hours,
            "total_weeks": 20,
            "generated_rule": "按章节和每周课时均匀分配",
        },
        "weekly_plan": weekly_plan,
        "chapter_hours": chapter_hours,
        "exam_review": [
            {"week": 17, "arrangement": "专项复习"},
            {"week": 18, "arrangement": "综合模拟"},
            {"week": 19, "arrangement": "期末考试"},
        ],
        "key_difficulties": [
            {"chapter": item["chapter"], "key_difficulty": "核心概念与典型题型"}
            for item in chapter_hours
        ],
    }


def generate_weekly_plan(semester_plan: dict, week_number: int) -> dict:
    """读取某周计划。"""
    try:
        week = int(week_number)
    except (TypeError, ValueError):
        raise ValueError("周次必须是整数。")
    for item in semester_plan.get("weekly_plan", []):
        if int(item.get("week_number", 0)) == week:
            return dict(item)
    raise ValueError(f"学期计划中没有第 {week} 周。")


def _get_row(session, subject, grade, semester, week_number) -> TeachingProgress:
    row = (session.query(TeachingProgress)
           .filter(TeachingProgress.subject == subject,
                   TeachingProgress.grade == grade,
                   TeachingProgress.semester == semester,
                   TeachingProgress.week_number == week_number).first())
    if row is None:
        row = TeachingProgress(
            subject=subject, grade=grade, semester=semester,
            week_number=week_number)
        session.add(row)
    return row


def save_planned_weeks(session, semester_plan: dict) -> int:
    """把学期计划写入按周进度记录；只写计划内容，不造实际完成内容。"""
    meta = semester_plan.get("meta", {})
    subject = meta.get("subject", "数学")
    grade = meta.get("grade", "")
    semester = meta.get("semester", "")
    count = 0
    for item in semester_plan.get("weekly_plan", []):
        row = _get_row(session, subject, grade, semester,
                       int(item["week_number"]))
        row.planned_content = item.get("content", "")
        row.status = row.status or "normal"
        count += 1
    session.flush()
    return count


def track_progress(session, subject, grade, semester, week_number,
                   actual_content, note: str = "") -> TeachingProgress:
    """录入实际进度；状态按周次与当前日期判断，不猜文本完成度。"""
    week = int(week_number)
    current_week = calendar_service.semester_progress(
        date.today(), calendar_service.load_semester())[0]
    text = str(actual_content or "").strip()
    row = _get_row(session, str(subject), str(grade), str(semester), week)
    row.actual_content = text
    row.note = str(note or "")
    if not text and week <= current_week:
        row.status = "lag"
    elif week > current_week:
        row.status = "ahead"
    else:
        row.status = "normal"
    session.flush()
    return row


def compare_progress(session, subject, grade, semester) -> dict:
    """对比本学期按周进度。"""
    rows = (session.query(TeachingProgress)
            .filter(TeachingProgress.subject == subject,
                    TeachingProgress.grade == grade,
                    TeachingProgress.semester == semester)
            .order_by(TeachingProgress.week_number).all())
    current_week = calendar_service.semester_progress(
        date.today(), calendar_service.load_semester())[0]
    lag_weeks = [r.week_number for r in rows if r.status == "lag"]
    ahead_weeks = [r.week_number for r in rows if r.status == "ahead"]
    missing_weeks = [
        w for w in range(1, current_week + 1)
        if not any(r.week_number == w and (r.actual_content or "").strip()
                   for r in rows)
    ]
    return {
        "current_week": current_week,
        "status": "lag" if lag_weeks or missing_weeks else
                  ("ahead" if ahead_weeks else "normal"),
        "lag_weeks": sorted(set(lag_weeks + missing_weeks)),
        "ahead_weeks": ahead_weeks,
        "lag_count": len(set(lag_weeks + missing_weeks)),
        "ahead_count": len(ahead_weeks),
        "details": [
            {"week": r.week_number, "planned": r.planned_content or "",
             "actual": r.actual_content or "", "status": r.status,
             "note": r.note or ""}
            for r in rows
        ],
    }


def auto_adjust_plan(semester_plan: dict, current_week: int,
                     actual_progress) -> dict:
    """复制原计划并顺延后续周内容；不修改原计划。"""
    adjusted = deepcopy(semester_plan)
    lag_count = 0
    if isinstance(actual_progress, dict):
        statuses = actual_progress
    else:
        statuses = {i: item for i, item in enumerate(actual_progress or [], start=1)}
    for week in range(1, int(current_week) + 1):
        item = statuses.get(week) if isinstance(statuses, dict) else None
        if isinstance(item, dict) and item.get("status") == "lag":
            lag_count += 1
    weekly = adjusted.setdefault("weekly_plan", [])
    if lag_count:
        for item in weekly:
            week = int(item.get("week_number", 0))
            if week > current_week:
                item["content"] = item.get("content", "") + "（含顺延内容）"
                item["note"] = item.get("note", "") + f"；自动顺延{lag_count}周内容"
    adjusted["meta"]["auto_adjusted"] = True
    adjusted["meta"]["lag_count"] = lag_count
    return adjusted


def apply_adjusted_plan(session, adjusted_plan: dict) -> int:
    """保存一键调整后的计划内容。"""
    return save_planned_weeks(session, adjusted_plan)

