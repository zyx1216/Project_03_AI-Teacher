# -*- coding: utf-8 -*-
"""AI 出题测试：JSON 围栏修复、缺答案拒收、题型/难度归一、SymPy 验算三态。"""

import json

from utils import question_service as qs


def test_strip_code_fence():
    assert qs.strip_code_fence("```json\n[1, 2]\n```") == "[1, 2]"
    assert qs.strip_code_fence("[1, 2]") == "[1, 2]"


def test_parse_plain_array_and_wrapped_object():
    arr = json.dumps([{"content": "1+1=?", "answer": "2"} for _ in range(2)],
                     ensure_ascii=False)
    assert len(qs.parse_generated_questions(arr)) == 2
    wrapped = json.dumps({"questions": [{"content": "q", "answer": "a"}]},
                         ensure_ascii=False)
    assert len(qs.parse_generated_questions(wrapped)) == 1


def test_parse_fenced_json():
    payload = "```json\n" + json.dumps(
        [{"content": "题", "answer": "答"}], ensure_ascii=False) + "\n```"
    assert len(qs.parse_generated_questions(payload)) == 1


def test_parse_bad_text_returns_empty():
    assert qs.parse_generated_questions("模型说了一堆废话没有 JSON") == []


def test_validate_question_rejects_missing_answer():
    assert qs.validate_question({"content": "只有题干"}) is None
    assert qs.validate_question({"answer": "只有答案"}) is None


def test_validate_normalizes_type_and_difficulty():
    q = qs.validate_question(
        {"content": "题干", "answer": "答案", "question_type": "单选题",
         "difficulty": "拓展", "knowledge_points": "韦达定理,判别式"})
    assert q["question_type"] == "choice"
    assert q["difficulty"] == 3
    assert json.loads(q["knowledge_points"]) == ["韦达定理", "判别式"]


def test_validate_difficulty_bounds():
    assert qs.normalize_difficulty(9) == 3
    assert qs.normalize_difficulty(0) == 1
    assert qs.normalize_difficulty("中等") == 2


def test_build_questions_counts_rejected():
    data = [
        {"content": "有答案", "answer": "1"},
        {"content": "缺答案", "answer": ""},
        {"answer": "缺题干"},
    ]
    valid, rejected = qs.build_questions(json.dumps(data, ensure_ascii=False))
    assert len(valid) == 1
    assert rejected == 2


def test_sympy_verify_pass():
    r = qs.verify_with_sympy({"expr": "2*x + 3*x", "expect": "5*x"})
    assert r["status"] == "pass"


def test_sympy_verify_fail():
    r = qs.verify_with_sympy({"expr": "1 + 1", "expect": "3"})
    assert r["status"] == "fail"


def test_sympy_verify_skip_states():
    assert qs.verify_with_sympy(None)["status"] == "skip"
    assert qs.verify_with_sympy({"expr": "这不是算式", "expect": "??"})["status"] == "skip"
    assert qs.verify_with_sympy({"expr": "x"})["status"] == "skip"