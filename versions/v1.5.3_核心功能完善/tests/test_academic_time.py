# -*- coding: utf-8 -*-
"""按考试日期推导学期、学年、考试类型和趋势标签。"""

from datetime import date

from utils import academic_time as at


def test_semester_boundaries():
    assert at.semester_name(date(2026, 1, 15)) == "2025秋"
    assert at.short_semester_name(date(2026, 1, 15)) == "25秋"
    assert at.semester_name(date(2026, 2, 1)) == "2026春"
    assert at.semester_name(date(2026, 8, 31)) == "2026春"
    assert at.semester_name(date(2026, 9, 1)) == "2026秋"
    assert at.short_semester_name(date(2026, 9, 1)) == "26秋"


def test_academic_year_boundaries():
    assert at.academic_year_name(date(2026, 1, 31)) == "2025-2026学年"
    assert at.academic_year_name(date(2026, 8, 31)) == "2025-2026学年"
    assert at.academic_year_name(date(2026, 9, 1)) == "2026-2027学年"


def test_exam_type_detection():
    assert at.exam_type("入学摸底考试") == "摸底"
    assert at.exam_type("第一次月考") == "月考"
    assert at.exam_type("期中考试") == "期中"
    assert at.exam_type("期末考试") == "期末"
    assert at.exam_type("单元练习") == "其他"


class _Exam:
    def __init__(self, exam_id, name, exam_date):
        self.id = exam_id
        self.name = name
        self.exam_date = exam_date


def test_unique_exam_labels_duplicate_same_semester_adds_number():
    exams = [
        _Exam(1, "第一次月考", date(2026, 9, 1)),
        _Exam(2, "第一次月考", date(2026, 10, 1)),
        _Exam(3, "第一次月考", date(2027, 3, 1)),
    ]
    labels = at.unique_exam_labels(exams)
    assert labels == {
        1: "26秋·第一次月考(1)",
        2: "26秋·第一次月考(2)",
        3: "27春·第一次月考",
    }


def test_unique_exam_labels_accept_mapping():
    labels = at.unique_exam_labels({
        8: {"name": "期中", "exam_date": date(2026, 11, 1)},
    })
    assert labels == {8: "26秋·期中"}
