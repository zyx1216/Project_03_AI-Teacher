# -*- coding: utf-8 -*-
"""v1.6.4 AI 备课区优化测试。"""

import importlib.util
from pathlib import Path

import pytest

from streamlit.testing.v1 import AppTest

from utils import material_service as material


_SMOKE_PATH = Path(__file__).with_name("test_app_smoke.py")
_SPEC = importlib.util.spec_from_file_location("test_app_smoke", _SMOKE_PATH)
_SMOKE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_SMOKE)
_isolated_app_code = _SMOKE._isolated_app_code


# ---------------------------------------------------------------------------
# PDF / 教材章节切分
# ---------------------------------------------------------------------------

def test_unit_heading_merges_next_line_title():
    text = (
        "第一单元\n"
        "混合运算\n"
        "小熊购物\n"
        "第一单元正文。\n"
        "第二单元\n"
        "观察物体\n"
        "第二单元正文。"
    )
    chapters = material.split_chapters(text)
    titles = [c["title"] for c in chapters]

    assert "第一单元 混合运算" in titles
    assert "第二单元 观察物体" in titles
    first = next(c for c in chapters if c["title"] == "第一单元 混合运算")
    second = next(c for c in chapters if c["title"] == "第二单元 观察物体")
    assert "混合运算" not in first["content"]
    assert "小熊购物" in first["content"]
    assert "第一单元正文" in first["content"]
    assert "观察物体" not in second["content"]
    assert "第二单元正文" in second["content"]


@pytest.mark.parametrize("title", [
    "整理与复习", "总复习", "综合实践", "练一练",
])
def test_special_headings_recognized(title):
    assert material.is_chapter_heading(title)
    chapters = material.split_chapters(f"{title}\n对应内容。")
    assert any(c["title"] == title for c in chapters)


def test_unnumbered_lesson_titles_not_recognized():
    text = "第一单元 混合运算\n小熊购物\n买文具\n正文内容。"
    chapters = material.split_chapters(text)
    titles = [c["title"] for c in chapters]

    assert titles == ["第一单元 混合运算"]
    assert "小熊购物" in chapters[0]["content"]
    assert "买文具" in chapters[0]["content"]




def test_math_fun_heading_not_recognized_as_general_title():
    assert not material.is_chapter_heading("数学好玩")
    chapters = material.split_chapters("数学好玩\n对应内容。")
    assert not any(c["title"] == "数学好玩" for c in chapters)


@pytest.mark.parametrize("title", ["复习", "练习"])
def test_generic_review_and_exercise_not_recognized(title):
    assert not material.is_chapter_heading(title)


def test_unit_heading_followed_by_heading_not_swallowed():
    text = "第一单元\n整理与复习\n复习内容。"
    chapters = material.split_chapters(text)
    titles = [c["title"] for c in chapters]

    assert "第一单元" in titles
    assert "整理与复习" in titles
    review = next(c for c in chapters if c["title"] == "整理与复习")
    assert "复习内容" in review["content"]


# ---------------------------------------------------------------------------
# AppTest：AI 备课布局
# ---------------------------------------------------------------------------

def test_lesson_tab_single_chapter_picker_empty_db(tmp_path):
    db_file = tmp_path / "lesson_v164.db"
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / "feature.json"),
        default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📚 备课").run()

    assert not at.exception, [str(e) for e in at.exception]
    picker = next(x for x in at.multiselect if x.key == "lesson_chapter_select")
    assert picker.label == "选择章节（可搜索）"
    assert "输入关键词可搜索" in picker.help
    assert all(x.label != "章节筛选（从资料章节选）" for x in at.multiselect)
    assert all(x.label != "章节（可手动修改）" for x in at.text_input)
    assert any("📝 备课参数" in str(x.value) for x in at.markdown)
    assert any(x.key == "lesson_template_select" for x in at.selectbox)


def test_lesson_tab_with_material_has_no_exception(tmp_path):
    db_file = tmp_path / "lesson_v164_material.db"
    text_dir = tmp_path / "material_text"
    text_dir.mkdir(parents=True, exist_ok=True)

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from models.models import Base, Textbook

    eng = create_engine(f"sqlite:///{db_file.as_posix()}")
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    tb = Textbook(
        name="北师大数学教材", file_type="pdf",
        subject="数学", grade="八年级")
    session.add(tb)
    session.commit()
    (text_dir / f"{tb.id}.txt").write_text(
        "第一单元\n混合运算\n小熊购物\n正文内容。",
        encoding="utf-8")
    eng.dispose()

    at = AppTest.from_string(
        _isolated_app_code(
            db_file, tmp_path / "feature.json", text_dir=text_dir),
        default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📚 备课").run()
    next(x for x in at.selectbox if x.key == "lesson_material_select").set_value(tb.id).run()

    assert not at.exception, [str(e) for e in at.exception]
    picker = next(x for x in at.multiselect if x.key == "lesson_chapter_select")
    assert "第一单元 混合运算" in picker.options


