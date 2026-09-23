# -*- coding: utf-8 -*-
"""v1.6.9：待定任务草稿组测试。"""

import json
from pathlib import Path

import pytest

from utils import question_service as qs


@pytest.fixture()
def pending_groups_path(tmp_path, monkeypatch):
    path = tmp_path / "pending_question_groups.json"
    monkeypatch.setattr(qs, "PENDING_GROUPS_PATH", path)
    return path


def _group(rows=None, subject="数学", grade="三年级", chapters=None, kps=None):
    return {
        "subject": subject,
        "grade": grade,
        "material_id": None,
        "chapters": chapters or ["第一单元 混合运算"],
        "knowledge_points": kps or ["连减运算"],
        "extra": "贴近生活",
        "rows": rows or [
            {"题型": "选择题", "难度": 2, "数量": 5},
            {"题型": "填空题", "难度": 1, "数量": 3},
        ],
    }


# ---------------------------------------------------------------------------
# 服务层
# ---------------------------------------------------------------------------

def test_pending_groups_missing_auto_create(pending_groups_path):
    assert qs.load_pending_question_groups() == []
    assert pending_groups_path.exists()


def test_pending_groups_save_chinese_not_escaped(pending_groups_path):
    qs.add_pending_question_group(_group())
    raw = pending_groups_path.read_text(encoding="utf-8")
    assert "第一单元 混合运算" in raw and "连减运算" in raw
    assert "\\u" not in raw

    groups = qs.load_pending_question_groups()
    assert groups[0]["group_id"] and groups[0]["created_at"]
    assert groups[0]["rows"][0]["question_type"] == "选择题"


def test_pending_groups_corrupt_file_falls_back_without_overwrite(
        pending_groups_path):
    pending_groups_path.write_text("{损坏", encoding="utf-8")
    assert qs.load_pending_question_groups() == []
    assert pending_groups_path.read_text(encoding="utf-8") == "{损坏"


def test_add_delete_and_clear_pending_groups(pending_groups_path):
    groups = qs.add_pending_question_group(_group())
    assert len(groups) == 1
    group_id = groups[0]["group_id"]

    groups = qs.add_pending_question_group(_group(
        rows=[{"题型": "应用题", "难度": 3, "数量": 2}],
        chapters=["第二单元 观察物体"],
        kps=["观察方法"]))
    assert len(groups) == 2

    remaining = qs.delete_pending_question_group(group_id)
    assert len(remaining) == 1
    assert remaining[0]["chapters"] == ["第二单元 观察物体"]

    assert qs.clear_pending_question_groups() == []
    assert qs.load_pending_question_groups() == []


def test_add_pending_group_rejects_duplicate_id(pending_groups_path):
    group = qs.normalize_pending_question_group(_group())
    qs.add_pending_question_group(group)
    with pytest.raises(ValueError, match="草稿组 ID 已存在"):
        qs.add_pending_question_group(group)


@pytest.mark.parametrize("field,value,match", [
    ("subject", "体育", "学科不合法"),
    ("grade", "大十二", "年级不合法"),
])
def test_normalize_pending_group_rejects_bad_basic_fields(
        pending_groups_path, field, value, match):
    data = _group()
    data[field] = value
    with pytest.raises(ValueError, match=match):
        qs.normalize_pending_question_group(data)


@pytest.mark.parametrize("rows,match", [
    ([], "至少要有一行题型"),
    ([{"题型": "火星题型", "难度": 1, "数量": 1}], "题型不符合"),
    ([{"题型": "选择题", "难度": 1, "数量": 0}], "数量必须大于 0"),
])
def test_normalize_pending_group_rejects_bad_rows(
        pending_groups_path, rows, match):
    data = _group()
    data["rows"] = rows
    with pytest.raises(ValueError, match=match):
        qs.normalize_pending_question_group(data)


def test_tasks_from_pending_groups_inherits_group_context(pending_groups_path):
    first = qs.normalize_pending_question_group(_group())
    second = qs.normalize_pending_question_group(_group(
        grade="初一",
        chapters=["第一章 有理数"],
        kps=["正负数"],
        rows=[{"题型": "选择题", "难度": 1, "数量": 2}]))

    tasks = qs.tasks_from_pending_groups([first, second])
    # 第一组 2 行 + 第二组 1 行，共 3 条任务
    assert len(tasks) == 3
    assert tasks[0]["chapters"] == ["第一单元 混合运算"]
    assert tasks[0]["knowledge_points"] == ["连减运算"]
    assert tasks[1]["question_type"] == "填空题"
    assert tasks[2]["grade"] == "初一"
    assert tasks[2]["chapters"] == ["第一章 有理数"]


# ---------------------------------------------------------------------------
# AppTest
# ---------------------------------------------------------------------------

from streamlit.testing.v1 import AppTest  # noqa: E402

ROWS_KEY = "question_task_editor_rows"
EDITOR_KEY = "question_task_editor"


def _isolated_app_code(patch_dir):
    import importlib.util

    smoke_path = Path(__file__).with_name("test_app_smoke.py")
    spec = importlib.util.spec_from_file_location("test_app_smoke", smoke_path)
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)

    db_file = patch_dir / "v169.db"
    code = smoke._isolated_app_code(
        db_file, patch_dir / "feature.json",
        question_tasks_file=patch_dir / "question_tasks.json",
        pending_groups_file=patch_dir / "pending_question_groups.json")
    return code, db_file


