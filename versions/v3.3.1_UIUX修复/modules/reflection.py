# -*- coding: utf-8 -*-
"""
教学反思独立页面（v2.4.0）。

由原学情页「教学反思」与备课页「课堂实录」合并而来，仅做入口迁移，
不改变任何业务逻辑。三个标签页：课堂实录 / 教学反思 / 改进历史。
"""

from datetime import date

import pandas as pd
import streamlit as st

from utils.db import SessionLocal
from utils import (
    llm_client, student_service as ss, exam_service as es,
    reflection_service as rs,
)
from utils.app_config import SUBJECT_NAMES


def show():
    """教学反思独立页：课堂实录 / 教学反思 / 改进历史。"""
    st.title("💭 教学反思")
    tabs = st.tabs(["🎙️ 课堂实录", "💭 教学反思", "📚 改进历史"])
    with tabs[0]:
        _recording_tab()
    with tabs[1]:
        _reflection_tab()
    with tabs[2]:
        _improvement_history_tab()


def _read_prompt_file(filename: str) -> str:
    """读取 prompts 目录下的系统提示词模板。"""
    import config
    return (
        Path(config.BASE_DIR) / "prompts" / filename
    ).read_text(encoding="utf-8")


from pathlib import Path  # noqa: E402  供 _read_prompt_file 使用

def _recording_tab():
    """文本课堂实录：粘贴或上传逐字稿，生成纪要并保存历史。"""
    from utils import class_recording_service

    st.subheader("🎙️ 课堂实录")
    st.caption("本版只支持文本逐字稿，不做录音自动转写。")

    title = st.text_input("课堂标题", key="recording_title")
    upload = st.file_uploader(
        "上传 TXT/MD 逐字稿（可选）",
        type=["txt", "md"], key="recording_upload")
    default_text = ""
    if upload is not None:
        default_text = upload.read().decode("utf-8", errors="ignore")
    transcript = st.text_area(
        "逐字稿", value=default_text, height=260,
        key="recording_transcript")

    if st.button("🤖 生成纪要", key="recording_generate"):
        try:
            st.session_state["recording_summary"] = (
                class_recording_service.summarize_transcript(
                    transcript, context=title))
        except ValueError as exc:
            st.warning(str(exc))

    summary = st.session_state.get("recording_summary")
    if summary is not None:
        st.markdown(f"**课堂摘要：**{summary.get('summary', '')}")
        st.caption(f"学生互动：{summary.get('interaction', '')}")
        cols = st.columns(3)
        cols[0].markdown("重点知识\n" + "\n".join(
            f"- {x}" for x in summary.get("key_points", [])))
        cols[1].markdown("课堂亮点\n" + "\n".join(
            f"- {x}" for x in summary.get("highlights", [])))
        cols[2].markdown("后续建议\n" + "\n".join(
            f"- {x}" for x in summary.get("suggestions", [])))
        if st.button("💾 保存实录", key="recording_save"):
            class_recording_service.save_recording({
                "title": title, "transcript": transcript,
                "summary": summary,
            })
            st.toast("已保存。")

    st.divider()
    _recording_history()


def _recording_history():
    """课堂实录历史列表和详情。"""
    from utils import class_recording_service

    store = class_recording_service.load_recordings()
    records = store.get("records", [])
    if not records:
        st.info("暂无课堂实录。")
        return

    options = {item["id"]: f"{item['title']}｜{item.get('created_at', '')}"
               for item in records}
    picked = st.selectbox(
        "选择历史实录", list(options),
        format_func=lambda x: options[x],
        key="recording_pick")
    record = next(item for item in records if item["id"] == picked)
    with st.expander("查看纪要和逐字稿"):
        st.json(record.get("summary", {}))
        st.text_area(
            "逐字稿", value=record.get("transcript", ""),
            height=220, key=f"recording_history_text_{picked}")
    if st.button("🗑️ 删除", key="recording_delete"):
        class_recording_service.delete_recording(picked)

def _reflection_tab():
    """教学反思：反思生成（含改进计划入口）。"""
    with SessionLocal() as session:
        rs.refresh_expired_plans(session)
        session.commit()
    _render_reflection_generation()

