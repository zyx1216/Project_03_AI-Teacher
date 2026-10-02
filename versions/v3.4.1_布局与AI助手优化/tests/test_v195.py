# -*- coding: utf-8 -*-
"""v1.9.5 自主规划 + 主动提醒 + 教学建议 Agent 测试。

全程临时 SQLite/JSON，不读真实库、不触发真实 AI；LLM 调用全部 monkeypatch。
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from models.models import (
    Base, Exam, Homework, HomeworkAnswer, HomeworkQuestion,
    LessonPlan, Question, ReflectionPlan, Score, Student,
    TeachingReflection)
from streamlit.testing.v1 import AppTest
from tests.test_app_smoke import (
    _isolated_app_code, goto_assistant, goto_sub, goto_top)
from utils import (
    agent_alert, agent_advisor, agent_context, agent_intents,
    agent_service, agent_planner, llm_client)
from utils import homework_service as hw_svc
from utils import question_service


# ---------------------------------------------------------------------------
# 临时库与路径隔离
# ---------------------------------------------------------------------------

@pytest.fixture()
def session(tmp_path, monkeypatch):
    monkeypatch.setattr(
        agent_alert, "ALERTS_PATH", tmp_path / "agent_alerts.json")
    monkeypatch.setattr(
        agent_advisor, "SUGGESTIONS_PATH", tmp_path / "agent_suggestions.json")
    monkeypatch.setattr(
        agent_context, "AGENT_CONTEXT_PATH", tmp_path / "agent_context.json")
    monkeypatch.setattr(
        agent_service, "AGENT_HISTORY_PATH", tmp_path / "agent_history.json")
    engine = create_engine(f"sqlite:///{(tmp_path / 'v195.db').as_posix()}")
    Base.metadata.create_all(engine)
    sess = sessionmaker(bind=engine)()
    yield sess
    sess.close()
    engine.dispose()


def _student(sess, name, class_name="高一1班"):
    s = Student(name=name, class_name=class_name)
    sess.add(s)
    sess.flush()
    return s


def _question(sess, *, qtype="choice", difficulty=1, kps=None,
              subject="数学", status="approved", content=None, grade="高一"):
    data = {
        "content": content or f"题目-{datetime.now().microsecond}",
        "question_type": qtype, "difficulty": difficulty,
        "knowledge_points": json.dumps(kps or [], ensure_ascii=False),
        "answer": "A", "analysis": "", "error_points": "", "verify": None}
    q = question_service.create_question(
        sess, data, source="manual", status=status,
        subject=subject, grade=grade)
    sess.flush()
    return q


def _exam(sess, name, day, scores=None, class_name="高一1班"):
    """建一场考试并写入总分；scores={学生名: 总分}（单科数学）。"""
    exam = Exam(name=name, exam_date=day, grade="高一", term="")
    sess.add(exam)
    sess.flush()
    if scores:
        for stu_name, total in scores.items():
            stu = (sess.query(Student)
                   .filter(Student.name == stu_name,
                           Student.class_name == class_name).first())
            sess.add(Score(exam_id=exam.id, student_id=stu.id,
                           subject="数学", score=total))
    sess.flush()
    return exam


# ---------------------------------------------------------------------------
# 一、复杂度分级
# ---------------------------------------------------------------------------

def test_classify_complexity_levels():
    assert agent_intents.classify_complexity("题库里有多少道题") == "simple"
    assert agent_intents.classify_complexity("数学高一出5道函数选择题") == "single"
    assert (agent_intents.classify_complexity("备这节课并生成配套作业")
            == "multi_step")
    assert agent_intents.classify_complexity("帮我准备下周的课") == "complex"
    assert (agent_intents.classify_complexity("给这个班出一套期末复习卷")
            == "complex")
    assert (agent_intents.classify_complexity("分析这次考试并给出改进方案")
            == "complex")


def test_build_plan_enhanced_four_kinds(session):
    def plan_for(instruction):
        parsed = {"params": {"topic": instruction}}
        kind = agent_planner.plan_kind_of(instruction)
        return agent_planner.build_plan_enhanced(
            parsed, {"instruction": instruction, "plan_kind": kind})

    names = {
        "帮我准备下周的课": "full_lesson_prep",
        "分析这次考试并给出改进方案": "exam_analysis_with_plan",
        "出一套期末复习卷": "review_paper_generation",
        "帮我分析张三并安排专项": "student_intervention",
    }
    for text, kind in names.items():
        plan = plan_for(text)
        assert plan and all("step_id" in s and "name" in s for s in plan)
        # 计划类型应与预期一致（通过 step_id 集合侧面验证）。
        first_ids = [s["step_id"] for s in plan]
        if kind == "full_lesson_prep":
            assert "gen_homework" in first_ids
        elif kind == "exam_analysis_with_plan":
            assert "ep_make_plan" in first_ids
        elif kind == "review_paper_generation":
            assert "ep_finalize_paper" in first_ids
        else:
            assert "ep_special_homework" in first_ids


# ---------------------------------------------------------------------------
# 二、主动提醒：五类检测
# ---------------------------------------------------------------------------

def test_alert_score_decline(session):
    today = date.today()
    _student(session, "张三")
    _exam(session, "考试1", today - timedelta(days=20), {"张三": 100})
    _exam(session, "考试2", today - timedelta(days=10), {"张三": 90})
    _exam(session, "考试3", today, {"张三": 80})
    alerts = agent_alert.check_score_decline(session)
    assert len(alerts) == 1
    assert alerts[0]["alert_type"] == "score_decline"
    assert alerts[0]["severity"] == "severe"


def test_alert_score_no_decline_when_stable(session):
    today = date.today()
    _student(session, "张三")
    _exam(session, "考试1", today - timedelta(days=20), {"张三": 80})
    _exam(session, "考试2", today - timedelta(days=10), {"张三": 90})
    _exam(session, "考试3", today, {"张三": 100})
    assert agent_alert.check_score_decline(session) == []


def test_alert_student_decline(session):
    today = date.today()
    _student(session, "张三")
    _exam(session, "上次", today - timedelta(days=10), {"张三": 100})
    _exam(session, "这次", today, {"张三": 70})
    alerts = agent_alert.check_student_decline(session)
    assert len(alerts) == 1
    assert alerts[0]["alert_type"] == "student_decline"
    assert alerts[0]["extra"]["profile_student_id"] is not None


def test_alert_homework_submission_low(session):
    # 班级 5 人，只 1 人提交，且作业临近截止。
    for i in range(5):
        _student(session, f"学生{i}")
    hw = hw_svc.create_homework(
        session, "在线作业", homework_type="exam",
        subject="数学", class_name="高一1班")
    hw.due_date = datetime.now() + timedelta(hours=24)
    session.flush()
    from models.models import HomeworkSubmission
    session.add(HomeworkSubmission(
        homework_id=hw.id, student_name="学生0",
        answers_json="[]", submitted_at=datetime.now()))
    session.flush()
    alerts = agent_alert.check_homework_submission(session)
    assert len(alerts) == 1
    assert alerts[0]["alert_type"] == "homework_submission"


def test_alert_progress_delay(session, monkeypatch):
    # 构造本周有课但无教案。
    schedule_data = {"entries": [
        {"class_name": "高一1班", "weekday": 0, "period": 1, "subject": "数学"}]}
    import utils.schedule_service as schedule_service
    monkeypatch.setattr(
        schedule_service, "load_schedule", lambda: schedule_data)
    alerts = agent_alert.check_progress_delay(session)
    assert len(alerts) == 1
    assert alerts[0]["alert_type"] == "progress_delay"


def test_alert_question_bank_low(session):
    # 某知识点只放 2 道已审核题。
    _question(session, kps=["函数"], content="题1")
    _question(session, kps=["函数"], content="题2")
    alerts = agent_alert.check_question_bank_low(session)
    assert any(a["alert_type"] == "question_bank_low" for a in alerts)


def test_alert_dedup_24h_and_resolved(session, tmp_path):
    today = date.today()
    _student(session, "张三")
    _exam(session, "考试1", today - timedelta(days=20), {"张三": 100})
    _exam(session, "考试2", today - timedelta(days=10), {"张三": 90})
    _exam(session, "考试3", today, {"张三": 80})

    first = agent_alert.check_all_alerts(session)
    assert first
    key = first[0]["dedup_key"]
    # 展示后记时间戳：24 小时内不再出现。
    agent_alert.mark_displayed(first)
    assert agent_alert.check_all_alerts(session) == []
    # 已处理后即便清掉 24 小时戳也不再显示。
    state = agent_alert.load_state()
    state["dismissed24"].pop(key, None)
    agent_alert.save_state(state)
    agent_alert.resolve_alert(key)
    assert agent_alert.check_all_alerts(session) == []


def test_alert_switch_disables_type(session):
    today = date.today()
    _student(session, "张三")
    _exam(session, "考试1", today - timedelta(days=20), {"张三": 100})
    _exam(session, "考试2", today - timedelta(days=10), {"张三": 90})
    _exam(session, "考试3", today, {"张三": 80})
    state = agent_alert.load_state()
    state["config"]["score_decline"] = False
    agent_alert.save_state(state)
    assert agent_alert.check_all_alerts(session) == []


def test_alert_corrupt_json_fallback_no_overwrite(session, tmp_path):
    path = tmp_path / "agent_alerts.json"
    path.write_text("{损坏内容", encoding="utf-8")
    state = agent_alert.load_state()
    assert state["config"]["score_decline"] is True
    # 读损坏文件不能覆盖原文件。
    assert path.read_text(encoding="utf-8") == "{损坏内容"


# ---------------------------------------------------------------------------
# 三、教学建议 Agent
# ---------------------------------------------------------------------------

def test_weekly_insufficient_when_empty(session):
    entry = agent_advisor.generate_weekly_suggestions(
        session, {"subject": "数学"})
    assert entry["insufficient"] is True
    assert "需要更多成绩数据" in entry["text"]


def test_weekly_cached_once_per_week(session, tmp_path):
    # 空库第一次生成写缓存，第二次直接读缓存。
    first = agent_advisor.generate_weekly_suggestions(
        session, {"subject": "数学"})
    assert first["week_id"] == agent_advisor.week_id()
    cached = agent_advisor.get_cached_weekly()
    assert cached is not None and cached["week_id"] == first["week_id"]


def test_weekly_with_data_and_template_fallback(session, monkeypatch):
    # 有考试数据，且 AI 不可用时走规则模板兜底。
    today = date.today()
    _student(session, "张三")
    _student(session, "李四")
    _exam(session, "月考", today, {"张三": 100, "李四": 60})
    monkeypatch.setattr(llm_client, "is_content_configured", lambda: False)
    entry = agent_advisor.generate_weekly_suggestions(
        session, {"subject": "数学"}, force=True)
    assert entry["insufficient"] is False
    assert entry["text"]
    assert entry["focus_points"]
    assert entry["measures"]


def test_weekly_llm_organized(session, monkeypatch):
    today = date.today()
    _student(session, "张三")
    _exam(session, "月考", today, {"张三": 90})
    monkeypatch.setattr(llm_client, "is_content_configured", lambda: True)
    reply = json.dumps({
        "text": "本周应重点巩固函数基础。",
        "focus_points": ["函数概念", "函数图像"],
        "measures": [{"measure": "增加函数例题", "method": "课堂调整",
                      "expected_effect": "提高掌握率"}]}, ensure_ascii=False)
    monkeypatch.setattr(llm_client, "chat_content",
                        lambda system, user, temperature=0.4: reply)
    entry = agent_advisor.generate_weekly_suggestions(
        session, {"subject": "数学"}, force=True)
    assert entry["text"] == "本周应重点巩固函数基础。"
    assert entry["focus_points"] == ["函数概念", "函数图像"]
    assert entry["measures"][0]["measure"] == "增加函数例题"


def test_layered_suggestions(session, monkeypatch):
    today = date.today()
    _student(session, "甲"); _student(session, "乙"); _student(session, "丙")
    _exam(session, "月考", today, {"甲": 120, "乙": 95, "丙": 60})
    data = agent_advisor.generate_layered_teaching_suggestions(
        session, "高一1班", "数学")
    assert data["insufficient"] is False
    assert sum(data["layers"].values()) == 3
    assert set(data["plans"]) == {"A", "B", "C"}


def test_layered_insufficient_when_no_exam(session):
    data = agent_advisor.generate_layered_teaching_suggestions(
        session, "高一1班", "数学")
    assert data["insufficient"] is True


def test_review_plan(session):
    today = date.today()
    _student(session, "张三")
    exam = _exam(session, "期末", today, {"张三": 90})
    data = agent_advisor.generate_review_plan(session, exam.id, days=4)
    assert len(data["daily"]) == 4
    assert data["error_points"] is not None


def test_intervention_plan(session):
    student = _student(session, "张三")
    today = date.today()
    _exam(session, "月考", today, {"张三": 60})
    data = agent_advisor.generate_intervention_plan(session, student.id)
    assert data["student_name"] == "张三"
    assert data["measures"]
    assert data["family"] and data["tracking"]


def test_advisor_corrupt_json_fallback(session, tmp_path):
    path = tmp_path / "agent_suggestions.json"
    path.write_text("损坏", encoding="utf-8")
    state = agent_advisor.load_state()
    assert state["weeks"] == []
    assert path.read_text(encoding="utf-8") == "损坏"


# ---------------------------------------------------------------------------
# 四、建议保存到教学反思
# ---------------------------------------------------------------------------

def test_save_weekly_to_reflection_creates_plan(session, monkeypatch):
    today = date.today()
    _student(session, "张三"); _student(session, "李四")
    _exam(session, "月考", today, {"张三": 100, "李四": 60})
    monkeypatch.setattr(llm_client, "is_content_configured", lambda: False)
    entry = agent_advisor.generate_weekly_suggestions(
        session, {"subject": "数学", "class_name": "高一1班"}, force=True)
    info = agent_advisor.save_weekly_to_reflection(session, entry)
    session.flush()

    reflection = session.get(TeachingReflection, info["reflection_id"])
    assert reflection is not None and reflection.has_plan == 1
    plan = (session.query(ReflectionPlan)
            .filter(ReflectionPlan.reflection_id == reflection.id).first())
    assert plan is not None and plan.status == "pending"


def test_save_weekly_insufficient_raises(session):
    entry = agent_advisor.generate_weekly_suggestions(
        session, {"subject": "数学"})
    with pytest.raises(ValueError):
        agent_advisor.save_weekly_to_reflection(session, entry)


# ---------------------------------------------------------------------------
# 五、AppTest：首页置顶、口语路由、complex 预览
# ---------------------------------------------------------------------------

def _app(tmp_path, name):
    db_file = tmp_path / f"{name}.db"
    # v2.3.0：默认跳过新手引导，避免其弹窗与本版测试的 toast 同帧触发
    # AppTest 框架对 Toast 占位节点的解析限制；引导本身在 test_v230 中覆盖。
    (db_file.parent / "onboarding.json").write_text(json.dumps({
        "completed_steps": [], "skipped": True,
        "snooze_until": "", "updated_at": ""
    }, ensure_ascii=False), encoding="utf-8")
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / f"{name}_feature.json"),
        default_timeout=30)
    at.run()
    return at, db_file


def test_app_empty_home_shows_two_blocks(tmp_path):
    at, _ = _app(tmp_path, "empty_home")
    assert not at.exception, [str(e) for e in at.exception]
    # 首页标题下应出现两个置顶区块。
    subheaders = [x.value for x in at.subheader]
    assert "🔔 智能提醒" in subheaders
    assert "💡 AI教学建议" in subheaders
    # 智能提醒区在前、建议区在后。
    assert subheaders.index("🔔 智能提醒") < subheaders.index("💡 AI教学建议")


def test_app_complex_instruction_shows_preview_only(tmp_path, monkeypatch):
    at, _ = _app(tmp_path, "complex_preview")
    intent = json.dumps({
        "intent": "prepare_lesson",
        "params": {"subject": "数学", "grade": "高一", "class_name": "高一1班",
                   "chapter": "", "knowledge_points": [],
                   "question_type": "", "count": 0, "difficulty": 0,
                   "student_name": "", "time_range": "",
                   "topic": "准备下周的课"}}, ensure_ascii=False)

    def fake_chat(system_prompt, user_text, temperature=0.0):
        return intent

    monkeypatch.setattr(llm_client, "is_content_configured", lambda: True)
    monkeypatch.setattr(llm_client, "chat_content", fake_chat)
    goto_assistant(at)

    next(x for x in at.text_area if x.key == "ai_assistant_page_input"
         ).set_value("帮我准备下周的课").run()
    next(x for x in at.button if x.key == "ai_assistant_run").click().run()
    assert not at.exception, [str(e) for e in at.exception]

    # complex 首轮只出预览，没有执行结果。
    preview = at.session_state.get("ai_assistant_plan_preview")
    assert preview and preview["plan"]
    assert at.session_state.get("ai_assistant_last_result") is None
    # 应出现确认、跳过、取消三个固定按钮。
    for key in ("ai_assistant_plan_confirm", "ai_assistant_plan_skip", "ai_assistant_plan_cancel"):
        assert any(x.key == key for x in at.button)


def test_app_complex_cancel_no_execution(tmp_path, monkeypatch):
    at, _ = _app(tmp_path, "complex_cancel")
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
    next(x for x in at.button if x.key == "ai_assistant_run").click().run()
    next(x for x in at.button if x.key == "ai_assistant_plan_cancel").click().run()
    assert not at.exception
    assert at.session_state.get("ai_assistant_plan_preview") is None


def test_app_quick_info_alerts_phrase(tmp_path, monkeypatch):
    at, _ = _app(tmp_path, "quick_alerts")
    goto_assistant(at)
    next(x for x in at.text_area if x.key == "ai_assistant_page_input"
         ).set_value("有什么需要注意的").run()
    next(x for x in at.button if x.key == "ai_assistant_run").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    last = at.session_state.get("ai_assistant_last_result")
    assert last and "暂无异常提醒" in last["summary"]


def test_app_dashboard_with_data_no_exception(tmp_path, monkeypatch):
    at, db_file = _app(tmp_path, "home_data")
    engine = create_engine(f"sqlite:///{db_file.as_posix()}")
    seed = sessionmaker(bind=engine)()
    student = Student(name="张三", class_name="高一1班")
    seed.add(student)
    seed.flush()
    exam = Exam(name="月考", exam_date=date.today())
    seed.add(exam)
    seed.flush()
    seed.add(Score(exam_id=exam.id, student_id=student.id,
                   subject="数学", score=88))
    seed.commit()
    seed.close()
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
