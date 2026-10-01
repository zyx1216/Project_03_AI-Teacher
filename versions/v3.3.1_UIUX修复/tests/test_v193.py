# -*- coding: utf-8 -*-
"""v1.9.3 教学反思改进闭环测试。"""

from __future__ import annotations

import io
import json
from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from models.models import (
    Base, Homework, HomeworkAnswer, HomeworkQuestion, Question,
    ReflectionPlan, Student)
from streamlit.testing.v1 import AppTest
from tests.test_app_smoke import _isolated_app_code, goto_sub
from utils import db as db_service
from utils import llm_client, reflection_service as rs


MEASURES = [
    {"measure": "增加当堂反馈", "method": "课堂调整", "expected_effect": "得分率提高"},
    {"measure": "布置分层练习", "method": "作业优化", "expected_effect": "减少低分"},
]


@pytest.fixture()
def session(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'v193.db').as_posix()}")
    Base.metadata.create_all(engine)
    sess = sessionmaker(bind=engine)()
    yield sess
    sess.close()
    engine.dispose()


def _exam_with_scores(sess, name: str, day: date, scores: tuple[float, float]):
    from utils import exam_service
    students = sess.query(Student).order_by(Student.id).all()
    _exam_with_scores.counter = getattr(_exam_with_scores, "counter", 0) + 1
    exam = exam_service.create_exam(
        sess, f"{name}-{_exam_with_scores.counter}", exam_date=day,
        grade="八年级", full_scores={"数学": 100})
    sess.flush()
    exam_service.import_scores(sess, exam.id, [
        {"name": students[0].name, "class_name": "一班",
         "scores": {"数学": scores[0]}},
        {"name": students[1].name, "class_name": "一班",
         "scores": {"数学": scores[1]}},
    ])
    sess.flush()
    return exam


def _prepare_students(sess):
    rows = [Student(name="闭环甲", class_name="一班"),
            Student(name="闭环乙", class_name="一班")]
    sess.add_all(rows)
    sess.flush()
    return rows


def _closed_loop(sess, before=(50, 50), after=(70, 70), add_answers=False):
    """构造基准考试、反思、验证考试和待验证计划。"""
    _prepare_students(sess)
    base = _exam_with_scores(sess, "基准考试", date(2026, 3, 1), before)
    reflection = rs.save_reflection(
        sess, "一轮课后反思", "exam", base.id, "一班",
        {"成功之处": "节奏清楚", "不足之处": "计算薄弱",
         "学生反馈": "希望多练", "改进措施": "加强反馈"})
    reflection.created_at = datetime(2026, 3, 2, 9, 0)
    verify = _exam_with_scores(sess, "验证考试", date(2026, 5, 10), after)
    plan = rs.save_plan(sess, reflection.id, MEASURES, verify.id)
    sess.flush()
    if add_answers:
        q = Question(
            content="计算 2+3", question_type="fill", difficulty=1,
            knowledge_points='["有理数运算"]', answer="5",
            subject="数学", grade="八年级")
        sess.add(q)
        sess.flush()
        for exam_day, correct_values in (
                (base.exam_date, (False, False)),
                (verify.exam_date, (True, True))):
            hw = Homework(
                name=f"逐题作业-{exam_day}", homework_type="after_class",
                class_name="一班", subject="数学", grade="八年级",
                status="completed", completed_at=datetime.combine(
                    exam_day, datetime.min.time()))
            sess.add(hw)
            sess.flush()
            sess.add(HomeworkQuestion(
                homework_id=hw.id, question_id=q.id, order=1, score=10))
            students = sess.query(Student).order_by(Student.id).all()
            for stu, ok in zip(students, correct_values):
                sess.add(HomeworkAnswer(
                    homework_id=hw.id, student_id=stu.id, question_id=q.id,
                    order_no=1, is_correct=ok, earned_score=10 if ok else 0))
        sess.flush()
    return base, reflection, verify, plan

# ---------------------------------------------------------------------------
# 服务层测试
# ---------------------------------------------------------------------------


