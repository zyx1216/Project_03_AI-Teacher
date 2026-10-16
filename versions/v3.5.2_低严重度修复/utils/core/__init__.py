# -*- coding: utf-8 -*-
"""utils 分类兼容包，不物理移动原文件。"""
from __future__ import annotations
import importlib
_MODULES = {
    "db": "utils.db",
    "error_handler": "utils.error_handler",
    "cache_service": "utils.cache_service",
    "logger_service": "utils.logger_service",
    "monitor_service": "utils.monitor_service",
}
def __getattr__(name):
    target = _MODULES.get(name)
    if target is None:
        raise AttributeError(name)
    return importlib.import_module(target)
def __dir__():
    return sorted(list(globals().keys()) + list(_MODULES))
