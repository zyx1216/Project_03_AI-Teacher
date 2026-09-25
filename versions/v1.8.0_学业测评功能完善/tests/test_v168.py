# -*- coding: utf-8 -*-
"""v1.6.8 出题 Bug 修复与题库年级筛选测试。"""

import io
import json

import pandas
import pytest

from utils import question_service as qs
from utils import db as db_module
from utils.app_config import DISPLAY_GRADE_CHOICES


def _data(content="题干", answer="答案", qtype="solution", difficulty=2):
    return {"content": content, "question_type": qtype, "difficulty": difficulty,
            "knowledge_points": "[]", "answer": answer, "analysis": "",
            "error_points": "", "verify": None}


# ---------------------------------------------------------------------------
# 服务层：年级入库与筛选
# ---------------------------------------------------------------------------

def test_create_question_with_grade(session):
    q = qs.create_question(session, _data(), grade="初一")
    session.commit()
    assert q.grade == "初一"
    assert qs.list_questions(session)[0].grade == "初一"


def test_create_question_grade_defaults_none(session):
    q = qs.create_question(session, _data())
    session.commit()
    assert q.grade is None


def test_list_questions_filter_by_grade(session):
    qs.create_question(session, _data("三年级题", "甲"), grade="三年级")
    qs.create_question(session, _data("初一题", "乙"), grade="初一")
    qs.create_question(session, _data("历史题", "丙"))  # grade 为空
    session.commit()

    assert [q.content for q in qs.list_questions(session, grade="三年级")] == ["三年级题"]
    assert [q.content for q in qs.list_questions(session, grade="初一")] == ["初一题"]
    # grade=None 返回全部（含历史空年级题）
    assert len(qs.list_questions(session)) == 3


# ---------------------------------------------------------------------------
# 迁移：轻量补列
# ---------------------------------------------------------------------------

def test_pending_columns_contains_grade():
    grades = [name for name, _type in db_module._PENDING_COLUMNS["questions"]]
    assert "grade" in grades


def test_add_missing_columns_idempotent(tmp_path, monkeypatch):
    from sqlalchemy import create_engine, text

    db_file = tmp_path / "old.db"
    eng = create_engine(f"sqlite:///{db_file.as_posix()}")
    with eng.begin() as conn:
        conn.execute(text(
            "CREATE TABLE questions (id INTEGER PRIMARY KEY, content TEXT, "
            "question_type TEXT, difficulty INTEGER, answer TEXT, subject TEXT)"))
    monkeypatch.setattr(db_module, "engine", eng)

    db_module._add_missing_columns()
    with eng.connect() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(questions)"))]
    assert "grade" in cols

    # 重复执行不报错，列仍只有一个
    db_module._add_missing_columns()
    with eng.connect() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(questions)"))]
    assert cols.count("grade") == 1
    eng.dispose()


# ---------------------------------------------------------------------------
# AppTest
# ---------------------------------------------------------------------------

from streamlit.testing.v1 import AppTest  # noqa: E402

ROWS_KEY = "question_task_editor_rows"
EDITOR_KEY = "question_task_editor"


def _isolated_app_code(patch_dir):
    import importlib.util
    from pathlib import Path

    smoke_path = Path(__file__).with_name("test_app_smoke.py")
    spec = importlib.util.spec_from_file_location("test_app_smoke", smoke_path)
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)

    db_file = patch_dir / "v168.db"
    code = smoke._isolated_app_code(db_file, patch_dir / "feature.json")
    return code, db_file


def _patch_aggrid(monkeypatch):
    """题库有数据时给一个不勾选的假 AgGrid，避免组件返回 None 干扰。"""
    import modules.lesson_plan as lesson_plan

    def fake_aggrid(_df, gridOptions=None, key=None, **kwargs):
        return {"data": _df, "selected_rows": pandas.DataFrame()}

    monkeypatch.setattr(lesson_plan, "AgGrid", fake_aggrid)


def _goto_tab(at, index):
    at.sidebar.radio[0].set_value("📚 备课").run()
    return at.tabs[index]


def _editor_state(edited):
    return {"edited_rows": edited, "added_rows": [], "deleted_rows": []}


