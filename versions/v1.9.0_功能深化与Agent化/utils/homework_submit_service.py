# -*- coding: utf-8 -*-
"""作业在线提交服务。"""
from __future__ import annotations

import io
import json
import secrets
from datetime import datetime

from models.models import Homework, HomeworkQuestion, HomeworkSubmission, Question


def ensure_submit_code(session, homework_id: int) -> str:
    """生成并保存 6 位提交码；已有提交码时直接复用。"""
    hw = session.get(Homework, int(homework_id))
    if hw is None:
        raise ValueError("作业不存在。")
    if not hw.submit_code:
        hw.submit_code = f"{secrets.randbelow(10 ** 6):06d}"
        session.flush()
    return hw.submit_code


def get_homework_by_code(session, code: str) -> Homework:
    """按提交码查找作业。"""
    code = str(code or "").strip()
    hw = (session.query(Homework)
          .filter(Homework.submit_code == code,
                  Homework.is_template.is_(False)).first())
    if hw is None:
        raise ValueError("提交码无效或作业不存在。")
    return hw


def build_submit_qr_png(url: str) -> bytes:
    """生成提交链接二维码 PNG。"""
    import qrcode

    buffer = io.BytesIO()
    qrcode.make(url).save(buffer, format="PNG")
    return buffer.getvalue()


def ordered_questions(session, homework_id: int) -> list[tuple[int, Question]]:
    """按作业顺序返回题号和题目，题号从 1 开始。"""
    links = (session.query(HomeworkQuestion)
             .filter(HomeworkQuestion.homework_id == homework_id)
             .order_by(HomeworkQuestion.order, HomeworkQuestion.id).all())
    result = []
    for index, link in enumerate(links, start=1):
        question = session.get(Question, link.question_id)
        if question is not None:
            result.append((index, question))
    return result


def _norm_answer(value) -> str:
    return str(value or "").strip().lower().replace(" ", "")


def _is_objective_correct(question: Question, answer) -> bool:
    """判断选择/判断题答案是否正确。"""
    student_answer = _norm_answer(answer)
    right_answer = _norm_answer(question.answer)
    if question.question_type == "judge":
        true_values = {"正确", "对", "true", "t", "√", "是"}
        false_values = {"错误", "错", "false", "f", "×", "否"}
        if student_answer in true_values:
            student_answer = "正确"
        elif student_answer in false_values:
            student_answer = "错误"
    return student_answer == right_answer


def auto_grade_objective(session, homework_id: int,
                         answers: dict) -> tuple[float, int, int]:
    """按等权重批改客观题，返回百分制分数、答对题数和客观题总数。"""
    correct = total = 0
    for index, question in ordered_questions(session, homework_id):
        if question.question_type not in {"choice", "judge"}:
            continue
        total += 1
        if _is_objective_correct(question, answers.get(str(index))):
            correct += 1
    if total == 0:
        return 0.0, 0, 0
    return round(correct / total * 100, 2), correct, total


def save_submission(session, code: str, student_name: str,
                    answers: dict) -> HomeworkSubmission:
    """保存一名学生的在线提交，并自动批改客观题。"""
    student_name = str(student_name or "").strip()
    if not student_name:
        raise ValueError("请填写学生姓名。")
    hw = get_homework_by_code(session, code)
    score, _, _ = auto_grade_objective(session, hw.id, answers)

    old = (session.query(HomeworkSubmission)
           .filter(HomeworkSubmission.homework_id == hw.id,
                   HomeworkSubmission.student_name == student_name).first())
    if old is None:
        row = HomeworkSubmission(
            homework_id=hw.id, student_name=student_name,
            answers_json=json.dumps(answers, ensure_ascii=False), score=score)
        session.add(row)
    else:
        old.answers_json = json.dumps(answers, ensure_ascii=False)
        old.score = score
        old.submitted_at = datetime.now()
        row = old
    session.flush()
    return row


def list_submissions(session, homework_id: int) -> list[HomeworkSubmission]:
    """列出作业全部在线提交。"""
    return (session.query(HomeworkSubmission)
            .filter(HomeworkSubmission.homework_id == homework_id)
            .order_by(HomeworkSubmission.submitted_at.desc(),
                      HomeworkSubmission.id.desc()).all())


def submission_stats(session, homework_id: int) -> dict:
    """返回提交人数、客观题平均分等统计。"""
    rows = list_submissions(session, homework_id)
    scores = [row.score for row in rows if row.score is not None]
    return {
        "submitted_count": len(rows),
        "average_score": round(sum(scores) / len(scores), 2) if scores else None,
        "names": [row.student_name for row in rows],
    }


def update_manual_grade(session, submission_id: int,
                        score: float | None,
                        feedback: str = "") -> HomeworkSubmission:
    """老师手动修改提交分数和评语。"""
    row = session.get(HomeworkSubmission, int(submission_id))
    if row is None:
        raise ValueError("提交记录不存在。")
    if score is not None:
        row.score = max(0.0, min(100.0, float(score)))
    row.feedback = str(feedback or "").strip() or None
    session.flush()
    return row
