# -*- coding: utf-8 -*-
"""顶层 AI 助手页面（v3.3.1 合并原侧边栏嵌入式助手）。

主区块走 agent_service 链路：教学上下文、多Agent模式、复杂任务先出计划再确认、
指代澄清、历史指令与修正撤销；
折叠区保留 v3.1.0 的 agent_core 工具步骤与执行日志。不展示模型原始思维链。
"""
from __future__ import annotations

import json

import streamlit as st

from utils import (
    agent_context, agent_core, agent_intents, agent_service, multi_agent,
)
from utils.db import SessionLocal

QUICK_COMMANDS = {
    "帮我备课": "帮我准备明天的数学课",
    "出一份试卷": "帮我出一份高一数学函数单元测试卷",
    "分析最近考试": "分析最近一次数学考试",
    "生成讲评材料": "生成最近一次作业的讲评材料",
    "做单元整体设计": "帮我做高一数学函数单元整体设计",
}

# 结果 route -> 组内子功能 session key，供「打开结果」一次性跳转。
SUB_KEY_BY_ROUTE = {
    "📚 备课": "lesson_plan_tab",
    "📝 学业测评": "homework_tab",
    "📊 学情": "analysis_tab",
}


# ---------------------------------------------------------------------------
# 教学上下文
# ---------------------------------------------------------------------------

def _load_material_chapters(material_id) -> list[str]:
    """取某份资料的章节标题；复用备课区同一口径，取不到返回空表。"""
    try:
        from modules import lesson_plan
        return list(lesson_plan._load_material_chapter_titles(int(material_id)))
    except Exception:  # noqa: BLE001 —— 章节读不到就降级为手动输入
        return []


@st.dialog("修改当前上下文")
def _context_dialog() -> None:
    """编辑教学上下文；v3.4.1：章节从资料联动选择，去掉班级字段。"""
    from models.models import Textbook
    from utils.app_config import (
        DISPLAY_GRADE_CHOICES, SUBJECT_NAMES, to_storage_grade)
    from utils.db import SessionLocal

    current = agent_context.load_context()
    subject_index = (SUBJECT_NAMES.index(current["subject"])
                     if current.get("subject") in SUBJECT_NAMES else 1)
    grade_index = (list(DISPLAY_GRADE_CHOICES[:-1]).index(current["grade"])
                   if current.get("grade") in DISPLAY_GRADE_CHOICES[:-1] else 0)
    dialog_subject = st.selectbox("学科", SUBJECT_NAMES, index=subject_index,
                                  key="ai_ctx_subject")
    dialog_grade = st.selectbox("年级", DISPLAY_GRADE_CHOICES[:-1],
                                index=grade_index, key="ai_ctx_grade")

    # 章节：按学科+年级筛资料（与备课区同口径：学科/年级匹配或为空），
    # 再取该资料的章节目录；没有资料或读不到目录时降级为手动输入。
    storage_grade = to_storage_grade(dialog_grade)
    with SessionLocal() as session:
        query = session.query(Textbook).filter(
            (Textbook.subject == dialog_subject) | Textbook.subject.is_(None))
        if storage_grade:
            query = query.filter(
                (Textbook.grade == storage_grade) | Textbook.grade.is_(None))
        books = query.order_by(Textbook.id.desc()).all()

    dialog_chapter = ""
    if not books:
        st.info("暂无该学科年级的资料，章节可手动输入。")
        dialog_chapter = st.text_input(
            "章节", value=current.get("current_chapter") or "",
            key="ai_ctx_chapter")
    else:
        book_options = [None] + [book.id for book in books]
        book_labels = ["不关联资料"] + [book.name for book in books]
        selected_book = st.selectbox(
            "选择资料", book_options,
            format_func=lambda x: book_labels[book_options.index(x)],
            key="ai_ctx_book")
        chapters = (_load_material_chapters(selected_book)
                    if selected_book else [])
        if chapters:
            saved_chapter = current.get("current_chapter") or ""
            chapter_index = (chapters.index(saved_chapter)
                             if saved_chapter in chapters else 0)
            dialog_chapter = st.selectbox("选择章节", chapters,
                                          index=chapter_index,
                                          key="ai_ctx_chapter_select")
        else:
            dialog_chapter = st.text_input(
                "章节（资料未提取到目录，可手动输入）",
                value=current.get("current_chapter") or "",
                key="ai_ctx_chapter")

    c1, c2 = st.columns(2)
    if c1.button("保存", type="primary", key="ai_ctx_save",
                 use_container_width=True):
        # v3.4.1：不再写班级字段；弹窗开关也不再用 session_state 中转。
        agent_context.update_context(
            subject=dialog_subject, grade=dialog_grade,
            current_chapter=str(dialog_chapter or "").strip())
        st.rerun()
    if c2.button("取消", key="ai_ctx_cancel", use_container_width=True):
        st.rerun()


