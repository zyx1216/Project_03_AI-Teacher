# -*- coding: utf-8 -*-
"""
AI教学辅助 —— Streamlit 主入口。

职责：
1. 启动时初始化数据目录和数据库；
2. 用侧边栏做 6 个页面的导航；
3. 把主内容区交给对应的页面模块渲染。

页面规划：
- 🏠 首页
- 📅 教学日历
- 📚 备课
- 📝 学业测评
- 📊 学情
- ⚙️ 设置
"""

import streamlit as st

import config
from utils.db import init_db, SessionLocal
from utils import global_search_service
from modules import analysis, calendar, dashboard, homework, lesson_plan, settings
from utils.keyboard_shortcuts import shortcut_js
from utils import material_service
import streamlit.components.v1 as components

# 启动时确保目录存在、13 张表就绪（幂等操作，不会清空数据）
init_db()
# 启动时把已保存的原始资料文件同步到 Streamlit 静态目录。
material_service.sync_original_static_files()

# 页面基础设置（标题、图标固定，不再随学科切换）
st.set_page_config(
    page_title=config.APP_NAME,
    page_icon="📐",
    layout="wide",
)

def _render_global_search(query: str):
    """v1.8.1：渲染全局搜索结果，四类结果点击后跳转到对应页面。"""
    with SessionLocal() as session:
        result = global_search_service.search_all(session, query)
    questions = result["questions"]
    plans = result["plans"]
    students = result["students"]
    homeworks = result["homeworks"]
    total = len(questions) + len(plans) + len(students) + len(homeworks)

    def _go(page, **extra):
        # 一次性跨页跳转：主导航走 _pending_main_page，落点写各自 pending key。
        st.session_state["_pending_main_page"] = page
        for key, value in extra.items():
            st.session_state[key] = value
        st.rerun()

    with st.sidebar.expander(f"🔍 搜索结果（{total}）", expanded=True):
        if questions:
            st.markdown("**📝 题目**")
            for q in questions:
                if st.button(q.content[:24], key=f"search_q_{q.id}"):
                    _go("📚 备课",
                        pending_lesson_plan_tab="题库管理",
                        bank_search_keyword=query)
        if plans:
            st.markdown("**📋 教案**")
            for plan in plans:
                if st.button(f"📄 {plan.title}", key=f"search_plan_{plan.id}"):
                    _go("📚 备课",
                        pending_lesson_plan_tab="AI 备课",
                        pending_load_plan_id=plan.id)
        if students:
            st.markdown("**👨‍🎓 学生**")
            for s in students:
                label = f"{s.name}（{s.class_name or '未分班'}）"
                if st.button(label, key=f"search_stu_{s.id}"):
                    _go("📊 学情",
                        pending_analysis_tab="学生管理",
                        student_filter_keyword=s.name)
        if homeworks:
            st.markdown("**📚 作业**")
            for h in homeworks:
                if st.button(f"📝 {h.name}", key=f"search_hw_{h.id}"):
                    _go("📝 学业测评",
                        homework_tab="作业管理",
                        hw_open_id=h.id)
        if total == 0:
            st.caption("未找到匹配结果")


# 侧边栏导航
st.sidebar.title(f"📐 {config.APP_NAME}")
# v1.8.1：全局搜索（题目/教案/学生/作业）
_search_query = st.sidebar.text_input(
    "🔍 全局搜索", key="global_search",
    placeholder="搜索题目/教案/学生/作业")
if _search_query.strip():
    _render_global_search(_search_query.strip())
NAV_OPTIONS = ["🏠 首页", "📅 教学日历", "📚 备课", "📝 学业测评", "📊 学情", "⚙️ 设置"]

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
        "Ctrl+1/2/3/4：切换 首页/教学日历/备课/学业测评\n"
        "Ctrl+K：聚焦当前页搜索框")

# 全局快捷键（同源 iframe，JS 通过 window.parent 操作侧边栏；注入一次）
components.html(shortcut_js(), height=0)
st.sidebar.caption(f"版本 v{config.APP_VERSION}")

# 主导航切离作业页时，关掉未完成的新建作业弹窗，避免切回来自动弹出。
# 同一页面内的 rerun 不清理，保证点按钮、切类型、提交表单不受影响。
last_page = st.session_state.get("_last_main_page")
if last_page is not None and last_page != page and last_page == "📝 学业测评":
    homework.close_new_homework_dialog_state()
st.session_state["_last_main_page"] = page

# 根据选择渲染对应页面（每个模块暴露 show() 函数）
if page == "🏠 首页":
    dashboard.show()
elif page == "📚 备课":
    lesson_plan.show()
elif page == "📝 学业测评":
    homework.show()
elif page == "📊 学情":
    analysis.show()
elif page == "📅 教学日历":
    calendar.show()
else:
    settings.show()

