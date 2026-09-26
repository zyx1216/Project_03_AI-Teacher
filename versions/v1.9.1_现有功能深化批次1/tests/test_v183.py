# -*- coding: utf-8 -*-
"""v1.8.3 中低优先级功能完善测试。"""
from __future__ import annotations

import io
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from models.models import Base, Homework, LessonPlan, Question, Student
from streamlit.testing.v1 import AppTest
from utils import (
    backup_service,
    dashboard_service as dash_svc,
    homework_score_service as hscore,
    homework_service as hw_svc,
    knowledge_heatmap_service,
    lesson_service,
    question_importer as qi,
    question_service,
    score_doc_parser,
)
from utils import homework_submit_service as submit_svc
from tests.test_app_smoke import _isolated_app_code


# ---------------------------------------------------------------------------
# 数据模型和补列
# ---------------------------------------------------------------------------

def test_new_tables_and_submit_code_pending_column():
    from models.models import HomeworkSubmission, LessonPlanVersion, QuestionEditLog

    assert HomeworkSubmission.__tablename__ == "homework_submissions"
    assert LessonPlanVersion.__tablename__ == "lesson_plan_versions"
    assert QuestionEditLog.__tablename__ == "question_edit_logs"
    from utils.db import _PENDING_COLUMNS

    assert ("submit_code", "VARCHAR(10)") in _PENDING_COLUMNS["homeworks"]


def test_old_homework_table_adds_submit_code_idempotent(tmp_path, monkeypatch):
    db_file = tmp_path / "old.db"
    eng = create_engine(f"sqlite:///{db_file.as_posix()}")
    with eng.begin() as conn:
        conn.execute(text("CREATE TABLE homeworks (id INTEGER PRIMARY KEY, name TEXT)"))
    from utils import db

    monkeypatch.setattr(db, "engine", eng)
    db._add_missing_columns()
    db._add_missing_columns()
    columns = [c["name"] for c in inspect(eng).get_columns("homeworks")]
    assert "submit_code" in columns


# ---------------------------------------------------------------------------
# 备份增强
# ---------------------------------------------------------------------------

def _backup_data_dir(root: Path) -> Path:
    data = root / "data"
    (data / "uploads").mkdir(parents=True)
    (data / "database.db").write_bytes(b"db")
    (data / "uploads" / "a.txt").write_text("资料", encoding="utf-8")
    return data


def test_auto_backup_stats_and_prune(tmp_path):
    data_dir = _backup_data_dir(tmp_path)
    path = backup_service.auto_backup_if_needed(data_dir)
    assert path is not None and path.exists()
    assert backup_service.auto_backup_if_needed(data_dir) is None

    old_dir = data_dir / "backups" / "old"
    old_dir.mkdir()
    old_zip = old_dir / "backup_old.zip"
    old_zip.write_bytes(b"old")
    old_time = (datetime.now() - timedelta(days=10)).timestamp()
    import os

    os.utime(old_zip, (old_time, old_time))
    backup_service.prune_old_backups(data_dir, keep_days=7)
    assert not old_zip.exists()

    stats = backup_service.backup_stats(data_dir)
    assert stats["db_size"] > 0
    assert stats["material_count"] == 1
    assert stats["last_backup"] is not None


def test_pre_restore_backup_created(tmp_path):
    data_dir = _backup_data_dir(tmp_path)
    path = backup_service.create_pre_restore_backup(data_dir)
    assert "恢复前备份" in path.name and path.exists()


# ---------------------------------------------------------------------------
# 首页四区
# ---------------------------------------------------------------------------

def test_dashboard_four_area_counts_and_weekly_progress(session):
    session.add(Student(name="学生甲"))
    data = question_service.validate_question({
        "content": "题目甲", "answer": "A", "question_type": "choice",
        "difficulty": 1, "knowledge_points": []})
    question_service.create_question(session, data, subject="数学")
    session.add(LessonPlan(title="教案甲", content="{}"))
    hw_svc.create_homework(session, "作业甲", subject="数学")
    session.flush()

    result = dash_svc.dashboard_data(session, date.today())
    assert result["student_count"] == 1
    assert result["question_count"] == 1
    assert result["plan_count"] == 1
    assert result["homework_count"] == 1
    assert "today" in result and "weekly_progress" in result


# ---------------------------------------------------------------------------
# 教案版本和题目修改记录
# ---------------------------------------------------------------------------

def _plan_content(title: str) -> dict:
    return {
        "subject": "数学",
        "objectives": {"knowledge": title, "process": "", "emotion": ""},
        "key_points": title,
        "difficult_points": "",
        "process": [{"stage": "导入", "minutes": 5, "content": title}],
        "board_design": "",
        "reflection": "",
    }


def test_lesson_versions_limit_and_rollback(session):
    plan = lesson_service.save_plan(
        session, "课题", _plan_content("第1版"), subject="数学")
    for i in range(2, 8):
        lesson_service.save_plan(
            session, "课题", _plan_content(f"第{i}版"),
            plan_id=plan.id, subject="数学")
    versions = lesson_service.list_plan_versions(session, plan.id)
    assert len(versions) == 5
    assert versions[0].content_json
    oldest = versions[-1]

    restored = lesson_service.rollback_plan_version(
        session, plan.id, oldest.id)
    current = lesson_service.load_plan(restored)
    assert current["key_points"] == json.loads(oldest.content_json)["key_points"]


