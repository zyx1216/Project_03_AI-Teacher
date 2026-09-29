# -*- coding: utf-8 -*-
"""v1.9.2 现有功能深化批次2测试。

覆盖：双向细目表、Word 附录、知识点掌握追踪、学生个人追踪和 AppTest 主流程。
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from streamlit.testing.v1 import AppTest

from models.models import (
    Base, Exam, Homework, HomeworkAnswer, HomeworkQuestion, Question,
    Score, Student,
)
from tests.test_app_smoke import _isolated_app_code, goto_sub
from utils import knowledge_graph_service as kgs
from utils import smart_compose_service as scs
from utils import question_service as qs
from utils import homework_service as hws


# ---------------------------------------------------------------------------
# 测试辅助
# ---------------------------------------------------------------------------


def _student(session, name="学生甲", class_name="一班"):
    row = Student(name=name, class_name=class_name)
    session.add(row)
    session.flush()
    return row


def _question(session, *, content="函数题目", qtype="choice", difficulty=1,
              kps=("函数",), grade="高一", status="approved",
              subject="数学"):
    row = Question(
        content=content, question_type=qtype, difficulty=difficulty,
        knowledge_points=json.dumps(list(kps), ensure_ascii=False),
        answer="A", analysis="解析", subject=subject, grade=grade,
        source="manual", status=status)
    session.add(row)
    session.flush()
    return row


def _homework(session, name, *, index=0, homework_type="after_class",
              class_name=None):
    completed_at = datetime(2026, 1, 1) + timedelta(days=index * 30)
    row = Homework(
        name=name, homework_type=homework_type, subject="数学",
        grade="高一", status="completed", completed_at=completed_at,
        created_at=completed_at, class_name=class_name)
    session.add(row)
    session.flush()
    return row


def _link(session, homework, question, score=10, order=1):
    row = HomeworkQuestion(
        homework_id=homework.id, question_id=question.id,
        order=order, score=score)
    session.add(row)
    session.flush()
    return row


def _answer(session, homework, question, student, rate, *, created_at=None):
    row = HomeworkAnswer(
        homework_id=homework.id, student_id=student.id,
        question_id=question.id, order_no=1,
        earned_score=round(rate * 10, 2), is_correct=rate >= 0.6,
        created_at=created_at or homework.completed_at)
    session.add(row)
    session.flush()
    return row


def _docx_text(data: bytes) -> str:
    """读取 Word 包内全部 XML 文本。"""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return "\n".join(
            archive.read(name).decode("utf-8", errors="ignore")
            for name in archive.namelist()
            if name.endswith(".xml"))


def _app(tmp_path):
    db_file = tmp_path / "app.db"
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / "feature.json"),
        default_timeout=30)
    return at, db_file


# ---------------------------------------------------------------------------
# 双向细目表
# ---------------------------------------------------------------------------


def test_specification_table_counts_and_split_scores(session):
    q1 = _question(session, kps=("函数", "方程"))
    q2 = _question(session, difficulty=2, kps=("方程",))

    spec = scs.build_specification_table(
        [q1, q2], {q1.id: 10, q2.id: 20})

    assert spec["knowledge_points"] == ["函数", "方程"]
    assert spec["cells"]["函数"]["1"] == {
        "count": 1, "score": 5.0, "question_ids": [q1.id]}
    assert spec["cells"]["方程"]["1"]["score"] == 5.0
    assert spec["cells"]["方程"]["2"] == {
        "count": 1, "score": 20.0, "question_ids": [q2.id]}
    assert spec["kp_totals"]["函数"] == {"count": 1, "score": 5.0}
    assert spec["kp_totals"]["方程"] == {"count": 2, "score": 25.0}
    assert spec["difficulty_totals"]["1"] == {"count": 1, "score": 10.0}
    assert spec["difficulty_totals"]["2"] == {"count": 1, "score": 20.0}
    assert spec["total"] == {"count": 2, "score": 30.0}


def test_specification_table_empty_and_unknown_knowledge(session):
    spec = scs.build_specification_table([], {})
    assert spec["knowledge_points"] == []
    assert spec["total"] == {"count": 0, "score": 0.0}

    question = _question(session, kps=())
    spec = scs.build_specification_table([question], {question.id: 10})
    assert spec["knowledge_points"] == ["未标注"]


def test_get_questions_by_cell(session):
    q1 = _question(session, kps=("函数",))
    q2 = _question(session, difficulty=2, kps=("函数",))

    assert scs.get_questions_by_cell([q1, q2], "函数", 1) == [q1]
    assert scs.get_questions_by_cell([q1, q2], "函数", 2) == [q2]
    assert scs.get_questions_by_cell([q1, q2], "方程", 1) == []


def test_word_append_specification_table(session):
    question = _question(session, kps=("函数", "方程"))
    spec = scs.build_specification_table([question], {question.id: 10})
    data = qs.export_questions_word(
        [question], False, title="测试卷", specification_table=spec)
    text = _docx_text(data)
    assert "双向细目表" in text


def test_homework_export_exam_auto_appends_specification(session):
    question = _question(session, kps=("函数",))
    exam = hws.create_homework(
        session, "正式试卷", homework_type="exam", subject="数学")
    hws.add_questions(session, exam.id, [question.id], default_score=10)

    exam_data = hws.export_word(session, exam.id, False)
    assert "双向细目表" in _docx_text(exam_data)

    homework = hws.create_homework(
        session, "普通作业", homework_type="after_class", subject="数学")
    hws.add_questions(session, homework.id, [question.id], default_score=10)
    homework_data = hws.export_word(session, homework.id, False)
    assert "双向细目表" not in _docx_text(homework_data)


def test_replace_question_keeps_order_and_score(session):
    old_question = _question(session, kps=("函数",))
    new_question = _question(session, content="替换题", kps=("函数",))
    homework = _homework(session, "作业")
    _link(session, homework, old_question, score=10)

    assert hws.replace_question(
        session, homework.id, old_question.id, new_question.id) is True
    links = session.query(HomeworkQuestion).filter(
        HomeworkQuestion.homework_id == homework.id).all()
    assert len(links) == 1
    assert links[0].question_id == new_question.id
    assert links[0].score == 10
    assert links[0].order == 1


# ---------------------------------------------------------------------------
# 知识点掌握追踪
# ---------------------------------------------------------------------------


def test_class_knowledge_trend_order_and_label(session):
    student = _student(session)
    question = _question(session, kps=("函数",))
    homeworks = []
    for index, rate in enumerate((1.0, 0.5, 0.8)):
        homework = _homework(session, f"作业{index}", index=index)
        _link(session, homework, question)
        _answer(session, homework, question, student, rate)
        homeworks.append(homework)

    result = kgs.get_knowledge_trend(session, "数学", ["函数"])
    assert [item["homework_id"] for item in result["events"]] == [
        homework.id for homework in homeworks]
    assert result["series"]["函数"] == pytest.approx([100, 50, 80])
    assert result["trends"]["函数"][0] == "下降"


def test_class_knowledge_trend_none_gap(session):
    student = _student(session)
    question = _question(session, kps=("函数",))

    hw1 = _homework(session, "第一次", index=0)
    hw2 = _homework(session, "第二次", index=1)
    hw3 = _homework(session, "第三次", index=2)
    for homework in (hw1, hw2, hw3):
        _link(session, homework, question)
    _answer(session, hw1, question, student, 1.0)
    _answer(session, hw3, question, student, 0.5)

    result = kgs.get_knowledge_trend(session, "数学", ["函数"])
    assert result["series"]["函数"] == pytest.approx([100, None, 50])
    assert result["trends"]["函数"][0] == "数据不足"


def test_student_knowledge_trend_with_class_average(session):
    student = _student(session)
    question = _question(session, kps=("函数",))
    for index, rate in enumerate((0.6, 0.8, 0.9)):
        homework = _homework(session, f"作业{index}", index=index)
        _link(session, homework, question)
        _answer(session, homework, question, student, rate)

    result = kgs.get_student_knowledge_trend(session, student.id, "数学")
    assert len(result["events"]) == 3
    assert result["student_series"]["函数"] == pytest.approx([60, 80, 90])
    assert result["class_series"]["函数"] == pytest.approx([60, 80, 90])
    assert "函数" in result["strengths"]
    assert result["weak_points"] == []


def test_class_filter_for_knowledge_trend(session):
    student = _student(session, class_name="一班")
    question = _question(session, kps=("函数",))
    homework = _homework(session, "一班作业", class_name="一班")
    _link(session, homework, question)
    _answer(session, homework, question, student, 0.8)

    one_class = kgs.get_knowledge_trend(
        session, "数学", ["函数"], ["一班"])
    assert len(one_class["events"]) == 1

    other_class = kgs.get_knowledge_trend(
        session, "数学", ["函数"], ["二班"])
    assert other_class["events"] == []


def test_exam_total_scores_not_split_to_knowledge(session):
    student = _student(session)
    exam = Exam(name="总分考试", exam_date=date(2026, 1, 1))
    session.add(exam)
    session.flush()
    session.add(Score(
        exam_id=exam.id, student_id=student.id,
        subject="数学", score=90))
    session.flush()

    assert "数学" not in kgs.list_trend_subjects(session)


def test_analyze_knowledge_trend_uses_llm(session, monkeypatch):
    student = _student(session)
    question = _question(session, kps=("函数",))
    homework = _homework(session, "作业")
    _link(session, homework, question)
    _answer(session, homework, question, student, 0.5)
    monkeypatch.setattr(
        kgs.llm_client, "chat_content",
        lambda *args, **kwargs: "建议：增加函数专项练习。")

    assert "函数专项" in kgs.analyze_knowledge_trend(
        "数学", ["函数"],
        kgs.get_knowledge_trend(session, "数学", ["函数"])["events"])


# ---------------------------------------------------------------------------
# AppTest
# ---------------------------------------------------------------------------


def test_apptest_smart_compose_config_empty(tmp_path):
    at, _db_file = _app(tmp_path)
    goto_sub(at, "homework_tab", "🤖 智能组卷", "📝 学业测评")

    assert at.exception == []
    assert any("细目表预览" in item.label for item in at.expander)


def test_apptest_knowledge_empty(tmp_path):
    at, _db_file = _app(tmp_path)
    goto_sub(at, "analysis_tab", "🧠 知识图谱", "📊 学情")

    assert at.exception == []
    assert any("知识点掌握追踪" in item.value for item in at.markdown)


def test_apptest_profile_empty(tmp_path):
    at, _db_file = _app(tmp_path)
    goto_sub(at, "analysis_tab", "学生画像", "📊 学情")

    assert at.exception == []


def test_apptest_class_and_personal_tracking_with_data(tmp_path):
    db_file = tmp_path / "with_data.db"
    engine = create_engine(f"sqlite:///{db_file.as_posix()}")
    Base.metadata.create_all(engine)
    seed_session = sessionmaker(bind=engine)()
    student = _student(seed_session)
    question = _question(seed_session, kps=("函数",))
    for index, rate in enumerate((0.6, 0.8, 0.9)):
        homework = _homework(seed_session, f"作业{index}", index=index)
        _link(seed_session, homework, question)
        _answer(seed_session, homework, question, student, rate)
    seed_session.commit()
    seed_session.close()

    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / "feature.json"),
        default_timeout=30)
    goto_sub(at, "analysis_tab", "🧠 知识图谱", "📊 学情")
    assert at.exception == []
    # AppTest 不把 st.plotly_chart 暴露成独立列表；无异常且出现趋势说明即可。
    assert any("知识点掌握追踪" in item.value for item in at.markdown)

    goto_sub(at, "analysis_tab", "学生画像", "📊 学情")
    assert at.exception == []
    assert any("个人知识点追踪" in item.value for item in at.markdown)


def test_apptest_smart_draft_specification_and_cell(tmp_path, monkeypatch):
    at, _db_file = _app(tmp_path)
    from modules import homework as homework_module

    def fake_auto_compose(session, homework_id, spec, knowledge_points,
                          ai_context=None):
        question = _question(session, kps=("函数",))
        homework_module.hw_svc.add_questions(
            session, homework_id, [question.id], default_score=10)
        return {
            "rule_picked": 1, "ai_generated": 0,
            "shortage_count": 0, "shortage": [],
            "coverage": {"covered": ["函数"], "missing": []},
            "total_questions": 1,
        }

    monkeypatch.setattr(
        homework_module.hw_svc, "auto_compose", fake_auto_compose)
    goto_sub(at, "homework_tab", "🤖 智能组卷", "📝 学业测评")

    run_button = next(
        item for item in at.button if item.key == "smart_compose_run")
    run_button.click().run()
    assert at.exception == []
    assert any("双向细目表" in item.value for item in at.markdown)

    cell_button = next(
        item for item in at.button if item.key == "spec_open_cell")
    cell_button.click().run()
    assert at.exception == []