def test_bug1_add_row_keeps_previous_count(tmp_path, monkeypatch):
    code, _db = _isolated_app_code(tmp_path)
    at = AppTest.from_string(code, default_timeout=30)
    at.run()
    _goto_tab(at, 2)

    # 先放一行到当前配置表
    at.session_state[ROWS_KEY] = pandas.DataFrame(
        [{"题型": "选择题", "难度": 2, "数量": 1, "删除": False}])
    at.run()

    # 注入编辑器编辑态：第 0 行数量改成 5。
    # AppTest 不会把裸字典同步到已挂 data_editor，但“添加一行”的业务路径会读取它。
    editor_state = _editor_state({"0": {"数量": 5}})
    at.session_state[EDITOR_KEY] = editor_state

    # 点“添加一行”；click 后、run 前补一次编辑态（重挂编辑器会清状态）
    next(b for b in at.button if b.key == "add_question_row").click()
    at.session_state[EDITOR_KEY] = editor_state
    at.run()
    assert not at.exception, [str(e) for e in at.exception]

    rows = at.session_state[ROWS_KEY]
    assert len(rows) == 2
    assert int(rows.iloc[0]["数量"]) == 5  # 旧行数量保留
    assert int(rows.iloc[1]["数量"]) == 1  # 新行默认 1


def test_bug2_multiple_rows_all_added(tmp_path, monkeypatch):
    code, _db = _isolated_app_code(tmp_path)
    at = AppTest.from_string(code, default_timeout=30)
    at.run()
    _goto_tab(at, 2)

    # 三年级数学允许选择题、填空题、应用题，不允许“解答题”这个展示名。
    grade_box = next(x for x in at.selectbox if x.key == "question_gen_grade")
    grade_box.set_value("三年级").run()

    # 当前配置表放 3 行有效任务
    at.session_state[ROWS_KEY] = pandas.DataFrame([
        {"题型": "选择题", "难度": 1, "数量": 2, "删除": False},
        {"题型": "填空题", "难度": 2, "数量": 3, "删除": False},
        {"题型": "应用题", "难度": 3, "数量": 1, "删除": False},
    ])
    at.run()

    next(b for b in at.button
         if b.key == "add_current_question_tasks").click()
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    assert any("已添加 3 条任务到任务栏" in str(x.value) for x in at.success)

    tasks = json.loads((tmp_path / "question_tasks.json").read_text(encoding="utf-8"))
    assert len(tasks) == 3  # 修复前只有 1 条


def test_question_bank_grade_filter_apptest(tmp_path, monkeypatch):
    code, db_file = _isolated_app_code(tmp_path)
    _patch_aggrid(monkeypatch)

    # 造 2 题：一题初一，一题无年级（历史题）
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from models.models import Base

    eng = create_engine(f"sqlite:///{db_file.as_posix()}")
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    qs.create_question(session, _data("初一题", "乙"), grade="初一")
    qs.create_question(session, _data("历史题", "丙"))
    session.commit()
    session.close()

    at = AppTest.from_string(code, default_timeout=30)
    at.run()
    _goto_tab(at, 3)
    assert not at.exception, [str(e) for e in at.exception]

    grade_box = next(x for x in at.selectbox if x.key == "question_bank_grade")
    assert grade_box.options == ["全部年级"] + DISPLAY_GRADE_CHOICES

    # 默认全部年级：两题都在
    captions = " ".join(str(x.value) for x in at.caption)
    assert "共 2 道题" in captions

    # 选初一：只剩初一题，历史题隐藏
    grade_box.set_value("初一").run()
    assert not at.exception, [str(e) for e in at.exception]
    assert "共 1 道题" in " ".join(str(x.value) for x in at.caption)
    eng.dispose()


def test_question_bank_empty_apptest(tmp_path, monkeypatch):
    code, _db = _isolated_app_code(tmp_path)
    at = AppTest.from_string(code, default_timeout=30)
    at.run()
    _goto_tab(at, 3)
    assert not at.exception, [str(e) for e in at.exception]
    # 空库也显示年级下拉
    assert any(x.key == "question_bank_grade" for x in at.selectbox)
