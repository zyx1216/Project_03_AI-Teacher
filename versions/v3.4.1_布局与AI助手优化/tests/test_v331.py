# -*- coding: utf-8 -*-
"""v3.3.1 UI/UX 关键问题修复测试。"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from streamlit.testing.v1 import AppTest

import config
from models.models import Base
from tests.test_app_smoke import _isolated_app_code, goto_assistant, goto_sub
from utils import llm_client
from utils import lesson_service as lesson_svc


def _app(tmp_path, name: str):
    """起一个隔离库的 AppTest，返回 (at, db_file)。"""
    db_file = tmp_path / f"{name}.db"
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / f"{name}_feature.json"),
        default_timeout=30)
    at.run()
    return at, db_file


def _query(db_file, sql: str):
    engine = create_engine(f"sqlite:///{db_file.as_posix()}")
    with engine.connect() as conn:
        rows = conn.execute(text(sql)).fetchall()
    engine.dispose()
    return rows


# ---------------------------------------------------------------------------
# 版本与库结构
# ---------------------------------------------------------------------------

def test_version_and_tables_unchanged():
    assert config.APP_VERSION == "3.4.1"
    assert len(Base.metadata.tables) == 38


# ---------------------------------------------------------------------------
# 修复1/2：AI 助手合并到独立页
# ---------------------------------------------------------------------------

def test_sidebar_has_single_assistant_entry(tmp_path):
    at, _ = _app(tmp_path, "sidebar")
    assert not at.exception, [str(e) for e in at.exception]
    assert "nav_ai_assistant" in {b.key for b in at.sidebar.button}
    # 侧边栏不再有嵌入式助手聊天框。
    assert not any(x.key == "ai_assistant_page_input"
                   for x in at.sidebar.text_area)
    assert not any(x.key == "agent_assistant_input"
                   for x in at.sidebar.text_area)
    # 旧的子功能 radio 已移除。
    assert not {"lesson_plan_tab", "homework_tab",
                "analysis_tab"} & {r.key for r in at.sidebar.radio}


def test_assistant_page_has_migrated_controls(tmp_path):
    at, _ = _app(tmp_path, "assistant")
    goto_assistant(at)
    assert not at.exception, [str(e) for e in at.exception]
    button_keys = {b.key for b in at.button}
    assert {"ai_assistant_ctx_edit", "ai_assistant_ctx_reset",
            "ai_assistant_run", "ai_assistant_task_run"} <= button_keys
    assert any(x.key == "ai_assistant_multi_agent" for x in at.checkbox)
    assert any(x.key == "ai_assistant_page_input" for x in at.text_area)


def test_context_dialog_only_on_assistant_page(tmp_path):
    """弹窗只在助手页渲染，切到别的页面不会自动弹出。"""
    at, _ = _app(tmp_path, "ctx_dialog")
    goto_assistant(at)
    next(b for b in at.button if b.key == "ai_assistant_ctx_edit").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    # 切到首页后，弹窗不应该跟着出现。
    at.session_state["app_top_page"] = "🏠 首页"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    assert not any(b.key == "ai_ctx_save" for b in at.button)


def test_complex_instruction_plan_preview_on_assistant_page(tmp_path,
                                                            monkeypatch):
    at, _ = _app(tmp_path, "plan_preview")
    intent = json.dumps({
        "intent": "prepare_lesson",
        "params": {"subject": "数学", "grade": "高一", "class_name": "",
                   "chapter": "", "knowledge_points": [],
                   "question_type": "", "count": 0, "difficulty": 0,
                   "student_name": "", "time_range": "",
                   "topic": "准备下周的课"}}, ensure_ascii=False)
    monkeypatch.setattr(llm_client, "is_content_configured", lambda: True)
    monkeypatch.setattr(llm_client, "chat_content",
                        lambda system, user, temperature=0.0: intent)
    goto_assistant(at)
    next(x for x in at.text_area if x.key == "ai_assistant_page_input"
         ).set_value("帮我准备下周的课").run()
    next(b for b in at.button if b.key == "ai_assistant_run").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    preview = at.session_state.get("ai_assistant_plan_preview")
    assert preview and preview["plan"]
    assert at.session_state.get("ai_assistant_last_result") is None
    for key in ("ai_assistant_plan_confirm", "ai_assistant_plan_skip",
                "ai_assistant_plan_cancel"):
        assert any(b.key == key for b in at.button)


# ---------------------------------------------------------------------------
# 修复3：折叠组子功能改按钮组
# ---------------------------------------------------------------------------

def test_sub_function_buttons_switch_including_first(tmp_path):
    """点已选中的第一个子功能也必须立即切换并渲染。"""
    at, _ = _app(tmp_path, "sub_switch")
    # v3.4.1：资料管理移入「📂 资源中心」。
    next(b for b in at.sidebar.button
         if b.key == "resource_sub_📚 资料管理").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    assert at.session_state["app_top_page"] == "📂 资源中心"
    assert at.session_state["resource_tab"] == "📚 资料管理"
    assert any(x.key == "materials_subject" for x in at.selectbox)

    next(b for b in at.sidebar.button
         if b.key == "hw_sub_作业管理").click().run()
    assert at.session_state["app_top_page"] == "📝 学业测评"
    assert at.session_state["homework_tab"] == "作业管理"

    next(b for b in at.sidebar.button
         if b.key == "analysis_sub_学生管理").click().run()
    assert at.session_state["app_top_page"] == "📊 学情"
    assert at.session_state["analysis_tab"] == "学生管理"


# ---------------------------------------------------------------------------
# 修复4：教案生成与单元系列教案走后台上任务
# ---------------------------------------------------------------------------

@pytest.fixture()
def bound_db(tmp_path, monkeypatch):
    """把 utils.db 与 lesson_plan 的 SessionLocal 绑到临时库。"""
    import utils.db as db
    from modules import lesson_plan

    eng = create_engine(
        f"sqlite:///{(tmp_path / 'v331_unit.db').as_posix()}",
        connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    SL = sessionmaker(bind=eng)
    monkeypatch.setattr(db, "engine", eng, raising=False)
    monkeypatch.setattr(db, "SessionLocal", SL, raising=False)
    monkeypatch.setattr(lesson_plan, "SessionLocal", SL, raising=False)
    yield SL
    eng.dispose()


def test_generate_lesson_core_saves_draft(bound_db, monkeypatch):
    from modules import lesson_plan

    monkeypatch.setattr(lesson_plan.template_service,
                        "lesson_template_content", lambda name: "")
    plan = lesson_svc.empty_plan()
    plan["subject"] = "数学"
    raw = "```json\n" + json.dumps(plan, ensure_ascii=False) + "\n```"
    monkeypatch.setattr(llm_client, "chat_content",
                        lambda system, user, temperature=0.7: raw)

    out = lesson_plan._generate_lesson_core({
        "topic": "函数的概念", "grade": "高一", "chapter": "函数",
        "hours": 1, "style": "传统讲授课", "textbook_id": None,
        "selected_chapters": [], "subject": "数学",
        "template_name": "", "extra_instruction": None,
    })
    assert out["plan_id"]
    assert out["title"] == "函数的概念（草稿）"
    assert out["args"]["subject"] == "数学"
    with bound_db() as session:
        row = session.execute(text(
            "SELECT title, chapter FROM lesson_plans WHERE id = :i"),
            {"i": out["plan_id"]}).first()
    assert row is not None and row[0] == "函数的概念（草稿）"


def test_generate_lesson_button_submits_background_task(tmp_path, monkeypatch):
    import utils.task_service as ts

    at, db_file = _app(tmp_path, "lesson_bg")
    # 只建任务、不起线程，方便断言任务真的落到隔离库。
    monkeypatch.setattr(ts, "submit_task",
                        lambda task_type, params, runner:
                        ts.create_task(task_type, params))
    monkeypatch.setattr(llm_client, "is_content_configured", lambda: True)
    goto_sub(at, "lesson_plan_tab", "AI 备课", "📚 备课")
    next(x for x in at.text_input if x.label == "课题 *").set_value(
        "测试课题").run()
    next(b for b in at.button
         if b.key == "generate_lesson_button").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    rows = _query(db_file, "SELECT task_type, status FROM background_tasks")
    assert ("教案生成", "pending") in rows


def test_unit_task_runner_creates_unit(bound_db, monkeypatch):
    from modules import lesson_plan

    calls = []
    monkeypatch.setattr(lesson_plan.unit_design_service, "generate_all_lessons",
                        lambda session, unit_id: calls.append(unit_id))
    params = {
        "name": "函数单元", "subject": "数学", "grade": "高一",
        "textbook_id": None, "chapter": "函数",
        "objectives": {"lesson_titles": ["第1课时", "第2课时"],
                       "lesson_hours": 2},
    }
    out = lesson_plan._unit_task_runner(
        params, lambda p: None, lambda: False)
    assert out["unit_id"]
    assert calls == [out["unit_id"]]
    with bound_db() as session:
        unit = session.execute(text(
            "SELECT name, lesson_count FROM unit_plans WHERE id = :i"),
            {"i": out["unit_id"]}).first()
        lessons = session.execute(text(
            "SELECT COUNT(*) FROM unit_lessons WHERE unit_id = :i"),
            {"i": out["unit_id"]}).scalar_one()
    assert unit is not None and unit[0] == "函数单元"
    assert lessons == 2