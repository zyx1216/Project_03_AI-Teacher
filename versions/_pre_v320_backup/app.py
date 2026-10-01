# -*- coding: utf-8 -*-
"""
AI教学辅助 —— Streamlit 主入口（v1.9.0）。

侧边栏：全局搜索 + AI 自然语言助手 + 直接按钮（首页/日历/设置）
+ 三个折叠组（备课/学业测评/学情，组内 radio 选子功能）；
主内容区按选择直接渲染对应子功能函数。
"""

import os

import streamlit as st

import config
from utils.db import init_db, SessionLocal
from utils import (
    backup_service, global_search_service, agent_service, undo_service,
    llm_client, agent_context, agent_intents, agent_alert, multi_agent,
)
from modules import (ai_assistant, analysis, calendar, dashboard, databoard,
                     homework, lesson_plan, reflection, settings, submit_page)
from utils.keyboard_shortcuts import shortcut_js, shortcuts_enabled
from utils.app_config import DISPLAY_GRADE_CHOICES, SUBJECT_NAMES
from utils import material_service
import streamlit.components.v1 as components

# 启动时确保目录存在、30 张表就绪（幂等操作，不会清空数据）
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

TOP_PAGES = ["🏠 首页", "🤖 AI助手", "📅 教学日历", "📊 数据看板",
             "📚 备课", "💭 教学反思", "📝 学业测评",
             "📊 学情", "⚙️ 设置"]


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


# v2.4.0：一次性迁移旧子功能值（执行后值已更新，天然只跑一次）。
# 每项：旧值 -> (所在顶级页, 新子功能值, {内部模式key: 模式值})
_LEGACY_SUB_MIGRATION = {
    "lesson_plan_tab": {
        "📚 RAG知识库": ("📚 备课", "资料管理",
                       {"material_view_mode": "AI智能检索"}),
        "PPT 生成": ("📚 备课", "AI 备课", {}),
        "🎙️ 课堂实录": ("💭 教学反思", None, {}),
    },
    "homework_tab": {
        "📜 历史记录": ("📝 学业测评", "作业管理",
                       {"homework_state_mode": "已完成"}),
        "成绩录入": ("📝 学业测评", "✏️ 批改与分析", {}),
        "作业分析": ("📝 学业测评", "✏️ 批改与分析", {}),
        "作业批改与分析": ("📝 学业测评", "✏️ 批改与分析", {}),
    },
    "analysis_tab": {
        "教学反思": ("💭 教学反思", None, {}),
        "期末评语": ("📊 学情", "学生画像", {}),
        "🧠 知识图谱": ("📊 学情", "考试分析", {}),
    },
}
for _sub_key, _mapping in _LEGACY_SUB_MIGRATION.items():
    _old = st.session_state.get(_sub_key)
    if _old in _mapping:
        _top, _new_sub, _extra = _mapping[_old]
        st.session_state["app_top_page"] = _top
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


def _consume_agent_result():
    """执行成功且带路由时，按一次性 pending 跳转并打开结果。"""
    _r = st.session_state.get("agent_last_result")
    if not _r or _r.get("status") != "success" or not _r.get("route"):
        return
    if st.sidebar.button("➡️ 打开结果", key="agent_open_result"):
        st.session_state["_pending_app_route"] = _r["route"]
        if _r.get("sub"):
            st.session_state["_pending_app_sub"] = _r["sub"]
            st.session_state["_pending_app_sub_key"] = {
                "📚 备课": "lesson_plan_tab",
                "📝 学业测评": "homework_tab",
                "📊 学情": "analysis_tab"}.get(_r["route"])
        for _k, _v in (_r.get("extra") or {}).items():
            st.session_state[_k] = _v
        st.session_state.pop("agent_last_result", None)
        st.rerun()