def _render_reflection_generation():
    """生成、保存、查看反思，并为已保存反思维护改进计划。"""
    dialog_state = st.session_state.get("plan_dialog_state")
    if dialog_state:
        _plan_dialog(dialog_state[0], dialog_state[1])
        return

    with SessionLocal() as session:
        exams = es.list_exams(session)
        classes = ss.list_classes(session)
    if not exams:
        st.info("还没有考试数据，先到「成绩管理」新建考试并导入成绩，再来写反思。")
        return

    exam_labels = [f"{e.name}（{e.exam_date}）" for e in exams]
    class_options = ["全部班级"] + classes

    with st.form("reflection_scope_form"):
        scope_type = st.selectbox("反思范围", ["单次考试", "一段时间（起止两场考试）"],
                                  key="reflection_scope")
        c1, c2, c3 = st.columns(3)
        start_label = c1.selectbox("起始考试 / 单次考试", exam_labels,
                                   key="reflection_start")
        end_label = None
        if scope_type.startswith("一段"):
            end_label = c2.selectbox("截止考试", exam_labels,
                                     index=len(exam_labels) - 1, key="reflection_end")
        class_choice = c3.selectbox("班级", class_options, key="reflection_class")
        generate = st.form_submit_button("🤖 生成教学反思", type="primary")

    start_id = exams[exam_labels.index(start_label)].id
    end_id = exams[exam_labels.index(end_label)].id if end_label else None
    class_name = None if class_choice == "全部班级" else class_choice
    scope_key = "range" if scope_type.startswith("一段") else "exam"

    if generate:
        if not llm_client.is_configured():
            st.warning("还没配置 AI：请到「⚙️ 设置 → 主模型配置」填写 API Key 后再来。")
        elif scope_key == "range" and (end_id is None or end_id == start_id):
            st.warning("时间段要选两场不同的起止考试；只想分析一场请选“单次考试”。")
        else:
            with SessionLocal() as session:
                data_text = rs.build_reflection_data_text(
                    session, scope_key, start_id, end_id, class_name)
            with st.expander("查看发给 AI 的数据", expanded=False):
                st.code(data_text)
            system_prompt = _read_prompt_file("reflection_prompt.txt")
            with st.spinner("AI 正在结合成绩和作业错题撰写反思……"):
                try:
                    reply = llm_client.chat(system_prompt, data_text, temperature=0.5)
                    title_scope = (f"{start_label} 至 {end_label}"
                                   if scope_key == "range" else start_label)
                    st.session_state["reflection_draft"] = {
                        "title": f"教学反思·{title_scope}",
                        "sections": rs.parse_sections(reply),
                        "scope_type": scope_key, "start_id": start_id,
                        "end_id": end_id, "class_name": class_name}
                    st.rerun()
                except llm_client.LLMConfigError as exc:
                    st.warning(str(exc))
                except llm_client.LLMCallError as exc:
                    st.error(str(exc))

    draft = st.session_state.get("reflection_draft")
    if draft:
        st.markdown("#### 反思内容（可在线编辑后保存留档）")
        title = st.text_input("标题", value=draft["title"], key="reflection_title")
        edited = {}
        for name in rs.SECTIONS:
            edited[name] = st.text_area(
                f"## {name}", value=draft["sections"].get(name, ""), height=120)
        b1, b2 = st.columns(2)
        if b1.button("💾 保存留档", type="primary"):
            with SessionLocal() as session:
                saved = rs.save_reflection(
                    session, title, draft["scope_type"], draft["start_id"],
                    draft["class_name"], edited, end_exam_id=draft["end_id"])
                session.commit()
                saved_id = saved.id
            st.toast("反思已保存，可在下方制定改进计划。")
            _sync_analysis_context(class_name=draft.get("class_name"),
                                   last_action="保存教学反思")
            st.session_state.pop("reflection_draft", None)
            st.session_state["reflection_history_pick_id"] = saved_id
            st.rerun()
        if b2.button("🧹 清空当前编辑"):
            st.session_state.pop("reflection_draft", None)
            st.rerun()

    st.divider()
    st.markdown("#### 历史反思")
    with SessionLocal() as session:
        history = rs.list_reflections(session, class_name)
        if not history:
            st.caption("还没有保存过的反思。")
            return

        labels = []
        label_to_row = {}
        for row in history:
            label = f"{row.title}｜{row.created_at:%Y-%m-%d}"
            labels.append(label)
            label_to_row[label] = row

        preferred_id = st.session_state.pop("reflection_history_pick_id", None)
        preferred_index = next(
            (i for i, row in enumerate(history) if row.id == preferred_id), 0)
        pick = st.selectbox("选择一条反思", labels,
                            index=preferred_index,
                            key="reflection_history_pick")
        selected = label_to_row[pick]
        data = rs.load_reflection_content(selected)
        plan = rs.get_plan_by_reflection(session, selected.id)
        blob = rs.export_word(selected)

    for name in rs.SECTIONS:
        st.markdown(f"**{name}**")
        st.write(data["sections"].get(name) or "—")

    _render_plan_panel(selected, plan)

    d1, d2 = st.columns(2)
    d1.download_button(
        "⬇️ 导出反思 Word", blob,
        file_name=f"{selected.title}.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        key="download_reflection")
    if d2.button("🗑️ 删除这条反思", key="del_reflection"):
        with SessionLocal() as session:
            rs.delete_reflection(session, selected.id)
            session.commit()
        st.toast("已删除。")
        st.rerun()



def _draft_measures_key(reflection_id: int) -> str:
    return f"plan_draft_measures_{reflection_id}"


@st.dialog("制定改进计划", width="large")
def _plan_dialog(reflection_id: int, plan_id: int | None = None):
    """创建或编辑改进计划。"""
    with SessionLocal() as session:
        reflection = session.get(__import__("models.models", fromlist=["TeachingReflection"]).TeachingReflection, reflection_id)
        if reflection is None:
            st.error("反思不存在。")
            return
        existing = (session.get(__import__("models.models", fromlist=["ReflectionPlan"]).ReflectionPlan, plan_id)
                    if plan_id else rs.get_plan_by_reflection(session, reflection_id))
        later_exams = [exam for exam in es.list_exams(session)
                       if exam.exam_date > reflection.created_at.date()]

    draft_key = _draft_measures_key(reflection_id)
    if draft_key not in st.session_state:
        st.session_state[draft_key] = (
            rs.plan_content(existing) if existing else
            [{"measure": "", "method": "课堂调整", "expected_effect": ""}])

    c1, c2 = st.columns(2)
    if c1.button("🤖 AI 生成措施", key="plan_generate"):
        try:
            content = rs.load_reflection_content(reflection)["raw"]
            st.session_state[draft_key] = rs.generate_improvement_plan(
                content, reflection.class_name)
            st.rerun()
        except (ValueError, llm_client.LLMConfigError, llm_client.LLMCallError) as exc:
            st.warning(str(exc))
    if c2.button("➕ 添加空措施", key="plan_add_measure"):
        st.session_state[draft_key].append(
            {"measure": "", "method": "课堂调整", "expected_effect": ""})
        st.rerun()

    measures = st.session_state[draft_key]
    for index, item in enumerate(list(measures)):
        st.markdown(f"**措施 {index + 1}**")
        cols = st.columns([3, 1.3, 2, 0.7])
        cols[0].text_input(
            "措施内容", value=item.get("measure", ""),
            key=f"plan_measure_{reflection_id}_{index}",
            label_visibility="collapsed",
            placeholder="具体做什么")
        method_value = item.get("method", "课堂调整")
        method_index = rs.PLAN_METHODS.index(method_value) if method_value in rs.PLAN_METHODS else 3
        cols[1].selectbox(
            "实施方式", rs.PLAN_METHODS, index=method_index,
            key=f"plan_method_{reflection_id}_{index}",
            label_visibility="collapsed")
        cols[2].text_input(
            "预期效果", value=item.get("expected_effect", ""),
            key=f"plan_expected_{reflection_id}_{index}",
            label_visibility="collapsed",
            placeholder="预期达到的效果")
        if cols[3].button("🗑️", key=f"plan_remove_measure_{reflection_id}_{index}"):
            measures.pop(index)
            st.rerun()

    options = [None] + [exam.id for exam in later_exams]
    labels = {None: "不设置验证考试（仅手动验证）"}
    labels.update({exam.id: f"{exam.name}（{exam.exam_date}）"
                   for exam in later_exams})
    current_exam = existing.verify_exam_id if existing else None
    exam_index = options.index(current_exam) if current_exam in options else 0
    verify_exam_id = st.selectbox(
        "选择验证考试", options, index=exam_index,
        format_func=lambda x: labels[x], key=f"plan_verify_exam_{reflection_id}")

    action_cols = st.columns(2)
    if action_cols[0].button("💾 保存改进计划", type="primary", key="plan_save"):
        submitted_measures = []
        for index in range(len(measures)):
            submitted_measures.append({
                "measure": st.session_state[f"plan_measure_{reflection_id}_{index}"],
                "method": st.session_state[f"plan_method_{reflection_id}_{index}"],
                "expected_effect": st.session_state[f"plan_expected_{reflection_id}_{index}"],
            })
        try:
            with SessionLocal() as session:
                if existing:
                    rs.update_plan(session, existing.id, submitted_measures,
                                   verify_exam_id)
                else:
                    rs.save_plan(session, reflection_id, submitted_measures,
                                 verify_exam_id)
                session.commit()
            st.toast("改进计划已保存。")
            st.session_state.pop(draft_key, None)
            st.session_state.pop("plan_dialog_state", None)
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
    if action_cols[1].button("取消", key="plan_cancel"):
        st.session_state.pop(draft_key, None)
        st.session_state.pop("plan_dialog_state", None)
        st.rerun()


def _status_badge(status: str) -> str:
    """返回计划状态的彩色标记。"""
    colors = {"pending": "#ca8a04", "verified": "#16a34a", "expired": "#6b7280"}
    name = rs.PLAN_STATUSES.get(status, status)
    return f"<span style='color:{colors.get(status, '#6b7280')};font-weight:700'>{name}</span>"


def _render_plan_panel(reflection, plan):
    """渲染计划入口或计划详情。"""
    st.divider()
    st.markdown("#### 📋 改进计划")
    if plan is None:
        st.caption("把反思中的问题转成可执行措施，后续可用考试结果验证效果。")
        if st.button("📋 制定改进计划", key=f"make_plan_{reflection.id}"):
            st.session_state["plan_dialog_state"] = (reflection.id, None)
            st.rerun()
        return

    st.markdown(_status_badge(plan.status), unsafe_allow_html=True)
    if plan.verify_exam_id:
        with SessionLocal() as session:
            exam = session.get(__import__("models.models", fromlist=["Exam"]).Exam, plan.verify_exam_id)
        if exam:
            st.caption(f"验证考试：{exam.name}（{exam.exam_date}）")
    else:
        st.caption("验证考试：未设置，仅支持手动确认。")

    with st.expander("查看改进措施", expanded=True):
        for index, item in enumerate(rs.plan_content(plan), start=1):
            st.markdown(
                f"{index}. **{item['measure']}**"
                f"（{item['method']}）")
            st.caption("预期效果：" + item["expected_effect"])

    actions = st.columns(3)
    if actions[0].button("✏️ 编辑计划", disabled=plan.status != "pending",
                         key=f"plan_edit_{plan.id}"):
        st.session_state["plan_dialog_state"] = (reflection.id, plan.id)
        st.rerun()
    if actions[1].button("🗑️ 删除计划", key=f"plan_delete_{plan.id}"):
        with SessionLocal() as session:
            rs.delete_plan(session, plan.id)
            session.commit()
        st.toast("改进计划已删除。")
        st.rerun()
    if actions[2].button("✅ 手动标记已验证",
                         disabled=plan.status == "verified",
                         key=f"plan_manual_verify_{plan.id}"):
        with SessionLocal() as session:
            rs.mark_plan_verified_manually(session, plan.id)
            session.commit()
        st.toast("已手动标记验证完成。")
        st.rerun()

    if plan.status == "verified":
        _render_verify_report(plan)


def _render_verify_report(plan):
    """展示自动或手动验证报告。"""
    report = rs.load_verify_result(plan)
    if not report:
        return
    with st.expander("📊 验证报告", expanded=True):
        effect = report.get("overall_effect", "—")
        effect_color = {"有效": "#16a34a", "部分有效": "#ea580c",
                        "效果不明显": "#dc2626"}.get(effect, "#1f4e79")
        st.markdown(
            f"<h4 style='color:{effect_color}'>整体效果：{effect}</h4>",
            unsafe_allow_html=True)
        for item in report.get("measure_effects", []):
            rate = float(item.get("attainment") or 0)
            st.caption(f"{item.get('measure')}｜{item.get('result')}")
            st.progress(rate)

        support = report.get("data_support", [])
        if support:
            st.dataframe(pd.DataFrame({"数据支撑": support}),
                         hide_index=True, width="stretch")

        knowledge = report.get("knowledge_effects", [])
        if knowledge:
            st.dataframe(pd.DataFrame(knowledge),
                                         hide_index=True, width="stretch")
        else:
            st.caption("无逐题数据，不评估知识点变化。")

        suggestions = report.get("suggestions", [])
        if suggestions:
            st.info("后续建议：" + "；".join(suggestions))


def _render_improvement_history():
    """展示已验证的教学改进闭环。"""
    from utils.app_config import SUBJECT_NAMES

    filter_cols = st.columns([1, 1, 1])
    subject = filter_cols[0].selectbox(
        "学科", ["全部学科"] + SUBJECT_NAMES,
        key="improvement_history_subject")
    start_date = filter_cols[1].date_input(
        "开始日期", value=date(2026, 1, 1),
        key="improvement_history_start")
    end_date = filter_cols[2].date_input(
        "结束日期", value=date(2026, 12, 31),
        key="improvement_history_end")

    with SessionLocal() as session:
        items = rs.get_improvement_history(
            session,
            None if subject == "全部学科" else subject,
            start_date, end_date)

    if not items:
        st.info("暂无已完成的改进闭环。")
        return

    table = pd.DataFrame([{
        "反思时间": item["reflection_created_at"].strftime("%Y-%m-%d")
        if item["reflection_created_at"] else "—",
        "基准考试": item["base_exam"],
        "验证考试": item["verify_exam"],
        "核心问题": item["core_problem"],
        "措施数量": item["measure_count"],
        "整体效果": item["overall_effect"],
    } for item in items])
    st.dataframe(table, hide_index=True, width="stretch")

    options = {
        f"{item['reflection_title']}｜{item['overall_effect']}": item["plan_id"]
        for item in items}
    picked = st.selectbox("选择记录", list(options.keys()),
                          key="improvement_history_pick")
    plan_id = options[picked]
    c1, c2 = st.columns(2)
    if c1.button("查看详情", key="open_improvement_detail"):
        _improvement_detail_dialog(plan_id)
    if c2.button("📄 导出教学改进报告 Word",
                 key="export_improvement_report"):
        with SessionLocal() as session:
            data = rs.export_improvement_report(session, items)
        st.download_button(
            "⬇️ 下载 Word", data,
            file_name="教学改进年度报告.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            key="download_improvement_report")


@st.dialog("改进详情")
def _improvement_detail_dialog(plan_id: int):
    """查看一条改进闭环的完整信息。"""
    with SessionLocal() as session:
        plan = session.get(__import__("models.models", fromlist=["ReflectionPlan"]).ReflectionPlan, plan_id)
        if plan is None:
            st.error("记录不存在。")
            return
        reflection = session.get(
            __import__("models.models", fromlist=["TeachingReflection"]).TeachingReflection,
            plan.reflection_id)
        reflection_data = rs.load_reflection_content(reflection)
        report = rs.load_verify_result(plan)

    st.markdown("#### 反思核心问题")
    st.write(reflection_data["sections"].get("不足之处") or "—")
    st.markdown("#### 改进措施")
    for index, item in enumerate(rs.plan_content(plan), start=1):
        st.markdown(
            f"{index}. {item['measure']}"
            f"（{item['method']}）")
        st.caption("预期：" + item["expected_effect"])
    st.markdown("#### 验证结果")
    st.write(report.get("overall_effect", "—"))
    for suggestion in report.get("suggestions", []):
        st.caption("建议：" + suggestion)



def _improvement_history_tab():
    """改进历史标签：只展示已验证的改进闭环。"""
    _render_improvement_history()
