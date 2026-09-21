# -*- coding: utf-8 -*-
"""
教学资料提取与章节切分层（纯逻辑 + 文件解析，不依赖 Streamlit）。

职责：
1. 从 PDF（PyMuPDF）、Word（python-docx）提取纯文本，或直接接收粘贴文本；
2. 按"第X章 / 第X节"等关键词切分章节目录；
3. 章内按固定字数切块，相邻块保留少量重叠，避免句子被拦腰切断后检索不到。

网页链接用 trafilatura 抓取公开网页正文，只做单篇资料导入，不做爬虫。
"""

from __future__ import annotations

import html as html_lib
import io
import re
import time
from datetime import date
from urllib.parse import urlsplit

# 章节标题正则：第X章、第X节、第X单元、第X课，以及 1.1 / 1.2 这类编号
_CHAPTER_PATTERNS = [
    re.compile(r"^\s*第\s*[0-9一二三四五六七八九十百零〇]+\s*[章节单元课]\s*[^\n]{0,40}$"),
    re.compile(r"^\s*[0-9]{1,2}\.[0-9]{1,2}(?:\.[0-9]{1,2})?\s+[^\n]{1,40}$"),
]

# 切块参数
CHUNK_SIZE = 500      # 每块目标字数
CHUNK_OVERLAP = 80    # 相邻块重叠字数


# ---------------------------------------------------------------------------
# 网页链接抓取（阶段 6 / v1.1.0）
# ---------------------------------------------------------------------------

WEB_TIMEOUT_SECONDS = 30
WEB_MAX_REDIRECTS = 2
WEB_FETCH_ATTEMPTS = 3
WEB_RETRY_WAIT_SECONDS = (1, 2)
WEB_MAX_TEXT_CHARS = 100_000
WEB_MAX_URL_LENGTH = 500


class WebExtractError(Exception):
    """网页地址非法、抓取失败或正文不可用时抛出，界面直接显示中文原因。"""


def normalize_url(url: str) -> str:
    """校验并归一化网页地址，只允许公开网页常用的 http/https。"""
    if url is None:
        raise WebExtractError("请输入网页链接。")
    cleaned = str(url).strip()
    if not cleaned:
        raise WebExtractError("请输入网页链接。")
    if len(cleaned) > WEB_MAX_URL_LENGTH:
        raise WebExtractError(f"网页链接过长，请控制在 {WEB_MAX_URL_LENGTH} 字符以内。")
    if any(ch.isspace() for ch in cleaned):
        raise WebExtractError("网页链接中不能包含空格。")

    try:
        parts = urlsplit(cleaned)
    except ValueError as exc:
        raise WebExtractError("网页链接格式不正确。") from exc

    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise WebExtractError("只支持 http:// 或 https:// 开头的公开网页链接。")
    if not parts.netloc or not parts.hostname:
        raise WebExtractError("网页链接缺少域名，请检查后重试。")
    if "." not in parts.hostname and parts.hostname.lower() != "localhost":
        raise WebExtractError("网页链接域名格式不正确。")
    return cleaned


def _web_config():
    """生成 trafilatura 配置：30 秒超时、最多跟随 2 次重定向。"""
    from trafilatura.settings import use_config

    cfg = use_config()
    cfg["DEFAULT"]["DOWNLOAD_TIMEOUT"] = str(WEB_TIMEOUT_SECONDS)
    cfg["DEFAULT"]["MAX_REDIRECTS"] = str(WEB_MAX_REDIRECTS)
    return cfg


def _fetch_web_once(url: str, cfg) -> str:
    """实际下载一次网页；下载为空时抛异常交给上层重试。"""
    import trafilatura

    html_text = trafilatura.fetch_url(url, config=cfg)
    if not html_text:
        raise WebExtractError("网页下载失败或返回内容为空。")
    return html_text


