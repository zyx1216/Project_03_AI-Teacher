# -*- coding: utf-8 -*-
"""全局错误处理（v2.8.0）。

把未捕获异常转成友好中文提示（不回显技术栈/路径），并写入错误日志。
"""

from __future__ import annotations

import traceback

FRIENDLY_MESSAGE = "页面处理失败，请重试；若反复出现可在「⚙️ 设置 → 🧯 错误日志」查看记录。"


def friendly_message(exc: BaseException | None = None,
                     page: str | None = None) -> str:
    """返回给用户看的中文提示（不含路径/堆栈/密钥）。"""
    hint = FRIENDLY_MESSAGE
    if page:
        hint = f"「{page}」{hint}"
    return hint


def _safe_context(exc, context) -> dict:
    """构造安全的错误上下文（只保留页面等非敏感字段）。"""
    ctx = {}
    for key, value in (context or {}).items():
        text = str(value)
        if len(text) > 100:
            text = text[:100] + "…"
        ctx[str(key)] = text
    return ctx


def handle_page_error(page: str, exc: BaseException,
                      rerun=None, go_home=None) -> str:
    """记录错误并提供友好提示与恢复按钮（在当前页面渲染）。

    返回给调用方的友好提示文本。失败不抛出。
    """
    try:
        from utils import error_logger
        error_logger.log_error(exc, _safe_context(exc, {"页面": page}))
    except Exception:  # noqa: BLE001 —— 记录失败不影响提示
        pass
    msg = friendly_message(exc, page)
    try:
        import streamlit as st
        st.error(msg)
        c1, c2 = st.columns(2)
        if c1.button("🔁 重试", key=f"err_retry_{page}"):
            if callable(rerun):
                rerun()
            else:
                st.rerun()
        if c2.button("🏠 返回首页", key=f"err_home_{page}"):
            if callable(go_home):
                go_home()
            else:
                st.session_state["app_top_page"] = "🏠 首页"
                st.rerun()
    except Exception:  # noqa: BLE001 —— 无 Streamlit 上下文时只返回文本
        pass
    return msg


def error_summary(exc: BaseException) -> str:
    """异常类型 + 首行信息（用于日志，不含完整堆栈）。"""
    return f"{type(exc).__name__}: {str(exc).splitlines()[0] if str(exc) else ''}"


def format_traceback(exc: BaseException) -> str:
    """完整堆栈（只写日志，不展示给用户）。"""
    return "".join(traceback.format_exception(type(exc), exc,
                                              exc.__traceback__))
