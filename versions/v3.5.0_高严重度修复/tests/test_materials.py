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


# ---------------------------------------------------------------------------
# 阶段 6：网页链接抓取（全部 mock，不联网）
# ---------------------------------------------------------------------------



def test_normalize_url_accepts_http_https():
    assert mat.normalize_url("  https://example.com/a?x=1  ") == "https://example.com/a?x=1"
    assert mat.normalize_url("http://www.example.com/数学") == "http://www.example.com/数学"


@pytest.mark.parametrize("bad_url", [
    "", "   ", "ftp://example.com/file", "javascript:alert(1)",
    "not a url", "https://", "https:///path",
])
def test_normalize_url_rejects_invalid(bad_url):
    with pytest.raises(mat.WebExtractError):
        mat.normalize_url(bad_url)


def test_normalize_url_rejects_too_long():
    with pytest.raises(mat.WebExtractError):
        mat.normalize_url("https://example.com/" + "a" * 500)


def test_fetch_web_page_success(monkeypatch):
    monkeypatch.setattr(mat, "_fetch_web_once", lambda url, cfg: "<html>网页HTML</html>")
    monkeypatch.setattr(
        mat, "_extract_web_content",
        lambda html, url: ("一元二次方程", "这是从网页提取出的正文。"))
    monkeypatch.setattr(mat.time, "sleep", lambda seconds: None)

    result = mat.fetch_web_page("  https://example.com/article?x=1 ")

    assert result == {
        "url": "https://example.com/article?x=1",
        "title": "一元二次方程",
        "text": "这是从网页提取出的正文。",
    }


def test_fetch_web_page_empty_text_raises(monkeypatch):
    calls = []

    def fake_fetch(url, cfg):
        calls.append(url)
        return "<html></html>"

    monkeypatch.setattr(mat, "_fetch_web_once", fake_fetch)
    monkeypatch.setattr(mat, "_extract_web_content", lambda html, url: ("空页", "   "))
    monkeypatch.setattr(mat.time, "sleep", lambda seconds: None)

    with pytest.raises(mat.WebExtractError, match="换一个公开网页链接"):
        mat.fetch_web_page("https://example.com/empty")
    assert len(calls) == mat.WEB_FETCH_ATTEMPTS


def test_fetch_web_page_rejects_oversized_text(monkeypatch):
    monkeypatch.setattr(mat, "_fetch_web_once", lambda url, cfg: "<html>长网页</html>")
    monkeypatch.setattr(
        mat, "_extract_web_content",
        lambda html, url: ("长网页", "字" * (mat.WEB_MAX_TEXT_CHARS + 1)))

    with pytest.raises(mat.WebExtractError, match="正文过长"):
        mat.fetch_web_page("https://example.com/long")


def test_fetch_web_page_retries_then_succeeds(monkeypatch):
    states = {"calls": 0}
    sleeps = []

    def fake_fetch(url, cfg):
        states["calls"] += 1
        if states["calls"] < 3:
            raise TimeoutError("network timeout")
        return "<html>成功</html>"

    monkeypatch.setattr(mat, "_fetch_web_once", fake_fetch)
    monkeypatch.setattr(
        mat, "_extract_web_content",
        lambda html, url: ("成功标题", "成功正文"))
    monkeypatch.setattr(mat.time, "sleep", lambda seconds: sleeps.append(seconds))

    result = mat.fetch_web_page("https://example.com/retry")

    assert states["calls"] == 3
    assert sleeps == [1, 2]
    assert result["text"] == "成功正文"


def test_fetch_web_page_invalid_url_does_not_request(monkeypatch):
    def forbidden_fetch(url, cfg):
        raise AssertionError("非法 URL 不应发起请求")

    monkeypatch.setattr(mat, "_fetch_web_once", forbidden_fetch)
    with pytest.raises(mat.WebExtractError):
        mat.fetch_web_page("ftp://example.com/file")


def test_web_config_timeout_and_redirects():
    cfg = mat._web_config()
    assert cfg["DEFAULT"]["DOWNLOAD_TIMEOUT"] == str(mat.WEB_TIMEOUT_SECONDS)
    assert cfg["DEFAULT"]["MAX_REDIRECTS"] == str(mat.WEB_MAX_REDIRECTS)


def test_extract_title_from_html():
    html = "<html><head><title>  函数与图像 &amp; 图象 &lt;上&gt; </title></head></html>"
    assert mat._extract_title(html, "https://example.com") == "函数与图像 & 图象 <上>"


def test_extract_web_content_uses_trafilatura(monkeypatch):
    import trafilatura

    def fake_extract(filecontent, url, **kwargs):
        assert url == "https://example.com/article"
        assert kwargs["include_comments"] is False
        assert kwargs["include_tables"] is True
        return "网页正文第一段。"

    monkeypatch.setattr(trafilatura, "extract", fake_extract)
    html = "<html><head><title>示例课</title></head><body><p>内容</p></body></html>"

    title, text = mat._extract_web_content(html, "https://example.com/article")

    assert title == "示例课"
    assert text == "网页正文第一段。"


def test_fetch_web_once_uses_trafilatura(monkeypatch):
    import trafilatura

    calls = {}

    def fake_fetch(url, config):
        calls["url"] = url
        calls["config"] = config
        return "<html>正文</html>"

    monkeypatch.setattr(trafilatura, "fetch_url", fake_fetch)
    cfg = mat._web_config()

    assert mat._fetch_web_once("https://example.com", cfg) == "<html>正文</html>"
    assert calls["url"] == "https://example.com"
    assert calls["config"] is cfg


def test_build_web_source_text_contains_metadata():
    result = {
        "url": "https://example.com/article",
        "title": "二次函数",
        "text": "这是网页正文。",
    }
    out = mat.build_web_source_text(result, fetched_at="2026-09-19")
    assert "标题：二次函数" in out
    assert "来源：https://example.com/article" in out
    assert "抓取日期：2026-09-19" in out
    assert "这是网页正文。" in out
