# -*- coding: utf-8 -*-
"""v2.1.0 功能深化批次2测试。

覆盖：客观题重批、主观题 AI 批改、抄袭检测、完成度分析、个性化作业、
资料 ZIP、板书生成、文本课堂实录和 AppTest 无异常路径。
"""

from __future__ import annotations

import io
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models.models import (
    Base, Homework, HomeworkAnswer, HomeworkQuestion, HomeworkScore,
    HomeworkSubmission, Question, Student, Textbook)
from utils import (
    blackboard_service, class_recording_service, grading_service,
    homework_analysis_service, material_service, personalized_homework_service,
    plagiarism_service, subjective_grading_service)


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------


@pytest.fixture()
def session(tmp_path, monkeypatch):
    db_path = tmp_path / "v210.db"
    engine = create_engine(
        f"sqlite:///{db_path.as_posix()}", future=True)
    Base.metadata.create_all(engine)
    sess = sessionmaker(bind=engine, future=True)()

    # 测试期间资料文件仍写到临时 data 子目录，避免碰真实上传目录。
    upload_dir = tmp_path / "uploads"
    monkeypatch.setattr("config.UPLOAD_DIR", upload_dir)
    monkeypatch.setattr(material_service, "ORIGINAL_DIR",
                        upload_dir / "original")
    monkeypatch.setattr(material_service, "STATIC_ORIGINAL_DIR",
                        upload_dir / "static_original")
    yield sess
    sess.close()
    engine.dispose()


def _question(session, *, qid_content="题目", qtype="choice",
              difficulty=1, answer="A", kps=None):
    question = Question(
        content=qid_content, question_type=qtype, difficulty=difficulty,
        answer=answer,
        knowledge_points=json.dumps(kps or ["知识点"], ensure_ascii=False),
        analysis="解析", subject="数学", grade="八年级",
        source="manual", status="approved")
    session.add(question)
    session.flush()
    return question


def _homework(session, *, class_name="一班", due=False):
    homework = Homework(
        name="测试作业", homework_type="after_class",
        class_name=class_name, total_score=100, subject="数学",
        grade="八年级", status="pending",
        due_date=datetime.now() + timedelta(days=1) if due else None)
    session.add(homework)
    session.flush()
    return homework


def _link(session, homework, question, order, score=None):
    link = HomeworkQuestion(
        homework_id=homework.id, question_id=question.id,
        order=order, score=score)
    session.add(link)
    session.flush()
    return link


def _student(session, name="张三", class_name="一班"):
    student = Student(name=name, class_name=class_name)
    session.add(student)
    session.flush()
    return student


# ---------------------------------------------------------------------------
# 客观题重批
# ---------------------------------------------------------------------------


def test_objective_question_grading():
    question = Question(question_type="choice", answer="A")
    assert grading_service.grade_objective_question(question, " a ")["correct"]
    assert not grading_service.grade_objective_question(question, "B")["correct"]

    fill = Question(question_type="fill", answer="北京；北平")
    assert grading_service.grade_objective_question(fill, " 北平 ")["correct"]


def test_batch_regrade_objective_skips_feedback_and_force(session):
    homework = _homework(session)
    question = _question(session)
    _link(session, homework, question, 1)
    first = HomeworkSubmission(
        homework_id=homework.id, student_name="张三",
        answers_json=json.dumps({"1": "A"}), score=0, feedback="已人工批改")
    second = HomeworkSubmission(
        homework_id=homework.id, student_name="李四",
        answers_json=json.dumps({"1": "B"}), score=100)
    session.add_all([first, second])
    session.flush()

    result = grading_service.grade_homework_objective(
        session, homework.id)
    assert result["updated"] == 1
    assert result["skipped"] == 1
    assert second.score == 0
    assert first.score == 0

    result = grading_service.grade_homework_objective(
        session, homework.id, force=True)
    assert result["updated"] == 2
    assert first.score == 100


# ---------------------------------------------------------------------------
# 主观题批改
# ---------------------------------------------------------------------------


def test_subjective_question_grading(monkeypatch):
    question = Question(content="解答题", answer="参考答案")

    def fake_chat(system, user, temperature=0):
        return json.dumps({
            "score": 8,
            "feedback": "步骤基本完整",
            "key_points_missed": ["结论说明"],
        }, ensure_ascii=False)

    monkeypatch.setattr(
        "utils.llm_client.chat_content", fake_chat)
    result = subjective_grading_service.grade_subjective_question(
        question, "学生作答", 10)
    assert result["score"] == 8
    assert result["percent"] == 80
    assert result["key_points_missed"] == ["结论说明"]


