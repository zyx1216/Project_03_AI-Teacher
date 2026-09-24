# -*- coding: utf-8 -*-
"""教学反思服务层测试：数据聚合、四段解析、留档、Word 导出。"""

from datetime import date, datetime

from models.models import (
    Exam, Homework, HomeworkAnswer, HomeworkQuestion, Question, Student)
from utils import exam_service, reflection_service as rs


# 两个班共用的造数据小工具
def _make_exam_with_scores(session, name, d, students, totals, full=100):
    exam = exam_service.create_exam(
        session, name, exam_date=d, grade="八年级",
        full_scores={"数学": full})
    session.flush()
    for stu, score in zip(students, totals):
        exam_service.import_scores(
            session, exam.id,
            [{"name": stu.name, "class_name": stu.class_name,
              "scores": {"数学": score}}])
    session.flush()
    return exam


def _seed(session):
    s1 = Student(name="学生01", class_name="一班")
    s2 = Student(name="学生02", class_name="一班")
    s3 = Student(name="学生03", class_name="一班")
    session.add_all([s1, s2, s3])
    session.flush()
    e1 = _make_exam_with_scores(session, "第一次月考", date(2026, 3, 1),
                                [s1, s2, s3], [60, 70, 90])
    e2 = _make_exam_with_scores(session, "期中考试", date(2026, 4, 15),
                                [s1, s2, s3], [70, 60, 95])
    # 一份作业 + 一道题 + 两个错误作答
    q = Question(content="解方程 2x=4", question_type="solution", difficulty=1,
                 knowledge_points='["一元一次方程"]', answer="x=2")
    hw = Homework(name="一元一次方程作业", homework_type="after_class",
                  class_name="一班", created_at=datetime(2026, 4, 1))
    session.add_all([q, hw])
    session.flush()
    session.add(HomeworkQuestion(homework_id=hw.id, question_id=q.id, order=1, score=10))
    session.add_all([
        HomeworkAnswer(homework_id=hw.id, student_id=s1.id, question_id=q.id,
                       order_no=1, is_correct=False, error_type="计算错误"),
        HomeworkAnswer(homework_id=hw.id, student_id=s2.id, question_id=q.id,
                       order_no=1, is_correct=False, error_type="概念错误"),
        HomeworkAnswer(homework_id=hw.id, student_id=s3.id, question_id=q.id,
                       order_no=1, is_correct=True),
    ])
    session.commit()
    return e1, e2, q, hw


def test_exams_in_scope_single_and_range(session):
    e1, e2, _, _ = _seed(session)
    single = rs.exams_in_scope(session, "exam", e2.id)
    assert [e.id for e in single] == [e2.id]
    ranged = rs.exams_in_scope(session, "range", e1.id, e2.id)
    assert [e.id for e in ranged] == [e1.id, e2.id]


def test_data_text_contains_exam_metrics_and_wrong_questions(session):
    e1, e2, q, hw = _seed(session)
    text = rs.build_reflection_data_text(session, "range", e1.id, e2.id, "一班")
    # 成绩指标
    assert "考试成绩数据" in text
    assert "及格率" in text and "均分" in text
    # 作业错题
    assert "作业错题数据" in text
    assert "一元一次方程" in text
    assert "计算错误" in text and "概念错误" in text


def test_data_text_single_exam_without_answers(session):
    e1, e2, q, hw = _seed(session)
    # 只选第一场（作业创建在 4 月，窗口取不到也没关系）；至少不报错且含成绩
    text = rs.build_reflection_data_text(session, "exam", e1.id, None, "一班")
    assert "第一次月考" in text


def test_parse_sections_four_parts():
    raw = ("## 成功之处\n均分提高。\n## 不足之处\n计算薄弱。\n"
           "## 学生反馈\n状态稳定。\n## 改进措施\n加强练习。")
    sec = rs.parse_sections(raw)
    assert sec["成功之处"] == "均分提高。"
    assert sec["不足之处"] == "计算薄弱。"
    assert sec["学生反馈"] == "状态稳定。"
    assert sec["改进措施"] == "加强练习。"


def test_parse_sections_fallback_keeps_text():
    sec = rs.parse_sections("没有标题的整段内容")
    assert sec["成功之处"] == "没有标题的整段内容"
    assert sec["不足之处"] == ""


def test_save_load_list_delete_reflection(session):
    e1, e2, _, _ = _seed(session)
    sections = {name: f"{name}内容" for name in rs.SECTIONS}
    row = rs.save_reflection(session, "期中反思", "exam", e2.id, "一班", sections)
    session.commit()
    assert row.id is not None

    loaded = rs.load_reflection_content(row)
    assert loaded["sections"]["成功之处"] == "成功之处内容"
    assert "## 改进措施" in loaded["raw"]

    assert len(rs.list_reflections(session)) == 1
    assert rs.list_reflections(session, "二班") == []

    rs.delete_reflection(session, row.id)
    session.commit()
    assert rs.list_reflections(session) == []


def test_save_reflection_plain_text_and_update(session):
    e1, e2, _, _ = _seed(session)
    raw = "## 成功之处\n进步明显\n## 不足之处\n仍需努力"
    row = rs.save_reflection(session, "标题", "range", e1.id, "一班", raw,
                             end_exam_id=e2.id)
    session.commit()
    assert row.scope_type == "range" and row.end_exam_id == e2.id
    updated = rs.save_reflection(
        session, "新标题", "range", e1.id, "一班",
        {n: "x" for n in rs.SECTIONS}, end_exam_id=e2.id, reflection_id=row.id)
    session.commit()
    assert updated.title == "新标题"


def test_export_word_contains_four_headings(session):
    e1, e2, _, _ = _seed(session)
    row = rs.save_reflection(session, "反思导出", "exam", e2.id, "一班",
                             {n: f"{n}的内容" for n in rs.SECTIONS})
    session.commit()
    blob = rs.export_word(row)
    from docx import Document
    import io
    doc = Document(io.BytesIO(blob))
    headings = [p.text for p in doc.paragraphs if p.style.name.startswith("Heading")]
    for name in rs.SECTIONS:
        assert name in headings


def test_data_text_custom_thresholds_without_median(session):
    s1 = Student(name="阈值甲", class_name="一班")
    s2 = Student(name="阈值乙", class_name="一班")
    s3 = Student(name="阈值丙", class_name="一班")
    session.add_all([s1, s2, s3])
    session.flush()
    exam = _make_exam_with_scores(
        session, "阈值月考", date(2026, 4, 20),
        [s1, s2, s3], [60, 80, 100])
    session.commit()

    text = rs.build_reflection_data_text(
        session, "exam", exam.id, None, "一班",
        thresholds={"pass_ratio": 0.6, "excellent_ratio": 0.8})
    assert "中位数" not in text
    assert "标准差" not in text
    assert "及格率100.0%" in text
    assert "优秀率66.7%" in text
