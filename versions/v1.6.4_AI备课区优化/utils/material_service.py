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
import json
import config
import pandas as pd
import re
import time
from datetime import date
from urllib.parse import urlsplit

# 章节标题正则：第X章、第X节、第X单元、第X课，以及 1.1 / 1.2 这类编号
_CHAPTER_PATTERNS = [
    re.compile(r"^\s*第\s*[0-9一二三四五六七八九十百零〇]+\s*[章节单元课]\s*[^\n]{0,40}$"),
    re.compile(r"^\s*[0-9]{1,2}\.[0-9]{1,2}(?:\.[0-9]{1,2})?\s+[^\n]{1,40}$"),
    re.compile(r"^\s*第\s*[0-9一二三四五六七八九十百零〇]+\s*单元\s*$"),
    re.compile(r"^\s*(?:整理与复习|总复习|数学好玩|综合实践|练一练)\s*$"),
]

_UNIT_STANDALONE_RE = re.compile(
    r"^\s*第\s*[0-9一二三四五六七八九十百零〇]+\s*单元\s*$")

# 切块参数
CHUNK_SIZE = 500      # 每块目标字数
CHUNK_OVERLAP = 80    # 相邻块重叠字数


def strip_code_fence(text: str) -> str:
    """去掉模型常见的 ```json ... ``` 包裹。"""
    cleaned = str(text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    return cleaned.strip()


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
    # 句末标点通常说明这是正文句，避免“第一单元正文。”被误判成标题。
    if line[-1] in "。！？；，、":
        return False
    return any(pattern.match(line) for pattern in _CHAPTER_PATTERNS)


def _merge_unit_title_lines(lines: list[str]) -> list[str]:
    """把单独成行的“第X单元”和下一行短标题合并。

    下一行本身是章节标题时不合并，避免吞掉“整理与复习”等后续章节。
    """
    merged = []
    skip_next = False
    for index, line in enumerate(lines):
        if skip_next:
            skip_next = False
            continue
        title = line.strip()
        if (index + 1 < len(lines) and _UNIT_STANDALONE_RE.match(title)):
            next_title = lines[index + 1].strip()
            if (next_title and len(next_title) < 20
                    and not is_chapter_heading(next_title)):
                merged.append(f"{title} {next_title}")
                skip_next = True
                continue
        merged.append(line)
    return merged


def split_chapters(text: str) -> list[dict]:
    """
    按章节标题切分，返回 [{"title":..., "content":...}]。
    没识别到任何章节标题时，整篇作为一个章节（标题"全文"）。
    """
    if not text.strip():
        return []
    lines = _merge_unit_title_lines(text.split("\n"))
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

# ---------------------------------------------------------------------------
# v1.6.2：原始文件、静态文件、PDF 章节识别
# ---------------------------------------------------------------------------

ORIGINAL_DIR = config.UPLOAD_DIR / "original"
STATIC_ORIGINAL_DIR = config.BASE_DIR / "static" / "uploads" / "original"
OCR_SOURCE_DIR = config.UPLOAD_DIR / "ocr_source"

_ORIGINAL_EXTENSIONS = {"pdf": ".pdf", "word": ".docx"}


def original_file_path(textbook_id: int, file_type: str) -> Path:
    """返回资料原始文件的固定保存路径。"""
    suffix = _ORIGINAL_EXTENSIONS.get(file_type)
    if suffix is None:
        raise ValueError("只有 PDF 和 Word 资料有原始文件。")
    return ORIGINAL_DIR / f"{int(textbook_id)}{suffix}"


def static_original_file_path(textbook_id: int, file_type: str) -> Path:
    """返回 Streamlit 静态目录中的原始文件路径。"""
    suffix = _ORIGINAL_EXTENSIONS.get(file_type)
    if suffix is None:
        raise ValueError("只有 PDF 和 Word 资料有静态原始文件。")
    return STATIC_ORIGINAL_DIR / f"{int(textbook_id)}{suffix}"


def save_original_file(textbook_id: int, file_type: str, file_bytes: bytes) -> Path:
    """保存原始 PDF/Word。老师重新导入后才能使用原版打开功能。"""
    target = original_file_path(textbook_id, file_type)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(bytes(file_bytes))
    expose_original_file(target)
    return target


def expose_original_file(source: Path) -> Path:
    """把 canonical 原始文件发布到 static；优先硬链接，失败后复制。"""
    import os
    import shutil

    target = STATIC_ORIGINAL_DIR / source.name
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        try:
            if target.stat().st_size == source.stat().st_size:
                return target
            target.unlink()
        except OSError:
            pass
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)
    return target


def static_url_for_original(path: Path) -> str:
    """返回 Streamlit 静态文件访问地址。"""
    return f"app/static/uploads/original/{path.name}"


def publish_original_file(textbook_id: int, file_type: str, file_bytes: bytes) -> str:
    """保存并发布原始文件，返回静态 URL。"""
    path = save_original_file(textbook_id, file_type, file_bytes)
    return static_url_for_original(path)


