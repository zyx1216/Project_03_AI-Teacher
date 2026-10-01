# -*- coding: utf-8 -*-
"""学情 Tab 兼容导出。"""
from modules.analysis import tab_exam_analysis
def __getattr__(name):
    import modules.analysis as _impl
    return getattr(_impl, name)
