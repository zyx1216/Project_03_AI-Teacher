# -*- coding: utf-8 -*-
"""
AI教学辅助 —— Streamlit 主入口（v1.8.2 折叠导航）。

侧边栏：全局搜索 + 直接按钮（首页/日历/设置）+ 三个折叠组
（备课/学业测评/学情，组内 radio 选子功能）；主内容区按选择
直接渲染对应子功能函数，不再用 st.tabs。
"""

import os

import streamlit as st

import config
from utils.db import init_db, SessionLocal
from utils import backup_service, global_search_service
from modules import analysis, calendar, dashboard, homework, lesson_plan, settings, submit_page
from utils.keyboard_shortcuts import shortcut_js
from utils import material_service
import streamlit.components.v1 as components

# 启动时确保目录存在、16 张表就绪（幂等操作，不会清空数据）
init_db()
# 当天无备份时自动备份，并清理 7 天前旧备份；隔离测试用环境变量关闭。
if os.environ.get("MATH_TEACHER_DISABLE_STARTUP_BACKUP") != "1":
    backup_service.auto_backup_if_needed()
    backup_service.prune_old_backups(keep_days=7)
# 启动时把已保存的原始资料文件同步到 Streamlit 静态目录。
material_service.sync_original_static_files()

st.set_page_config(
    page_title=config.APP_NAME,
    page_icon="📐",
    layout="wide",
)

TOP_PAGES = ["🏠 首页", "📅 教学日历", "📚 备课",
             "📝 学业测评", "📊 学情", "⚙️ 设置"]

def _query_param_scalar(name: str):
    """读取 query 参数；兼容 AppTest 中以列表保存参数值。"""
    value = st.query_params.get(name)
    if isinstance(value, list):
        return value[0] if value else None
    return value


# v1.8.3：在线提交页在导航渲染前分流；命中后只渲染提交页。
_submit_code = _query_param_scalar("code")
if _submit_code or _query_param_scalar("page") == "submit":
    submit_page.show_submit_page(str(_submit_code or ""))
    st.stop()

# v1.8.2：一次性跨页跳转，在所有导航控件创建前消费。
_pending_route = st.session_state.pop("_pending_app_route", None)
if _pending_route in TOP_PAGES:
    st.session_state["app_top_page"] = _pending_route
_pending_sub = st.session_state.pop("_pending_app_sub", None)
if _pending_sub is not None:
    _sub_key = st.session_state.get("_pending_app_sub_key")
    if _sub_key:
        st.session_state[_sub_key] = _pending_sub
        st.session_state.pop("_pending_app_sub_key", None)

# 顶级路由默认首页。
if st.session_state.get("app_top_page") not in TOP_PAGES:
    st.session_state["app_top_page"] = "🏠 首页"


def _render_global_search(query: str):
    """渲染全局搜索结果，四类结果点击后一次性跳转到对应子功能。"""
    with SessionLocal() as session:
        result = global_search_service.search_all(session, query)
    questions = result["questions"]
    plans = result["plans"]
    students = result["students"]
    homeworks = result["homeworks"]
    total = len(questions) + len(plans) + len(students) + len(homeworks)

    def _go(route, sub=None, sub_key=None, **extra):
        st.session_state["_pending_app_route"] = route
        if sub is not None:
            st.session_state["_pending_app_sub"] = sub
            st.session_state["_pending_app_sub_key"] = sub_key
        for key, value in extra.items():
            st.session_state[key] = value
        st.rerun()

    with st.sidebar.expander(f"🔍 搜索结果（{total}）", expanded=True):
        if questions:
            st.markdown("**📝 题目**")
            for q in questions:
                if st.button(q.content[:24], key=f"search_q_{q.id}"):
                    _go("📚 备课", sub="题库管理", sub_key="lesson_plan_tab",
                        bank_search_keyword=query)
        if plans:
            st.markdown("**📋 教案**")
            for plan in plans:
                if st.button(f"📄 {plan.title}", key=f"search_plan_{plan.id}"):
                    _go("📚 备课", sub="AI 备课", sub_key="lesson_plan_tab",
                        pending_load_plan_id=plan.id)
        if students:
            st.markdown("**👨‍🎓 学生**")
            for s in students:
                label = f"{s.name}（{s.class_name or '未分班'}）"
                if st.button(label, key=f"search_stu_{s.id}"):
                    _go("📊 学情", sub="学生管理", sub_key="analysis_tab",
                        student_filter_keyword=s.name)
        if homeworks:
            st.markdown("**📚 作业**")
            for h in homeworks:
                if st.button(f"📝 {h.name}", key=f"search_hw_{h.id}"):
                    _go("📝 学业测评", sub="作业管理", sub_key="homework_tab",
                        hw_open_id=h.id)
        if total == 0:
            st.caption("未找到匹配结果")


# ---------------- 侧边栏 ----------------
st.sidebar.title(f"📐 {config.APP_NAME}")
_search_query = st.sidebar.text_input(
    "🔍 全局搜索", key="global_search",
    placeholder="搜索题目/教案/学生/作业")
