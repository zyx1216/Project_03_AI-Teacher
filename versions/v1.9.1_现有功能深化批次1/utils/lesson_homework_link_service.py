# -*- coding: utf-8 -*-
"""教案与作业联动服务（v1.9.0）。

create_homework_from_lesson：从教案提取学科、年级、章节，
按默认题量（选择 5、填空 3、解答 2）走 auto_compose 生成课后作业，
并把作业的 lesson_plan_id 指回来源教案。章节只约束 AI 补题。
"""

from __future__ import annotations

from models.models import LessonPlan
from utils.app_config import DEFAULT_SUBJECT, to_storage_grade
from utils import (
    lesson_service as lesson_svc,
    homework_service as hw_svc,
    question_service as qs,
)

# 默认题量：(内部题型, 难度, 数量)
DEFAULT_COUNTS = [
    ("choice", 1, 5),
    ("fill", 2, 3),
    ("solution", 2, 2),
]


def create_homework_from_lesson(session, lesson_id: int,
                                counts: dict | None = None):
    """根据教案生成一份课后作业。

    总题数为 0 时删除空作业并抛 ValueError；成功返回 Homework。
    """
    lesson = session.get(LessonPlan, lesson_id)
    if lesson is None:
        raise ValueError(f"教案不存在：id={lesson_id}")

    plan = lesson_svc.load_plan(lesson)
    subject = lesson_svc.plan_subject(lesson) or DEFAULT_SUBJECT
    # lesson.grade 历史上可能存界面或存储口径，to_storage_grade 对存储值原样返回。
    grade_store = to_storage_grade(lesson.grade) if lesson.grade else None
    chapter = lesson.chapter or None

    if counts:
        slots = [{"question_type": t, "difficulty": d, "count": int(c)}
                 for (t, d, c) in _counts_from_dict(counts)]
    else:
        slots = [{"question_type": t, "difficulty": d, "count": c}
                 for (t, d, c) in DEFAULT_COUNTS]
    spec = {"slots": slots}

    name = f"{lesson.title}·配套作业"
    hw = hw_svc.create_homework(
        session, name, homework_type="after_class",
        subject=subject, grade=grade_store, chapter=chapter)
    hw.lesson_plan_id = lesson_id
    session.flush()

    stats = hw_svc.auto_compose(
        session, hw.id, spec,
        ai_context={"grade": grade_store,
                    "chapters": [chapter] if chapter else []})
    if stats.get("total_questions", 0) <= 0:
        hw_svc.delete_homework(session, hw.id)
        session.flush()
        raise ValueError("根据教案没有生成任何题目，作业未创建。")
    return hw


def _counts_from_dict(counts: dict):
    """把 {内部题型: 数量} 转成 [(题型, 难度2, 数量)]。"""
    out = []
    for qtype, count in counts.items():
        key = str(qtype).strip().lower()
        if key not in {"choice", "fill", "judge", "solution"}:
            continue
        c = int(count)
        if c > 0:
            out.append((key, 2, c))
    return out
