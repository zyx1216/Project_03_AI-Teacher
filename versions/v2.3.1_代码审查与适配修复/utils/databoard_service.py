# -*- coding: utf-8 -*-
"""教学数据看板聚合服务（v1.9.8）。

只做确定性聚合，输出全部 JSON 安全的数据，供 modules/databoard.py 画图。
跨考试、跨学科比较统一使用得分率；原始分和满分同时保留。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from utils import analysis_settings, exam_service, full_score_service


def collect_rows(session, *, class_names=None, subject=None,
                 start_date=None, end_date=None):
    """按筛选条件收集考试成绩行；每行带原始分、满分和得分率。"""
    exams = [e for e in exam_service.list_exams(session)
             if _in_range(e, start_date, end_date)]
    rows = []
    for exam in exams:
        full_scores = full_score_service.get_exam_full_scores(session, exam.id)
        for row in exam_service.exam_score_rows(session, exam.id):
            if class_names and row.get("class_name") not in class_names:
                continue
            if subject:
                score = row.get(subject)
                full_score = full_scores.get(subject)
            else:
                present_subjects = [
                    item_subject for item_subject in full_scores
                    if row.get(item_subject) is not None]
                score = row.get("total")
                full_score = round(sum(
                    full_scores[item_subject] for item_subject in present_subjects), 2)
            if score is None:
                continue
            rows.append({
                "exam_id": exam.id,
                "exam_name": exam.name,
                "exam_date": exam.exam_date,
                "student_id": row["student_id"],
                "name": row["name"],
                "class_name": row["class_name"],
                "subject": subject or "总分",
                "score": score,
                "full_score": full_score,
                "rate": full_score_service.calc_rate(score, full_score),
            })
    return rows


def _in_range(exam, start_date, end_date):
    day = exam.exam_date
    if not isinstance(day, date):
        return True
    if start_date and day < start_date:
        return False
    if end_date and day > end_date:
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
        "metrics": _metrics(rows, thresholds),
        "class_trend": _class_trend(rows),
        "subject_compare": _subject_compare(
            session, class_names=class_names, start_date=start_date,
            end_date=end_date),
        "score_bands": _score_bands(rows),
        "ranking": _ranking(rows),
        "has_data": bool(rows),
        "thresholds": thresholds,
    }


def _metrics(rows, thresholds):
    """核心指标；跨满分场景平均分改为平均得分率。"""
    rates = [r["rate"] for r in rows if r["rate"] is not None]
    scores = [r["score"] for r in rows]
    student_ids = {r["student_id"] for r in rows}
    exam_ids = {r["exam_id"] for r in rows}
    pass_line = round(float(thresholds.get("pass_ratio", 0.6)) * 100, 1)
    excellent_line = round(float(thresholds.get("excellent_ratio", 0.85)) * 100, 1)
    return {
        "student_count": len(student_ids),
        "exam_count": len(exam_ids),
        "average_rate": round(sum(rates) / len(rates), 1) if rates else 0,
        "raw_average": round(sum(scores) / len(scores), 1) if scores else 0,
        "pass_rate": _rate_count(rates, pass_line),
        "excellent_rate": _rate_count(rates, excellent_line),
    }


def _rate_count(rates, line):
    """统计得分率达到阈值的比例。"""
    if not rates:
        return 0.0
    return round(sum(1 for value in rates if value >= line) / len(rates) * 100, 1)


def _class_trend(rows):
    """各班历次考试平均分、满分和得分率走势。"""
    groups = defaultdict(list)
    for r in rows:
        groups[r["class_name"]].append(r)
    series = {}
    for class_name, items in groups.items():
        items.sort(key=lambda x: (x["exam_date"] or date.min, x["exam_name"]))
        per_exam = defaultdict(list)
        for item in items:
            per_exam[(item["exam_name"], item["exam_date"])].append(item)
        points = []
        for (exam_name, exam_day), group in per_exam.items():
            scores = [x["score"] for x in group]
            full_scores = [x["full_score"] for x in group]
            rates = [x["rate"] for x in group if x["rate"] is not None]
            average = round(sum(scores) / len(scores), 1)
            full_score = round(sum(full_scores) / len(full_scores), 1)
            points.append({
                "exam_name": exam_name,
                "date": exam_day.isoformat() if hasattr(exam_day, "isoformat") else "",
                "average": average,
                "full_score": full_score,
                "rate": round(sum(rates) / len(rates), 1) if rates else None,
            })
        series[class_name] = points
    return series


def _subject_compare(session, *, class_names=None, start_date=None,
                     end_date=None):
    """各学科成绩按得分率对比，原始分按成绩条数取平均。"""
    totals = defaultdict(lambda: {"score": 0.0, "full": 0.0, "count": 0})
    exams = [e for e in exam_service.list_exams(session)
             if _in_range(e, start_date, end_date)]
    for exam in exams:
        full_scores = full_score_service.get_exam_full_scores(session, exam.id)
        for row in exam_service.exam_score_rows(session, exam.id):
            if class_names and row.get("class_name") not in class_names:
                continue
            for subject, score in ((s, row.get(s)) for s in full_scores):
                if score is None:
                    continue
                full = full_scores[subject]
                bucket = totals[subject]
                bucket["score"] += float(score)
                bucket["full"] += float(full)
                bucket["count"] += 1
    result = []
    for subject in sorted(totals):
        item = totals[subject]
        average = round(item["score"] / item["count"], 1)
        full_score = round(item["full"] / item["count"], 1)
        rate = round(item["score"] / item["full"] * 100, 1) if item["full"] else None
        result.append({
            "subject": subject, "average": average,
            "full_score": full_score, "rate": rate,
        })
    return result


def _score_bands(rows):
    """按五个标准得分率段统计人数。"""
    bands = full_score_service.rate_bands()
    result = [{"band": item["label"], "count": 0} for item in bands]
    for row in rows:
        rate = row.get("rate")
        if rate is None:
            continue
        for index, band in enumerate(bands):
            if band["low"] <= rate < band["high"]:
                result[index]["count"] += 1
                break
    return result


def _ranking(rows):
    """学生按平均得分率排名，前 20；同时保留原始均分和平均满分。"""
    per_student = defaultdict(list)
    for r in rows:
        per_student[(r["student_id"], r["name"])].append(r)
    ranked = []
    for (student_id, name), items in per_student.items():
        rates = [x["rate"] for x in items if x["rate"] is not None]
        scores = [x["score"] for x in items]
        full_scores = [x["full_score"] for x in items]
        ranked.append({
            "student_id": student_id, "name": name,
            "average": round(sum(scores) / len(scores), 1),
            "full_score": round(sum(full_scores) / len(full_scores), 1),
            "rate": round(sum(rates) / len(rates), 1) if rates else None,
        })
    ranked.sort(key=lambda x: -(x["rate"] or 0))
    return ranked[:20]