def test_subjective_empty_answer_and_bad_json(monkeypatch):
    question = Question(content="解答题", answer="参考答案")
    result = subjective_grading_service.grade_subjective_question(
        question, "", 10)
    assert result["score"] == 0

    monkeypatch.setattr(
        "utils.llm_client.chat_content",
        lambda *args, **kwargs: "不是 JSON")
    with pytest.raises(ValueError, match="无法解析"):
        subjective_grading_service.grade_subjective_question(
            question, "学生答案", 10)


def test_batch_subjective_records_bad_item_as_ungraded(session, monkeypatch):
    homework = _homework(session)
    question = _question(session, qid_content="解答题", qtype="solution",
                         answer="参考答案", difficulty=2)
    _link(session, homework, question, 1)
    submission = HomeworkSubmission(
        homework_id=homework.id, student_name="张三",
        answers_json=json.dumps({"1": "学生答案"}), score=0)
    session.add(submission)
    session.flush()
    monkeypatch.setattr(
        "utils.llm_client.chat_content",
        lambda *args, **kwargs: "坏 JSON")

    payload = subjective_grading_service.batch_grade_subjective(
        session, homework.id, question.id)
    assert payload["results"][0]["score"] is None
    assert "无法解析" in payload["results"][0]["feedback"]


# ---------------------------------------------------------------------------
# 抄袭检测
# ---------------------------------------------------------------------------


def test_plagiarism_detects_similar_answers():
    base = "这是一份很长的学生解答，内容包括第一步分析和第二步计算过程以及最终结论"
    almost = "这是一份很长的学生解答，内容包括第一步分析和第二步计算过程以及最终结轮。"
    payload = plagiarism_service.detect_plagiarism([
        {"student_name": "甲", "answer": base},
        {"student_name": "乙", "answer": almost},
    ])
    assert payload["pairs"]
    assert payload["pairs"][0]["similarity"] > 0.8


def test_plagiarism_ignores_short_different_answers():
    payload = plagiarism_service.detect_plagiarism([
        {"student_name": "甲", "answer": "A"},
        {"student_name": "乙", "answer": "B"},
    ])
    assert payload["pairs"] == []
    assert "未发现" in payload["report"]


# ---------------------------------------------------------------------------
# 完成度分析
# ---------------------------------------------------------------------------


def test_completion_analysis_with_due_date(session):
    homework = _homework(session, due=True)
    student = _student(session)
    question = _question(session)
    _link(session, homework, question, 1, score=10)
    submission = HomeworkSubmission(
        homework_id=homework.id, student_name=student.name,
        answers_json=json.dumps({"1": "A"}), score=100,
        submitted_at=datetime.now() - timedelta(minutes=30))
    score = HomeworkScore(
        homework_id=homework.id, student_id=student.id,
        total_score=100, submitted=True)
    answer = HomeworkAnswer(
        homework_id=homework.id, student_id=student.id,
        question_id=question.id, order_no=1,
        earned_score=10, is_correct=True)
    session.add_all([submission, score, answer])
    session.flush()

    data = homework_analysis_service.analyze_homework_completion(
        session, homework.id)
    assert data["submission_rate"] == 1
    assert data["on_time_rate"] == 1
    assert data["average_minutes_before_due"] > 0
    assert data["questions"][0]["correct_rate"] == 1
    assert data["questions"][0]["inferred_difficulty"] == "基础"


def test_completion_analysis_without_due_date(session):
    homework = _homework(session)
    data = homework_analysis_service.analyze_homework_completion(
        session, homework.id)
    assert data["submission_rate"] is None
    assert data["on_time_rate"] is None
    assert data["average_minutes_before_due"] is None


# ---------------------------------------------------------------------------
# 个性化作业
# ---------------------------------------------------------------------------


def test_personalized_homework_uses_weak_points(session):
    student = _student(session)
    question = _question(session, kps=["函数概念"])
    base_homework = _homework(session)
    _link(session, base_homework, question, 1)
    session.add(HomeworkAnswer(
        homework_id=base_homework.id, student_id=student.id,
        question_id=question.id, order_no=1,
        earned_score=0, is_correct=False))
    session.flush()

    result = personalized_homework_service.generate_personalized_homework(
        session, student.id, "数学", count=1)
    assert result["homework_id"]
    assert result["knowledge_points"] == ["函数概念"]
    assert result["total_questions"] == 1


