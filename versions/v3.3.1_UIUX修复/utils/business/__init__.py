# -*- coding: utf-8 -*-
"""utils 分类兼容包，不物理移动原文件。"""
from __future__ import annotations
import importlib
_MODULES = {
    "question_service": "utils.question_service",
    "grading_service": "utils.grading_service",
    "homework_service": "utils.homework_service",
    "review_service": "utils.review_service",
    "variation_service": "utils.variation_service",
    "tiered_homework_service": "utils.tiered_homework_service",
}
def __getattr__(name):
    target = _MODULES.get(name)
    if target is None:
        raise AttributeError(name)
    return importlib.import_module(target)
def __dir__():
    return sorted(list(globals().keys()) + list(_MODULES))
