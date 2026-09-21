# -*- coding: utf-8 -*-
"""
AI教学辅助 —— Streamlit 主入口。

职责：
1. 启动时初始化数据目录和数据库；
2. 用侧边栏做 6 个页面的导航；
3. 把主内容区交给对应的页面模块渲染。

页面规划：
- 🏠 首页
- 📚 备课
- 📝 作业
- 📊 学情
- ⚙️ 设置
- 📅 教学日历
"""

import streamlit as st

import config
from utils.db import init_db
from modules import analysis, calendar, dashboard, homework, lesson_plan, settings
from utils.keyboard_shortcuts import shortcut_js
import streamlit.components.v1 as components

# 启动时确保目录存在、13 张表就绪（幂等操作，不会清空数据）
init_db()

# 页面基础设置（标题、图标固定，不再随学科切换）
st.set_page_config(
    page_title=config.APP_NAME,
    page_icon="📐",
    layout="wide",
)

# 侧边栏导航
st.sidebar.title(f"📐 {config.APP_NAME}")
NAV_OPTIONS = ["🏠 首页", "📚 备课", "📝 作业", "📊 学情", "⚙️ 设置", "📅 教学日历"]

# 跨页跳转必须在 radio 创建前写入固定 key，侧边栏选中态才会同步。
if st.session_state.get("_pending_main_page"):
    target = st.session_state.pop("_pending_main_page")
    if target in NAV_OPTIONS:
        st.session_state["main_nav"] = target

page = st.sidebar.radio(
    label="功能导航",
    options=NAV_OPTIONS,
    index=0,
    label_visibility="collapsed",
    key="main_nav",
)

# 快捷键说明（默认折叠）
with st.sidebar.expander("⌨️ 快捷键", expanded=False):
    st.caption(
        "Ctrl+1/2/3/4：切换 备课/作业/学情/设置\n"
        "Ctrl+K：聚焦当前页搜索框")

# 全局快捷键（同源 iframe，JS 通过 window.parent 操作侧边栏；注入一次）
components.html(shortcut_js(), height=0)
st.sidebar.caption(f"版本 v{config.APP_VERSION}")

# 主导航切离作业页时，关掉未完成的新建作业弹窗，避免切回来自动弹出。
# 同一页面内的 rerun 不清理，保证点按钮、切类型、提交表单不受影响。
last_page = st.session_state.get("_last_main_page")
if last_page is not None and last_page != page and last_page == "📝 作业":
    homework.close_new_homework_dialog_state()
st.session_state["_last_main_page"] = page

# 根据选择渲染对应页面（每个模块暴露 show() 函数）
if page == "🏠 首页":
    dashboard.show()
elif page == "📚 备课":
    lesson_plan.show()
elif page == "📝 作业":
    homework.show()
elif page == "📊 学情":
    analysis.show()
elif page == "📅 教学日历":
    calendar.show()
else:
    settings.show()
