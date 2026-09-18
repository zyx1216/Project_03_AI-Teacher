# -*- coding: utf-8 -*-
"""
设置页面。

阶段 0 只展示项目信息与数据库文件位置；
LLM API 配置、数据备份/恢复在后续阶段实现。
"""

import streamlit as st

import config


def show() -> None:
    """渲染设置页面。"""
    st.title("⚙️ 设置")

    st.subheader("关于")
    st.write(f"**项目名称：** {config.APP_NAME}")
    st.write(f"**当前版本：** v{config.APP_VERSION}（项目骨架）")
    st.write("**技术栈：** Streamlit + SQLAlchemy + SQLite，本地单机运行。")

    st.subheader("数据存储位置")
    st.write(f"数据库文件：`{config.DB_PATH}`")
    st.write(f"上传文件目录：`{config.UPLOAD_DIR}`")
    st.write(f"导出文件目录：`{config.EXPORT_DIR}`")

    st.subheader("后续开放")
    st.markdown(
        """
        - LLM API 配置（API Key、模型名称、Base URL、连接测试）
        - 数据备份与恢复（一键打包 data 目录）
        """
    )