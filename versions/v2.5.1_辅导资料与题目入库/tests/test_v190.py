# -*- coding: utf-8 -*-
"""v1.9.0 功能深化与 Agent 化测试。

覆盖服务层：
- AI 意图解析 5 类；出题草稿转正式 / 空结果删草稿；
- 查询指令、多步计划与取消；
- 知识图谱时间衰减/难度权重/红黄绿、薄弱点推荐；
- 班级对比、教案作业联动、撤销重做；
- 图表与多格式导出。

AppTest：侧边栏 AI 助手入口、空库/有数据无异常。
全部用临时 SQLite / JSON，monkeypatch 模拟 LLM，不请求真实模型。
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from models.models import (
    Base, Homework, HomeworkAnswer, HomeworkQuestion, Question, Student,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


# ---------------------------------------------------------------------------
# 临时库夹具
# ---------------------------------------------------------------------------

@pytest.fixture()
def session(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'v190.db').as_posix()}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()
    engine.dispose()


def _make_question(session, *, qtype="choice", difficulty=1,
                   kps=None, subject="数学", status="approved"):
    data = {
        "content": f"题目-{qtype}-{difficulty}",
        "question_type": qtype, "difficulty": difficulty,
        "knowledge_points": json.dumps(kps or [], ensure_ascii=False),
        "answer": "A", "analysis": "", "error_points": "", "verify": None}
    from utils import question_service as qs
    q = qs.create_question(session, data, source="manual",
                           status=status, subject=subject)
    session.flush()
    return q


# ---------------------------------------------------------------------------
# 一、意图常量与解析
# ---------------------------------------------------------------------------

def test_intent_constants_six_classes():
    from utils import agent_intents as ai
    assert ai.INTENTS == [
        ai.COMPOSE_PAPER, ai.PREPARE_LESSON, ai.ANALYZE_STUDENT,
        ai.QUERY, ai.MULTI_STEP, ai.RAG_QUERY]


def test_normalize_intent_basic():
    from utils import agent_intents as ai
    out = ai.normalize_intent({
        "intent": "compose_paper",
        "params": {"subject": "数学", "grade": "高一",
                   "question_type": "选择题", "count": "5",
                   "difficulty": "基础"}})
    assert out["params"]["grade"] == "高一"
    assert out["params"]["question_type"] == "choice"
    assert out["params"]["count"] == 5
    assert out["params"]["difficulty"] == 1


def test_normalize_intent_rejects_unknown():
    from utils import agent_intents as ai
    with pytest.raises(ValueError):
        ai.normalize_intent({"intent": "hack"})


def test_parse_instruction_uses_llm(monkeypatch):
    from utils import agent_service
    monkeypatch.setattr(
        agent_service.llm_client, "chat_content",
        lambda *a, **k: json.dumps({
            "intent": "query",
            "params": {"subject": "数学"}}, ensure_ascii=False))
    parsed = agent_service.parse_instruction("题库多少题")
    assert parsed["intent"] == "query"


# ---------------------------------------------------------------------------
# 二、出题指令
# ---------------------------------------------------------------------------

def test_compose_creates_formal_paper(session, monkeypatch):
    """出题成功：草稿转正式 exam、is_template=False。"""
    from utils import agent_service
    monkeypatch.setattr(
        agent_service.llm_client, "chat_content",
        lambda *a, **k: json.dumps({
            "intent": "compose_paper",
            "params": {"subject": "数学", "grade": "高一",
                       "question_type": "choice", "count": 5,
                       "difficulty": 1}}, ensure_ascii=False))
    _make_question(session, qtype="choice", difficulty=1)
    result = agent_service.run_instruction(session, "出5道数学高一选择基础题")
    assert result["status"] == "success"
    hid = result["extra"]["hw_open_id"]
    hw = session.get(Homework, hid)
    assert hw.homework_type == "exam"
    assert hw.is_template is False
    # 历史写入。
    from utils import agent_service as svc
    assert svc.list_agent_history()


def test_compose_empty_deletes_draft(session, monkeypatch):
    """总题数 0：草稿删除，返回 empty，不留垃圾。"""
    from utils import agent_service, homework_service as hw_svc
    monkeypatch.setattr(
        agent_service.llm_client, "chat_content",
        lambda *a, **k: json.dumps({
            "intent": "compose_paper",
            "params": {"subject": "数学", "grade": "高一",
                       "question_type": "choice", "count": 5,
                       "difficulty": 1}}, ensure_ascii=False))
    # 让 auto_compose 不产出任何题（题库空 + AI 补缺静默失败）。
    monkeypatch.setattr(hw_svc, "_ai_generate_for_shortage",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    result = agent_service.run_instruction(session, "出5道数学高一选择基础题")
    assert result["status"] == "empty"
    drafts = session.query(Homework).filter(
        Homework.name.like("__smart_compose_draft__%")).all()
    assert drafts == []


def test_compose_failure_deletes_draft(session, monkeypatch):
    """auto_compose 异常：草稿被删除。"""
    from utils import agent_service, homework_service as hw_svc
    monkeypatch.setattr(
        agent_service.llm_client, "chat_content",
        lambda *a, **k: json.dumps({
            "intent": "compose_paper",
            "params": {"subject": "数学", "grade": "高一",
                       "question_type": "choice", "count": 5,
                       "difficulty": 1}}, ensure_ascii=False))
    def _boom(*a, **k):
        raise RuntimeError("组卷炸了")
    monkeypatch.setattr(hw_svc, "auto_compose", _boom)
    with pytest.raises(RuntimeError):
        agent_service.run_instruction(session, "出5道数学高一选择基础题")
    drafts = session.query(Homework).filter(
        Homework.name.like("__smart_compose_draft__%")).all()
    assert drafts == []


# ---------------------------------------------------------------------------
# 三、查询指令
# ---------------------------------------------------------------------------

def test_query_returns_bank_count(session):
    from utils import agent_service
    _make_question(session)
    parsed = {"intent": "query",
              "params": {"subject": "数学"}}
    result = agent_service._execute_parsed(session, parsed)
    assert result["status"] == "success"
    assert "题库共 1 道题" in result["summary"]


# ---------------------------------------------------------------------------
# 四、多步计划
# ---------------------------------------------------------------------------

def test_build_plan_two_kinds():
    from utils import agent_planner
    p1 = agent_planner.build_plan({"params": {"topic": "备课并生成作业"}})
    assert [s["step_id"] for s in p1] == [
        "gen_lesson", "gen_homework", "summary"]
    p2 = agent_planner.build_plan({"params": {"topic": "分析成绩并生成反思"}})
    assert "build_reflection" in [s["step_id"] for s in p2]


def test_plan_cancel_stops_further_steps(session):
    from utils import agent_planner
    plan = [{"step_id": "gen_lesson", "name": "教案"},
            {"step_id": "gen_homework", "name": "作业"}]

    # 第一步完成后请求取消：第二步不应执行。
    def fake_step(session, step_id, parsed, context):
        if step_id == "gen_lesson":
            agent_planner.request_cancel()
            return {"summary": "教案完成"}
        raise AssertionError("不应执行第二步")
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(agent_planner, "_run_step", fake_step)
    out = agent_planner.execute_plan(session, "x", plan)
    assert out["status"] == "cancelled"
    monkeypatch.undo()


# ---------------------------------------------------------------------------
# 五、知识图谱
# ---------------------------------------------------------------------------

def _seed_answer(session, *, student, question, correct, days_ago,
                 link_score=10, earned=None):
    hw = Homework(name="图谱作业", homework_type="after_class",
                  subject="数学", status="pending")
    session.add(hw)
    session.flush()
    session.add(HomeworkQuestion(
        homework_id=hw.id, question_id=question.id, order=1,
        score=link_score))
    session.add(HomeworkAnswer(
        homework_id=hw.id, student_id=student.id, question_id=question.id,
        earned_score=earned if earned is not None else (link_score if correct else 0),
        is_correct=correct,
        created_at=datetime.now() - timedelta(days=days_ago)))
    session.flush()
    return hw


def test_mastery_weights_and_colors(session):
    from utils import knowledge_graph_service as kgs
    stu = Student(name="图谱生", class_name="图谱班")
    session.add(stu)
    session.flush()
    q_easy = _make_question(session, difficulty=1, kps=["知识点A"])
    _seed_answer(session, student=stu, question=q_easy, correct=True,
                  days_ago=0)
    result = kgs.build_mastery(session, "数学", class_names=["图谱班"])
    assert result["matrix"][stu.id]["知识点A"] > 0
    assert result["weak_top5"] is not None


def test_mastery_time_decay(session):
    """同一题同一得分，越早作答时间权重越低（这里只验证函数可算且范围正常）。"""
    from utils import knowledge_graph_service as kgs
    assert kgs.mastery_color(0.5) == "red"
    assert kgs.mastery_color(0.7) == "yellow"
    assert kgs.mastery_color(0.9) == "green"


def test_mastery_recommendations_only_approved_same_subject(session):
    from utils import knowledge_graph_service as kgs
    stu = Student(name="生", class_name="班")
    session.add(stu)
    session.flush()
    q = _make_question(session, difficulty=1, kps=["薄弱K"], status="approved")
    _seed_answer(session, student=stu, question=q, correct=False, days_ago=0)
    result = kgs.build_mastery(session, "数学", class_names=["班"])
    assert result["recommendations"].get("薄弱K") == [q.id]
    # 未审核题不进推荐。
    q2 = _make_question(session, difficulty=1, kps=["薄弱K"],
                        status="pending")
    result2 = kgs.build_mastery(session, "数学", class_names=["班"])
    assert q2.id not in {x for ids in result2["recommendations"].values()
                         for x in ids}


# ---------------------------------------------------------------------------
# 六、班级对比
# ---------------------------------------------------------------------------

def _seed_exam_classes(session):
    from utils import exam_service
    exam = exam_service.create_exam(
        session, "对比考", exam_date=date(2026, 3, 1),
        full_scores={"数学": 100})
    session.flush()
    records = []
    for name, cls, score in [
            ("甲1", "一班", 90), ("甲2", "一班", 70),
            ("乙1", "二班", 50), ("乙2", "二班", 40)]:
        records.append({"name": name, "class_name": cls,
                        "scores": {"数学": score}})
    exam_service.import_scores(session, exam.id, records)
    session.flush()
    return exam


def test_compare_exam_classes(session):
    from utils import class_compare_service
    exam = _seed_exam_classes(session)
    result = class_compare_service.compare_exam_classes(
        session, exam.id, ["一班", "二班"])
    means = {c["class_name"]: c["mean"] for c in result["classes"]}
    assert means["一班"] == 80
    assert means["二班"] == 45
    assert result["bands"]


def test_compare_rejects_bad_count(session):
    from utils import class_compare_service
    exam = _seed_exam_classes(session)
    with pytest.raises(ValueError):
        class_compare_service.compare_exam_classes(
            session, exam.id, ["一班"])


def test_compare_trends_and_word(session):
    from utils import class_compare_service
    exam = _seed_exam_classes(session)
    trend = class_compare_service.compare_class_trends(
        session, ["一班", "二班"])
    assert trend["class_names"] == ["一班", "二班"]
    report = class_compare_service.export_compare_report(
        session,
        class_compare_service.compare_exam_classes(
            session, exam.id, ["一班", "二班"]))
    assert report[:2] == b"PK"


# ---------------------------------------------------------------------------
# 七、教案作业联动
# ---------------------------------------------------------------------------

def test_create_homework_from_lesson(session):
    from utils import (
        lesson_service, lesson_homework_link_service)
    plan = lesson_service.empty_plan()
    plan["subject"] = "数学"
    lesson = lesson_service.save_plan(
        session, "函数的概念", plan, grade="高一", subject="数学")
    session.flush()
    # 题库无题；AI 补缺在测试中会因未配置而失败，total 可能为 0，
    # 这里造一道已审核题保证有题可抽。
    _make_question(session, qtype="choice", difficulty=1)
    hw = lesson_homework_link_service.create_homework_from_lesson(
        session, lesson.id)
    assert hw.lesson_plan_id == lesson.id
    assert hw.homework_type == "after_class"


def test_create_homework_from_lesson_empty_raises(session, monkeypatch):
    from utils import (
        lesson_service, lesson_homework_link_service,
        homework_service as hw_svc)
    plan = lesson_service.empty_plan()
    lesson = lesson_service.save_plan(session, "空课", plan, grade="高一")
    session.flush()
    monkeypatch.setattr(
        hw_svc, "_ai_generate_for_shortage",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no ai")))
    with pytest.raises(ValueError):
        lesson_homework_link_service.create_homework_from_lesson(
            session, lesson.id)
    assert session.query(Homework).filter(
        Homework.name.like("%配套作业")).all() == []


# ---------------------------------------------------------------------------
# 八、撤销 / 重做
# ---------------------------------------------------------------------------

def test_undo_redo_delete_question(session):
    from utils import undo_service
    q = _make_question(session)
    qid = q.id
    undo_service.record(
        session, "delete_question",
        {"target": (Question, qid)}, "删除题目")
    session.delete(q)
    session.flush()
    assert session.get(Question, qid) is None

    undo_service.undo(session)
    session.flush()
    assert session.get(Question, qid) is not None

    undo_service.redo(session)
    session.flush()
    assert session.get(Question, qid) is None


def test_undo_stack_limits_and_clear(session):
    from utils import undo_service
    undo_service.clear()
    for i in range(12):
        undo_service.record(
            session, "x", {"snapshot": {"questions": []}}, f"动作{i}")
    assert undo_service.can_undo()
    undo_service.clear()
    assert not undo_service.can_undo()
    assert not undo_service.can_redo()


# ---------------------------------------------------------------------------
# 九、图表
# ---------------------------------------------------------------------------

def test_chart_functions():
    from utils import chart_service
    rows = [{"total": 80, "class_name": "一班"},
            {"total": 60, "class_name": "二班"}]
    assert chart_service.score_box(rows, group_key="class_name").data
    radar = chart_service.ability_radar(
        [{"name": "生", "数学": 0.8}], ["数学"])
    assert radar.data
    gauge = chart_service.rate_gauge(75, "及格率")
    assert gauge.data
    assert len(chart_service.knowledge_gauges(
        [{"knowledge_point": "K", "rate": 50}])) == 1


# ---------------------------------------------------------------------------
# 十、多格式导出
# ---------------------------------------------------------------------------

def test_lesson_plan_pdf(session):
    from utils import lesson_service, export_service
    lesson = lesson_service.save_plan(
        session, "PDF课", lesson_service.empty_plan())
    session.flush()
    pdf = export_service.lesson_plan_pdf(
        lesson, lesson_service.load_plan(lesson))
    assert pdf[:4] == b"%PDF"


def test_homework_latex(session):
    from utils import export_service
    q = _make_question(session, qtype="choice")
    hw = Homework(name="LaTeX作业", homework_type="after_class",
                  subject="数学")
    session.add(hw)
    session.flush()
    session.add(HomeworkQuestion(
        homework_id=hw.id, question_id=q.id, order=1, score=10))
    session.flush()
    from utils import homework_service as hw_svc
    pairs = hw_svc.homework_questions(session, hw.id)
    tex = export_service.homework_latex(hw, pairs)
    assert "\\documentclass{ctexart}" in tex
    assert "LaTeX作业" in tex


def test_analysis_report_ppt_exam(session):
    from utils import export_service
    exam = _seed_exam_classes(session)
    blob = export_service.analysis_report_ppt(session, exam.id, "exam")
    assert blob[:2] == b"PK"


def test_analysis_report_ppt_homework(session):
    from utils import export_service, homework_service as hw_svc
    hw = hw_svc.create_homework(session, "PPT作业")
    session.flush()
    blob = export_service.analysis_report_ppt(session, hw.id, "homework")
    assert blob[:2] == b"PK"


# ---------------------------------------------------------------------------
# AppTest
# ---------------------------------------------------------------------------

APP_FILE = Path(__file__).resolve().parent.parent / "app.py"


def _isolated(db_file):
    from tests.test_app_smoke import _isolated_app_code
    return _isolated_app_code(db_file, db_file.parent / "feature.json")


def test_apptest_empty_no_exception(tmp_path):
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_string(
        _isolated(tmp_path / "empty.db"), default_timeout=30)
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    # AI 助手控件存在。
    assert any(x.key == "agent_assistant_input" for x in at.text_area)


def test_apptest_smart_compose_and_knowledge_tabs_no_exception(tmp_path):
    """空库进入智能组卷、知识图谱、考试分析、趋势页均无异常。"""
    from streamlit.testing.v1 import AppTest
    from tests.test_app_smoke import goto_top, goto_sub
    at = AppTest.from_string(
        _isolated(tmp_path / "tabs.db"), default_timeout=30)
    at.run()
    goto_sub(at, "homework_tab", "🤖 智能组卷", "📝 学业测评")
    assert not at.exception
    goto_sub(at, "analysis_tab", "考试分析", "📊 学情")
    assert not at.exception
    goto_sub(at, "analysis_tab", "趋势分析", "📊 学情")
    assert not at.exception
