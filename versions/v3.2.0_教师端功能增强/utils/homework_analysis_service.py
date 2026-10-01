# -*- coding: utf-8 -*-
"""作业完成度增强分析服务（v2.1.0）。"""

from __future__ import annotations

from models.models import (
    Homework, HomeworkAnswer, HomeworkScore, HomeworkSubmission)


def _submissions_map(session, homework_id):
    rows = session.query(HomeworkSubmission).filter(
        HomeworkSubmission.homework_id == homework_id).all()
    return {row.student_name: row for row in rows}


def analyze_homework_completion(session, homework_id) -> dict:
    """汇总提交率、按时率、逐题完成情况和距截止时间。"""
    hw = session.get(Homework, int(homework_id))
    if hw is None:
        raise ValueError(f"作业不存在：id={homework_id}")

    from utils import homework_score_service, homework_service

    roster_rows = homework_score_service.score_rows(session, hw.id)
    total = len(roster_rows)
    submissions = session.query(HomeworkSubmission).filter(
        HomeworkSubmission.homework_id == hw.id).all()
    sub_by_name = {row.student_name: row for row in submissions}

    submitted_names = set()
    for row in roster_rows:
        score_row = session.query(HomeworkScore).filter(
            HomeworkScore.homework_id == hw.id,
            HomeworkScore.student_id == row["student_id"]).first()
        if score_row is not None and score_row.submitted:
            submitted_names.add(row["name"])
    for row in submissions:
        submitted_names.add(row.student_name)

    on_time = None
    minutes_before_due = []
    if hw.due_date is not None:
        on_time = 0
        for name in submitted_names:
            row = sub_by_name.get(name)
            if row is None:
                continue
            delta = (hw.due_date - row.submitted_at).total_seconds() / 60
            minutes_before_due.append(round(delta, 1))
            if delta >= 0:
                on_time += 1

    pairs = homework_service.homework_questions(session, hw.id)
    answers = session.query(HomeworkAnswer).filter(
        HomeworkAnswer.homework_id == hw.id).all()
    grouped = {}
    for link, question in pairs:
        grouped[question.id] = {
            "order": link.order,
            "question_content": question.content[:80],
            "answered": 0,
            "correct": 0,
            "wrong": 0,
            "judged": 0,
            "score_sum": 0.0,
            "score_n": 0,
            "full_score": _link_score(session, hw.id, question.id),
        }
    for answer in answers:
        item = grouped.get(answer.question_id)
        if item is None:
            continue
        if answer.is_correct is not None or answer.earned_score is not None:
            item["answered"] += 1
        if answer.is_correct is not None:
            item["judged"] += 1
            if answer.is_correct:
                item["correct"] += 1
            else:
                item["wrong"] += 1
        if answer.earned_score is not None:
            item["score_sum"] += float(answer.earned_score)
            item["score_n"] += 1

    questions = []
    for item in grouped.values():
        correct_rate = item["correct"] / item["judged"] if item["judged"] else None
        score_rate = None
        if item["score_n"] and item["full_score"]:
            score_rate = item["score_sum"] / (
                item["score_n"] * item["full_score"])
        questions.append({
            **item,
            "correct_rate": round(correct_rate, 4) if correct_rate is not None else None,
            "score_rate": round(score_rate, 4) if score_rate is not None else None,
            "inferred_difficulty": _infer_difficulty(correct_rate),
        })
    questions.sort(key=lambda item: (item["order"] or 999, item["question_content"]))

    return {
        "homework_id": hw.id,
        "total_students": total,
        "submitted_count": len(submitted_names),
        "submission_rate": round(len(submitted_names) / total, 4) if total else None,
        "on_time_count": on_time,
        "on_time_rate": round(on_time / len(submitted_names), 4)
        if on_time is not None and submitted_names else None,
        "average_minutes_before_due": round(
            sum(minutes_before_due) / len(minutes_before_due), 1)
        if minutes_before_due else None,
        "questions": questions,
    }


def _link_score(session, homework_id, question_id):
    from models.models import HomeworkQuestion

    link = session.query(HomeworkQuestion).filter(
        HomeworkQuestion.homework_id == homework_id,
        HomeworkQuestion.question_id == question_id).first()
    return float(link.score) if link is not None and link.score else None


def _infer_difficulty(rate):
    if rate is None:
        return "无法判断"
    if rate >= 0.85:
        return "基础"
    if rate >= 0.60:
        return "中等"
    return "偏难"