def sync_original_static_files() -> int:
    """启动时补齐 static 中缺失的原始文件，返回处理数量。"""
    if not ORIGINAL_DIR.exists():
        return 0
    count = 0
    for source in ORIGINAL_DIR.iterdir():
        if source.is_file():
            expose_original_file(source)
            count += 1
    return count


def delete_material(session, textbook_id: int) -> None:
    """删除资料并级联清理：文本、canonical 原文、static 原文、向量集合。

    只删除 ORM 实例和文件，事务由调用方提交。向量集合删除失败不阻断。
    """
    from models.models import Textbook
    tb = session.get(Textbook, int(textbook_id))
    if tb is None:
        raise ValueError("资料不存在或已被删除。")

    # 全文文本
    text_path = config.UPLOAD_DIR / "text" / f"{int(textbook_id)}.txt"
    try:
        text_path.unlink()
    except FileNotFoundError:
        pass

    # PDF/Word 原文（canonical 与 static 各一份）
    if tb.file_type in _ORIGINAL_EXTENSIONS:
        for remover in (original_file_path, static_original_file_path):
            try:
                remover(int(textbook_id), tb.file_type).unlink()
            except FileNotFoundError:
                pass

    session.delete(tb)
    session.flush()

    # 向量集合最后清，异常不阻断
    from utils import vector_store
    try:
        vector_store.drop_index(int(textbook_id))
    except Exception:
        pass


def ocr_source_path(task_id: str) -> Path:
    """返回后台 OCR 原始 PDF 暂存路径。"""
    return OCR_SOURCE_DIR / f"{task_id}.pdf"


