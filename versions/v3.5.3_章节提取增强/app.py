# -*- coding: utf-8 -*-
"""
AI教学辅助 —— Streamlit 主入口（v1.9.0）。

侧边栏：全局搜索 + 直接按钮 + 三个折叠组（备课/学业测评/学情，组内按钮选子功能）；
AI 助手已合并为独立页面「🤖 AI助手」（v3.3.1），侧边栏只保留入口按钮；
主内容区按选择直接渲染对应子功能函数。
"""

import os

import streamlit as st

import config
from utils.db import init_db, SessionLocal
from utils import backup_service, global_search_service, undo_service
from modules import (ai_assistant, analysis, calendar, class_interaction, dashboard,
                     databoard, homework, lesson_plan, reflection, settings, submit_page,
                     template_library)
from utils.keyboard_shortcuts import shortcut_js, shortcuts_enabled
from utils.app_config import DISPLAY_GRADE_CHOICES, SUBJECT_NAMES
from utils import material_service
import streamlit.components.v1 as components

# 启动时确保目录存在、38 张表就绪（幂等操作，不会清空数据）
init_db()
# v2.3.0：补齐 operation_logs 和核心索引；迁移可重复执行。
from migrations.v2_3_0_migration import migrate as _migrate_v230
_migrate_v230()
# v2.9.0：确认 review_records 和 homeworks.level（幂等）
from migrations.v2_9_0_migration import migrate as _migrate_v290
_migrate_v290()
# v2.9.1：确认诊断/单元设计三张表（幂等）
from migrations.v2_9_1_migration import migrate as _migrate_v291
_migrate_v291()
# v3.1.0：确认 Agent 执行日志表（幂等）
from migrations.v3_1_0_migration import migrate as _migrate_v310
_migrate_v310()
# v3.2.0：确认课堂互动/收藏/模板表（幂等）
from migrations.v3_2_0_migration import migrate as _migrate_v320
_migrate_v320()
# v3.3.0：补齐教学进度列并创建提醒设置表（幂等）
from migrations.v3_3_0_migration import migrate as _migrate_v330
_migrate_v330()
# v3.4.0：创建家校沟通/版本历史/回收站/导出模板表（幂等）
from migrations.v3_4_0_migration import migrate as _migrate_v340
_migrate_v340()
# 当天无备份时自动备份，并清理 7 天前旧备份；隔离测试用环境变量关闭。
if os.environ.get("MATH_TEACHER_DISABLE_STARTUP_BACKUP") != "1":
    backup_service.auto_backup_if_needed()
    backup_service.prune_old_backups(keep_days=7)
# v3.4.0：清理回收站里超过 30 天的条目（失败不影响启动）。
try:
    from utils import recycle_service as _recycle_service
    _recycle_service.purge_expired(30)
except Exception:  # noqa: BLE001
    pass
# 启动时把已保存的原始资料文件同步到 Streamlit 静态目录。
material_service.sync_original_static_files()

st.set_page_config(
    page_title=config.APP_NAME,
    page_icon="📐",
    layout="wide",
)

# v3.4.1：布局重构——保留 3 个独立按钮，其余收进折叠组。
TOP_PAGES = ["🏠 首页", "🤖 AI助手", "📊 数据看板",
             "📂 资源中心", "🎓 教学工具",
             "📚 备课", "📝 学业测评", "📊 学情", "⚙️ 设置"]


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

# v3.4.1：被收进折叠组的四个旧顶级页，一次性迁移到新组与子项。
_LEGACY_TOP_MIGRATION = {
    "📅 教学日历": ("🎓 教学工具", "teaching_tab", "📅 教学日历"),
    "🎯 课堂互动": ("🎓 教学工具", "teaching_tab", "🎯 课堂互动"),
    "💭 教学反思": ("🎓 教学工具", "teaching_tab", "💭 教学反思"),
    "📁 我的模板": ("📂 资源中心", "resource_tab", "📁 我的模板"),
}
_old_top = st.session_state.get("app_top_page")
if _old_top in _LEGACY_TOP_MIGRATION:
    _migrated_top, _migrated_key, _migrated_sub = _LEGACY_TOP_MIGRATION[_old_top]
    st.session_state["app_top_page"] = _migrated_top
    st.session_state[_migrated_key] = _migrated_sub

