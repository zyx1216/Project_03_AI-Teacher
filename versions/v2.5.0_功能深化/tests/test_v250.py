# -*- coding: utf-8 -*-
"""v2.5.0 现有功能深化（方向一）测试。"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models.models import Base
from utils import (question_service as qs, homework_stats as hstat,
                   subjective_grading_service as sgs, homework_score_service as hs,
                   exam_service as es, stats as st, smart_compose_service as scs)
from utils import homework_service as hw_svc, student_service as stu_svc


@pytest.fixture()
def session(tmp_path, monkeypatch):
    eng = create_engine(f"sqlite:///{(tmp_path/'t.db').as_posix()}")
    Base.metadata.create_all(eng)
    mon = monkeypatch
    # 让 DATA_DIR 指向临时目录，避免污染真实 data
    import config
    mon.setattr(config, "DATA_DIR", tmp_path, raising=False)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()
    eng.dispose()


# --- 1.1 组卷模板 ---

def test_template_extended_fields_and_rename(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path, raising=False)
    monkeypatch.setattr(scs, "TEMPLATES_PATH", tmp_path / "tpl.json", raising=False)
    tpl = scs.save_template("方案A", "数学", "初二", 100, 60,
                            [{"type": "选择题", "easy": 1, "medium": 0, "hard": 0}],
                            material_id=3, chapters=["第一章"], knowledge_points=["函数"])
    assert tpl["material_id"] == 3 and tpl["chapters"] == ["第一章"]
    scs.rename_template(tpl["template_id"], "方案B")
    assert scs.load_templates()[0]["name"] == "方案B"


def test_template_backward_compatible(tmp_path, monkeypatch):
    monkeypatch.setattr(scs, "TEMPLATES_PATH", tmp_path / "tpl.json", raising=False)
    (tmp_path / "tpl.json").write_text(json.dumps([{
        "template_id": "x", "name": "旧方案", "subject": "数学", "grade": "初二",
        "total_score": 100, "duration": 60,
        "rows": [{"type": "选择题", "easy": 1, "medium": 0, "hard": 0}]}]),
        encoding="utf-8")
    items = scs.load_templates()
    assert items[0].get("material_id") is None  # 缺键不报错


# --- 1.2 预估平均分 / 分布 ---

def test_predict_average_score():
    r = hstat.predict_average_score([(1, 50), (3, 50)])
    assert r["full"] == 100.0
    assert r["predicted"] == pytest.approx(65.0)
    assert hstat.predict_average_score([])["predicted"] is None


def test_distributions():
    assert hstat.difficulty_distribution([1, 1, 3]) == {"易": 2, "中": 0, "难": 1}
    assert hstat.type_distribution(["选择题", "选择题", "解答题"]) == {
        "选择题": 2, "解答题": 1}


# --- 1.3 知识点覆盖 ---

def test_kp_coverage_and_rows():
    q_kps = [(1, ["函数"]), (2, ["几何"])]
    scores = {1: 10.0, 2: 10.0}
    report = hstat.knowledge_coverage(q_kps, ["函数", "代数"])
    assert report["covered"] == ["函数"] and report["missing"] == ["代数"]
    rows = hstat.kp_coverage_rows(q_kps, ["函数", "代数"], scores)
    by = {r["知识点"]: r for r in rows}
    assert by["函数"]["已覆盖"] is True and by["代数"]["已覆盖"] is False


# --- 2.1 评语模板 ---

def test_comment_templates_crud(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path, raising=False)
    items = sgs.load_comment_templates()
    assert len([i for i in items if i.get("builtin")]) == 4
    sgs.save_comment_template("我的模板", "继续保持")
    assert any(i["name"] == "我的模板" for i in sgs.load_comment_templates())
    with pytest.raises(ValueError):
        sgs.delete_comment_template("builtin_excellent")


def test_comment_templates_corrupt_fallback(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path, raising=False)
    (tmp_path / "grading_comment_templates.json").write_text("{bad", encoding="utf-8")
    items = sgs.load_comment_templates()
    assert len([i for i in items if i.get("builtin")]) == 4
    # 原文件未被覆盖
    assert (tmp_path / "grading_comment_templates.json").read_text(encoding="utf-8") == "{bad"


# --- 2.2 批改历史 ---

def test_student_knowledge_history(session):
    from models.models import Question, HomeworkQuestion, HomeworkAnswer, Homework
    hw = hw_svc.create_homework(session, "作业1", subject="数学")
    q = qs.create_question(session, {
        "content": "题", "question_type": "solution", "difficulty": 2,
        "knowledge_points": '["函数"]', "answer": "a", "analysis": ""},
        source="manual", status="approved", subject="数学")
    hw_svc.add_questions(session, hw.id, [q.id], default_score=10.0)
    stu, _ = stu_svc.get_or_create_student(session, "甲", "一班")
    session.commit()
    hs.save_answers(session, hw.id, [{"student_id": stu.id, "question_id": q.id,
                                      "order_no": 1, "earned_score": 6.0}])
    session.commit()
    hist = hs.student_knowledge_history(session, stu.id, subject="数学")
    assert "函数" in hist["series"]
    assert hist["series"]["函数"][0]["rate"] == pytest.approx(0.6)


# --- 2.3 批改进度 ---

def test_grading_progress():
    assert hstat.grading_progress(10, 5)["ungraded"] == 5
    assert hstat.grading_progress(10, 5, elapsed_seconds=100)["remaining_seconds"] == 100
    assert hstat.grading_progress(10, 5)["remaining_seconds"] is None


# --- 3.1 多考试对比 ---

def test_compare_exams(session):
    from datetime import date
    e1 = es.create_exam(session, "月考1", exam_date=date(2026, 3, 1),
                        full_scores={"数学": 100})
    es.import_scores(session, e1.id, [{"name": "甲", "class_name": "一班",
                                       "scores": {"数学": 60}}])
    e2 = es.create_exam(session, "月考2", exam_date=date(2026, 4, 1),
                        full_scores={"数学": 100})
    es.import_scores(session, e2.id, [{"name": "甲", "class_name": "一班",
                                       "scores": {"数学": 80}}])
    session.commit()
    data = es.compare_exams(session, [e1.id, e2.id])
    assert len(data["exams"]) == 2
    assert data["exams"][0]["mean"] == pytest.approx(60)


# --- 3.2 班级进步追踪 ---

def test_class_progress_tracking(session):
    from datetime import date
    for i, scores in enumerate([[90, 60], [60, 90]], start=1):
        e = es.create_exam(session, f"考{i}", exam_date=date(2026, i, 1),
                           full_scores={"数学": 100})
        es.import_scores(session, e.id, [
            {"name": "甲", "class_name": "一班", "scores": {"数学": scores[0]}},
            {"name": "乙", "class_name": "一班", "scores": {"数学": scores[1]}}])
    session.commit()
    data = es.class_progress_tracking(session, class_name="一班", subject="数学")
    assert data["need"] == 0
    assert data["improve_top"][0]["name"] == "乙"  # 60→90 名次前进


# --- 3.3 教学效果 ---

def test_teaching_effect_summary():
    assert st.knowledge_effect_series([0.4, 0.7])["effect"] == "有效"
    assert st.knowledge_effect_series([0.7, 0.4])["effect"] == "效果不明显"
    assert st.knowledge_effect_series([0.5])["effect"] == "数据不足"
    assert st.repeat_wrong_rate([0, 2, 1]) == pytest.approx(1 / 3, rel=1e-3)
    summary = st.summarize_teaching_effect({
        "函数": [{"rate": 0.4, "wrong": 1}, {"rate": 0.7, "wrong": 0}]})
    assert "函数" in summary["good"]


# --- 4.1 标签 ---

def test_custom_tags_and_summary(session):
    q = qs.create_question(session, {
        "content": "题", "question_type": "choice", "difficulty": 1,
        "knowledge_points": '["函数"]', "answer": "A", "analysis": ""},
        source="manual", status="approved", subject="数学")
    session.commit()
    qs.update_custom_tags(session, q.id, ["易错", "易错", "重点"])
    session.commit()
    assert qs.custom_tags_list(session.get(type(q), q.id)) == ["易错", "重点"]
    summary = qs.question_tag_summary(session, "数学")
    assert summary["自定义"].get("易错") == 1
    assert "函数" in summary["知识点"]


# --- 4.2 难度标定 ---

def test_recalibrate_difficulty(session):
    from models.models import Question
    hw = hw_svc.create_homework(session, "作业", subject="数学")
    q = qs.create_question(session, {
        "content": "题", "question_type": "solution", "difficulty": 3,
        "knowledge_points": "[]", "answer": "a", "analysis": ""},
        source="manual", status="approved", subject="数学")
    hw_svc.add_questions(session, hw.id, [q.id], default_score=10.0)
    stu, _ = stu_svc.get_or_create_student(session, "甲", "一班")
    session.commit()
    # 得分率 0.1 → 系数 0.9 → 难(3)；用户设定难度保持 3 不变
    hs.save_answers(session, hw.id, [{"student_id": stu.id, "question_id": q.id,
                                      "order_no": 1, "earned_score": 1.0}])
    session.commit()
    res = qs.recalibrate_difficulty(session, question_ids=[q.id])
    session.commit()
    assert res["updated"] == 1
    assert session.get(Question, q.id).ai_difficulty == 3


# --- 4.3 知识点自动标注 ---

def test_suggest_knowledge_points_fallback(session):
    q = qs.create_question(session, {
        "content": "函数题", "question_type": "solution", "difficulty": 2,
        "knowledge_points": '["函数"]', "answer": "a", "analysis": ""},
        source="manual", status="approved", subject="数学")
    session.commit()
    out = qs.suggest_knowledge_points(q, chat_func=None)
    assert out["confidence"] == "low"
    assert out["knowledge_points"] == ["函数"]


def test_suggest_knowledge_points_with_chat(session):
    q = qs.create_question(session, {
        "content": "函数题", "question_type": "solution", "difficulty": 2,
        "knowledge_points": "[]", "answer": "a", "analysis": ""},
        source="manual", status="approved", subject="数学")
    session.commit()

    def fake_chat(system, user):
        return json.dumps({"knowledge_points": ["函数", "单调性"],
                           "confidence": "high"})
    out = qs.suggest_knowledge_points(q, chat_func=fake_chat)
    assert out["knowledge_points"] == ["函数", "单调性"]
    assert out["confidence"] == "high"


def test_batch_auto_tag(session):
    q = qs.create_question(session, {
        "content": "题", "question_type": "choice", "difficulty": 1,
        "knowledge_points": "[]", "answer": "A", "analysis": ""},
        source="manual", status="approved", subject="数学")
    session.commit()
    res = qs.batch_auto_tag_knowledge_points(
        session, [q.id], chat_func=lambda s, u: '{"knowledge_points":["集合"],"confidence":"high"}')
    session.commit()
    assert qs.knowledge_points_list(session.get(type(q), q.id)) == ["集合"]
    assert res["low_confidence"] == []


def test_extract_knowledge_points_from_text():
    out = qs.extract_knowledge_points_from_text("本节讲函数的定义与函数的性质，以及勾股定理。")
    assert "函数" in out and "勾股" in out
