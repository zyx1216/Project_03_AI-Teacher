# -*- coding: utf-8 -*-
"""
学业测评页面（v0.4）。

页内 4 个标签页：
1. 作业管理：新建日常作业（弹窗）、题库勾选/AI 即时出题/外部导入/手动加题、
   调序与分值、学生卷/教师卷预览导出、存模板、删除；
2. 智能组卷：独立生成试卷，草稿预览确认后创建正式试卷；
3. 成绩录入：Excel 导入总分、手动录分、逐题批改（错题本数据来源）；
4. 作业分析：概览指标、分数段、排名、进退步、每题正确率、高频错题、AI 总结；
5. 错题本：自动收集的错题筛选、详情、典型错题、导出 Word。

本文件只管界面；逻辑在 utils/homework_service.py、homework_score_service.py、
homework_stats.py，统计口径复用 utils/stats.py。
"""

import json
import re
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import config
from models.models import Homework, Question, Textbook
from utils.db import SessionLocal
from utils import llm_client, feature_subjects as fs
from utils.app_config import (
    SUBJECT_NAMES, DEFAULT_SUBJECT, DISPLAY_GRADE_CHOICES,
    to_storage_grade, to_display_grade,
)
from utils import stats as stats_mod
from utils import excel_handler as eh
from utils import student_service as student_svc
from utils import question_service as qs
from utils import question_importer as qi
from utils import homework_service as hw_svc
from utils import homework_score_service as hscore
from utils import smart_compose_service as scs
from utils import homework_stats as hstat

PROMPTS_DIR = Path(config.BASE_DIR) / "prompts"

TYPE_LABELS = {"choice": "选择题", "fill": "填空题", "judge": "判断题", "solution": "解答题"}
DIFF_LABELS = {1: "基础", 2: "中等", 3: "拓展"}
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

# 弹窗里 4 种日常作业类型；试卷只能从“智能组卷”独立入口创建。
_TYPE_KEYS = ["preview", "classroom", "after_class", "review"]
_TYPE_OPTION_LABELS = {
    k: f"{hw_svc.type_emoji(k)} {hw_svc.type_label(k)}" for k in _TYPE_KEYS}

SMART_COMPOSE_DRAFT_PREFIX = "__smart_compose_draft__"


def _remember_subject(key: str) -> None:
    """功能级学科选择器变化时立即持久化。"""
    fs.set_feature_subject(key, st.session_state[key])


def _subject_selectbox(key: str, caption: str | None = None) -> str:
    """固定 key 的学科选择器，各作业功能互不影响。"""
    current = fs.get_feature_subject(key)
    value = st.selectbox(
        "学科", SUBJECT_NAMES,
        index=SUBJECT_NAMES.index(current) if current in SUBJECT_NAMES else 1,
        key=key, on_change=_remember_subject, args=(key,))
    if caption:
        st.caption(caption)
    return value


def _render_math(text: str):
    """安全渲染文本：转义所有可能导致React错误的字符。
    处理：$...$公式、HTML特殊字符、反引号、连续换行等。
    """
    if not text:
        st.markdown("—")
        return
    import re as _re
    # 1. 把$...$公式换成纯文本（去掉$符号，避免LaTeX渲染错误）
    text = _re.sub(r"\$([^$]+)\$", r"\1", text)
    # 2. 转义HTML特殊字符
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # 3. 把反引号转义（避免破坏代码格式）
    text = text.replace("`", "\`")
    # 4. 把连续多个换行符换成markdown换行
    text = _re.sub(r"\n{2,}", "  \n", text)
    st.markdown(text)


def _read_prompt(filename: str) -> str:
    return (PROMPTS_DIR / filename).read_text(encoding="utf-8")

# ---------------------------------------------------------------------------
# 新建日常作业弹窗
# ---------------------------------------------------------------------------

def _choose_new_homework_type(hw_type: str):
    """类型按钮回调（普通函数，不要加 @st.dialog，否则点类型会弹一个空窗）。"""
    st.session_state["hw_new_type"] = hw_type
    # 换一次控件 key：新类型首次渲染用自己的默认值，也避开状态冲突警告。
    st.session_state["hw_new_dialog_nonce"] = st.session_state.get(
        "hw_new_dialog_nonce", 0) + 1


@st.dialog("新建作业", width="large")
def _new_homework_dialog():
    """真正的弹窗内容：选日常作业类型（emoji 网格）→ 填参数 → 可选模板 → 创建。"""
    st.markdown("**选择作业类型**")
    cols = st.columns(4)
    hw_type = st.session_state.get("hw_new_type", "after_class")
    for i, key in enumerate(_TYPE_KEYS):
        active = key == hw_type
        # 不能在按钮返回 True 后手动 st.rerun()：那会造成整页卸载、弹窗重挂。
        # on_click 会在本次弹窗局部重跑前执行，刚好让新类型参与本轮渲染。
        cols[i].button(
            _TYPE_OPTION_LABELS[key], key=f"type_btn_{key}",
            use_container_width=True, type=("primary" if active else "secondary"),
            on_click=_choose_new_homework_type, args=(key,))

    dialog_subject = _subject_selectbox(
        fs.HOMEWORK_NEW_SUBJECT, caption="新作业学科，不影响下方作业列表的筛选。")
    dialog_grade = st.selectbox(
        "年级", DISPLAY_GRADE_CHOICES, index=0, key="hw_new_grade")
    defaults = hw_svc.DEFAULT_PARAMS[hw_type]
    nonce = st.session_state.get("hw_new_dialog_nonce", 0)
    with st.form("new_homework_form"):
        name = st.text_input("作业名称 *",
                             placeholder=f"如：{hw_svc.type_label(hw_type)}·一元二次方程")
        c1, c2, c3 = st.columns(3)
        class_name = c1.text_input("适用班级")
        # key 带类型：切换作业类型时，总分和用时立刻换成该类型的默认值。
        total_score = c2.number_input(
            "总分", min_value=1.0, value=float(defaults["total_score"]), step=5.0,
            key=f"new_hw_total_{hw_type}_{nonce}")
        duration = c3.number_input(
            "建议用时（分钟）", min_value=1, value=int(defaults["duration"]), step=5,
            key=f"new_hw_duration_{hw_type}_{nonce}")
        remark = st.text_input("说明（可选）")

        with SessionLocal() as session:
            templates = hw_svc.list_homeworks(
                session, templates=True, subject=dialog_subject)
            templates = [
                item for item in templates
                if not item.name.startswith(SMART_COMPOSE_DRAFT_PREFIX)
            ]
        template_id = None
        if templates:
            tpl_labels = ["不使用模板（空白作业）"] + [
                f"{t.name}（{len(t.questions)} 题）" for t in templates]
            tpl_idx = st.selectbox("从模板复制题目", range(len(tpl_labels)),
                                   format_func=lambda i: tpl_labels[i])
            if tpl_idx > 0:
                template_id = templates[tpl_idx - 1].id

        cc1, cc2 = st.columns(2)
        submitted = cc1.form_submit_button("创建", type="primary", use_container_width=True)
        cancelled = cc2.form_submit_button("取消", use_container_width=True)

    if submitted:
        if not name.strip():
            st.error("请填写作业名称。")
        else:
            basket_note = ""
            with SessionLocal() as session:
                hw = hw_svc.create_homework(
                    session, name, homework_type=hw_type,
                    class_name=class_name.strip() or None,
                    total_score=total_score, duration=duration,
                    remark=remark.strip() or None, template_id=template_id,
                    subject=dialog_subject,
                    grade=to_storage_grade(dialog_grade))
                # 题篮：只把与新作业同学科的题带入末尾。
                basket = list(st.session_state.get("next_hw_question_basket", []))
                if basket:
                    same_subject_ids = []
                    other_subjects = set()
                    for qid in dict.fromkeys(basket):
                        q = session.get(Question, int(qid))
                        if q is None:
                            continue
                        if (q.subject or DEFAULT_SUBJECT) == dialog_subject:
                            same_subject_ids.append(q.id)
                        else:
                            other_subjects.add(q.subject or DEFAULT_SUBJECT)
                    if same_subject_ids:
                        hw_svc.add_questions(session, hw.id, same_subject_ids)
                    if other_subjects:
                        basket_note = (
                            f"题篮含 {'、'.join(sorted(other_subjects))} 学科的题，"
                            f"请把新作业学科切到该学科后再建，本次未带入、题篮保留。")
                    else:
                        st.session_state["next_hw_question_basket"] = []
                # 无论有没有题篮都要提交，否则作业会随会话关闭回滚。
                session.commit()
                new_id = hw.id
            if basket_note:
                st.session_state["hw_new_basket_note"] = basket_note
            st.session_state["hw_open_id"] = new_id
            close_new_homework_dialog_state()
            st.rerun()
    if cancelled:
        close_new_homework_dialog_state()
        st.rerun()

def close_new_homework_dialog_state() -> None:
    """关闭新建弹窗并清掉类型、总分、用时状态，下次打开重新取默认值。

    主导航切离作业页时也调用：弹窗开关只是临时 UI 状态，不能跨页面残留。
    """
    st.session_state.pop("hw_new_dialog_open", None)
    st.session_state.pop("hw_new_type", None)
    st.session_state.pop("hw_new_grade", None)
    st.session_state.pop("hw_new_dialog_nonce", None)
    for key in list(st.session_state.keys()):
        if key.startswith("new_hw_total_") or key.startswith("new_hw_duration_"):
            st.session_state.pop(key, None)

# ---------------------------------------------------------------------------
# Tab 1：作业管理
# ---------------------------------------------------------------------------

def tab_manage():
    st.subheader("作业管理")
    c1, c2 = st.columns([3, 1])
    with c1:
        if st.button("➕ 新建作业", type="primary"):
            st.session_state["hw_new_dialog_open"] = True
    with c2:
        _subject_selectbox(fs.HOMEWORK_LIST_SUBJECT, caption="仅筛选作业和模板列表。")
    # 不能只在按钮点击当帧调用弹窗：弹窗内切换类型会 rerun，导致弹窗消失。
    if st.session_state.get("hw_new_dialog_open"):
        _new_homework_dialog()

    open_id = st.session_state.get("hw_open_id")
    if open_id is not None:
        _homework_editor(open_id)
        st.divider()
    _homework_list()

