# -*- coding: utf-8 -*-
"""
扫描件 PDF 的本地 OCR 服务。

默认引擎为 RapidOCR（ONNX Runtime）。页面只调用本模块，不直接依赖具体引擎；
以后要换成 PaddleOCR 或云端 OCR 时，只改这里的引擎适配。
"""

from __future__ import annotations

import io
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

OCR_FAILURE_MESSAGE = "OCR识别失败，请检查PDF质量，或改用文字版PDF/Word"


class OCRError(Exception):
    """OCR 引擎失败或识别结果为空时抛出，界面显示固定中文提示。"""


_ENGINE: Any | None = None
_LOCAL_ENGINES = threading.local()


@contextmanager
def _open_pdf(file_bytes_or_path: bytes | str | Path) -> Iterator[Any]:
    """统一处理 bytes/路径，兼容 PyMuPDF 1.28 的 stream 参数。"""
    import pymupdf

    if isinstance(file_bytes_or_path, (bytes, bytearray)):
        doc = pymupdf.open(stream=io.BytesIO(file_bytes_or_path), filetype="pdf")
    else:
        doc = pymupdf.open(file_bytes_or_path)
    try:
        yield doc
    finally:
        doc.close()


def _page_texts(doc: Any) -> list[str]:
    """读取每页纯文本，去掉空白后用于判断扫描件。"""
    return [page.get_text("text").strip() for page in doc]


def is_scanned_pdf(file_bytes_or_path: bytes | str | Path,
                   min_chars_per_page: int = 20) -> bool:
    """
    判断 PDF 是否为扫描件。

    口径：每页平均有效字符少于阈值，或存在完全没有文字的页，即按扫描件处理。
    """
    with _open_pdf(file_bytes_or_path) as doc:
        if len(doc) == 0:
            return True
        texts = _page_texts(doc)

    average_chars = sum(len(text) for text in texts) / len(texts)
    return average_chars < min_chars_per_page or any(not text for text in texts)


def get_engine() -> Any:
    """
    懒加载 OCR 引擎。

    全局已注入引擎时复用（测试用）；后台线程各自持有一个引擎，
    避免多个 OCR 任务共享 RapidOCR 对象做前后处理。
    """
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
    """从 RapidOCR 返回对象中提取文本行。"""
    txts = getattr(result, "txts", None)
    if not txts:
        return []
    return [str(text).strip() for text in txts if str(text).strip()]


def pdf_page_count(file_bytes_or_path: bytes | str | Path) -> int:
    """返回 PDF 页数，供后台任务初始化进度。"""
    with _open_pdf(file_bytes_or_path) as doc:
        return len(doc)


def ocr_pdf(file_bytes_or_path: bytes | str | Path, dpi: int = 200,
            progress_callback=None, engine: Any | None = None) -> str:
    """逐页渲染 PDF 并做 OCR，返回合并后的全文。"""
    engine = engine or get_engine()
    page_texts: list[str] = []

    try:
        with _open_pdf(file_bytes_or_path) as doc:
            for index, page in enumerate(doc):
                pixmap = page.get_pixmap(dpi=dpi)
                result = engine(pixmap.tobytes("png"))
                lines = _extract_texts(result)
                if lines:
                    page_texts.append("\n".join(lines))
                if progress_callback is not None:
                    progress_callback(index + 1, len(doc))
    except OCRError:
        raise
    except Exception as exc:
        raise OCRError(OCR_FAILURE_MESSAGE) from exc

    text = "\n\n".join(page_texts).strip()
    if not text:
        raise OCRError(OCR_FAILURE_MESSAGE)
    return text
