# -*- coding: utf-8 -*-
"""v1.7.4 Homework 年级字段与 AI 年级传递测试。"""

from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from models.models import Homework
from modules import homework as homework_mod
from utils import app_config
from utils import db
from utils import homework_service as hw_svc
from utils import llm_client
from utils import question_service as qs


# ---------------------------------------------------------------------------
# 年级映射
# ---------------------------------------------------------------------------

def test_high_school_grade_mapping():
    assert app_config.to_storage_grade("高一") == "十年级"
    assert app_config.to_storage_grade("高二") == "十一年级"
    assert app_config.to_storage_grade("高三") == "十二年级"
    assert app_config.to_display_grade("十年级") == "高一"
    assert app_config.to_display_grade("十一年级") == "高二"
    assert app_config.to_display_grade("十二年级") == "高三"


def test_primary_junior_and_unspecified_grade_mapping_unchanged():
    assert app_config.to_storage_grade("三年级") == "三年级"
    assert app_config.to_display_grade("一年级") == "一年级"
    assert app_config.to_storage_grade("初一") == "七年级"
    assert app_config.to_display_grade("八年级") == "初二"
    assert app_config.to_storage_grade("未指定") == "未指定"
    assert app_config.to_display_grade("未指定") == "未指定"
    assert app_config.to_display_grade(None) == ""
    assert app_config.to_storage_grade(None) == ""


def test_grade_names_and_validation_cover_twelve_grades():
    assert len(app_config.GRADE_NAMES) == 12
    assert app_config.GRADE_NAMES[-3:] == ["十年级", "十一年级", "十二年级"]
    for grade in app_config.GRADE_NAMES + ["未指定"]:
        assert app_config.is_valid_grade(grade)
    assert not app_config.is_valid_grade("十三年级")


def test_high_school_question_type_options_use_storage_grade():
    options = qs.question_type_options("十一年级", "数学")
    assert "多项选择题" in options
    assert "看拼音写词语" not in options


# ---------------------------------------------------------------------------
# Homework 服务
# ---------------------------------------------------------------------------

def test_create_homework_saves_grade(session):
    homework = hw_svc.create_homework(session, "初二作业", grade="八年级")
    session.commit()
    stored = session.get(Homework, homework.id)
    assert stored.grade == "八年级"


def test_create_homework_default_grade_is_none(session):
    homework = hw_svc.create_homework(session, "历史作业")
    session.commit()
    assert session.get(Homework, homework.id).grade is None


def test_save_as_template_copies_grade(session):
    homework = hw_svc.create_homework(session, "高二作业", grade="十一年级")
    template = hw_svc.save_as_template(session, homework.id)
    session.commit()
    assert template.grade == "十一年级"


# ---------------------------------------------------------------------------
# 轻量补列迁移
# ---------------------------------------------------------------------------

def test_pending_columns_contains_homework_grade():
    assert ("grade", "VARCHAR(20)") in db._PENDING_COLUMNS["homeworks"]


def test_add_missing_columns_for_legacy_homeworks(tmp_path, monkeypatch):
    db_file = tmp_path / "legacy.db"
    eng = create_engine(f"sqlite:///{db_file.as_posix()}")
    with eng.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE homeworks ("
            "id INTEGER PRIMARY KEY, name TEXT, homework_type TEXT, "
            "class_name TEXT, total_score FLOAT, duration INTEGER, "
            "remark TEXT, is_template BOOLEAN, subject TEXT, created_at TEXT)"
        )
    monkeypatch.setattr(db, "engine", eng)

    db._add_missing_columns()
    columns = {col["name"] for col in inspect(eng).get_columns("homeworks")}
    assert "grade" in columns

    # 幂等：已有列时重复执行不报错。
    db._add_missing_columns()
    eng.dispose()


# ---------------------------------------------------------------------------
# AI 请求年级
# ---------------------------------------------------------------------------

