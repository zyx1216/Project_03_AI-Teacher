# -*- coding: utf-8 -*-
"""顶层 AI 助手页面：自然语言任务、结构化执行步骤和历史记录。"""
from __future__ import annotations
import json
import streamlit as st
from utils.db import SessionLocal
from utils import agent_core

QUICK_COMMANDS = {
    "帮我备课": "帮我准备明天的数学课",
    "出一份试卷": "帮我出一份高一数学函数单元测试卷",
    "分析最近考试": "分析最近一次数学考试",
    "生成讲评材料": "生成最近一次作业的讲评材料",
    "做单元整体设计": "帮我做高一数学函数单元整体设计",
}


def show() -> None:
    """渲染 AI 助手页，不展示模型原始思维链。"""
    st.subheader("🤖 AI助手")
    st.caption("用自然语言描述任务，系统会拆解为真实工具步骤；高风险写操作必须确认。")
    quick = st.columns(len(QUICK_COMMANDS))
    for index, (label, prompt) in enumerate(QUICK_COMMANDS.items()):
        if quick[index].button(label, key=f"ai_assistant_quick_{index}"):
            st.session_state["ai_assistant_page_input"] = prompt
            st.rerun()
    task = st.text_area(
        "告诉 AI 要做什么", key="ai_assistant_page_input",
        placeholder="例如：帮我准备明天的数学课，并生成一份预习作业",
        label_visibility="collapsed")
    confirmed = st.checkbox("允许执行写库类工具", key="ai_assistant_confirm",
                            help="未勾选时，高风险工具会停在确认阶段。")
    if st.button("▶️ 执行任务", type="primary", key="ai_assistant_run"):
        if not str(task or "").strip():
            st.warning("请先输入任务。")
        else:
            try:
                with SessionLocal() as session:
                    result = agent_core.run(session, str(task).strip(),
                                            confirmed=confirmed)
                    session.commit()
                st.session_state["ai_assistant_last_result"] = result
                st.toast("任务执行完成。")
            except Exception as exc:  # noqa: BLE001
                st.error(f"任务执行失败：{exc}")
            st.rerun()

    result = st.session_state.get("ai_assistant_last_result")
    if result:
        st.markdown("**执行过程**")
        for item in result.get("steps", []):
            icon = "✅" if item.get("status") == "success" else "❌"
            with st.expander(f"{icon} 步骤 {item.get('step')} · {item.get('tool_name')}",
                             expanded=item.get("status") != "success"):
                if item.get("result") is not None:
                    st.json(item["result"])
                if item.get("error"):
                    st.error(item["error"])
        st.caption(f"日志编号：{result.get('log_id')}")

    with st.expander("📜 历史执行记录", expanded=False):
        with SessionLocal() as session:
            logs = agent_core.list_logs(session)
        if not logs:
            st.caption("暂无执行记录。")
        for row in logs:
            st.markdown(f"**#{row.id} · {row.created_at:%Y-%m-%d %H:%M} · {row.status}**")
            st.caption(row.task)
            if row.steps_json:
                try:
                    steps = json.loads(row.steps_json)
                except json.JSONDecodeError:
                    steps = []
                for item in steps:
                    st.caption(f"- {item.get('tool_name')}：{item.get('status')}")
