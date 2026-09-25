# -*- coding: utf-8 -*-
"""v1.4.0 新增筛选能力：作业、学生、考试学期、题目排序。"""

from datetime import date

from models.models import Exam, Homework, Question, Student
from utils import exam_service, homework_service as hw, question_service as qs
from utils import student_service as ss


def _question(content: str) -> dict:
    return qs.validate_question({
        "content": content, "question_type": "solution",
        "difficulty": 2, "answer": "答", "analysis": "", "knowledge_points": ""})


# ---------------- 作业 ----------------

def _make_homework(session, name, **kw):
    h = hw.create_homework(session, name, **kw)
    session.flush()
    return h


def test_list_homeworks_without_new_filters_keeps_old_behavior(session):
    _make_homework(session, "作业甲")
    _make_homework(session, "作业乙")
    rows = hw.list_homeworks(session, templates=False)
    assert {h.name for h in rows} == {"作业甲", "作业乙"}


def test_list_homeworks_keyword_fuzzy(session):
    _make_homework(session, "一元二次方程练习")
    _make_homework(session, "函数复习卷")
    rows = hw.list_homeworks(session, keyword="方程")
    assert [h.name for h in rows] == ["一元二次方程练习"]
    # 关键词带空格也能匹配
    assert len(hw.list_homeworks(session, keyword=" 复习 ")) == 1


def test_list_homeworks_type_filter(session):
    _make_homework(session, "预习单", homework_type="preview")
    _make_homework(session, "试卷", homework_type="exam")
    rows = hw.list_homeworks(session, homework_type="exam")
    assert [h.name for h in rows] == ["试卷"]


def test_list_homeworks_class_filter(session):
    _make_homework(session, "一班作业", class_name="一班")
    _make_homework(session, "二班作业", class_name="二班")
    rows = hw.list_homeworks(session, class_name="一班")
    assert [h.name for h in rows] == ["一班作业"]


def test_list_homeworks_keyword_and_subject_combined(session):
    _make_homework(session, "物理力学卷", homework_type="exam", subject="物理")
    _make_homework(session, "数学力学练习", homework_type="exam", subject="数学")
    rows = hw.list_homeworks(session, keyword="力学", subject="物理")
    assert [h.name for h in rows] == ["物理力学卷"]
    # 模板不受普通作业筛选参数影响：模板仍按学科过滤
    hw.create_homework(session, "数学模板", is_template=True, subject="数学")
    tpl = hw.list_homeworks(session, templates=True, subject="数学")
    assert [h.name for h in tpl] == ["数学模板"]


def test_list_homework_classes(session):
    _make_homework(session, "甲", class_name="二班", subject="数学")
    _make_homework(session, "乙", class_name="一班", subject="数学")
    _make_homework(session, "丙", class_name="一班", subject="物理")
    # 不传学科：全部班级
    assert hw.list_homework_classes(session) == ["一班", "二班"]
    # 传学科只统计该学科普通作业的班级
    assert hw.list_homework_classes(session, subject="物理") == ["一班"]


# ---------------- 学生 ----------------

def _add_student(session, name, class_name="一班", gender=None, tags=None,
                 student_no=None):
    s = Student(name=name, class_name=class_name, gender=gender, tags=tags,
                student_no=student_no)
    session.add(s)
    session.flush()
    return s


def test_list_students_gender_filter(session):
    _add_student(session, "甲", gender="男")
    _add_student(session, "乙", gender="女")
    _add_student(session, "丙")  # NULL
    _add_student(session, "丁", gender="")  # 空串也算未设置
    assert {s.name for s in ss.list_students(session, gender="男")} == {"甲"}
    assert {s.name for s in ss.list_students(session, gender="女")} == {"乙"}
    assert {s.name for s in ss.list_students(session, gender="未设置")} == {"丙", "丁"}


def test_list_students_tag_filter(session):
    _add_student(session, "甲", tags="积极,计算薄弱")
    _add_student(session, "乙", tags="积极")
    _add_student(session, "丙", tags="粗心")
    assert {s.name for s in ss.list_students(session, tag="计算薄弱")} == {"甲"}
    assert {s.name for s in ss.list_students(session, tag="积极")} == {"甲", "乙"}


def test_list_students_filters_combined(session):
    _add_student(session, "甲", class_name="一班", gender="男", tags="积极")
    _add_student(session, "乙", class_name="一班", gender="女", tags="积极")
    _add_student(session, "丙", class_name="二班", gender="男", tags="积极")
    rows = ss.list_students(session, class_name="一班", gender="男", tag="积极")
    assert [s.name for s in rows] == ["甲"]
    # 关键词与其他条件组合
    _add_student(session, "甲二号", class_name="一班", gender="男",
                 student_no="1002")
    rows = ss.list_students(session, keyword="1002")
    assert [s.name for s in rows] == ["甲二号"]


def test_list_student_tags_split_dedup_sort(session):
    _add_student(session, "甲", tags="积极,计算薄弱、粗心")
    _add_student(session, "乙", tags="积极，认真,,、")
    _add_student(session, "丙", tags=None)
    tags = ss.list_student_tags(session)
    # 逗号、中文逗号、顿号都能拆；去重排序；空标签忽略
    assert tags == sorted({"积极", "计算薄弱", "粗心", "认真"})


# ---------------- 考试学期 ----------------

def _add_exam(session, name, term):
    e = exam_service.create_exam(session, name, exam_date=date(2026, 9, 1),
                                 term=term)
    session.flush()
    return e


def test_list_exams_term_filter(session):
    e1 = _add_exam(session, "2026上期中", "2026上")
    e2 = _add_exam(session, "2026下月考", "2026下")
    e3 = _add_exam(session, "旧考试无学期", term=None)
    assert [e.id for e in exam_service.list_exams(session, term="2026上")] == [e1.id]
    # 不过滤时全部返回（含学期为空的旧考试），顺序按日期
    assert [e.id for e in exam_service.list_exams(session)] == [e1.id, e2.id, e3.id]


def test_list_exam_terms_dedup_sort(session):
    _add_exam(session, "甲", "2026下")
    _add_exam(session, "乙", "2026上")
    _add_exam(session, "丙", "2026上")
    _add_exam(session, "丁", term=None)
    _add_exam(session, "戊", term="")
    assert exam_service.list_exam_terms(session) == ["2026上", "2026下"]


# ---------------- 题目排序 ----------------

def test_list_questions_newest_first_with_id_tiebreak(session):
    # created_at 可能相同，靠 id DESC 兜底，保证顺序稳定、新题在前
    q1 = qs.create_question(session, _question("旧题"), status="approved")
    q2 = qs.create_question(session, _question("新题"), status="approved")
    session.flush()
    assert q2.id > q1.id
    rows = qs.list_questions(session)
    assert [q.id for q in rows[:2]] == [q2.id, q1.id]
