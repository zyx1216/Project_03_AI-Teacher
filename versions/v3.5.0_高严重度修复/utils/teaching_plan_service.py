# -*- coding: utf-8 -*-
"""学期/周教学计划生成与进度跟踪。"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta

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


# ---------------------------------------------------------------------------
# v2.6.0：教学节奏建议（结合进度对比与成绩数据）
# ---------------------------------------------------------------------------

def suggest_pace(session, subject: str, grade: str, semester: str,
                 chat_func=None) -> dict:
    """根据教学进度与成绩数据给出节奏调整建议。

    返回 {"status","lag_weeks","ahead_weeks","suggestions":[...],
          "next_focus":str}；无数据时给明确提示。
    """
    compare = compare_progress(session, subject, grade, semester)
    rows = compare.get("rows") or []
    if not rows:
        return {"status": "no_data", "lag_weeks": 0, "ahead_weeks": 0,
                "suggestions": ["还没有教学进度记录，先去「教学日历」录入进度。"],
                "next_focus": ""}
    lag = sum(1 for r in rows if r.get("status") == "lag")
    ahead = sum(1 for r in rows if r.get("status") == "ahead")
    suggestions = []
    if lag:
        suggestions.append(f"有 {lag} 周进度落后，建议适当放慢并增加复习课时。")
    if ahead:
        suggestions.append(f"有 {ahead} 周进度超前，可补充拓展练习或专题课。")
    if not lag and not ahead:
        suggestions.append("进度与计划基本一致，保持当前节奏。")

    # 结合最近考试：均分偏低提示放缓，偏高提示可加速
    next_focus = ""
    try:
        from utils import exam_service
        exams = exam_service.list_exams(session)
        if exams:
            latest = exams[0]
            data = exam_service.analyze_exam(session, latest.id)
            total = (data or {}).get("total_stats") or {}
            rate = total.get("mean")
            full = (data or {}).get("total_full") or 100
            if rate is not None and full:
                ratio = rate / full
                if ratio < 0.6:
                    suggestions.append("最近考试得分率偏低，建议本周安排一次专项复习。")
                else:
                    suggestions.append("最近考试表现稳定，可按计划推进新课。")
    except Exception:  # noqa: BLE001 —— 成绩数据缺失不影响进度建议
        pass

    if lag:
        next_focus = "本周重点：补齐落后章节的基础概念与典型例题。"
    elif ahead:
        next_focus = "本周重点：为超前内容补充变式练习与综合应用。"
    else:
        next_focus = "本周重点：按计划推进新课，穿插过关小测。"
    return {"status": "lag" if lag else ("ahead" if ahead else "normal"),
            "lag_weeks": lag, "ahead_weeks": ahead,
            "suggestions": suggestions, "next_focus": next_focus}


# ---------------------------------------------------------------------------
# v3.3.0：甘特图数据与 AI 调整建议
# ---------------------------------------------------------------------------

def gantt_rows(session, subject: str, grade: str, semester: str) -> list[dict]:
    """甘特图：每周一行，含计划日期、实际完成日期和章节内容。

    行里没填 planned_date 时，按学期开学日期 + (周次-1)*7 天推算。
    """
    rows = (session.query(TeachingProgress)
            .filter(TeachingProgress.subject == subject,
                    TeachingProgress.grade == grade,
                    TeachingProgress.semester == semester)
            .order_by(TeachingProgress.week_number).all())
    start = date.fromisoformat(calendar_service.load_semester()["start"])
    result = []
    for row in rows:
        planned_date = row.planned_date or (
            start + timedelta(days=(int(row.week_number) - 1) * 7))
        result.append({
            "week": row.week_number,
            "chapter": row.chapter or row.planned_content or "",
            "planned_content": row.planned_content or "",
            "actual_content": row.actual_content or "",
            "planned_date": planned_date,
            "actual_date": row.actual_date,
            "status": row.status,
        })
    return result


def ai_adjust_suggestions(session, subject: str, grade: str, semester: str,
                          chat_func=None) -> dict:
    """进度落后时给调整建议；AI 不可用按规则生成，不会空着。"""
    compare = compare_progress(session, subject, grade, semester)
    lag_weeks = compare.get("lag_weeks") or []
    if not lag_weeks:
        return {"suggestions": "当前进度与计划一致，不需要调整。",
                "lag_weeks": []}

    weeks_text = "、".join(str(w) for w in lag_weeks)
    if chat_func is not None:
        system = (
            "你是教学排课助手。根据进度落后情况给出具体可执行的调整建议，"
            "例如合并课时、跳过已掌握内容的练习、用自习课补课。"
            "只输出建议正文，不超过100字。")
        user = f"{subject}{grade} 在第 {weeks_text} 周进度落后，请给调整建议。"
        try:
            text = str(chat_func(system, user)).strip()
            if text:
                return {"suggestions": text, "lag_weeks": lag_weeks}
        except Exception:  # noqa: BLE001 —— AI 失败回落规则建议
            pass
    return {
        "suggestions": (f"第 {weeks_text} 周内容已落后，建议合并相近课时、"
                        "精讲多练，利用自习课补1课时，并顺延复习安排。"),
        "lag_weeks": lag_weeks,
    }