def _render_agent_plan_preview():
    """渲染 complex 指令的计划预览：先确认后执行，含跳过/取消/失败重试。"""
    preview = st.session_state.get("agent_plan_preview")
    if not preview:
        return
    plan = preview.get("plan") or []
    st.markdown("**📋 执行计划（请确认后开始）**")
    for index, step in enumerate(plan, start=1):
        st.markdown(f"{index}. {step.get('name','')}")
    start_index = int(preview.get("_start_index", 0))
    if start_index:
        st.caption(f"已设置从前 {start_index} 步之后开始执行。")

    plan_result = st.session_state.get("agent_plan_result")
    if plan_result is None:
        c1, c2, c3 = st.columns(3)
        if c1.button("▶️ 确认开始执行", key="agent_plan_confirm",
                     type="primary", use_container_width=True):
            with SessionLocal() as _s:
                _res = _execute_agent_plan(_s, preview, start_index)
                _s.commit()
                st.session_state["agent_plan_result"] = _res
            st.rerun()
        if c2.button("⏭️ 跳过此步", key="agent_plan_skip",
                     use_container_width=True):
            preview["_start_index"] = min(start_index + 1, len(plan) - 1)
            st.toast("已跳过当前第一步。")
            st.rerun()
        if c3.button("🗑️ 取消全部", key="agent_plan_cancel",
                     use_container_width=True):
            st.session_state.pop("agent_plan_preview", None)
            st.toast("已取消计划，未执行任何操作。")
            st.rerun()
        return

    # 执行结果：进度条 + 详细日志 + 汇总/重试。
    steps = plan_result.get("steps") or []
    total = len(plan)
    done = sum(1 for s in steps if s.get("status") == "success")
    st.progress(done / total if total else 0)
    failed_index = plan_result.get("failed_index")
    if plan_result.get("status") == "success":
        st.caption(f"已完成 {done}/{total} 步。")
    elif plan_result.get("cancelled"):
        st.caption(plan_result.get("summary"))
    else:
        st.error(plan_result.get("summary"))
    if plan_result.get("via_multi_agent"):
        _render_multi_agent_result(plan_result, plan, preview)
    with st.expander("查看详细日志"):
        for s in steps:
            icon = "✅" if s.get("status") == "success" else "❌"
            st.markdown(f"{icon} {s.get('name','')}：{s.get('summary','')}")
    cc1, cc2 = st.columns(2)
    if failed_index is not None and cc1.button(
            "🔄 从失败步骤重试", key="agent_plan_retry",
            use_container_width=True):
        with SessionLocal() as _s:
            _res = _execute_agent_plan(_s, preview, failed_index)
            _s.commit()
            st.session_state["agent_plan_result"] = _res
        st.rerun()
    if cc2.button("关闭计划", key="agent_plan_close",
                   use_container_width=True):
        st.session_state.pop("agent_plan_preview", None)
        st.session_state.pop("agent_plan_result", None)
        st.rerun()

def _execute_agent_plan(session, preview: dict, start_index: int) -> dict:
    """确认后执行计划：多Agent开关开走 Coordinator，否则走原 execute_plan。"""
    if not st.session_state.get("multi_agent_mode"):
        return agent_service.execute_complex_preview(
            session, preview, start_index=start_index)
    parsed = preview.get("parsed") or {}
    instruction = preview.get("instruction") or ""
    task = preview.get("work_task")
    if not isinstance(task, dict):
        task = dict(parsed.get("params") or {})
    # 重试时截掉旧的后续 Agent 输出，避免重复。
    outs = task.get("_agent_out")
    if isinstance(outs, list) and len(outs) > start_index:
        task["_agent_out"] = outs[:start_index]
    scenario = multi_agent.scenario_of(instruction, task)
    result = multi_agent.Coordinator().execute(
        session, scenario, task, start_index=start_index)
    result["via_multi_agent"] = True
    preview["work_task"] = task
    return result


def _render_multi_agent_result(plan_result: dict, plan: list,
                               preview: dict) -> None:
    """多Agent结果：按 Agent 展开协调过程与产出，支持重执行/跳过。"""
    scenario = plan_result.get("scenario")
    keys = multi_agent.SCENARIO_STEPS.get(scenario, [])
    agents = plan_result.get("agents") or []
    st.caption("协调者已按角色拆解任务并分派给各专业 Agent。")
    for out in agents:
        name = out.get("agent_name") or out.get("agent") or "Agent"
        icon = "✅" if out.get("status") == "success" else "❌"
        idx = int(out.get("step_index", -1))
        with st.expander(f"{icon} {name}（{out.get('elapsed', 0)} 秒）"):
            st.markdown(out.get("summary", ""))
            artifact = out.get("artifact") or {}
            if artifact:
                st.caption(str(artifact)[:300])
            if idx >= 0:
                b1, b2 = st.columns(2)
                if b1.button("🔁 重新执行此Agent",
                             key=f"ma_reexec_{idx}",
                             use_container_width=True):
                    with SessionLocal() as _s:
                        _res = _execute_agent_plan(_s, preview, idx)
                        _s.commit()
                        st.session_state["agent_plan_result"] = _res
                    st.rerun()
                if b2.button("⏭️ 跳过此Agent",
                             key=f"ma_skip_{idx}",
                             use_container_width=True):
                    with SessionLocal() as _s:
                        _res = _execute_agent_plan(
                            _s, preview, min(idx + 1, len(keys)))
                        _s.commit()
                        st.session_state["agent_plan_result"] = _res
                    st.rerun()