# 顶级路由默认首页。
if st.session_state.get("app_top_page") not in TOP_PAGES:
    st.session_state["app_top_page"] = "🏠 首页"


# v2.4.0：一次性迁移旧子功能值（执行后值已更新，天然只跑一次）。
# v3.4.1：条目改为四元组（所在顶级页, 目标子key, 新子功能值, {内部模式key: 模式值}），
# 因为「资料管理」「教学反思」等已换到别的折叠组，不再写回原 key。
_LEGACY_SUB_MIGRATION = {
    "lesson_plan_tab": {
        "📚 RAG知识库": ("📂 资源中心", "resource_tab", "📚 资料管理",
                       {"material_view_mode": "AI智能检索"}),
        "资料管理": ("📂 资源中心", "resource_tab", "📚 资料管理", {}),
        "PPT 生成": ("📚 备课", "lesson_plan_tab", "AI 备课", {}),
        "🎙️ 课堂实录": ("🎓 教学工具", "teaching_tab", "💭 教学反思", {}),
    },
    "homework_tab": {
        "📜 历史记录": ("📝 学业测评", "homework_tab", "作业管理",
                       {"homework_state_mode": "已完成"}),
        "成绩录入": ("📝 学业测评", "homework_tab", "✏️ 批改与分析", {}),
        "作业分析": ("📝 学业测评", "homework_tab", "✏️ 批改与分析", {}),
        "作业批改与分析": ("📝 学业测评", "homework_tab", "✏️ 批改与分析", {}),
    },
    "analysis_tab": {
        "教学反思": ("🎓 教学工具", "teaching_tab", "💭 教学反思", {}),
        "期末评语": ("📊 学情", "analysis_tab", "学生画像", {}),
        "🧠 知识图谱": ("📊 学情", "analysis_tab", "考试分析", {}),
    },
}
for _sub_key, _mapping in _LEGACY_SUB_MIGRATION.items():
    _old = st.session_state.get(_sub_key)
    if _old in _mapping:
        _top, _target_key, _new_sub, _extra = _mapping[_old]
        st.session_state["app_top_page"] = _top
        if _target_key and _new_sub is not None:
            st.session_state[_target_key] = _new_sub
        if _new_sub is not None:
            st.session_state[_sub_key] = _new_sub
        for _mode_key, _mode_value in _extra.items():
            st.session_state[_mode_key] = _mode_value


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

# 直接按钮：首页 / 日历
if st.sidebar.button("🏠 首页", key="nav_home",
                      use_container_width=True):
    st.session_state["app_top_page"] = "🏠 首页"
    st.rerun()
if st.sidebar.button("🤖 AI助手", key="nav_ai_assistant",
                      use_container_width=True):
    st.session_state["app_top_page"] = "🤖 AI助手"
    st.rerun()
# v3.4.1：数据看板前移到 AI助手 之后，成为第三个独立按钮。
if st.sidebar.button("📊 数据看板", key="nav_databoard",
                      use_container_width=True):
    st.session_state["app_top_page"] = "📊 数据看板"
    st.rerun()

# 折叠组：资源中心（v3.4.1；资料管理、我的模板从原位置移入）
with st.sidebar.expander("📂 资源中心", expanded=(top_page == "📂 资源中心")):
    resource_subs = ["📚 资料管理", "📁 我的模板"]
    if st.session_state.get("resource_tab") not in resource_subs:
        st.session_state["resource_tab"] = "📚 资料管理"
    _current_resource = st.session_state["resource_tab"]
    for _sub in resource_subs:
        if st.button(_sub, key=f"resource_sub_{_sub}",
                     use_container_width=True,
                     type=("primary" if _sub == _current_resource
                           else "secondary")):
            st.session_state["resource_tab"] = _sub
            st.session_state["app_top_page"] = "📂 资源中心"
            st.rerun()

