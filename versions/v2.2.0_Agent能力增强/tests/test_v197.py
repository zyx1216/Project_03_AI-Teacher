# -*- coding: utf-8 -*-
"""v1.9.7 数据看板 + 智能批改 + API 接口测试。

全程临时 SQLite/JSON，不读真实 data、不请求真实 AI；
OCR 与 LLM 全部 monkeypatch。
"""

from __future__ import annotations

import json
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from streamlit.testing.v1 import AppTest

from models.models import (
    Base, GradingLog, HomeworkAnswer, HomeworkScore, Student)
from tests.test_app_smoke import _isolated_app_code, goto_top
from utils import api_key_service, db, grading_service, ocr_service
from utils import homework_service as hw_svc
from utils import question_service
from utils import llm_client


# ---------------------------------------------------------------------------
# 临时库 fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(
        api_key_service, "API_KEYS_PATH", tmp_path / "api_keys.json")
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'v197.db').as_posix()}")
    Base.metadata.create_all(engine)
    SL = sessionmaker(bind=engine)
    monkeypatch.setattr(db, "SessionLocal", SL)
    session = SL()
    yield {"session": session, "SL": SL, "engine": engine}
    session.close()
    engine.dispose()


def _seed_homework(session, *, answer="A", qtype="choice"):
    """造学生、题目、作业并关联题目。"""
    student = Student(name="张三", class_name="高一1班")
    session.add(student)
    data = {
        "content": "1+1=？", "question_type": qtype, "difficulty": 1,
        "knowledge_points": json.dumps(["有理数"], ensure_ascii=False),
        "answer": answer, "analysis": "", "error_points": "",
        "verify": None}
    q = question_service.create_question(
        session, data, source="manual", status="approved",
        subject="数学", grade="高一")
    hw = hw_svc.create_homework(
        session, "有理数作业", homework_type="after_class",
        subject="数学", grade="高一", class_name="高一1班",
        total_score=100)
    session.add_all([q, hw])
    session.flush()
    hw_svc.add_questions(session, hw.id, [q.id])
    session.flush()
    return student, q, hw


# ---------------------------------------------------------------------------
# 一、数据结构
# ---------------------------------------------------------------------------

def test_grading_log_table_exists(env):
    """新表存在，备份业务表清单含 grading_logs 且总数口径正确。"""
    from sqlalchemy import inspect
    names = inspect(env["engine"]).get_table_names()
    assert "grading_logs" in names
    from utils import backup_service
    assert "grading_logs" in backup_service.BUSINESS_TABLES
    assert len(backup_service.BUSINESS_TABLES) == 20


def test_api_key_create_verify_revoke(env):
    record = api_key_service.create_key("测试")
    assert record["plain_key"].startswith("mt-")
    assert api_key_service.verify_key(record["plain_key"])
    assert not api_key_service.verify_key("错误key")
    api_key_service.revoke_key(record["id"])
    assert not api_key_service.verify_key(record["plain_key"])


def test_api_key_corrupt_file(env, tmp_path, monkeypatch):
    path = tmp_path / "api_keys.json"
    path.write_text("{坏", encoding="utf-8")
    monkeypatch.setattr(api_key_service, "API_KEYS_PATH", path)
    assert api_key_service.load_keys() == {"keys": []}
    assert path.read_text(encoding="utf-8") == "{坏"  # 不覆盖


# ---------------------------------------------------------------------------
# 二、智能批改
# ---------------------------------------------------------------------------

def _patch_grading(monkeypatch, recognized, overall="整体表现不错。"):
    monkeypatch.setattr(ocr_service, "ocr_image",
                        lambda image_bytes: "1. A")

    def fake_chat(system, user, temperature=0.0):
        if "JSON 对象" in system:
            return json.dumps(recognized, ensure_ascii=False)
        return overall

    monkeypatch.setattr(llm_client, "chat_content", fake_chat)


def test_grade_objective_correct(env, monkeypatch):
    session = env["session"]
    student, q, hw = _seed_homework(session)
    session.commit()
    _patch_grading(monkeypatch, {"1": "A"})

    result = grading_service.grade_homework_image(
        [b"img"], hw.id, student.id, mode="all")
    assert result["total_score"] == 100
    item = result["items"][0]
    assert item["is_correct"] is True
    assert item["earned_score"] == 100
    assert result["ai_comment"]