def _homework_list():
    """日常作业列表：按进行中/已完成分组，支持筛选、批量操作。"""
    current_subject = fs.get_feature_subject(fs.HOMEWORK_LIST_SUBJECT)
    last_batch = st.session_state.pop("hw_batch_last", None)
    if last_batch:
        st.success(last_batch)
    basket_note = st.session_state.pop("hw_new_basket_note", None)
    if basket_note:
        st.warning(basket_note)

    with SessionLocal() as session:
        classes = hw_svc.list_homework_classes(session, subject=current_subject)

    with st.container(border=True):
        fc1, fc2, fc3, fc4, fc5 = st.columns(5)
        keyword = fc1.text_input("作业名称搜索", key="homework_filter_keyword")
        type_options = [None] + _TYPE_KEYS
        homework_type = fc2.selectbox(
            "作业类型", type_options,
            format_func=lambda x: "全部类型" if x is None else hw_svc.type_label(x),
            key="homework_filter_type")
        grade_filter = fc3.selectbox(
            "年级", ["全部年级"] + DISPLAY_GRADE_CHOICES,
            key="homework_filter_grade")
        class_filter = fc4.selectbox(
            "班级", ["全部班级"] + classes, key="homework_filter_class")
        sort_label = fc5.selectbox(
            "排序", ["最新创建", "最旧创建", "最近打开"],
            key="homework_filter_sort")

    sort_map = {
        "最新创建": "created_desc",
        "最旧创建": "created_asc",
        "最近打开": "opened_desc",
    }
    storage_grade = None if grade_filter == "全部年级" else to_storage_grade(grade_filter)
    with SessionLocal() as session:
        homeworks = hw_svc.list_homeworks(
            session, templates=False, subject=current_subject,
            keyword=keyword.strip() or None, homework_type=homework_type,
            grade=storage_grade, exclude_types=["exam"],
            class_name=None if class_filter == "全部班级" else class_filter,
            sort_order=sort_map[sort_label])
        templates = hw_svc.list_homeworks(
            session, templates=True, subject=current_subject)
        templates = [t for t in templates
                     if not t.name.startswith(SMART_COMPOSE_DRAFT_PREFIX)]
        items = [{
            "id": h.id, "name": h.name, "class_name": h.class_name,
            "type": h.homework_type, "n": len(h.questions),
            "total": h.total_score or 0, "duration": h.duration or 0,
            "grade": h.grade, "status": h.status or "pending",
            "completed_at": (h.completed_at.strftime("%Y-%m-%d %H:%M")
                             if h.completed_at else ""),
        } for h in homeworks]
        tpl_items = [{
            "name": t.name, "type": t.homework_type, "n": len(t.questions),
            "grade": t.grade,
        } for t in templates]

    basket = st.session_state.get("next_hw_question_basket", [])
    if basket:
        bc1, bc2 = st.columns([4, 1])
        bc1.caption(f"🧺 题篮：{len(basket)} 道题待带入新作业（仅带入同学科作业）。")
        if bc2.button("清空题篮", key="clear_basket_manage"):
            st.session_state["next_hw_question_basket"] = []
            st.rerun()

    pending_items = [h for h in items if h["status"] != "completed"]
    completed_items = [h for h in items if h["status"] == "completed"]

    st.markdown(f"**📋 进行中（{len(pending_items)} 份）**")
    if not pending_items and not completed_items:
        st.info("还没有符合条件的作业，点上方“新建作业”开始。")
    for hw in pending_items:
        _render_homework_row(hw, completed=False)

    if completed_items:
        with st.expander(f"📚 已完成（{len(completed_items)} 份）"):
            for hw in completed_items:
                _render_homework_row(hw, completed=True)

    picked_ids = [hw["id"] for hw in items
                  if st.session_state.get(f"pick_hw_{hw['id']}")]
    if picked_ids:
        bc1, bc2 = st.columns(2)
        if bc1.button(f"🗑️ 批量删除所选（{len(picked_ids)}）",
                      key="hw_batch_del_btn"):
            st.session_state["hw_batch_delete_pending"] = picked_ids
            st.rerun()
        if bc2.button(f"📦 批量导出所选 Word（{len(picked_ids)}）",
                      key="hw_batch_export_btn"):
            with SessionLocal() as session:
                zip_bytes = hw_svc.export_homeworks_zip(session, picked_ids)
            st.download_button(
                "⬇️ 下载批量 Word 压缩包", zip_bytes,
                file_name="作业批量导出.zip",
                mime="application/zip", key="hw_batch_export_dl")

    if st.session_state.get("hw_batch_delete_pending"):
        pending_ids = list(st.session_state["hw_batch_delete_pending"])
        st.error(f"将删除勾选的 {len(pending_ids)} 份作业，其题目关联、成绩与作答一并删除。确定继续吗？")
        bc1, bc2 = st.columns(2)
        if bc1.button("✅ 确认批量删除", type="primary", key="hw_batch_del_ok"):
            with SessionLocal() as session:
                deleted_n = hw_svc.delete_homeworks(session, pending_ids)
                session.commit()
            for pid in pending_ids:
                st.session_state.pop(f"pick_hw_{pid}", None)
                if st.session_state.get("hw_open_id") == pid:
                    st.session_state.pop("hw_open_id", None)
            st.session_state.pop("hw_batch_delete_pending", None)
            st.session_state["hw_batch_last"] = f"已批量删除 {deleted_n} 份作业。"
            st.rerun()
        if bc2.button("取消", key="hw_batch_del_cancel"):
            st.session_state.pop("hw_batch_delete_pending", None)
            st.rerun()

    if tpl_items:
        st.markdown("**作业模板**")
        for tpl in tpl_items:
            st.caption(
                f"📦 {tpl['name']}（{hw_svc.type_label(tpl['type'])}，"
                f"{to_display_grade(tpl['grade']) or '未指定'}，{tpl['n']} 题）")


def _render_homework_row(hw: dict, completed: bool):
    """渲染一行作业及操作按钮。"""
    hid = hw["id"]
    with st.container(border=True):
        c0, c1, c2, c3, c4 = st.columns([0.5, 4.6, 1, 1, 1])
        c0.checkbox("选择", key=f"pick_hw_{hid}", label_visibility="collapsed")
        extra = f"完成时间：{hw['completed_at']}　" if completed else ""
        c1.markdown(
            f"{hw_svc.type_emoji(hw['type'])} **{hw['name']}**　"
            f"（{to_display_grade(hw['grade']) or '未指定'}）　"
            f"{hw['class_name'] or ''}　{hw['n']} 题　"
            f"满分 {hw['total']}　{hw['duration']} 分钟　{extra}")
        if c2.button("打开编辑", key=f"open_{hid}"):
            with SessionLocal() as session:
                hw_svc.touch_homework(session, hid)
                session.commit()
            st.session_state["hw_open_id"] = hid
            st.rerun()
        if completed:
            if c3.button("再次布置", key=f"copy_{hid}"):
                with SessionLocal() as session:
                    clone = hw_svc.duplicate_homework(session, hid)
                    session.commit()
                    new_id = clone.id
                st.session_state["hw_open_id"] = new_id
                st.rerun()
            if c4.button("重新打开", key=f"reopen_{hid}"):
                with SessionLocal() as session:
                    hw_svc.reopen_homework(session, hid)
                    session.commit()
                st.rerun()
        else:
            if c3.button("✅ 完成", key=f"finish_{hid}"):
                with SessionLocal() as session:
                    hw_svc.mark_homework_completed(session, hid)
                    session.commit()
                st.rerun()
            if c4.button("删除", key=f"del_hw_{hid}"):
                st.session_state["confirm_del_hw"] = hid

        if st.session_state.get("confirm_del_hw") == hid:
            cc1, cc2 = st.columns(2)
            if cc1.button("确认删除（含成绩与作答）", key=f"ok_del_hw_{hid}",
                          type="primary"):
                with SessionLocal() as session:
                    hw_svc.delete_homework(session, hid)
                    session.commit()
                st.session_state.pop("confirm_del_hw", None)
                st.session_state.pop(f"pick_hw_{hid}", None)
                if st.session_state.get("hw_open_id") == hid:
                    st.session_state.pop("hw_open_id", None)
                st.rerun()
            if cc2.button("取消", key=f"cancel_del_hw_{hid}"):
                st.session_state.pop("confirm_del_hw", None)
                st.rerun()


def _homework_editor(homework_id: int):
    """作业编辑抽屉：4 个加题入口、调序、分值、预览导出和存模板。"""
    with SessionLocal() as session:
        hw = hw_svc.get_homework(session, homework_id)
        if hw is None:
            st.session_state.pop("hw_open_id", None)
            st.rerun()
            return

        st.markdown(f"### {hw_svc.type_emoji(hw.homework_type)} {hw.name}")
        tabs = st.tabs(["从题库选题", "AI 即时出题", "外部导入", "手动添加"])
        with tabs[0]:
            _add_from_bank(session, hw)
        with tabs[1]:
            _add_from_ai(session, hw)
        with tabs[2]:
            _add_from_import(session, hw)
        with tabs[3]:
            _add_manual(session, hw)

        _question_list_editor(session, hw)

