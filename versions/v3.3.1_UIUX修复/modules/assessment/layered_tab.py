# -*- coding: utf-8 -*-
"""学业测评 Tab 兼容导出。"""
from modules.homework import tab_tiered_homework
def __getattr__(name):
    import modules.homework as _impl
    return getattr(_impl, name)
