# -*- coding: utf-8 -*-
"""v1.6.6 PDF 目录识别优化测试。"""

import io
import json

import pymupdf
import pytest

from streamlit.testing.v1 import AppTest

from utils import material_service as material


def _make_toc_pdf() -> bytes:
    """构造“封面、目录、正文”结构的中文 PDF。"""
    doc = pymupdf.open()

    page = doc.new_page()
    page.insert_text((72, 72), "封面", fontname="china-s", fontsize=14)

    toc_lines = [
        "目录",
        "第一单元 混合运算 ...... 1",
        "第二单元 观察物体 ...... 2",
        "第三单元 加与减 ...... 3",
        "整理与复习 ...... 4",
    ]
    page = doc.new_page()
    y = 72
    for line in toc_lines:
        page.insert_text((60, y), line, fontname="china-s", fontsize=12)
        y += 26

    body_pages = [
        "第一单元 混合运算\n第一单元正文。",
        "第二单元 观察物体\n第二单元正文。",
        "第三单元 加与减\n第三单元正文。",
        "整理与复习\n复习正文。",
    ]
    # 目录占 PDF 第 2 页；印刷第 N 页对应 PDF 第 N+2 页，因此 offset=2。
    for text in body_pages:
        page = doc.new_page()
        page.insert_text((60, 80), text, fontname="china-s", fontsize=12)

    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


def test_extract_toc_by_regex_standard_lines():
    text = """
第一单元 混合运算 ...... 2
综合实践 记录我们的校园 ......... 24
总复习 …… 99
第一章 有理数 5
"""
    rows = material.extract_toc_by_regex(text)

    assert rows == [
        {"title": "第一单元 混合运算", "page": 2},
        {"title": "第一章 有理数", "page": 5},
        {"title": "综合实践 记录我们的校园", "page": 24},
        {"title": "总复习", "page": 99},
    ]


@pytest.mark.parametrize("line", [
    "第一单元 混合运算 ...... 0",
    "第一单元 混合运算",
    "第一单元 混合运算 ......",
    "普通正文没有页码",
])
def test_extract_toc_by_regex_rejects_invalid(line):
    assert material.extract_toc_by_regex(line) == []


def test_extract_toc_by_regex_sorts_and_deduplicates():
    text = """
第二章 整式 ...... 8
第一章 有理数 ...... 1
第一章 有理数 ...... 1
"""
    assert material.extract_toc_by_regex(text) == [
        {"title": "第一章 有理数", "page": 1},
        {"title": "第二章 整式", "page": 8},
    ]


def test_detect_page_offset_from_pdf():
    pdf_bytes = _make_toc_pdf()
    toc_pages = [
        {"title": "第一单元 混合运算", "page": 1},
        {"title": "第二单元 观察物体", "page": 2},
    ]

    assert material.detect_page_offset(pdf_bytes, toc_pages) == 2


def test_detect_page_offset_missing_title_returns_zero():
    pdf_bytes = _make_toc_pdf()
    assert material.detect_page_offset(
        pdf_bytes, [{"title": "不存在的章节", "page": 1}]) == 0
    assert material.detect_page_offset(pdf_bytes, []) == 0


def test_apply_page_offset_clamps_sorts_and_deduplicates():
    chapters = [
        {"title": "第三课", "level": 1, "page": 3},
        {"title": "第一课", "level": 1, "page": 1},
        {"title": "越界课", "level": 2, "page": 20},
        {"title": "第一课", "level": 1, "page": 1},
    ]

    rows = material.apply_page_offset(chapters, offset=2, page_count=6)

    assert rows == [
        {"title": "第一课", "level": 1, "page": 3},
        {"title": "第三课", "level": 1, "page": 5},
        {"title": "越界课", "level": 2, "page": 6},
    ]


def test_detect_pdf_chapters_regex_first_and_skips_ai():
    pdf_bytes = _make_toc_pdf()
    calls = 0

    def fake_chat(system_prompt, user_prompt):
        nonlocal calls
        calls += 1
        raise AssertionError("正则结果足够时不应调用 AI")

    rows = material.detect_pdf_chapters(pdf_bytes, fake_chat)

    assert calls == 0
    assert [item["page"] for item in rows] == [3, 4, 5, 6]
    assert rows[0]["title"] == "第一单元 混合运算"


