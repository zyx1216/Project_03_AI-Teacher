# -*- coding: utf-8 -*-
"""
设置页面。

- 主模型（阶段 1）：考试分析、学情总结；
- 内容生成模型（阶段 2）：教案生成、AI 出题，留空时回退主模型；
- Embedding 模型（阶段 2）：课本 RAG 向量化，默认火山方舟 OpenAI 兼容地址；
- API Key 统一存 Windows 凭据管理器，Base URL/模型名存本地配置文件。
数据备份/恢复/清空在「数据管理」分区。
"""

import streamlit as st

import config
from utils import llm_client, backup_service

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
    st.caption("建议用中文能力更强的通用模型，如 deepseek-chat、doubao-pro。"
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


def _backup_restore_panel():
    """数据备份 / 恢复 / 清空。所有文件操作都包 try-except，失败给友好提示。"""
    st.subheader("数据管理（备份 / 恢复 / 清空）")
    st.caption("数据都在本机项目目录的 `data/` 下（数据库、上传资料、向量库、AI 非敏感配置）。"
               "API Key 存在 Windows 凭据管理器，不在备份包里，换电脑需重新填写。")

    tab_backup, tab_restore, tab_wipe = st.tabs(["📦 备份", "♻️ 恢复", "🗑️ 清空业务数据"])

    # ---- 备份 ----
    with tab_backup:
        st.write("把整个 data 目录打包成一个带时间戳的 zip，可下载保存到 U 盘或网盘。")
        c1, c2 = st.columns(2)
        if c1.button("⬇️ 生成并下载备份", type="primary"):
            try:
                blob = backup_service.backup_data_dir()
                st.download_button(
                    "💾 保存备份 zip", blob,
                    file_name=backup_service.default_backup_name(),
                    mime="application/zip")
                st.success(f"备份已生成（{len(blob) / 1024:.0f} KB），点上方按钮保存。")
            except Exception as exc:
                st.error(f"备份失败：{exc}")
        if c2.button("📁 在本机留一份（data/backups/）"):
            try:
                path = backup_service.save_backup_to_disk()
                st.success(f"已保存到：`{path}`")
            except Exception as exc:
                st.error(f"备份失败：{exc}")

    # ---- 恢复 ----
    with tab_restore:
        st.error("恢复会用备份内容**整体覆盖**当前 data 目录；当前目录会先自动改名成 "
                 "`data.bak-时间戳` 留底。恢复成功后请**重启 Streamlit**。")
        uploaded = st.file_uploader("选择之前生成的备份 zip", type=["zip"],
                                    key="restore_zip")
        if uploaded is not None and st.button("♻️ 确认恢复", type="primary"):
            import tempfile, os
            tmp_path = None
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
                    tmp.write(uploaded.getvalue())
                    tmp_path = tmp.name
                manifest = backup_service.restore_from_zip(tmp_path)
                backup_service.prune_backup_dirs(keep=3)
                st.success(f"恢复完成（备份版本 v{manifest.get('version', '?')}）。"
                           "请关闭 Streamlit 后重新启动，再刷新页面。")
            except (ValueError, FileNotFoundError) as exc:
                st.error(f"没有改动现有数据：{exc}")
            except Exception as exc:
                st.error(f"恢复失败，旧数据已尝试自动改回：{exc}")
            finally:
                if tmp_path and os.path.exists(tmp_path):
                    os.remove(tmp_path)

    # ---- 清空 ----
    with tab_wipe:
        st.error("这会删除**全部学生、成绩、作业、题目、教案、资料、反思、评语**等 13 张业务表数据，"
                 "且不可撤销。AI 配置、API Key 和已有备份 zip 会保留。")
        st.write("为防误触，请在下面输入 **确认清空** 四个字，再点删除按钮。")
        confirm_text = st.text_input("输入确认文字", key="wipe_confirm_text")
        if st.button("🗑️ 清空全部业务数据", type="primary",
                     disabled=(confirm_text.strip() != "确认清空")):
            st.session_state["wipe_armed"] = True
        if st.session_state.get("wipe_armed"):
            st.error("最后确认：真的要清空全部业务数据吗？建议先做一次备份。")
            d1, d2 = st.columns(2)
            if d1.button("✅ 我已备份，确认删除", key="wipe_final_ok"):
                try:
                    backup_service.wipe_business_data()
                    st.session_state.pop("wipe_armed", None)
                    st.success("业务数据已清空，AI 配置和备份保留。请重启 Streamlit。")
                except Exception as exc:
                    st.error(f"清空失败：{exc}")
            if d2.button("取消", key="wipe_final_cancel"):
                st.session_state.pop("wipe_armed", None)
                st.rerun()



def _about_panel():
    """关于信息。"""
    st.subheader("关于")
    st.write(f"**项目名称：** {config.APP_NAME}")
    st.write(f"**当前版本：** v{config.APP_VERSION}")
    st.write("**技术栈：** Streamlit + SQLAlchemy + SQLite + ChromaDB，本地单机运行。")
    st.markdown(
        """
        **四大模块（v1.3.0）**
        - 学情：学生管理、成绩管理、考试分析、趋势分析、学生画像、教学反思、期末评语
        - 备课：资料管理、AI 备课、AI 出题、题库管理、PPT 生成
        - 作业：作业管理、成绩录入、作业分析、错题本
        - 设置：主模型 / 内容模型 / 向量模型配置、数据备份恢复清空
        - 共 13 张数据表；备课、作业等功能各自选择并记住学科，应用标题保持固定；详细操作见项目根目录的 `USAGE.md`。

        **启动方式**：必须用 `streamlit run app.py`，不要直接运行 app.py。
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
    _backup_restore_panel()
    st.divider()
    _about_panel()
