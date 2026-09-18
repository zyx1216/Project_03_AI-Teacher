# -*- coding: utf-8 -*-
"""
AI 数学教师工作台 —— Streamlit 主入口。

职责：
1. 启动时初始化数据目录和数据库；
2. 用侧边栏做 4 个页面的导航；
3. 把主内容区交给对应的页面模块渲染。

页面规划（按开发指令）：
- 📚 备课工作台（阶段 2）
- 📝 作业工作台（阶段 3）
- 📊 学情工作台（阶段 1）
- ⚙️ 设置（阶段 4 完善）
"""

import streamlit as st

import config
from utils.db import init_db
from modules import analysis, homework, lesson_plan, settings

# 启动时确保目录存在、9 张表就绪（幂等操作，不会清空数据）
init_db()

# 页面基础设置
st.set_page_config(
    page_title=config.APP_NAME,
    page_icon="📐",
    layout="wide",
)

# 侧边栏导航
st.sidebar.title("📐 AI 数学教师工作台")
page = st.sidebar.radio(
    label="功能导航",
    options=["📚 备课工作台", "📝 作业工作台", "📊 学情工作台", "⚙️ 设置"],
    index=0,
    label_visibility="collapsed",
)
st.sidebar.caption(f"版本 v{config.APP_VERSION}")

# 根据选择渲染对应页面（每个模块暴露 show() 函数）
if page == "📚 备课工作台":
    lesson_plan.show()
elif page == "📝 作业工作台":
    homework.show()
elif page == "📊 学情工作台":
    analysis.show()
else:
    settings.show()