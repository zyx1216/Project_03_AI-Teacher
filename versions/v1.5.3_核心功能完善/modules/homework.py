# -*- coding: utf-8 -*-
"""
作业页面（v0.4）。

页内 4 个标签页：
1. 作业管理：新建作业/试卷（弹窗）、混合组卷（题库勾选/AI 即时出题/外部导入/手动加题）、
   调序与分值、自动组卷（试卷）、学生卷/教师卷预览导出、存模板、删除；
2. 成绩录入：Excel 导入总分、手动录分、逐题批改（错题本数据来源）；
3. 作业分析：概览指标、分数段、排名、进退步、每题正确率、高频错题、AI 总结；
4. 错题本：自动收集的错题筛选、详情、典型错题、导出 Word。

本文件只管界面；逻辑在 utils/homework_service.py、homework_score_service.py、
homework_stats.py，统计口径复用 utils/stats.py。
"""

import re
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import config
from models.models import Question
from utils.db import SessionLocal
from utils import llm_client, feature_subjects as fs
from utils.app_config import SUBJECT_NAMES, DEFAULT_SUBJECT
from utils import stats as stats_mod
from utils import excel_handler as eh
from utils import student_service as student_svc
from utils import question_service as qs
from utils import question_importer as qi
from utils import homework_service as hw_svc
from utils import homework_score_service as hscore
from utils import homework_stats as hstat

PROMPTS_DIR = Path(config.BASE_DIR) / "prompts"

TYPE_LABELS = {"choice": "选择题", "fill": "填空题", "judge": "判断题", "solution": "解答题"}
DIFF_LABELS = {1: "基础", 2: "中等", 3: "拓展"}
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

# 弹窗里 5 种类型的单选项（emoji + 名称）
_TYPE_KEYS = ["preview", "classroom", "after_class", "review", "exam"]
_TYPE_OPTION_LABELS = {
    k: f"{hw_svc.type_emoji(k)} {hw_svc.type_label(k)}" for k in _TYPE_KEYS}


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
    """含 $...$ 的文本分段渲染：公式 st.latex，普通文本 st.write。"""
    if not text:
        st.write("—")
        return
    for part in re.split(r"(\$[^$]+\$)", text):
        if not part:
            continue
        if part.startswith("$") and part.endswith("$") and len(part) > 2:
            st.latex(part.strip("$"))
        else:
            st.write(part)


def _read_prompt(filename: str) -> str:
    return (PROMPTS_DIR / filename).read_text(encoding="utf-8")

# ---------------------------------------------------------------------------
# 新建作业 / 试卷弹窗
# ---------------------------------------------------------------------------

def _choose_new_homework_type(hw_type: str):
    """类型按钮回调（普通函数，不要加 @st.dialog，否则点类型会弹一个空窗）。"""
    st.session_state["hw_new_type"] = hw_type
    # 换一次控件 key：新类型首次渲染用自己的默认值，也避开状态冲突警告。
    st.session_state["hw_new_dialog_nonce"] = st.session_state.get(
        "hw_new_dialog_nonce", 0) + 1