def test_smart_compose_converts_storage_grade_before_ai(session, monkeypatch):
    captured = {}

    def fake_chat(system, user, temperature=0.8):
        captured["user"] = user
        return '''[
            {
                "content": "高中函数题",
                "question_type": "choice",
                "difficulty": 1,
                "knowledge_points": ["函数"],
                "answer": "A"
            }
        ]'''

    monkeypatch.setattr(llm_client, "chat_content", fake_chat)
    homework = hw_svc.create_homework(session, "高中补缺", grade="十一年级")
    result = hw_svc.auto_compose(
        session, homework.id,
        {"counts": {"choice": 1}, "difficulty_ratio": {1: 100, 2: 0, 3: 0}},
        ["函数"],
        ai_context={"textbook_id": None, "chapters": [], "grade": "十一年级"})

    assert "年级：高二" in captured["user"]
    assert result["ai_generated"] == 1
    assert result["shortage_count"] == 0


class _FakeStreamlit:
    @contextmanager
    def spinner(self, text):
        yield

    def success(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        raise AssertionError(args)

    def rerun(self):
        pass


def test_ai_instant_question_request_contains_display_grade(session, monkeypatch):
    captured = {}

    def fake_chat(system, user, temperature=0.8):
        captured["user"] = user
        return '''[
            {
                "content": "高中选择题",
                "question_type": "choice",
                "difficulty": 2,
                "knowledge_points": ["概率"],
                "answer": "B"
            }
        ]'''

    monkeypatch.setattr(homework_mod.llm_client, "chat_content", fake_chat)
    monkeypatch.setattr(homework_mod, "st", _FakeStreamlit())
    homework = hw_svc.create_homework(session, "AI即时出题", grade="十一年级")
    homework_mod._generate_and_add(
        session, homework, "概率", ["choice"], 2, 1)

    assert "学科：数学" in captured["user"]
    assert "年级：高二" in captured["user"]
    pairs = hw_svc.homework_questions(session, homework.id)
    assert len(pairs) == 1


# ---------------------------------------------------------------------------
# AppTest
# ---------------------------------------------------------------------------

def _apptest(db_file: Path, tmp_path: Path):
    from streamlit.testing.v1 import AppTest
    from tests import test_app_smoke as smoke

    return AppTest.from_string(
        smoke._isolated_app_code(db_file, tmp_path / "feature.json"),
        default_timeout=30)


def test_create_high_school_homework_isolated(tmp_path):
    db_file = tmp_path / "high_school.db"
    at = _apptest(db_file, tmp_path)
    at.run()
    at.sidebar.radio[0].set_value("📝 学业测评").run()
    assert not at.exception

    next(b for b in at.button if b.label == "➕ 新建作业 / 试卷").click().run()
    grade_box = next(x for x in at.selectbox if x.key == "hw_new_grade")
    grade_box.set_value("高二").run()
    next(x for x in at.text_input if x.label == "作业名称 *").input("高二作业").run()
    next(b for b in at.button if b.label == "创建").click().run()
    assert not at.exception, [str(e) for e in at.exception]

    eng = create_engine(f"sqlite:///{db_file.as_posix()}")
    db_session = sessionmaker(bind=eng)()
    homework = db_session.query(Homework).one()
    assert homework.name == "高二作业"
    assert homework.grade == "十一年级"
    db_session.close()
    eng.dispose()

    page_text = " ".join(str(x.value) for x in at.markdown)
    assert "高二作业" in page_text
    assert "未指定" in page_text or "高二" in page_text


def test_historical_null_grade_homework_displays_unspecified_isolated(tmp_path):
    from tests import test_app_smoke as smoke

    db_file = tmp_path / "null_grade.db"
    eng = smoke._seed_homework_data_db(db_file)
    at = _apptest(db_file, tmp_path)
    at.run()
    at.sidebar.radio[0].set_value("📝 学业测评").run()
    assert not at.exception

    list_subject = next(
        item for item in at.selectbox if item.key == "homework_list_subject")
    list_subject.set_value("物理").run()
    assert not at.exception
    page_text = " ".join(str(x.value) for x in at.markdown)
    assert "冒烟临时作业" in page_text
    assert "未指定" in page_text
    eng.dispose()
