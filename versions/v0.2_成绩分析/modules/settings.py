# -*- coding: utf-8 -*-
"""
设置页面。

阶段 1：
- LLM API 配置：API Key 存 Windows 凭据管理器，Base URL/模型名存本地配置文件；
- 测试连接：真实发一条消息验证；
- 数据文件位置展示。
数据备份/恢复在后续阶段实现。
"""

import streamlit as st

import config
from utils import llm_client


def _llm_config_panel():
    """LLM 配置表单。"""
    st.subheader("LLM API 配置")
    cfg = llm_client.load_llm_config()
    has_key = bool(llm_client.get_api_key())

    if has_key:
        st.success("已保存 API Key（出于安全不显示原文，重新输入可覆盖）。")
    else:
        st.warning("还没有配置 API Key，AI 功能暂不可用。")

    with st.form("llm_config_form"):
        api_key = st.text_input(
            "API Key", type="password",
            placeholder=("已保存，留空保存则保持不变" if has_key else "粘贴你的 API Key"),
            help="Key 保存在 Windows 凭据管理器，不会写进项目文件、不会上传。")
        base_url = st.text_input(
            "API Base URL（OpenAI 兼容接口）",
            value=cfg.get("base_url", config.DEFAULT_API_BASE),
            help="DeepSeek 用 https://api.deepseek.com；其它兼容服务填对应地址。")
        model = st.text_input(
            "模型名称", value=cfg.get("model", config.DEFAULT_MODEL),
            help="如 deepseek-chat、qwen-turbo、doubao-pro 等，以服务商文档为准。")
        col_save, col_test, col_clear = st.columns(3)
        save_clicked = col_save.form_submit_button("💾 保存配置", type="primary")
        test_clicked = col_test.form_submit_button("🔌 测试连接")
        clear_clicked = col_clear.form_submit_button("🗑️ 清除已存 Key")

    if save_clicked:
        try:
            # Key 留空表示不动已有 Key；填了才覆盖
            if api_key.strip():
                llm_client.set_api_key(api_key.strip())
            llm_client.save_llm_config(base_url, model)
            st.success("配置已保存。")
            st.rerun()
        except llm_client.LLMConfigError as exc:
            st.error(str(exc))

    if test_clicked:
        # 先把表单里临时填的内容纳入：保存非敏感项，内存里临时用本次输入的 Key
        try:
            llm_client.save_llm_config(base_url, model)
            if api_key.strip():
                llm_client.set_api_key(api_key.strip())
            with st.spinner("正在连接模型，请稍候……"):
                ok, message = llm_client.test_connection()
            if ok:
                st.success(message)
            else:
                st.error(message)
        except llm_client.LLMConfigError as exc:
            st.error(str(exc))

    if clear_clicked:
        try:
            llm_client.set_api_key("")
            st.success("已清除保存的 API Key。")
            st.rerun()
        except llm_client.LLMConfigError as exc:
            st.error(str(exc))


def _data_panel():
    """数据存储位置与配置文件说明。"""
    st.subheader("数据存储位置")
    st.write(f"数据库文件：`{config.DB_PATH}`")
    st.write(f"上传文件目录：`{config.UPLOAD_DIR}`")
    st.write(f"导出文件目录：`{config.EXPORT_DIR}`")
    st.write(f"LLM 非敏感配置：`{llm_client.CONFIG_PATH}`")
    st.caption("API Key 不在这些文件里，它保存在 Windows 凭据管理器（服务名 math-ai-teacher）。")


def _about_panel():
    """关于信息。"""
    st.subheader("关于")
    st.write(f"**项目名称：** {config.APP_NAME}")
    st.write(f"**当前版本：** v{config.APP_VERSION}")
    st.write("**技术栈：** Streamlit + SQLAlchemy + SQLite，本地单机运行。")
    st.markdown(
        """
        **本阶段已开放**
        - 学情工作台：学生管理、成绩管理、考试分析、趋势分析、学生画像
        - LLM 配置与连接测试

        **后续开放**
        - 数据一键备份 / 恢复、清空数据
        - 备课、题库、作业工作台
        """)


def show() -> None:
    """渲染设置页面。"""
    st.title("⚙️ 设置")
    _llm_config_panel()
    st.divider()
    _data_panel()
    st.divider()
    _about_panel()