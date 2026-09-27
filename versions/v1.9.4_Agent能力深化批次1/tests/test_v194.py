# -*- coding: utf-8 -*-
"""v1.9.4 上下文记忆 + 多轮修正测试。"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from models.models import (
    Base, Homework, HomeworkQuestion, LessonPlan, LessonPlanVersion, Question)
from streamlit.testing.v1 import AppTest
from tests.test_app_smoke import _isolated_app_code, goto_sub
from utils import agent_context, agent_service, llm_client
from utils import homework_service as hw_svc
from utils import lesson_service
from utils import question_service


# ---------------------------------------------------------------------------
# 临时库与路径隔离
# ---------------------------------------------------------------------------

@pytest.fixture()
def session(tmp_path, monkeypatch):
    monkeypatch.setattr(
        agent_context, "AGENT_CONTEXT_PATH", tmp_path / "agent_context.json")
    monkeypatch.setattr(
        agent_service, "AGENT_HISTORY_PATH", tmp_path / "agent_history.json")
    engine = create_engine(f"sqlite:///{(tmp_path / 'v194.db').as_posix()}")
    Base.metadata.create_all(engine)
    sess = sessionmaker(bind=engine)()
    yield sess
    sess.close()
    engine.dispose()


def _make_question(sess, *, qtype="choice", difficulty=1,
                   kps=None, subject="数学", status="approved",
                   content=None):
    data = {
        "content": content or f"题目-{qtype}-{difficulty}-{datetime.now().microsecond}",
        "question_type": qtype, "difficulty": difficulty,
        "knowledge_points": json.dumps(kps or [], ensure_ascii=False),
        "answer": "A", "analysis": "", "error_points": "", "verify": None}
    q = question_service.create_question(
        sess, data, source="manual", status=status, subject=subject)
    sess.flush()
    return q


def _homework_with_questions(sess, questions):
    hw = hw_svc.create_homework(
        sess, "测试试卷", homework_type="exam",
        subject="数学", grade="十年级", class_name="高一1班")
    sess.flush()
    hw_svc.add_questions(sess, hw.id, [q.id for q in questions])
    sess.flush()
    return hw


# ---------------------------------------------------------------------------
# 一、上下文服务
# ---------------------------------------------------------------------------

def test_context_missing_returns_empty(session):
    assert agent_context.load_context()["subject"] == ""


def test_context_save_roundtrip_chinese(session):
    agent_context.update_context(
        subject="数学", grade="高一", class_name="高一1班",
        current_chapter="第一章 集合")
    loaded = agent_context.load_context()
    assert (loaded["subject"], loaded["grade"],
            loaded["class_name"], loaded["current_chapter"]) == (
        "数学", "高一", "高一1班", "第一章 集合")
    assert loaded["updated_at"]


def test_context_corrupt_json_not_overwritten(session, tmp_path):
    path = tmp_path / "agent_context.json"
    path.write_text("这不是JSON", encoding="utf-8")
    assert agent_context.load_context()["subject"] == ""
    assert path.read_text(encoding="utf-8") == "这不是JSON"


def test_context_expires_after_30_days(session, tmp_path):
    old = agent_context.empty_context()
    old.update({"subject": "数学",
                "updated_at": (datetime.now() - timedelta(days=31)
                               ).strftime("%Y-%m-%d %H:%M:%S")})
    (tmp_path / "agent_context.json").write_text(
        json.dumps(old, ensure_ascii=False), encoding="utf-8")
    assert agent_context.load_context()["subject"] == ""


def test_context_rejects_invalid_subject_and_grade(session):
    agent_context.update_context(subject="伪学科", grade="伪年级")
    loaded = agent_context.load_context()
    assert loaded["subject"] == "" and loaded["grade"] == ""


def test_fill_intent_params_only_missing(session):
    agent_context.update_context(subject="数学", grade="高一",
                                 class_name="高一1班")
    # 显式给的语文不被上下文数学覆盖
    params = agent_context.fill_intent_params(
        {"subject": "语文"})
    assert params["subject"] == "语文"
    assert params["grade"] == "高一" and params["class_name"] == "高一1班"


def test_extract_context_from_instruction(session):
    patch = agent_context.extract_context_from_instruction(
        "记住我现在教高二物理，班级是高二3班")
    assert patch["subject"] == "物理" and patch["grade"] == "高二"
    assert "3班" in patch["class_name"]


def test_clear_context(session):
    agent_context.update_context(subject="数学")
    assert agent_context.clear_context()["subject"] == ""
    assert agent_context.load_context()["subject"] == ""


# ---------------------------------------------------------------------------
# 二、修正识别
# ---------------------------------------------------------------------------

def _last_homework_result(session):
    q = _make_question(session)
    hw = _homework_with_questions(session, [q])
    artifact = agent_service._homework_artifact(session, hw, [])
    return {"artifact": artifact, "correction_count": 0}, hw, q


def test_no_last_result_not_correction(session):
    from utils.agent_intents import is_correction_instruction
    assert is_correction_instruction("把第2题改难", None) is False


def test_normal_new_instruction_not_correction(session):
    from utils.agent_intents import is_correction_instruction
    last, _, _ = _last_homework_result(session)
    assert is_correction_instruction("出一道改写句子题", last) is False


def test_revise_and_add_recognized(session):
    from utils.agent_intents import (
        is_correction_instruction, parse_correction)
    last, _, _ = _last_homework_result(session)
    text1 = "把第2题改难一点"
    text2 = "增加2道选择题"
    assert is_correction_instruction(text1, last)
    assert is_correction_instruction(text2, last)
    c1 = parse_correction(text1, last)
    assert c1["action"] == "revise" and c1["targets"] == [2]
    c2 = parse_correction(text2, last)
    assert (c2["action"], c2["question_type"], c2["count"]) == (
        "add", "choice", 2)


# ---------------------------------------------------------------------------
# 三、试卷修正
# ---------------------------------------------------------------------------

def test_revise_creates_new_pending_question(session, monkeypatch):
    last, hw, old_q = _last_homework_result(session)

    def fake_modify(question, instruction, context=None):
        return dict(question, difficulty=2)

    monkeypatch.setattr(question_service, "modify_question", fake_modify)
    result = agent_service._correct_homework(
        session,
        {"action": "revise", "targets": [1], "instruction": "把第1题改难一点"},
        last)
    session.flush()
    assert result["correction_count"] == 1

    links = hw_svc.homework_questions(session, hw.id)
    assert len(links) == 1
    link, new_q = links[0]
    assert new_q.id != old_q.id
    assert new_q.difficulty == 2 and new_q.status == "pending"
    assert new_q.source == "AI 修正" and new_q.grade == "高一"
    # 原题保持不变
    assert session.get(Question, old_q.id).difficulty == 1


def test_replace_type_keeps_score(session, monkeypatch):
    last, hw, old_q = _last_homework_result(session)
    # 给原题关联设置分值
    link_row = session.query(HomeworkQuestion).filter(
        HomeworkQuestion.homework_id == hw.id,
        HomeworkQuestion.question_id == old_q.id).first()
    link_row.score = 8.0

    def fake_modify(question, instruction, context=None):
        return dict(question, question_type="fill", answer="填空答案")

    monkeypatch.setattr(question_service, "modify_question", fake_modify)
    agent_service._correct_homework(
        session, {"action": "replace", "targets": [1],
                  "instruction": "第1题换成填空题"}, last)
    session.flush()
    link, new_q = hw_svc.homework_questions(session, hw.id)[0]
    assert new_q.question_type == "fill"
    assert link.score == 8.0


def test_add_questions_increases_count(session):
    # 再准备 2 道已审核题供追加
    extra = [_make_question(session, difficulty=2),
             _make_question(session, difficulty=2)]
    last, hw, _ = _last_homework_result(session)
    before = hw_svc.question_count(session, hw.id)
    correction = {"action": "add", "question_type": "choice",
                  "count": 2, "instruction": "增加2道选择题"}
    agent_service._correct_homework(session, correction, last)
    session.flush()
    assert hw_svc.question_count(session, hw.id) == before + 2


def test_remove_only_drops_link(session):
    last, hw, old_q = _last_homework_result(session)
    agent_service._correct_homework(
        session, {"action": "remove", "targets": [1],
                  "instruction": "删掉第1题"}, last)
    session.flush()
    assert hw_svc.question_count(session, hw.id) == 0
    # 题库原题仍在
    assert session.get(Question, old_q.id) is not None


def test_undo_homework_correction(session, monkeypatch):
    last, hw, old_q = _last_homework_result(session)

    monkeypatch.setattr(
        question_service, "modify_question",
        lambda question, instruction, context=None: dict(question, difficulty=2))
    corrected = agent_service._correct_homework(
        session, {"action": "revise", "targets": [1],
                  "instruction": "把第1题改难"}, last)
    _, new_q = hw_svc.homework_questions(session, hw.id)[0]
    assert new_q.id != old_q.id

    undone = agent_service.undo_last_correction(session, corrected)
    session.flush()
    _, restored = hw_svc.homework_questions(session, hw.id)[0]
    assert restored.id == old_q.id
    # 撤销不删除新生成的题库题
    assert session.get(Question, new_q.id) is not None
    assert undone["correction_count"] == 0


def test_batch_modify_questions(session, monkeypatch):
    q1 = _make_question(session)
    q2 = _make_question(session)
    d1 = question_service.question_to_data(q1)
    d2 = question_service.question_to_data(q2)
    payload = json.dumps({
        "questions": [
            {"source_index": 0, "content": d1["content"], "answer": "A",
             "difficulty": 2},
            {"source_index": 1, "content": d2["content"], "answer": "A",
             "difficulty": 3},
        ]}, ensure_ascii=False)
    monkeypatch.setattr(llm_client, "chat_content",
                        lambda *a, **k: payload)
    result = question_service.batch_modify_questions(
        [q1, q2], "全部改难")
    assert result[0]["difficulty"] == 2 and result[1]["difficulty"] == 3


# ---------------------------------------------------------------------------
# 四、教案修正
# ---------------------------------------------------------------------------

def _saved_lesson(session):
    plan = {
        "subject": "数学",
        "objectives": {"knowledge": "原始目标", "process": "", "emotion": ""},
        "key_points": "重点", "difficult_points": "难点",
        "process": [{"stage": "导入", "minutes": 10, "content": "内容"}],
        "board_design": "板书",
    }
    lesson = lesson_service.save_plan(
        session, "函数", plan, grade="十年级", subject="数学")
    session.flush()
    return lesson, plan


def test_lesson_correction_updates_in_place(session, monkeypatch):
    lesson, plan = _saved_lesson(session)
    original_id = lesson.id
    monkeypatch.setattr(
        lesson_service, "modify_lesson_plan",
        lambda p, instruction: dict(
            p, objectives={**p["objectives"], "knowledge": "更具体目标"}))
    last = {"artifact": {"artifact_type": "lesson_plan",
                          "plan_id": original_id, "undo_stack": []},
            "correction_count": 0}
    result = agent_service._correct_lesson(
        session, {"action": "revise", "instruction": "把教学目标改具体"}, last)
    session.flush()
    assert lesson.id == original_id
    loaded = lesson_service.load_plan(lesson)
    assert loaded["objectives"]["knowledge"] == "更具体目标"
    assert result["correction_count"] == 1
    # 自动产生新版本
    versions = session.query(LessonPlanVersion).filter(
        LessonPlanVersion.plan_id == original_id).count()
    assert versions >= 2


def test_undo_lesson_correction(session, monkeypatch):
    lesson, plan = _saved_lesson(session)
    monkeypatch.setattr(
        lesson_service, "modify_lesson_plan",
        lambda p, instruction: dict(
            p, objectives={**p["objectives"], "knowledge": "新目标"}))
    last = {"artifact": {"artifact_type": "lesson_plan",
                          "plan_id": lesson.id, "undo_stack": []},
            "correction_count": 0}
    corrected = agent_service._correct_lesson(
        session, {"action": "revise", "instruction": "改目标"}, last)
    agent_service.undo_last_correction(session, corrected)
    session.flush()
    assert lesson_service.load_plan(lesson)["objectives"]["knowledge"] == "原始目标"


# ---------------------------------------------------------------------------
# 五、分析修正
# ---------------------------------------------------------------------------

def test_analysis_change_to_trend(session):
    last = {"artifact": {"artifact_type": "analysis",
                          "params": {"student_id": 1, "subject": "语文"},
                          "undo_stack": []},
            "correction_count": 0, "summary": "旧分析"}
    result = agent_service._correct_analysis(
        {"action": "change_analysis", "instruction": "再看看数学的趋势"}, last)
    assert result["route"] == "📊 学情" and result["sub"] == "趋势分析"
    assert result["extra"]["trend_subject"] == "数学"
    assert result["correction_count"] == 1


def test_analysis_unsupported_filter_raises(session):
    last = {"artifact": {"artifact_type": "analysis",
                          "params": {"student_id": 1}, "undo_stack": []},
            "correction_count": 0, "summary": "旧分析"}
    with pytest.raises(ValueError, match="不支持"):
        agent_service._correct_analysis(
            {"action": "change_analysis", "instruction": "只看男生"}, last)


# ---------------------------------------------------------------------------
# 六、历史记录
# ---------------------------------------------------------------------------

def test_correction_history_duplicate_and_parent(session, monkeypatch):
    last, hw, _ = _last_homework_result(session)
    monkeypatch.setattr(
        question_service, "modify_question",
        lambda question, instruction, context=None: dict(question, difficulty=2))
    correction = {"action": "revise", "targets": [1],
                  "instruction": "把第1题改难"}
    result = agent_service._correct_homework(session, correction, last)
    agent_service._append_history(
        agent_service._history_item(
            "把第1题改难", result, correction=correction),
        allow_duplicate=True)
    # 相同修正文本可连续再记一条
    agent_service._append_history(
        agent_service._history_item(
            "把第1题改难", result, correction=correction),
        allow_duplicate=True)
    rows = agent_service.list_agent_history()
    corrections = [r for r in rows if r["entry_kind"] == "correction"]
    assert len(corrections) == 2
    assert all(r["artifact_type"] == "homework" for r in corrections)


def test_reexecute_missing_history_raises(session):
    with pytest.raises(ValueError, match="找不到历史记录"):
        agent_service.reexecute_agent_history(session, "不存在的id")


def test_reexecute_correction_without_last_raises(session, monkeypatch):
    # 构造一条修正历史，但不提供 last_result，应要求先执行原指令。
    fake = [{
        "history_id": "corr1", "instruction": "把第1题改难",
        "entry_kind": "correction", "artifact_type": "homework"}]
    monkeypatch.setattr(agent_service, "list_agent_history", lambda: fake)
    with pytest.raises(ValueError, match="原指令"):
        agent_service.reexecute_agent_history(session, "corr1")


# ---------------------------------------------------------------------------
# AppTest
# ---------------------------------------------------------------------------

def _app(tmp_path, name):
    db_file = tmp_path / f"{name}.db"
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / f"{name}_feature.json"),
        default_timeout=30)
    at.run()
    return at, db_file


def test_app_empty_has_context_controls(tmp_path):
    at, _ = _app(tmp_path, "empty")
    assert not at.exception, [str(e) for e in at.exception]
    assert any(x.key == "agent_context_edit" for x in at.button)
    assert any(x.key == "agent_context_reset" for x in at.button)
    assert any(x.key == "agent_assistant_input" for x in at.text_area)
    # 直接按钮仍在
    assert any(x.key == "nav_home" for x in at.button)


def test_app_page_control_syncs_context(tmp_path):
    at, _ = _app(tmp_path, "sync")
    assert not at.exception
    goto_sub(at, "lesson_plan_tab", "AI 备课", "📚 备课")
    # 先切到与当前值不同的年级，再切高二，保证 on_change 真触发
    next(x for x in at.selectbox if x.key == "lesson_grade_select"
         ).set_value("初一").run()
    next(x for x in at.selectbox if x.key == "lesson_grade_select"
         ).set_value("高二").run()
    assert not at.exception
    ctx_path = tmp_path / "agent_context.json"
    saved = json.loads(ctx_path.read_text(encoding="utf-8"))
    assert saved["grade"] == "高二"


def test_app_compose_then_correction(tmp_path, monkeypatch):
    at, db_file = _app(tmp_path, "compose")

    # 预置 5 道已审核选择题
    engine = create_engine(f"sqlite:///{db_file.as_posix()}")
    seed_sess = sessionmaker(bind=engine)()
    for i in range(5):
        _make_question(seed_sess, content=f"预置选择题{i}")
    seed_sess.commit()
    seed_sess.close()

    # 预置上下文文件
    ctx = agent_context.empty_context()
    ctx.update({"subject": "数学", "grade": "高一", "class_name": "高一1班",
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
    (tmp_path / "agent_context.json").write_text(
        json.dumps(ctx, ensure_ascii=False), encoding="utf-8")

    compose_intent = json.dumps({
        "intent": "compose_paper",
        "params": {"subject": "数学", "grade": "高一", "class_name": "高一1班",
                   "chapter": "", "knowledge_points": [],
                   "question_type": "choice", "count": 5, "difficulty": 1,
                   "student_name": "", "time_range": "", "topic": ""}},
        ensure_ascii=False)

    def fake_chat(system_prompt, user_text, temperature=0.0):
        if "解析器" in system_prompt:
            return compose_intent
        raise AssertionError("不应有其他 LLM 调用")

    monkeypatch.setattr(llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(llm_client, "chat_content", fake_chat)
    at.run()

    next(x for x in at.text_area if x.key == "agent_assistant_input"
         ).set_value("出5道选择题").run()
    next(x for x in at.button if x.key == "agent_run").click().run()
    assert not at.exception, [str(e) for e in at.exception]

    last = at.session_state["agent_last_result"]
    assert last["status"] == "success"
    hw_id = last["extra"]["hw_open_id"]

    # 多轮修正：把第2题改难
    monkeypatch.setattr(
        question_service, "modify_question",
        lambda question, instruction, context=None: dict(question, difficulty=2))
    next(x for x in at.text_area if x.key == "agent_assistant_input"
         ).set_value("把第2题改难一点").run()
    next(x for x in at.button if x.key == "agent_run").click().run()
    assert not at.exception, [str(e) for e in at.exception]

    corrected = at.session_state["agent_last_result"]
    assert corrected["correction_count"] == 1

    # 数据库断言：第 2 个关联被替换为新题
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT hq.question_id, q.difficulty, q.status, q.source, q.grade
            FROM homework_questions hq JOIN questions q ON q.id = hq.question_id
            WHERE hq.homework_id = :hid ORDER BY hq."order" """),
            {"hid": hw_id}).fetchall()
        total_q = conn.execute(text(
            "SELECT COUNT(*) FROM questions")).scalar_one()
    assert len(rows) == 5 and total_q == 6
    second = rows[1]
    assert second[0] not in range(1, 6)
    assert second[1] == 2 and second[2] == "pending"
    assert second[3] == "AI 修正" and second[4] == "高一"

    # 撤销修正
    next(x for x in at.button if x.key == "agent_undo_correction"
         ).click().run()
    assert not at.exception
    with engine.connect() as conn:
        restored_id = conn.execute(text("""
            SELECT question_id FROM homework_questions
            WHERE homework_id = :hid ORDER BY "order" LIMIT 1 OFFSET 1 """),
            {"hid": hw_id}).scalar_one()
    assert restored_id in range(1, 6)
    engine.dispose()