def _context_bar() -> None:
    """当前教学上下文 + 修改 / 重置。"""
    context = agent_context.load_context()
    c1, c2, c3 = st.columns([4, 1, 1])
    c1.caption(f"当前上下文：{agent_context.context_label(context)}")
    if c2.button("✏️ 修改", key="ai_assistant_ctx_edit",
                 use_container_width=True):
        # v3.4.1：直接打开弹窗，不经 session_state 中转——
        # 点 x / 空白处关闭后状态不残留，切页回来不会自动弹出。
        _context_dialog()
    if c3.button("🔄 重置", key="ai_assistant_ctx_reset",
                 use_container_width=True):
        agent_context.clear_context()
        st.toast("已重置教学上下文。")
        st.rerun()


# ---------------------------------------------------------------------------
# 指令执行
# ---------------------------------------------------------------------------

def _submit(text: str, retried: bool = False) -> None:
    """执行一条指令：快问快答 → 复杂度判定 → 简单执行 / 复杂只出计划。"""
    with SessionLocal() as session:
        try:
            quick = agent_service.run_quick_info(session, text)
            if quick is not None:
                st.session_state["ai_assistant_last_result"] = quick
            elif agent_intents.classify_complexity(text) == agent_intents.COMPLEX:
                # complex：本轮只出计划预览，不执行、不落库。
                st.session_state["ai_assistant_plan_preview"] = (
                    agent_service.build_complex_preview(session, text))
                st.session_state.pop("ai_assistant_last_result", None)
            else:
                st.session_state["ai_assistant_last_result"] = (
                    agent_service.run_instruction(
                        session, text,
                        last_result=st.session_state.get(
                            "ai_assistant_last_result")))
                st.session_state.pop("ai_assistant_plan_preview", None)
            session.commit()
        except agent_service.AgentClarificationNeeded as need:
            session.rollback()
            payload = dict(need.clarification or {})
            payload["instruction"] = text
            payload["retried"] = bool(retried)
            st.session_state["ai_assistant_clarification"] = payload
        except Exception as exc:  # noqa: BLE001 —— 页面只展示友好摘要
            session.rollback()
            st.session_state["ai_assistant_last_result"] = {
                "status": "error", "summary": str(exc)}


def _execute_plan(session, preview: dict, start_index: int) -> dict:
    """确认后执行计划：多Agent开关打开走 Coordinator，否则走单链路执行。"""
    if not st.session_state.get("ai_assistant_multi_agent"):
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
    """多Agent结果：按 Agent 展开，支持重新执行 / 跳过。"""
    scenario = plan_result.get("scenario")
    keys = multi_agent.SCENARIO_STEPS.get(scenario, [])
    st.caption("协调者已按角色拆解任务并分派给各专业 Agent。")
    for out in plan_result.get("agents") or []:
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
                             key=f"ai_assistant_agent_reexec_{idx}",
                             use_container_width=True):
                    with SessionLocal() as session:
                        st.session_state["ai_assistant_plan_result"] = (
                            _execute_plan(session, preview, idx))
                        session.commit()
                    st.rerun()
                if b2.button("⏭️ 跳过此Agent",
                             key=f"ai_assistant_agent_skip_{idx}",
                             use_container_width=True):
                    with SessionLocal() as session:
                        st.session_state["ai_assistant_plan_result"] = (
                            _execute_plan(session, preview,
                                          min(idx + 1, len(keys))))
                        session.commit()
                    st.rerun()


