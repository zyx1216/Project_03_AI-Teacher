# -*- coding: utf-8 -*-
"""单学生个性化作业服务（v2.1.0）。"""

from __future__ import annotations

from collections import defaultdict

from models.models import HomeworkAnswer, Question, Student


def suggest_personal_knowledge(session, student_id, subject) -> list[str]:
    """根据真实逐题作答找学生薄弱知识点，返回知识点名称列表。"""
    return [item["knowledge_point"]
            for item in _personal_knowledge_stats(session, student_id, subject)]


def _personal_knowledge_stats(session, student_id, subject) -> list[dict]:
    """汇总每个知识点的错误率，供生成作业匹配难度。"""
    student = session.get(Student, int(student_id))
    if student is None:
        raise ValueError("学生不存在。")

    rows = (session.query(HomeworkAnswer, Question)
            .join(Question, HomeworkAnswer.question_id == Question.id)
            .filter(HomeworkAnswer.student_id == int(student_id),
                    Question.subject == subject,
                    HomeworkAnswer.is_correct.is_not(None)).all())
    stats = defaultdict(lambda: {"wrong": 0, "total": 0})
    for answer, question in rows:
        for kp in _knowledge_points(question):
            stats[kp]["total"] += 1
            if not answer.is_correct:
                stats[kp]["wrong"] += 1

    weak = [
        {"knowledge_point": kp, "wrong_rate": round(
            item["wrong"] / item["total"], 4),
         "total": item["total"]}
        for kp, item in stats.items() if item["total"]
    ]
    weak.sort(key=lambda item: (-item["wrong_rate"], -item["total"], item["knowledge_point"]))
    return weak


def _knowledge_points(question: Question) -> list[str]:
    import json

    try:
        value = json.loads(question.knowledge_points or "[]")
    except (TypeError, ValueError):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def generate_personalized_homework(
        session, student_id, subject,
        knowledge_points=None, count=10) -> dict:
    """为指定学生创建一份个性化作业。"""
    from utils import homework_service

    student = session.get(Student, int(student_id))
    if student is None:
        raise ValueError("学生不存在。")
    count = max(1, min(int(count), 30))
    kps = [str(item).strip() for item in (knowledge_points or [])
           if str(item).strip()]
    weak = _personal_knowledge_stats(session, student.id, subject)
    if not kps:
        kps = [item["knowledge_point"] for item in weak[:3]]
    if not kps:
        raise ValueError("逐题作答数据不足，无法判断薄弱知识点；请手动选择知识点。")

    rates = [item["wrong_rate"] for item in weak
             if item["knowledge_point"] in kps]
    avg_wrong = sum(rates) / len(rates) if rates else 0.5
    if avg_wrong >= 0.7:
        difficulty = 1
    elif avg_wrong >= 0.35:
        difficulty = 2
    else:
        difficulty = 3

    homework = homework_service.create_homework(
        session, f"{student.name}·{subject}个性化作业",
        homework_type="after_class", class_name=student.class_name,
        total_score=float(count * 10), subject=subject,
        grade=None, status="pending")
    ratios = {1: 0, 2: 0, 3: 0}
    ratios[difficulty] = 100
    spec = {
        "counts": {"choice": count},
        "difficulty_ratio": ratios,
    }
    result = homework_service.auto_compose(
        session, homework.id, spec, knowledge_points=kps,
        ai_context={"grade": None, "chapters": []})
    return {
        "homework_id": homework.id,
        "homework_name": homework.name,
        "knowledge_points": kps,
        "target_difficulty": difficulty,
        **result,
    }
