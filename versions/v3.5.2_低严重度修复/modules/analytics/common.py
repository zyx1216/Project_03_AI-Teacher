# -*- coding: utf-8 -*-
"""学情跨 Tab 公共组件兼容导出。"""
def __getattr__(name):
    import modules.analysis as _impl
    return getattr(_impl, name)
