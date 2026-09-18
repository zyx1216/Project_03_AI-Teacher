# -*- coding: utf-8 -*-
"""
设置页面。

- 主模型（阶段 1）：考试分析、学情总结；
- 内容生成模型（阶段 2）：教案生成、AI 出题，留空时回退主模型；
- Embedding 模型（阶段 2）：课本 RAG 向量化，默认火山方舟 OpenAI 兼容地址；
- API Key 统一存 Windows 凭据管理器，Base URL/模型名存本地配置文件。
数据备份/恢复在后续阶段实现。
"""

import streamlit as st

import config
from utils import llm_client

# 火山方舟 OpenAI 兼容接口默认地址（embedding 用，模型 ID 仍需用户填写）
VOLC_ARK_BASE = "https://ark.cn-beijing.volces.com/api/v3"


def _llm_config_panel():
    """主模型配置表单。"""
    st.subheader("主模型配置（学情分析 / 学情总结）")
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
            if api_key.strip():
                llm_client.set_api_key(api_key.strip())
            llm_client.save_llm_config(base_url, model)
            st.success("配置已保存。")
            st.rerun()
        except llm_client.LLMConfigError as exc:
            st.error(str(exc))

    if test_clicked:
        try:
            llm_client.save_llm_config(base_url, model)
            if api_key.strip():
                llm_client.set_api_key(api_key.strip())
            with st.spinner("正在连接模型，请稍候……"):
                ok, message = llm_client.test_connection()
            st.success(message) if ok else st.error(message)
        except llm_client.LLMConfigError as exc:
            st.error(str(exc))

    if clear_clicked:
        try:
            llm_client.set_api_key("")
            st.success("已清除保存的 API Key。")
            st.rerun()
        except llm_client.LLMConfigError as exc:
            st.error(str(exc))

def _content_config_panel():
    """内容生成模型配置（教案 / 出题）；留空则回退主模型。"""
    st.subheader("内容生成模型（教案 / AI 出题）")
    cfg = llm_client.load_llm_config()
    using_fallback = not (cfg.get("content_model") and cfg.get("content_base_url"))
    st.caption("建议用中文/数学能力更强的通用模型，如 deepseek-chat、doubao-pro。"
               "留空则自动使用上面的主模型。API Key 与主模型共用同一个。")
    if using_fallback:
        st.info("当前未单独配置，备课/出题将使用主模型。")

    with st.form("content_config_form"):
        content_base = st.text_input(
            "内容模型 Base URL", value=cfg.get("content_base_url", ""),
            placeholder="留空则用主模型地址")
        content_model = st.text_input(
            "内容模型名称", value=cfg.get("content_model", ""),
            placeholder="留空则用主模型，如 deepseek-chat")
        cs, ct = st.columns(2)
        save_clicked = cs.form_submit_button("💾 保存内容模型", type="primary")
        test_clicked = ct.form_submit_button("🔌 测试连接")

    if save_clicked:
        llm_client.save_llm_config(content_base_url=content_base,
                                   content_model=content_model)
        st.success("内容模型配置已保存。")
        st.rerun()

    if test_clicked:
        llm_client.save_llm_config(content_base_url=content_base,
                                   content_model=content_model)
        with st.spinner("正在连接内容模型……"):
            ok, message = llm_client.test_connection("content")
        st.success(message) if ok else st.error(message)


def _embedding_config_panel():
    """Embedding 模型配置（课本 RAG）；未配置时自动降级本地模型/关键词检索。"""
    st.subheader("向量模型 Embedding（课本检索）")
    cfg = llm_client.load_llm_config()
    ready = llm_client.embedding_config_ready()
    if ready:
        st.success("已配置云端向量模型。")
    else:
        st.warning("未配置：备课时会自动降级为本地向量模型，再不行用关键词检索，功能不会中断。")

    with st.form("embedding_config_form"):
        embed_base = st.text_input(
            "Embedding Base URL", value=cfg.get("embed_base_url", VOLC_ARK_BASE),
            help="火山方舟 OpenAI 兼容地址默认已填好；用其它服务改成对应地址。")
        embed_model = st.text_input(
            "Embedding 模型 ID", value=cfg.get("embed_model", ""),
            placeholder="在火山方舟开通后填写，如 doubao-embedding-...")
        es, _ = st.columns(2)
        save_clicked = es.form_submit_button("💾 保存向量模型", type="primary")

    if save_clicked:
        llm_client.save_llm_config(embed_base_url=embed_base, embed_model=embed_model)
        st.success("向量模型配置已保存。")
        st.rerun()


def _data_panel():
    """数据存储位置说明。"""
    st.subheader("数据存储位置")
    st.write(f"数据库文件：`{config.DB_PATH}`")
    st.write(f"上传文件目录：`{config.UPLOAD_DIR}`")
    st.write(f"导出文件目录：`{config.EXPORT_DIR}`")
    st.write(f"向量库目录：`{config.CHROMA_DIR}`")
    st.write(f"LLM 非敏感配置：`{llm_client.CONFIG_PATH}`")
    st.caption("API Key 不在这些文件里，它保存在 Windows 凭据管理器（服务名 math-ai-teacher）。")


def _about_panel():
    """关于信息。"""
    st.subheader("关于")
    st.write(f"**项目名称：** {config.APP_NAME}")
    st.write(f"**当前版本：** v{config.APP_VERSION}")
    st.write("**技术栈：** Streamlit + SQLAlchemy + SQLite + ChromaDB，本地单机运行。")
    st.markdown(
        """
        **已开放**
        - 学情工作台：学生管理、成绩管理、考试分析、趋势分析、学生画像
        - 备课工作台：资料管理、AI 备课、AI 出题、题库管理、PPT 生成
        - 主模型 / 内容模型 / 向量模型配置与连接测试

        **后续开放**
        - 作业工作台、数据一键备份 / 恢复
        """)


def show() -> None:
    """渲染设置页面。"""
    st.title("⚙️ 设置")
    _llm_config_panel()
    st.divider()
    _content_config_panel()
    st.divider()
    _embedding_config_panel()
    st.divider()
    _data_panel()
    st.divider()
    _about_panel()