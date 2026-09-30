# -*- coding: utf-8 -*-
"""v2.5.1 辅导资料与题目自动入库 + 难度判定优化 + LLM 模型适配 测试。"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models.models import Base, Question, Textbook
from utils import (question_service as qs, question_extract_service as qes,
                   material_type_service as mts, model_registry as mr,
                   material_service, homework_service as hw_svc,
                   student_service as stu_svc, homework_score_service as hs)


@pytest.fixture()
def session(tmp_path, monkeypatch):
    eng = create_engine(f"sqlite:///{(tmp_path/'t.db').as_posix()}")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()
    eng.dispose()


# --- 第一部分：资料类型 ---

def test_material_type_helpers():
    assert mts.normalize_type("workbook") == "workbook"
    assert mts.normalize_type("bad") == "textbook"
    assert mts.type_icon(None) == "📖"
    assert "练习册" in mts.type_label("workbook")


def test_textbook_type_and_filter(session):
    session.add(Textbook(name="课本A", file_type="pdf", subject="数学",
                         type="textbook"))
    session.add(Textbook(name="练习册B", file_type="pdf", subject="数学",
                         type="workbook"))
    session.add(Textbook(name="老资料", file_type="pdf", subject="数学"))  # type NULL
    session.commit()
    books = material_service.list_materials(session, subject="数学",
                                            material_type="workbook")
    assert [b.name for b in books] == ["练习册B"]
    textbooks = material_service.list_materials(session, subject="数学",
                                                material_type="textbook")
    names = {b.name for b in textbooks}
    assert "课本A" in names and "老资料" in names  # NULL 兼容为课本


# --- 第二部分：题目提取 ---

def test_parse_question_structure():
    parsed = qes.parse_question_structure(
        "1. 求 x+1=2\nA.1 B.2\n答案：1\n解析：移项得 x=1")
    assert parsed["answer"] == "1"
    assert parsed["question_type"] == "choice"
    assert "移项" in parsed["analysis"]


def test_extract_questions_from_material(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path, raising=False)
    (tmp_path / "text").mkdir(parents=True, exist_ok=True)
    (tmp_path / "text" / "7.txt").write_text(
        "1. 第1题：求 1+1\n答案：2\n2. 第2题：求 2+2\n答案：4", encoding="utf-8")
    rows = qes.extract_questions_from_material(7, chat_func=None)
    assert len(rows) >= 2
    assert all("content" in r for r in rows)


def test_extract_material_missing_file(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path, raising=False)
    assert qes.extract_questions_from_material(999, chat_func=None) == []


def test_extract_uses_ai_when_available(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path, raising=False)
    (tmp_path / "text").mkdir(parents=True, exist_ok=True)
    (tmp_path / "text" / "8.txt").write_text("1. 原始题干", encoding="utf-8")

    def fake(sysp, user):
        return json.dumps({"content": "AI整理题干", "question_type": "fill",
                           "answer": "42", "analysis": "", "knowledge_points": ["函数"]})
    rows = qes.extract_questions_from_material(8, chat_func=fake)
    assert rows and rows[0]["content"] == "AI整理题干"


# --- 第三部分：难度判定（不用得分率） ---

def test_estimate_difficulty_weights_and_evidence():
    easy = qes.estimate_difficulty({"content": "简单", "knowledge_points": ["x"]},
                                   chat_func=None)
    assert easy["difficulty"] == "易"
    assert set(easy["evidence"]) >= {"knowledge_complexity", "step_count",
                                     "error_prone_points", "ai_estimate"}
    hard = qes.estimate_difficulty(
        {"content": "综合" * 30, "knowledge_points": ["a", "b", "c", "d"],
         "error_points": "1,2,3,4"}, chat_func=None)
    assert hard["difficulty"] == "难"
    # 权重合计为 1
    assert abs(sum(qes.DIFFICULTY_WEIGHTS.values()) - 1.0) < 1e-9


def test_estimate_difficulty_with_ai():
    def fake(sysp, user):
        return json.dumps({"difficulty": "难", "knowledge_complexity": "创新应用",
                           "step_count": 5, "error_prone_points": 3})
    out = qes.estimate_difficulty({"content": "x", "knowledge_points": []},
                                  chat_func=fake)
    assert out["difficulty"] == "难"
    assert out["evidence"]["ai_estimate"] == "难"


# --- 双轨难度字段 ---

def test_dual_difficulty_columns(session):
    q = qs.create_question(session, {
        "content": "题", "question_type": "solution", "difficulty": 2,
        "knowledge_points": "[]", "answer": "a", "analysis": ""},
        source="manual", status="approved", subject="数学")
    session.commit()
    q.ai_difficulty = "易"
    q.calibrated_difficulty = 3
    session.commit()
    row = session.get(Question, q.id)
    assert row.ai_difficulty == "易" and row.calibrated_difficulty == 3


# --- 第四部分：来源 ---

def test_question_sources_and_labels():
    assert set(qs.QUESTION_SOURCES) == {"ai", "manual", "material", "grading"}
    assert "资料提取" in qs.QUESTION_SOURCE_LABELS["material"]
    assert "批改入库" in qs.QUESTION_SOURCE_LABELS["grading"]


def test_source_in_filter(session):
    for src in ("ai_generated", "material", "grading"):
        qs.create_question(session, {
            "content": f"题{src}", "question_type": "choice", "difficulty": 1,
            "knowledge_points": "[]", "answer": "A", "analysis": ""},
            source=src, status="approved", subject="数学")
    session.commit()
    rows = qs.list_questions(session, subject="数学",
                             source_in=["material", "grading"])
    assert {q.source for q in rows} == {"material", "grading"}


# --- 第五部分：模型注册表 ---

def test_model_registry():
    ids = mr.model_options()
    assert "deepseek-chat" in ids and "custom" in ids
    assert mr.is_deprecated("Doubao-Seed-2.0-lite") is True
    assert mr.suggest_for("Doubao-Seed-2.0-lite") == "Doubao-Seed-2.1-lite"
    assert set(mr.PRESETS) == {"均衡模式", "高质量模式", "低成本模式"}
    assert mr.find_model("deepseek-chat")["status"] == "stable"


def test_default_model_unchanged():
    """按决策：不改 config.py 默认模型/地址。"""
    import config
    assert config.DEFAULT_MODEL == "deepseek-chat"
    assert "deepseek" in config.DEFAULT_API_BASE


# --- 批改后入库（服务层） ---

def test_intake_marks_source_and_difficulty(tmp_path, monkeypatch):
    import modules.homework as hw

    eng = create_engine(f"sqlite:///{(tmp_path/'intake.db').as_posix()}")
    Base.metadata.create_all(eng)
    SL = sessionmaker(bind=eng)
    monkeypatch.setattr(hw, "SessionLocal", SL, raising=False)

    s = SL()
    hw_id = hw_svc.create_homework(s, "批改作业", subject="数学").id
    q = qs.create_question(s, {
        "content": "批改题", "question_type": "solution", "difficulty": 2,
        "knowledge_points": "[]", "answer": "a", "analysis": ""},
        source="imported", status="pending", subject="数学")
    qid = q.id
    hw_svc.add_questions(s, hw_id, [qid], default_score=10.0)
    s.commit()
    s.close()

    class _FakeHW:
        id = hw_id
        name = "批改作业"
    n = hw._intake_questions(_FakeHW(), [qid])
    assert n == 1

    s2 = SL()
    row = s2.get(Question, qid)
    assert row.source == "grading"
    assert row.source_id == hw_id
    assert row.status == "approved"
    assert row.ai_difficulty in ("易", "中", "难")
    assert row.difficulty_evidence
    s2.close()
    eng.dispose()