# 折叠组：教学工具（v3.4.1；日历、课堂互动、教学反思从独立按钮移入）
with st.sidebar.expander("🎓 教学工具", expanded=(top_page == "🎓 教学工具")):
    teaching_subs = ["📅 教学日历", "🎯 课堂互动", "💭 教学反思"]
    if st.session_state.get("teaching_tab") not in teaching_subs:
        st.session_state["teaching_tab"] = "📅 教学日历"
    _current_teaching = st.session_state["teaching_tab"]
    for _sub in teaching_subs:
        if st.button(_sub, key=f"teaching_sub_{_sub}",
                     use_container_width=True,
                     type=("primary" if _sub == _current_teaching
                           else "secondary")):
            st.session_state["teaching_tab"] = _sub
            st.session_state["app_top_page"] = "🎓 教学工具"
            st.rerun()

# 折叠组：备课
with st.sidebar.expander("📚 备课", expanded=(top_page == "📚 备课")):
    # v3.4.1：资料管理移入「资源中心」，备课组只剩 4 项。
    lesson_subs = ["AI 备课", "AI 出题", "📚 单元整体设计", "题库管理"]
    if st.session_state.get("lesson_plan_tab") not in lesson_subs:
        st.session_state["lesson_plan_tab"] = "AI 备课"

    # v3.3.1：改用按钮组，点已选中的第一个也能立即切换并 rerun。
    _current_lesson = st.session_state["lesson_plan_tab"]
    for _sub in lesson_subs:
        if st.button(_sub, key=f"lesson_sub_{_sub}", use_container_width=True,
                     type=("primary" if _sub == _current_lesson
                           else "secondary")):
            st.session_state["lesson_plan_tab"] = _sub
            st.session_state["app_top_page"] = "📚 备课"
            st.rerun()

# 折叠组：学业测评
with st.sidebar.expander("📝 学业测评",
                         expanded=(top_page == "📝 学业测评")):
    hw_subs = ["作业管理", "🤖 智能组卷",
               "✏️ 批改与分析", "📚 分层作业", "错题本"]
    if st.session_state.get("homework_tab") not in hw_subs:
        st.session_state["homework_tab"] = "作业管理"

    # v3.3.1：改用按钮组，点已选中的第一个也能立即切换并 rerun。
    _current_hw = st.session_state["homework_tab"]
    for _sub in hw_subs:
        if st.button(_sub, key=f"hw_sub_{_sub}", use_container_width=True,
                     type=("primary" if _sub == _current_hw
                           else "secondary")):
            st.session_state["homework_tab"] = _sub
            st.session_state["app_top_page"] = "📝 学业测评"
            st.rerun()

# 折叠组：学情
with st.sidebar.expander("📊 学情", expanded=(top_page == "📊 学情")):
    analysis_subs = ["学生管理", "成绩管理", "考试分析",
                     "趋势分析", "学生画像", "🔍 AI教学诊断"]
    if st.session_state.get("analysis_tab") not in analysis_subs:
        st.session_state["analysis_tab"] = "学生管理"

    # v3.3.1：改用按钮组，点已选中的第一个也能立即切换并 rerun。
    _current_analysis = st.session_state["analysis_tab"]
    for _sub in analysis_subs:
        if st.button(_sub, key=f"analysis_sub_{_sub}", use_container_width=True,
                     type=("primary" if _sub == _current_analysis
                           else "secondary")):
            st.session_state["analysis_tab"] = _sub
            st.session_state["app_top_page"] = "📊 学情"
            st.rerun()

# 直接按钮：设置
if st.sidebar.button("⚙️ 设置", key="nav_settings",
                      use_container_width=True):
    st.session_state["app_top_page"] = "⚙️ 设置"
    st.rerun()

# v1.9.0：撤销 / 重做（仅栈非空时显示）。
if undo_service.can_undo() or undo_service.can_redo():
    _u1, _u2 = st.sidebar.columns(2)
    if _u1.button("↩️ 撤销", key="undo_btn",
                  disabled=not undo_service.can_undo(),
                  use_container_width=True):
        with SessionLocal() as _s:
            _info = undo_service.undo(_s)
            _s.commit()
        st.toast(f"已撤销：{_info['label']}")
        st.rerun()
    if _u2.button("↪️ 重做", key="redo_btn",
                  disabled=not undo_service.can_redo(),
                  use_container_width=True):
        with SessionLocal() as _s:
            _info = undo_service.redo(_s)
            _s.commit()
        st.toast(f"已重做：{_info['label']}")
        st.rerun()