def test_personalized_homework_requires_real_data(session):
    student = _student(session)
    with pytest.raises(ValueError, match="逐题作答数据不足"):
        personalized_homework_service.generate_personalized_homework(
            session, student.id, "数学")


# ---------------------------------------------------------------------------
# 资料 ZIP
# ---------------------------------------------------------------------------


def _text_material(session, tmp_path, name="文本资料"):
    textbook = Textbook(
        name=name, file_type="text", subject="数学",
        grade="八年级", vectorized=False)
    session.add(textbook)
    session.flush()
    text_dir = tmp_path / "uploads" / "text"
    text_dir.mkdir(parents=True, exist_ok=True)
    (text_dir / f"{textbook.id}.txt").write_text("这是资料正文", encoding="utf-8")
    return textbook


def test_material_zip_export_import(tmp_path, session):
    textbook = _text_material(session, tmp_path)
    package = material_service.export_materials_zip(
        session, [textbook.id])
    assert b"manifest.json" in package

    new_db = tmp_path / "new.db"
    engine = create_engine(f"sqlite:///{new_db.as_posix()}", future=True)
    Base.metadata.create_all(engine)
    new_session = sessionmaker(bind=engine)()
    result = material_service.import_materials_zip(new_session, package)
    new_session.commit()
    assert len(result["imported"]) == 1
    imported = new_session.query(Textbook).one()
    assert imported.name == "文本资料"
    new_session.close()
    engine.dispose()


# ---------------------------------------------------------------------------
# 板书
# ---------------------------------------------------------------------------


def test_blackboard_generate_and_png(monkeypatch):
    def fake_chat(system, user, temperature=0):
        return json.dumps({
            "title": "测试课",
            "sections": [{"title": "知识框架", "items": ["概念", "公式"]}],
            "summary": "完成小结",
        }, ensure_ascii=False)

    monkeypatch.setattr(
        "utils.llm_client.chat_content", fake_chat)
    design = blackboard_service.generate_blackboard_design(
        {"title": "测试课"}, style="structured")
    assert design["sections"][0]["items"] == ["概念", "公式"]
    png = blackboard_service.export_blackboard_png(design)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")


def test_blackboard_fallback_without_ai(monkeypatch):
    monkeypatch.setattr(
        "utils.llm_client.chat_content",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("AI 不可用")))
    plan = {
        "title": "测试课",
        "objectives": {"knowledge": "理解概念"},
        "process": [{"stage": "新授", "content": "讲解定义"}],
        "difficult_points": "公式应用",
    }
    design = blackboard_service.generate_blackboard_design(plan)
    text = blackboard_service.render_blackboard_text(design)
    assert "测试课" in text and "公式应用" in text


# ---------------------------------------------------------------------------
# 课堂实录
# ---------------------------------------------------------------------------


def test_recording_save_load_delete(tmp_path, monkeypatch):
    path = tmp_path / "class_records.json"
    monkeypatch.setattr(class_recording_service, "RECORDING_PATH", path)
    record = class_recording_service.save_recording({
        "title": "第一节",
        "transcript": "课堂逐字稿",
        "summary": {"summary": "课堂摘要"},
    })
    assert class_recording_service.load_recordings()["records"][0]["id"] == record["id"]
    class_recording_service.delete_recording(record["id"])
    assert class_recording_service.load_recordings()["records"] == []


def test_recording_summarize_with_llm(monkeypatch):
    monkeypatch.setattr(
        "utils.llm_client.chat_content",
        lambda *args, **kwargs: json.dumps({
            "summary": "完成教学",
            "key_points": ["知识点"],
            "interaction": "互动充分",
            "highlights": ["提问有效"],
            "problems": [],
            "suggestions": ["继续巩固"],
        }, ensure_ascii=False))
    summary = class_recording_service.summarize_transcript("逐字稿")
    assert summary["summary"] == "完成教学"
    assert summary["ai_available"] is True


def test_recording_corrupt_json_returns_default_without_overwrite(
        tmp_path, monkeypatch):
    path = tmp_path / "bad.json"
    path.write_text("{bad", encoding="utf-8")
    monkeypatch.setattr(class_recording_service, "RECORDING_PATH", path)
    assert class_recording_service.load_recordings() == {"records": []}
    assert path.read_text(encoding="utf-8") == "{bad"


