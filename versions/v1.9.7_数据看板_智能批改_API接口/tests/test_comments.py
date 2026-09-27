# -*- coding: utf-8 -*-
"""期末评语服务层测试：数据组装、模板 CRUD、评语 upsert、批量导出。"""

from datetime import date

from models.models import (
    Homework, HomeworkAnswer, HomeworkQuestion, Question, Student)
from utils import comment_service as cs
from utils import exam_service


def _seed_student_with_scores(session):
    stu = Student(name="学生01", class_name="一班", student_no="2026001")
    session.add(stu)
    session.flush()
    for name, d, score in [("第一次月考", date(2026, 3, 1), 90),
                           ("期中考试", date(2026, 4, 15), 95)]:
        exam = exam_service.create_exam(
            session, name, exam_date=d, full_scores={"数学": 100})
        session.flush()
        exam_service.import_scores(
            session, exam.id,
            [{"name": stu.name, "class_name": stu.class_name,
              "scores": {"数学": score}}])
    # 一道错题，带薄弱知识点
    q = Question(content="题", question_type="solution", difficulty=2,
                 knowledge_points='["因式分解"]', answer="略")
    hw = Homework(name="作业", homework_type="after_class", class_name="一班")
    session.add_all([q, hw])
    session.flush()
    session.add(HomeworkQuestion(homework_id=hw.id, question_id=q.id, order=1))
    session.add(HomeworkAnswer(homework_id=hw.id, student_id=stu.id,
                               question_id=q.id, is_correct=False,
                               error_type="计算错误"))
    session.commit()
    return stu


def test_build_comment_input_contains_tags_history_and_kp(session):
    stu = _seed_student_with_scores(session)
    text = cs.build_comment_input(session, stu, "2026 上")
    assert "学生01" in text and "2026 上" in text
    assert "成绩层次" in text and "趋势" in text
    assert "第一次月考" in text and "期中考试" in text
    assert "因式分解" in text  # 作业错题的薄弱知识点


def test_build_comment_input_no_scores(session):
    stu = Student(name="无成绩", class_name="一班")
    session.add(stu)
    session.commit()
    text = cs.build_comment_input(session, stu, "2026 上")
    assert "暂无考试成绩" in text


def test_template_crud(session):
    tpl = cs.create_template(session, "鼓励模板", "你这学期表现不错", "鼓励")
    session.commit()
    assert tpl.id is not None
    assert len(cs.list_templates(session)) == 1
    assert len(cs.list_templates(session, style="严格")) == 0
    cs.delete_template(session, tpl.id)
    session.commit()
    assert cs.list_templates(session) == []


def test_template_invalid_style_defaults(session):
    tpl = cs.create_template(session, "x", "y", "不存在的风格")
    session.commit()
    assert tpl.style == "中肯"


def test_upsert_comment_updates_instead_of_duplicate(session):
    stu = Student(name="学生02", class_name="一班")
    session.add(stu)
    session.commit()
    c1 = cs.upsert_comment(session, stu.id, "2026 上", "第一段评语", "鼓励")
    session.commit()
    c2 = cs.upsert_comment(session, stu.id, "2026 上", "第二段评语", "严格")
    session.commit()
    assert c1.id == c2.id
    assert c2.content == "第二段评语" and c2.style == "严格"
    rows = cs.list_comments(session, term="2026 上")
    assert len(rows) == 1 and rows[0]["content"] == "第二段评语"


def test_upsert_comment_validation(session):
    import pytest
    stu = Student(name="学生03", class_name="一班")
    session.add(stu)
    session.commit()
    with pytest.raises(ValueError):
        cs.upsert_comment(session, stu.id, "", "内容", "中肯")
    with pytest.raises(ValueError):
        cs.upsert_comment(session, stu.id, "2026 上", "", "中肯")


def test_different_terms_are_separate_rows(session):
    stu = Student(name="学生04", class_name="一班")
    session.add(stu)
    session.commit()
    cs.upsert_comment(session, stu.id, "2025 下", "上学期", "中肯")
    cs.upsert_comment(session, stu.id, "2026 上", "这学期", "中肯")
    session.commit()
    assert len(cs.list_comments(session)) == 2


def test_export_comments_word_grouped_by_class(session):
    s1 = Student(name="甲", class_name="一班")
    s2 = Student(name="乙", class_name="二班")
    session.add_all([s1, s2])
    session.flush()
    cs.upsert_comment(session, s1.id, "2026 上", "甲的评语", "鼓励")
    cs.upsert_comment(session, s2.id, "2026 上", "乙的评语", "严格")
    session.commit()
    rows = cs.list_comments(session, term="2026 上")
    blob = cs.export_comments_word(rows, "期末评语")
    import io
    from docx import Document
    text = "\n".join(p.text for p in Document(io.BytesIO(blob)).paragraphs)
    assert "甲的评语" in text and "乙的评语" in text
    assert "一班" in text and "二班" in text