def save_ocr_source(task_id: str, pdf_bytes: bytes) -> Path:
    """OCR 启动时先保存原始 PDF，确认命名后再移动到资料目录。"""
    target = ocr_source_path(task_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(bytes(pdf_bytes))
    return target


def move_ocr_source_to_original(task_id: str, textbook_id: int) -> Path | None:
    """确认资料后，把 OCR 原文移动为该资料的 canonical 文件。"""
    source = ocr_source_path(task_id)
    if not source.exists():
        return None
    target = original_file_path(textbook_id, "pdf")
    target.parent.mkdir(parents=True, exist_ok=True)
    source.replace(target)
    expose_original_file(target)
    return target


def remove_ocr_source(task_id: str) -> None:
    """删除 OCR 原始 PDF 暂存文件。"""
    try:
        ocr_source_path(task_id).unlink()
    except FileNotFoundError:
        pass


def pdf_bookmarks(file_bytes: bytes) -> list[dict]:
    """读取 PDF 内置书签，返回标题、层级和页码。"""
    import pymupdf

    result = []
    with pymupdf.open(stream=io.BytesIO(bytes(file_bytes)), filetype="pdf") as doc:
        total = len(doc)
        for item in doc.get_toc(simple=True):
            try:
                level, title, page = item[:3]
                level = int(level)
                page = int(page)
            except (TypeError, ValueError):
                continue
            title = str(title or "").strip()
            if title and 1 <= page <= total:
                result.append({"title": title[:120], "level": min(3, max(1, level)), "page": page})
    return result


def build_toc_source_text(file_bytes: bytes) -> str:
    """优先截取目录页附近文本；找不到目录时取前 20 页。"""
    import pymupdf

    with pymupdf.open(stream=io.BytesIO(bytes(file_bytes)), filetype="pdf") as doc:
        pages = [page.get_text("text") for page in doc]
    toc_index = next((i for i, text in enumerate(pages[:10]) if "目录" in text), -1)
    if toc_index >= 0:
        selected = pages[toc_index:toc_index + 3]
    else:
        selected = pages[:min(20, len(pages))]
    return "\n".join(selected).strip()[:8000]


def parse_ai_chapters(raw: str, page_count: int) -> list[dict]:
    """校验 AI 返回的章节 JSON。"""
    cleaned = strip_code_fence(raw)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError("AI 没有返回合法的章节 JSON。") from exc
    if not isinstance(data, list) or not data:
        raise ValueError("AI 没有识别到章节。")

    result = []
    for item in data:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        try:
            level = int(item.get("level", 1))
            page = int(item.get("page", 1))
        except (TypeError, ValueError) as exc:
            raise ValueError("AI 返回的章节层级或页码不是数字。") from exc
        if not title:
            raise ValueError("AI 返回了空章节标题。")
        if not 1 <= level <= 3:
            raise ValueError("AI 返回的章节层级超出 1-3。")
        if not 1 <= page <= int(page_count):
            raise ValueError("AI 返回的章节页码超出 PDF 页数。")
        result.append({"title": title[:120], "level": level, "page": page})
    if not result:
        raise ValueError("AI 没有识别到有效章节。")
    return result


def detect_pdf_chapters(file_bytes: bytes, chat_func) -> list[dict]:
    """用目录页或前 20 页请求 AI 识别章节。"""
    import pymupdf

    with pymupdf.open(stream=io.BytesIO(bytes(file_bytes)), filetype="pdf") as doc:
        page_count = len(doc)
    source = build_toc_source_text(file_bytes)
    if not source:
        raise ValueError("PDF 中没有可用于识别目录的文字。")
    system_prompt = (
        "你是中小学教材目录分析专家。只根据给定目录或前几页识别章节，"
        "不要把正文段落识别成章节。只返回 JSON 数组。"
    )
    user_prompt = (
        f"PDF共 {page_count} 页。\n"
        "每个元素格式为 {\"title\":\"章节名\",\"level\":1,\"page\":1}。\n"
        f"目录或前20页内容如下：\n{source}"
    )
    raw = chat_func(system_prompt, user_prompt)
    return parse_ai_chapters(raw, page_count)


def build_chapters_from_pdf_pages(file_bytes: bytes, chapters: list[dict]) -> list[dict]:
    """按章节起始页和下一章起始页组装章节正文。"""
    import pymupdf

    normalized = []
    for item in chapters:
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        try:
            page = int(item.get("page", 1))
            level = int(item.get("level", 1))
        except (TypeError, ValueError):
            continue
        normalized.append({"title": title, "level": min(3, max(1, level)), "page": page})
    normalized.sort(key=lambda item: (item["page"], item["level"], item["title"]))

    with pymupdf.open(stream=io.BytesIO(bytes(file_bytes)), filetype="pdf") as doc:
        total = len(doc)
        page_texts = [page.get_text("text") for page in doc]

    result = []
    for index, item in enumerate(normalized):
        start = min(max(item["page"], 1), total)
        next_page = normalized[index + 1]["page"] if index + 1 < len(normalized) else total + 1
        end = min(max(next_page, start), total + 1)
        content = _normalize_text("\n".join(page_texts[start - 1:end - 1]))
        result.append({
            "title": item["title"],
            "level": item["level"],
            "page": start,
            "content": content,
        })
    return result


def materialize_data_editor(source_df: pd.DataFrame, value=None) -> pd.DataFrame:
    """把 data_editor 返回值归一成 DataFrame。

    正常运行时 Streamlit 返回 DataFrame；AppTest/直接读取 key 时可能拿到
    DataEditorState，需要按 edited_rows、added_rows、deleted_rows 重建。
    """
    if isinstance(value, pd.DataFrame):
        return value.copy()

    df = source_df.copy()
    if value is None:
        return df

    edited_rows = getattr(value, "edited_rows", None)
    added_rows = getattr(value, "added_rows", None)
    deleted_rows = getattr(value, "deleted_rows", None)
    if edited_rows is None and isinstance(value, dict):
        edited_rows = value.get("edited_rows", {})
        added_rows = value.get("added_rows", [])
        deleted_rows = value.get("deleted_rows", [])

    # edited_rows 和 deleted_rows 的行号都指向原始 DataFrame，先编辑后删除。
    for row_index, changes in (edited_rows or {}).items():
        row_index = int(row_index)
        if 0 <= row_index < len(df) and isinstance(changes, dict):
            for column, new_value in changes.items():
                if column in df.columns:
                    df.loc[df.index[row_index], column] = new_value

    for row_index in sorted({int(x) for x in (deleted_rows or [])}, reverse=True):
        if 0 <= row_index < len(df):
            df.drop(df.index[row_index], inplace=True)

    for added in added_rows or []:
        if isinstance(added, dict):
            row = {column: added.get(column) for column in df.columns}
            df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    return df


def chapter_editor_dataframe(chapters: list[dict], editable_page: bool = True) -> pd.DataFrame:
    """把章节转成可编辑表格数据；原序号用于非 PDF 删除后保留原文内容。"""
    rows = []
    for index, chapter in enumerate(chapters):
        rows.append({
            "章节标题": str(chapter.get("title") or ""),
            "层级": int(chapter.get("level") or 1),
            "页码": int(chapter.get("page") or 1) if editable_page else 1,
            "原序号": index,
        })
    if not rows:
        rows.append({"章节标题": "全文", "层级": 1, "页码": 1, "原序号": 0})
    return pd.DataFrame(rows)


def chapters_from_editor(rule_chapters: list[dict], rows: list[dict],
                         file_type: str, source_bytes: bytes | None = None) -> list[dict]:
    """合并老师在章节表格中的修改。"""
    edited = []
    for row in rows:
        title = str(row.get("章节标题") or "").strip()
        if not title:
            continue
        try:
            level = int(row.get("层级", 1))
            page = int(row.get("页码", 1))
        except (TypeError, ValueError):
            continue
        try:
            original_index = int(row.get("原序号", -1))
        except (TypeError, ValueError):
            original_index = -1
        edited.append({
            "title": title,
            "level": min(3, max(1, level)),
            "page": max(1, page),
            "原序号": original_index,
        })

    if file_type == "pdf" and source_bytes:
        return build_chapters_from_pdf_pages(source_bytes, edited)

    result = []
    for item in edited:
        original_index = int(item.get("原序号", -1))
        content = rule_chapters[original_index].get("content", "") if 0 <= original_index < len(rule_chapters) else ""
        result.append({"title": item["title"], "level": item["level"], "content": content})
    return result
