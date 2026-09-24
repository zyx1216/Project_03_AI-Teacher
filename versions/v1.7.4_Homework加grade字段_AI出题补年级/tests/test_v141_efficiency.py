# -*- coding: utf-8 -*-
"""v1.4.1 效率工具：批量审核 / 批量删除（作业、学生）服务层测试。"""

from datetime import date

from models.models import Homework, Score, Student
from utils import exam_service, homework_service as hw
from utils import question_service as qs
from utils import student_service as ss


def _question(session, content, status="pending", subject="数学"):
    data = qs.validate_question({
        "content": content, "question_type": "solution",
        "difficulty": 2, "answer": "答", "knowledge_points": ""})
    return qs.create_question(session, data, source="manual",
                              status=status, subject=subject)


# ---------------- 批量审核 ----------------

def test_approve_questions_only_pending(session):
    q1 = _question(session, "待审1", status="pending")
    q2 = _question(session, "待审2", status="pending")
    q3 = _question(session, "已审", status="approved")
    n = qs.approve_questions(session, [q1.id, q2.id, q3.id, 999999])
    session.commit()
    assert n == 2  # 已审核和不存在的 id 跳过
    assert session.get(type(q1), q1.id).status == "approved"
    assert session.get(type(q2), q2.id).status == "approved"
    assert session.get(type(q3), q3.id).status == "approved"


def test_approve_questions_dedup_ids(session):
    q1 = _question(session, "待审1")
    n = qs.approve_questions(session, [q1.id, q1.id, q1.id])
    assert n == 1


# ---------------- 批量删除作业 ----------------

def test_delete_homeworks_cascade(session):
    h1 = hw.create_homework(session, "作业1")
    h2 = hw.create_homework(session, "作业2")
    data = qs.validate_question({
        "content": "题", "question_type": "solution", "difficulty": 2,
        "answer": "x=1", "knowledge_points": ""})
    q = qs.create_question(session, data, source="manual", status="approved")
    session.flush()
    hw.add_questions(session, h1.id, [q.id])
    session.commit()

    n = hw.delete_homeworks(session, [h1.id, h2.id, 999999])
    session.commit()
    assert n == 2  # 不存在的 id 跳过
    assert session.get(Homework, h1.id) is None
    assert session.get(Homework, h2.id) is None
    # 题目本身不删，只删作业关联
    assert session.get(type(q), q.id) is not None
    assert hw.list_homeworks(session) == []


def test_delete_homeworks_can_remove_template_by_id(session):
    tpl = hw.create_homework(session, "模板", is_template=True)
    session.commit()
    n = hw.delete_homeworks(session, [tpl.id])
    session.commit()
    assert n == 1
    assert hw.list_homeworks(session, templates=True) == []


# ---------------- 批量删除学生 ----------------

def test_delete_students_cascade_scores(session):
    s1, _ = ss.get_or_create_student(session, "甲", "一班")
    s2, _ = ss.get_or_create_student(session, "乙", "一班")
    s3, _ = ss.get_or_create_student(session, "丙", "二班")
    exam = exam_service.create_exam(session, "月考", exam_date=date(2026, 9, 1),
                                    full_scores={"数学": 100})
    session.flush()
    exam_service.import_scores(session, exam.id, [
        {"name": "甲", "class_name": "一班", "scores": {"数学": 80.0}},
        {"name": "乙", "class_name": "一班", "scores": {"数学": 90.0}},
    ])
    session.commit()
    assert session.query(Score).count() == 2

    n = ss.delete_students(session, [s1.id, s2.id, 999999])
    session.commit()
    assert n == 2  # 不存在的 id 跳过
    remaining = session.query(Student).all()
    assert [s.name for s in remaining] == ["丙"]
    # 成绩随学生级联删除
    assert session.query(Score).count() == 0


def test_delete_students_dedup_ids(session):
    s1, _ = ss.get_or_create_student(session, "甲", "一班")
    session.commit()
    n = ss.delete_students(session, [s1.id, s1.id])
    session.commit()
    assert n == 1
