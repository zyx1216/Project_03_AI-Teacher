# -*- coding: utf-8 -*-
"""首页 Dashboard 页面。"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from utils.db import SessionLocal
from utils import agent_alert, agent_advisor, onboarding_service
from utils import calendar_service as cal_svc
from utils import class_service
from utils import dashboard_service as svc
from utils import schedule_service
from utils.navigation import goto_group


def _metric_or_dash(value) -> str:
    return "—" if value is None else str(value)


@st.dialog("👋 欢迎使用")
def _onboarding_dialog() -> None:
    """六步新手引导；跳过后不再弹，稍后暂缓到次日。"""
    steps = onboarding_service.guide_steps()
    completed = onboarding_service.get_status().get("completed_steps", [])
    index = min(len(completed), len(steps) - 1)
    step = steps[index]

    st.markdown(f"### 第 {index + 1} / {len(steps)} 步：{step['title']}")
    st.write(step["description"])
    st.progress((index + 1) / len(steps))

    c1, c2, c3 = st.columns(3)
    next_label = "完成" if index == len(steps) - 1 else "下一步"
    if c1.button(next_label, key="onboarding_next", type="primary",
                 use_container_width=True):
        onboarding_service.complete_step(step["id"])
        st.rerun()
    if c2.button("跳过引导", key="onboarding_skip", use_container_width=True):
        onboarding_service.skip()
        st.rerun()
    if c3.button("稍后再说", key="onboarding_later", use_container_width=True):
        onboarding_service.snooze()
        st.rerun()

def _quick_actions() -> None:
    c1, c2, c3 = st.columns(3)
    if c1.button("📝 新建作业", key="dash_new_homework", use_container_width=True):
        goto_group("📝 学业测评", "作业管理", hw_new_dialog_open=True)
    if c2.button("📥 上传成绩", key="dash_upload_score", use_container_width=True):
        goto_group("📊 学情", "成绩管理", score_import_expander=True)
    if c3.button("📚 AI 备课", key="dash_ai_lesson", use_container_width=True):
        goto_group("📚 备课", "AI 备课")


def _overview_cards(data: dict) -> None:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("本学期备课次数", data["lesson_count"])
    c2.metric("本月布置作业次数", data["monthly_homework_count"])
    c3.metric("最近考试平均分", _metric_or_dash(data["latest_average"]))
    c4.metric("待批改作业数", data["pending_count"])


def _recent_exams(data: dict) -> None:
    st.markdown("#### 最近 3 场考试")
    if not data["recent_exams"]:
        st.info("还没有考试成绩。可通过上方“上传成绩”导入。")
        return
    rows = []
    for item in data["recent_exams"]:
        delta_text = "—" if item["变化"] is None else f"{item['变化']:+.1f}"
        rows.append({
            "日期": item["日期"] or "—", "考试": item["考试"],
            "平均分": _metric_or_dash(item["平均分"]),
            "满分": _metric_or_dash(item.get("满分")),
            "得分率": _metric_or_dash(item.get("得分率")),
            "较上一场": delta_text})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def _recent_homeworks(data: dict) -> None:
    st.markdown("#### 最近布置的 3 次作业")
    if not data["recent_homeworks"]:
        st.info("还没有作业。可通过上方“新建作业”创建。")
        return
    st.dataframe(pd.DataFrame(data["recent_homeworks"]), hide_index=True, width="stretch")


def _todo(data: dict) -> None:
    st.markdown("#### 待办事项")
    if not data["pending_items"]:
        st.info("当前没有待批改作业。")
        return
    rows = []
    for item in data["pending_items"]:
        rows.append({
            "作业": item["作业"],
            "未录成绩人数": "未录（无班级作业）" if item["未录人数"] is None else item["未录人数"]})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def _calendar_preview(session, today) -> None:
    st.subheader("本周日历预览")
    rows = cal_svc.week_preview_rows(session, today)
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    if st.button("📅 打开完整教学日历", key="dash_open_calendar"):
        # v3.4.1：教学日历已收进「教学工具」折叠组。
        st.session_state["_pending_app_route"] = "🎓 教学工具"
        st.session_state["_pending_app_sub"] = "📅 教学日历"
        st.session_state["_pending_app_sub_key"] = "teaching_tab"
        st.rerun()


def _home_schedule(session) -> None:
    st.subheader("本周课程表（每周重复）")
    classes = class_service.list_class_names(session)
    if not classes:
        st.info("还没有班级。先在“学情 → 学生管理 → 班级管理”创建班级。")
        return

    selected = st.selectbox(
        "选择班级", options=classes, key="home_schedule_class")
    grid = schedule_service.week_grid(selected)
    entries = schedule_service.list_entries(selected)
    if not entries:
        st.info("这个班还没有课程安排，可在完整教学日历页维护。")
    st.dataframe(pd.DataFrame(grid), hide_index=True, width="stretch")


def _alert_block(session) -> None:
    """首页置顶：智能提醒（邮箱消息样式，支持单条/批量已读）。"""
    st.subheader("🔔 智能提醒")
    alerts = agent_alert.check_all_alerts(session)
    if not alerts:
        st.info("暂无异常提醒。")
        return

    # 工具栏：全选 + 批量已读
    unread_keys = [a["dedup_key"] for a in alerts
                   if not agent_alert.is_read(a["dedup_key"])]
    tool_c1, tool_c2, tool_c3 = st.columns([1, 2, 4])
    select_all = tool_c1.checkbox(
        "全选", key="alert_select_all",
        value=len(unread_keys) == len(alerts) and bool(alerts))
    if tool_c2.button("✅ 批量已读", key="alert_mark_all_read",
                      use_container_width=True, disabled=not unread_keys):
        target_keys = ([a["dedup_key"] for a in alerts] if select_all
                       else unread_keys)
        agent_alert.mark_all_read(target_keys)
        st.toast(f"已标记 {len(target_keys)} 条为已读。")
        st.rerun()
    tool_c3.caption(f"共 {len(alerts)} 条，未读 {len(unread_keys)} 条")

    # 消息列表
    for idx, alert in enumerate(alerts):
        read = agent_alert.is_read(alert["dedup_key"])
        severe = alert.get("severity") == "severe"
        # 消息卡片
        with st.container(border=True):
            row_c1, row_c2 = st.columns([0.5, 9.5])
            # 未读圆点
            if not read:
                row_c1.markdown(
                    "<span style='color:#ff4b4b;font-size:20px'>●</span>",
                    unsafe_allow_html=True)
            else:
                row_c1.markdown(
                    "<span style='color:#ccc;font-size:20px'>○</span>",
                    unsafe_allow_html=True)
            # 标题和内容
            title_style = "color:#999" if read else ""
            row_c2.markdown(
                f"**<span style='{title_style}'>{alert['title']}</span>**"
                f"　<span style='color:#888;font-size:12px'>"
                f"{'🔴 严重' if severe else '🟡 提醒'}</span>")
            content_style = "color:#aaa" if read else ""
            row_c2.markdown(
                f"<span style='{content_style}'>{alert['content']}</span>",
                unsafe_allow_html=True)
            # 操作按钮
            btn_c1, btn_c2, btn_c3 = row_c2.columns([1, 1, 1])
            if not read:
                if btn_c1.button("📖 标记已读",
                                 key=f"alert_read_{alert['dedup_key']}",
                                 use_container_width=True):
                    agent_alert.mark_read(alert["dedup_key"])
                    st.toast("已标记为已读。")
                    st.rerun()
            else:
                btn_c1.caption("已读")
            if btn_c2.button("→ 去处理",
                             key=f"alert_go_{alert['dedup_key']}",
                             use_container_width=True):
                goto_group(alert["route"], alert["sub"],
                           **(alert.get("extra") or {}))
            if btn_c3.button("✅ 已处理",
                             key=f"alert_done_{alert['dedup_key']}",
                             use_container_width=True):
                agent_alert.resolve_alert(alert["dedup_key"])
                st.toast("该提醒已标记为处理完成。")
                st.rerun()

    # 展示后记时间戳，保证 24 小时内只显示一次。
    agent_alert.mark_displayed(alerts)


def _v330_reminder_center(session) -> None:
    """v3.3.0 教学数据提醒：作业催交、教学进度、学生预警，可筛选和已处理。"""
    from utils import reminder_service as rs

    st.markdown("##### 📌 教学数据提醒")
    with st.expander("⚙️ 提醒设置", expanded=False):
        cols = st.columns(3)
        for rtype, col in zip(rs.REMINDER_TYPES, cols):
            enabled = rs.is_enabled(session, rtype)
            checked = col.checkbox(rs.TYPE_LABELS[rtype], value=enabled,
                                   key=f"v330_setting_{rtype}")
            if checked != enabled:
                rs.save_setting(session, rtype, enabled=checked)

    reminders = rs.list_reminders(session)
    labels = ["全部"] + list(rs.TYPE_LABELS.values())
    choice = st.radio("提醒类型", labels, horizontal=True,
                      key="v330_reminder_filter",
                      label_visibility="collapsed")
    if choice != "全部":
        wanted = next(k for k, v in rs.TYPE_LABELS.items() if v == choice)
        reminders = [r for r in reminders if r["reminder_type"] == wanted]
    if not reminders:
        st.caption("没有需要处理的教学提醒。")
        return

    for reminder in reminders:
        with st.container(border=True):
            tag = rs.TYPE_LABELS.get(reminder["reminder_type"], "")
            st.markdown(
                f"**{reminder['title']}**　"
                f"<span style='color:#888;font-size:12px'>{tag}</span>",
                unsafe_allow_html=True)
            st.caption(reminder["content"])
            b1, b2 = st.columns(2)
            if reminder["reminder_type"] == "homework":
                if b1.button("📋 生成催交文案",
                             key=f"v330_text_{reminder['signature']}",
                             use_container_width=True):
                    st.code(rs.reminder_text(reminder))
            if b2.button("✅ 标记已处理",
                         key=f"v330_done_{reminder['signature']}",
                         use_container_width=True):
                rs.mark_handled(session, reminder["signature"])
                st.toast("已标记为处理完成。")
                st.rerun()


def _advisor_block(session) -> None:
    """首页置顶：本周 AI 教学建议。每周自动生成一次并缓存。"""
    st.subheader("💡 AI教学建议")
    entry = agent_advisor.get_cached_weekly()
    if entry is None:
        with st.spinner("正在生成本周教学建议…"):
            entry = agent_advisor.generate_weekly_suggestions(session)
    if entry.get("insufficient"):
        st.info(entry.get("text") or agent_advisor.INSUFFICIENT_TEXT)
        b1, b2 = st.columns(2)
        if b1.button("🔄 重新生成", key="advisor_regen",
                     use_container_width=True):
            agent_advisor.generate_weekly_suggestions(session, force=True)
            st.rerun()
        return
    st.markdown(entry.get("text", ""))
    b1, b2, b3 = st.columns(3)
    if b1.button("🔄 重新生成", key="advisor_regen",
                 use_container_width=True):
        agent_advisor.generate_weekly_suggestions(session, force=True)
        st.toast("已重新生成本周教学建议。")
        st.rerun()
    if b2.button("📂 展开详情", key="advisor_expand",
                 use_container_width=True):
        st.session_state["advisor_detail_open"] = True
        st.rerun()
    if b3.button("💾 保存到教学反思", key="advisor_save_reflection",
                 use_container_width=True):
        info = agent_advisor.save_weekly_to_reflection(session, entry)
        st.toast(f"已保存教学反思：{info['title']}")
        st.rerun()
    if st.session_state.get("advisor_detail_open"):
        with st.expander("本周建议详情", expanded=True):
            focus = entry.get("focus_points") or []
            if focus:
                st.markdown("**教学重点：**" + "、".join(focus))
            for m in entry.get("measures") or []:
                st.markdown(
                    f"- 【{m.get('method')}】{m.get('measure')}"
                    f"（预期：{m.get('expected_effect') or '—'}）")
            if st.button("收起详情", key="advisor_detail_close"):
                st.session_state.pop("advisor_detail_open", None)
                st.rerun()

def show() -> None:
    """渲染首页：今日概览、总数卡片、本周进度、快速入口。"""
    st.title("🏠 首页")
    with SessionLocal() as session:
        data = svc.dashboard_data(session)
        today = data["date"]
        st.caption(
            f"今天是 {today.strftime('%Y年%m月%d日')} {data['today']['weekday']}，"
            f"本学期第 {data['today']['semester_week']} 周")

        # 新手引导在所有业务区块之前弹出；跳过后不再自动出现。
        if onboarding_service.should_show(today=today):
            _onboarding_dialog()

        # 置顶区块：智能提醒 → AI 教学建议 → 教学进度，位于今日概览之前。
        _alert_block(session)
        _v330_reminder_center(session)
        _advisor_block(session)
        _teaching_progress_block(session, today=today)

        st.subheader("今日概览")
        c1, c2 = st.columns(2)
        with c1:
            _calendar_preview(session, today)
        with c2:
            _todo(data)

        st.subheader("教学数据")
        cols = st.columns(4)
        cols[0].metric("学生总数", data["student_count"])
        cols[1].metric("题目总数", data["question_count"])
        cols[2].metric("教案总数", data["plan_count"])
        cols[3].metric("作业总数", data["homework_count"])

        st.subheader("本周教学进度")
        progress = data["weekly_progress"]
        ratio = progress["done"] / progress["total"] if progress["total"] else 0
        st.progress(ratio)
        st.caption(f"本周已完成 {progress['done']} / {progress['total']} 课时")

        st.subheader("快速入口")
        _quick_actions()

        with st.expander("查看最近考试、作业和课表"):
            left, right = st.columns(2)
            with left:
                _recent_exams(data)
            with right:
                _recent_homeworks(data)
            _home_schedule(session)






def _teaching_progress_block(session, today=None) -> None:
    """首页教学进度卡片：位于智能提醒、AI建议之后。"""
    from models.models import TeachingProgress
    st.subheader("📈 教学进度")
    current_week = cal_svc.semester_progress(
        today or pd.Timestamp.today().date(), cal_svc.load_semester())[0]
    rows = (session.query(TeachingProgress)
            .filter(TeachingProgress.week_number == current_week)
            .order_by(TeachingProgress.updated_at.desc()).all())
    if not rows:
        rows = (session.query(TeachingProgress)
                .order_by(TeachingProgress.updated_at.desc()).limit(5).all())
    if not rows:
        st.info("暂无教学进度记录，可在教学日历生成学期计划并录入实际进度。")
        return

    lag = sum(1 for x in rows if x.status == "lag")
    ahead = sum(1 for x in rows if x.status == "ahead")
    normal = len(rows) - lag - ahead
    c1, c2, c3 = st.columns(3)
    c1.metric("当前周", current_week)
    c2.metric("落后", lag)
    c3.metric("超前", ahead)
    st.caption(f"正常 {normal} 项；落后 {lag} 项；超前 {ahead} 项。")
    st.dataframe(pd.DataFrame([
        {"学科": r.subject, "年级": r.grade, "周次": r.week_number,
         "计划": r.planned_content or "", "实际": r.actual_content or "",
         "状态": r.status} for r in rows]),
        hide_index=True, width="stretch")


