# -*- coding: utf-8 -*-
"""v1.5.3 首页统计与错题重做卷服务测试。"""

from datetime import date, datetime

import pytest

from models.models import Homework, HomeworkQuestion, LessonPlan, Question
from utils import (
    dashboard_service as ds,
    exam_service,
    homework_score_service as hscore,
    homework_service as hw,
    question_service as qs,
    student_service as ss,
)

TODAY = date(2026, 9, 21)


def _question(session, name: str, difficulty: int = 2) -> Question:
    data = qs.validate_question({
        "content": name, "question_type": "solution",
        "difficulty": difficulty, "answer": "答案",
        "analysis": "解析", "knowledge_points": "知识点"})
    return qs.create_question(session, data, source="manual", status="approved")


def _exam_with_score(session, name: str, day: date, score: float):
    exam = exam_service.create_exam(
        session, name, exam_date=day, term="2026秋",
        full_scores={"数学": 100})
    exam_service.import_scores(session, exam.id, [{
        "name": "学生甲", "class_name": "一班",
        "scores": {"数学": score}}])
    return exam


def test_semester_and_month_bounds():
    assert ds.semester_bounds(date(2026, 9, 21)) == (
        date(2026, 9, 1), date(2027, 2, 1))
    assert ds.semester_bounds(date(2027, 1, 10)) == (
        date(2026, 9, 1), date(2027, 2, 1))
    assert ds.semester_bounds(date(2027, 3, 1)) == (
        date(2027, 2, 1), date(2027, 9, 1))
    assert ds.month_bounds(TODAY) == (
        date(2026, 9, 1), date(2026, 10, 1))


def test_dashboard_counts_exams_and_pending(session):
    # 本学期教案：1 条计入；暑假旧教案不计入。
    session.add(LessonPlan(title="秋教案", content="{}",
                           created_at=datetime(2026, 9, 10)))
    session.add(LessonPlan(title="暑假教案", content="{}",
                           created_at=datetime(2026, 8, 30)))
    # 本月普通作业计入；模板不计入。
    hw.create_homework(session, "九月作业", subject="数学",
                       class_name="一班", duration=45)
    hw.create_homework(session, "模板", is_template=True, subject="数学")
    # 名册 2 人，作业只录 1 人，因此待批改 1 人。
    ss.get_or_create_student(session, "学生甲", "一班")
    ss.get_or_create_student(session, "学生乙", "一班")
    hscore.import_total_scores(session, 1, [{
        "name": "学生甲", "class_name": "一班", "score": 90}])

    _exam_with_score(session, "第一次月考", date(2026, 9, 1), 80)
    latest = _exam_with_score(session, "第二次月考", date(2026, 9, 15), 90)
    session.flush()

    data = ds.dashboard_data(session, TODAY)
    assert data["lesson_count"] == 1
    assert data["monthly_homework_count"] == 1
    assert data["latest_average"] == 90
    assert data["pending_count"] == 1
    assert data["pending_items"][0] == {"作业": "九月作业", "未录人数": 1}
    assert [x["考试"] for x in data["recent_exams"]] == [
        "第二次月考", "第一次月考"]
    assert data["recent_exams"][0]["变化"] == 10
    assert data["recent_homeworks"][0]["名称"] == "九月作业"


def test_dashboard_completed_class_homework_not_pending(session):
    hw.create_homework(session, "已完成", class_name="一班")
    ss.get_or_create_student(session, "学生甲", "一班")
    hscore.import_total_scores(session, 1, [{
        "name": "学生甲", "class_name": "一班", "score": 90}])
    session.flush()
    data = ds.dashboard_data(session, TODAY)
    assert data["pending_count"] == 0


def test_dashboard_no_class_homework_pending_rules(session):
    # 无班级且完全未录：待批改。
    first = hw.create_homework(session, "无班级未录", class_name=None)
    # 无班级但已有一条成绩：不再计入待批改。
    second = hw.create_homework(session, "无班级部分录", class_name=None)
    student, _ = ss.get_or_create_student(session, "学生甲", None)
    hscore.save_total_score(session, second.id, student.id, 88)
    session.flush()

    data = ds.dashboard_data(session, TODAY)
    assert [x["作业"] for x in data["pending_items"]] == ["无班级未录"]


def test_dashboard_empty_database(session):
    data = ds.dashboard_data(session, TODAY)
    assert data["lesson_count"] == 0
    assert data["monthly_homework_count"] == 0
    assert data["latest_average"] is None
    assert data["pending_count"] == 0


def test_retry_homework_name_dedup(session):
    base_name = "错题重做卷_20260921"
    hw.create_homework(session, base_name)
    assert hw.default_retry_homework_name(session, TODAY) == f"{base_name}_2"
    hw.create_homework(session, f"{base_name}_2")
    assert hw.default_retry_homework_name(session, TODAY) == f"{base_name}_3"


def test_generate_retry_homework_with_changed_score(session):
    q = _question(session, "原题")
    original = hw.create_homework(session, "原作业", class_name="一班")
    hw.add_questions(session, original.id, [q.id], default_score=8)

    result = hw.generate_retry_homework(
        session,
        [{"question_id": q.id, "difficulty": 2, "score": 12}],
        "错题重做卷_20260921", "数学", class_name="一班")
    session.flush()

    new_hw = session.get(Homework, result["homework_id"])
    link = session.query(HomeworkQuestion).filter_by(
        homework_id=new_hw.id).one()
    assert new_hw.homework_type == "after_class"
    assert new_hw.class_name == "一班"
    assert new_hw.subject == "数学"
    assert new_hw.total_score == 12
    assert link.score == 12 and link.question_id == q.id
    assert result == {
        "homework_id": new_hw.id, "question_count": 1,
        "reused_count": 1, "cloned_count": 0}


def test_generate_retry_homework_changed_difficulty_clones_question(session):
    q = _question(session, "原题", difficulty=2)
    result = hw.generate_retry_homework(
        session,
        [{"question_id": q.id, "difficulty": 3, "score": 10}],
        "错题重做卷_20260921", "数学")
    session.flush()

    link = session.query(HomeworkQuestion).filter_by(
        homework_id=result["homework_id"]).one()
    clone = session.get(Question, link.question_id)
    assert clone.id != q.id
    assert clone.difficulty == 3
    assert clone.content == q.content and clone.answer == q.answer
    assert clone.source == "错题重做"
    assert q.difficulty == 2
    assert result["reused_count"] == 0
    assert result["cloned_count"] == 1


def test_generate_retry_homework_dedup_and_validation(session):
    q = _question(session, "原题")
    with pytest.raises(ValueError, match="没有选择错题"):
        hw.generate_retry_homework(session, [], "名称", "数学")
    with pytest.raises(ValueError, match="大于 0"):
        hw.generate_retry_homework(
            session,
            [{"question_id": q.id, "difficulty": 2, "score": 0}],
            "名称", "数学")
    with pytest.raises(ValueError, match="难度"):
        hw.generate_retry_homework(
            session,
            [{"question_id": q.id, "difficulty": 4, "score": 10}],
            "名称", "数学")

    result = hw.generate_retry_homework(
        session,
        [{"question_id": q.id, "difficulty": 2, "score": 10},
         {"question_id": q.id, "difficulty": 2, "score": 10}],
        "名称", "数学")
    session.flush()
    assert result["question_count"] == 1
