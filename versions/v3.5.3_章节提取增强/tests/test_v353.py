# -*- coding: utf-8 -*-
"""v3.5.3 章节提取增强测试。"""
from __future__ import annotations

import pytest

from models.models import Base
from utils import material_service as mat


def _by_title(chapters):
    return {c["title"]: c for c in chapters}


LANGUAGE_TEXT = """第一单元

1 大青树下的小学

早晨，从山坡上，从坪坝里，从一条条开着绒球花和太阳花的小路上，走来了许多小学生。

2 花的学校

当雷云在天上轰响，六月的阵雨落下的时候，花从地里跑出来。

口语交际

我的暑假生活

习作

猜猜他是谁

语文园地

词句段运用。
"""

MATH_TEXT = """第一单元 混合运算

1 小熊购物

面包每个3元，饼干每包4元。

2 买文具

先算乘除，再算加减。

练习一

计算下面各题。
"""


# ---------------------------------------------------------------------------
# 语文 / 数学教材结构
# ---------------------------------------------------------------------------

def test_language_textbook_lessons_and_columns():
    chapters = mat.split_chapters(LANGUAGE_TEXT)
    got = _by_title(chapters)
    # 空的一级标题不单列，单元名体现在子节的 display_title 里
    assert "第一单元" not in got
    assert got["1 大青树下的小学"]["level"] == 2
    assert got["1 大青树下的小学"]["display_title"] == \
        "第一单元 > 1 大青树下的小学"
    assert got["2 花的学校"]["display_title"] == "第一单元 > 2 花的学校"
    for column in ("口语交际", "习作", "语文园地"):
        assert got[column]["level"] == 2
        assert got[column]["parent"] == "第一单元"
        assert got[column]["content"]
    assert mat.chapter_titles(chapters, hierarchical=True) == [
        "第一单元 > 1 大青树下的小学", "第一单元 > 2 花的学校",
        "第一单元 > 口语交际", "第一单元 > 习作", "第一单元 > 语文园地"]


def test_math_textbook_unit_lessons_and_practice():
    chapters = mat.split_chapters(MATH_TEXT)
    got = _by_title(chapters)
    assert got["1 小熊购物"]["level"] == 2
    assert got["1 小熊购物"]["parent"] == "第一单元 混合运算"
    assert got["1 小熊购物"]["display_title"] == \
        "第一单元 混合运算 > 1 小熊购物"
    assert got["2 买文具"]["level"] == 2
    assert got["练习一"]["level"] == 2
    assert got["练习一"]["parent"] == "第一单元 混合运算"
    assert "先算乘除" in got["2 买文具"]["content"]
    assert "计算下面各题" in got["练习一"]["content"]


# ---------------------------------------------------------------------------
# 固定栏目
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("title", [
    "口语交际", "习作例文", "习作", "语文园地", "综合性学习", "写字", "识字",
    "数学好玩", "营养午餐", "练习一", "练习二十", "练习10",
])
def test_fixed_columns_recognized(title):
    assert mat.is_chapter_heading(title)


@pytest.mark.parametrize("title", [
    "复习", "练习", "数学乐园", "这是普通的一句话",
])
def test_generic_short_titles_still_not_recognized(title):
    assert not mat.is_chapter_heading(title)


def test_spaced_column_title_is_normalized():
    """PDF 里"习\u2003 作"这种带空格的栏目名要归一成"习作"。"""
    chapters = mat.split_chapters("第一单元\n\n习\u2003 作\n\n正文内容。")
    assert [c["title"] for c in chapters] == ["习作"]


# ---------------------------------------------------------------------------
# 数字开头的课文标题 + 防误判
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("title", [
    "1 大青树下的小学", "1. 小熊购物", "2\u3000花的学校", "12 总也倒不了的老屋",
])
def test_numbered_lesson_titles_recognized(title):
    assert mat.is_numbered_lesson_title(title)
    assert mat.is_chapter_heading(title)


@pytest.mark.parametrize("line", [
    "1.说一说",              # 点号后没有空格：习题编号
    "1.先算乘除法",
    "20 - 2 × 7",            # 算式
    "18.9 - 16.8",           # X.X 后面是算式，不是"1.2 数轴"那种标题
    "1.2 3+2=5",
    "3 ，在竹林中吹着风笛",     # 正文里的句中标点
    "1 山坡 学校 飘扬 课文",   # 词表
    "1 这是一行很长的正文内容用来测试标题长度上限不应该被当成课文标题哦",
])
def test_body_numbers_not_lesson_titles(line):
    assert not mat.is_numbered_lesson_title(line)
    assert not mat.is_chapter_heading(line)


def test_numbered_title_must_stand_alone():
    """正文里紧挨着文字的"1 先算乘除法"不算章节（防误判优先）。"""
    text = "第一单元 混合运算\n\n1 小熊购物\n\n正文段落。\n1 先算乘除法\n正文继续。"
    chapters = mat.split_chapters(text)
    assert [c["title"] for c in chapters] == ["1 小熊购物"]
    assert "1 先算乘除法" in chapters[0]["content"]


# ---------------------------------------------------------------------------
# 层级与去重
# ---------------------------------------------------------------------------

def test_duplicate_columns_get_index_suffix():
    text = "第一单元\n\n口语交际\n\n内容甲。\n\n口语交际\n\n内容乙。"
    chapters = mat.split_chapters(text)
    assert [c["display_title"] for c in chapters] == [
        "第一单元 > 口语交际", "第一单元 > 口语交际（2）"]
    assert chapters[0]["content"] != chapters[1]["content"]


def test_unit_name_merge_ignores_page_number():
    """单独成行的"第四单元"不会再和后面的页码合成"第四单元 41"。"""
    chapters = mat.split_chapters("第四单元\n41\n正文内容。")
    assert [c["title"] for c in chapters] == ["第四单元"]


def test_empty_trailing_column_dropped():
    text = "第一单元\n\n1 大青树下的小学\n\n正文。\n\n语文园地"
    chapters = mat.split_chapters(text)
    assert "语文园地" not in [c["title"] for c in chapters]


def test_version_and_tables():
    import config
    assert config.APP_VERSION == "3.5.3"
    assert len(Base.metadata.tables) == 38
