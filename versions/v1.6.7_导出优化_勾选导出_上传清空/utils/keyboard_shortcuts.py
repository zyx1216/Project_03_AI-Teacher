# -*- coding: utf-8 -*-
"""快捷键注入（v1.5.6）。

只做页面导航和聚焦搜索：Ctrl+1/2/3/4、Ctrl+K；不绑定浏览器保留的 Ctrl+N/S。
JS 在 streamlit.components.v1 的同源 iframe 内，通过 window.parent.document 操作侧边栏。
"""

from __future__ import annotations


def shortcut_js() -> str:
    """返回注入用的 JS（纯函数，便于单测）。"""
    return r"""
<script>
(function () {
  function sidebarLabel(text) {
    var doc = window.parent.document;
    var labels = doc.querySelectorAll('[data-testid="stSidebar"] label');
    for (var i = 0; i < labels.length; i++) {
      if (labels[i].textContent.indexOf(text) !== -1) return labels[i];
    }
    return null;
  }
  function clickNav(text) {
    var label = sidebarLabel(text);
    if (label) label.click();
  }
  function focusSearch() {
    var doc = window.parent.document;
    var scope = doc.querySelector('[data-testid="stMain"]') || doc;
    var fields = scope.querySelectorAll('input, textarea');
    for (var i = 0; i < fields.length; i++) {
      var el = fields[i];
      if (el.disabled || el.readOnly) continue;
      var rect = el.getBoundingClientRect();
      if (rect.width > 0 && rect.height > 0) { el.focus(); break; }
    }
  }
  window.parent.document.addEventListener('keydown', function (e) {
    if (!e.ctrlKey) return;
    var key = e.key;
    if (key === '1') { e.preventDefault(); clickNav('首页'); }
    else if (key === '2') { e.preventDefault(); clickNav('教学日历'); }
    else if (key === '3') { e.preventDefault(); clickNav('备课'); }
    else if (key === '4') { e.preventDefault(); clickNav('作业'); }
    else if (key === 'k') { e.preventDefault(); focusSearch(); }
  });
})();
</script>
"""