def _add_from_bank(session, hw):
    """从已审核题库按条件筛选，勾选加入当前作业。"""
    with st.container(border=True):
        c1, c2, c3, c4 = st.columns(4)
        ftype = c1.selectbox("题型", [None] + list(TYPE_LABELS),
                             format_func=lambda x: "全部" if x is None else TYPE_LABELS[x],
                             key=f"bank_type_{hw.id}")
        fdiff = c2.selectbox("难度", [None, 1, 2, 3],
                             format_func=lambda x: "全部" if x is None else DIFF_LABELS[x],
                             key=f"bank_diff_{hw.id}")
        keyword = c3.text_input("知识点/题干关键词", key=f"bank_kw_{hw.id}")
        fgrade = c4.selectbox(
            "年级", [None] + DISPLAY_GRADE_CHOICES,
            format_func=lambda x: "全部年级" if x is None else x,
            key=f"bank_grade_{hw.id}")
        questions = qs.list_questions(session, question_type=ftype,
                                      difficulty=fdiff, status="approved",
                                      keyword=keyword.strip() or None,
                                      subject=hw.subject or DEFAULT_SUBJECT,
                                      grade=fgrade)
        existing = hw_svc.question_ids_in_homework(session, hw.id)
        choices = [q for q in questions if q.id not in existing]
        st.caption(f"题库中可选 {len(choices)} 道（已在作业里的自动隐藏）")
        if not choices:
            st.info("没有符合条件且未加入的已审核题。")
            return
        labels = [f"#{q.id} {TYPE_LABELS[q.question_type]}·{DIFF_LABELS[q.difficulty]}"
                  f"　{q.content[:30]}" for q in choices]
        picked = st.multiselect("勾选要加入的题", range(len(choices)),
                                format_func=lambda i: labels[i],
                                key=f"bank_pick_{hw.id}")
        if st.button("➕ 加入作业", key=f"bank_add_{hw.id}"):
            ids = [choices[i].id for i in picked]
            added = hw_svc.add_questions(session, hw.id, ids)
            session.commit()
            st.success(f"已加入 {added} 道题。")
            st.rerun()


def _add_from_ai(session, hw):
    """AI 即时出题：生成→校验→入库→加入作业（走待审核）。"""
    with st.container(border=True):
        knowledge = st.text_input("知识点", key=f"ai_kp_{hw.id}",
                                  placeholder="如：根的判别式")
        c1, c2, c3 = st.columns(3)
        types = c1.multiselect("题型", list(TYPE_LABELS),
                               format_func=lambda x: TYPE_LABELS[x],
                               key=f"ai_types_{hw.id}")
        difficulty = c2.select_slider("难度", options=[1, 2, 3],
                                      format_func=lambda x: DIFF_LABELS[x],
                                      value=2, key=f"ai_diff_{hw.id}")
        count = c3.number_input("数量", min_value=1, max_value=10, value=5,
                                key=f"ai_count_{hw.id}")
        if st.button("🤖 生成并加入", key=f"ai_gen_{hw.id}", type="primary"):
            if not knowledge.strip():
                st.warning("请先填知识点。")
            elif not llm_client.is_content_configured():
                st.warning("还没配置内容生成模型，请到「⚙️ 设置」配置。")
            else:
                _generate_and_add(session, hw, knowledge.strip(), types,
                                  difficulty, count)


def _generate_and_add(session, hw, knowledge, types, difficulty, count):
    """调内容模型出题，校验后入库并加入作业。"""
    type_text = "、".join(TYPE_LABELS[t] for t in types) if types else "各种题型"
    system_prompt = _read_prompt("question_prompt.txt")
    subject = hw.subject or DEFAULT_SUBJECT
    grade_text = to_display_grade(hw.grade) or "未指定"
    user_text = (f"学科：{subject}\n年级：{grade_text}\n知识点：{knowledge}\n"
                 f"题型：{type_text}\n难度：{DIFF_LABELS[difficulty]}\n"
                 f"题目数量：恰好 {count} 道")
    with st.spinner("AI 正在命题……"):
        try:
            raw = llm_client.chat_content(system_prompt, user_text, temperature=0.8)
        except (llm_client.LLMConfigError, llm_client.LLMCallError) as exc:
            st.error(f"生成失败：{exc}")
            return
    valid, rejected = qs.build_questions(raw)
    if not valid:
        st.error("没解析出有效题目，请重试。")
        return
    new_ids = []
    for data in valid:
        q = qs.create_question(session, data, source="ai_generated",
                                       status="pending", subject=hw.subject or DEFAULT_SUBJECT)
        new_ids.append(q.id)
    session.flush()
    added = hw_svc.add_questions(session, hw.id, new_ids)
    session.commit()
    msg = f"已生成并加入 {added} 道题（待审核状态）。"
    if rejected:
        msg += f" {rejected} 道因缺答案被拒收。"
    st.success(msg)
    st.rerun()


def _add_from_import(session, hw):
    """把外部导入的题加入当前作业（导入题同样走校验，缺答案跳过）。"""
    with st.container(border=True):
        mode = st.radio("来源", ["Excel", "Word", "粘贴文本"], horizontal=True,
                        key=f"imp_mode_{hw.id}", label_visibility="collapsed")
        records = None
        if mode in ("Excel", "Word"):
            suffix = "xlsx" if mode == "Excel" else "docx"
            up = st.file_uploader(f"选择 {suffix.upper()} 文件", type=[suffix],
                                  key=f"imp_file_{hw.id}")
            if up is not None and st.button("解析预览", key=f"imp_parse_file_{hw.id}"):
                try:
                    if mode == "Excel":
                        df = pd.read_excel(up)
                        detected = qi.detect_question_columns(df)
                        for problem in detected["problems"]:
                            st.error(problem)
                        if detected["mapping"]["content"] and detected["mapping"]["answer"]:
                            st.session_state[f"imp_records_{hw.id}"] = \
                                qi.records_from_excel(df, detected["mapping"])
                            st.rerun()
                    else:
                        st.session_state[f"imp_records_{hw.id}"] = \
                            qi.records_from_docx(up.getvalue())
                        st.rerun()
                except Exception as exc:
                    st.error(f"解析失败：{exc}")
        else:
            pasted = st.text_area("粘贴题目（用“答案：”标答案）", height=140,
                                  key=f"imp_text_{hw.id}")
            if st.button("解析预览", key=f"imp_parse_text_{hw.id}"):
                st.session_state[f"imp_records_{hw.id}"] = qi.records_from_text(pasted)
                st.rerun()

        records = st.session_state.get(f"imp_records_{hw.id}")
        if records:
            bad = sum(1 for r in records if r.get("problems"))
            if bad:
                st.warning(f"{bad} 道缺题干/答案，导入时自动跳过。")
            st.dataframe(pd.DataFrame([{
                "题干": r["content"][:30], "答案": r["answer"][:20],
                "问题": "、".join(r.get("problems", []))} for r in records]),
                width="stretch", hide_index=True)
            if st.button("✅ 确认导入并加入作业", key=f"imp_ok_{hw.id}", type="primary"):
                result = qi.import_records(session, records, subject=hw.subject or DEFAULT_SUBJECT)
                session.flush()
                # import_records 新建的题按内容找回来加入作业
                new_questions = (session.query(Question)
                                 .filter(Question.source == "imported",
                                         Question.status == "pending",
                                         Question.subject == (hw.subject or DEFAULT_SUBJECT))
                                 .order_by(Question.id.desc())
                                 .limit(result["imported"]).all())
                added = hw_svc.add_questions(session, hw.id, [q.id for q in new_questions])
                session.commit()
                st.success(f"导入 {result['imported']} 道，{added} 道已加入作业，"
                           f"跳过 {result['rejected']} 道。")
                st.session_state.pop(f"imp_records_{hw.id}", None)
                st.rerun()


def _add_manual(session, hw):
    """手动添加一道题（题干+答案必填），入库即已审核并加入作业。"""
    with st.container(border=True):
        with st.form(f"manual_q_{hw.id}"):
            content = st.text_area("题干（公式用 $...$）", height=100)
            c1, c2 = st.columns(2)
            qtype = c1.selectbox("题型", list(TYPE_LABELS),
                                 format_func=lambda x: TYPE_LABELS[x])
            diff = c2.select_slider("难度", options=[1, 2, 3],
                                    format_func=lambda x: DIFF_LABELS[x], value=2)
            kps = st.text_input("知识点（逗号分隔）")
            answer = st.text_area("答案（必填）", height=70)
            analysis = st.text_area("解析（可选）", height=70)
            submitted = st.form_submit_button("➕ 添加并加入", type="primary")
        if submitted:
            normalized = qs.validate_question({
                "content": content, "question_type": qtype, "difficulty": diff,
                "knowledge_points": kps, "answer": answer, "analysis": analysis})
            if normalized is None:
                st.error("题干和答案都不能为空。")
            else:
                q = qs.create_question(session, normalized, source="manual",
                                       status="approved",
                                       subject=hw.subject or DEFAULT_SUBJECT)
                session.flush()
                hw_svc.add_questions(session, hw.id, [q.id])
                session.commit()
                st.success("已添加并加入作业。")
                st.rerun()

def _question_list_editor(session, hw):
    """作业内题目清单：调序、改分值、移除、总分、预览、导出、存模板。"""
    st.markdown("**作业题目**")
    pairs = hw_svc.homework_questions(session, hw.id)
    if not pairs:
        st.info("还没有题目，用上面四个入口加题。")
        return

    summed = hw_svc.summed_score(session, hw.id)
    st.caption(f"已设置分值合计：{summed} 分；作业登记满分：{hw.total_score or 0} 分。")

    for idx, (link, q) in enumerate(pairs):
        with st.container(border=True):
            c1, c2, c3, c4, c5 = st.columns([5, 1.3, 1, 1, 1])
            c1.markdown(f"{idx + 1}. {TYPE_LABELS[q.question_type]}·"
                        f"{DIFF_LABELS[q.difficulty]}　{q.content[:40]}")
            score = c2.number_input("分值", min_value=0.0, value=float(link.score or 0),
                                    step=1.0, key=f"score_{hw.id}_{q.id}",
                                    label_visibility="collapsed")
            if c3.button("⬆️", key=f"up_{hw.id}_{q.id}", disabled=(idx == 0)):
                hw_svc.move_question(session, hw.id, q.id, -1)
                session.commit()
                st.rerun()
            if c4.button("⬇️", key=f"down_{hw.id}_{q.id}",
                         disabled=(idx == len(pairs) - 1)):
                hw_svc.move_question(session, hw.id, q.id, 1)
                session.commit()
                st.rerun()
            if c5.button("移除", key=f"rm_{hw.id}_{q.id}"):
                hw_svc.remove_question(session, hw.id, q.id)
                session.commit()
                st.rerun()
            if float(link.score or 0) != score:
                # 分值被改动时即时保存（下一次 rerun 生效）
                hw_svc.set_question_score(session, hw.id, q.id, score or None)
                session.commit()

    with st.expander("👁️ 预览学生卷 / 教师卷"):
        pc1, pc2 = st.columns(2)
        if pc1.button("导出学生卷 Word", key=f"dl_stu_{hw.id}"):
            data = hw_svc.export_word(session, hw.id, with_answer=False)
            st.download_button("⬇️ 下载学生卷", data, file_name=f"{hw.name}-学生卷.docx",
                               mime=DOCX_MIME, key=f"dl_stu_b_{hw.id}")
        if pc2.button("导出教师卷 Word", key=f"dl_tea_{hw.id}"):
            data = hw_svc.export_word(session, hw.id, with_answer=True)
            st.download_button("⬇️ 下载教师卷", data, file_name=f"{hw.name}-教师卷.docx",
                               mime=DOCX_MIME, key=f"dl_tea_b_{hw.id}")

    cc1, cc2 = st.columns(2)
    if cc1.button("📦 存为模板", key=f"tpl_{hw.id}"):
        hw_svc.save_as_template(session, hw.id)
        session.commit()
        st.success("已存为模板，下次新建作业时可复制。")
        st.rerun()


