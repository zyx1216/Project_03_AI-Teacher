# -*- coding: utf-8 -*-
"""v1.8.2 折叠导航与学期自定义测试。

- 服务层：学期配置读写、周次计算、学期周、进度；
- AppTest：折叠导航结构、子功能直接渲染与状态保持、搜索四类跳转、日历两视图。
全部用临时 SQLite / 临时 JSON，不碰真实数据库。
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models.models import Base, Homework, LessonPlan, Student
from utils import calendar_service as cal_svc
from utils import homework_service as hw_svc
from utils import lesson_service as lesson_svc

from streamlit.testing.v1 import AppTest

from tests.test_app_smoke import _isolated_app_code, goto_top, goto_sub


SEMESTER = {"start": "2026-09-01", "end": "2027-01-31"}


# ---------------------------------------------------------------------------
# 服务层：周次
# ---------------------------------------------------------------------------

def test_get_week_of_semester():
    # 开学当天（周二）= 第 1 周
    assert cal_svc.get_week_of_semester(date(2026, 9, 1), SEMESTER) == 1
    # 开学前
    assert cal_svc.get_week_of_semester(date(2026, 8, 31), SEMESTER) == 0
    # 开学那周周一 8/31（早于开学）= 0
    assert cal_svc.get_week_of_semester(date(2026, 8, 31), SEMESTER) == 0
    # 第 2 周周一 9/7
    assert cal_svc.get_week_of_semester(date(2026, 9, 7), SEMESTER) == 2
    # 开学后第 8 天 9/8
    assert cal_svc.get_week_of_semester(date(2026, 9, 8), SEMESTER) == 2
    # 10/1（第 5 周）
    assert cal_svc.get_week_of_semester(date(2026, 10, 1), SEMESTER) == 5


def test_get_semester_weeks():
    weeks = cal_svc.get_semester_weeks(SEMESTER)
    # 9/1 开学，首周只含 9/1-9/4（周二到周五，4 天）
    assert weeks[0] == [date(2026, 9, 1), date(2026, 9, 2),
                        date(2026, 9, 3), date(2026, 9, 4)]
    # 第 2 周完整 5 天
    assert weeks[1] == [date(2026, 9, 7), date(2026, 9, 8),
                        date(2026, 9, 9), date(2026, 9, 10),
                        date(2026, 9, 11)]
    # 每周不超过 5 天
    assert all(len(w) <= 5 for w in weeks)
    # 尾周：1/29（周五）结束
    assert weeks[-1][-1] == date(2027, 1, 29)
    # 周数：跨 9-1 月
    assert len(weeks) == 22


def test_semester_progress():
    current, total, percent = cal_svc.semester_progress(
        date(2026, 9, 1), SEMESTER)
    assert current == 1 and total == 22 and percent == 0
    # 开学前
    _, _, p0 = cal_svc.semester_progress(date(2026, 8, 1), SEMESTER)
    assert p0 == 0
    # 放假后
    c2, t2, p2 = cal_svc.semester_progress(date(2027, 2, 1), SEMESTER)
    assert c2 == t2 and p2 == 100
    # 中段百分比在 0-100
    _, _, pm = cal_svc.semester_progress(date(2026, 11, 15), SEMESTER)
    assert 0 < pm < 100


# ---------------------------------------------------------------------------
# 服务层：学期配置持久化
# ---------------------------------------------------------------------------

def test_load_semester_creates_default(tmp_path):
    path = tmp_path / "semester.json"
    data = cal_svc.load_semester(path)
    assert set(data) == {"start", "end"}
    assert path.exists()


def test_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "semester.json"
    saved = cal_svc.save_semester(
        {"start": "2026-02-26", "end": "2026-07-10"}, path)
    assert saved == {"start": "2026-02-26", "end": "2026-07-10"}
    loaded = cal_svc.load_semester(path)
    assert loaded == saved


def test_load_semester_corrupt_fallback_keep_file(tmp_path):
    path = tmp_path / "semester.json"
    path.write_text("{坏 JSON", encoding="utf-8")
    data = cal_svc.load_semester(path)
    # 回退默认，且不覆盖坏文件
    assert set(data) == {"start", "end"}
    assert path.read_text(encoding="utf-8") == "{坏 JSON"


def test_save_semester_invalid_normalized(tmp_path):
    path = tmp_path / "semester.json"
    # 放假早于开学 -> 回退默认后写默认
    saved = cal_svc.save_semester(
        {"start": "2026-09-01", "end": "2026-08-01"}, path)
    assert date.fromisoformat(saved["end"]) > date.fromisoformat(saved["start"])


# ---------------------------------------------------------------------------
# AppTest：折叠导航结构
# ---------------------------------------------------------------------------

def _app(tmp_path, db_name="n.db"):
    db_file = tmp_path / db_name
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / "feature.json",
                           semester_file=tmp_path / "semester.json"),
        default_timeout=30)
    at.run()
    return at


def test_sidebar_structure(tmp_path):
    at = _app(tmp_path)
    # 没有旧的 main_nav radio
    assert all(r.key != "main_nav" for r in at.sidebar.radio)
    # 三个直接按钮
    keys = {b.key for b in at.sidebar.button}
    assert {"nav_home", "nav_calendar", "nav_settings"} <= keys
    # 三个子 radio
    rkeys = {r.key for r in at.sidebar.radio}
    assert {"lesson_plan_tab", "homework_tab", "analysis_tab"} <= rkeys


def test_direct_buttons_navigate(tmp_path):
    at = _app(tmp_path)
    next(b for b in at.sidebar.button if b.key == "nav_calendar").click().run()
    assert at.session_state["app_top_page"] == "📅 教学日历"
    assert any(t.value == "📅 教学日历" for t in at.title)
    next(b for b in at.sidebar.button if b.key == "nav_settings").click().run()
    assert at.session_state["app_top_page"] == "⚙️ 设置"
    assert not at.exception


@pytest.mark.parametrize("sub_key,sub_value,top,marker", [
    ("lesson_plan_tab", "AI 备课", "📚 备课", "AI 备课"),
    ("lesson_plan_tab", "题库管理", "📚 备课", "题库里还没有"),
    ("homework_tab", "✏️ 批改与分析", "📝 学业测评", "✏️ 批改与分析"),
    ("homework_tab", "📜 历史记录", "📝 学业测评", "暂无历史记录"),
    ("analysis_tab", "学生管理", "📊 学情", "学生管理"),
    ("analysis_tab", "🧠 知识图谱", "📊 学情", "知识图谱"),
])
def test_sub_radio_renders_function(tmp_path, sub_key, sub_value, top, marker):
    at = _app(tmp_path, f"{sub_value}.db")
    goto_sub(at, sub_key, sub_value, top)
    assert not at.exception, [str(e) for e in at.exception]
    text = " ".join([str(x.value) for x in at.subheader]
                     + [str(x.value) for x in at.info]
                     + [str(x.value) for x in at.selectbox])
    assert marker in text


def test_state_kept_across_sub_switch(tmp_path):
    at = _app(tmp_path, "state.db")
    # 注入 AI 备课与 AI 出题、作业打开状态
    plan = lesson_svc.empty_plan()
    at.session_state["lp_plan"] = plan
    at.session_state["lp_meta"] = {"plan_id": 7}
    at.session_state["lesson_gen_args"] = {"topic": "保留课题"}
    at.session_state["multi_gen_questions"] = {"数学": {"valid": [1]}}
    at.session_state["multi_gen_config"] = {"tasks": [1]}
    at.session_state["hw_open_id"] = 42
    goto_sub(at, "lesson_plan_tab", "AI 出题", "📚 备课")
    goto_sub(at, "lesson_plan_tab", "题库管理", "📚 备课")
    # 切回 AI 备课，状态仍在
    goto_sub(at, "lesson_plan_tab", "AI 备课", "📚 备课")
    assert at.session_state["lp_plan"] == plan
    assert at.session_state["lesson_gen_args"]["topic"] == "保留课题"
    assert at.session_state["multi_gen_questions"]
    assert at.session_state["multi_gen_config"]
    assert at.session_state["hw_open_id"] == 42


# ---------------------------------------------------------------------------
# AppTest：搜索四类跳转
# ---------------------------------------------------------------------------

def _seed_search_db(db_file: Path):
    """造题目/教案/学生/作业各 1，返回各自 id。"""
    from utils import question_service as qs
    from models.models import Question, Student as Stu, Homework as Hw

    engine = create_engine(
        f"sqlite:///{db_file.as_posix()}",
        connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    data = qs.validate_question({
        "content": "搜索专用题干", "question_type": "solution",
        "difficulty": 2, "answer": "A", "knowledge_points": []})
    q = qs.create_question(session, data, subject="数学")
    plan = LessonPlan(title="搜索专用教案", chapter="第一章",
                      content=json.dumps({"subject": "数学"}))
    session.add(plan)
    stu = Stu(name="搜索学生")
    session.add(stu)
    hw = Hw(name="搜索专用作业", is_template=False)
    session.add(hw)
    session.commit()
    ids = {"q": q.id, "plan": plan.id, "stu": stu.id, "hw": hw.id}
    session.close()
    engine.dispose()
    return ids


def test_search_jump_four_targets(tmp_path):
    db_file = tmp_path / "search.db"
    ids = _seed_search_db(db_file)
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / "feature.json",
                           semester_file=tmp_path / "semester.json"),
        default_timeout=30)
    at.run()

    # 题目
    at.sidebar.text_input[0].set_value("搜索专用题干").run()
    next(b for b in at.sidebar.button if b.key == f"search_q_{ids['q']}").click().run()
    assert at.session_state["app_top_page"] == "📚 备课"
    assert at.session_state["lesson_plan_tab"] == "题库管理"
    assert at.session_state["bank_search_keyword"] == "搜索专用题干"

    # 教案
    at.sidebar.text_input[0].set_value("搜索专用教案").run()
    next(b for b in at.sidebar.button if b.key == f"search_plan_{ids['plan']}").click().run()
    assert at.session_state["lesson_plan_tab"] == "AI 备课"
    assert "lp_plan" in at.session_state

    # 学生
    at.sidebar.text_input[0].set_value("搜索学生").run()
    next(b for b in at.sidebar.button if b.key == f"search_stu_{ids['stu']}").click().run()
    assert at.session_state["app_top_page"] == "📊 学情"
    assert at.session_state["analysis_tab"] == "学生管理"
    assert at.session_state["student_filter_keyword"] == "搜索学生"

    # 作业
    at.sidebar.text_input[0].set_value("搜索专用作业").run()
    next(b for b in at.sidebar.button if b.key == f"search_hw_{ids['hw']}").click().run()
    assert at.session_state["app_top_page"] == "📝 学业测评"
    assert at.session_state["homework_tab"] == "作业管理"
    assert at.session_state["hw_open_id"] == ids["hw"]
    assert not at.exception


# ---------------------------------------------------------------------------
# AppTest：日历两视图
# ---------------------------------------------------------------------------

def test_calendar_month_marks_week(tmp_path):
    at = _app(tmp_path, "cal.db")
    goto_top(at, "📅 教学日历")
    assert not at.exception
    # 月历格内出现“第1周”
    text = " ".join(str(x.value) for x in at.markdown)
    # AgGrid 内容在组件数据里，检查进度与标题
    assert len(at.get("progress")) == 1


def test_calendar_semester_view_and_setting(tmp_path):
    at = _app(tmp_path, "calsem.db")
    goto_top(at, "📅 教学日历")
    # 切学期视图
    next(x for x in at.radio if x.key == "calendar_view").set_value(
        "📆 学期视图").run()
    assert not at.exception, [str(e) for e in at.exception]
    # 学期设置保存
    next(x for x in at.date_input if x.key == "semester_start_input").set_value(
        date(2026, 9, 7)).run()
    next(b for b in at.button if b.key == "save_semester").click().run()
    assert not at.exception
    saved = json.loads((tmp_path / "semester.json").read_text(encoding="utf-8"))
    assert saved["start"] == "2026-09-07"
