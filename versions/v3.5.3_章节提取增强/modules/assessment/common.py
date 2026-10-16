# -*- coding: utf-8 -*-
"""学业测评跨 Tab 公共组件兼容导出。"""
def __getattr__(name):
    import modules.homework as _impl
    return getattr(_impl, name)