def test_database_has_21_tables_and_reflection_plan_columns(session):
    assert len(Base.metadata.tables) == 34
    assert "reflection_plans" in Base.metadata.tables
    columns = {c["name"]: c for c in inspect(session.bind).get_columns(
        "teaching_reflections")}
    assert "has_plan" in columns
    pending = db_service._PENDING_COLUMNS["teaching_reflections"]
    assert ("has_plan", "INTEGER DEFAULT 0") in pending


def test_add_has_plan_column_to_legacy_db(tmp_path):
    db_file = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{db_file.as_posix()}")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE teaching_reflections ("
            "id INTEGER PRIMARY KEY, title TEXT, scope_type TEXT, "
            "start_exam_id INTEGER, end_exam_id INTEGER, class_name TEXT, "
            "content TEXT, created_at TEXT, updated_at TEXT)"))
    original_engine = db_service.engine
    db_service.engine = engine
    try:
        db_service._add_missing_columns()
        db_service._add_missing_columns()  # 重复执行不报错
        cols = {c["name"] for c in inspect(engine).get_columns(
            "teaching_reflections")}
        assert "has_plan" in cols
    finally:
        db_service.engine = original_engine
        engine.dispose()


def test_generate_improvement_plan(monkeypatch):
    def fake_chat(system_prompt, user_text, temperature=0.4):
        assert "教学反思" in user_text
        return json.dumps(MEASURES, ensure_ascii=False)

    monkeypatch.setattr(llm_client, "chat_content", fake_chat)
    result = rs.generate_improvement_plan("学生计算薄弱", "数学")
    assert result == MEASURES


def test_generate_improvement_plan_bad_json(monkeypatch):
    monkeypatch.setattr(llm_client, "chat_content", lambda *a, **k: "不是JSON")
    with pytest.raises(ValueError, match="格式不正确"):
        rs.generate_improvement_plan("反思", None)


def test_save_get_update_delete_plan(session):
    reflection = rs.save_reflection(
        session, "反思", "exam", 1, "一班",
        {"成功之处": "", "不足之处": "问题", "学生反馈": "", "改进措施": ""})
    session.flush()
    plan = rs.save_plan(session, reflection.id, MEASURES, None)
    assert reflection.has_plan == 1
    assert rs.get_plan_by_reflection(session, reflection.id).id == plan.id

    changed = [{"measure": "改成个别辅导", "method": "个别辅导",
                "expected_effect": "补齐基础"}]
    rs.update_plan(session, plan.id, changed, None)
    assert rs.plan_content(plan) == changed

    rs.delete_plan(session, plan.id)
    assert rs.get_plan_by_reflection(session, reflection.id) is None
    assert reflection.has_plan == 0


def test_delete_reflection_deletes_plan(session):
    reflection = rs.save_reflection(
        session, "反思", "exam", 1, None,
        {"成功之处": "", "不足之处": "问题", "学生反馈": "", "改进措施": ""})
    session.flush()
    plan = rs.save_plan(session, reflection.id, MEASURES, None)
    rs.delete_reflection(session, reflection.id)
    session.flush()
    assert session.get(type(plan), plan.id) is None


def test_verify_report_effect_levels(session):
    _closed_loop(session, before=(50, 50), after=(70, 70))
    plan = rs.get_plan_by_reflection(session, 1)
    report = rs.verify_plan(session, plan.id)
    assert report["overall_effect"] == "有效"
    assert report["overall_delta"] == 20
    assert report["measure_effects"][0]["attainment"] == 1

    _closed_loop(session, before=(50, 50), after=(52, 52))
    plan = rs.get_plan_by_reflection(session, 2)
    report = rs.verify_plan(session, plan.id)
    assert report["overall_effect"] == "部分有效"
    assert report["overall_delta"] == 2

    _closed_loop(session, before=(50, 50), after=(40, 40))
    plan = rs.get_plan_by_reflection(session, 3)
    report = rs.verify_plan(session, plan.id)
    assert report["overall_effect"] == "效果不明显"
    assert report["overall_delta"] == -10


