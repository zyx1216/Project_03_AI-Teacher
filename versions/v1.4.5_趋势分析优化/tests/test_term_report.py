# -*- coding: utf-8 -*-
"""v1.4.2 学期报告 Word 生成测试。"""

from datetime import date, datetime, timedelta
from io import BytesIO
from zipfile import ZipFile

import pytest
from docx import Document
from models.models import Homework, HomeworkAnswer, Question, Student
from modules import analysis
from utils import exam_service, term_report_service


def _add_scores(session, exam, values, class_name="一班"):
    records = []
    for name, score in values:
        records.append({"name": name, "class_name": class_name,
                        "scores": {"数学": score}})
    return exam_service.import_scores(session, exam.id, records)


def _make_three_exam_term(session):
    exam_dates = [date(2026, 3, 1), date(2026, 4, 1), date(2026, 5, 1)]
    exams = []
    for i, d in enumerate(exam_dates, start=1):
        exam = exam_service.create_exam(
            session, f"第{i}次月考", exam_date=d, term="2026春",
            full_scores={"数学": 100})
        session.flush()
        # 丙第一场缺考，后两场有分，用于验证缺考留空但学生仍进入变化表。
        bing_score = None if i == 1 else 60 + i
        _add_scores(session, exam, [("甲", 70 + i * 5),
                                    ("乙", 80 + i * 2),
                                    ("丙", bing_score)])
        exams.append(exam)
    session.commit()
    return exams


def _read_docx_text_and_images(blob: bytes):
    doc = Document(BytesIO(blob))
    text = "\n".join(p.text for p in doc.paragraphs)
    for table in doc.tables:
        for row in table.rows:
            text += "\n" + "|".join(cell.text for cell in row.cells)
    with ZipFile(BytesIO(blob)) as zf:
        images = [n for n in zf.namelist() if n.startswith("word/media/")]
    return text, images


def test_build_term_report_contains_tables_students_and_embedded_image(session):
    _make_three_exam_term(session)
    blob = term_report_service.build_term_report(session, "2026春", "一班")
    text, images = _read_docx_text_and_images(blob)

    assert "2026春 学期成绩报告" in text
    assert "考试成绩汇总" in text
    assert "各科统计" in text
    assert "成绩趋势" in text
    assert "学生成绩变化" in text
    assert "第1次月考" in text and "第3次月考" in text
    assert "甲" in text and "乙" in text
    assert len(images) == 1
    # 缺考丙仍进入学生变化表，但分数单元格为破折号，不写成 0。
    assert "丙" in text


def test_build_term_report_top_wrong_questions_order(session):
    exams = _make_three_exam_term(session)
    student = session.query(Student).filter(Student.name == "甲").first()
    homework = Homework(name="春学期作业", class_name="一班", subject="数学",
                        created_at=datetime.combine(exams[0].exam_date, datetime.min.time()))
    q1 = Question(content="高频错题第一题", answer="答", subject="数学",
                  knowledge_points='["函数"]')
    q2 = Question(content="低频错题第二题", answer="答", subject="数学",
                  knowledge_points='["几何"]')
    session.add_all([homework, q1, q2])
    session.flush()
    # q1 两人错，q2 一人错；各补一个正确作答形成错误率差异。
    other = session.query(Student).filter(Student.name == "乙").first()
    session.add_all([
        HomeworkAnswer(homework_id=homework.id, student_id=student.id,
                       question_id=q1.id, is_correct=False),
        HomeworkAnswer(homework_id=homework.id, student_id=other.id,
                       question_id=q1.id, is_correct=False),
        HomeworkAnswer(homework_id=homework.id, student_id=student.id,
                       question_id=q2.id, is_correct=False),
        HomeworkAnswer(homework_id=homework.id, student_id=other.id,
                       question_id=q2.id, is_correct=True),
    ])
    session.commit()

    blob = term_report_service.build_term_report(session, "2026春", "一班")
    text, _images = _read_docx_text_and_images(blob)
    assert "高频错题 TOP5" in text
    assert text.index("高频错题第一题") < text.index("低频错题第二题")
    assert "函数" in text and "几何" in text


def test_build_term_report_without_answers_shows_empty_note(session):
    _make_three_exam_term(session)
    blob = term_report_service.build_term_report(session, "2026春", "一班")
    text, images = _read_docx_text_and_images(blob)
    assert "本学期暂无逐题批改数据" in text
    assert len(images) == 1


def test_build_term_report_rejects_all_terms_and_empty_term(session):
    with pytest.raises(ValueError, match="具体学期"):
        term_report_service.build_term_report(session, "全部学期")
    with pytest.raises(ValueError, match="还没有考试"):
        term_report_service.build_term_report(session, "不存在学期")


def test_build_term_report_does_not_mutate_scores(session):
    _make_three_exam_term(session)
    before = [(s.exam_id, s.student_id, s.subject, s.score)
              for s in session.query(__import__("models.models", fromlist=["Score"]).Score).all()]
    term_report_service.build_term_report(session, "2026春", "一班")
    term_report_service.build_term_report(session, "2026春", "一班")
    after = [(s.exam_id, s.student_id, s.subject, s.score)
             for s in session.query(__import__("models.models", fromlist=["Score"]).Score).all()]
    assert before == after



def test_term_report_filename_sanitized():
    assert analysis._safe_filename("2026春/一:班") == "2026春_一_班"


def test_build_term_report_uses_custom_thresholds_and_no_median(session):
    exams = _make_three_exam_term(session)
    # 60/80/100 在默认 85% 优秀线下只有 1 人优秀；80% 线下有 2 人优秀。
    extra = exam_service.create_exam(
        session, "阈值月考", exam_date=date(2026, 6, 1), term="2026春",
        full_scores={"数学": 100})
    session.flush()
    _add_scores(session, extra, [("甲", 60), ("乙", 80), ("丙", 100)])
    session.commit()

    blob = term_report_service.build_term_report(
        session, "2026春", "一班",
        thresholds={"pass_ratio": 0.6, "excellent_ratio": 0.8})
    text, images = _read_docx_text_and_images(blob)
    assert "中位数" not in text
    assert "标准差" not in text
    assert "66.7%" in text  # 2/3 优秀
    assert images