def test_question_edit_logs_single_and_batch(session):
    data = question_service.validate_question({
        "content": "原题", "answer": "A", "difficulty": 1,
        "knowledge_points": ["旧知识点"]})
    q = question_service.create_question(session, data, subject="数学")
    question_service.log_question_edit(
        session, q.id, "difficulty", 1, 2)

    question_service.batch_update_questions(
        session, [q.id], subject="物理", grade="高一",
        add_knowledge_points=["新知识点"])
    logs = question_service.list_question_edit_logs(session, q.id)
    fields = {log.field for log in logs}
    assert {"difficulty", "subject", "grade", "knowledge_points"} <= fields


# ---------------------------------------------------------------------------
# 在线提交
# ---------------------------------------------------------------------------

def _homework_for_submit(session) -> Homework:
    items = [
        ("选择题", "choice", "A", ["选择"]),
        ("判断题", "judge", "正确", ["判断"]),
        ("解答题", "solution", "过程", ["解答"]),
    ]
    hw = hw_svc.create_homework(session, "提交作业", subject="数学")
    for i, (_, qtype, answer, kps) in enumerate(items, start=1):
        data = question_service.validate_question({
            "content": f"第{i}题", "answer": answer,
            "question_type": qtype, "difficulty": 1,
            "knowledge_points": kps})
        q = question_service.create_question(session, data, subject="数学")
        hw_svc.add_questions(session, hw.id, [q.id])
    session.flush()
    return hw


def test_question_import_failure_report(session):
    result = qi.import_records(session, [{
        "row_no": 2, "content": "", "answer": "",
        "problems": ["缺题干", "缺答案"]}], subject="数学")
    assert result["imported"] == 0
    assert result["rejected"] == 1
    assert result["failures"][0]["失败原因"] == "缺题干、缺答案"

def test_submit_code_qr_submission_and_auto_grade(session):
    hw = _homework_for_submit(session)
    code = submit_svc.ensure_submit_code(session, hw.id)
    assert len(code) == 6 and hw.submit_code == code

    png = submit_svc.build_submit_qr_png(f"http://localhost:8501/?code={code}")
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert submit_svc.get_homework_by_code(session, code).id == hw.id

    submission = submit_svc.save_submission(
        session, code, "学生甲",
        {"1": "A", "2": "错误", "3": "答案内容"})
    assert submission.student_name == "学生甲"
    # 两道客观题只答对一道。
    assert submission.score == pytest.approx(1 / 2 * 100)
    assert submit_svc.submission_stats(session, hw.id)["submitted_count"] == 1


# ---------------------------------------------------------------------------
# 热力图和纯文本成绩
# ---------------------------------------------------------------------------

def test_knowledge_heatmap_matrix(session):
    student = Student(name="热力学生", class_name="一班")
    session.add(student)
    hw = hw_svc.create_homework(session, "热力作业", subject="数学", class_name="一班")
    data = question_service.validate_question({
        "content": "热力题", "answer": "A", "question_type": "choice",
        "difficulty": 1, "knowledge_points": ["热力知识点"]})
    q = question_service.create_question(session, data, subject="数学")
    hw_svc.add_questions(session, hw.id, [q.id], default_score=10)
    session.flush()
    hscore.save_answer(session, hw.id, q.id, student.id, 1, earned_score=8)

    result = knowledge_heatmap_service.build_heatmap(
        session, subject="数学", class_names=["一班"])
    assert result["x"] == ["一班"]
    assert "热力知识点" in result["y"]
    assert result["z"][0][0] == pytest.approx(0.8)
    assert result["details"]


def test_txt_score_parser_comma_tab_space():
    comma = "姓名,分数\n张三,90\n李四,80"
    df = score_doc_parser.txt_score_dataframe(comma)
    assert list(df["姓名"]) == ["张三", "李四"]

    tab = "姓名\t分数\n张三\t90"
    assert score_doc_parser.txt_score_dataframe(tab)["分数"].tolist() == ["90"]

    space = "姓名 分数\n张三 90"
    assert score_doc_parser.txt_score_dataframe(space)["分数"].tolist() == ["90"]

    with pytest.raises(ValueError, match="未找到"):
        score_doc_parser.txt_score_dataframe("没有表头和分数的普通文字")


# ---------------------------------------------------------------------------
# AppTest
# ---------------------------------------------------------------------------

def test_empty_app_no_exception(tmp_path):
    db_file = tmp_path / "empty.db"
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / "feature.json",
                           semester_file=tmp_path / "semester.json"),
        default_timeout=30)
    at.run()
    assert not at.exception


def test_submit_page_query_params(tmp_path):
    db_file = tmp_path / "submit.db"
    eng = create_engine(f"sqlite:///{db_file.as_posix()}")
    Base.metadata.create_all(eng)
    db_session = sessionmaker(bind=eng)()
    hw = _homework_for_submit(db_session)
    code = submit_svc.ensure_submit_code(db_session, hw.id)
    db_session.commit()
    db_session.close()

    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / "feature.json",
                           semester_file=tmp_path / "semester.json"),
        default_timeout=30)
    at.query_params["code"] = code
    at.run()
    assert not at.exception
    assert any("在线提交" in str(s.value) for s in at.subheader)


def test_dead_show_functions_removed():
    from modules import analysis, homework, lesson_plan

    assert not hasattr(analysis, "show")
    assert not hasattr(homework, "show")
    assert not hasattr(lesson_plan, "show")
