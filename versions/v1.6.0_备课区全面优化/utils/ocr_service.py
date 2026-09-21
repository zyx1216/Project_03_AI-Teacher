# -*- coding: utf-8 -*-
"""
PDF 扫描件识别服务。

只封装“判定扫描件 + 页数 + 逐页 OCR”三件事，页面不直接依赖 RapidOCR。
后台线程可通过 threading.Event 在页与页之间停止。
"""

from __future__ import annotations

import io
import threading
from pathlib import Path
from typing import Any

import pymupdf

OCR_FAILURE_MESSAGE = "OCR识别失败，请检查PDF质量，或改用文字版PDF/Word"


class OCRError(Exception):
    """OCR 模型、PDF 或识别结果异常。"""


_ENGINE = None
_LOCAL_ENGINES = threading.local()


def _open_pdf(file_bytes_or_path: bytes | str | Path):
    """统一打开 bytes/路径，避免 PyMuPDF 新版本不接受裸 bytes。"""
    if isinstance(file_bytes_or_path, (bytes, bytearray)):
        doc = pymupdf.open(stream=io.BytesIO(bytes(file_bytes_or_path)), filetype="pdf")
    else:
        doc = pymupdf.open(file_bytes_or_path)
    return doc


def _page_texts(doc: Any) -> list[str]:
    """读取每页纯文本，用于判断扫描件。"""
    return [page.get_text("text").strip() for page in doc]


def is_scanned_pdf(file_bytes_or_path: bytes | str | Path,
                   min_chars_per_page: int = 20) -> bool:
    """平均有效字符过少，或存在空文本页，即按扫描件处理。"""
    with _open_pdf(file_bytes_or_path) as doc:
        if len(doc) == 0:
            return True
        texts = _page_texts(doc)
    average_chars = sum(len(text) for text in texts) / len(texts)
    return average_chars < min_chars_per_page or any(not text for text in texts)


def get_engine() -> Any:
    """获取当前线程的 OCR 引擎，避免多任务共享同一引擎对象。"""
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE
    engine = getattr(_LOCAL_ENGINES, "engine", None)
    if engine is None:
        from rapidocr import RapidOCR

        engine = RapidOCR()
        _LOCAL_ENGINES.engine = engine
    return engine


def _extract_texts(result: Any) -> list[str]:
    """提取 RapidOCR 3.x 返回对象中的文本行。"""
    txts = getattr(result, "txts", None)
    if not txts:
        return []
    return [str(text).strip() for text in txts if str(text).strip()]


def pdf_page_count(file_bytes_or_path: bytes | str | Path) -> int:
    """返回 PDF 页数。"""
    with _open_pdf(file_bytes_or_path) as doc:
        return len(doc)


def ocr_pdf(file_bytes_or_path: bytes | str | Path, dpi: int = 200,
            progress_callback=None, engine: Any | None = None,
            stop_event: threading.Event | None = None) -> str:
    """逐页渲染并 OCR；收到停止事件后，在当前页结束后停止。"""
    engine = engine or get_engine()
    page_texts: list[str] = []

    try:
        with _open_pdf(file_bytes_or_path) as doc:
            total = len(doc)
            for index, page in enumerate(doc):
                if stop_event is not None and stop_event.is_set():
                    raise RuntimeError("已停止识别")
                pixmap = page.get_pixmap(dpi=dpi)
                result = engine(pixmap.tobytes("png"))
                lines = _extract_texts(result)
                if lines:
                    page_texts.append("\n".join(lines))
                if progress_callback is not None:
                    progress_callback(index + 1, total)
                if stop_event is not None and stop_event.is_set():
                    raise RuntimeError("已停止识别")
    except OCRError:
        raise
    except Exception as exc:
        if stop_event is not None and stop_event.is_set():
            raise RuntimeError("已停止识别") from exc
        raise OCRError(OCR_FAILURE_MESSAGE) from exc

    text = "\n\n".join(page_texts).strip()
    if not text:
        if stop_event is not None and stop_event.is_set():
            raise RuntimeError("已停止识别")
        raise OCRError(OCR_FAILURE_MESSAGE)
    return text
