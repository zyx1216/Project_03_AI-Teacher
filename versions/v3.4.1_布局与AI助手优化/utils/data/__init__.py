# -*- coding: utf-8 -*-
"""utils 分类兼容包，不物理移动原文件。"""
from __future__ import annotations
import importlib
_MODULES = {
    "excel_handler": "utils.excel_handler",
    "score_doc_parser": "utils.score_doc_parser",
    "ocr_service": "utils.ocr_service",
    "material_service": "utils.material_service",
}
def __getattr__(name):
    target = _MODULES.get(name)
    if target is None:
        raise AttributeError(name)
    return importlib.import_module(target)
def __dir__():
    return sorted(list(globals().keys()) + list(_MODULES))