def test_verify_same_exam_and_missing_scores(session):
    _prepare_students(session)
    base = _exam_with_scores(session, "基准", date(2026, 3, 1), (60, 60))
    reflection = rs.save_reflection(
        session, "反思", "exam", base.id, "一班",
        {"成功之处": "", "不足之处": "问题", "学生反馈": "", "改进措施": ""})
    reflection.created_at = datetime(2026, 3, 2)
    plan = ReflectionPlan(
        reflection_id=reflection.id,
        content=json.dumps(MEASURES, ensure_ascii=False),
        verify_exam_id=base.id, status="pending",
        created_at=datetime(2026, 3, 2))
    session.add(plan)
    session.flush()
    with pytest.raises(ValueError, match="不能和基准考试相同"):
        rs.verify_plan(session, plan.id)

    verify = _exam_with_scores(session, "空成绩考试", date(2026, 5, 1), (0, 0))
    # 把刚导入的成绩删掉，制造验证考试无成绩。
    session.execute(text("DELETE FROM scores WHERE exam_id = :eid"),
                    {"eid": verify.id})
    plan.verify_exam_id = verify.id
    with pytest.raises(ValueError, match="暂无成绩"):
        rs.verify_plan(session, plan.id)


def test_knowledge_effects_with_real_answers(session):
    _closed_loop(session, add_answers=True)
    plan = rs.get_plan_by_reflection(session, 1)
    report = rs.verify_plan(session, plan.id)
    assert report["knowledge_effects"][0]["knowledge_point"] == "有理数运算"
    assert report["knowledge_effects"][0]["delta"] == 100
    assert "无逐题数据，不评估知识点变化。" not in report["data_support"]


def test_knowledge_effects_without_real_answers(session):
    _closed_loop(session, add_answers=False)
    plan = rs.get_plan_by_reflection(session, 1)
    report = rs.verify_plan(session, plan.id)
    assert report["knowledge_effects"] == []
    assert "无逐题数据，不评估知识点变化。" in report["data_support"]


def test_check_and_verify_pending_plans(session):
    _, _, verify, plan = _closed_loop(session)
    ids = rs.check_and_verify_pending_plans(session, verify.id)
    assert ids == [plan.id]
    assert plan.status == "verified"
    report = json.loads(plan.verify_result)
    assert report["overall_effect"] == "有效"


def test_manual_verify_plan(session):
    reflection = rs.save_reflection(
        session, "无验证考试反思", "exam", None, "一班",
        {"成功之处": "", "不足之处": "问题", "学生反馈": "", "改进措施": ""})
    session.flush()
    plan = rs.save_plan(session, reflection.id, MEASURES, None)
    report = rs.mark_plan_verified_manually(session, plan.id)
    assert plan.status == "verified"
    assert report["overall_effect"] == "手动确认"
    assert report["measure_effects"][0]["attainment"] == 1


def test_refresh_expired_then_reactivate(session):
    from utils import exam_service
    students = _prepare_students(session)
    base = _exam_with_scores(session, "基准", date(2026, 8, 1), (50, 50))
    reflection = rs.save_reflection(
        session, "开学反思", "exam", base.id, "一班",
        {"成功之处": "", "不足之处": "计算薄弱", "学生反馈": "", "改进措施": ""})
    reflection.created_at = datetime(2026, 8, 2)
    verify = exam_service.create_exam(
        session, "已过期考试", exam_date=date(2026, 9, 1),
        full_scores={"数学": 100})
    session.flush()
    plan = rs.save_plan(session, reflection.id, MEASURES, verify.id)
    assert rs.refresh_expired_plans(session) == 1
    assert plan.status == "expired"

    exam_service.import_scores(session, verify.id, [
        {"name": students[0].name, "class_name": "一班",
         "scores": {"数学": 70}},
        {"name": students[1].name, "class_name": "一班",
         "scores": {"数学": 70}},
    ])
    ids = rs.check_and_verify_pending_plans(session, verify.id)
    assert ids == [plan.id]
    assert plan.status == "verified"


def test_improvement_history_filter_and_export(session):
    _, reflection, _, plan = _closed_loop(session)
    rs.mark_plan_verified_manually(session, plan.id)
    session.flush()
    all_items = rs.get_improvement_history(session)
    assert len(all_items) == 1
    assert all_items[0]["reflection_id"] == reflection.id
    assert all_items[0]["measure_count"] == 2
    assert rs.get_improvement_history(session, subject="数学")
    assert rs.get_improvement_history(
        session, start_date=date(2026, 3, 1), end_date=date(2026, 3, 31))
    assert not rs.get_improvement_history(session, subject="英语")
    assert not rs.get_improvement_history(
        session, start_date=date(2026, 6, 1))

    blob = rs.export_improvement_report(session, all_items)
    assert blob[:2] == b"PK"
    from docx import Document
    doc = Document(io.BytesIO(blob))
    assert any(p.text.startswith("1. 一轮课后反思") for p in doc.paragraphs)

