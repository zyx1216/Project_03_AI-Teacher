# -*- coding: utf-8 -*-
"""v1.5.2 快捷键纯函数测试。"""
from utils.keyboard_shortcuts import shortcut_js


def test_shortcut_js_bindings():
    js = shortcut_js()
    # 导航 Ctrl+1/2/3/4 按 v1.5.6 后的主导航顺序
    for target in ("首页", "教学日历", "备课", "作业"):
        assert f"clickNav('{target}')" in js
    assert "clickNav('学情')" not in js
    assert "clickNav('设置')" not in js
    # 聚焦搜索 Ctrl+K
    assert "'k'" in js
    # 通过 window.parent 操作侧边栏
    assert "window.parent.document" in js
    assert "preventDefault" in js
    # 不绑定浏览器保留的 Ctrl+N / Ctrl+S
    assert "'n'" not in js
    assert "'s'" not in js
    assert "<script>" in js
