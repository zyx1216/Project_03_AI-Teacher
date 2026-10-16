# -*- coding: utf-8 -*-
"""学业测评 Tab 兼容导出。"""
from modules.homework import tab_wrong_book
def __getattr__(name):
    import modules.homework as _impl
    return getattr(_impl, name)
