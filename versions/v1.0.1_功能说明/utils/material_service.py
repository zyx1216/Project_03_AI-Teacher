# -*- coding: utf-8 -*-
"""
教学资料提取与章节切分层（纯逻辑 + 文件解析，不依赖 Streamlit）。

职责：
1. 从 PDF（PyMuPDF）、Word（python-docx）提取纯文本，或直接接收粘贴文本；
2. 按"第X章 / 第X节"等关键词切分章节目录；
3. 章内按固定字数切块，相邻块保留少量重叠，避免句子被拦腰切断后检索不到。

网页链接抓取本阶段只留接口，不实现（开发指令允许第二版再做）。
"""

from __future__ import annotations

import io
import re

# 章节标题正则：第X章、第X节、第X单元、第X课，以及 1.1 / 1.2 这类编号
_CHAPTER_PATTERNS = [
    re.compile(r"^\s*第\s*[0-9一二三四五六七八九十百零〇]+\s*[章节单元课]\s*[^\n]{0,40}$"),
    re.compile(r"^\s*[0-9]{1,2}\.[0-9]{1,2}(?:\.[0-9]{1,2})?\s+[^\n]{1,40}$"),
]

# 切块参数
CHUNK_SIZE = 500      # 每块目标字数
CHUNK_OVERLAP = 80    # 相邻块重叠字数


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