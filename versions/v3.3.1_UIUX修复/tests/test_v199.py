# -*- coding: utf-8 -*-
"""v1.9.9 趋势图样式优化测试。

全程使用临时 SQLite/JSON，不读取真实 data，不调用真实 AI。
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from streamlit.testing.v1 import AppTest

from models.models import Base, Exam, Homework, Score, Student
from tests.test_app_smoke import _isolated_app_code, goto_top
from utils import chart_service


# ---------------------------------------------------------------------------
# 纯函数 trend_header
# ---------------------------------------------------------------------------

def test_trend_header_full():
    header = chart_service.trend_header(1, "月考", "2026-09-15", 150)
    assert "<br>" in header
    assert "\n" not in header
    for text in ("第1次考试", "考试：月考", "日期：2026-09-15", "满分：150"):
        assert text in header


def test_trend_header_empty_date_and_full():
    header = chart_service.trend_header(3, "期末", "", None)
    assert "日期：未知" in header
    assert "满分" not in header
    assert "第3次考试" in header


# ---------------------------------------------------------------------------
# build_trend_figure 样式
# ---------------------------------------------------------------------------

def _headers(points):
    return [chart_service.trend_header(
        i, p["name"], p["date"], p.get("full"))
        for i, p in enumerate(points, start=1)]


def _line(name, points, headers, *, with_full=True):
    pmap = {}
    for point, header in zip(points, headers):
        if point.get("value") is None:
            continue
        pmap[header] = {
            "score": point["value"],
            "full": point.get("full"),
            "rate": point.get("rate"),
        }
    return {"name": name, "points": pmap}


def test_build_trend_figure_layout_and_trace():
    points = [
        {"name": "月考一", "date": "2026-03-01", "full": 150,
         "value": 90, "rate": 60.0},
        {"name": "月考二", "date": "2026-04-01", "full": 150,
         "value": 120, "rate": 80.0},
    ]
    headers = _headers(points)
    lines = [_line("高一1班", points, headers)]
    fig = chart_service.build_trend_figure(
        lines, headers, title="班级趋势", y_title="平均分")

    layout = fig.layout
    assert layout.height == 420
    assert layout.hovermode == "x unified"
    assert layout.xaxis.showticklabels is False
    assert layout.hoverlabel.align == "left"
    assert layout.hoverlabel.font.size == 13

    trace = fig.data[0]
    assert trace.line.width == 3
    assert trace.marker.size == 10
    assert trace.connectgaps is False
    # 悬停每线一行且含原始分与得分率
    hover = trace.customdata
    assert all("<br>" not in str(x) for x in hover)
    assert "高一1班：90（60%）" in hover


def test_build_trend_figure_rate_only_and_fixed_percent():
    points = [
        {"name": "月考一", "date": "2026-03-01", "full": 120,
         "value": 60, "rate": 50.0},
    ]
    headers = _headers(points)
    lines = [_line("初二1班", points, headers)]
    fig = chart_service.build_trend_figure(
        lines, headers, title="趋势", y_title="得分率(%)",
        fixed_percent=True, rate_only=True)
    assert list(fig.layout.yaxis.range) == [0, 100]
    assert "初二1班：50%" in fig.data[0].customdata


def test_missing_point_aligns_and_breaks():
    # 两次考试；二班缺第一场，统一类目下不应错位
    p1 = {"name": "月考一", "date": "2026-03-01", "full": 150,
          "value": 90, "rate": 60.0}
    p2a = {"name": "月考二", "date": "2026-04-01", "full": 150,
           "value": 120, "rate": 80.0}
    p2b = {"name": "月考二", "date": "2026-04-01", "full": 150,
           "value": 105, "rate": 70.0}
    points_all = [p1, p2a]
    headers = _headers(points_all)
    line_a = _line("一班", points_all, headers)
    line_b = _line("二班", [
        {"name": "月考一", "date": "2026-03-01", "full": 150,
         "value": None, "rate": None}, p2b], headers)
    fig = chart_service.build_trend_figure(
        [line_a, line_b], headers, title="对比", y_title="平均分")
    b_trace = fig.data[1]
    # 二班只剩月考二一个点，且 x 落在第二个类目
    assert len(b_trace.x) == 1
    assert b_trace.x[0] == headers[1]


# ---------------------------------------------------------------------------
# AppTest 辅助
# ---------------------------------------------------------------------------

def _seed_db(path, *, exams=2, with_homework_answers=False):
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    Base.metadata.create_all(engine)
    sl = sessionmaker(bind=engine)
    session = sl()
    base_day = date.today() - timedelta(days=40)
    for i in range(exams):
        exam = Exam(
            name=f"月考{i + 1}", exam_date=base_day + timedelta(days=30 * i),
            grade="高一", full_scores='{"数学": 150}')
        session.add(exam)
        session.flush()
        for name in ("甲", "乙"):
            student = Student(name=name, class_name="高一1班")
            session.add(student)
            session.flush()
            session.add(Score(
                exam_id=exam.id, student_id=student.id,
                subject="数学", score=90 + i * 10))
    session.commit()
    session.close()
    engine.dispose()


def _app(tmp_path, name, **kwargs):
    db_file = tmp_path / f"{name}.db"
    _seed_db(db_file, **kwargs)
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / f"{name}_feature.json"),
        default_timeout=30)
    at.run()
    return at


# ---------------------------------------------------------------------------
# 数据看板
# ---------------------------------------------------------------------------

def test_databoard_empty_no_exception(tmp_path):
    db_file = tmp_path / "empty.db"
    engine = create_engine(f"sqlite:///{db_file.as_posix()}")
    Base.metadata.create_all(engine)
    engine.dispose()
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / "f.json"),
        default_timeout=30)
    at.run()
    goto_top(at, "📊 数据看板")
    assert not at.exception, [str(x) for x in at.exception]


def test_databoard_switch_score_mode(tmp_path):
    at = _app(tmp_path, "board")
    goto_top(at, "📊 数据看板")
    radio = next(x for x in at.radio
                 if x.key == "databoard_trend_score_mode")
    radio.set_value("得分率").run()
    assert not at.exception, [str(x) for x in at.exception]
    radio.set_value("原始分").run()
    assert not at.exception, [str(x) for x in at.exception]


# ---------------------------------------------------------------------------
# 学情趋势分析
# ---------------------------------------------------------------------------

def test_trend_page_ranges_and_time_filter(tmp_path):
    at = _app(tmp_path, "trend")
    at.session_state["app_top_page"] = "📊 学情"
    at.run()
    at.sidebar.button(key="analysis_sub_趋势分析").click().run()
    assert not at.exception, [str(x) for x in at.exception]

    range_box = at.selectbox(key="trend_range")
    for value in ("最近 3 次", "最近 10 次", "全部"):
        range_box.set_value(value).run()
        assert not at.exception, [str(x) for x in at.exception]

    # 单科原始分/得分率切换
    subj_box = at.selectbox(key="trend_subject")
    subj_box.set_value("数学").run()
    mode = at.radio(key="trend_class_score_mode")
    mode.set_value("原始分").run()
    assert not at.exception, [str(x) for x in at.exception]
    mode.set_value("得分率").run()
    assert not at.exception, [str(x) for x in at.exception]


def test_trend_student_switch(tmp_path):
    at = _app(tmp_path, "student")
    at.session_state["app_top_page"] = "📊 学情"
    at.run()
    at.sidebar.button(key="analysis_sub_趋势分析").click().run()
    mode = at.radio(key="trend_student_score_mode")
    mode.set_value("原始分").run()
    assert not at.exception, [str(x) for x in at.exception]
    # 柱状图模式也无异常
    at.radio(key="student_trend_chart_type").set_value("柱状图").run()
    assert not at.exception, [str(x) for x in at.exception]


# ---------------------------------------------------------------------------
# 知识点掌握追踪（需要逐题作答数据）
# ---------------------------------------------------------------------------

def _seed_answer_db(path):
    import json as _json
    from datetime import datetime
    from models.models import (
        HomeworkAnswer, HomeworkQuestion, Question)
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    Base.metadata.create_all(engine)
    sl = sessionmaker(bind=engine)
    session = sl()
    student = Student(name="甲", class_name="高一1班")
    session.add(student)
    session.flush()
    for i, kp in enumerate(("函数", "方程")):
        question = Question(
            content=f"{kp}题", question_type="choice", difficulty=1,
            knowledge_points=_json.dumps([kp], ensure_ascii=False),
            answer="A", analysis="解析", subject="数学", grade="高一",
            source="manual", status="approved")
        session.add(question)
        session.flush()
        for j in range(2):
            done = datetime(2026, 1, 1 + j * 30)
            homework = Homework(
                name=f"作业{j + 1}", homework_type="after_class",
                subject="数学", grade="高一", status="completed",
                completed_at=done, created_at=done,
                class_name="高一1班")
            session.add(homework)
            session.flush()
            link = HomeworkQuestion(
                homework_id=homework.id, question_id=question.id,
                order=1, score=10)
            session.add(link)
            # 两次作业，第二次正确率更高
            rate = 0.5 + 0.4 * j
            session.add(HomeworkAnswer(
                homework_id=homework.id, student_id=student.id,
                question_id=question.id, order_no=1,
                earned_score=round(rate * 10, 2), is_correct=rate >= 0.6,
                created_at=done))
    session.commit()
    session.close()
    engine.dispose()


def test_class_knowledge_tracking(tmp_path):
    db_file = tmp_path / "kp.db"
    _seed_answer_db(db_file)
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / "f.json"),
        default_timeout=30)
    at.run()
    # v2.4.0：知识点并入「考试分析」的第二标签。
    at.session_state["app_top_page"] = "📊 学情"
    at.run()
    at.sidebar.button(key="analysis_sub_考试分析").click().run()
    assert not at.exception, [str(x) for x in at.exception]


def test_personal_knowledge_tracking(tmp_path):
    db_file = tmp_path / "pkp.db"
    _seed_answer_db(db_file)
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / "f.json"),
        default_timeout=30)
    at.run()
    at.session_state["app_top_page"] = "📊 学情"
    at.run()
    at.sidebar.button(key="analysis_sub_学生画像").click().run()
    assert not at.exception, [str(x) for x in at.exception]

