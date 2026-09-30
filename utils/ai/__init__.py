# -*- coding: utf-8 -*-
"""utils 分类兼容包，不物理移动原文件。"""
from __future__ import annotations
import importlib
_MODULES = {
    "llm_client": "utils.llm_client",
    "rag_service": "utils.rag_service",
    "knowledge_graph_service": "utils.knowledge_graph_service",
}
def __getattr__(name):
    target = _MODULES.get(name)
    if target is None:
        raise AttributeError(name)
    return importlib.import_module(target)
def __dir__():
    return sorted(list(globals().keys()) + list(_MODULES))
