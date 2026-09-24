# -*- coding: utf-8 -*-
"""v1.7.0：章节单选和暂存后保留上下文测试。"""

import json
from pathlib import Path

from streamlit.testing.v1 import AppTest

ROWS_KEY = "question_task_editor_rows"
EDITOR_KEY = "question_task_editor"


def _isolated_app_code(patch_dir):
    import importlib.util

    smoke_path = Path(__file__).with_name("test_app_smoke.py")
    spec = importlib.util.spec_from_file_location("test_app_smoke", smoke_path)
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)

    db_file = patch_dir / "v170.db"
    code = smoke._isolated_app_code(
        db_file, patch_dir / "feature.json",
        question_tasks_file=patch_dir / "question_tasks.json",
        pending_groups_file=patch_dir / "pending_question_groups.json")
    return code, db_file


def _goto_question_tab(at):
    at.sidebar.radio[0].set_value("📚 备课").run()
    return at.tabs[2]


def _seed_material(db_file):
    """造一份带两个章节的临时资料。"""
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


def _editor_state(rows):
    return {
        "edited_rows": {str(i): dict(row) for i, row in enumerate(rows)},
        "added_rows": [],
        "deleted_rows": [],
    }


def _prepare_current_config(at, rows, chapter, kps, extra="结合生活"):
    import pandas

    material = _widget(at, "selectbox", "question_gen_material")
    if material.value != 1:
        material.set_value(1).run()
    chapter_box = _widget(at, "selectbox", "question_gen_chapter")
    if chapter_box.value != chapter:
        chapter_box.set_value(chapter).run()

    # 空题库没有知识点选项，新知识点通过“手动补充”进入多选状态。
    kp_box = _widget(at, "multiselect", "question_gen_kps")
    if set(kp_box.value) != set(kps):
        if kp_box.value:
            kp_box.set_value([]).run()
        _widget(at, "text_input", "question_gen_manual_kps").set_value(
            "、".join(kps)).run()

    _widget(at, "text_input", "question_gen_extra").set_value(extra).run()
    at.session_state[ROWS_KEY] = pandas.DataFrame(rows)
    at.run()


def _widget(at, kind, key):
    return next(item for item in getattr(at, kind) if item.key == key)


def _click_with_editor(at, button_key, rows):
    _widget(at, "button", button_key).click()
    at.session_state[EDITOR_KEY] = _editor_state(rows)
    at.run()


def _load_json(tmp_path, name):
    return json.loads((tmp_path / name).read_text(encoding="utf-8"))


def test_question_page_empty_renders_without_exception(tmp_path):
    code, _db = _isolated_app_code(tmp_path)
    at = AppTest.from_string(code, default_timeout=30)
    at.run()
    _goto_question_tab(at)
    chapter = _widget(at, "selectbox", "question_gen_chapter")
    assert chapter.label == "📖 参考章节（来自资料，单选）"
    assert chapter.value is None and chapter.options == ["不指定章节"]
    assert not at.exception


def test_chapter_single_select_options_and_no_old_multiselect(tmp_path):
    code, db_file = _isolated_app_code(tmp_path)
    _seed_material(db_file)
    at = AppTest.from_string(code, default_timeout=30)
    at.run()
    _goto_question_tab(at)

    _widget(at, "selectbox", "question_gen_material").set_value(1).run()

    chapter = _widget(at, "selectbox", "question_gen_chapter")
    assert chapter.options == [
        "不指定章节", "第一单元 混合运算", "第二单元 观察物体"]
    assert chapter.value is None
    assert "question_gen_chapters" not in at.session_state
    assert not any(
        "参考章节" in item.label and "可多选" in item.label
        for item in at.multiselect)
    assert not at.exception


def test_stash_clears_consumed_rows_but_keeps_context(tmp_path):
    code, db_file = _isolated_app_code(tmp_path)
    _seed_material(db_file)
    at = AppTest.from_string(code, default_timeout=30)
    at.run()
    _goto_question_tab(at)

    rows = [{"题型": "选择题", "难度": 2, "数量": 5, "删除": False}]
    chapter_title = "第一单元 混合运算"
    _prepare_current_config(at, rows, chapter_title, ["连减运算"])
    _click_with_editor(at, "stash_current_question_group", rows)

    assert not at.exception
    groups = _load_json(tmp_path, "pending_question_groups.json")
    assert groups[0]["chapters"] == [chapter_title]
    assert list(at.session_state[ROWS_KEY].to_dict("records")) == []
    assert _widget(at, "selectbox", "question_gen_material").value == 1
    assert _widget(at, "selectbox", "question_gen_chapter").value == chapter_title
    assert _widget(at, "multiselect", "question_gen_kps").value == ["连减运算"]
    assert _widget(at, "text_input", "question_gen_manual_kps").value == ""
    assert _widget(at, "text_input", "question_gen_extra").value == ""
    assert any(
        f"章节：{chapter_title}" in item.value for item in at.success)