def _extract_title(html_text: str, url: str) -> str:
    """优先从 HTML title 取标题，取不到时用 URL 兜底。"""
    match = re.search(r"(?is)<title[^>]*>(.*?)</title>", html_text or "")
    if match:
        title = html_lib.unescape(match.group(1))
        title = re.sub(r"\s+", " ", title).strip()
        if title:
            return title[:120]
    return url


def _extract_web_content(html_text: str, url: str) -> tuple[str, str]:
    """从网页 HTML 提取标题和正文。"""
    import trafilatura

    title = _extract_title(html_text, url)
    text = trafilatura.extract(
        html_text,
        url=url,
        include_comments=False,
        include_tables=True,
        favor_precision=True,
    )
    text = _normalize_text(text or "")
    return title, text


def fetch_web_page(url: str) -> dict:
    """
    抓取并提取一个公开网页的正文。

    网络/解析类错误最多尝试 3 次；URL 非法不重试；正文超过上限直接拒绝，
    防止异常网页把本地文本和向量索引撑得过大。
    """
    normalized = normalize_url(url)
    cfg = _web_config()
    last_error = None

    for attempt in range(1, WEB_FETCH_ATTEMPTS + 1):
        try:
            html_text = _fetch_web_once(normalized, cfg)
            title, text = _extract_web_content(html_text, normalized)
            text = (text or "").strip()
            if not text:
                raise WebExtractError(
                    "没有从网页中提取到正文。可换一个公开网页链接，"
                    "或直接复制网页正文粘贴导入；需要登录的页面暂不支持。")
            if len(text) > WEB_MAX_TEXT_CHARS:
                raise WebExtractError(
                    f"网页正文过长（超过 {WEB_MAX_TEXT_CHARS:,} 字），"
                    "请选择更聚焦的文章页，或复制需要的正文后粘贴导入。")
            return {"url": normalized, "title": title, "text": text}
        except WebExtractError as exc:
            message = str(exc)
            last_error = exc
            # 地址问题和正文超限不需要重试；抓不到正文保留原有重试策略。
            if message.startswith(("网页链接", "只支持", "网页正文过长")):
                raise
        except Exception as exc:  # 网络/解析库异常统一转成用户能看懂的错误
            last_error = exc
        if attempt < WEB_FETCH_ATTEMPTS:
            time.sleep(WEB_RETRY_WAIT_SECONDS[attempt - 1])

    raise WebExtractError(
        "网页抓取失败，请检查网络和链接；也可以换一个公开网页链接，"
        f"或直接复制正文粘贴导入。最后一次错误：{last_error}")


def build_web_source_text(result: dict, fetched_at: str | None = None) -> str:
    """把网页元信息和正文拼成保存文本，后续章节切分与检索直接复用。"""
    fetched_at = fetched_at or date.today().isoformat()
    title = str(result.get("title") or result.get("url") or "网页资料").strip()
    url = str(result.get("url") or "").strip()
    text = _normalize_text(str(result.get("text") or ""))
    return _normalize_text(
        "网页资料\n"
        f"标题：{title}\n"
        f"来源：{url}\n"
        f"抓取日期：{fetched_at}\n\n"
        f"{text}"
    )


def extract_pdf(file_bytes_or_path) -> str:
    """用 PyMuPDF 提取文本型 PDF 的全文。扫描件 PDF 提取为空时由上层提示。"""
    import pymupdf
    if isinstance(file_bytes_or_path, (bytes, bytearray)):
        doc = pymupdf.open(stream=io.BytesIO(file_bytes_or_path), filetype="pdf")
    else:
        doc = pymupdf.open(file_bytes_or_path)
    try:
        pages = [page.get_text("text") for page in doc]
    finally:
        doc.close()
    return _normalize_text("\n".join(pages))