# ---------------------------------------------------------------------------
# AppTest
# ---------------------------------------------------------------------------


def _feature_file(path):
    path.write_text(
        json.dumps({
            "materials_subject": "数学",
            "lesson_plan_subject": "数学",
            "question_gen_subject": "数学",
            "question_bank_subject": "数学",
            "homework_list_subject": "数学",
            "homework_analysis_subject": "数学",
            "wrong_book_subject": "数学",
        }, ensure_ascii=False),
        encoding="utf-8")


def test_v210_app_empty_paths(tmp_path):
    from streamlit.testing.v1 import AppTest
    from tests.test_app_smoke import _isolated_app_code, goto_sub

    db_file = tmp_path / "empty-v210.db"
    engine = create_engine(f"sqlite:///{db_file.as_posix()}", future=True)
    Base.metadata.create_all(engine)
    feature = tmp_path / "feature.json"
    _feature_file(feature)

    at = AppTest.from_string(
        _isolated_app_code(db_file, feature,
                           class_records_file=tmp_path / "records.json"),
        default_timeout=30)
    at.run()
    assert not at.exception

    goto_sub(at, "lesson_plan_tab", "资料管理", "📚 备课")
    assert not at.exception
    goto_sub(at, "lesson_plan_tab", "🎙️ 课堂实录", "📚 备课")
    assert "本版只支持文本逐字稿" in " ".join(
        str(x.value) for x in at.caption)
    assert not at.exception

    goto_sub(at, "homework_tab", "作业管理", "📝 学业测评")
    assert not at.exception
    engine.dispose()


def test_v210_app_data_paths(tmp_path):
    from streamlit.testing.v1 import AppTest
    from tests.test_app_smoke import _isolated_app_code, goto_sub

    db_file = tmp_path / "data-v210.db"
    engine = create_engine(f"sqlite:///{db_file.as_posix()}", future=True)
    Base.metadata.create_all(engine)
    sess = sessionmaker(bind=engine)()

    student = Student(name="张三", class_name="一班")
    sess.add(student)
    sess.flush()
    homework = Homework(
        name="App作业", homework_type="after_class", class_name="一班",
        total_score=100, subject="数学", grade="八年级", status="pending")
    sess.add(homework)
    sess.flush()
    choice = Question(
        content="选择题", question_type="choice", difficulty=1,
        answer="A", knowledge_points='["函数"]', subject="数学",
        grade="八年级", status="approved")
    solution = Question(
        content="解答题", question_type="solution", difficulty=2,
        answer="参考答案", knowledge_points='["函数"]', subject="数学",
        grade="八年级", status="approved")
    sess.add_all([choice, solution])
    sess.flush()
    sess.add_all([
        HomeworkQuestion(homework_id=homework.id, question_id=choice.id,
                         order=1, score=50),
        HomeworkQuestion(homework_id=homework.id, question_id=solution.id,
                         order=2, score=50),
        HomeworkSubmission(
            homework_id=homework.id, student_name="张三",
            answers_json=json.dumps({"1": "B", "2": "学生解答"}),
            score=0),
        HomeworkScore(homework_id=homework.id, student_id=student.id,
                      total_score=0, submitted=True),
        HomeworkAnswer(homework_id=homework.id, student_id=student.id,
                       question_id=choice.id, order_no=1,
                       earned_score=0, is_correct=False),
    ])
    app_homework_id = int(homework.id)
    sess.commit()
    sess.close()

    feature = tmp_path / "feature.json"
    _feature_file(feature)
    at = AppTest.from_string(
        _isolated_app_code(db_file, feature,
                           original_dir=tmp_path / "original",
                           static_original_dir=tmp_path / "static",
                           text_dir=tmp_path / "text",
                           class_records_file=tmp_path / "records.json"),
        default_timeout=30)
    at.run()
    goto_sub(at, "homework_tab", "作业管理", "📝 学业测评")
    next(b for b in at.button
         if b.key == f"auto_grade_objective_{app_homework_id}").click().run()
    assert not at.exception
    next(b for b in at.button
         if b.key == f"plagiarism_run_{app_homework_id}").click().run()
    assert not at.exception

    goto_sub(at, "homework_tab", "作业分析", "📝 学业测评")
    assert not at.exception
    assert any("完成度分析" in str(x.label) for x in at.expander)

    goto_sub(at, "lesson_plan_tab", "🎙️ 课堂实录", "📚 备课")
    assert not at.exception
    engine.dispose()
