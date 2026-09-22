# -*- coding: utf-8 -*-
"""v1.5.2 知识点掌握分析服务层测试。"""
import json

from models.models import (
    Homework, HomeworkAnswer, HomeworkQuestion, Question, Student)
from utils import homework_score_service as hss


def _kps_json(items):
    return json.dumps(items, ensure_ascii=False)


def _make_homework(session):
    hw = Homework(name="测试作业", is_template=False, class_name="一班",
                  subject="数学")
    session.add(hw)
    session.flush()
    return hw


def _add_question(session, hw, qid, kps, full, order):
    q = Question(
        id=qid, content=f"题{qid}", question_type="solution", difficulty=2,
        knowledge_points=_kps_json(kps), answer="ans")
    session.add(q)
    session.add(HomeworkQuestion(
        homework_id=hw.id, question_id=qid, order=order, score=full))
    session.flush()
    return q


def _answer(session, hw, student, qid, earned, correct=True):
    session.add(HomeworkAnswer(
        homework_id=hw.id, student_id=student.id, question_id=qid,
        order_no=qid, earned_score=earned, is_correct=correct))


def _map(rows):
    return {r["knowledge_point"]: r for r in rows}


def test_mastery_level_boundaries():
    f = hss.mastery_level
    assert f(None) == "薄弱"
    assert f(0.90) == "优秀"
    assert f(0.85) == "良好"     # 85% 边界归良好
    assert f(0.70) == "良好"
    assert f(0.60) == "良好"
    assert f(0.50) == "一般"
    assert f(0.40) == "一般"     # 40% 边界归一般
    assert f(0.30) == "薄弱"


def test_knowledge_mastery_aggregation_and_multi_tag(session):
    hw = _make_homework(session)
    # 题1：10分，两个标签 A、B；题2：10分，标签 A
    _add_question(session, hw, 1, ["A", "B"], 10, 1)
    _add_question(session, hw, 2, ["A"], 10, 2)
    s1 = Student(name="甲", class_name="一班")
    s2 = Student(name="乙", class_name="一班")
    session.add_all([s1, s2])
    session.flush()
    # 甲：题1得8分，题2得5分；乙：题1得2分，题2得9分
    _answer(session, hw, s1, 1, 8)
    _answer(session, hw, s1, 2, 5)
    _answer(session, hw, s2, 1, 2, correct=False)
    _answer(session, hw, s2, 2, 9)
    session.commit()

    rows = _map(hss.knowledge_mastery(session, hw.id))
    # A：满=10+10（两人×两题中带A的：题1和题2）=40，得=8+5+2+9=24，率0.6
    assert rows["A"]["full_score"] == 40
    assert rows["A"]["earned_score"] == 24
    assert rows["A"]["rate"] == 0.6
    assert rows["A"]["level"] == "良好"
    assert rows["A"]["participants"] == 2
    assert rows["A"]["judge_count"] == 4
    # B：只有题1，满=20（两人），得=8+2=10，率0.5
    assert rows["B"]["full_score"] == 20
    assert rows["B"]["earned_score"] == 10
    assert rows["B"]["rate"] == 0.5
    assert rows["B"]["level"] == "一般"
    assert rows["B"]["participants"] == 2


def test_unlabeled_question_bucket(session):
    hw = _make_homework(session)
    _add_question(session, hw, 1, [], 10, 1)
    s1 = Student(name="甲", class_name="一班")
    session.add(s1)
    session.flush()
    _answer(session, hw, s1, 1, 3, correct=False)
    session.commit()
    rows = _map(hss.knowledge_mastery(session, hw.id))
    assert hss.UNLABELED_KP in rows
    assert rows[hss.UNLABELED_KP]["rate"] == 0.3
    assert rows[hss.UNLABELED_KP]["level"] == "薄弱"


def test_unjudged_answers_excluded_from_denominator(session):
    hw = _make_homework(session)
    _add_question(session, hw, 1, ["A"], 10, 1)
    s1 = Student(name="甲", class_name="一班")
    s2 = Student(name="乙", class_name="一班")
    session.add_all([s1, s2])
    session.flush()
    # 只判甲（得9分），乙只有 is_correct 无 earned_score
    _answer(session, hw, s1, 1, 9)
    session.add(HomeworkAnswer(
        homework_id=hw.id, student_id=s2.id, question_id=1,
        order_no=1, earned_score=None, is_correct=False))
    session.commit()
    rows = _map(hss.knowledge_mastery(session, hw.id))
    assert rows["A"]["full_score"] == 10
    assert rows["A"]["earned_score"] == 9
    assert rows["A"]["rate"] == 0.9
    assert rows["A"]["participants"] == 1


def test_student_knowledge_mastery(session):
    hw = _make_homework(session)
    _add_question(session, hw, 1, ["A", "B"], 10, 1)
    s1 = Student(name="甲", class_name="一班")
    s2 = Student(name="乙", class_name="一班")
    session.add_all([s1, s2])
    session.flush()
    _answer(session, hw, s1, 1, 3, correct=False)
    _answer(session, hw, s2, 1, 9)
    session.commit()
    rows = _map(hss.student_knowledge_mastery(session, hw.id, s1.id))
    assert rows["A"]["rate"] == 0.3 and rows["A"]["level"] == "薄弱"
    assert rows["B"]["rate"] == 0.3 and rows["B"]["level"] == "薄弱"
    # 学生2不混入
    assert rows["A"]["earned_score"] == 3


def test_weakest_knowledge_order_and_suggestion(session):
    hw = _make_homework(session)
    _add_question(session, hw, 1, ["A"], 10, 1)
    _add_question(session, hw, 2, ["B"], 10, 2)
    _add_question(session, hw, 3, ["C"], 10, 3)
    _add_question(session, hw, 4, ["D"], 10, 4)
    s1 = Student(name="甲", class_name="一班")
    session.add(s1)
    session.flush()
    for qid, earned in [(1, 9), (2, 5), (3, 2), (4, 7)]:
        _answer(session, hw, s1, qid, earned, correct=earned >= 6)
    session.commit()
    weak = hss.weakest_knowledge(session, hw.id, 3)
    assert [w["knowledge_point"] for w in weak] == ["C", "B", "D"]
    assert weak[0]["level"] == "薄弱"
    assert weak[0]["suggestion"]
