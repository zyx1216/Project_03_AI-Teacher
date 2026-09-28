# -*- coding: utf-8 -*-
"""v1.4.5 趋势范围、自定义分析线和历次成绩长表测试。"""

from datetime import date

import pandas as pd
import pytest

from utils import exam_service as es
from utils import stats


def _add_exam_scores(session, name, exam_date, subject="数学", full=100,
                     class_name="一班", values=None):
    exam = es.create_exam(
        session, name, exam_date=exam_date,
        full_scores={subject: full})
    session.flush()
    values = values or [("甲", 60), ("乙", 80)]
    es.import_scores(session, exam.id, [
        {"name": student, "class_name": class_name, "scores": {subject: score}}
        for student, score in values
    ])
    return exam


def test_custom_thresholds_and_three_bands():
    summary = stats.subject_summary(
        [50, 70, 80, 90], 100, pass_ratio=0.6, excellent_ratio=0.8,
        custom_bands=True)
    assert summary["pass_rate"] == 0.75
    assert summary["excellent_rate"] == 0.5
    assert [b["label"] for b in summary["bands"]] == [
        "未及格（<60%）", "及格（60%–80%）", "优秀（≥80%）"]
    assert [b["count"] for b in summary["bands"]] == [1, 1, 2]


def test_invalid_custom_thresholds_raise():
    with pytest.raises(ValueError):
        stats.pass_and_excellent([1, 2], 100, pass_ratio=0.8, excellent_ratio=0.7)


def test_analyze_exam_uses_thresholds(session):
    exam = _add_exam_scores(session, "月考", date(2026, 9, 1),
                            values=[("甲", 50), ("乙", 70), ("丙", 80)])
    data = es.analyze_exam(
        session, exam.id, thresholds={"pass_ratio": 0.7,
                                      "excellent_ratio": 0.8})
    assert data["thresholds"] == {"pass_ratio": 0.7, "excellent_ratio": 0.8}
    assert data["subject_stats"]["数学"]["pass_rate"] == round(2 / 3, 4)
    assert len(data["subject_stats"]["数学"]["bands"]) == 3


def test_analyze_subject_uses_thresholds(session):
    exam = _add_exam_scores(session, "月考", date(2026, 9, 1),
                            values=[("甲", 50), ("乙", 79), ("丙", 80)])
    data = es.analyze_subject(
        session, exam.id, "数学",
        thresholds={"pass_ratio": 0.8, "excellent_ratio": 0.9})
    assert data["stats"]["pass_rate"] == round(1 / 3, 4)
    assert data["stats"]["excellent_rate"] == 0


def test_create_exam_blocks_same_name_and_date(session):
    es.create_exam(session, "月考", exam_date=date(2026, 9, 1))
    session.flush()
    with pytest.raises(ValueError, match="同名、同日期"):
        es.create_exam(session, "月考", exam_date=date(2026, 9, 1))


def test_create_exam_allows_same_name_different_date(session):
    first = es.create_exam(session, "月考", exam_date=date(2026, 9, 1))
    second = es.create_exam(session, "月考", exam_date=date(2026, 10, 1))
    session.flush()
    assert first.id != second.id


def test_class_trend_exam_ids_filter(session):
    e1 = _add_exam_scores(session, "第一次月考", date(2026, 9, 1),
                          values=[("甲", 60)])
    e2 = _add_exam_scores(session, "期中考试", date(2026, 11, 1),
                          values=[("甲", 90)])
    trend = es.class_trend(session, class_name="一班", exam_ids=[e2.id])
    assert trend["exam_ids"] == [e2.id]
    assert trend["exams"] == ["期中考试"]
    assert trend["series"]["数学"] == [90.0]
    assert trend["labels"] == ["26秋·期中考试"]


def test_student_score_history_rows_and_filters(session):
    e1 = _add_exam_scores(session, "第一次月考", date(2026, 9, 1),
                          values=[("甲", 60), ("乙", 80)])
    e2 = _add_exam_scores(session, "期中考试", date(2026, 11, 1),
                          values=[("甲", 70), ("乙", 90)])
    rows = es.student_score_history_rows(session, class_name="一班")
    assert len(rows) == 4
    assert {r["学期"] for r in rows} == {"2026秋"}
    assert {r["学年"] for r in rows} == {"2026-2027学年"}
    assert {r["考试类型"] for r in rows} == {"月考", "期中"}
    first = next(r for r in rows if r["考试"] == "第一次月考" and r["姓名"] == "甲")
    second = next(r for r in rows if r["考试"] == "期中考试" and r["姓名"] == "甲")
    assert first["分数"] == 60 and first["科目班级排名"] == 2
    assert second["分数"] == 70 and second["科目班级排名"] == 2
    assert first["总分"] == 60 and second["总分班级排名"] == 2

    filtered = es.student_score_history_rows(session, exam_ids=[e1.id])
    assert {r["考试"] for r in filtered} == {"第一次月考"}
    assert len(filtered) == 2


def test_student_scores_over_time_exam_ids_filter(session):
    e1 = _add_exam_scores(session, "第一次月考", date(2026, 9, 1),
                          values=[("甲", 60)])
    _add_exam_scores(session, "期中考试", date(2026, 11, 1),
                     values=[("甲", 90)])
    student = es.exam_score_rows(session, e1.id)[0]["student_id"]
    history = es.student_scores_over_time(session, student, exam_ids=[e1.id])
    assert [h["exam_id"] for h in history] == [e1.id]
    assert history[0]["数学"] == 60
