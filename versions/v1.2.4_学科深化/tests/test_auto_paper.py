# -*- coding: utf-8 -*-
"""自动组卷测试：规则抽题满足配比、题库不足时 AI 补题、知识点覆盖。AI 全部 mock。"""

import json

from utils import homework_service as hw
from utils import question_service as qs


def _q(session, qtype, diff, kps=None):
    data = qs.validate_question({
        "content": f"{qtype}{diff}{kps}", "question_type": qtype,
        "difficulty": diff, "answer": "A",
        "knowledge_points": kps or "方程"})
    return qs.create_question(session, data, source="manual", status="approved")


def test_auto_compose_all_from_bank(session, monkeypatch):
    """题库充足时全部规则抽题，不调 AI。"""
    # 4 道选择（按 50/50 基础拓展：2 基础 2 拓展）+ 2 道中等解答
    for i in range(2):
        _q(session, "choice", 1)
    for i in range(2):
        _q(session, "choice", 3)
    for i in range(2):
        _q(session, "solution", 2)

    called = {"n": 0}

    def _boom(*a, **k):
        called["n"] += 1
        raise AssertionError("题库充足不应调 AI")

    monkeypatch.setattr(
        "utils.homework_service._ai_generate_for_shortage", _boom)

    h = hw.create_homework(session, "试卷", homework_type="exam")
    spec = {"counts": {"choice": 4, "solution": 2},
            "difficulty_ratio": {1: 50, 2: 0, 3: 50}}
    result = hw.auto_compose(session, h.id, spec, ["方程"])
    assert result["rule_picked"] == 6
    assert result["ai_generated"] == 0
    assert result["shortage_count"] == 0

    pairs = hw.homework_questions(session, h.id)
    types = [q.question_type for _l, q in pairs]
    assert types.count("choice") == 4 and types.count("solution") == 2


def test_auto_compose_ai_fills_shortage(session, monkeypatch):
    """题库只有 1 道选择，却要 3 道：缺口 2 道由 AI 补。"""
    bank_q = _q(session, "choice", 2)

    def _fake_ai(session, shortage, kps, subject=None):
        # 按缺口造 2 道选择基础题
        made = []
        for slot in shortage:
            data = qs.validate_question({
                "content": "AI补题", "question_type": slot["question_type"],
                "difficulty": slot["difficulty"], "answer": "B",
                "knowledge_points": "判别式"})
            made.append(qs.create_question(session, data, source="ai_generated",
                                           status="pending"))
        return made

    monkeypatch.setattr(hw, "_ai_generate_for_shortage", _fake_ai)

    h = hw.create_homework(session, "试卷2", homework_type="exam")
    spec = {"counts": {"choice": 3},
            "difficulty_ratio": {1: 100, 2: 0, 3: 0}}
    result = hw.auto_compose(session, h.id, spec, ["方程", "判别式"])
    assert result["rule_picked"] == 1
    assert result["ai_generated"] == 2
    assert result["shortage_count"] == 0
    assert len(hw.homework_questions(session, h.id)) == 3
    # 知识点覆盖：题库题“方程” + AI 题“判别式”
    assert result["coverage"]["missing"] == []


def test_auto_compose_ai_failure_keeps_rule_picks(session, monkeypatch):
    """AI 补题抛错时不影响规则抽到的题，缺口如实上报。"""
    _q(session, "choice", 2)

    def _fail(session, shortage, kps, subject=None):
        raise RuntimeError("网络不通")

    monkeypatch.setattr(hw, "_ai_generate_for_shortage", _fail)

    h = hw.create_homework(session, "试卷3", homework_type="exam")
    spec = {"counts": {"choice": 3, "solution": 2},
            "difficulty_ratio": {1: 0, 2: 100, 3: 0}}
    result = hw.auto_compose(session, h.id, spec, [])
    assert result["rule_picked"] == 1
    assert result["shortage_count"] == 4
    assert len(hw.homework_questions(session, h.id)) == 1


def test_auto_compose_reports_missing_knowledge(session):
    """要求覆盖的知识点没考到，要在 coverage.missing 里报出来。"""
    _q(session, "choice", 1, kps="方程")
    h = hw.create_homework(session, "试卷4", homework_type="exam")
    spec = {"counts": {"choice": 1},
            "difficulty_ratio": {1: 100, 2: 0, 3: 0}}
    result = hw.auto_compose(session, h.id, spec, ["方程", "韦达定理"])
    assert "韦达定理" in result["coverage"]["missing"]
    assert "方程" in result["covered"] if "covered" in result else True
    assert "方程" in result["coverage"]["covered"]