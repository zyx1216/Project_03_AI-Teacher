# -*- coding: utf-8 -*-
"""v1.6.2：原版文件、PDF 章节识别、按学科待定出题配置测试。"""

import io
import json

import pymupdf
import pytest

from utils import material_service as material
from utils import question_service as qs


# ---------------------------------------------------------------------------
# 测试用 PDF
# ---------------------------------------------------------------------------

def _bookmark_pdf_bytes() -> bytes:
    """造 3 页 PDF，并写入内置书签。"""
    doc = pymupdf.open()
    for index in range(3):
        page = doc.new_page()
        page.insert_text((72, 72), f"Page {index + 1}")
    doc.set_toc([
        [1, "第一章 有理数", 1],
        [2, "1.1 正数和负数", 1],
        [1, "第二章 整式", 2],
    ])
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 原版文件与静态目录
# ---------------------------------------------------------------------------

@pytest.fixture()
def original_paths(tmp_path, monkeypatch):
    original_dir = tmp_path / "uploads" / "original"
    static_dir = tmp_path / "static" / "uploads" / "original"
    monkeypatch.setattr(material, "ORIGINAL_DIR", original_dir)
    monkeypatch.setattr(material, "STATIC_ORIGINAL_DIR", static_dir)
    return original_dir, static_dir


def test_save_pdf_original_and_static_url_hardlink_or_copy(original_paths):
    original_dir, static_dir = original_paths
    pdf_bytes = _bookmark_pdf_bytes()

    url = material.publish_original_file(7, "pdf", pdf_bytes)

    assert url == "app/static/uploads/original/7.pdf"
    assert (original_dir / "7.pdf").read_bytes() == pdf_bytes
    static_file = static_dir / "7.pdf"
    assert static_file.exists() and static_file.read_bytes() == pdf_bytes
    original_stat = (original_dir / "7.pdf").stat()
    static_stat = static_file.stat()
    # 同一卷应优先硬链接；退化为复制时，文件内容仍必须一致。
    assert original_stat.st_nlink == 2 or static_stat.st_ino != original_stat.st_ino


def test_save_word_original_and_static_url(original_paths):
    original_dir, static_dir = original_paths
    word_bytes = b"PK fake docx bytes"

    url = material.publish_original_file(3, "word", word_bytes)

    assert url == "app/static/uploads/original/3.docx"
    assert (original_dir / "3.docx").read_bytes() == word_bytes
    assert (static_dir / "3.docx").read_bytes() == word_bytes


def test_old_material_without_original_has_no_entry(original_paths):
    original_dir, _ = original_paths
    candidate = material.original_file_path(99, "pdf")
    assert not candidate.exists()
    with pytest.raises(ValueError, match="只有 PDF 和 Word"):
        material.original_file_path(1, "text")


def test_sync_original_static_files_fills_missing_files(original_paths):
    original_dir, static_dir = original_paths
    original_dir.mkdir(parents=True)
    (original_dir / "1.pdf").write_bytes(b"pdf-1")
    (original_dir / "2.docx").write_bytes(b"word-2")

    assert material.sync_original_static_files() == 2
    assert (static_dir / "1.pdf").read_bytes() == b"pdf-1"
    assert (static_dir / "2.docx").read_bytes() == b"word-2"


# ---------------------------------------------------------------------------
# PDF 书签、AI 识别、页码组装、手工编辑
# ---------------------------------------------------------------------------

def test_pdf_bookmarks_read_builtin_toc():
    chapters = material.pdf_bookmarks(_bookmark_pdf_bytes())

    assert chapters == [
        {"title": "第一章 有理数", "level": 1, "page": 1},
        {"title": "1.1 正数和负数", "level": 2, "page": 1},
        {"title": "第二章 整式", "level": 1, "page": 2},
    ]


def test_build_chapters_from_pdf_pages_uses_page_ranges():
    pdf_bytes = _bookmark_pdf_bytes()
    chapters = material.build_chapters_from_pdf_pages(pdf_bytes, [
        {"title": "第一章", "level": 1, "page": 1},
        {"title": "第二章", "level": 1, "page": 2},
        {"title": "第三章", "level": 1, "page": 3},
    ])

    assert [item["page"] for item in chapters] == [1, 2, 3]
    assert "Page 1" in chapters[0]["content"]
    assert "Page 2" in chapters[1]["content"]
    assert "Page 3" in chapters[2]["content"]


def test_build_toc_source_text_reads_first_pages_without_toc_word():
    text = material.build_toc_source_text(_bookmark_pdf_bytes())
    assert "Page 1" in text and "Page 3" in text


def test_parse_ai_chapters_validates_json_and_page_bounds():
    raw = json.dumps([
        {"title": "第一章", "level": 1, "page": 1},
        {"title": "第二章", "level": 2, "page": 2},
    ], ensure_ascii=False)

    assert material.parse_ai_chapters(raw, 3)[1]["page"] == 2

    with pytest.raises(ValueError, match="合法的章节 JSON"):
        material.parse_ai_chapters("不是 JSON", 3)
    with pytest.raises(ValueError, match="页码超出"):
        material.parse_ai_chapters(
            json.dumps([{"title": "第三章", "level": 1, "page": 4}]), 3)
    with pytest.raises(ValueError, match="层级超出"):
        material.parse_ai_chapters(
            json.dumps([{"title": "第三章", "level": 4, "page": 3}]), 3)