# ---------------------------------------------------------------------------
# AppTest 辅助
# ---------------------------------------------------------------------------


def _make_students_exam(sess, title: str, day: date, scores=None):
    from utils import exam_service, student_service
    students = [
        student_service.get_or_create_student(sess, "闭环甲", "一班")[0],
        student_service.get_or_create_student(sess, "闭环乙", "一班")[0]]
    exam = exam_service.create_exam(
        sess, title, exam_date=day, grade="八年级",
        full_scores={"数学": 100})
    sess.flush()
    if scores is not None:
        exam_service.import_scores(sess, exam.id, [
            {"name": students[0].name, "class_name": "一班",
             "scores": {"数学": scores[0]}},
            {"name": students[1].name, "class_name": "一班",
             "scores": {"数学": scores[1]}},
        ])
    sess.flush()
    return students, exam


def _seed_reflection_db(db_file: Path, *, plan="pending", verified=False):
    engine = create_engine(f"sqlite:///{db_file.as_posix()}")
    Base.metadata.create_all(engine)
    sess = sessionmaker(bind=engine)()
    _students, base = _make_students_exam(
        sess, "基准考试", date(2026, 9, 1), scores=(50, 50))
    reflection = rs.save_reflection(
        sess, "一轮课后反思", "exam", base.id, "一班",
        {"成功之处": "节奏清楚", "不足之处": "计算薄弱",
         "学生反馈": "希望多练", "改进措施": "加强反馈"})
    reflection.created_at = datetime(2026, 9, 2, 9, 0)
    _students2, verify = _make_students_exam(
        sess, "验证考试", date(2026, 12, 1), scores=None)
    sess.flush()
    plan_row = None
    if plan:
        plan_row = rs.save_plan(sess, reflection.id, MEASURES, verify.id)
        if verified:
            rs.mark_plan_verified_manually(sess, plan_row.id)
    sess.commit()
    ids = {"reflection": reflection.id, "verify": verify.id,
           "plan": plan_row.id if plan_row else None}
    sess.close()
    engine.dispose()
    return ids


def _reflection_app(tmp_path, name="reflection"):
    db_file = tmp_path / f"{name}.db"
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / f"{name}_feature.json"),
        default_timeout=30)
    at.run()
    # v2.4.0：教学反思是独立顶级页（不再是学情子功能）。
    at.session_state["app_top_page"] = "💭 教学反思"
    at.run()
    return at, db_file

# ---------------------------------------------------------------------------
# AppTest
# ---------------------------------------------------------------------------


def test_reflection_empty_page_has_nested_tabs(tmp_path):
    at, _ = _reflection_app(tmp_path, "empty_reflection")
    assert not at.exception, [str(e) for e in at.exception]
    # v2.4.0：独立页三标签；空考试时教学反思区给引导提示。
    assert [tab.label for tab in at.tabs] == [
        "🎙️ 课堂实录", "💭 教学反思", "📚 改进历史"]
    assert any("还没有考试数据" in str(x.value) for x in at.info)


def test_saved_reflection_shows_make_plan_entry(tmp_path):
    at, db_file = _reflection_app(tmp_path, "saved_reflection")
    _seed_reflection_db(db_file, plan=False)
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    assert any(x.key == "make_plan_1" for x in at.button)


