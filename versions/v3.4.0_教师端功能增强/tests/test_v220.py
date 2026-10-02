# -*- coding: utf-8 -*-
"""v2.2.0 Agent 能力增强测试。"""

from __future__ import annotations

import json
from datetime import date
from io import BytesIO

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from models.models import Base, AgentMemory, GradingLog, TeachingProgress
from utils import (
    agent_memory_service, agent_tools, reference_resolution_service,
    teaching_plan_service,
)
from utils import calendar_service
from utils import exam_service, homework_service, question_service, student_service


@pytest.fixture()
def session(tmp_path, monkeypatch):
    semester = tmp_path / "semester.json"
    monkeypatch.setattr(calendar_service, "SEMESTER_PATH", semester)
    engine = create_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    Base.metadata.create_all(engine)
    sl = sessionmaker(bind=engine)
    s = sl()
    yield s
    s.close()
    engine.dispose()


def _student(session, name="张三", class_name="一班"):
    student, _ = student_service.get_or_create_student(
        session, name, class_name)
    session.flush()
    return student


def _exam(session, name="月考", day=date(2026, 9, 1)):
    exam = exam_service.create_exam(session, name, exam_date=day)
    session.flush()
    return exam


def _valid_question(content="1+1=？", answer="2", difficulty=1,
                    subject="数学", kps=None):
    data = question_service.validate_question({
        "content": content, "answer": answer, "difficulty": difficulty,
        "question_type": "choice", "knowledge_points": kps or ["计算"]})
    return question_service.create_question(
        session, data, source="manual", status="approved",
        subject=subject)


def test_database_has_21_tables_and_backup_tables():
    assert len(Base.metadata.tables) == 38
    from utils.backup_service import BUSINESS_TABLES
    assert len(BUSINESS_TABLES) == 38
    assert {"teaching_progress", "agent_memory"} <= set(BUSINESS_TABLES)


def test_new_table_fields(session):
    cols = {c["name"]: c for c in inspect(session.bind).get_columns("agent_memory")}
    assert {"memory_type", "key", "value", "category", "importance",
            "created_at", "last_used_at", "use_count"} <= set(cols)
    cols = {c["name"]: c for c in inspect(session.bind).get_columns(
        "teaching_progress")}
    assert {"subject", "grade", "semester", "week_number",
            "planned_content", "actual_content", "status", "note",
            "updated_at"} <= set(cols)


def test_migration_repeatable(tmp_path):
    import importlib.util
    from pathlib import Path
    migration_path = Path("migrations/v2.2.0_migration.py")
    spec = importlib.util.spec_from_file_location("v220_migration", migration_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'm.db').as_posix()}")
    first = module.migrate(engine)
    second = module.migrate(engine)
    assert set(first["created"]) == {"teaching_progress", "agent_memory"}
    assert second["missing"] == []
    engine.dispose()


def test_semester_and_weekly_plan_structure(session):
    plan = teaching_plan_service.generate_semester_plan(
        "数学", "高一", "2026秋", 5, ["第一章 集合", "第二章 函数"])
    assert set(plan) == {"meta", "weekly_plan", "chapter_hours",
                         "exam_review", "key_difficulties"}
    assert len(plan["weekly_plan"]) == 20
    weekly = teaching_plan_service.generate_weekly_plan(plan, 2)
    assert weekly["week_number"] == 2
    assert "函数" in weekly["content"]
    assert teaching_plan_service.save_planned_weeks(session, plan) == 20


def test_ai_unavailable_even_distribution():
    plan = teaching_plan_service.generate_semester_plan(
        "数学", "初一", "2026秋", 4, ["第一章", "第二章", "第三章"])
    assert plan["meta"]["generated_rule"] == "按章节和每周课时均匀分配"
    assert all(item["hours"] == 4 for item in plan["weekly_plan"][:18])


def test_progress_normal_lag_ahead_compare(session, monkeypatch):
    plan = teaching_plan_service.generate_semester_plan(
        "数学", "高一", "2026秋", 4, ["第一章", "第二章"])
    teaching_plan_service.save_planned_weeks(session, plan)

    class FakeDate:
        @classmethod
        def today(cls):
            return date(2026, 9, 28)

    row_lag = teaching_plan_service.track_progress(
        session, "数学", "高一", "2026秋", 3, "", note="未上")
    row_ahead = teaching_plan_service.track_progress(
        session, "数学", "高一", "2026秋", 20, "提前内容")
    assert row_lag.status == "lag"
    assert row_ahead.status == "ahead"
    report = teaching_plan_service.compare_progress(
        session, "数学", "高一", "2026秋")
    assert report["lag_weeks"]
    assert report["ahead_weeks"]


def test_auto_adjust_does_not_delete_original(session):
    plan = teaching_plan_service.generate_semester_plan(
        "数学", "高一", "2026秋", 4, ["第一章", "第二章"])
    adjusted = teaching_plan_service.auto_adjust_plan(
        plan, 2, [{"week": 1, "status": "lag"}])
    assert plan["meta"].get("auto_adjusted") is not True
    assert adjusted["meta"]["lag_count"] == 1
    assert any("顺延" in item.get("note", "")
               for item in adjusted["weekly_plan"][2:])


def test_plan_excel_word_bytes(session):
    # 通过日历模块的私有导出函数，检查 Excel/Word 都是有效文件。
    from modules.calendar import _semester_plan_excel, _semester_plan_word
    plan = teaching_plan_service.generate_semester_plan(
        "数学", "高一", "2026秋", 4, ["第一章"])
    assert _semester_plan_excel(plan)[:2] == b"PK"
    assert _semester_plan_word(plan)[:2] == b"PK"


