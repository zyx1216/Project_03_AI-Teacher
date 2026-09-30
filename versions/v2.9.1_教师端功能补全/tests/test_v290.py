# -*- coding: utf-8 -*-
"""v2.9.0 教师端功能补全（第一批）测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from models.models import (
    Base, Exam, Homework, HomeworkAnswer, HomeworkQuestion, HomeworkScore,
    Question, ReviewRecord, Score, Student,
)


@pytest.fixture()
def session(tmp_path):
    eng = create_engine(f"sqlite:///{(tmp_path / 'v290.db').as_posix()}")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()
    eng.dispose()


def _question(session, qtype="choice", difficulty=1, kp="方程", content="题干"):
    q = Question(content=content, question_type=qtype, difficulty=difficulty,
                 knowledge_points=json.dumps([kp], ensure_ascii=False),
                 answer="A", analysis="解析", error_points="易错", subject="数学",
                 status="approved", source="manual")
    session.add(q)
    session.flush()
    return q


def _homework_with_grading(session, *, score=5, correct=False):
    hw = Homework(name="讲评测试", homework_type="after_class",
                  class_name="一班", subject="数学", status="completed")
    session.add(hw)
    session.flush()
    q = _question(session, content="1+1=?", difficulty=1, kp="加法")
    session.add(HomeworkQuestion(homework_id=hw.id, question_id=q.id,
                                 order=1, score=10))
    stu = Student(name="张三", class_name="一班")
    session.add(stu)
    session.flush()
    session.add(HomeworkScore(homework_id=hw.id, student_id=stu.id,
                              total_score=score, submitted=True))
    session.add(HomeworkAnswer(homework_id=hw.id, student_id=stu.id,
                               question_id=q.id, order_no=1,
                               earned_score=score, is_correct=correct))
    session.commit()
    return hw, q, stu


# --- 数据结构与迁移 ---

def test_v290_tables_and_columns():
    assert len(Base.metadata.tables) == 29
    assert "review_records" in Base.metadata.tables
    cols = {c.name for c in ReviewRecord.__table__.columns}
    assert cols == {"id", "homework_id", "ppt_path", "script_path", "created_at"}
    assert "level" in Homework.__table__.columns


def test_v290_migration_idempotent():
    from migrations.v2_9_0_migration import migrate
    eng = create_engine("sqlite:///:memory:")
    r1 = migrate(eng)
    r2 = migrate(eng)
    assert r1["tables"] == ["review_records"]
    assert r2["tables"] == ["review_records"]
    assert r2["added_columns"] == []
    assert "review_records" in inspect(eng).get_table_names()
    eng.dispose()


# --- 变式题 ---

def test_variation_five_types_and_save(session, monkeypatch):
    from utils import llm_client, question_service as qs, variation_service as vs
    parent = _question(session, kp="原知识点", content="原题")
    raw = [
        {"content": f"{name}题干", "answer": "A", "variant_type": key,
         "knowledge_point": "原知识点", "question_type": "choice"}
        for key, name in vs.VARIATION_TYPE_LABELS.items()
    ]
    monkeypatch.setattr(llm_client, "chat_content",
                        lambda *a, **k: json.dumps(raw, ensure_ascii=False))
    variants = vs.generate_variations(session, parent.id, [
        "换数字", "换情境", "换问法", "逆向思维", "拓展提升"], 5, "keep")
    # 模型返回 5 类，服务保留原知识点且总数受控。
    assert len(variants) == 5
    assert {v["variant_type"] for v in variants} == set(vs.VARIATION_TYPE_LABELS)
    assert all(json.loads(v["knowledge_points"])[0] == "原知识点" for v in variants)
    ids = vs.save_variations(session, variants, parent.id)
    session.commit()
    assert len(ids) == 5
    saved = [session.get(Question, qid) for qid in ids]
    assert all(q.source == "variation" and q.parent_question_id == parent.id for q in saved)


def test_variation_count_validation(session):
    from utils import variation_service as vs
    parent = _question(session)
    with pytest.raises(ValueError):
        vs.generate_variations(session, parent.id, ["换数字"], 2, "keep")
    with pytest.raises(ValueError):
        vs.generate_variations(session, parent.id, ["换数字"], 11, "keep")


def test_variant_relation_filter(session):
    from utils import question_service as qs
    parent = _question(session, content="父题")
    child = _question(session, content="变式题")
    child.parent_question_id = parent.id
    child.source = "variation"
    session.commit()
    assert qs.count_questions(session, subject="数学", variant_relation="origin") == 1
    assert qs.count_questions(session, subject="数学", variant_relation="variant") == 1


# --- 讲评辅助 ---

def test_review_analysis_ppt_word_and_records(session, tmp_path, monkeypatch):
    from utils import review_service as rs
    hw, _q, _stu = _homework_with_grading(session, score=5, correct=False)
    ready = rs.is_review_ready(session, hw.id)
    assert ready["ready"] is True
    data = rs.analyze_for_review(session, hw.id)
    assert data["overall"]["mean"] == 5.0
    assert data["per_question"][0]["avg_rate"] == 0.5
    assert data["high_freq_wrong"][0]["question_id"] == data["per_question"][0]["question_id"]
    assert data["knowledge_groups"]["加法"]
    ppt = rs.generate_review_ppt(session, hw.id)
    word = rs.generate_review_script(session, hw.id)
    assert ppt[:2] == b"PK" and len(ppt) > 1000
    assert word[:2] == b"PK" and len(word) > 1000
    monkeypatch.setattr(rs.config, "EXPORT_DIR", tmp_path / "exports", raising=False)
    result = rs.build_review_files(session, hw.id)
    session.commit()
    assert Path(result["ppt_path"]).exists()
    assert Path(result["script_path"]).exists()
    assert len(rs.list_review_records(session, hw.id)) == 1


def test_review_not_ready_without_answers(session):
    hw = Homework(name="空作业", class_name="一班", subject="数学")
    session.add(hw)
    session.flush()
    q = _question(session)
    session.add(HomeworkQuestion(homework_id=hw.id, question_id=q.id,
                                 order=1, score=10))
    session.commit()
    from utils import review_service as rs
    assert rs.is_review_ready(session, hw.id)["ready"] is False


# --- 分层作业 ---

def _seed_tier_data(session, n=10):
    exam = Exam(name="分层考试", grade="高一", term="2026春")
    session.add(exam)
    session.flush()
    students = []
    for i in range(n):
        stu = Student(name=f"学生{i}", class_name="一班")
        session.add(stu)
        session.flush()
        students.append(stu)
        session.add(Score(exam_id=exam.id, student_id=stu.id,
                          subject="数学", score=60 + i * 3))
    for qtype in ("choice", "fill", "solution"):
        for diff in (1, 2, 3):
            for j in range(4):
                _question(session, qtype=qtype, difficulty=diff,
                          kp=f"知识点{diff}", content=f"{qtype}-{diff}-{j}")
    session.commit()
    return exam, students


def test_tier_assignment_ratios_and_generation(session, monkeypatch):
    from utils import tiered_homework_service as ts
    exam, students = _seed_tier_data(session, 10)
    tiers = ts.build_tier_assignment([
        {"student_id": s.id, "name": s.name, "class_name": s.class_name,
         "total": 60 + i * 3} for i, s in enumerate(students)])
    assert len(tiers["A"]) == 3
    assert len(tiers["B"]) == 4
    assert len(tiers["C"]) == 3
    assert ts.build_tier_spec("A", 5)["difficulty_ratio"] == {1: 70, 2: 30, 3: 0}
    assignments = {tier: [r["student_id"] for r in members]
                   for tier, members in tiers.items()}
    result = ts.generate_tiered_homework(
        session, "一班", "数学", exam_id=exam.id,
        questions_per_layer=3, tier_assignments=assignments)
    assert set(result["homework_ids"]) == {"A", "B", "C"}
    for tier, hid in result["homework_ids"].items():
        hw = session.get(Homework, hid)
        assert hw.level == tier and hw.status == "draft"
        assert len(hw.questions) == 3
    deployed = ts.deploy_tiered_homework(
        session, list(result["homework_ids"].values()), ["A", "C"])
    session.commit()
    assert deployed == 2
    assert session.get(Homework, result["homework_ids"]["A"]).status == "pending"
    assert session.get(Homework, result["homework_ids"]["B"]).status == "draft"


def test_tier_effect_report(session):
    from utils import tiered_homework_service as ts
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    hw = Homework(name="A层", level="A", class_name="一班", subject="数学")
    s.add(hw)
    s.flush()
    stu = Student(name="学生A", class_name="一班")
    s.add(stu)
    s.flush()
    s.add(HomeworkScore(homework_id=hw.id, student_id=stu.id,
                        total_score=80, submitted=True))
    s.commit()
    report = ts.tier_effect_report(s, [hw.id])
    assert report[0]["level"] == "A"
    assert report[0]["average"] == 80
    assert report[0]["submitted"] == 1
    s.close()
    eng.dispose()


# --- AppTest 空态与入口 ---

def test_app_tiered_empty_state(tmp_path):
    from tests.test_app_smoke import _isolated_app_code, goto_sub
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_string(
        _isolated_app_code(tmp_path / "tier_empty.db", tmp_path / "feature.json"),
        default_timeout=30)
    at.run()
    goto_sub(at, "homework_tab", "📚 分层作业", "📝 学业测评")
    assert not at.exception, [str(e) for e in at.exception]
    assert any("还没有班级" in str(x.value) for x in at.info)


def test_app_tiered_with_data(tmp_path):
    from tests.test_app_smoke import _isolated_app_code, goto_sub
    from streamlit.testing.v1 import AppTest
    db_file = tmp_path / "tier_data.db"
    eng = create_engine(f"sqlite:///{db_file.as_posix()}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    _seed_tier_data(s, 6)
    s.close()
    eng.dispose()
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / "feature.json"),
        default_timeout=30)
    at.run()
    goto_sub(at, "homework_tab", "📚 分层作业", "📝 学业测评")
    assert not at.exception, [str(e) for e in at.exception]
    assert any(x.key == "tiered_assignment_editor" for x in at.dataframe)