def _render_plan_preview() -> None:
    """复杂指令的计划预览：先确认再执行，含跳过 / 取消 / 失败重试。"""
    preview = st.session_state.get("ai_assistant_plan_preview")
    if not preview:
        return
    plan = preview.get("plan") or []
    st.markdown("**📋 执行计划（请确认后开始）**")
    for index, step in enumerate(plan, start=1):
        st.markdown(f"{index}. {step.get('name', '')}")
    start_index = int(preview.get("_start_index", 0))
    if start_index:
        st.caption(f"已设置从前 {start_index} 步之后开始执行。")

    plan_result = st.session_state.get("ai_assistant_plan_result")
    if plan_result is None:
        c1, c2, c3 = st.columns(3)
        if c1.button("▶️ 确认开始执行", key="ai_assistant_plan_confirm",
                     type="primary", use_container_width=True):
            with SessionLocal() as session:
                st.session_state["ai_assistant_plan_result"] = _execute_plan(
                    session, preview, start_index)
                session.commit()
            st.rerun()
        if c2.button("⏭️ 跳过此步", key="ai_assistant_plan_skip",
                     use_container_width=True):
            preview["_start_index"] = min(start_index + 1,
                                          max(len(plan) - 1, 0))
            st.toast("已跳过当前第一步。")
            st.rerun()
        if c3.button("🗑️ 取消全部", key="ai_assistant_plan_cancel",
                     use_container_width=True):
            st.session_state.pop("ai_assistant_plan_preview", None)
            st.toast("已取消计划，未执行任何操作。")
            st.rerun()
        return

    # 执行结果：进度、详细日志、多Agent过程与失败重试。
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
        for step in steps:
            icon = "✅" if step.get("status") == "success" else "❌"
            st.markdown(
                f"{icon} {step.get('name', '')}：{step.get('summary', '')}")
    cc1, cc2 = st.columns(2)
    if failed_index is not None and cc1.button(
            "🔄 从失败步骤重试", key="ai_assistant_plan_retry",
            use_container_width=True):
        with SessionLocal() as session:
            st.session_state["ai_assistant_plan_result"] = _execute_plan(
                session, preview, int(failed_index))
            session.commit()
        st.rerun()
    if cc2.button("关闭计划", key="ai_assistant_plan_close",
                  use_container_width=True):
        st.session_state.pop("ai_assistant_plan_preview", None)
        st.session_state.pop("ai_assistant_plan_result", None)
        st.rerun()


# ---------------------------------------------------------------------------
# 指代澄清
# ---------------------------------------------------------------------------

def _render_clarification() -> None:
    """指代不清时先问清楚，答案写回上下文后最多自动重跑一次。"""
    need = st.session_state.get("ai_assistant_clarification")
    if not need:
        return
    st.warning(need.get("question") or "需要补充信息，请说明具体对象。")
    options = need.get("options") or []
    reference_type = need.get("reference_type") or ""
    if options:
        answer = str(st.radio("请选择", options,
                              key="ai_assistant_clarification_choice"))
    else:
        answer = str(st.text_input("请直接补充",
                                   key="ai_assistant_clarification_answer"))
    c1, c2 = st.columns(2)
    if c1.button("确认并继续", key="ai_assistant_clarification_submit",
                 type="primary", use_container_width=True):
        if not answer.strip():
            st.warning("补充内容不能为空。")
            return
        _apply_clarification(reference_type, answer.strip())
        st.rerun()
    if c2.button("取消", key="ai_assistant_clarification_cancel",
                 use_container_width=True):
        st.session_state.pop("ai_assistant_clarification", None)
        st.rerun()


def _apply_clarification(reference_type: str, answer: str) -> None:
    """把澄清结果落到教学上下文；能识别的写字段，其余提示重新描述。"""
    need = st.session_state.get("ai_assistant_clarification") or {}
    instruction = str(need.get("instruction") or "")
    clean = answer.split("（")[0].strip() or answer
    # 章节/知识点是 agent_context 现有字段，写回后下次解析可直接补全。
    if reference_type in ("topic", "knowledge"):
        agent_context.update_context(current_chapter=clean)
    st.session_state.pop("ai_assistant_clarification", None)
    if instruction and not need.get("retried"):
        _submit(instruction, retried=True)
    else:
        st.toast("已记下补充信息，请把对象写清楚后重新执行。")


# ---------------------------------------------------------------------------
# 结果与历史
# ---------------------------------------------------------------------------

def _open_result(result: dict) -> None:
    """按结果路由一次性跳转，并带上目标子功能与内部状态。"""
    st.session_state["_pending_app_route"] = result["route"]
    if result.get("sub"):
        st.session_state["_pending_app_sub"] = result["sub"]
        st.session_state["_pending_app_sub_key"] = SUB_KEY_BY_ROUTE.get(
            result["route"])
    for key, value in (result.get("extra") or {}).items():
        st.session_state[key] = value
    st.session_state.pop("ai_assistant_last_result", None)
    st.rerun()


def _render_result() -> None:
    """执行结果：摘要、修正撤销与打开结果。"""
    result = st.session_state.get("ai_assistant_last_result")
    if not result:
        return
    if result.get("status") == "error":
        st.error(result.get("summary"))
        return
    st.caption(result.get("summary") or "")
    if result.get("correction_count"):
        st.caption(f"已修正 {result['correction_count']} 次")
    st.caption("💬 可以直接说修改意见，如“把第2题改难”")
    c1, c2 = st.columns(2)
    if (bool((result.get("artifact") or {}).get("undo_stack"))
            and c1.button("↩️ 撤销修正", key="ai_assistant_undo_correction",
                          use_container_width=True)):
        with SessionLocal() as session:
            st.session_state["ai_assistant_last_result"] = (
                agent_service.undo_last_correction(session, result))
            session.commit()
        st.rerun()
    if result.get("route") and c2.button("➡️ 打开结果",
                                        key="ai_assistant_open_result",
                                        use_container_width=True):
        _open_result(result)


