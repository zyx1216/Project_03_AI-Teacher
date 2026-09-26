# -*- coding: utf-8 -*-
"""快捷键注入（v1.9.0 扩展版）。

支持：
- Ctrl+1/2/3：首页 / 教学日历 / 设置；
- Ctrl+4 至 Ctrl+9：当前组内第 1-6 个子功能；
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
  function visibleExpanderRadio() {
    // 返回当前展开组 expander 内可见的 radio 选项标签。
    var doc = parentDoc();
    var radios = doc.querySelectorAll('[data-testid="stSidebar"] [role="radiogroup"]');
    var result = [];
    for (var i = 0; i < radios.length; i++) {
      var box = radios[i].closest('[data-testid="stExpander"]');
      if (box && box.getAttribute('aria-expanded') === 'true') {
        var labels = radios[i].querySelectorAll('label');
        for (var j = 0; j < labels.length; j++) {
          if (labels[j].offsetParent !== null) result.push(labels[j]);
        }
      }
    }
    return result;
  }
  function pickSub(index) {
    var labels = visibleExpanderRadio();
    if (labels[index]) labels[index].click();
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
