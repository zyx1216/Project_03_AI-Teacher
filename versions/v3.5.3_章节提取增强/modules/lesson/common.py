# -*- coding: utf-8 -*-
"""备课区跨 Tab 公共组件兼容导出。"""
def __getattr__(name):
    import modules.lesson_plan as _impl
    return getattr(_impl, name)