def test_detect_pdf_chapters_details():
    pdf_bytes = _make_toc_pdf()
    details = material.detect_pdf_chapters(
        pdf_bytes, lambda s, u: "[]", return_details=True)

    assert details["source"] == "regex"
    assert details["offset"] == 2
    assert details["printed_chapters"][0]["page"] == 1
    assert details["chapters"][0]["page"] == 3


def test_detect_pdf_chapters_ai_fallback(monkeypatch):
    """构造无目录文本，让正则不足后走 AI。"""
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "无目录前言")
    page = doc.new_page()
    page.insert_text((72, 72), "第一章 正文标题")
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    pdf_bytes = buf.getvalue()

    def fake_chat(system_prompt, user_prompt):
        return json.dumps([
            {"title": "第一章", "level": 1, "page": 1},
            {"title": "第二章", "level": 1, "page": 2},
            {"title": "第三章", "level": 1, "page": 2},
        ], ensure_ascii=False)

    details = material.detect_pdf_chapters(
        pdf_bytes, fake_chat, return_details=True)

    assert details["source"] == "ai"
    assert details["printed_chapters"][0] == {
        "title": "第一章", "level": 1, "page": 1}


def test_build_chapters_from_pdf_pages_after_offset():
    pdf_bytes = _make_toc_pdf()
    chapters = material.detect_pdf_chapters(
        pdf_bytes, lambda s, u: "[]")
    built = material.build_chapters_from_pdf_pages(pdf_bytes, chapters)

    assert "第一单元正文" in built[0]["content"]
    assert "第二单元正文" in built[1]["content"]
    assert "第三单元正文" in built[2]["content"]
    assert built[-1]["page"] == 6


# ---------------------------------------------------------------------------
# AppTest
# ---------------------------------------------------------------------------

def _isolated_app_code():
    import importlib.util
    from pathlib import Path

    smoke_path = Path(__file__).with_name("test_app_smoke.py")
    spec = importlib.util.spec_from_file_location("test_app_smoke", smoke_path)
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)
    return smoke._isolated_app_code


def test_pdf_toc_preview_apptest(tmp_path):
    isolated = _isolated_app_code()
    db_file = tmp_path / "v166.db"
    at = AppTest.from_string(
        isolated(db_file, tmp_path / "feature.json"), default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📚 备课").run()

    at.file_uploader[0].upload(
        "教材.pdf", _make_toc_pdf(), "application/pdf").run()
    next(b for b in at.button if b.label == "提取并确认信息").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    next(b for b in at.button if b.label == "确认").click().run()
    assert not at.exception, [str(e) for e in at.exception]

    success_text = "\n".join(str(x.value) for x in at.success)
    assert "目录正则提取" in success_text
    assert "页码偏移 2 页" in success_text

    offset_input = next(x for x in at.number_input
                        if x.key == "pdf_page_offset_input")
    assert offset_input.value == 2
    assert any(x.key == "redetect_pdf_offset" for x in at.button)
    assert any(x.key == "use_pdf_bookmarks" for x in at.button)
    assert any(x.key == "ai_detect_chapters" for x in at.button)
    assert any(x.key == "material_chapter_editor" for x in at.dataframe)

    next(b for b in at.button if b.key == "use_pdf_bookmarks").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    assert any("没有内置书签" in str(x.value) for x in at.warning)

    offset_input.set_value(3).run()
    assert not at.exception, [str(e) for e in at.exception]
    assert any("已按新偏移整体重算" in str(x.value) for x in at.success)


def test_pdf_toc_save_apptest(tmp_path):
    isolated = _isolated_app_code()
    db_file = tmp_path / "v166_save.db"
    at = AppTest.from_string(
        isolated(db_file, tmp_path / "feature.json"), default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📚 备课").run()
    at.file_uploader[0].upload(
        "教材.pdf", _make_toc_pdf(), "application/pdf").run()
    next(b for b in at.button if b.label == "提取并确认信息").click().run()
    next(b for b in at.button if b.label == "确认").click().run()
    next(b for b in at.button if b.key == "save_material").click().run()

    assert not at.exception, [str(e) for e in at.exception]
    assert any("资料已保存" in str(x.value) for x in at.success)

    from sqlalchemy import create_engine, text
    eng = create_engine(f"sqlite:///{db_file.as_posix()}")
    with eng.connect() as conn:
        row = conn.execute(text(
            "SELECT name, file_type, subject FROM textbooks"
        )).mappings().one()
    assert dict(row) == {
        "name": "教材.pdf", "file_type": "pdf", "subject": "数学"}
    eng.dispose()
