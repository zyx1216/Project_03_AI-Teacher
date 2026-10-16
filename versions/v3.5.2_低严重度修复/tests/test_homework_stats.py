# -*- coding: utf-8 -*-
"""作业纯逻辑测试：抽题算法、每题正确率、高频错题、覆盖检查、进退步、提交率。"""

from types import SimpleNamespace as NS

from utils import homework_stats as hs


def _q(qid, qtype="choice", diff=2):
    return NS(id=qid, question_type=qtype, difficulty=diff)


# ---- 提交率与总分概览 ----

def test_submission_rate():
    assert hs.submission_rate(8, 10) == 0.8
    assert hs.submission_rate(10, 10) == 1.0
    assert hs.submission_rate(3, 0) is None


def test_overall_scores_excludes_absent():
    rows = [{"name": "甲", "score": 90}, {"name": "乙", "score": 80},
            {"name": "丙", "score": None}]
    out = hs.overall_scores(rows)
    assert out["total"] == 3 and out["submitted"] == 2
    assert out["mean"] == 85 and out["max"] == 90 and out["min"] == 80
    assert out["submission_rate"] == round(2 / 3, 4)


# ---- 每题正确率 / 典型错题 ----

def test_question_correct_rate():
    answers = [
        {"question_id": 1, "order_no": 1, "is_correct": True, "earned_score": 10, "full_score": 10},
        {"question_id": 1, "order_no": 1, "is_correct": True, "earned_score": 10, "full_score": 10},
        {"question_id": 1, "order_no": 1, "is_correct": False, "earned_score": 4, "full_score": 10},
    ]
    out = hs.question_correct_rate(answers)
    assert len(out) == 1
    assert out[0]["judged"] == 3 and out[0]["correct"] == 2 and out[0]["wrong"] == 1
    assert out[0]["rate"] == round(2 / 3, 4)
    assert out[0]["avg_rate"] == round(24 / 3 / 10, 4)
    assert out[0]["typical"] is False  # 错误率 1/3 < 0.4


def test_typical_question_threshold():
    answers = [{"question_id": 9, "order_no": 1, "is_correct": c,
                "earned_score": None, "full_score": 10}
               for c in [True, True, False, False, False]]  # 3/5 错 = 0.6
    out = hs.question_correct_rate(answers)
    assert out[0]["typical"] is True


def test_top_wrong_orders_by_wrong_count():
    per_question = [
        {"question_id": 1, "order_no": 1, "judged": 10, "correct": 9, "wrong": 1,
         "rate": 0.9, "typical": False},
        {"question_id": 2, "order_no": 2, "judged": 10, "correct": 5, "wrong": 5,
         "rate": 0.5, "typical": True},
        {"question_id": 3, "order_no": 3, "judged": 10, "correct": 10, "wrong": 0,
         "rate": 1.0, "typical": False},
    ]
    top = hs.top_wrong_questions(per_question, top_k=2)
    assert [q["question_id"] for q in top] == [2, 1]


# ---- 进退步 ----

def test_homework_deltas_only_both_scored():
    cur = [{"student_id": 1, "score": 90}, {"student_id": 2, "score": 70},
           {"student_id": 3, "score": 60}]
    prev = [{"student_id": 1, "score": 85}, {"student_id": 2, "score": 75}]
    d = hs.homework_deltas(cur, prev)
    assert d == {1: 5, 2: -5}  # 3 上次缺，不计


# ---- 知识点覆盖 ----

def test_knowledge_coverage():
    qkps = [(1, ["方程", "判别式"]), (2, ["韦达定理"])]
    out = hs.knowledge_coverage(qkps, ["方程", "判别式", "二次函数"])
    assert out["covered"] == ["判别式", "方程"]
    assert out["missing"] == ["二次函数"]


# ---- 组卷槽位 ----

def test_plan_paper_slots_counts_and_ratio():
    spec = {"counts": {"choice": 4, "solution": 2},
            "difficulty_ratio": {1: 30, 2: 50, 3: 20}}
    slots = hs.plan_paper_slots(spec)
    assert len(slots) == 6
    choice_slots = [s for s in slots if s["question_type"] == "choice"]
    assert len(choice_slots) == 4
    # 4 道选择按 30/50/20：1 基础 + 2 中等（先整除）+ 余数 1 补给占比最大的中等 = 3
    by_diff = {d: 0 for d in (1, 2, 3)}
    for s in choice_slots:
        by_diff[s["difficulty"]] += 1
    assert by_diff == {1: 1, 2: 3, 3: 0}


# ---- 确定性抽题 ----

def test_deterministic_pick_exact():
    pool = [_q(1, "choice", 1), _q(2, "choice", 2), _q(3, "choice", 2)]
    slots = [{"question_type": "choice", "difficulty": 1},
             {"question_type": "choice", "difficulty": 2}]
    out = hs.deterministic_pick(pool, slots)
    assert [q.id for q in out["picked"]] == [1, 2]
    assert out["shortage"] == []


def test_deterministic_pick_no_repeat():
    """只有 1 道符合的题，却要 2 个槽位：第二槽不能重复抽同一题。"""
    pool = [_q(1, "choice", 2)]
    slots = [{"question_type": "choice", "difficulty": 2},
             {"question_type": "choice", "difficulty": 2}]
    out = hs.deterministic_pick(pool, slots)
    assert len(out["picked"]) == 1
    assert len(out["shortage"]) == 1


def test_deterministic_pick_neighbor_difficulty_fallback():
    """要拓展题但库里只有基础题：同题型相邻难度兜底，不算缺口。"""
    pool = [_q(1, "solution", 1)]
    slots = [{"question_type": "solution", "difficulty": 3}]
    out = hs.deterministic_pick(pool, slots)
    assert [q.id for q in out["picked"]] == [1]
    assert out["shortage"] == []


def test_deterministic_pick_shortage_when_type_missing():
    pool = [_q(1, "choice", 2)]
    slots = [{"question_type": "solution", "difficulty": 2}]
    out = hs.deterministic_pick(pool, slots)
    assert out["picked"] == []
    assert len(out["shortage"]) == 1


def test_deterministic_pick_respects_exclude():
    pool = [_q(1, "choice", 2), _q(2, "choice", 2)]
    slots = [{"question_type": "choice", "difficulty": 2}]
    out = hs.deterministic_pick(pool, slots, exclude_ids={1})
    assert [q.id for q in out["picked"]] == [2]