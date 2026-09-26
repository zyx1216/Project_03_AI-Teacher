# -*- coding: utf-8 -*-
"""学生知识图谱服务（v1.9.0）。

掌握度口径：
- 只用逐题批改的 HomeworkAnswer，不把考试总分分摊到知识点；
- 单条作答权重 = 时间衰减权重 × 难度权重；
- 时间权重按半衰期：0.5 ** (距今天数 / decay_days)；
- 难度权重：基础 1.0、中等 1.3、拓展 1.6；
- 有 earned_score 且题目有分值时按得分率；否则按 is_correct 取 1/0。
"""

from __future__ import annotations

from datetime import datetime

from models.models import (
    HomeworkAnswer, HomeworkQuestion, Question, Student,
)
from utils.app_config import DEFAULT_SUBJECT
from utils import question_service as qs

DIFFICULTY_WEIGHT = {1: 1.0, 2: 1.3, 3: 1.6}


def _answer_rate(ans: HomeworkAnswer, question: Question,
                 link: HomeworkQuestion | None) -> float | None:
    """取单条作答的得分率；无法判定返回 None。"""
    if ans.earned_score is not None and link is not None and link.score:
        rate = float(ans.earned_score) / float(link.score)
        return min(1.0, max(0.0, rate))
    if ans.is_correct is not None:
        return 1.0 if ans.is_correct else 0.0
    return None


def mastery_color(rate: float) -> str:
    """红黄绿分级：<60 红，60-80 黄，>80 绿。"""
    if rate < 0.6:
        return "red"
    if rate <= 0.8:
        return "yellow"
    return "green"


def build_mastery(session, subject, grade=None, class_names=None,
                  student_id=None, homework_ids=None,
                  decay_days=180) -> dict:
    """构建学生 × 知识点掌握度。

    返回 {students, knowledge_points, matrix, personal, weak_top5, recommendations}
    matrix：{student_id: {kp: 百分制掌握度}}
    """
    subject = subject or DEFAULT_SUBJECT
    today = datetime.now()

    q = (session.query(HomeworkAnswer, Question, HomeworkQuestion, Student)
         .join(Question, HomeworkAnswer.question_id == Question.id)
         .join(Student, HomeworkAnswer.student_id == Student.id)
         .outerjoin(HomeworkQuestion,
                    (HomeworkQuestion.homework_id == HomeworkAnswer.homework_id)
                    & (HomeworkQuestion.question_id == HomeworkAnswer.question_id))
         .filter(Question.subject == subject))
    if grade:
        q = q.filter(Question.grade == grade)
    if class_names:
        q = q.filter(Student.class_name.in_(list(class_names)))
    if student_id is not None:
        q = q.filter(Student.id == student_id)
    if homework_ids:
        q = q.filter(HomeworkAnswer.homework_id.in_(list(homework_ids)))
    rows = q.all()

    # acc[student_id][kp] = {"weighted": 加权得分和, "weight": 权重和}
    acc: dict[int, dict[str, dict]] = {}
    student_meta: dict[int, Student] = {}

    for ans, question, link, stu in rows:
        rate = _answer_rate(ans, question, link)
        if rate is None:
            continue
        days = (today - (ans.created_at or today)).days
        time_weight = 0.5 ** (max(0, days) / decay_days)
        weight = time_weight * DIFFICULTY_WEIGHT.get(question.difficulty, 1.3)
        kps = qs.knowledge_points_list(question) or ["未标注"]
        bucket = acc.setdefault(stu.id, {})
        student_meta[stu.id] = stu
        for kp in kps:
            item = bucket.setdefault(kp, {"weighted": 0.0, "weight": 0.0})
            item["weighted"] += rate * weight
            item["weight"] += weight

    # 汇总成百分制矩阵。
    matrix: dict[int, dict[str, float]] = {}
    all_kps: set[str] = set()
    for sid, kp_map in acc.items():
        matrix[sid] = {}
        for kp, item in kp_map.items():
            rate = item["weighted"] / item["weight"] if item["weight"] else 0.0
            matrix[sid][kp] = round(rate * 100, 1)
            all_kps.add(kp)

    personal = _personal_lists(matrix, student_meta)
    weak_top5 = _weak_top5(matrix, student_meta)
    recommendations = _recommend_questions(session, subject, weak_top5)

    return {
        "subject": subject,
        "students": [{"student_id": sid, "name": s.name,
                      "class_name": s.class_name}
                     for sid, s in sorted(student_meta.items())],
        "knowledge_points": sorted(all_kps),
        "matrix": matrix,
        "personal": personal,
        "weak_top5": weak_top5,
        "recommendations": recommendations,
    }


def _personal_lists(matrix, student_meta) -> list[dict]:
    """每个学生的个人掌握列表（含红黄绿等级）。"""
    result = []
    for sid, kp_map in matrix.items():
        stu = student_meta.get(sid)
        items = [{"knowledge_point": kp, "rate": rate,
                  "color": mastery_color(rate / 100)}
                 for kp, rate in kp_map.items()]
        items.sort(key=lambda x: x["rate"])
        result.append({
            "student_id": sid,
            "name": stu.name if stu else str(sid),
            "class_name": stu.class_name if stu else None,
            "items": items,
        })
    return result


def _weak_top5(matrix, student_meta, top_n: int = 5) -> list[dict]:
    """全班平均掌握度最低的 Top5 知识点。"""
    totals: dict[str, list[float]] = {}
    for sid, kp_map in matrix.items():
        for kp, rate in kp_map.items():
            totals.setdefault(kp, []).append(rate)
    ranked = sorted(
        ((kp, round(sum(v) / len(v), 1)) for kp, v in totals.items()),
        key=lambda x: x[1])
    return [{"knowledge_point": kp, "avg_rate": rate,
             "color": mastery_color(rate / 100)}
            for kp, rate in ranked[:top_n]]


def _recommend_questions(session, subject, weak_top5) -> dict:
    """按薄弱点推荐同学科、已审核题目 ID。"""
    weak_kps = [w["knowledge_point"] for w in weak_top5
                if w["knowledge_point"] != "未标注"]
    pool = qs.list_questions(session, status="approved", subject=subject)
    recs: dict[str, list[int]] = {}
    for kp in weak_kps:
        ids = [q.id for q in pool
               if kp in qs.knowledge_points_list(q)][:5]
        if ids:
            recs[kp] = ids
    return recs