def _smart_material_chapters(book: Textbook) -> list[str]:
    """读取资料确认过的章节；缺失时从已保存全文按规则回退切分。"""
    try:
        info = json.loads(book.chapter_info or "[]")
        titles = [str(item.get("title") or "").strip()
                  for item in info if isinstance(item, dict)]
        titles = list(dict.fromkeys(titles))
        if titles:
            return titles
    except (json.JSONDecodeError, TypeError, AttributeError):
        pass

    text_path = Path(config.UPLOAD_DIR) / "text" / f"{book.id}.txt"
    if text_path.exists():
        chapters = qs_split_chapters(text_path.read_text(encoding="utf-8"))
        return [item["title"] for item in chapters]
    return []


def qs_split_chapters(text: str):
    """避免页面直接引入 material_service，复用题目资料文本的章节规则。"""
    from utils import material_service
    return material_service.split_chapters(text)


def _smart_storage_type(type_name: str) -> str | None:
    """把扩展题型中文标签归一到现有四类题型；非法题型返回 None。"""
    key = str(type_name or "").strip().lower().replace(" ", "")
    return qs.EXTENDED_TYPE_ALIASES.get(key)


# ---------------------------------------------------------------------------
# 独立智能组卷：草稿试卷 → 预览 → 正式试卷
# ---------------------------------------------------------------------------

_SMART_CONFIG_KEYS = [
    "smart_compose_grade",
    "smart_compose_material",
    "smart_compose_chapters",
    "smart_compose_kps",
    "smart_compose_manual_kps",
    "smart_compose_type_matrix",
    "smart_compose_total",
    "smart_compose_duration",
    "smart_template_name",
    "smart_compose_paper_name",
]


def tab_smart_compose():
    """智能组卷独立 Tab：配置后先组草稿试卷，确认后转正式试卷。"""
    st.subheader("🤖 智能组卷")
    st.caption("按资料章节、知识点、题型题量和难度配比组卷，生成后创建为试卷。")

    if st.session_state.get("smart_compose_result") is None:
        # 清理上次异常退出可能残留的草稿。
        with SessionLocal() as session:
            leftovers = (session.query(Homework)
                         .filter(Homework.is_template.is_(True))
                         .all())
            for draft in leftovers:
                if draft.name.startswith(SMART_COMPOSE_DRAFT_PREFIX):
                    session.delete(draft)
            session.commit()
        _smart_compose_config_ui()
    else:
        _smart_compose_preview_ui()


def _cleanup_smart_draft(session, homework_id: int) -> None:
    """删除智能组卷草稿及其题目关联。"""
    draft = session.get(Homework, int(homework_id))
    if draft is not None and draft.name.startswith(SMART_COMPOSE_DRAFT_PREFIX):
        session.delete(draft)
        session.flush()


def _default_type_matrix() -> list[dict]:
    """默认题型矩阵。"""
    return [
        {"type": "选择题", "easy": 0, "medium": 1, "hard": 0},
        {"type": "填空题", "easy": 0, "medium": 1, "hard": 0},
        {"type": "计算题", "easy": 0, "medium": 1, "hard": 0},
    ]


def _smart_compose_config_ui():
    """智能组卷配置界面。"""
    if "smart_compose_type_matrix" not in st.session_state:
        st.session_state["smart_compose_type_matrix"] = _default_type_matrix()

    with st.container(border=True):
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            subject = _subject_selectbox(fs.SMART_COMPOSE_SUBJECT)
        with c2:
            grade = st.selectbox(
                "年级", DISPLAY_GRADE_CHOICES, index=0,
                key="smart_compose_grade")
        with c3:
            total_score = st.number_input(
                "试卷总分", min_value=1.0, value=100.0, step=5.0,
                key="smart_compose_total")
        with c4:
            duration = st.number_input(
                "建议用时（分钟）", min_value=1, value=60, step=5,
                key="smart_compose_duration")

    with SessionLocal() as session:
        materials = (session.query(Textbook)
                     .filter(Textbook.subject == subject)
                     .order_by(Textbook.id.desc()).all())
        material_labels = {book.id: book.name for book in materials}

    book_id = st.selectbox(
        "选择资料（可选）", [None] + [book.id for book in materials],
        format_func=lambda x: "不使用资料" if x is None else material_labels[x],
        key="smart_compose_material")
    selected_book = next((book for book in materials if book.id == book_id), None)

    chapter_options = (
        _smart_material_chapters(selected_book) if selected_book is not None else [])
    st.multiselect(
        "选择章节（可选，只用于约束 AI 补题）", chapter_options,
        disabled=selected_book is None,
        key="smart_compose_chapters")

    with SessionLocal() as session:
        known_kps = qs.get_all_knowledge_points(session, subject)
    st.multiselect(
        "选择知识点（可选，题库和 AI 都按此约束）", known_kps,
        key="smart_compose_kps")
    manual_kps = st.text_input(
        "手动补充知识点（逗号分隔）", key="smart_compose_manual_kps")
    all_kps = list(dict.fromkeys(
        list(st.session_state.get("smart_compose_kps", []))
        + [item.strip()
           for item in re.split(r"[，,、;；]", manual_kps) if item.strip()]
    ))

    st.markdown("**题型 × 难度数量**")
    storage_grade = to_storage_grade(grade)
    type_options = qs.question_type_options(storage_grade, subject)
    matrix_rows = st.session_state["smart_compose_type_matrix"]

    for idx, row in enumerate(matrix_rows):
        c1, c2, c3, c4, c5, c6 = st.columns([3.2, 1, 1, 1, 0.8, 0.7])
        current_index = (type_options.index(row["type"])
                         if row["type"] in type_options else 0)
        row["type"] = c1.selectbox(
            "题型", type_options, index=current_index,
            key=f"smart_type_{idx}", label_visibility="collapsed")
        row["easy"] = int(c2.number_input(
            "基础", min_value=0, value=int(row["easy"]), step=1,
            key=f"smart_easy_{idx}"))
        row["medium"] = int(c3.number_input(
            "中等", min_value=0, value=int(row["medium"]), step=1,
            key=f"smart_medium_{idx}"))
        row["hard"] = int(c4.number_input(
            "拓展", min_value=0, value=int(row["hard"]), step=1,
            key=f"smart_hard_{idx}"))
        c5.markdown(f"**{row['easy'] + row['medium'] + row['hard']}**")
        if c6.button("🗑️", key=f"smart_del_row_{idx}"):
            matrix_rows.pop(idx)
            st.rerun()

    bc1, bc2 = st.columns(2)
    if bc1.button("➕ 添加题型行", key="smart_add_type_row"):
        matrix_rows.append({
            "type": type_options[0] if type_options else "选择题",
            "easy": 0, "medium": 1, "hard": 0})
        st.rerun()
    if bc2.button("恢复默认题型", key="smart_reset_matrix"):
        st.session_state["smart_compose_type_matrix"] = _default_type_matrix()
        st.rerun()

    st.divider()
    st.markdown("#### 组卷方案")
    templates = scs.load_templates()
    tc1, tc2, tc3 = st.columns(3)
    selected_template = tc1.selectbox(
        "加载组卷方案", [None] + templates,
        format_func=lambda item: "不加载" if item is None else
        f"{item.get('name')}（{item.get('created_at')}）",
        key="smart_selected_template")
    if tc2.button("📥 应用方案", key="smart_apply_template",
                  disabled=selected_template is None):
        template_subject = selected_template.get("subject") or subject
        template_grade = selected_template.get("grade") or grade
        if template_subject in SUBJECT_NAMES:
            fs.set_feature_subject(fs.SMART_COMPOSE_SUBJECT, template_subject)
        st.session_state["smart_compose_grade"] = template_grade
        st.session_state["smart_compose_type_matrix"] = [
            dict(row) for row in selected_template.get("rows", [])]
        st.session_state["smart_compose_total"] = selected_template.get(
            "total_score", 100.0)
        st.session_state["smart_compose_duration"] = selected_template.get(
            "duration", 60)
        st.rerun()
    template_name = tc3.text_input("方案名称", key="smart_template_name")
    sc1, sc2 = st.columns(2)
    if sc1.button("💾 保存为组卷方案", key="smart_save_template"):
        try:
            scs.save_template(
                template_name, subject, grade, total_score, duration, matrix_rows)
            st.success("组卷方案已保存。")
            st.rerun()
        except ValueError as exc:
            st.warning(str(exc))
    if sc2.button("🗑️ 删除所选方案", key="smart_delete_template",
                  disabled=selected_template is None):
        scs.delete_template(selected_template["template_id"])
        st.rerun()

    if st.button("🤖 开始组卷", type="primary", key="smart_compose_run"):
        try:
            slots = hw_svc.slots_from_type_matrix(matrix_rows)
        except ValueError as exc:
            st.error(str(exc))
            return

        import uuid
        draft_name = f"{SMART_COMPOSE_DRAFT_PREFIX}{uuid.uuid4().hex}"
        storage_grade = to_storage_grade(grade)
        spec = {"slots": slots}
        ai_context = {
            "textbook_id": selected_book.id if selected_book else None,
            "chapters": list(st.session_state.get("smart_compose_chapters", [])),
            "grade": storage_grade,
        }

        draft_id = None
        try:
            with SessionLocal() as session:
                draft = hw_svc.create_homework(
                    session, draft_name, homework_type="exam",
                    total_score=total_score, duration=duration,
                    is_template=True, subject=subject, grade=storage_grade)
                draft_id = draft.id
                result = hw_svc.auto_compose(
                    session, draft.id, spec, all_kps, ai_context=ai_context)
                session.commit()
        except Exception as exc:
            if draft_id is not None:
                try:
                    with SessionLocal() as cleanup_session:
                        hw_svc.delete_homeworks(cleanup_session, [draft_id])
                        cleanup_session.commit()
                except Exception as cleanup_exc:
                    st.caption(f"临时草稿清理失败，请在智能组卷页手动删除：{cleanup_exc}")
            st.error("组卷没有完成，暂时没有生成试卷。请调整资料、知识点或题型数量后重试。")
            with st.expander("技术详情"):
                st.text(str(exc))
            return

        display_grade = grade
        try:
            scs.add_history(subject, display_grade, draft_id, result)
        except OSError:
            st.caption("组卷历史暂时没有写入，不影响本次试卷。")
        st.session_state.pop("smart_compose_paper_name", None)
        st.session_state["smart_compose_result"] = {
            "homework_id": draft_id,
            "result": result,
        }
        st.rerun()

    _generated_exams_panel(subject)
    _compose_history_panel(subject)