if _search_query.strip():
    _render_global_search(_search_query.strip())

top_page = st.session_state["app_top_page"]

# 直接按钮：首页 / 日历 / 设置
if st.sidebar.button("🏠 首页", key="nav_home",
                      use_container_width=True):
    st.session_state["app_top_page"] = "🏠 首页"
    st.rerun()
if st.sidebar.button("📅 教学日历", key="nav_calendar",
                      use_container_width=True):
    st.session_state["app_top_page"] = "📅 教学日历"
    st.rerun()

# 折叠组：备课
with st.sidebar.expander("📚 备课", expanded=(top_page == "📚 备课")):
    lesson_subs = ["资料管理", "AI 备课", "AI 出题", "题库管理", "PPT 生成"]
    if st.session_state.get("lesson_plan_tab") not in lesson_subs:
        st.session_state["lesson_plan_tab"] = "资料管理"

    def _on_lesson_sub():
        st.session_state["app_top_page"] = "📚 备课"

    st.radio("备课子功能", lesson_subs, key="lesson_plan_tab",
             label_visibility="collapsed", on_change=_on_lesson_sub)

# 折叠组：学业测评
with st.sidebar.expander("📝 学业测评",
                         expanded=(top_page == "📝 学业测评")):
    hw_subs = ["作业管理", "🤖 智能组卷", "成绩录入",
               "作业分析", "错题本", "📜 历史记录"]
    if st.session_state.get("homework_tab") not in hw_subs:
        st.session_state["homework_tab"] = "作业管理"

    def _on_hw_sub():
        st.session_state["app_top_page"] = "📝 学业测评"

    st.radio("学业测评子功能", hw_subs, key="homework_tab",
             label_visibility="collapsed", on_change=_on_hw_sub)

# 折叠组：学情
with st.sidebar.expander("📊 学情", expanded=(top_page == "📊 学情")):
    analysis_subs = ["学生管理", "成绩管理", "考试分析", "趋势分析",
                     "学生画像", "教学反思", "期末评语", "知识点分析"]
    if st.session_state.get("analysis_tab") not in analysis_subs:
        st.session_state["analysis_tab"] = "学生管理"

    def _on_analysis_sub():
        st.session_state["app_top_page"] = "📊 学情"

    st.radio("学情子功能", analysis_subs, key="analysis_tab",
             label_visibility="collapsed", on_change=_on_analysis_sub)

# 直接按钮：设置
if st.sidebar.button("⚙️ 设置", key="nav_settings",
                      use_container_width=True):
    st.session_state["app_top_page"] = "⚙️ 设置"
    st.rerun()

# 快捷键说明
with st.sidebar.expander("⌨️ 快捷键", expanded=False):
    st.caption(
        "Ctrl+1/2：切换 首页/教学日历\n"
        "Ctrl+K：聚焦当前页搜索框")

components.html(shortcut_js(), height=0)
st.sidebar.caption(f"版本 v{config.APP_VERSION}")

# 切离学业测评时关闭未完成的新建作业弹窗；同页 rerun 不清理。
last_top = st.session_state.get("_last_top_page")
if last_top is not None and last_top != top_page and last_top == "📝 学业测评":
    homework.close_new_homework_dialog_state()
st.session_state["_last_top_page"] = top_page

# ---------------- 主内容区分发 ----------------
if top_page == "🏠 首页":
    dashboard.show()
elif top_page == "📅 教学日历":
    calendar.show()
elif top_page == "⚙️ 设置":
    settings.show()
elif top_page == "📚 备课":
    st.title("📚 备课")
    sub = st.session_state["lesson_plan_tab"]
    if sub == "资料管理":
        lesson_plan.tab_materials()
    elif sub == "AI 备课":
        lesson_plan.tab_lesson()
    elif sub == "AI 出题":
        lesson_plan.tab_question_gen()
    elif sub == "题库管理":
        lesson_plan.tab_bank()
    else:
        lesson_plan.tab_ppt()
elif top_page == "📝 学业测评":
    st.title("📝 学业测评")
    sub = st.session_state["homework_tab"]
    if sub == "作业管理":
        homework.tab_manage()
    elif sub == "🤖 智能组卷":
        homework.tab_smart_compose()
    elif sub == "成绩录入":
        homework.tab_scores()
    elif sub == "作业分析":
        homework.tab_analysis()
    elif sub == "错题本":
        homework.tab_wrong_book()
    else:
        homework.tab_history()
else:  # 📊 学情
    st.title("📊 学情")
    sub = st.session_state["analysis_tab"]
    if sub == "学生管理":
        analysis.tab_students()
    elif sub == "成绩管理":
        analysis.tab_scores()
    elif sub == "考试分析":
        analysis.tab_exam_analysis()
    elif sub == "趋势分析":
        analysis.tab_trends()
    elif sub == "学生画像":
        analysis.tab_profile()
    elif sub == "教学反思":
        analysis.tab_reflection()
    elif sub == "期末评语":
        analysis.tab_comments()
    else:
        analysis.tab_knowledge()