# v1.9.4：AI 自然语言助手（固定 key）。
@st.dialog("修改当前上下文")
def _edit_agent_context_dialog():
    """修改 AI 助手默认教学上下文。"""
    current = agent_context.load_context()
    subject_index = (SUBJECT_NAMES.index(current["subject"])
                     if current.get("subject") in SUBJECT_NAMES else 1)
    grade_index = (list(DISPLAY_GRADE_CHOICES[:-1]).index(current["grade"])
                   if current.get("grade") in DISPLAY_GRADE_CHOICES[:-1] else 0)
    st.selectbox("学科", SUBJECT_NAMES, index=subject_index, key="ctx_subject")
    st.selectbox("年级", DISPLAY_GRADE_CHOICES[:-1], index=grade_index,
                 key="ctx_grade")
    st.text_input("班级", value=current.get("class_name") or "",
                  key="ctx_class_name")
    st.text_input("章节", value=current.get("current_chapter") or "",
                  key="ctx_chapter")
    if st.button("保存", type="primary", key="ctx_save",
                 use_container_width=True):
        agent_context.update_context(
            subject=st.session_state["ctx_subject"],
            grade=st.session_state["ctx_grade"],
            class_name=str(st.session_state["ctx_class_name"]).strip(),
            current_chapter=str(st.session_state["ctx_chapter"]).strip())
        st.session_state["agent_context_open"] = False
        st.rerun()




def _render_agent_clarification():
    """信息不足时主动澄清；同一会话得到答案后写入短期上下文。"""
    clarification = st.session_state.get("agent_clarification")
    if not clarification:
        return
    st.warning(clarification.get("question", "需要补充信息。"))
    options = clarification.get("options") or []
    reference_type = clarification.get("reference_type", "")

    if options:
        chosen = st.radio("请选择", options, key="agent_clarification_choice")
        if st.button("确认选择", key="agent_clarification_confirm"):
            _save_clarification(reference_type, str(chosen))
    else:
        answer = st.text_input("请直接补充", key="agent_clarification_answer")
        if st.button("提交补充", key="agent_clarification_submit"):
            if not answer.strip():
                st.warning("补充内容不能为空。")
            else:
                _save_clarification(reference_type, answer.strip())
    if st.button("取消澄清", key="agent_clarification_cancel"):
        st.session_state.pop("agent_clarification", None)
        st.rerun()


def _save_clarification(reference_type: str, answer: str) -> None:
    """把澄清答案写入短期上下文；需要长期偏好时由后续记忆链路处理。"""
    patch = {}
    clean = answer.split("（")[0].strip()
    if reference_type in ("student",):
        patch = {}
        st.session_state["agent_clarified_student_name"] = clean
    elif reference_type == "homework":
        st.session_state["agent_clarified_homework_name"] = clean
    elif reference_type == "exam":
        st.session_state["agent_clarified_exam_name"] = clean
    elif reference_type in ("knowledge",):
        st.session_state["agent_clarified_knowledge_point"] = clean
    elif reference_type == "topic":
        st.session_state["agent_clarified_topic"] = clean
    if patch:
        agent_context.update_context(**patch)
    st.session_state.pop("agent_clarification", None)
    st.toast("已记住本次补充信息，请重新执行指令。")
    st.rerun()