def _goto_question_tab(at):
    at.sidebar.radio[0].set_value("📚 备课").run()
    return at.tabs[2]


def _set_rows(at, rows):
    import pandas

    at.session_state[ROWS_KEY] = pandas.DataFrame(rows)
    at.run()


def _seed_material(db_file):
    """造一份带章节信息的临时资料，供 AI 出题选择章节。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from models.models import Base, Textbook

    eng = create_engine(f"sqlite:///{db_file.as_posix()}")
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    session.add(Textbook(
        id=1,
        name="三年级数学书",
        subject="数学",
        file_type="text",
        file_path=None,
        grade="三年级",
        chapter_info=json.dumps([
            {"title": "第一单元 混合运算", "length": 20},
            {"title": "第二单元 观察物体", "length": 20},
        ], ensure_ascii=False),
    ))
    session.commit()
    session.close()
    eng.dispose()


def _select_material_chapter(at, chapter, kps):
    """只写 session 状态，不单独 run；由后续 _set_rows 的 run 统一生效。"""
    at.session_state["question_gen_material"] = 1
    at.session_state["question_gen_chapters"] = [chapter]
    at.session_state["question_gen_kps"] = kps


def _editor_state(rows):
    edited = {str(index): dict(row) for index, row in enumerate(rows)}
    return {"edited_rows": edited, "added_rows": [], "deleted_rows": []}


def test_app_stash_current_question_group(tmp_path):
    code, db_file = _isolated_app_code(tmp_path)
    _seed_material(db_file)
    at = AppTest.from_string(code, default_timeout=30)
    at.run()
    _goto_question_tab(at)

    rows = [
        {"题型": "选择题", "难度": 2, "数量": 5, "删除": False},
        {"题型": "填空题", "难度": 1, "数量": 3, "删除": False},
    ]
    # 先写资料/章节状态，再通过 _set_rows 的 run 统一渲染。
    _select_material_chapter(
        at, "第一单元 混合运算", ["连减运算"])
    at.session_state[ROWS_KEY] = __import__("pandas").DataFrame(rows)
    at.run()

    next(b for b in at.button if b.key == "stash_current_question_group").click()
    at.session_state[EDITOR_KEY] = _editor_state(rows)
    at.run()
    assert not at.exception, [str(e) for e in at.exception]

    groups = json.loads(
        (tmp_path / "pending_question_groups.json").read_text(encoding="utf-8"))
    assert len(groups) == 1
    assert len(groups[0]["rows"]) == 2
    assert groups[0]["chapters"] == ["第一单元 混合运算"]

    # 暂存后当前题型表清空
    assert list(at.session_state[ROWS_KEY].to_dict("records")) == []


def test_app_multiple_pending_groups_and_add_all_to_tasks(tmp_path):
    code, db_file = _isolated_app_code(tmp_path)
    _seed_material(db_file)
    at = AppTest.from_string(code, default_timeout=30)
    at.run()
    _goto_question_tab(at)

    # 第一组：三年级，选择题 5 道
    import pandas as _pd
    first_rows = [{"题型": "选择题", "难度": 2, "数量": 5, "删除": False}]
    _select_material_chapter(
        at, "第一单元 混合运算", ["连减运算"])
    at.session_state[ROWS_KEY] = _pd.DataFrame(first_rows)
    at.run()
    next(b for b in at.button if b.key == "stash_current_question_group").click()
    at.session_state[EDITOR_KEY] = _editor_state(first_rows)
    at.run()
    assert not at.exception, [str(e) for e in at.exception]

    # 第二组：三年级，填空题 3 道
    second_rows = [{"题型": "填空题", "难度": 1, "数量": 3, "删除": False}]
    _select_material_chapter(
        at, "第二单元 观察物体", ["观察方法"])
    at.session_state[ROWS_KEY] = _pd.DataFrame(second_rows)
    at.run()
    next(b for b in at.button if b.key == "stash_current_question_group").click()
    at.session_state[EDITOR_KEY] = _editor_state(second_rows)
    at.run()
    assert not at.exception, [str(e) for e in at.exception]

    groups = json.loads(
        (tmp_path / "pending_question_groups.json").read_text(encoding="utf-8"))
    assert len(groups) == 2
    assert groups[0]["chapters"] == ["第一单元 混合运算"]
    assert groups[1]["chapters"] == ["第二单元 观察物体"]
    assert any("待定任务草稿箱（共 2 组）" in x.label for x in at.expander)

    # 全部加入任务栏
    next(b for b in at.button
         if b.key == "add_all_pending_groups_to_tasks").click().run()
    assert not at.exception, [str(e) for e in at.exception]

    tasks = json.loads(
        (tmp_path / "question_tasks.json").read_text(encoding="utf-8"))
    assert len(tasks) == 2
    assert tasks[0]["question_type"] == "选择题"
    assert tasks[0]["chapters"] == ["第一单元 混合运算"]
    assert tasks[1]["question_type"] == "填空题"
    assert tasks[1]["chapters"] == ["第二单元 观察物体"]

    groups = json.loads(
        (tmp_path / "pending_question_groups.json").read_text(encoding="utf-8"))
    assert groups == []


def test_app_question_page_empty_renders_without_exception(tmp_path):
    code, _db = _isolated_app_code(tmp_path)
    at = AppTest.from_string(code, default_timeout=30)
    at.run()
    _goto_question_tab(at)
    assert not at.exception, [str(e) for e in at.exception]