@st.dialog("新建作业 / 试卷", width="large")
def _new_homework_dialog():
    """真正的弹窗内容：选类型（emoji 网格）→ 填参数 → 可选模板 → 创建。"""
    st.markdown("**选择作业类型**")
    cols = st.columns(5)
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
                    subject=dialog_subject)
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
        if st.button("➕ 新建作业 / 试卷", type="primary"):
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
    """普通作业 + 模板两个区块。题数在会话内取好，避免会话关闭后懒加载。"""
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
        fc1, fc2, fc3 = st.columns(3)
        keyword = fc1.text_input("作业名称搜索", key="homework_filter_keyword")
        type_options = [None] + list(hw_svc.HOMEWORK_TYPES.keys())
        homework_type = fc2.selectbox(
            "作业类型", type_options,
            format_func=lambda x: "全部类型" if x is None else hw_svc.type_label(x),
            key="homework_filter_type")
        class_filter = fc3.selectbox(
            "班级", ["全部班级"] + classes, key="homework_filter_class")

    with SessionLocal() as session:
        homeworks = hw_svc.list_homeworks(
            session, templates=False, subject=current_subject,
            keyword=keyword.strip() or None, homework_type=homework_type,
            class_name=None if class_filter == "全部班级" else class_filter)
        templates = hw_svc.list_homeworks(session, templates=True,
                                          subject=current_subject)
        # 在会话内物化渲染所需字段（id/名称/班级/题数/满分/时长/类型）
        items = [{
            "id": h.id, "name": h.name, "class_name": h.class_name,
            "type": h.homework_type, "n": len(h.questions),
            "total": h.total_score or 0, "duration": h.duration or 0,
        } for h in homeworks]
        tpl_items = [{
            "name": t.name, "type": t.homework_type, "n": len(t.questions)
        } for t in templates]

    # 题篮状态：错题本里“加入下次作业”的题，新建同学科作业时自动带入。
    basket = st.session_state.get("next_hw_question_basket", [])
    if basket:
        bc1, bc2 = st.columns([4, 1])
        bc1.caption(f"🧺 题篮：{len(basket)} 道题待带入新作业（仅带入同学科作业）。")
        if bc2.button("清空题篮", key="clear_basket_manage"):
            st.session_state["next_hw_question_basket"] = []
            st.rerun()

    st.markdown("**我的作业**")
    if not items:
        st.info("还没有符合条件的作业，点上方“新建作业/试卷”开始。")
    for hw in items:
        with st.container(border=True):
            c0, c1, c2, c3 = st.columns([0.5, 5.5, 1, 1])
            hid = hw["id"]
            c0.checkbox("选择", key=f"pick_hw_{hid}", label_visibility="collapsed")
            c1.markdown(
                f"{hw_svc.type_emoji(hw['type'])} **{hw['name']}**　"
                f"{hw['class_name'] or ''}　{hw['n']} 题　"
                f"满分 {hw['total']}　{hw['duration']} 分钟")
            if c2.button("打开编辑", key=f"open_{hid}"):
                st.session_state["hw_open_id"] = hid
                st.rerun()
            if c3.button("删除", key=f"del_hw_{hid}"):
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

    # 批量删除勾选的普通作业（二次确认）。
    picked_ids = [hw["id"] for hw in items
                  if st.session_state.get(f"pick_hw_{hw['id']}")]
    if picked_ids and not st.session_state.get("hw_batch_delete_pending"):
        if st.button(f"🗑️ 批量删除所选（{len(picked_ids)}）",
                     key="hw_batch_del_btn"):
            st.session_state["hw_batch_delete_pending"] = picked_ids
            st.rerun()
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
            st.caption(f"📦 {tpl['name']}（{hw_svc.type_label(tpl['type'])}，"
                       f"{tpl['n']} 题）")


def _homework_editor(homework_id: int):
    """作业编辑抽屉：加题 4 入口、调序、分值、预览导出、存模板、自动组卷。"""
    with SessionLocal() as session:
        hw = hw_svc.get_homework(session, homework_id)
        if hw is None:
            st.session_state.pop("hw_open_id", None)
            st.rerun()
            return

        st.markdown(f"### {hw_svc.type_emoji(hw.homework_type)} {hw.name}")
        if hw.homework_type == "exam":
            _auto_compose_panel(session, hw)

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
        c1, c2, c3 = st.columns(3)
        ftype = c1.selectbox("题型", [None] + list(TYPE_LABELS),
                             format_func=lambda x: "全部" if x is None else TYPE_LABELS[x],
                             key=f"bank_type_{hw.id}")
        fdiff = c2.selectbox("难度", [None, 1, 2, 3],
                             format_func=lambda x: "全部" if x is None else DIFF_LABELS[x],
                             key=f"bank_diff_{hw.id}")
        keyword = c3.text_input("知识点/题干关键词", key=f"bank_kw_{hw.id}")
        questions = qs.list_questions(session, question_type=ftype,
                                      difficulty=fdiff, status="approved",
                                      keyword=keyword.strip() or None,
                                      subject=hw.subject or DEFAULT_SUBJECT)
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
    user_text = (f"知识点：{knowledge}\n题型：{type_text}\n"
                 f"难度：{DIFF_LABELS[difficulty]}\n题目数量：恰好 {count} 道")
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