def test_manual_chapter_change_binds_second_group(tmp_path):
    code, db_file = _isolated_app_code(tmp_path)
    _seed_material(db_file)
    at = AppTest.from_string(code, default_timeout=30)
    at.run()
    _goto_question_tab(at)

    first_rows = [{"题型": "选择题", "难度": 2, "数量": 5, "删除": False}]
    _prepare_current_config(
        at, first_rows, "第一单元 混合运算", ["连减运算"])
    _click_with_editor(at, "stash_current_question_group", first_rows)

    second_rows = [{"题型": "填空题", "难度": 1, "数量": 3, "删除": False}]
    _widget(at, "selectbox", "question_gen_chapter").set_value(
        "第二单元 观察物体").run()
    if _widget(at, "multiselect", "question_gen_kps").value:
        _widget(at, "multiselect", "question_gen_kps").set_value([]).run()
    _widget(at, "text_input", "question_gen_manual_kps").set_value(
        "观察方法").run()
    at.session_state[ROWS_KEY] = __import__("pandas").DataFrame(second_rows)
    at.run()
    _click_with_editor(at, "stash_current_question_group", second_rows)

    assert not at.exception
    groups = _load_json(tmp_path, "pending_question_groups.json")
    assert [item["chapters"][0] for item in groups] == [
        "第一单元 混合运算", "第二单元 观察物体"]
    assert groups[1]["knowledge_points"] == ["观察方法"]
    assert _widget(at, "selectbox", "question_gen_chapter").value == (
        "第二单元 观察物体")


def test_direct_add_task_keeps_context(tmp_path):
    code, db_file = _isolated_app_code(tmp_path)
    _seed_material(db_file)
    at = AppTest.from_string(code, default_timeout=30)
    at.run()
    _goto_question_tab(at)

    rows = [{"题型": "填空题", "难度": 1, "数量": 2, "删除": False}]
    chapter_title = "第一单元 混合运算"
    _prepare_current_config(at, rows, chapter_title, ["连减运算"])
    _click_with_editor(at, "add_current_question_tasks", rows)

    assert not at.exception
    tasks = _load_json(tmp_path, "question_tasks.json")
    assert len(tasks) == 1
    assert tasks[0]["chapters"] == [chapter_title]
    assert list(at.session_state[ROWS_KEY].to_dict("records")) == []
    assert _widget(at, "selectbox", "question_gen_material").value == 1
    assert _widget(at, "selectbox", "question_gen_chapter").value == chapter_title
    assert _widget(at, "multiselect", "question_gen_kps").value == ["连减运算"]
    assert _widget(at, "text_input", "question_gen_extra").value == ""


def test_subject_change_clears_material_chapter_and_kps(tmp_path):
    code, db_file = _isolated_app_code(tmp_path)
    _seed_material(db_file)
    at = AppTest.from_string(code, default_timeout=30)
    at.run()
    _goto_question_tab(at)

    rows = [{"题型": "选择题", "难度": 2, "数量": 1, "删除": False}]
    _prepare_current_config(
        at, rows, "第一单元 混合运算", ["连减运算"])

    _widget(at, "radio", "question_gen_subject").set_value("语文").run()
    assert not at.exception
    assert _widget(at, "selectbox", "question_gen_material").value is None
    assert _widget(at, "selectbox", "question_gen_chapter").value is None
    assert _widget(at, "multiselect", "question_gen_kps").value == []


def test_material_change_clears_chapter_and_kps(tmp_path):
    code, db_file = _isolated_app_code(tmp_path)
    _seed_material(db_file)
    at = AppTest.from_string(code, default_timeout=30)
    at.run()
    _goto_question_tab(at)

    rows = [{"题型": "选择题", "难度": 2, "数量": 1, "删除": False}]
    _prepare_current_config(
        at, rows, "第一单元 混合运算", ["连减运算"])

    _widget(at, "selectbox", "question_gen_material").select_index(0).run()
    assert not at.exception
    assert _widget(at, "selectbox", "question_gen_chapter").value is None
    assert _widget(at, "multiselect", "question_gen_kps").value == []