def _generated_exams_panel(subject: str):
    """智能组卷页底部的正式试卷列表。"""
    st.divider()
    st.markdown("### 📄 已生成试卷")
    with SessionLocal() as session:
        exams = hw_svc.list_homeworks(
            session, templates=False, homework_type="exam", subject=subject)
        exams = [item for item in exams
                 if not item.name.startswith(SMART_COMPOSE_DRAFT_PREFIX)]
        exam_counts = {item.id: hw_svc.question_count(session, item.id) for item in exams}
    if not exams:
        st.info("还没有生成试卷，上方配置后点击“开始组卷”。")
        return
    for exam in exams:
        with st.container(border=True):
            c1, c2, c3, c4 = st.columns([4.5, 1, 1, 1])
            c1.markdown(
                f"📄 **{exam.name}**　{exam.class_name or ''}　"
                f"{exam_counts.get(exam.id, 0)} 题　满分 {exam.total_score or 0}")
            if c2.button("打开编辑", key=f"open_exam_{exam.id}"):
                with SessionLocal() as session:
                    hw_svc.touch_homework(session, exam.id)
                    session.commit()
                st.session_state["hw_open_id"] = exam.id
                st.session_state["homework_tab"] = "作业管理"
                st.rerun()
            if c3.button("导出", key=f"export_exam_{exam.id}"):
                with SessionLocal() as session:
                    data = hw_svc.export_word(session, exam.id, with_answer=False)
                st.download_button(
                    "⬇️ 下载试卷", data,
                    file_name=f"{exam.name}.docx", mime=DOCX_MIME,
                    key=f"download_exam_{exam.id}")
            if c4.button("删除", key=f"del_exam_{exam.id}"):
                st.session_state["confirm_del_exam"] = exam.id
            if st.session_state.get("confirm_del_exam") == exam.id:
                cc1, cc2 = st.columns(2)
                if cc1.button("确认删除", key=f"ok_del_exam_{exam.id}",
                              type="primary"):
                    with SessionLocal() as session:
                        hw_svc.delete_homework(session, exam.id)
                        session.commit()
                    st.session_state.pop("confirm_del_exam", None)
                    st.rerun()
                if cc2.button("取消", key=f"cancel_del_exam_{exam.id}"):
                    st.session_state.pop("confirm_del_exam", None)
                    st.rerun()


def _compose_history_panel(subject: str):
    """显示最近 10 条组卷历史。"""
    st.markdown("### 📜 组卷历史")
    history = [item for item in scs.load_history()
               if item.get("subject") == subject][:10]
    if not history:
        st.caption("暂无组卷历史。")
        return
    rows = [{
        "时间": item.get("created_at", ""),
        "年级": item.get("grade", ""),
        "总题数": item.get("total_questions", 0),
        "题库抽题": item.get("rule_picked", 0),
        "AI补题": item.get("ai_generated", 0),
        "未满足": item.get("shortage_count", 0),
    } for item in history]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def _smart_compose_preview_ui():
    """预览草稿试卷，确认后转正式试卷。"""
    data = st.session_state["smart_compose_result"]
    with SessionLocal() as session:
        draft = session.get(Homework, data["homework_id"])
        if draft is None:
            st.session_state["smart_compose_result"] = None
            st.rerun()
            return
        pairs = hw_svc.homework_questions(session, draft.id)
        subject = draft.subject or DEFAULT_SUBJECT
        grade = to_display_grade(draft.grade) or "未指定"

    result = data["result"]
    st.success(
        f"组卷完成：题库抽题 {result['rule_picked']} 道，"
        f"AI 补题 {result['ai_generated']} 道，共 {len(pairs)} 道。")
    if result.get("shortage_count"):
        st.warning(f"仍有 {result['shortage_count']} 个槽位未满足。")

    for i, (_link, question) in enumerate(pairs, start=1):
        title = (f"第{i}题 [{TYPE_LABELS.get(question.question_type, question.question_type)}"
                 f"·{DIFF_LABELS.get(question.difficulty, question.difficulty)}]")
        with st.expander(title):
            st.markdown(question.content)
            kps = qs.knowledge_points_list(question)
            st.caption("知识点：" + ("、".join(kps) if kps else "—"))
            if question.status != "approved":
                st.caption("这道 AI 补题目前是待审核状态。")
            if st.button("🗑️ 移除此题", key=f"remove_q_{question.id}"):
                with SessionLocal() as session:
                    hw_svc.remove_question(session, draft.id, question.id)
                    session.commit()
                st.rerun()

    default_name = f"{subject}{grade}智能组卷"
    paper_name = st.text_input(
        "试卷名称", value=st.session_state.get("smart_compose_paper_name", default_name),
        key="smart_compose_paper_name")

    c1, c2, c3 = st.columns(3)
    if c1.button("✅ 创建为正式试卷", type="primary", key="confirm_smart_paper"):
        if not paper_name.strip():
            st.error("请填写试卷名称。")
            return
        if not pairs:
            st.error("当前没有题目，不能创建试卷。")
            return
        with SessionLocal() as session:
            formal = session.get(Homework, draft.id)
            formal.is_template = False
            formal.homework_type = "exam"
            formal.name = paper_name.strip()
            session.commit()
            formal_id = formal.id
        st.session_state["smart_compose_result"] = None
        st.session_state["homework_tab"] = "作业管理"
        st.session_state["hw_open_id"] = formal_id
        st.session_state["hw_batch_last"] = "试卷已创建。"
        st.rerun()

    if c2.button("🔄 重新配置", key="reconfigure_smart_paper"):
        with SessionLocal() as session:
            _cleanup_smart_draft(session, draft.id)
            session.commit()
        st.session_state["smart_compose_result"] = None
        st.rerun()

    if c3.button("❌ 放弃", key="discard_smart_paper"):
        with SessionLocal() as session:
            _cleanup_smart_draft(session, draft.id)
            session.commit()
        st.session_state["smart_compose_result"] = None
        for key in _SMART_CONFIG_KEYS:
            st.session_state.pop(key, None)
        st.rerun()


# ===========================================================================
# Tab 3：成绩录入
# ===========================================================================

def _pick_homework_and_class(templates: bool = False):
    """选普通作业 + 班级两个下拉，返回 (hw, class_name)。成绩/分析不按学科隐藏作业。"""
    with SessionLocal() as session:
        homeworks = hw_svc.list_homeworks(session, templates=False)
        classes = student_svc.list_classes(session)
    if not homeworks:
        st.info("还没有作业，先到“作业管理”新建。")
        return None, None, None
    labels = [
        f"[{hw.subject or DEFAULT_SUBJECT}] {hw_svc.type_emoji(hw.homework_type)} "
        f"{hw.name}（{hw.class_name or '未分班'}）" for hw in homeworks]
    idx = st.selectbox("选择作业", range(len(homeworks)),
                       format_func=lambda i: labels[i])
    hw = homeworks[idx]
    class_name = st.selectbox(
        "选择班级", ["（作业默认/全部）"] + classes,
        index=(0 if not hw.class_name or hw.class_name not in classes
               else classes.index(hw.class_name) + 1))
    selected_class = None if class_name == "（作业默认/全部）" else class_name
    return hw, selected_class, classes

def tab_scores():
    st.subheader("成绩录入")
    hw, class_name, _classes = _pick_homework_and_class()
    if hw is None:
        return
    st.caption("总分支持 Excel 导入或手动录入；需要错题本和每题正确率时，用下方逐题批改。")

    tabs = st.tabs(["Excel 导入总分", "手动录总分", "逐题批改"])
    with tabs[0]:
        _import_total_scores(hw)
    with tabs[1]:
        _manual_total_scores(hw, class_name)
    with tabs[2]:
        _grade_per_question(hw, class_name)


