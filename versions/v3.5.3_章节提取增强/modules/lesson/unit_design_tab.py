# -*- coding: utf-8 -*-
"""单元整体设计 Tab 的兼容导出。"""
from modules.lesson_plan import tab_unit_design
def __getattr__(name):
    import modules.lesson_plan as _impl
    return getattr(_impl, name)
