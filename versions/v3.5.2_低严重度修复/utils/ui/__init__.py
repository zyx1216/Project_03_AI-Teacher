# -*- coding: utf-8 -*-
"""utils 分类兼容包，不物理移动原文件。"""
from __future__ import annotations
import importlib
_MODULES = {
    "chart_service": "utils.chart_service",
    "full_score_service": "utils.full_score_service",
    "pagination_service": "utils.pagination_service",
    "ppt_generator": "utils.ppt_generator",
}
def __getattr__(name):
    target = _MODULES.get(name)
    if target is None:
        raise AttributeError(name)
    return importlib.import_module(target)
def __dir__():
    return sorted(list(globals().keys()) + list(_MODULES))