def _render_history() -> None:
    """历史指令：选一条重新执行。"""
    history = agent_service.list_agent_history()
    if not history:
        return
    with st.expander("🕘 历史指令", expanded=False):
        options = {h["history_id"]: h["instruction"][:24] for h in history}
        st.selectbox("选择历史指令", options=list(options),
                     format_func=lambda x: options[x],
                     key="ai_assistant_history_pick")
        if st.button("🔁 重新执行历史", key="ai_assistant_reexec",
                     use_container_width=True):
            with SessionLocal() as session:
                st.session_state["ai_assistant_last_result"] = (
                    agent_service.reexecute_agent_history(
                        session,
                        st.session_state["ai_assistant_history_pick"],
                        last_result=st.session_state.get(
                            "ai_assistant_last_result")))
                session.commit()
            st.rerun()


# ---------------------------------------------------------------------------
# v3.1.0 保留：Agent 工具步骤 + 执行日志
# ---------------------------------------------------------------------------

def _render_agent_core_section() -> None:
    """工具步骤式 Agent 任务与执行日志（高风险工具需显式允许）。"""
    with st.expander("🧭 Agent 任务（工具步骤 + 执行日志）", expanded=False):
        task = st.text_area(
            "Agent 任务", key="ai_assistant_task_input",
            placeholder="例如：帮我准备明天的数学课，并生成一份预习作业",
            label_visibility="collapsed")
        confirmed = st.checkbox(
            "允许执行写库类工具", key="ai_assistant_confirm",
            help="未勾选时，高风险工具会停在确认阶段。")
        if st.button("▶️ 执行任务", key="ai_assistant_task_run",
                     use_container_width=True):
            if not str(task or "").strip():
                st.warning("请先输入任务。")
            else:
                try:
                    with SessionLocal() as session:
                        result = agent_core.run(session, str(task).strip(),
                                                confirmed=confirmed)
                        session.commit()
                    st.session_state["ai_assistant_task_result"] = result
                    st.toast("任务执行完成。")
                except Exception as exc:  # noqa: BLE001
                    st.error(f"任务执行失败：{exc}")
                st.rerun()
        result = st.session_state.get("ai_assistant_task_result")
        if result:
            st.markdown("**执行过程**")
            for item in result.get("steps", []):
                icon = "✅" if item.get("status") == "success" else "❌"
                with st.expander(
                        f"{icon} 步骤 {item.get('step')} · "
                        f"{item.get('tool_name')}",
                        expanded=item.get("status") != "success"):
                    if item.get("result") is not None:
                        st.json(item["result"])
                    if item.get("error"):
                        st.error(item["error"])
            st.caption(f"日志编号：{result.get('log_id')}")

        st.markdown("**📜 执行记录**")
        with SessionLocal() as session:
            logs = agent_core.list_logs(session)
        if not logs:
            st.caption("暂无执行记录。")
        for row in logs[:20]:
            st.markdown(f"**#{row.id} · {row.created_at:%Y-%m-%d %H:%M} · "
                        f"{row.status}**")
            st.caption(row.task)
            if row.steps_json:
                try:
                    steps = json.loads(row.steps_json)
                except json.JSONDecodeError:
                    steps = []
                for item in steps:
                    st.caption(f"- {item.get('tool_name')}：{item.get('status')}")


# ---------------------------------------------------------------------------
# 页面
# ---------------------------------------------------------------------------

def show() -> None:
    """渲染 AI 助手页（合并后唯一入口）。"""
    st.subheader("🤖 AI助手")
    st.caption("用自然语言描述任务，系统会拆解为真实工具步骤；高风险写操作必须确认。")
    _context_bar()

    quick = st.columns(len(QUICK_COMMANDS))
    for index, (label, prompt) in enumerate(QUICK_COMMANDS.items()):
        if quick[index].button(label, key=f"ai_assistant_quick_{index}"):
            st.session_state["ai_assistant_page_input"] = prompt
            st.rerun()

    st.checkbox("🤖 多Agent模式", key="ai_assistant_multi_agent",
                help="complex 任务确认后由多个专业Agent协作执行。")
    task = st.text_area(
        "告诉 AI 要做什么", key="ai_assistant_page_input",
        placeholder="例如：数学高一，出5道函数基础选择题",
        label_visibility="collapsed")
    if st.button("▶️ 执行", type="primary", key="ai_assistant_run",
                 use_container_width=True):
        text = str(task or "").strip()
        if not text:
            st.warning("请先输入指令。")
        else:
            _submit(text)
            st.rerun()

    _render_clarification()
    _render_plan_preview()
    _render_result()
    _render_history()
    _render_agent_core_section()
