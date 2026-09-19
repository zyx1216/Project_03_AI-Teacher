# -*- coding: utf-8 -*-
"""
AI教学辅助 —— Streamlit 主入口。

职责：
1. 启动时初始化数据目录和数据库；
2. 用侧边栏做 4 个页面的导航；
3. 把主内容区交给对应的页面模块渲染。

页面规划（按开发指令）：
- 📚 备课
- 📝 作业
- 📊 学情
- ⚙️ 设置（阶段 4 完善）
"""

import streamlit as st

import config
from utils import app_config
from utils.db import init_db
from modules import analysis, homework, lesson_plan, settings

# 启动时确保目录存在、13 张表就绪（幂等操作，不会清空数据）
init_db()

# 页面基础设置
app_name = config.get_app_name()
app_icon = app_config.get_subject_icon()

st.set_page_config(
    page_title=app_name,
    page_icon=app_icon,
    layout="wide",
)

# 侧边栏导航
st.sidebar.title(f"{app_icon} {app_name}")
page = st.sidebar.radio(
    label="功能导航",
    options=["📚 备课", "📝 作业", "📊 学情", "⚙️ 设置"],
    index=0,
    label_visibility="collapsed",
)
st.sidebar.caption(f"版本 v{config.APP_VERSION}")

# 根据选择渲染对应页面（每个模块暴露 show() 函数）
if page == "📚 备课":
    lesson_plan.show()
elif page == "📝 作业":
    homework.show()
elif page == "📊 学情":
    analysis.show()
else:
    settings.show()