def _auto_compose_panel(session, hw):
    """试卷类型专用：按题型题量 + 难度配比一键自动组卷。"""
    with st.expander("🤖 AI 自动组卷（试卷专用）", expanded=False):
        st.caption("先从已审核题库按配比确定性抽题，题库不够的题自动调 AI 生成补齐。")
        with st.form(f"auto_compose_{hw.id}"):
            scope = st.text_input("知识点范围（逗号分隔，用于覆盖检查和补题）",
                                  placeholder="如：一元二次方程,根的判别式,韦达定理")
            ac1, ac2, ac3, ac4 = st.columns(4)
            n_choice = ac1.number_input("选择题", 0, 30, 6, key=f"ac_choice_{hw.id}")
            n_fill = ac2.number_input("填空题", 0, 30, 4, key=f"ac_fill_{hw.id}")
            n_judge = ac3.number_input("判断题", 0, 30, 0, key=f"ac_judge_{hw.id}")
            n_solution = ac4.number_input("解答题", 0, 30, 5, key=f"ac_sol_{hw.id}")
            r1, r2, r3 = st.columns(3)
            p1 = r1.slider("基础占比%", 0, 100, 30, key=f"ac_p1_{hw.id}")
            p2 = r2.slider("中等占比%", 0, 100, 50, key=f"ac_p2_{hw.id}")
            p3 = r3.slider("拓展占比%", 0, 100, 20, key=f"ac_p3_{hw.id}")
            run = st.form_submit_button("🤖 开始自动组卷", type="primary")

        if run:
            if p1 + p2 + p3 != 100:
                st.error("三种难度占比之和必须等于 100%。")
                return
            spec = {
                "counts": {"choice": n_choice, "fill": n_fill,
                           "judge": n_judge, "solution": n_solution},
                "difficulty_ratio": {1: p1, 2: p2, 3: p3},
            }
            kps = [k.strip() for k in re.split(r"[，,、;；]", scope) if k.strip()]
            with st.spinner("正在抽题并补缺……"):
                try:
                    result = hw_svc.auto_compose(session, hw.id, spec, kps)
                    session.commit()
                except Exception as exc:
                    st.error(f"自动组卷失败：{exc}")
                    return
            st.success(f"题库抽题 {result['rule_picked']} 道，"
                       f"AI 补题 {result['ai_generated']} 道，"
                       f"当前共 {result['total_questions']} 道。")
            if result["shortage_count"]:
                st.warning(f"仍有 {result['shortage_count']} 个槽位未满足，"
                           f"可手动加题或再组卷一次。")
            missing = result["coverage"]["missing"]
            if kps and missing:
                st.warning("知识点未覆盖：" + "、".join(missing))
            elif kps:
                st.success("要求的知识点都已覆盖。")
            st.rerun()

# ===========================================================================
# Tab 2：成绩录入
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
    up = st.file_uploader("选择成绩 Excel（含“姓名”列和一个分数列）", type=["xlsx"])
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


def _manual_total_scores(hw, class_name):
    """data_editor 手动录总分，保存后自动算并列排名。"""
    with SessionLocal() as session:
        rows = hscore.score_rows(session, hw.id, class_name)
    if not rows:
        st.info("该班还没有学生。可先用 Excel 导入（会自动建学生）或到学情页添加学生。")
        return
    editable = pd.DataFrame([{
        "学生": r["name"], "班级": r["class_name"] or "",
        "总分": r["score"] if r["score"] is not None else None} for r in rows])
    edited = st.data_editor(editable, num_rows="fixed", width="stretch",
                            hide_index=True, key=f"manual_total_{hw.id}")
    if st.button("💾 保存总分", type="primary", key=f"save_total_{hw.id}"):
        with SessionLocal() as session:
            for r, (_, new) in zip(rows, edited.iterrows()):
                val = new["总分"]
                score = None if pd.isna(val) else float(val)
                hscore.save_total_score(session, hw.id, r["student_id"], score)
            session.commit()
        st.success("总分已保存。")
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
    with SessionLocal() as session:
        homeworks = hw_svc.list_homeworks(session, templates=False)
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

