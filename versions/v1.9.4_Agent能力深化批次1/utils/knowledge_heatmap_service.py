# -*- coding: utf-8 -*-
"""知识点掌握热力图服务。"""
from __future__ import annotations

import json

from models.models import Homework, HomeworkAnswer, HomeworkQuestion, Question, Student


def _question_knowledge_points(question: Question) -> list[str]:
    """题目没有知识点时归入“未标注知识点”。"""
    values: list[str] = []
    raw = question.knowledge_points
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                values = [str(x).strip() for x in data if str(x).strip()]
        except (json.JSONDecodeError, TypeError):
            values = []
    return values or ["未标注知识点"]


def _rate(answer: HomeworkAnswer, link: HomeworkQuestion) -> float | None:
    """优先用得分/题分计算；没有题分但有对错时按 1/0 计算。"""
    if answer.earned_score is not None and link.score:
        return max(0.0, min(1.0, float(answer.earned_score) / float(link.score)))
    if answer.is_correct is not None:
        return 1.0 if answer.is_correct else 0.0
    return None


def build_heatmap(session, *, subject: str, class_names: list[str] | None = None,
                  homework_ids: list[int] | None = None) -> dict:
    """聚合知识点 × 班级正确率。

    返回 x=班级、y=知识点、z=正确率矩阵、details=格子对应题目明细。
    """
    homework_query = session.query(Homework).filter(
        Homework.is_template.is_(False), Homework.subject == subject)
    if homework_ids:
        homework_query = homework_query.filter(Homework.id.in_(homework_ids))
    homeworks = homework_query.all()

    buckets: dict[tuple[str, str], list[float]] = {}
    details: dict[tuple[str, str], list[dict]] = {}
    class_set = set(class_names or [])

    for hw in homeworks:
        links = {link.question_id: link for link in hw.questions}
        answers = (session.query(HomeworkAnswer, Student)
                   .join(Student, HomeworkAnswer.student_id == Student.id)
                   .filter(HomeworkAnswer.homework_id == hw.id).all())
        for answer, student in answers:
            class_name = student.class_name or "未分班"
            if class_set and class_name not in class_set:
                continue
            link = links.get(answer.question_id)
            question = session.get(Question, answer.question_id)
            if link is None or question is None:
                continue
            rate = _rate(answer, link)
            if rate is None:
                continue
            for kp in _question_knowledge_points(question):
                key = (class_name, kp)
                buckets.setdefault(key, []).append(rate)
                details.setdefault(key, []).append({
                    "homework": hw.name, "student": student.name,
                    "question": question.content, "rate": rate})

    x = sorted({key[0] for key in buckets})
    y = sorted({key[1] for key in buckets})
    z = []
    for kp in y:
        row = []
        for class_name in x:
            values = buckets.get((class_name, kp), [])
            row.append(round(sum(values) / len(values), 4) if values else None)
        z.append(row)
    return {"x": x, "y": y, "z": z, "details": details}