def test_generate_and_save_plan_in_dialog(tmp_path, monkeypatch):
    at, db_file = _reflection_app(tmp_path, "make_plan")
    ids = _seed_reflection_db(db_file, plan=False)

    def fake_chat_content(system_prompt, user_text, temperature=0.4):
        assert "教学反思" in user_text
        return json.dumps(MEASURES, ensure_ascii=False)

    monkeypatch.setattr(llm_client, "chat_content", fake_chat_content)
    at.run()
    next(x for x in at.button if x.key == "make_plan_1").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    gen = next(x for x in at.button if x.key == "plan_generate")
    gen.click().run()
    assert not at.exception, [str(e) for e in at.exception]
    next(x for x in at.button if x.key == "plan_save").click().run()
    assert not at.exception, [str(e) for e in at.exception]

    engine = create_engine(f"sqlite:///{db_file.as_posix()}")
    with engine.connect() as conn:
        count = conn.execute(text(
            "SELECT COUNT(*) FROM reflection_plans "
            "WHERE reflection_id = :rid"), {"rid": ids["reflection"]}).scalar_one()
        has_plan = conn.execute(text(
            "SELECT has_plan FROM teaching_reflections WHERE id = :rid"),
            {"rid": ids["reflection"]}).scalar_one()
    engine.dispose()
    assert count == 1 and has_plan == 1
    assert any(x.key == f"plan_edit_1" for x in at.button)


def test_manual_verify_plan_button(tmp_path):
    at, db_file = _reflection_app(tmp_path, "manual_verify")
    ids = _seed_reflection_db(db_file, plan="pending")
    at.run()
    button = next(
        x for x in at.button
        if x.key == f"plan_manual_verify_{ids['plan']}")
    button.click().run()
    assert not at.exception, [str(e) for e in at.exception]

    engine = create_engine(f"sqlite:///{db_file.as_posix()}")
    with engine.connect() as conn:
        status = conn.execute(text(
            "SELECT status FROM reflection_plans WHERE id = :pid"),
            {"pid": ids["plan"]}).scalar_one()
    engine.dispose()
    assert status == "verified"


def test_delete_plan_button(tmp_path):
    at, db_file = _reflection_app(tmp_path, "delete_plan")
    ids = _seed_reflection_db(db_file, plan="pending")
    at.run()
    next(x for x in at.button
         if x.key == f"plan_delete_{ids['plan']}").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    engine = create_engine(f"sqlite:///{db_file.as_posix()}")
    with engine.connect() as conn:
        count = conn.execute(text(
            "SELECT COUNT(*) FROM reflection_plans")).scalar_one()
        has_plan = conn.execute(text(
            "SELECT has_plan FROM teaching_reflections WHERE id = :rid"),
            {"rid": ids["reflection"]}).scalar_one()
    engine.dispose()
    assert count == 0 and has_plan == 0


def test_import_verify_exam_scores_auto_verifies_plan(tmp_path):
    at, db_file = _reflection_app(tmp_path, "auto_verify")
    ids = _seed_reflection_db(db_file, plan="pending")
    at.run()

    goto_sub(at, "analysis_tab", "成绩管理", "📊 学情")
    import_pick = next(x for x in at.selectbox if x.key == "score_import_exam")
    verify_label = next(label for label in import_pick.options
                        if label.startswith("验证考试"))
    import_pick.set_value(verify_label).run()
    uploader = next(x for x in at.file_uploader if x.key == "score_upload")
    txt = "姓名,数学\n闭环甲,70\n闭环乙,70\n".encode("utf-8")
    uploader.upload("成绩.txt", txt, "text/plain").run()
    assert not at.exception, [str(e) for e in at.exception]
    next(x for x in at.button if x.key == "confirm_scores").click().run()
    assert not at.exception, [str(e) for e in at.exception]

    engine = create_engine(f"sqlite:///{db_file.as_posix()}")
    with engine.connect() as conn:
        status = conn.execute(text(
            "SELECT status FROM reflection_plans WHERE id = :pid"),
            {"pid": ids["plan"]}).scalar_one()
        result = conn.execute(text(
            "SELECT verify_result FROM reflection_plans WHERE id = :pid"),
            {"pid": ids["plan"]}).scalar_one()
    engine.dispose()
    assert status == "verified"
    assert "有效" in result


def test_improvement_history_detail_and_export(tmp_path):
    at, db_file = _reflection_app(tmp_path, "history")
    ids = _seed_reflection_db(db_file, plan="pending", verified=True)
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    assert any(x.key == "improvement_history_pick" for x in at.selectbox)
    next(x for x in at.button
         if x.key == "open_improvement_detail").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    assert any("改进措施" in str(x.value) for x in at.markdown)

    next(x for x in at.button
         if x.key == "export_improvement_report").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    assert any(x.key == "download_improvement_report"
               for x in at.download_button)