def _import_total_scores(hw):
    """复用阶段1成绩列识别：姓名 + 一个总分列，预览确认后 upsert。"""
    up = st.file_uploader("选择成绩 Excel/CSV（含“姓名”列和一个分数列）",
                       type=["xlsx", "csv"])
    if up is None:
        return
    try:
        df = eh.load_dataframe(up)
        detected = eh.detect_score_columns(df)
    except Exception as exc:
        st.error(f"读取失败：{exc}")
        return
    for problem in detected["problems"]:
        st.error(problem)
    if detected["name_col"] is None or not detected["subjects"]:
        return
    # 作业只有一个总分：取识别到的第一个分数列
    score_col = detected["subjects"][0][0]
    records = []
    for _i, row in df.iterrows():
        name = eh._to_text(row[detected["name_col"]])
        score = eh._to_score(row[score_col])
        cls = (eh._to_text(row[detected["class_col"]])
               if detected["class_col"] else None)
        if not name and score is None:
            continue
        records.append({"name": name, "class_name": cls, "score": score})
    bad = [r for r in records if not r["name"] or r["score"] is None]
    if bad:
        st.warning(f"{len(bad)} 行缺姓名或缺分数，写入时跳过。")
    st.dataframe(pd.DataFrame([{"姓名": r["name"], "班级": r["class_name"] or "",
                                "分数": r["score"],
                                "状态": ("正常" if r["name"] and r["score"] is not None
                                         else "缺姓名/缺分")} for r in records]),
                 width="stretch", hide_index=True)
    if st.button("✅ 确认导入", type="primary", key="import_hw_score"):
        with SessionLocal() as session:
            result = hscore.import_total_scores(session, hw.id, records)
            session.commit()
        st.success(f"写入 {result['written']} 条，更新 {result['updated']} 条，"
                   f"自动新建学生 {result['created_students']} 人，跳过 {result['skipped']} 行。")
        _render_instant_score_stats(hw.id)


