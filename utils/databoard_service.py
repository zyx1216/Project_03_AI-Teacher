# -*- coding: utf-8 -*-
"""教学数据看板聚合服务（v1.9.7）。

只做确定性聚合，输出全部 JSON 安全的数据，供 modules/databoard.py 画图。
成绩来源为普通考试的 Score 表；知识点掌握度复用 knowledge_graph_service。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from models.models import Exam, Score, Student
from utils import analysis_settings, exam_service

# 分数段定义（百分制，左闭右开，最后一段闭区间）。
SCORE_BANDS = [
    ("0-59", 0, 60),
    ("60-69", 60, 70),
    ("70-79", 70, 80),
    ("80-89", 80, 90),
    ("90-100", 90, 101),
]


def collect_rows(session, *, class_names=None, subject=None,
                 start_date=None, end_date=None):
    """按筛选条件收集考试成绩行（每学生每场考试一行的宽表）。"""
    exams = [e for e in exam_service.list_exams(session)
             if _in_range(e, start_date, end_date)]
    rows = []
    for exam in exams:
        for row in exam_service.exam_score_rows(session, exam.id):
            if class_names and row.get("class_name") not in class_names:
                continue
            value = _pick_score(row, subject)
            if value is None:
                continue
            rows.append({
                "exam_id": exam.id,
                "exam_name": exam.name,
                "exam_date": exam.exam_date,
                "student_id": row["student_id"],
                "name": row["name"],
                "class_name": row["class_name"],
                "subject": subject or "总分",
                "score": value,
            })
    return rows


def _pick_score(row, subject):
    """subject 为空取总分，否则取该科分数。"""
    if not subject:
        return row.get("total")
    return row.get(subject)


def _in_range(exam, start_date, end_date):
    day = exam.exam_date
    if isinstance(day, date):
        d = day
    else:
        return True
    if start_date and d < start_date:
        return False
    if end_date and d > end_date:
        return False
    return True


def board_data(session, *, class_names=None, subject=None,
               start_date=None, end_date=None) -> dict:
    """看板全量聚合：指标、趋势、对比、分布、排名。"""
    rows = collect_rows(
        session, class_names=class_names, subject=subject,
        start_date=start_date, end_date=end_date)
    thresholds = analysis_settings.load_thresholds()
    return {
        "metrics": _metrics(rows),
        "class_trend": _class_trend(rows),
        "subject_compare": _subject_compare(session, rows, class_names),
        "score_bands": _score_bands(rows),
        "ranking": _ranking(rows),
        "has_data": bool(rows),
        "thresholds": thresholds,
    }


def _metrics(rows):
    """5 个核心指标。"""
    scores = [r["score"] for r in rows]
    student_ids = {r["student_id"] for r in rows}
    exam_ids = {r["exam_id"] for r in rows}
    n = len(scores)
    average = round(sum(scores) / n, 1) if n else 0
    return {
        "student_count": len(student_ids),
        "exam_count": len(exam_ids),
        "average": average,
        "pass_rate": _rate(scores, 60),
        "excellent_rate": _rate(scores, 85),
    }


def _rate(scores, line):
    """达到分数线的占比（百分值，保留1位）。"""
    if not scores:
        return 0.0
    hit = sum(1 for s in scores if s >= line)
    return round(hit / len(scores) * 100, 1)


def _class_trend(rows):
    """各班历次考试平均分走势。"""
    groups = defaultdict(list)
    for r in rows:
        groups[r["class_name"]].append(
            (r["exam_date"], r["exam_name"], r["score"]))
    series = {}
    for class_name, items in groups.items():
        items.sort(key=lambda x: (x[0] or date.min, x[1]))
        # 同名/同日考试取平均，避免重复点。
        per_exam = defaultdict(list)
        for day, name, score in items:
            per_exam[(name, day)].append(score)
        series[class_name] = [
            {"exam_name": key[0],
             "date": key[1].isoformat() if hasattr(key[1], "isoformat") else "",
             "average": round(sum(v) / len(v), 1)}
            for key, v in per_exam.items()]
    return series


def _subject_compare(session, rows, class_names):
    """各学科平均分对比（取筛选范围内全部学科）。"""
    # 直接从 Score 聚合，避免 subject 过滤把其他科剔掉。
    q = session.query(Score)
    student_ids = {r["student_id"] for r in rows}
    if student_ids:
        q = q.filter(Score.student_id.in_(student_ids))
    totals = defaultdict(list)
    valid_students = (
        session.query(Student).filter(Student.id.in_(student_ids)).all()
        if student_ids else [])
    class_map = {s.id: s.class_name for s in valid_students}
    for s in q.all():
        if class_names and class_map.get(s.student_id) not in class_names:
            continue
        if s.score is not None:
            totals[s.subject].append(s.score)
    return [{"subject": k, "average": round(sum(v) / len(v), 1)}
            for k, v in sorted(totals.items())]


def _score_bands(rows):
    """分数段人数分布。"""
    result = []
    scores = [r["score"] for r in rows]
    for label, low, high in SCORE_BANDS:
        count = sum(1 for s in scores if low <= s < high)
        result.append({"band": label, "count": count})
    return result


def _ranking(rows):
    """学生平均分排名（取范围内该学生的平均分，降序，前 20）。"""
    per_student = defaultdict(list)
    for r in rows:
        per_student[(r["student_id"], r["name"])].append(r["score"])
    ranked = [
        {"student_id": key[0], "name": key[1],
         "average": round(sum(v) / len(v), 1)}
        for key, v in per_student.items()]
    ranked.sort(key=lambda x: -x["average"])
    return ranked[:20]
