# -*- coding: utf-8 -*-
"""快捷键注入（v1.9.0 扩展版）。

支持：
- Ctrl+1/2/3：首页 / 教学日历 / 设置；
- Ctrl+4 至 Ctrl+9：当前组内第 1-6 个子功能（按钮组）；
- Ctrl+N：按上下文新建；Ctrl+S：点当前页第一个保存按钮；
- Ctrl+F：聚焦第一个输入框；Ctrl+Z / Ctrl+Y：撤销 / 重做；
- Ctrl+K：聚焦搜索框。

事件目标为 input/textarea/contenteditable 时不触发全局快捷键。
Ctrl+N/S 是浏览器保留快捷键，这里只做尽力拦截。
JS 在 components.html 的同源 iframe 内，经 window.parent.document 操作。
"""

from __future__ import annotations


def shortcut_js() -> str:
    """返回注入用的 JS（纯函数，便于单测）。"""
    return r"""
<script>
(function () {
  function parentDoc() { return window.parent.document; }
  function typingTarget(e) {
    var t = e.target;
    if (!t) return false;
    var tag = t.tagName;
    return tag === 'INPUT' || tag === 'TEXTAREA' || t.isContentEditable;
  }
  function sidebarButtons() {
    return parentDoc().querySelectorAll('[data-testid="stSidebar"] button');
  }
  function clickButtonContaining(text) {
    var buttons = sidebarButtons();
    for (var i = 0; i < buttons.length; i++) {
      if (buttons[i].textContent.indexOf(text) !== -1
          && buttons[i].offsetParent !== null) {
        buttons[i].click();
        return true;
      }
    }
    return false;
  }
  function clickMainButtonContaining(text) {
    var scope = parentDoc().querySelector('[data-testid="stMain"]') || parentDoc();
    var buttons = scope.querySelectorAll('button');
    for (var i = 0; i < buttons.length; i++) {
      if (buttons[i].textContent.indexOf(text) !== -1
          && buttons[i].offsetParent !== null) {
        buttons[i].click();
        return true;
      }
    }
    return false;
  }
  function focusFirstField() {
    var scope = parentDoc().querySelector('[data-testid="stMain"]') || parentDoc();
    var fields = scope.querySelectorAll('input, textarea');
    for (var i = 0; i < fields.length; i++) {
      var el = fields[i];
      if (el.disabled || el.readOnly) continue;
      var rect = el.getBoundingClientRect();
      if (rect.width > 0 && rect.height > 0) { el.focus(); return true; }
    }
    return false;
  }
  function visibleExpanderButtons() {
    // v3.3.1：子功能改成按钮组，返回当前展开组 expander 内可见的子功能按钮。
    var doc = parentDoc();
    var boxes = doc.querySelectorAll('[data-testid="stSidebar"] [data-testid="stExpander"]');
    var result = [];
    for (var i = 0; i < boxes.length; i++) {
      if (boxes[i].getAttribute('aria-expanded') !== 'true') continue;
      var buttons = boxes[i].querySelectorAll('button');
      for (var j = 0; j < buttons.length; j++) {
        var btn = buttons[j];
        // 排除 expander 自己的折叠标题按钮。
        if (btn.closest('summary')) continue;
        if (btn.querySelector('[data-testid="stExpanderToggleIcon"]')) continue;
        if (btn.offsetParent !== null) result.push(btn);
      }
    }
    return result;
  }
  function pickSub(index) {
    var buttons = visibleExpanderButtons();
    if (buttons[index]) buttons[index].click();
  }

  parentDoc().addEventListener('keydown', function (e) {
    if (!e.ctrlKey || typingTarget(e)) return;
    var key = e.key.toLowerCase();
    if (key === '1') { e.preventDefault(); clickButtonContaining('首页'); }
    else if (key === '2') { e.preventDefault(); clickButtonContaining('教学日历'); }
    else if (key === '3') { e.preventDefault(); clickButtonContaining('设置'); }
    else if (key >= '4' && key <= '9') {
      e.preventDefault();
      pickSub(parseInt(key, 10) - 4);
    }
    else if (key === 'n') {
      e.preventDefault();
      if (!clickMainButtonContaining('新建')) clickButtonContaining('新建');
    }
    else if (key === 's') {
      e.preventDefault();
      clickMainButtonContaining('保存');
    }
    else if (key === 'f' || key === 'k') {
      e.preventDefault();
      focusFirstField();
    }
    else if (key === 'z') {
      e.preventDefault();
      clickButtonContaining('撤销');
    }
    else if (key === 'y') {
      e.preventDefault();
      clickButtonContaining('重做');
    }
  });
})();
</script>
"""


import json
from pathlib import Path
import config

SHORTCUT_CONFIG_PATH = config.DATA_DIR / "shortcut_config.json"


def default_config() -> dict:
    """快捷键默认配置。"""
    return {"enabled": True}


def load_shortcut_config(path: Path | str | None = None) -> dict:
    """读取快捷键配置；损坏或缺失回退默认，不覆盖原文件。"""
    target = Path(path or SHORTCUT_CONFIG_PATH)
    if not target.exists():
        return default_config()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default_config()
    result = default_config()
    if isinstance(raw, dict):
        result["enabled"] = bool(raw.get("enabled", True))
    return result


def save_shortcut_config(enabled: bool, path: Path | str | None = None) -> None:
    """保存快捷键启用状态。"""
    target = Path(path or SHORTCUT_CONFIG_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"enabled": bool(enabled)}, ensure_ascii=False, indent=2),
        encoding="utf-8")


def shortcuts_enabled(path: Path | str | None = None) -> bool:
    """是否启用全局快捷键。"""
    return bool(load_shortcut_config(path).get("enabled", True))
