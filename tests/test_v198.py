# -*- coding: utf-8 -*-
"""v1.9.8 分数图表满分适配测试。

全程使用临时 SQLite/JSON，不读取真实 data，不调用真实 AI。
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from streamlit.testing.v1 import AppTest

from models.models import Base, Exam, Homework, Score, Student
from tests.test_app_smoke import _isolated_app_code, goto_top
from utils import full_score_service


# ---------------------------------------------------------------------------
# 辅助构造
# ---------------------------------------------------------------------------

def _make_exam(session, name="月考", exam_day=None, grade="高一",
                full_scores=None):
    exam = Exam(
        name=name, exam_date=exam_day or date.today(), grade=grade,
        full_scores=json.dumps(full_scores or {}, ensure_ascii=False))
    session.add(exam)
    session.flush()
    return exam


def _add_score(session, exam_id, student_name, class_name, subject, score):
    student = Student(name=student_name, class_name=class_name)
    session.add(student)
    session.flush()
    session.add(Score(
        exam_id=exam_id, student_id=student.id,
        subject=subject, score=score))
    return student


# ---------------------------------------------------------------------------
# 统一满分服务
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "grade, expected",
    [
        ("三年级", {"语文": 100, "数学": 100, "英语": 100}),
        ("初二", {"语文": 120, "数学": 120, "英语": 120}),
        ("高一", {"语文": 150, "数学": 150, "英语": 150}),
        ("未知年级", {"语文": 100, "数学": 100, "英语": 100}),
    ],
)
def test_grade_default_full_scores(grade, expected):
    scores = full_score_service.get_grade_default_full_scores(grade)
    for subject, value in expected.items():
        assert scores[subject] == value
    if grade in {"初二", "高一"}:
        assert scores["物理"] == 100


def test_exam_full_scores_priority_and_invalid_fallback(session):
    exam = _make_exam(
        session, grade="高一",
        full_scores={"数学": 120, "物理": 0, "语文": "坏值"})
    scores = full_score_service.get_exam_full_scores(session, exam.id)
    assert scores["数学"] == 120
    assert scores["物理"] == 100
    assert scores["语文"] == 150


def test_corrupt_full_scores_json_falls_back(session):
    exam = _make_exam(session, grade="初二")
    exam.full_scores = "{坏JSON"
    scores = full_score_service.get_exam_full_scores(session, exam.id)
    assert scores["数学"] == 120


@pytest.mark.parametrize(
    "score, full, expected",
    [(90, 150, 60.0), (None, 100, None), (60, 0, None), ("x", 100, None)],
)
def test_calc_rate(score, full, expected):
    assert full_score_service.calc_rate(score, full) == expected


# ---------------------------------------------------------------------------
# 数据看板服务
# ---------------------------------------------------------------------------

def test_board_rows_carry_full_score_and_rate(session):
    from utils import databoard_service
    exam = _make_exam(session, full_scores={"数学": 100})
    _add_score(session, exam.id, "甲", "高一1班", "数学", 90)
    session.commit()

    subject_rows = databoard_service.collect_rows(
        session, subject="数学")
    total_rows = databoard_service.collect_rows(session)
    assert subject_rows[0]["full_score"] == 100
    assert subject_rows[0]["rate"] == 90
    assert total_rows[0]["full_score"] == 100
    assert total_rows[0]["rate"] == 90


def test_board_metrics_bands_ranking_and_subject_compare(session):
    from utils import databoard_service
    exam = _make_exam(session, full_scores={"数学": 100})
    _add_score(session, exam.id, "甲", "高一1班", "数学", 90)
    _add_score(session, exam.id, "乙", "高一1班", "数学", 50)
    session.commit()

    data = databoard_service.board_data(session, subject="数学")
    metrics = data["metrics"]
    assert metrics["student_count"] == 2
    assert metrics["average_rate"] == 70
    assert metrics["pass_rate"] == 50
    assert metrics["excellent_rate"] == 50

    bands = {item["band"]: item["count"]
             for item in data["score_bands"]}
    assert bands == {"不及格": 1, "及格": 0, "中等": 0,
                     "良好": 0, "优秀": 1}

    assert data["ranking"][0]["name"] == "甲"
    assert data["ranking"][0]["rate"] == 90
    subject = data["subject_compare"][0]
    assert subject["subject"] == "数学"
    assert subject["full_score"] == 100
    assert subject["rate"] == 70


def test_board_class_and_date_filters(session):
    from utils import databoard_service
    old_exam = _make_exam(
        session, name="旧考试", exam_day=date.today() - timedelta(days=30),
        full_scores={"数学": 100})
    new_exam = _make_exam(session, full_scores={"数学": 100})
    _add_score(session, old_exam.id, "旧生", "高一旧班", "数学", 10)
    _add_score(session, new_exam.id, "新生", "高一新班", "数学", 90)
    session.commit()

    by_class = databoard_service.board_data(
        session, class_names=["高一新班"], subject="数学")
    assert by_class["metrics"]["student_count"] == 1
    by_date = databoard_service.board_data(
        session, subject="数学", start_date=date.today() - timedelta(days=7))
    assert by_date["metrics"]["student_count"] == 1


def test_board_empty_data(session):
    from utils import databoard_service
    data = databoard_service.board_data(session)
    assert data["has_data"] is False
    assert data["metrics"]["average_rate"] == 0


def test_class_trend_contains_full_score_and_rate(session):
    from utils import exam_service
    exam = _make_exam(session, full_scores={"数学": 100})
    _add_score(session, exam.id, "甲", "高一1班", "数学", 80)
    session.commit()

    trend = exam_service.class_trend(
        session, "高一1班", subject="数学", exam_ids=[exam.id])
    point = trend["exam_meta"][0]
    assert point["full_scores"]["数学"] == 100
    assert point["values"]["数学"] == 80


def test_subject_summary_keeps_three_bands_and_adds_rate_bands(session):
    from utils import stats
    summary = stats.subject_summary(
        [90, 50], 100, custom_bands=True)
    assert len(summary["bands"]) == 3
    rate_bands = {item["label"]: item["count"]
                   for item in summary["rate_bands"]}
    assert rate_bands["优秀"] == 1
    assert rate_bands["不及格"] == 1


def test_compare_exam_classes_adds_mean_rate(session):
    from utils import class_compare_service
    exam = _make_exam(session, full_scores={"数学": 100})
    _add_score(session, exam.id, "甲", "高一1班", "数学", 80)
    _add_score(session, exam.id, "乙", "高一2班", "数学", 60)
    session.commit()

    result = class_compare_service.compare_exam_classes(
        session, exam.id, ["高一1班", "高一2班"], subject="数学")
    assert result["classes"][0]["mean_rate"] == 80
    assert result["classes"][1]["mean_rate"] == 60


def test_compare_class_trends_rate_series(session):
    from utils import class_compare_service
    exam = _make_exam(session, full_scores={"数学": 100})
    _add_score(session, exam.id, "甲", "高一1班", "数学", 80)
    _add_score(session, exam.id, "乙", "高一2班", "数学", 60)
    session.commit()

    result = class_compare_service.compare_class_trends(
        session, ["高一1班", "高一2班"], subject="数学", exam_ids=[exam.id])
    assert result["rate_series"]["高一1班"] == [80.0]
    assert result["rate_series"]["高一2班"] == [60.0]
    assert result["full_scores"] == [100.0]


def test_homework_full_score_sources(session):
    hw1 = Homework(name="仅登记总分", total_score=80)
    hw2 = Homework(name="无配置")
    session.add_all([hw1, hw2])
    session.flush()
    assert full_score_service.get_homework_full_score(session, hw1.id) == 80
    assert full_score_service.get_homework_full_score(session, hw2.id) == 100


# ---------------------------------------------------------------------------
# AppTest
# ---------------------------------------------------------------------------

def _seed_app_db(path):
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    Base.metadata.create_all(engine)
    sl = sessionmaker(bind=engine)
    session = sl()
    exam = _make_exam(session, full_scores={"数学": 100})
    _add_score(session, exam.id, "甲", "高一1班", "数学", 90)
    _add_score(session, exam.id, "乙", "高一1班", "数学", 50)

    hw = Homework(
        name="数学作业", subject="数学", grade="高一",
        class_name="高一1班", total_score=100)
    session.add(hw)
    session.commit()
    session.close()
    engine.dispose()


def _app(tmp_path, name):
    db_file = tmp_path / f"{name}.db"
    _seed_app_db(db_file)
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / f"{name}_feature.json"),
        default_timeout=30)
    at.run()
    return at


def test_app_databoard_renders_and_switches_score_mode(tmp_path):
    at = _app(tmp_path, "databoard")
    goto_top(at, "📊 数据看板")
    assert not at.exception, [str(x) for x in at.exception]
    radio = next(x for x in at.radio
                 if x.key == "databoard_trend_score_mode")
    radio.set_value("得分率").run()
    assert not at.exception, [str(x) for x in at.exception]


def test_app_analysis_exam_page(tmp_path):
    at = _app(tmp_path, "analysis_exam")
    at.session_state["app_top_page"] = "📊 学情"
    at.run()
    radio = next(x for x in at.sidebar.radio if x.key == "analysis_tab")
    radio.set_value("考试分析").run()
    assert not at.exception, [str(x) for x in at.exception]


def test_app_analysis_trend_page(tmp_path):
    at = _app(tmp_path, "analysis_trend")
    at.session_state["app_top_page"] = "📊 学情"
    at.run()
    radio = next(x for x in at.sidebar.radio if x.key == "analysis_tab")
    radio.set_value("趋势分析").run()
    assert not at.exception, [str(x) for x in at.exception]


def test_app_homework_analysis_and_dashboard(tmp_path):
    at = _app(tmp_path, "homework_dashboard")
    at.session_state["app_top_page"] = "📝 学业测评"
    at.run()
    radio = next(x for x in at.sidebar.radio if x.key == "homework_tab")
    # v2.4.0：作业分析并入「✏️ 批改与分析」。
    radio.set_value("✏️ 批改与分析").run()
    assert not at.exception, [str(x) for x in at.exception]

    goto_top(at, "🏠 首页")
    assert not at.exception, [str(x) for x in at.exception]