def _render_analysis(session, hw, data):
    overall = data["overall"]
    rows = data["rows"]

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("提交率", (f"{overall['submission_rate'] * 100:.0f}%"
                        if overall["submission_rate"] is not None else "—"))
    c2.metric("已交 / 应到", f"{overall['submitted']} / {overall['total']}")
    c3.metric("平均分", overall["mean"] if overall["mean"] is not None else "—")
    c4.metric("最高分", overall["max"] if overall["max"] is not None else "—")
    c5.metric("最低分", overall["min"] if overall["min"] is not None else "—")

    # 分数段柱状（按作业满分）
    full = hw.total_score or 100
    values = [r["score"] for r in rows if r["score"] is not None]
    if values:
        bands = stats_mod.score_bands(values, full)
        fig = go.Figure(go.Bar(
            x=[b["label"] for b in bands], y=[b["count"] for b in bands],
            marker_color="#1F4E79", text=[b["count"] for b in bands]))
        fig.update_layout(title="分数段分布", height=320,
                          margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig, width="stretch")

    # 排名表（含进退步红绿）
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
    st.markdown(f"**学生排名**" + (f"（对比上一份作业：{prev_name}）" if prev_name else ""))
    st.dataframe(pd.DataFrame(table), width="stretch", hide_index=True)

    # 每题正确率
    pq = data["per_question"]
    if pq:
        st.markdown("**每题正确率**")
        qlabels, rates, judged = [], [], []
        qmap = {q.id: (i + 1, q) for i, (_l, q) in
                enumerate(hw_svc.homework_questions(session, hw.id))}
        for item in pq:
            order, q = qmap.get(item["question_id"], (item["order_no"], None))
            label = f"第{order}题"
            qlabels.append(label)
            rates.append((item["rate"] or 0) * 100 if item["rate"] is not None else None)
            judged.append(item["judged"])
        fig2 = go.Figure(go.Bar(
            x=qlabels, y=rates, marker_color="#2E8B57",
            text=[("—" if r is None else f"{r:.0f}%") for r in rates]))
        fig2.update_layout(title="每题正确率（%）", height=300, yaxis_range=[0, 100],
                           margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig2, width="stretch")

    # 高频错题 TOP5
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
    """AI 作业分析总结；未配置给明确提示，失败给友好信息。"""
    st.markdown("**AI 分析总结**")
    if not llm_client.is_configured():
        st.info("还没配置 AI：到「⚙️ 设置 → 主模型配置」填写 API Key 后可生成分析。")
        return
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
                reply = llm_client.chat(system_prompt, payload, temperature=0.5)
                st.markdown(reply)
            except (llm_client.LLMConfigError, llm_client.LLMCallError) as exc:
                st.error(f"生成失败：{exc}")


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
    st.subheader("错题本")
    current_subject = _subject_selectbox(fs.WRONG_BOOK_SUBJECT)
    with SessionLocal() as session:
        classes = student_svc.list_classes(session)
        students = student_svc.list_students(session)
        homeworks = hw_svc.list_homeworks(
            session, templates=False, subject=current_subject)

    c1, c2, c3, c4 = st.columns(4)
    stu = c1.selectbox(
        "学生", [None] + students,
        format_func=lambda s: "全部学生" if s is None else f"{s.name}（{s.class_name or '未分班'}）",
        key="wb_student")
    hw = c2.selectbox(
        "作业", [None] + homeworks,
        format_func=lambda h: "全部作业" if h is None else h.name, key="wb_hw")
    err = c3.selectbox("错误类型", [None] + hscore.ERROR_TYPES,
                       format_func=lambda x: "全部类型" if x is None else x,
                       key="wb_err")
    keyword = c4.text_input("知识点/题干关键词", key="wb_kw")

    with SessionLocal() as session:
        rows = hscore.list_wrong_answers(
            session,
            student_id=stu.id if stu is not None else None,
            homework_id=hw.id if hw is not None else None,
            error_type=err, knowledge_keyword=keyword.strip() or None,
            subject=current_subject)

    st.caption(f"共 {len(rows)} 道错题（典型错题按全班错误率自动置顶）")
    if not rows:
        st.info("还没有错题。先到“成绩录入 → 逐题批改”判错，错题会自动收集到这里。")
        return

    # 题篮：错题本勾选的题会在新建同学科作业时自动带入。
    basket = st.session_state.setdefault("next_hw_question_basket", [])
    bc1, bc2 = st.columns([4, 1])
    bc1.caption(f"🧺 题篮：{len(basket)} 道题待带入新作业（仅同学科作业）。")
    if bc2.button("清空题篮", key="clear_basket_wrongbook", disabled=not basket):
        st.session_state["next_hw_question_basket"] = []
        st.rerun()

    _retry_preview_editor(rows, current_subject)

    if st.button("📄 导出错题本 Word", key="wb_export"):
        data = hscore.export_wrong_word(rows, title=f"{current_subject}错题本")
        st.download_button("⬇️ 下载错题本", data, file_name=f"{current_subject}错题本.docx",
                           mime=DOCX_MIME, key="wb_export_dl")

    for r in rows:
        tag = "　🔥 典型错题" if r["typical"] else ""
        with st.expander(
                f"{r['student_name']}｜{r['homework_name']}｜第{r['order_no'] or '?'}题"
                f"{tag}｜{r['error_type'] or '未分类'}"):
            st.checkbox("➕ 加入错题重做卷",
                        key=f"retry_pick_{r['answer_id']}")
            st.caption(f"知识点：{'、'.join(r['knowledge_points']) or '—'}　"
                       f"题型：{TYPE_LABELS.get(r['question_type'], r['question_type'])}　"
                       f"本题得分：{r['earned_score'] if r['earned_score'] is not None else '未录'}")
            ac1, ac2 = st.columns(2)
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
            st.markdown("**原题**")
            _render_math(r["content"])
            st.markdown("**正确答案**")
            _render_math(r["answer"])
            if r["analysis"]:
                st.markdown("**解析**")
                _render_math(r["analysis"])

    selected_ids = []
    for r in rows:
        pick_key = f"retry_pick_{r['answer_id']}"
        if st.session_state.get(pick_key):
            selected_ids.append(r["question_id"])
    selected_ids = list(dict.fromkeys(selected_ids))
    if st.button("🧾 用勾选错题生成重做卷", type="primary", key="make_retry_hw"):
        if not selected_ids:
            st.warning("请先勾选要加入重做卷的错题。")
        else:
            items = []
            for question_id in selected_ids:
                r = next(x for x in rows if x["question_id"] == question_id)
                original_score = r.get("original_score")
                try:
                    score = float(original_score)
                    if score <= 0:
                        score = 10.0
                except (TypeError, ValueError):
                    score = 10.0
                items.append({
                    "question_id": question_id,
                    "题干摘要": _truncate_for_retry(r["content"]),
                    "difficulty": int(r["difficulty"]),
                    "score": score,
                })
            st.session_state["retry_preview_items"] = items
            st.rerun()


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
    edited_df = st.data_editor(
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
        # st.data_editor 的固定 key 保存“按行号记录的改动”，原始 items 保存完整行。
        # 按行号合并，避免依赖隐藏列，也能覆盖 AppTest 注入的编辑态。
        changes = st.session_state.get("retry_question_editor", {}).get("edited_rows", {})
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
    """作业入口：4 个页内标签页。"""
    st.title("📝 作业")
    t1, t2, t3, t4 = st.tabs(
        ["作业管理", "成绩录入", "作业分析", "错题本"],
        key="homework_tab", default="作业管理")
    with t1:
        tab_manage()
    with t2:
        tab_scores()
    with t3:
        tab_analysis()
    with t4:
        tab_wrong_book()