with st.sidebar.expander("🤖 AI 助手", expanded=False):
    _context = agent_context.load_context()
    st.caption(f"当前：{agent_context.context_label(_context)}")
    _ctx_cols = st.columns(2)
    if _ctx_cols[0].button("✏️ 修改", key="agent_context_edit",
                           use_container_width=True):
        st.session_state["agent_context_open"] = True
        st.rerun()
    if _ctx_cols[1].button("🔄 重置", key="agent_context_reset",
                           use_container_width=True):
        agent_context.clear_context()
        st.rerun()
    if st.session_state.get("agent_context_open"):
        _edit_agent_context_dialog()

    st.checkbox("🤖 多Agent模式", key="multi_agent_mode",
                 help="complex 任务确认后由多个专业Agent协作执行。")
    st.text_area("用一句话告诉我要做什么", key="agent_assistant_input",
                 placeholder="例如：数学高一，出5道函数基础选择题",
                 label_visibility="collapsed")
    _agent_text = str(st.session_state.get("agent_assistant_input") or "").strip()
    _last_result = st.session_state.get("agent_last_result")
    if st.button("▶️ 执行", key="agent_run", use_container_width=True):
        if not _agent_text:
            st.warning("请先输入指令。")
        else:
            with SessionLocal() as _s:
                try:
                    # 提醒/建议类口语不走意图解析，直接返回。
                    _r = agent_service.run_quick_info(_s, _agent_text)
                    if _r is None:
                        _complexity = agent_intents.classify_complexity(_agent_text)
                        if _complexity == agent_intents.COMPLEX:
                            # complex：本轮只出计划预览，不执行、不落库。
                            _preview = agent_service.build_complex_preview(
                                _s, _agent_text)
                            st.session_state["agent_plan_preview"] = _preview
                            st.session_state.pop("agent_last_result", None)
                        else:
                            _r = agent_service.run_instruction(
                                _s, _agent_text, last_result=_last_result)
                            st.session_state["agent_last_result"] = _r
                            st.session_state.pop("agent_plan_preview", None)
                    else:
                        st.session_state["agent_last_result"] = _r
                    _s.commit()
                except Exception as _exc:
                    st.session_state["agent_last_result"] = {
                        "status": "error", "summary": str(_exc)}
            st.rerun()

    # complex 计划预览：先确认后执行。
    _render_agent_plan_preview()

    _last_result = st.session_state.get("agent_last_result")
    if _last_result:
        if _last_result.get("status") == "error":
            st.error(_last_result.get("summary"))
        else:
            st.caption(_last_result.get("summary"))
            if _last_result.get("correction_count"):
                st.caption(f"已修正 {_last_result['correction_count']} 次")
            st.caption("💬 可以直接说修改意见，如“把第2题改难”")
            if _last_result.get("artifact", {}).get("undo_stack"):
                if st.button("↩️ 撤销修正", key="agent_undo_correction",
                             use_container_width=True):
                    with SessionLocal() as _s:
                        _r = agent_service.undo_last_correction(
                            _s, _last_result)
                        _s.commit()
                        st.session_state["agent_last_result"] = _r
                    st.rerun()
        _consume_agent_result()

    _hist = agent_service.list_agent_history()
    if _hist:
        _opts = {h["history_id"]: h["instruction"][:18] for h in _hist}
        st.selectbox("历史指令", options=list(_opts),
                     format_func=lambda x: _opts[x],
                     key="agent_history_pick")
        if st.button("🔁 重新执行历史", key="agent_reexec"):
            with SessionLocal() as _s:
                _r = agent_service.reexecute_agent_history(
                    _s, st.session_state["agent_history_pick"],
                    last_result=st.session_state.get("agent_last_result"))
                _s.commit()
                st.session_state["agent_last_result"] = _r
            st.rerun()

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
if st.sidebar.button("📅 教学日历", key="nav_calendar",
                      use_container_width=True):
    st.session_state["app_top_page"] = "📅 教学日历"
    st.rerun()

# 直接按钮：数据看板
if st.sidebar.button("📊 数据看板", key="nav_databoard",
                      use_container_width=True):
    st.session_state["app_top_page"] = "📊 数据看板"
    st.rerun()
# 直接按钮：教学反思（v2.4.0 独立页）
if st.sidebar.button("💭 教学反思", key="nav_reflection",
                      use_container_width=True):
    st.session_state["app_top_page"] = "💭 教学反思"
    st.rerun()

# 折叠组：备课
with st.sidebar.expander("📚 备课", expanded=(top_page == "📚 备课")):
    lesson_subs = ["资料管理", "AI 备课", "AI 出题", "📚 单元整体设计", "题库管理"]
    if st.session_state.get("lesson_plan_tab") not in lesson_subs:
        st.session_state["lesson_plan_tab"] = "资料管理"

    def _on_lesson_sub():
        st.session_state["app_top_page"] = "📚 备课"

    st.radio("备课子功能", lesson_subs, key="lesson_plan_tab",
             label_visibility="collapsed", on_change=_on_lesson_sub)

# 折叠组：学业测评
with st.sidebar.expander("📝 学业测评",
                         expanded=(top_page == "📝 学业测评")):
    hw_subs = ["作业管理", "🤖 智能组卷",
               "✏️ 批改与分析", "📚 分层作业", "错题本"]
    if st.session_state.get("homework_tab") not in hw_subs:
        st.session_state["homework_tab"] = "作业管理"

    def _on_hw_sub():
        st.session_state["app_top_page"] = "📝 学业测评"

    st.radio("学业测评子功能", hw_subs, key="homework_tab",
             label_visibility="collapsed", on_change=_on_hw_sub)

# 折叠组：学情
with st.sidebar.expander("📊 学情", expanded=(top_page == "📊 学情")):
    analysis_subs = ["学生管理", "成绩管理", "考试分析",
                     "趋势分析", "学生画像", "🔍 AI教学诊断"]
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
    elif top_page == "📅 教学日历":
        calendar.show()
    elif top_page == "📊 数据看板":
        databoard.show()
    elif top_page == "⚙️ 设置":
        settings.show()
    elif top_page == "💭 教学反思":
        reflection.show()
    elif top_page == "📚 备课":
        st.title("📚 备课")
        sub = st.session_state["lesson_plan_tab"]
        if sub == "资料管理":
            lesson_plan.tab_materials()
        elif sub == "AI 备课":
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
