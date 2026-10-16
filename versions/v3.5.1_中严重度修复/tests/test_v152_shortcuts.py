# -*- coding: utf-8 -*-
"""快捷键纯函数测试（v1.9.0 扩展）。"""
from utils.keyboard_shortcuts import shortcut_js


def test_shortcut_js_bindings():
    js = shortcut_js()
    # Ctrl+1/2/3：首页 / 教学日历 / 设置（v1.9.0 起第 3 项是设置）
    for target in ("首页", "教学日历", "设置"):
        assert f"clickButtonContaining('{target}')" in js
    # Ctrl+4~9：当前组内子功能
    assert "pickSub(" in js
    # Ctrl+N/S/F/Z/Y/K
    for key in ("n", "s", "f", "z", "y", "k"):
        assert f"'{key}'" in js
    # 通过 window.parent 操作
    assert "window.parent.document" in js
    assert "preventDefault" in js
    # 输入框聚焦时不触发
    assert "typingTarget" in js
    assert "<script>" in js
