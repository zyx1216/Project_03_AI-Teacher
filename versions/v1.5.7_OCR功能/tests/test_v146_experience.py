# -*- coding: utf-8 -*-
"""v1.4.6 体验优化：趋势双维过滤、班级表格同步、学生排序。"""

from datetime import date
from types import SimpleNamespace

import pytest
from models.models import Homework, Student
from utils import class_service, student_service
from modules import analysis


def _exam(exam_id, exam_date, name="月考"):
    return SimpleNamespace(id=exam_id, exam_date=exam_date, name=name)


def test_trend_time_options_sorted():
    exams = [
        _exam(1, date(2026, 3, 1)),   # 2025-2026 学年，2026春
        _exam(2, date(2026, 10, 1)),  # 2026-2027 学年，2026秋
        _exam(3, date(2027, 3, 1)),   # 2026-2027 学年，2027春
    ]
    options = analysis._trend_time_options(exams)
    assert options[0] == "全部"
    assert "学期：2026春" in options
    assert "学期：2026秋" in options
    assert "学期：2027春" in options
    # 学期按时间升序：2026春 早于 2026秋 早于 2027春
    semesters = [x for x in options if x.startswith("学期：")]
    assert semesters == ["学期：2026春", "学期：2026秋", "学期：2027春"]
    assert "学年：2025-2026学年" in options
    assert "学年：2026-2027学年" in options


def test_trend_filter_time_then_limit():
    # 2026秋 3 场 + 2027春 3 场，共 6 场
    exams = [
        _exam(10, date(2026, 9, 10), "开学摸底"),
        _exam(11, date(2026, 10, 10), "第一次月考"),
        _exam(12, date(2026, 11, 10), "期中考试"),
        _exam(13, date(2027, 3, 10), "开学摸底"),
        _exam(14, date(2027, 4, 10), "第一次月考"),
        _exam(15, date(2027, 5, 10), "期中考试"),
    ]
    ids2, limit2 = analysis._trend_filter_exams(exams, "学期：2027春", "最近 3 次")
    assert ids2 == [13, 14, 15] and limit2 == 3

    ids3, limit3 = analysis._trend_filter_exams(exams, "学期：2027春", "最近 5 次")
    assert ids3 == [13, 14, 15] and limit3 == 5  # 不足 5 场返回全部

    # 2026秋+2027春 同属 2026-2027 学年：先过滤到 6 场，再由图表层取最后 2 场
    ids4, limit4 = analysis._trend_filter_exams(exams, "学年：2026-2027学年", "最近 2 次")
    assert ids4 == [10, 11, 12, 13, 14, 15] and limit4 == 2
    assert ids4[-2:] == [14, 15]

    ids5, limit5 = analysis._trend_filter_exams(exams, "全部", "全部")
    assert ids5 == [10, 11, 12, 13, 14, 15] and limit5 is None


def test_trend_filter_null_date_only_in_all():
    exams = [_exam(1, None), _exam(2, date(2026, 10, 1))]
    ids, _ = analysis._trend_filter_exams(exams, "学期：2026秋", "全部")
    assert ids == [2]
    ids_all, _ = analysis._trend_filter_exams(exams, "全部", "全部")
    assert set(ids_all) == {1, 2}


# ---- 学生服务：排序与表格新增 ----

def test_list_students_order_by_class_then_no(session):
    session.add_all([
        Student(name="乙", class_name="二班", student_no="02"),
        Student(name="丁", class_name="一班", student_no="10"),
        Student(name="甲", class_name="一班", student_no="03"),
        Student(name="丙", class_name="一班", student_no="01"),
    ])
    session.commit()
    names = [(s.class_name, s.student_no, s.name)
             for s in student_service.list_students(session)]
    assert names == [
        ("一班", "01", "丙"),
        ("一班", "03", "甲"),
        ("一班", "10", "丁"),
        ("二班", "02", "乙"),
    ]


def test_sync_students_add_row_with_gender_normalized(session):
    rows = [
        {"学生ID": None, "姓名": "新生", "班级": "一班",
         "学号": "01", "性别": "男", "标签": "", "备注": ""},
        {"学生ID": None, "姓名": "未设性别", "班级": "一班",
         "学号": "02", "性别": "其他", "标签": None, "备注": None},
    ]
    result = student_service.sync_students(session, rows, existing_ids=set())
    session.commit()
    assert result["created"] == 2
    students = student_service.list_students(session, class_name="一班")
    assert {s.name: s.gender for s in students} == {"新生": "男", "未设性别": None}


def test_sync_students_blank_name_and_duplicate_rejected(session):
    with pytest.raises(ValueError, match="姓名不能为空"):
        student_service.sync_students(
            session,
            [{"学生ID": None, "姓名": "  ", "班级": "一班"}],
            existing_ids=set())
    session.add(Student(name="甲", class_name="一班"))
    session.commit()
    with pytest.raises(ValueError, match="学生已存在"):
        student_service.sync_students(
            session,
            [{"学生ID": None, "姓名": "甲", "班级": "一班"}],
            existing_ids=set())


# ---- 班级服务：sync_classes ----

@pytest.fixture()
def class_file(tmp_path, monkeypatch):
    path = tmp_path / "class_names.json"
    monkeypatch.setattr(class_service, "CLASS_NAMES_PATH", path)
    return path


def test_sync_classes_add_and_rename(class_file, session):
    class_service.add_class(session, "一班")
    session.add(Student(name="甲", class_name="一班"))
    session.commit()

    result = class_service.sync_classes(session, [
        {"原班级名": "一班", "班级名": "三班"},
        {"原班级名": None, "班级名": "二班"},
    ])
    session.commit()
    assert result == {"added": 1, "renamed": 1}
    assert class_service.load_configured_classes() == ["三班", "二班"]
    assert session.query(Student).filter(Student.class_name == "三班").count() == 1


def test_sync_classes_blank_and_duplicate_rejected(class_file, session):
    class_service.add_class(session, "一班")
    class_service.add_class(session, "二班")
    with pytest.raises(ValueError, match="不能为空"):
        class_service.sync_classes(
            session, [{"原班级名": None, "班级名": "  "}])
    with pytest.raises(ValueError, match="已存在"):
        class_service.sync_classes(
            session, [{"原班级名": None, "班级名": "一班"}])
    with pytest.raises(ValueError, match="重复班级"):
        class_service.sync_classes(session, [
            {"原班级名": None, "班级名": "三班"},
            {"原班级名": None, "班级名": "三班"},
        ])


def test_class_usage_blocks_delete_with_homework_only(class_file, session):
    class_service.add_class(session, "一班")
    session.add(Homework(name="作业", class_name="一班", is_template=False))
    session.commit()
    usage = class_service.class_usage(session, "一班")
    assert usage["students"] == 0 and usage["homeworks"] == 1
    with pytest.raises(ValueError, match="学生或作业"):
        class_service.delete_class(session, "一班")