def extract_docx(file_bytes_or_path) -> str:
    """用 python-docx 提取 Word 全文（段落 + 表格单元格）。"""
    import io
    from docx import Document

    if isinstance(file_bytes_or_path, (bytes, bytearray)):
        doc = Document(io.BytesIO(file_bytes_or_path))
    else:
        doc = Document(file_bytes_or_path)
    parts = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            parts.append(" ".join(cell.text for cell in row.cells))
    return _normalize_text("\n".join(parts))


def extract_text(raw: str) -> str:
    """接收粘贴的纯文本并规范化。"""
    return _normalize_text(raw or "")


def _normalize_text(text: str) -> str:
    """清理多余空白，统一换行。"""
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # 行内连续空白压成一个空格，保留换行
    lines = [re.sub(r"[ \t\u3000]+", " ", line).strip() for line in text.split("\n")]
    # 去掉 3 个以上的连续空行
    result = "\n".join(lines)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def is_chapter_heading(line: str) -> bool:
    """判断一行是不是章节标题。"""
    line = line.strip()
    if not line or len(line) > 50:
        return False
    return any(p.match(line) for p in _CHAPTER_PATTERNS)


def split_chapters(text: str) -> list[dict]:
    """
    按章节标题切分，返回 [{"title":..., "content":...}]。
    没识别到任何章节标题时，整篇作为一个章节（标题"全文"）。
    """
    if not text.strip():
        return []
    lines = text.split("\n")
    chapters = []
    current_title = "全文"
    current_lines = []
    found = False

    for line in lines:
        if is_chapter_heading(line):
            if current_lines or found:
                chapters.append({
                    "title": current_title,
                    "content": "\n".join(current_lines).strip(),
                })
            current_title = line.strip()
            current_lines = []
            found = True
        else:
            current_lines.append(line)
    # 收尾
    if current_lines or not chapters:
        chapters.append({
            "title": current_title,
            "content": "\n".join(current_lines).strip(),
        })
    # 去掉空章节
    return [c for c in chapters if c["content"] or c["title"]]


def chunk_text(text: str, size: int = CHUNK_SIZE,
               overlap: int = CHUNK_OVERLAP) -> list[str]:
    """
    按字数切块，相邻块保留 overlap 字重叠。
    优先在换行/句号处断开，避免把句子切碎。
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]

    chunks = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + size, n)
        if end < n:
            # 在 [start+size*0.6, end) 范围内找最后一个断句点
            window = text[start + int(size * 0.6):end]
            break_pos = -1
            for sep in ("\n", "。", "！", "？", "；", ".", "!", "?", ";"):
                pos = window.rfind(sep)
                if pos > break_pos:
                    break_pos = pos
            if break_pos >= 0:
                end = start + int(size * 0.6) + break_pos + 1
        chunks.append(text[start:end].strip())
        if end >= n:
            break
        start = max(0, end - overlap)
    return [c for c in chunks if c]


def chunk_chapters(chapters: list[dict]) -> list[dict]:
    """
    把切好的章节进一步切块。
    返回 [{"chapter_title":..., "text":...}, ...]，供向量化和关键词检索用。
    """
    chunks = []
    for ch in chapters:
        for piece in chunk_text(ch.get("content", "")):
            chunks.append({"chapter_title": ch["title"], "text": piece})
    return chunks


def chapter_titles(chapters: list[dict]) -> list[str]:
    """提取章节标题列表。"""
    return [c["title"] for c in chapters]
def extract_pdf_with_ocr(file_bytes_or_path) -> dict:
    """
    提取 PDF 文本；检测到扫描件时自动调用本地 OCR。

    返回 {"text": 全文, "ocr_used": 是否使用 OCR}，供页面显示识别提示。
    """
    from utils import ocr_service

    if ocr_service.is_scanned_pdf(file_bytes_or_path):
        text = ocr_service.ocr_pdf(file_bytes_or_path)
        return {"text": text, "ocr_used": True}

    return {"text": extract_pdf(file_bytes_or_path), "ocr_used": False}