def test_detect_pdf_chapters_calls_chat_func():
    pdf_bytes = _bookmark_pdf_bytes()

    def fake_chat(system_prompt, user_prompt):
        assert "目录" in system_prompt
        assert "Page 1" in user_prompt
        return json.dumps([{"title": "AI识别章节", "level": 1, "page": 1}],
                          ensure_ascii=False)

    assert material.detect_pdf_chapters(pdf_bytes, fake_chat) == [
        {"title": "AI识别章节", "level": 1, "page": 1}]


def test_chapter_editor_merge_non_pdf_keeps_content_by_original_index():
    rule_chapters = [
        {"title": "旧一", "level": 1, "content": "正文一"},
        {"title": "旧二", "level": 1, "content": "正文二"},
    ]
    rows = [
        {"章节标题": "新二", "层级": 2, "原序号": 1},
        {"章节标题": "新一", "层级": 1, "原序号": 0},
    ]

    merged = material.chapters_from_editor(rule_chapters, rows, "word")

    assert merged == [
        {"title": "新二", "level": 2, "content": "正文二"},
        {"title": "新一", "level": 1, "content": "正文一"},
    ]


def test_chapter_editor_skips_empty_title_and_rebuilds_pdf():
    pdf_bytes = _bookmark_pdf_bytes()
    rows = [
        {"章节标题": "第一章改", "层级": 1, "页码": 1, "原序号": 0},
        {"章节标题": "", "层级": 1, "页码": 2, "原序号": 1},
    ]

    merged = material.chapters_from_editor([], rows, "pdf", pdf_bytes)

    assert len(merged) == 1
    assert merged[0]["title"] == "第一章改"
    assert "Page 1" in merged[0]["content"]


# ---------------------------------------------------------------------------
# 出题待定任务：学科切换、删除、旧历史兼容
# ---------------------------------------------------------------------------

def test_editor_rows_to_tasks_filters_deleted_rows():
    tasks = qs.editor_rows_to_tasks([
        {"题型": "选择题", "难度": 1, "数量": 2, "删除": False},
        {"题型": "填空题", "难度": 2, "数量": 3, "删除": True},
    ], ["选择题", "填空题"])

    assert tasks == [{
        "question_type": "选择题",
        "storage_type": "choice",
        "difficulty": 1,
        "count": 2,
    }]


def test_draft_from_editor_and_normalize_draft():
    draft = qs.draft_from_editor(
        [{"题型": "证明题", "难度": 3, "数量": 1, "删除": False}],
        ["证明题"], material_id="5", knowledge_points=["函数", "函数", " "],
        extra="结合生活")

    assert qs.normalize_draft(draft) == {
        "tasks": [{
            "question_type": "证明题",
            "storage_type": "solution",
            "difficulty": 3,
            "count": 1,
        }],
        "material_id": 5,
        "knowledge_points": ["函数"],
        "extra": "结合生活",
    }


def test_drafts_keep_each_subject_independent():
    math_draft = qs.draft_from_editor(
        [{"题型": "选择题", "难度": 1, "数量": 2, "删除": False}],
        ["选择题"], None, ["数与式"], "")
    history_draft = qs.draft_from_editor(
        [{"题型": "材料分析题", "难度": 2, "数量": 1, "删除": False}],
        ["材料分析题"], None, ["史料"], "")

    drafts = {"数学": math_draft, "历史": qs.normalize_draft(history_draft)}
    assert drafts["数学"]["tasks"][0]["question_type"] == "选择题"
    assert drafts["历史"]["tasks"][0]["storage_type"] == "solution"
    assert qs.validate_normalized_tasks(
        drafts["历史"]["tasks"], ["材料分析题"])[0]["count"] == 1


def test_drafts_from_new_history_config():
    config_data = {"drafts": {"数学": {
        "tasks": [{
            "question_type": "选择题",
            "storage_type": "choice",
            "difficulty": 1,
            "count": 2,
        }],
        "material_id": 3,
        "knowledge_points": ["函数"],
        "extra": "",
    }}}

    drafts = qs.drafts_from_history_config(config_data)

    assert drafts["数学"]["material_id"] == 3
    assert drafts["数学"]["tasks"][0]["count"] == 2


def test_drafts_from_v160_history_config_compat():
    config_data = {
        "subjects": ["数学", "物理"],
        "tasks": {
            "数学": [{
                "question_type": "选择题",
                "storage_type": "choice",
                "difficulty": 1,
                "count": 2,
            }],
            "物理": [{
                "question_type": "解答题",
                "storage_type": "solution",
                "difficulty": 3,
                "count": 1,
            }],
        },
        "material_id": None,
        "knowledge_points": ["共享知识点"],
        "extra": "旧要求",
    }

    drafts = qs.drafts_from_history_config(config_data)

    assert set(drafts) == {"数学", "物理"}
    assert drafts["数学"]["knowledge_points"] == ["共享知识点"]
    assert drafts["物理"]["tasks"][0]["difficulty"] == 3
    assert drafts["物理"]["extra"] == "旧要求"


def test_validate_normalized_tasks_rejects_invalid_type():
    with pytest.raises(ValueError, match="题型不符合"):
        qs.validate_normalized_tasks([{
            "question_type": "作文题",
            "difficulty": 1,
            "count": 1,
        }], ["选择题"])