def test_app_lesson_then_correction(tmp_path, monkeypatch):
    at, _ = _app(tmp_path, "lesson")

    prepare_intent = json.dumps({
        "intent": "prepare_lesson",
        "params": {"subject": "数学", "grade": "高一", "class_name": "",
                   "chapter": "", "knowledge_points": [],
                   "question_type": "", "count": 0, "difficulty": 0,
                   "student_name": "", "time_range": "",
                   "topic": "函数的概念"}}, ensure_ascii=False)
    lesson_json = json.dumps({
        "subject": "数学",
        "objectives": {"knowledge": "掌握函数概念", "process": "", "emotion": ""},
        "key_points": "重点", "difficult_points": "难点",
        "process": [{"stage": "导入", "minutes": 10, "content": "内容"}],
        "board_design": "板书"}, ensure_ascii=False)

    def fake_chat(system_prompt, user_text, temperature=0.0):
        if "解析器" in system_prompt:
            return prepare_intent
        return lesson_json

    monkeypatch.setattr(llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(llm_client, "chat_content", fake_chat)
    at.run()
    next(x for x in at.text_area if x.key == "agent_assistant_input"
         ).set_value("备一节函数的概念课").run()
    next(x for x in at.button if x.key == "agent_run").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    last = at.session_state["agent_last_result"]
    assert last["status"] == "success"
    plan_id = last["extra"]["pending_load_plan_id"]

    # 教案修正
    monkeypatch.setattr(
        lesson_service, "modify_lesson_plan",
        lambda p, instruction: dict(
            p, objectives={**p["objectives"], "knowledge": "更具体的目标"}))
    next(x for x in at.text_area if x.key == "agent_assistant_input"
         ).set_value("把教学目标改得更具体").run()
    next(x for x in at.button if x.key == "agent_run").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    corrected = at.session_state["agent_last_result"]
    assert corrected["correction_count"] == 1

    engine = create_engine(f"sqlite:///{(tmp_path / 'lesson.db').as_posix()}")
    with engine.connect() as conn:
        content = conn.execute(text(
            "SELECT content FROM lesson_plans WHERE id = :id"),
            {"id": plan_id}).scalar_one()
        versions = conn.execute(text(
            "SELECT COUNT(*) FROM lesson_plan_versions WHERE plan_id = :id"),
            {"id": plan_id}).scalar_one()
    engine.dispose()
    assert "更具体的目标" in content
    assert versions >= 2