def test_memory_crud_and_duplicate_updates(session):
    row = agent_memory_service.remember_preference(
        session, "default_difficulty", "基础", importance=7)
    found = agent_memory_service.recall_preference(
        session, "default_difficulty")
    assert found.id == row.id and found.use_count == 1
    updated = agent_memory_service.remember_preference(
        session, "default_difficulty", "中等", importance=8)
    assert updated.id == row.id and updated.use_count == 2 and updated.value == "中等"
    assert agent_memory_service.forget_preference(
        session, "default_difficulty") == 1
    assert agent_memory_service.recall_preference(
        session, "default_difficulty") is None


def test_memory_sorted_by_importance(session):
    agent_memory_service.remember_preference(
        session, "low", "低", importance=2)
    agent_memory_service.remember_preference(
        session, "high", "高", importance=9)
    rows = agent_memory_service.get_all_preferences(session)
    assert rows[0].key == "high"


def test_auto_extract_preferences_and_sensitive(session):
    saved = agent_memory_service.auto_extract_preferences(session, [
        {"role": "user", "content": "以后每次出8道题"},
        {"role": "user", "content": "我的API Key是 abc123，别告诉别人"},
    ])
    assert len(saved) == 1
    assert saved[0].key == "default_question_count"
    assert not session.query(AgentMemory).filter(
        AgentMemory.value.like("%abc123%")).count()


def test_reference_resolution_with_session(session):
    student = _student(session)
    homework = homework_service.create_homework(
        session, "上次的数学作业", class_name="一班", subject="数学")
    exam = _exam(session, "九月月考")
    plan = question_service  # keep imports used in module setup

    hw_result = reference_resolution_service.resolve_reference(
        "分析上次那套卷子", {}, session=session)
    assert hw_result["needs_clarification"] is False
    assert homework.name in hw_result["text"]

    exam_result = reference_resolution_service.resolve_reference(
        "分析这次考试", {}, session=session)
    assert exam.name in exam_result["text"]

    unclear = reference_resolution_service.resolve_reference(
        "那个学生是谁", {}, session=session)
    assert unclear["needs_clarification"] is True
    assert unclear["clarification"]["options"]


def test_high_risk_confirmation_shape():
    data = reference_resolution_service.high_risk_confirmation(
        "删除题目", {"题目ID": 8})
    assert data["needs_confirmation"] is True
    assert "题目ID：8" in data["summary"]


def test_tool_registration_validation(session):
    assert len(agent_tools.TOOLS) >= 10
    with pytest.raises(agent_tools.ToolError):
        agent_tools.execute_tool(session, "not_exists", {})
    with pytest.raises(agent_tools.ToolError):
        agent_tools.execute_tool(
            session, "delete_question", {"question_id": 1})


def test_query_add_student_analyze_tools(session):
    student = _student(session)
    exam = _exam(session)
    exam_service.import_scores(session, exam.id, [{
        "name": student.name, "class_name": "一班",
        "scores": {"数学": 88}}])
    result = agent_tools.execute_tool(
        session, "query_student_score", {"student_name": "张三"})
    assert result["student"] == "张三"
    assert result["scores"]

    added = agent_tools.execute_tool(
        session, "add_student", {"name": "李四", "class_name": "二班"})
    assert added["created"] is True

    analysis = agent_tools.execute_tool(
        session, "analyze_exam", {"exam_id": exam.id})
    assert analysis["exam_id"] == exam.id


def test_high_risk_update_score_requires_confirmation(session):
    student = _student(session)
    exam = _exam(session)
    params = {"student_name": "张三", "class_name": "一班",
              "subject": "数学", "score": 90, "exam_id": exam.id}
    with pytest.raises(agent_tools.ToolError):
        agent_tools.execute_tool(session, "update_student_score", params)
    result = agent_tools.execute_tool(
        session, "update_student_score", params, confirmed=True)
    assert result["scores_written"] == 1


def test_web_search_mocked(session, monkeypatch):
    sample_html = '<a href="https://example.com/article">数学教学</a>'
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return sample_html.encode("utf-8")
    def urlopen(*args, **kwargs):
        return Response()
    monkeypatch.setattr(agent_tools, "urlopen", urlopen)
    result = agent_tools.execute_tool(
        session, "web_search", {"query": "数学教学"})
    assert result["results"][0]["url"] == "https://example.com/article"


def test_chart_tool_returns_figure(session):
    student = _student(session)
    exam = _exam(session)
    exam_service.import_scores(session, exam.id, [{
        "name": "张三", "class_name": "一班",
        "scores": {"数学": 77}}])
    fig = agent_tools.execute_tool(
        session, "generate_chart", {"exam_id": exam.id})
    assert fig.data


def test_parse_and_execute_tool_json(session):
    student = _student(session)
    result = agent_tools.parse_and_execute(session, {
        "tool_name": "add_student",
        "params": {"name": "王五", "class_name": "三班"}})
    assert result["created"] is True


def test_auto_preferences_fill_missing_only(session):
    agent_memory_service.remember_preference(
        session, "default_difficulty", "拓展")
    parsed = {"intent": "compose_paper", "params": {
        "subject": "数学", "difficulty": 0, "count": 0}}
    from utils.agent_service import _apply_auto_preferences
    _apply_auto_preferences(session, parsed)
    assert parsed["params"]["difficulty"] == 3

    parsed["params"]["difficulty"] = 1
    _apply_auto_preferences(session, parsed)
    assert parsed["params"]["difficulty"] == 1


