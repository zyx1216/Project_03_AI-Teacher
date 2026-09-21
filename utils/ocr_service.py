# -*- coding: utf-8 -*-
"""
扫描件 PDF 的本地 OCR 服务。

默认引擎为 RapidOCR（ONNX Runtime）。页面只调用本模块，不直接依赖具体引擎；
以后要换成 PaddleOCR 或云端 OCR 时，只改这里的引擎适配。
"""

from __future__ import annotations

import io
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

OCR_FAILURE_MESSAGE = "OCR识别失败，请检查PDF质量，或改用文字版PDF/Word"


class OCRError(Exception):
    """OCR 引擎失败或识别结果为空时抛出，界面显示固定中文提示。"""


_ENGINE: Any | None = None


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
    """懒加载 OCR 引擎，避免导入模块或启动应用时立即加载模型。"""
    global _ENGINE
    if _ENGINE is None:
        from rapidocr import RapidOCR

        _ENGINE = RapidOCR()
    return _ENGINE


def _extract_texts(result: Any) -> list[str]:
    """从 RapidOCR 返回对象中提取文本行。"""
    txts = getattr(result, "txts", None)
    if not txts:
        return []
    return [str(text).strip() for text in txts if str(text).strip()]


def ocr_pdf(file_bytes_or_path: bytes | str | Path, dpi: int = 200) -> str:
    """逐页渲染 PDF 并做 OCR，返回合并后的全文。"""
    engine = get_engine()
    page_texts: list[str] = []

    try:
        with _open_pdf(file_bytes_or_path) as doc:
            for page in doc:
                pixmap = page.get_pixmap(dpi=dpi)
                result = engine(pixmap.tobytes("png"))
                lines = _extract_texts(result)
                if lines:
                    page_texts.append("\n".join(lines))
    except OCRError:
        raise
    except Exception as exc:
        raise OCRError(OCR_FAILURE_MESSAGE) from exc

    text = "\n\n".join(page_texts).strip()
    if not text:
        raise OCRError(OCR_FAILURE_MESSAGE)
    return text

