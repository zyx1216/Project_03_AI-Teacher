# -*- coding: utf-8 -*-
"""v1.5.7 扫描件 PDF OCR 服务测试。"""

import io
from types import SimpleNamespace

import pytest

from utils import material_service as mat
from utils import ocr_service as ocr


def _pdf_bytes(text: str | None = None) -> bytes:
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    if text is not None:
        page.insert_text((72, 72), text, fontsize=12)
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


class FakeEngine:
    def __init__(self, texts=("第一章 函数", "这是 OCR 识别出的正文。"),
                 error: Exception | None = None):
        self.texts = texts
        self.error = error
        self.images = []

    def __call__(self, image: bytes):
        self.images.append(image)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(txts=self.texts)


def test_text_pdf_is_not_scanned():
    pdf = _pdf_bytes("1234567890abcdefghij")  # 整 20 个字符
    assert ocr.is_scanned_pdf(pdf, min_chars_per_page=20) is False


def test_short_text_pdf_is_scanned():
    pdf = _pdf_bytes("1234567890abcdefghi")  # 19 个字符
    assert ocr.is_scanned_pdf(pdf, min_chars_per_page=20) is True


def test_blank_pdf_is_scanned():
    assert ocr.is_scanned_pdf(_pdf_bytes()) is True


def test_ocr_pdf_success_with_monkeypatched_engine(monkeypatch):
    engine = FakeEngine()
    monkeypatch.setattr(ocr, "get_engine", lambda: engine)

    text = ocr.ocr_pdf(_pdf_bytes(), dpi=120)

    assert "第一章 函数" in text
    assert "OCR 识别出的正文" in text
    assert engine.images
    assert isinstance(engine.images[0], bytes)


def test_ocr_pdf_engine_error_raises_ocr_error(monkeypatch):
    engine = FakeEngine(error=RuntimeError("model broken"))
    monkeypatch.setattr(ocr, "get_engine", lambda: engine)

    with pytest.raises(ocr.OCRError, match=ocr.OCR_FAILURE_MESSAGE):
        ocr.ocr_pdf(_pdf_bytes())


def test_ocr_pdf_empty_result_raises_ocr_error(monkeypatch):
    engine = FakeEngine(texts=())
    monkeypatch.setattr(ocr, "get_engine", lambda: engine)

    with pytest.raises(ocr.OCRError, match=ocr.OCR_FAILURE_MESSAGE):
        ocr.ocr_pdf(_pdf_bytes())


def test_extract_pdf_with_ocr_skips_text_pdf(monkeypatch):
    pdf = _pdf_bytes("plain pdf body text with enough characters")

    def forbidden_ocr(_):
        raise AssertionError("文字版 PDF 不应触发 OCR")

    monkeypatch.setattr(ocr, "ocr_pdf", forbidden_ocr)

    result = mat.extract_pdf_with_ocr(pdf)

    assert result["ocr_used"] is False
    assert "plain pdf body" in result["text"]


def test_extract_pdf_with_ocr_handles_scanned_pdf(monkeypatch):
    engine = FakeEngine()
    monkeypatch.setattr(ocr, "get_engine", lambda: engine)

    result = mat.extract_pdf_with_ocr(_pdf_bytes())

    assert result["ocr_used"] is True
    assert "OCR 识别出的正文" in result["text"]