def test_grade_objective_wrong(env, monkeypatch):
    session = env["session"]
    student, q, hw = _seed_homework(session)
    session.commit()
    _patch_grading(monkeypatch, {"1": "B"})

    result = grading_service.grade_homework_image(
        [b"img"], hw.id, student.id, mode="all")
    assert result["total_score"] == 0
    assert result["items"][0]["is_correct"] is False


def test_objective_only_mode_skips_subjective(env, monkeypatch):
    session = env["session"]
    student, q, hw = _seed_homework(session, qtype="solution")
    session.commit()
    # 主观题在 objective_only 下不应被批改（保持未判）。
    monkeypatch.setattr(ocr_service, "ocr_image", lambda b: "解：2")
    monkeypatch.setattr(
        llm_client, "chat_content",
        lambda s, u, temperature=0.0: json.dumps({"1": "解：2"}))

    result = grading_service.grade_homework_image(
        [b"img"], hw.id, student.id, mode="objective_only")
    item = result["items"][0]
    assert item["question_type"] == "solution"
    assert item["earned_score"] is None and item["is_correct"] is None


def test_confirm_grading_writes_rows(env, monkeypatch):
    session = env["session"]
    student, q, hw = _seed_homework(session)
    session.commit()
    _patch_grading(monkeypatch, {"1": "A"})

    result = grading_service.grade_homework_image(
        [b"img"], hw.id, student.id, mode="all")
    out = grading_service.confirm_grading(session, result)
    session.commit()

    answer = session.query(HomeworkAnswer).one()
    assert answer.is_correct is True and answer.earned_score == 100
    total = session.query(HomeworkScore).one()
    assert total.total_score == 100
    log = session.get(GradingLog, out["grading_log_id"])
    assert log.status == "confirmed" and log.student_id == student.id


# ---------------------------------------------------------------------------
# 三、数据看板
# ---------------------------------------------------------------------------

def test_board_empty_data(env):
    from utils import databoard_service
    data = databoard_service.board_data(env["session"])
    assert data["has_data"] is False
    assert data["metrics"]["student_count"] == 0


def test_board_metrics_and_bands(env):
    from utils import databoard_service
    from models.models import Exam
    from models.models import Score as ScoreModel
    session = env["session"]
    s1 = Student(name="甲", class_name="高一1班")
    s2 = Student(name="乙", class_name="高一1班")
    session.add_all([s1, s2])
    session.flush()
    exam = Exam(name="月考", exam_date=date.today())
    session.add(exam)
    session.flush()
    session.add_all([
        ScoreModel(exam_id=exam.id, student_id=s1.id,
                   subject="数学", score=90),
        ScoreModel(exam_id=exam.id, student_id=s2.id,
                   subject="数学", score=50)])
    session.commit()

    data = databoard_service.board_data(
        env["session"], subject="数学")
    m = data["metrics"]
    assert m["student_count"] == 2 and m["exam_count"] == 1
    assert m["average_rate"] == 70
    assert m["pass_rate"] == 50 and m["excellent_rate"] == 50
    bands = {b["band"]: b["count"] for b in data["score_bands"]}
    assert bands["优秀"] == 1 and bands["不及格"] == 1
    assert data["ranking"][0]["name"] == "甲"
    # 班级趋势里有一个均分点。
    assert data["class_trend"]["高一1班"][0]["average"] == 70


def test_board_class_filter(env):
    from utils import databoard_service
    from models.models import Exam
    from models.models import Score as ScoreModel
    session = env["session"]
    s1 = Student(name="甲", class_name="高一1班")
    s2 = Student(name="乙", class_name="高一2班")
    session.add_all([s1, s2])
    session.flush()
    exam = Exam(name="月考", exam_date=date.today())
    session.add(exam)
    session.flush()
    session.add_all([
        ScoreModel(exam_id=exam.id, student_id=s1.id,
                   subject="数学", score=90),
        ScoreModel(exam_id=exam.id, student_id=s2.id,
                   subject="数学", score=60)])
    session.commit()
    data = databoard_service.board_data(
        env["session"], class_names=["高一1班"], subject="数学")
    assert data["metrics"]["student_count"] == 1