with st.sidebar.expander("⌨️ 快捷键", expanded=False):
    st.caption(
        "Ctrl+1/2/3：首页 / 教学日历 / 设置\n"
        "Ctrl+4~9：当前组内子功能\n"
        "Ctrl+N 新建 / Ctrl+S 保存 / Ctrl+F 输入框\n"
        "Ctrl+Z 撤销 / Ctrl+Y 重做 / Ctrl+K 搜索")

if shortcuts_enabled():
    components.html(shortcut_js(), height=0)
st.sidebar.caption(f"版本 v{config.APP_VERSION}")

# 页面切换：关闭学业测评弹窗、清空撤销栈；同页 rerun 不清理。
last_top = st.session_state.get("_last_top_page")
if last_top is not None and last_top != top_page:
    if last_top == "📝 学业测评":
        homework.close_new_homework_dialog_state()
    undo_service.clear()
st.session_state["_last_top_page"] = top_page

# ---------------- 主内容区分发 ----------------
def _render_current_page() -> None:
    """按当前侧边栏选择渲染主页面。"""
    if top_page == "🏠 首页":
        dashboard.show()
    elif top_page == "🤖 AI助手":
        ai_assistant.show()
    elif top_page == "📊 数据看板":
        databoard.show()
    elif top_page == "⚙️ 设置":
        settings.show()
    elif top_page == "📂 资源中心":
        # v3.4.1：资料管理、我的模板收进资源中心（不新增 lesson_plan.show()）。
        _resource_sub = st.session_state.get("resource_tab", "📚 资料管理")
        if _resource_sub == "📚 资料管理":
            st.title("📂 资源中心")
            lesson_plan.tab_materials()
        else:
            template_library.show()
    elif top_page == "🎓 教学工具":
        # v3.4.1：日历/课堂互动/教学反思收进教学工具（各自渲染自己的标题）。
        _teaching_sub = st.session_state.get("teaching_tab", "📅 教学日历")
        if _teaching_sub == "📅 教学日历":
            calendar.show()
        elif _teaching_sub == "🎯 课堂互动":
            class_interaction.show()
        else:
            reflection.show()
    elif top_page == "📚 备课":
        st.title("📚 备课")
        sub = st.session_state["lesson_plan_tab"]
        if sub == "AI 备课":
            lesson_plan.tab_lesson()
        elif sub == "AI 出题":
            lesson_plan.tab_question_gen()
        elif sub == "📚 单元整体设计":
            lesson_plan.tab_unit_design()
        else:
            lesson_plan.tab_bank()
    elif top_page == "📝 学业测评":
        st.title("📝 学业测评")
        sub = st.session_state["homework_tab"]
        if sub == "作业管理":
            homework.tab_manage()
        elif sub == "🤖 智能组卷":
            homework.tab_smart_compose()
        elif sub == "✏️ 批改与分析":
            homework.tab_grading_analysis()
        elif sub == "📚 分层作业":
            homework.tab_tiered_homework()
        else:
            homework.tab_wrong_book()
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
        elif sub == "🔍 AI教学诊断":
            analysis.tab_diagnosis()
        else:
            analysis.tab_profile()


# v2.8.0：页面加载耗时监控 + 统一友好错误处理（含重试/返回首页）
import time as _time_mod

_page_start = _time_mod.perf_counter()
try:
    _render_current_page()
except Exception as exc:
    # v2.8.0：error_handler 负责友好提示（不泄露路径/技术栈）+ 重试/返回首页，
    # 同时把完整堆栈写入错误日志。
    from utils import error_handler
    error_handler.handle_page_error(top_page, exc)
finally:
    try:
        from utils import monitor_service
        monitor_service.record_metric(
            "page", str(top_page), (_time_mod.perf_counter() - _page_start) * 1000)
    except Exception:  # noqa: BLE001 —— 监控失败不影响页面
        pass
