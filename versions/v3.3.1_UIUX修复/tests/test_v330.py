# -*- coding: utf-8 -*-
"""v3.3.0 教师端功能增强（第二批）测试。"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models.models import (
    Base, Exam, Homework, HomeworkAnswer, HomeworkQuestion, HomeworkSubmission,
    KnowledgeEdge, KnowledgeNode, LessonPlan, Question, Score, Student,
    TeachingProgress,
)
from utils import (
    knowledge_graph_service as kgs,
    reminder_service,
    teaching_plan_service,
)


@pytest.fixture()
def session(tmp_path):
    eng = create_engine(f"sqlite:///{(tmp_path / 'v330.db').as_posix()}")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()
    eng.dispose()


# ---------------------------------------------------------------------------
# 数据库迁移
# ---------------------------------------------------------------------------

def test_v330_tables_and_migration():
    from migrations.v3_3_0_migration import migrate
    assert len(Base.metadata.tables) == 34
    assert "reminder_settings" in Base.metadata.tables
    eng = create_engine("sqlite:///:memory:")
    out = migrate(eng)
    assert out["tables"] == ["reminder_settings"]
    # 幂等：旧库 teaching_progress 缺列时补齐
    eng.dispose()


# ---------------------------------------------------------------------------
# 功能6：智能提醒
# ---------------------------------------------------------------------------

def _make_class_with_pending_homework(session, *, submitted=("甲",)):
    """一班 3 名学生 + 一份明天截止、只交了部分人的作业。"""
    students = [Student(name="甲", class_name="一班"),
                Student(name="乙", class_name="一班"),
                Student(name="丙", class_name="一班")]
    session.add_all(students)
    hw = Homework(name="课后练习1", homework_type="after_class",
                  class_name="一班", subject="数学", status="pending",
                  due_date=datetime.now() + timedelta(days=1))
    session.add(hw)
    session.flush()
    for name in submitted:
        session.add(HomeworkSubmission(
            homework_id=hw.id, student_name=name, answers_json="{}"))
    session.commit()
    return hw


def test_homework_reminder_lists_missing_students(session):
    hw = _make_class_with_pending_homework(session)
    reminders = reminder_service.list_reminders(session)
    homework_reminders = [r for r in reminders if r["reminder_type"] == "homework"]
    assert len(homework_reminders) == 1
    r = homework_reminders[0]
    assert set(r["missing"]) == {"乙", "丙"}
    assert r["submit_rate"] == pytest.approx(1 / 3, abs=0.01)
    # 可复制的催交文案里含未交学生姓名
    text = reminder_service.reminder_text(r)
    assert "乙" in text and "丙" in text and hw.name in text


def test_student_decline_and_no_submit_warnings(session):
    _make_class_with_pending_homework(session, submitted=())
    # 第二份作业也没人交 → 乙、丙连续 2 次未交
    hw2 = Homework(name="课后练习2", homework_type="after_class",
                   class_name="一班", subject="数学", status="pending")
    session.add(hw2)
    session.flush()
    # 学生乙最近 3 次考试持续下降
    yi = session.query(Student).filter(Student.name == "乙").first()
    for i, score in enumerate((80, 70, 60)):
        exam = Exam(name=f"月考{i}", exam_date=date.today() - timedelta(days=30 - i * 10))
        session.add(exam)
        session.flush()
        session.add(Score(exam_id=exam.id, student_id=yi.id,
                          subject="数学", score=score))
    session.commit()

    reminders = reminder_service.list_reminders(session)
    student_reminders = [r for r in reminders
                         if r["reminder_type"] == "student"]
    reasons = {r["reason"] for r in student_reminders}
    assert "score_decline" in reasons
    no_submit = next(r for r in student_reminders
                     if r["reason"] == "no_submit" and r["name"] == "乙")
    assert no_submit["missing_count"] == 2
    # 交了 0 次，甲也连续未交
    assert {r["name"] for r in student_reminders
            if r["reason"] == "no_submit"} == {"甲", "乙", "丙"}


def test_teaching_reminder_from_lag_progress(session):
    session.add(TeachingProgress(
        subject="数学", grade="初一", semester="2026秋", week_number=3,
        chapter="有理数运算", status="lag",
        planned_date=date.today() - timedelta(days=3)))
    session.commit()
    reminders = reminder_service.list_reminders(session)
    teaching = [r for r in reminders if r["reminder_type"] == "teaching"]
    assert len(teaching) == 1
    assert "有理数运算" in teaching[0]["content"]


def test_reminder_settings_enable_and_handled(session):
    _make_class_with_pending_homework(session)
    reminder_service.save_setting(session, "homework", enabled=False)
    session.commit()
    assert not [r for r in reminder_service.list_reminders(session)
                if r["reminder_type"] == "homework"]

    reminder_service.save_setting(session, "homework", enabled=True)
    session.commit()
    r = next(x for x in reminder_service.list_reminders(session)
             if x["reminder_type"] == "homework")
    reminder_service.mark_handled(session, r["signature"])
    session.commit()
    assert not [x for x in reminder_service.list_reminders(session)
                if x["signature"] == r["signature"]]


# ---------------------------------------------------------------------------
# 功能4：知识点体系可视化
# ---------------------------------------------------------------------------

def _question_with_kp(session, kp, **kwargs):
    q = Question(content=f"考{kp}的题", answer="略", subject="数学",
                 knowledge_points=f'["{kp}"]', status="approved", **kwargs)
    session.add(q)
    session.flush()
    return q


def test_node_detail(session):
    node = KnowledgeNode(name="有理数加减", type="概念", importance=4,
                         description="基础运算")
    session.add(node)
    session.flush()
    q1 = _question_with_kp(session, "有理数加减")
    q2 = _question_with_kp(session, "有理数加减")
    # 相关教案
    session.add(LessonPlan(title="有理数加减教案",
                           chapter="有理数加减"))
    # 作答数据：两题各一条正确一条错误 → 平均掌握度 50%
    stu = Student(name="甲", class_name="一班")
    session.add(stu)
    session.flush()
    hw = Homework(name="作业", class_name="一班", subject="数学")
    session.add(hw)
    session.flush()
    for q, correct, earned in ((q1, True, 10), (q2, False, 0)):
        link = HomeworkQuestion(homework_id=hw.id, question_id=q.id, score=10)
        session.add(link)
        session.flush()
        session.add(HomeworkAnswer(
            homework_id=hw.id, question_id=q.id, student_id=stu.id,
            is_correct=correct, earned_score=earned))
    session.commit()

    detail = kgs.node_detail(session, node.id, subject="数学")
    assert detail["name"] == "有理数加减"
    assert detail["question_count"] == 2
    assert detail["plan_count"] == 1
    assert detail["avg_mastery"] == pytest.approx(50, abs=2)
    assert detail["suggestion"]


def test_recommend_for_chapter_with_prerequisites(session):
    _question_with_kp(session, "一元一次方程")
    _question_with_kp(session, "一元一次方程")
    _question_with_kp(session, "等式性质")
    # “等式性质”是“一元一次方程”的前置
    n1 = KnowledgeNode(name="等式性质", importance=3)
    n2 = KnowledgeNode(name="一元一次方程", importance=5)
    session.add_all([n1, n2])
    session.flush()
    session.add(KnowledgeEdge(source_node_id=n1.id,
                              target_node_id=n2.id, relation_type="前置"))
    session.commit()

    recs = kgs.recommend_for_chapter(session, "数学", "解一元一次方程")
    top = recs[0]
    assert top["name"] == "一元一次方程"
    assert top["question_count"] == 2
    assert "等式性质" in top["prerequisites"]


def test_question_coverage_rows(session):
    _question_with_kp(session, "分数")
    _question_with_kp(session, "小数")
    session.commit()
    rows = kgs.coverage_rows(session, "数学", ["分数"])
    by_name = {r["name"]: r for r in rows}
    assert by_name["分数"]["covered"] is True
    assert by_name["小数"]["covered"] is False
    assert by_name["小数"]["question_count"] == 1


def test_student_rates_drilldown(session):
    from utils import knowledge_heatmap_service as khm
    hw = _make_class_with_pending_homework(session)  # 复用：3 名学生
    q = _question_with_kp(session, "分数")
    link = HomeworkQuestion(homework_id=hw.id, question_id=q.id, score=10)
    session.add(link)
    session.flush()
    stu = session.query(Student).filter(Student.name == "甲").first()
    session.add(HomeworkAnswer(homework_id=hw.id, question_id=q.id,
                               student_id=stu.id, earned_score=8))
    session.commit()
    rows = khm.student_rates_for(session, "一班", "分数")
    assert rows == [{"student": "甲", "rate": pytest.approx(0.8, abs=0.01)}]


# ---------------------------------------------------------------------------
# 功能5：甘特图与 AI 调整建议
# ---------------------------------------------------------------------------

def test_gantt_rows(session):
    plan = {
        "meta": {"subject": "数学", "grade": "初一", "semester": "2026秋"},
        "weekly_plan": [
            {"week_number": 1, "content": "有理数", "note": "新授"},
            {"week_number": 2, "content": "整式", "note": "新授"},
        ],
    }
    teaching_plan_service.save_planned_weeks(session, plan)
    row = teaching_plan_service.track_progress(
        session, "数学", "初一", "2026秋", 1, "有理数", "")
    row.actual_date = date.today()
    session.commit()

    rows = teaching_plan_service.gantt_rows(session, "数学", "初一", "2026秋")
    assert len(rows) == 2
    first = rows[0]
    assert first["planned_date"] and first["actual_date"] == date.today()


def test_ai_adjust_suggestions(session):
    session.add(TeachingProgress(
        subject="数学", grade="初一", semester="2026秋", week_number=1,
        chapter="有理数", status="lag"))
    session.commit()

    fake_chat = lambda sp, up: "建议合并两个课时，利用自习课补一节。"
    out = teaching_plan_service.ai_adjust_suggestions(
        session, "数学", "初一", "2026秋", chat_func=fake_chat)
    assert "合并" in out["suggestions"]

    # AI 不可用时规则兜底，也必须给得出建议
    out2 = teaching_plan_service.ai_adjust_suggestions(
        session, "数学", "初一", "2026秋", chat_func=None)
    assert out2["suggestions"]


# ---------------------------------------------------------------------------
# 页面冒烟：首页提醒中心、日历甘特图、备课推荐、出题覆盖率
# ---------------------------------------------------------------------------

def test_v330_pages_apptest(tmp_path):
    from streamlit.testing.v1 import AppTest
    from tests.test_app_smoke import _isolated_app_code
    at = AppTest.from_string(
        _isolated_app_code(tmp_path / "v330_app.db"),
        default_timeout=30)
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    # 首页含智能提醒中心
    at.run()
    # 教学日历：教学计划面板含甘特图与 AI 建议
    at.session_state["app_top_page"] = "📅 教学日历"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    # 备课与出题页新增面板不报错
    at.session_state["app_top_page"] = "📚 备课"
    at.session_state["lesson_plan_tab"] = "AI 备课"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    at.session_state["lesson_plan_tab"] = "AI 出题"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]