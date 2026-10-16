# -*- coding: utf-8 -*-
"""资料管理 Tab 的兼容导出。"""
from modules.lesson_plan import tab_materials
def __getattr__(name):
    import modules.lesson_plan as _impl
    return getattr(_impl, name)