# ---------------------------------------------------------------------------
# 四、FastAPI
# ---------------------------------------------------------------------------

@pytest.fixture()
def client(env):
    from fastapi.testclient import TestClient
    from api.main import app
    return TestClient(app)


def test_api_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_api_students_requires_key(client):
    assert client.get("/api/students").status_code == 401


def test_api_students_with_key(client, env):
    rec = api_key_service.create_key()
    headers = {"X-API-Key": rec["plain_key"]}
    session = env["session"]
    session.add(Student(name="李四", class_name="高一2班"))
    session.commit()

    r = client.get("/api/students", headers=headers)
    assert r.status_code == 200
    assert any(s["name"] == "李四" for s in r.json())

    # 新增学生。
    r = client.post("/api/students", headers=headers, json={
        "name": "王五", "class_name": "高一3班"})
    assert r.status_code == 200 and r.json()["created"] is True


def test_api_scores_post_and_list(client, env):
    rec = api_key_service.create_key()
    headers = {"X-API-Key": rec["plain_key"]}
    r = client.post("/api/scores", headers=headers, json={
        "student_name": "赵六", "class_name": "高一1班",
        "exam_name": "期中考试", "subject": "数学", "score": 88})
    assert r.status_code == 200
    r = client.get(
        "/api/scores?exam_name=期中考试&subject=数学", headers=headers)
    assert r.status_code == 200 and r.json()[0]["score"] == 88


def test_api_exam_analysis_404(client, env):
    rec = api_key_service.create_key()
    headers = {"X-API-Key": rec["plain_key"]}
    r = client.get(
        "/api/exams/analysis?exam_name=不存在", headers=headers)
    assert r.status_code == 404


def test_api_wrong_key_401(client):
    r = client.get("/api/students", headers={"X-API-Key": "mt-wrong"})
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# 五、AppTest
# ---------------------------------------------------------------------------

def _app(tmp_path, name):
    db_file = tmp_path / f"{name}.db"
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / f"{name}_feature.json"),
        default_timeout=30)
    at.run()
    return at, db_file


def test_app_databoard_empty(tmp_path):
    """空库：侧边栏有数据看板入口，进入后空态无异常。"""
    at, _ = _app(tmp_path, "databoard_empty")
    assert any(x.key == "nav_databoard" for x in at.button)
    goto_top(at, "📊 数据看板")
    assert not at.exception, [str(e) for e in at.exception]
    assert any("暂无成绩数据" in x.value for x in at.info)


def test_app_grading_dialog_opens(tmp_path):
    """作业管理：有作业时点批改能打开弹窗（不上传文件不触发真实识别）。"""
    at, db_file = _app(tmp_path, "grading_dialog")
    engine = create_engine(f"sqlite:///{db_file.as_posix()}")
    seed = sessionmaker(bind=engine)()
    stu = Student(name="张三", class_name="高一1班")
    seed.add(stu)
    seed.flush()
    from models.models import Homework
    hw = Homework(name="作业", homework_type="after_class",
                  subject="数学", grade="高一", class_name="高一1班",
                  total_score=100, status="pending")
    seed.add(hw)
    seed.commit()
    hw_id = hw.id
    seed.close()

    at.session_state["app_top_page"] = "📝 学业测评"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    next(x for x in at.button if x.key == f"grade_hw_{hw_id}").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    # 弹窗里出现学生选择与上传控件。
    assert any(f"grading_student_{hw_id}" in str(x.key)
               for x in at.selectbox)
    assert any(f"grading_files_{hw_id}" in str(x.key)
               for x in at.file_uploader)


def test_app_settings_api_panel(tmp_path):
    """设置页出现 API 访问面板且无异常。"""
    at, _ = _app(tmp_path, "settings_api")
    goto_top(at, "⚙️ 设置")
    assert not at.exception, [str(e) for e in at.exception]
    assert any(x.value == "🔑 API 访问" for x in at.subheader)
    assert any(x.key == "api_create_key" for x in at.button)


def test_app_submit_entry_unaffected(tmp_path):
    db_file = tmp_path / "submit_v197.db"
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / "submit_feature.json"),
        default_timeout=30)
    at.query_params["page"] = "submit"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
