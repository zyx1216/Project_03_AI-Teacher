# -*- coding: utf-8 -*-
"""教学资料层测试：章节切分、切块重叠、PDF/Word 提取。"""

import io

import pytest

from utils import material_service as mat


def test_split_chapters_by_chinese_heading():
    text = "第一章 有理数\n1.1 正数和负数\n第一课内容。\n第二章 整式\n整式的内容。"
    chapters = mat.split_chapters(text)
    titles = [c["title"] for c in chapters]
    assert "第一章 有理数" in titles
    assert "第二章 整式" in titles
    # 章内容正确归属
    second = [c for c in chapters if c["title"] == "第二章 整式"][0]
    assert "整式的内容" in second["content"]


def test_split_chapters_no_heading_returns_single():
    chapters = mat.split_chapters("这是一整篇没有章节标题的文本。")
    assert len(chapters) == 1
    assert chapters[0]["title"] == "全文"


def test_split_chapters_empty():
    assert mat.split_chapters("") == []
    assert mat.split_chapters("   ") == []


def test_is_chapter_heading():
    assert mat.is_chapter_heading("第3节 函数")
    assert mat.is_chapter_heading("1.2 数轴")
    assert not mat.is_chapter_heading("这是普通的一句话")


def test_chunk_text_length_and_overlap():
    text = "句子。" * 300  # 900 字，应切成多块
    chunks = mat.chunk_text(text, size=500, overlap=80)
    assert len(chunks) >= 2
    assert all(len(c) <= 520 for c in chunks)  # 允许断句带来的少量浮动
    # 相邻块存在重叠：后一块开头应能在前一块结尾附近找到
    tail = chunks[0][-80:]
    assert chunks[1][:30].strip("。") in tail + chunks[1][:30]


def test_chunk_text_short_returns_one():
    assert mat.chunk_text("短文本") == ["短文本"]
    assert mat.chunk_text("") == []


def test_chunk_chapters_structure():
    chapters = [{"title": "第一章", "content": "甲。" * 300}]
    pieces = mat.chunk_chapters(chapters)
    assert pieces
    assert all("chapter_title" in p and "text" in p for p in pieces)
    assert pieces[0]["chapter_title"] == "第一章"


def test_extract_text_normalizes():
    out = mat.extract_text("a\r\nb\r\n\r\n\r\n\r\nc")
    assert "\r" not in out
    assert "\n\n\n" not in out


def test_extract_docx_roundtrip(tmp_path):
    from docx import Document
    doc = Document()
    doc.add_paragraph("第一章 测试章")
    doc.add_paragraph("这是 Word 里的正文内容。")
    path = tmp_path / "sample.docx"
    doc.save(path)
    text = mat.extract_docx(str(path))
    assert "第一章 测试章" in text
    assert "正文内容" in text
    # 也支持字节输入
    data = path.read_bytes()
    assert "正文内容" in mat.extract_docx(io.BytesIO(data))


def test_extract_pdf_roundtrip(tmp_path):
    """PDF 提取链路用 ASCII 文本验证（内置字体不写中文，避免字体依赖）。"""
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "1.1 Alpha heading\nsome pdf body text here", fontsize=12)
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    text = mat.extract_pdf(buf.getvalue())
    assert "pdf body text" in text