def _render_instant_score_stats(homework_id: int):
    """保存成绩后立刻显示本次作业总体情况。"""
    with SessionLocal() as session:
        data = hscore.analyze_homework(session, homework_id)
    overall = data["overall"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("已交人数", overall["submitted"])
    c2.metric("平均分", overall["mean"] if overall["mean"] is not None else "—")
    c3.metric("最高分", overall["max"] if overall["max"] is not None else "—")
    c4.metric("最低分", overall["min"] if overall["min"] is not None else "—")


def _manual_total_scores(hw, class_name):
    """data_editor 手动录总分，保存后自动算并列排名。"""
    with SessionLocal() as session:
        rows = hscore.score_rows(session, hw.id, class_name)
    if not rows:
        st.info("该班还没有学生。可先用 Excel 导入（会自动建学生）或到学情页添加学生。")
        return
    editable = pd.DataFrame([{
        "学生": r["name"], "班级": r["class_name"] or "",
        "总分": r["score"] if r["score"] is not None else None,
        "状态": "已交" if r["score"] is not None else "未交"} for r in rows])
    edited = st.data_editor(
        editable, num_rows="fixed", width="stretch", hide_index=True,
        key=f"manual_total_{hw.id}",
        column_config={"状态": st.column_config.TextColumn(disabled=True)})
    if st.button("💾 保存总分", type="primary", key=f"save_total_{hw.id}"):
        with SessionLocal() as session:
            for r, (_, new) in zip(rows, edited.iterrows()):
                val = new["总分"]
                score = None if pd.isna(val) else float(val)
                hscore.save_total_score(session, hw.id, r["student_id"], score)
            session.commit()
        st.success("总分已保存。")
        _render_instant_score_stats(hw.id)
    # 排名预览
    values = [None if pd.isna(v) else float(v) for v in edited["总分"]]
    ranks = _ranks(values)
    preview = edited.copy()
    preview["班内排名"] = ranks
    st.dataframe(preview, width="stretch", hide_index=True)


def _ranks(values):
    """并列竞赛名次，缺考 None。"""
    scored = sorted((v for v in values if v is not None), reverse=True)
    rank_map = {}
    for i, v in enumerate(scored):
        rank_map.setdefault(v, i + 1)
    return [rank_map.get(v) if v is not None else None for v in values]

def _grade_per_question(hw, class_name):
    """逐题批改：一行一学生、一题一组（对错+得分+错误类型），写 HomeworkAnswer。"""
    with SessionLocal() as session:
        pairs = hw_svc.homework_questions(session, hw.id)
        students = student_svc.list_students(session, class_name=class_name
                                             or hw.class_name or None)
        if not pairs:
            st.info("这份作业还没有题目，先到“作业管理”加题。")
            return
        if not students:
            st.info("该班还没有学生，先到学情页添加或用 Excel 导入成绩自动建学生。")
            return

        # 已有作答，便于回显
        from models.models import HomeworkAnswer
        existing = {}
        for a in (session.query(HomeworkAnswer)
                  .filter(HomeworkAnswer.homework_id == hw.id).all()):
            existing[(a.student_id, a.question_id)] = a

        st.caption(f"共 {len(students)} 名学生、{len(pairs)} 道题。"
                   "每题选“对/错”即记录；错题可选错误类型，会自动进入错题本。")
        entries = []
        for stu in students:
            with st.expander(f"{stu.name}（{stu.class_name or '未分班'}）",
                             expanded=False):
                for order, (link, q) in enumerate(pairs, start=1):
                    old = existing.get((stu.id, q.id))
                    c1, c2, c3 = st.columns([1.2, 1, 2])
                    judge = c1.selectbox(
                        f"第{order}题", ["未判", "对", "错"],
                        index=(0 if old is None or old.is_correct is None
                               else (1 if old.is_correct else 2)),
                        key=f"j_{hw.id}_{stu.id}_{q.id}",
                        label_visibility="visible")
                    earned = c2.number_input(
                        "得分", min_value=0.0, max_value=float(link.score or 100),
                        value=float(old.earned_score) if (old and old.earned_score is not None)
                        else 0.0,
                        key=f"e_{hw.id}_{stu.id}_{q.id}")
                    err_idx = 0
                    if old and old.error_type in hscore.ERROR_TYPES:
                        err_idx = hscore.ERROR_TYPES.index(old.error_type) + 1
                    err = c3.selectbox(
                        "错误类型", ["（无）"] + hscore.ERROR_TYPES,
                        index=err_idx, key=f"t_{hw.id}_{stu.id}_{q.id}")
                    if judge != "未判":
                        entries.append({
                            "student_id": stu.id, "question_id": q.id,
                            "order_no": order,
                            "is_correct": judge == "对",
                            "earned_score": earned,
                            "error_type": None if err == "（无）" else err,
                        })
        if st.button("💾 保存批改结果", type="primary", key=f"save_ans_{hw.id}"):
            result = hscore.save_answers(session, hw.id, entries)
            session.commit()
            st.success(f"已保存 {result['written']} 条逐题作答，错题已进入错题本。")


# ===========================================================================
# Tab 3：作业分析
# ===========================================================================

def tab_analysis():
    st.subheader("作业分析")
    current_subject = _subject_selectbox(fs.HOMEWORK_ANALYSIS_SUBJECT)
    with SessionLocal() as session:
        homeworks = hw_svc.list_homeworks(
            session, templates=False, subject=current_subject)
    if not homeworks:
        st.info("还没有作业。")
        return
    labels = [
        f"[{hw.subject or DEFAULT_SUBJECT}] {hw_svc.type_emoji(hw.homework_type)} "
        f"{hw.name}（{hw.class_name or '未分班'}）" for hw in homeworks]
    idx = st.selectbox("选择作业", range(len(homeworks)),
                       format_func=lambda i: labels[i], key="analyze_pick")
    hw = homeworks[idx]
    with SessionLocal() as session:
        data = hscore.analyze_homework(session, hw.id)
        _render_analysis(session, hw, data)

def _default_score_segments(full: float) -> pd.DataFrame:
    """作业分析默认分数段。"""
    return pd.DataFrame([
        {"段名": "不及格", "下限": 0, "上限": full * 0.6},
        {"段名": "及格", "下限": full * 0.6, "上限": full * 0.7},
        {"段名": "中等", "下限": full * 0.7, "上限": full * 0.8},
        {"段名": "良好", "下限": full * 0.8, "上限": full * 0.9},
        {"段名": "优秀", "下限": full * 0.9, "上限": full + 1},
    ])


def _normalize_segments(df: pd.DataFrame, full: float):
    """校验并归一自定义分数段，返回标签和边界。"""
    rows = []
    for row in df.to_dict("records"):
        name = str(row.get("段名") or "").strip()
        if not name:
            continue
        try:
            lower = float(row.get("下限"))
            upper = float(row.get("上限"))
        except (TypeError, ValueError):
            raise ValueError("分数段下限和上限必须是数字。")
        if lower < 0 or upper <= lower:
            raise ValueError("分数段下限不能为负，且上限必须大于下限。")
        rows.append((name, lower, upper))
    if not rows:
        raise ValueError("请至少保留一个分数段。")
    rows.sort(key=lambda x: x[1])
    for i, item in enumerate(rows):
        if i and round(item[1], 6) != round(rows[i - 1][2], 6):
            raise ValueError("相邻分数段必须首尾相接。")
    if rows[-1][2] < full + 0.001:
        raise ValueError("最后一个分数段上限不能低于试卷总分。")
    labels = [x[0] for x in rows]
    edges = [x[1] for x in rows] + [rows[-1][2]]
    return labels, edges


def _render_analysis(session, hw, data):
    overall = data["overall"]
    rows = data["rows"]
    full = float(hw.total_score or 100)
    values = [r["score"] for r in rows if r["score"] is not None]

    st.markdown("**分数阈值**")
    t1, t2 = st.columns(2)
    pass_line = t1.number_input(
        "及格线（分）", min_value=0.0, max_value=full,
        value=float(round(full * 0.6, 1)), step=1.0,
        key=f"hw_pass_line_{hw.id}")
    excellent_line = t2.number_input(
        "优秀线（分）", min_value=0.0, max_value=full,
        value=float(round(full * 0.85, 1)), step=1.0,
        key=f"hw_excellent_line_{hw.id}")

    pass_count = sum(1 for v in values if v >= pass_line)
    excellent_count = sum(1 for v in values if v >= excellent_line)
    c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
    c1.metric("提交率", (f"{overall['submission_rate'] * 100:.0f}%"
                        if overall["submission_rate"] is not None else "—"))
    c2.metric("已交 / 应到", f"{overall['submitted']} / {overall['total']}")
    c3.metric("平均分", overall["mean"] if overall["mean"] is not None else "—")
    c4.metric("最高分", overall["max"] if overall["max"] is not None else "—")
    c5.metric("最低分", overall["min"] if overall["min"] is not None else "—")
    c6.metric("优秀率", f"{excellent_count / len(values) * 100:.0f}%" if values else "—")
    c7.metric("及格率", f"{pass_count / len(values) * 100:.0f}%" if values else "—")

    st.markdown("**自定义分数段**")
    segment_key = f"hw_score_segments_{hw.id}"
    if segment_key not in st.session_state:
        st.session_state[segment_key] = _default_score_segments(full)
    segment_df = st.data_editor(
        st.session_state[segment_key], num_rows="dynamic",
        key=f"{segment_key}_editor", hide_index=True, width="stretch")
    try:
        segment_labels, segment_edges = _normalize_segments(segment_df, full)
    except ValueError as exc:
        st.warning(str(exc))
        segment_labels, segment_edges = None, None

    if values and segment_labels:
        bands = stats_mod.score_bands(values, full, edges=segment_edges,
                                      labels=segment_labels)
        fig = go.Figure(go.Bar(
            x=[b["label"] for b in bands], y=[b["count"] for b in bands],
            marker_color="#1F4E79", text=[b["count"] for b in bands]))
        fig.update_layout(title="分数段分布", height=320,
                          margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig, width="stretch")

    class_stats = {}
    for r in rows:
        if r["score"] is None:
            continue
        class_name = r["class_name"] or "未分班"
        class_stats.setdefault(class_name, []).append(r["score"])
    if len(class_stats) > 1:
        class_names = list(class_stats)
        means = [sum(class_stats[x]) / len(class_stats[x]) for x in class_names]
        fig_class = go.Figure(go.Bar(
            x=class_names, y=means, marker_color="#2E8B57",
            text=[f"{v:.1f}" for v in means]))
        fig_class.update_layout(title="多班级平均分对比", height=320,
                                margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig_class, width="stretch")

    deltas = data["deltas"]
    prev_name = data["previous"].name if data["previous"] else None
    table = []
    for r in rows:
        delta = deltas.get(r["student_id"])
        if delta is None:
            mark = "—"
        elif delta > 0:
            mark = f"↑ +{delta:g}"
        elif delta < 0:
            mark = f"↓ {delta:g}"
        else:
            mark = "持平"
        table.append({"名次": r["rank"] if r["rank"] is not None else "未交",
                      "姓名": r["name"], "班级": r["class_name"] or "",
                      "总分": r["score"] if r["score"] is not None else "未交",
                      "进退步": mark})
    rank_df = pd.DataFrame(table)
    st.markdown(f"**学生排名**" + (f"（对比上一份作业：{prev_name}）" if prev_name else ""))
    st.dataframe(rank_df, width="stretch", hide_index=True)
    if not rank_df.empty:
        import io
        excel_buf = io.BytesIO()
        rank_df.to_excel(excel_buf, index=False)
        st.download_button(
            "📊 导出排名 Excel", excel_buf.getvalue(),
            file_name=f"{hw.name}-排名.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key=f"rank_excel_{hw.id}")

    pq = data["per_question"]
    if pq:
        st.markdown("**每题正确率**")
        qlabels, rates = [], []
        qmap = {q.id: (i + 1, q) for i, (_l, q) in
                enumerate(hw_svc.homework_questions(session, hw.id))}
        for item in pq:
            order, q = qmap.get(item["question_id"], (item["order_no"], None))
            qlabels.append(f"第{order}题")
            rates.append((item["rate"] or 0) * 100 if item["rate"] is not None else None)
        fig2 = go.Figure(go.Bar(
            x=qlabels, y=rates, marker_color="#2E8B57",
            text=[("—" if r is None else f"{r:.0f}%") for r in rates]))
        fig2.update_layout(title="每题正确率（%）", height=300, yaxis_range=[0, 100],
                           margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig2, width="stretch")

    top_wrong = data["top_wrong"]
    if top_wrong:
        st.markdown("**高频错题 TOP5**")
        qmap = {q.id: (i + 1, q) for i, (_l, q) in
                enumerate(hw_svc.homework_questions(session, hw.id))}
        tw_rows = []
        for item in top_wrong:
            order, q = qmap.get(item["question_id"], (item["order_no"], None))
            tw_rows.append({
                "题目": f"第{order}题",
                "错误人数": item["wrong"], "已判人数": item["judged"],
                "典型错题": "是" if item["typical"] else "",
                "题干": (q.content[:30] if q is not None else "")})
        st.dataframe(pd.DataFrame(tw_rows), width="stretch", hide_index=True)

    _ai_summary(session, hw, data, values)
    _export_analysis(session, hw)


def _ai_summary(session, hw, data, values):
    """AI 作业分析总结；可保存到作业备注。"""
    st.markdown("**AI 分析总结**")
    if not llm_client.is_configured():
        st.info("还没配置 AI：到「⚙️ 设置 → 主模型配置」填写 API Key 后可生成分析。")
        return
    reply_key = f"hw_ai_reply_{hw.id}"
    if st.button("🤖 生成分析总结", key=f"ai_hw_{hw.id}"):
        pq_lines = []
        for item in data["per_question"]:
            if item["rate"] is not None:
                pq_lines.append(f"第{item['order_no']}题正确率 {item['rate'] * 100:.0f}%，"
                                f"错误 {item['wrong']} 人")
        payload = (
            f"作业：{hw.name}；应到 {data['overall']['total']} 人，"
            f"已交 {data['overall']['submitted']} 人；"
            f"均分 {data['overall']['mean']}，最高 {data['overall']['max']}，"
            f"最低 {data['overall']['min']}。\n"
            f"每题情况：{'；'.join(pq_lines) if pq_lines else '暂无逐题批改数据'}。")
        system_prompt = _read_prompt("homework_analysis_prompt.txt").replace("{data}", "")
        with st.spinner("AI 正在分析……"):
            try:
                st.session_state[reply_key] = llm_client.chat(
                    system_prompt, payload, temperature=0.5)
            except (llm_client.LLMConfigError, llm_client.LLMCallError) as exc:
                st.error(f"生成失败：{exc}")
                return
    reply = st.session_state.get(reply_key)
    if reply:
        st.markdown(reply)
        c1, c2 = st.columns(2)
        if c1.button("💾 保存到作业备注", key=f"save_ai_remark_{hw.id}"):
            hw_svc.update_homework(session, hw.id, remark=reply)
            session.commit()
            st.success("已保存到作业备注。")
        if c2.button("清除本次分析", key=f"clear_ai_reply_{hw.id}"):
            st.session_state.pop(reply_key, None)
            st.rerun()


def _export_analysis(session, hw):
    """把分析结果导成 Word。"""
    if st.button("📄 导出分析报告 Word", key=f"exp_hw_{hw.id}"):
        data = hscore.analyze_homework(session, hw.id)
        import io
        from docx import Document
        doc = Document()
        doc.add_heading(f"{hw.name} · 作业分析", level=0)
        o = data["overall"]
        doc.add_paragraph(
            f"应到 {o['total']} 人，已交 {o['submitted']} 人，"
            f"均分 {o['mean']}，最高 {o['max']}，最低 {o['min']}。")
        doc.add_heading("学生排名", level=1)
        for r in data["rows"]:
            doc.add_paragraph(
                f"{r['rank'] if r['rank'] is not None else '未交'}. "
                f"{r['name']}　{r['score'] if r['score'] is not None else '未交'}分")
        doc.add_heading("每题正确率", level=1)
        for item in data["per_question"]:
            rate = "未批改" if item["rate"] is None else f"{item['rate'] * 100:.0f}%"
            doc.add_paragraph(f"第{item['order_no']}题：{rate}（错误 {item['wrong']} 人）")
        buf = io.BytesIO()
        doc.save(buf)
        st.download_button("⬇️ 下载分析报告", buf.getvalue(),
                           file_name=f"{hw.name}-分析.docx", mime=DOCX_MIME,
                           key=f"dl_analyze_{hw.id}")

# ===========================================================================
# Tab 4：错题本
# ===========================================================================

def tab_wrong_book():
    """错题本：统计、筛选、重做、按知识点聚合、单题移除。"""
    st.subheader("错题本")
    current_subject = _subject_selectbox(fs.WRONG_BOOK_SUBJECT)

    with SessionLocal() as session:
        students = student_svc.list_students(session)
        homeworks = hw_svc.list_homeworks(
            session, templates=False, subject=current_subject)

    with st.container(border=True):
        c1, c2, c3, c4, c5 = st.columns(5)
        stu = c1.selectbox(
            "学生", [None] + students,
            format_func=lambda x: "全部学生" if x is None else
            f"{x.name}（{x.class_name or '未分班'}）",
            key="wb_student")
        grade_filter = c2.selectbox(
            "年级", ["全部年级"] + DISPLAY_GRADE_CHOICES, key="wb_grade")
        hw = c3.selectbox(
            "作业", [None] + homeworks,
            format_func=lambda x: "全部作业" if x is None else x.name,
            key="wb_hw")
        err = c4.selectbox(
            "错误类型", [None] + hscore.ERROR_TYPES,
            format_func=lambda x: "全部类型" if x is None else x,
            key="wb_err")
        keyword = c5.text_input("知识点/题干关键词", key="wb_kw")

    storage_grade = None if grade_filter == "全部年级" else to_storage_grade(grade_filter)
    with SessionLocal() as session:
        rows = hscore.list_wrong_answers(
            session,
            student_id=stu.id if stu is not None else None,
            homework_id=hw.id if hw is not None else None,
            error_type=err, knowledge_keyword=keyword.strip() or None,
            subject=current_subject, grade=storage_grade)

    if not rows:
        st.info("暂无错题，继续保持。需要逐题批改后，错题才会自动收集到这里。")
        return

    selected_count = sum(
        1 for r in rows if st.session_state.get(f"retry_pick_{r['answer_id']}"))
    error_counts = {}
    for r in rows:
        key = r.get("error_type") or "未分类"
        error_counts[key] = error_counts.get(key, 0) + 1
    top_error = max(error_counts, key=error_counts.get) if error_counts else "—"
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("总错题数", len(rows))
    m2.metric("涉及学生", len({r["student_id"] for r in rows}))
    m3.metric("高频错误类型", top_error)
    m4.metric("待重做", selected_count)

    view_mode = st.radio(
        "查看方式", ["按题目列表", "按知识点聚合"], horizontal=True,
        key="wb_view_mode")
    if view_mode == "按知识点聚合":
        _wrong_knowledge_aggregation(rows)
        return

    basket = st.session_state.setdefault("next_hw_question_basket", [])
    bc1, bc2 = st.columns([4, 1])
    bc1.caption(f"🧺 题篮：{len(basket)} 道题待带入新作业（仅同学科作业）。")
    if bc2.button("清空题篮", key="clear_basket_wrongbook", disabled=not basket):
        st.session_state["next_hw_question_basket"] = []
        st.rerun()

    _retry_preview_editor(rows, current_subject)

    export_group_label = st.radio(
        "PDF 分类方式", ["按学生", "按知识点"], horizontal=True,
        key="wb_pdf_group")
    ec1, ec2 = st.columns(2)
    if ec1.button("📄 导出错题本 Word", key="wb_export"):
        data = hscore.export_wrong_word(rows, title=f"{current_subject}错题本")
        st.download_button(
            "⬇️ 下载错题本", data,
            file_name=f"{current_subject}错题本.docx",
            mime=DOCX_MIME, key="wb_export_dl")
    if ec2.button("📄 导出错题本 PDF", key="wb_export_pdf"):
        data = hscore.export_wrong_pdf(
            rows, title=f"{current_subject}错题本",
            group_by="student" if export_group_label == "按学生" else "knowledge")
        st.download_button(
            "⬇️ 下载错题本 PDF", data,
            file_name=f"{current_subject}错题本.pdf",
            mime="application/pdf", key="wb_export_pdf_dl")

    for r in rows:
        tag = "　🔥 典型错题" if r["typical"] else ""
        grade_text = to_display_grade(r.get("grade")) or "未指定"
        with st.expander(
                f"{r['student_name']}｜{grade_text}｜{r['homework_name']}｜"
                f"第{r['order_no'] or '?'}题{tag}｜{r['error_type'] or '未分类'}"):
            st.checkbox("➕ 加入错题重做卷",
                        key=f"retry_pick_{r['answer_id']}")
            st.caption(
                f"知识点：{'、'.join(r['knowledge_points']) or '—'}　"
                f"题型：{TYPE_LABELS.get(r['question_type'], r['question_type'])}　"
                f"本题得分：{r['earned_score'] if r['earned_score'] is not None else '未录'}")
            ac1, ac2, ac3 = st.columns(3)
            in_basket = r["question_id"] in basket
            if ac1.button("➕ 加入下次作业", key=f"wb_add_{r['answer_id']}",
                          disabled=in_basket):
                _add_to_next_hw_basket(r["question_id"])
                st.toast("已加入题篮，新建同学科作业时自动带入。")
                st.rerun()
            if ac2.button("🔓 打开这次作业", key=f"wb_open_{r['answer_id']}"):
                st.session_state["homework_tab"] = "作业管理"
                st.session_state["hw_open_id"] = r["homework_id"]
                st.rerun()
            if ac3.button("✅ 已掌握，移除", key=f"wb_remove_{r['answer_id']}"):
                with SessionLocal() as session:
                    hscore.remove_answer(session, r["answer_id"])
                    session.commit()
                st.session_state.pop(f"retry_pick_{r['answer_id']}", None)
                st.rerun()

            st.markdown("**原题**")
            _render_math(r["content"])
            st.markdown("**正确答案**")
            _render_math(r["answer"])
            if r["analysis"]:
                st.markdown("**解析**")
                _render_math(r["analysis"])

    selected_ids = []
    for r in rows:
        if st.session_state.get(f"retry_pick_{r['answer_id']}"):
            selected_ids.append(r["question_id"])
    selected_ids = list(dict.fromkeys(selected_ids))
    if st.button("🧾 用勾选错题生成重做卷", type="primary", key="make_retry_hw"):
        if not selected_ids:
            st.warning("请先勾选要加入重做卷的错题。")
        else:
            prepared_items = []
            for question_id in selected_ids:
                r = next(x for x in rows if x["question_id"] == question_id)
                try:
                    score = float(r.get("original_score"))
                    if score <= 0:
                        score = 10.0
                except (TypeError, ValueError):
                    score = 10.0
                prepared_items.append({
                    "question_id": question_id,
                    "题干摘要": _truncate_for_retry(r["content"]),
                    "difficulty": int(r["difficulty"]),
                    "score": score,
                })
            st.session_state["retry_preview_items"] = prepared_items
            st.rerun()


def _wrong_knowledge_groups(rows: list[dict]) -> list[dict]:
    """按知识点聚合错题；没有知识点的题归入未标注。"""
    groups = {}
    for r in rows:
        kps = r.get("knowledge_points") or ["未标注知识点"]
        for kp in kps:
            group = groups.setdefault(str(kp), {
                "count": 0, "students": set(), "samples": []})
            group["count"] += 1
            group["students"].add(r["student_name"])
            if len(group["samples"]) < 3:
                group["samples"].append(_truncate_for_retry(r["content"], 50))

    table = []
    for kp, group in sorted(
            groups.items(), key=lambda item: item[1]["count"], reverse=True):
        table.append({
            "知识点": kp,
            "错题数": group["count"],
            "涉及学生": "、".join(sorted(group["students"])),
            "题干摘要": "；".join(group["samples"]),
        })
    return table


def _wrong_knowledge_aggregation(rows: list[dict]):
    """显示知识点聚合结果。"""
    st.dataframe(
        pd.DataFrame(_wrong_knowledge_groups(rows)),
        width="stretch", hide_index=True)


def _truncate_for_retry(text: str, n: int = 40) -> str:
    text = str(text).replace("\n", " ")
    return text if len(text) <= n else text[:n] + "…"


def _clear_retry_pick_state(rows) -> None:
    """取消或生成后，清掉错题勾选、预览和编辑器状态。"""
    st.session_state.pop("retry_preview_items", None)
    st.session_state.pop("retry_question_editor", None)
    for r in rows:
        st.session_state.pop(f"retry_pick_{r['answer_id']}", None)


def _retry_preview_editor(rows, subject: str) -> None:
    """重做卷确认前的统一可编辑预览；此时尚未创建作业。"""
    items = st.session_state.get("retry_preview_items")
    if not items:
        return
    current_ids = {r["question_id"] for r in rows}
    if any(int(item["question_id"]) not in current_ids for item in items):
        _clear_retry_pick_state(rows)
        st.rerun()

    st.markdown("#### 错题重做卷预览")
    st.caption("可修改难度和分值；确认后才创建作业。修改难度会复制成新题，不改原题。")
    preview_df = pd.DataFrame([{
        "题目ID": item["question_id"],
        "题干摘要": item["题干摘要"],
        "难度": item["difficulty"],
        "分值": item["score"],
    } for item in items])
    st.data_editor(
        preview_df, hide_index=True, width="stretch",
        num_rows="fixed", key="retry_question_editor",
        column_config={
            "题目ID": None,
            "题干摘要": st.column_config.TextColumn(disabled=True),
            "难度": st.column_config.NumberColumn(
                "难度", min_value=1, max_value=3, step=1,
                help="1=基础，2=中等，3=拓展"),
            "分值": st.column_config.NumberColumn(
                "分值", min_value=0.1, step=1.0),
        })

    cc1, cc2 = st.columns(2)
    if cc1.button("✅ 确认生成重做卷", type="primary", key="confirm_retry_hw"):
        changes = st.session_state.get(
            "retry_question_editor", {}).get("edited_rows", {})
        edited_items = []
        for i, item in enumerate(items):
            prepared = dict(item)
            changed = changes.get(str(i), {})
            if "难度" in changed and changed["难度"] is not None:
                prepared["difficulty"] = int(changed["难度"])
            if "分值" in changed and changed["分值"] is not None:
                prepared["score"] = float(changed["分值"])
            edited_items.append(prepared)
        edited_ids = {int(x["question_id"]) for x in edited_items}
        selected_rows = [r for r in rows if r["question_id"] in edited_ids]
        class_names = {r["class_name"] for r in selected_rows if r["class_name"]}
        class_name = next(iter(class_names)) if len(class_names) == 1 else None
        try:
            with SessionLocal() as session:
                name = hw_svc.default_retry_homework_name(session)
                result = hw_svc.generate_retry_homework(
                    session, edited_items, name, subject,
                    class_name=class_name, duration=45)
                session.commit()
                new_id = result["homework_id"]
            _clear_retry_pick_state(rows)
            st.session_state["homework_tab"] = "作业管理"
            st.session_state["hw_open_id"] = new_id
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
    if cc2.button("取消", key="cancel_retry_hw"):
        _clear_retry_pick_state(rows)
        st.rerun()


def _add_to_next_hw_basket(question_id: int) -> None:
    """把题加入“下次作业”题篮，按 question_id 去重。"""
    basket = st.session_state.setdefault("next_hw_question_basket", [])
    if question_id not in basket:
        basket.append(question_id)


def show() -> None:
    """作业入口：5 个页内标签页。"""
    st.title("📝 学业测评")
    previous_tab = st.session_state.get("homework_tab", "作业管理")
    t1, t2, t3, t4, t5 = st.tabs(
        ["作业管理", "🤖 智能组卷", "成绩录入", "作业分析", "错题本"],
        key="homework_tab", default="作业管理")
    current_tab = st.session_state.get("homework_tab", "作业管理")
    if current_tab != previous_tab and current_tab == "作业管理":
        # 从其他 Tab 切回时关闭残留弹窗，筛选框变化不会走到这里。
        st.session_state.pop("hw_new_dialog_open", None)
    with t1:
        tab_manage()
    with t2:
        tab_smart_compose()
    with t3:
        tab_scores()
    with t4:
        tab_analysis()
    with t5:
        tab_wrong_book()
