# -*- coding: utf-8 -*-
"""
学情页面。

顶部 7 个标签页：学生管理 / 成绩管理 / 考试分析 / 趋势分析 / 学生画像 /
教学反思 / 期末评语。
本文件只负责界面与交互；统计口径在 utils/stats.py，数据库读写在
utils/student_service.py、utils/exam_service.py，Excel 识别在 utils/excel_handler.py。
"""

import json
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from utils.db import SessionLocal
from utils import excel_handler as eh
from utils import score_doc_parser as sdp
from utils import exam_service as es
from utils import stats as stats_mod
from utils import student_service as ss
from utils import llm_client
from utils.app_config import DEFAULT_SUBJECT
from utils import reflection_service as rs
from utils import comment_service as cs


# ---------------------------------------------------------------------------
# 通用小工具
# ---------------------------------------------------------------------------

def _read_excel_sheet(uploaded, sheet_name):
    """读取上传文件对象的指定工作表，回到开头以便重复读取。"""
    uploaded.seek(0)
    return eh.load_dataframe(uploaded, sheet_name=sheet_name)


def _download_xlsx(df: pd.DataFrame, filename: str, label: str = "下载 Excel"):
    """把 DataFrame 做成 Excel 下载按钮。"""
    from io import BytesIO
    buffer = BytesIO()
    df.to_excel(buffer, index=False, engine="openpyxl")
    st.download_button(label, buffer.getvalue(), file_name=filename,
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def _ai_button(prompt_kind: str, build_data_text, button_label: str, help_text: str):
    """
    通用 AI 总结按钮：未配置时提示去设置页；调用失败给友好信息。
    prompt_kind: 'exam' 或 'student'，决定用哪个提示词模板。
    build_data_text: 无参函数，返回注入给模型的数据文本。
    """
    if not llm_client.is_configured():
        st.info("还没配置 AI：请到「⚙️ 设置 → LLM 配置」填写 API Key 后再来。")
        return
    if st.button(button_label, help=help_text):
        import time
        from pathlib import Path
        import config
        prompt_file = {
            "exam": "exam_analysis_prompt.txt",
            "student": "student_profile_prompt.txt",
        }[prompt_kind]
        system_prompt = (Path(config.BASE_DIR) / "prompts" / prompt_file).read_text(encoding="utf-8")
        # 提示词模板里 {data} 是占位符，数据作为用户消息单独传入更安全（不做字符串拼接注入系统提示）
        system_prompt = system_prompt.replace("{data}", "").strip()
        with st.spinner("AI 正在分析，请稍候……"):
            try:
                reply = llm_client.chat(system_prompt, build_data_text(), temperature=0.5)
                st.markdown(reply)
            except llm_client.LLMConfigError as exc:
                st.warning(str(exc))
            except llm_client.LLMCallError as exc:
                st.error(str(exc))


# ---------------------------------------------------------------------------
# 标签页 1：学生管理
# ---------------------------------------------------------------------------

def tab_students():
    """学生名单：Excel 导入、手动添加、筛选搜索、编辑删除。"""
    st.subheader("学生管理")

    with st.expander("📥 从 Excel 导入学生名单", expanded=False):
        _student_import_panel()

    with st.expander("➕ 手动添加学生", expanded=False):
        _student_add_panel()

    st.divider()
    _student_list_panel()


def _student_import_panel():
    """上传名单 → 识别列 → 预览（标问题行）→ 确认入库。"""
    uploaded = st.file_uploader("选择学生名单 Excel（需含“姓名”列）",
                                type=["xlsx", "xls"], key="student_upload")
    if uploaded is None:
        st.caption("支持的列：姓名（必填）、学号、班级、性别、备注，表头叫法不同也能自动识别。")
        return

    try:
        sheets = eh.list_sheets(uploaded)
    except Exception as exc:
        st.error(f"读不了这个文件：{exc}")
        return
    sheet = st.selectbox("选择工作表", sheets, key="student_sheet") if len(sheets) > 1 else sheets[0]

    try:
        df = _read_excel_sheet(uploaded, sheet)
        detected = eh.detect_student_columns(df)
    except Exception as exc:
        st.error(f"解析表格出错：{exc}")
        return

    if detected["problems"]:
        st.error("　".join(detected["problems"]))
        return

    records = eh.extract_students(df, detected["mapping"])
    if not records:
        st.warning("表里没有有效学生行。")
        return

    preview = pd.DataFrame([{
        "Excel行号": r["row_no"], "姓名": r["name"], "学号": r["student_no"],
        "班级": r["class_name"], "性别": r["gender"], "备注": r["remark"],
        "问题": "、".join(r["problems"]),
    } for r in records])

    problem_rows = preview[preview["问题"] != ""]
    if len(problem_rows):
        st.warning(f"有 {len(problem_rows)} 行存在问题（导入时会被跳过），已在下表红色标出。")

    st.dataframe(
        preview.style.apply(
            lambda row: ["background-color:#ffe0e0"] * len(row) if row["问题"] else [""] * len(row),
            axis=1),
        width="stretch", hide_index=True)

    valid = len(records) - len(problem_rows)
    if st.button("✅ 确认导入", type="primary", key="confirm_students"):
        with SessionLocal() as session:
            result = ss.bulk_import_students(session, records)
            session.commit()
        st.success(f"导入完成：新增 {result['created']} 人，更新 {result['updated']} 人，"
                   f"跳过 {result['skipped']} 行。")
        st.cache_data.clear()
        st.rerun()


def _student_add_panel():
    """表单：手动添加单个学生。"""
    with st.form("add_student_form", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        name = c1.text_input("姓名 *")
        student_no = c2.text_input("学号")
        class_name = c3.text_input("班级")
        c4, c5 = st.columns(2)
        gender = c4.selectbox("性别", ["", "男", "女"])
        remark = c5.text_input("备注")
        submitted = st.form_submit_button("添加")
    if submitted:
        if not name.strip():
            st.error("姓名必填。")
            return
        with SessionLocal() as session:
            exists = ss.find_student(session, name.strip(), class_name.strip() or None)
            if exists:
                st.warning("这个姓名+班级已经存在，没有重复添加。")
                return
            from models.models import Student
            session.add(Student(
                name=name.strip(), student_no=student_no.strip() or None,
                class_name=class_name.strip() or None,
                gender=gender or None, remark=remark.strip() or None))
            session.commit()
        st.success(f"已添加学生：{name.strip()}")
        st.rerun()


def _student_list_panel():
    """学生表格：可直接编辑、动态新增；删除需二次确认。"""
    with SessionLocal() as session:
        classes = ss.list_classes(session)

    c1, c2 = st.columns(2)
    class_filter = c1.selectbox("按班级筛选", ["全部"] + classes)
    keyword = c2.text_input("搜索姓名或学号")

    # 表格 key 固定，筛选/搜索变化时不主动 pop key，避免组件重建引发表格 DOM 冲突。
    # data_editor 会自然合并新数据到已有状态中。
    with SessionLocal() as session:
        students = ss.list_students(
            session,
            class_name=None if class_filter == "全部" else class_filter,
            keyword=keyword.strip() or None)
        existing_ids = {s.id for s in students}
        initial_df = pd.DataFrame([{
            "学生ID": s.id,
            "姓名": s.name,
            "学号": s.student_no or "",
            "班级": s.class_name or "",
            "性别": s.gender if s.gender in ("男", "女") else None,
            "标签": s.tags or "",
            "备注": s.remark or "",
        } for s in students])

    st.caption(f"共 {len(students)} 名学生。可直接改表格，也可用最后一行新增学生。")
    if initial_df.empty:
        initial_df = pd.DataFrame({
            "学生ID": pd.Series(dtype="int64"),
            "姓名": pd.Series(dtype="object"),
            "学号": pd.Series(dtype="object"),
            "班级": pd.Series(dtype="object"),
            "性别": pd.Series(dtype="object"),
            "标签": pd.Series(dtype="object"),
            "备注": pd.Series(dtype="object"),
        })

    edited_df = st.data_editor(
        initial_df,
        num_rows="fixed",
        hide_index=True,
        key="student_editor_main",
        column_order=["姓名", "学号", "班级", "性别", "标签", "备注"],
        column_config={
            "学生ID": None,
            "姓名": st.column_config.TextColumn("姓名", required=True, width="medium"),
            "学号": st.column_config.TextColumn("学号"),
            "班级": st.column_config.TextColumn("班级"),
            "性别": st.column_config.TextColumn(
                "性别", help="输入男或女"),
            "标签": st.column_config.TextColumn("标签", help="多个标签可用逗号分隔"),
            "备注": st.column_config.TextColumn("备注"),
        },
        height=min(420, 80 + max(5, len(initial_df)) * 36),
    )

    rows = edited_df.where(pd.notna(edited_df), None).to_dict("records")
    retained_ids = {int(r["学生ID"]) for r in rows if r.get("学生ID") is not None}
    deleted_ids = existing_ids - retained_ids

    c_save, c_tip = st.columns([1, 3])
    if c_save.button("💾 保存表格修改", type="primary"):
        if deleted_ids:
            st.session_state["student_delete_pending"] = deleted_ids
        else:
            st.session_state["student_save_pending"] = True
    c_tip.caption("删除行会删除该学生及其成绩；保存时会要求二次确认。")

    if st.session_state.get("student_delete_pending"):
        pending_ids = set(st.session_state["student_delete_pending"])
        st.error(f"本次将删除 {len(pending_ids)} 名学生，其成绩和评语也会级联删除。确定继续吗？")
        cc1, cc2 = st.columns(2)
        if cc1.button("✅ 确认保存并删除", type="primary"):
            try:
                with SessionLocal() as save_session:
                    result = ss.sync_students(
                        save_session, rows, pending_ids | retained_ids)
                    save_session.commit()
                st.session_state.pop("student_delete_pending", None)
                st.session_state["student_editor_version"] = st.session_state.get(
                    "student_editor_version", 0) + 1
                st.success(
                    f"已保存：新增 {result['created']} 人，更新 {result['updated']} 人，"
                    f"删除 {result['deleted']} 人。")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
        if cc2.button("取消"):
            st.session_state.pop("student_delete_pending", None)
            st.rerun()
    elif st.session_state.get("student_save_pending"):
        try:
            with SessionLocal() as save_session:
                result = ss.sync_students(save_session, rows, existing_ids)
                save_session.commit()
            st.session_state.pop("student_save_pending", None)
            st.session_state["student_editor_version"] = st.session_state.get(
                "student_editor_version", 0) + 1
            st.success(
                f"已保存：新增 {result['created']} 人，更新 {result['updated']} 人。")
            st.rerun()
        except ValueError as exc:
            st.session_state.pop("student_save_pending", None)
            st.error(str(exc))


# ---------------------------------------------------------------------------
# 标签页 2：成绩管理
# ---------------------------------------------------------------------------

def tab_scores():
    """考试信息管理 + 成绩导入/手动录入/导出。"""
    st.subheader("成绩管理")

    with st.expander("🗂️ 考试管理（新建 / 修改满分 / 删除）", expanded=False):
        _exam_manage_panel()

    with st.expander("📥 从 Excel / Word / PDF 导入成绩", expanded=False):
        _score_import_panel()

    with st.expander("⌨️ 手动录入 / 修正成绩", expanded=False):
        _score_manual_panel()

    st.divider()
    _score_export_panel()


def _clear_new_exam_dialog_state():
    """关闭新建考试弹窗后清掉逐行满分等控件状态，避免下次打开读到旧值。"""
    st.session_state.pop("exam_dialog_open", None)
    st.session_state.pop("new_exam_full_rows", None)
    for key in ("new_exam_name", "new_exam_date", "new_exam_grade", "new_exam_term"):
        st.session_state.pop(key, None)
    for key in list(st.session_state.keys()):
        if (key.startswith("full_subject_new_exam_") or
                key.startswith("full_score_new_exam_") or
                key.startswith("full_delete_new_exam_")):
            st.session_state.pop(key, None)

@st.dialog("新建考试", width="large")
def _new_exam_dialog():
    """弹窗新建考试：名称/日期/年级/学期/逐行设置各科满分。"""
    rows_key = "new_exam_full_rows"
    if rows_key not in st.session_state:
        st.session_state[rows_key] = [
            {"rid": 1, "subject": DEFAULT_SUBJECT, "score": 100.0}
        ]

    with st.form("create_exam_form"):
        c1, c2, c3, c4 = st.columns(4)
        name = c1.text_input("考试名称 *", placeholder="如：八年级上册期中",
                             key="new_exam_name")
        exam_date = c2.date_input("考试日期", value=date.today(), key="new_exam_date")
        grade = c3.text_input("年级", value="八年级", key="new_exam_grade")
        term = c4.text_input("学期", placeholder="如：2026 上", key="new_exam_term")

        st.markdown("**学科满分设置**")
        rows = st.session_state[rows_key]
        _render_full_score_rows("new_exam", rows, rows_key)
        st.form_submit_button(
            "➕ 添加学科", on_click=_add_full_score_row,
            args=(rows_key, "new_exam"))
        cc1, cc2 = st.columns(2)
        submitted = cc1.form_submit_button("创建", type="primary")
        cancelled = cc2.form_submit_button("取消")

    if submitted:
        _sync_full_score_rows("new_exam", rows)
        if not name.strip():
            st.error("考试名称必填。")
            return
        try:
            full_scores = es.rows_to_full_scores(rows)
        except ValueError as exc:
            st.error(str(exc))
            return
        with SessionLocal() as session:
            es.create_exam(session, name, exam_date=exam_date,
                           grade=grade.strip() or None,
                           term=term.strip() or None,
                           full_scores=full_scores)
            session.commit()
        _clear_new_exam_dialog_state()
        st.success(f"已新建考试：{name.strip()}")
        st.rerun()
    if cancelled:
        _clear_new_exam_dialog_state()
        st.rerun()


def _add_full_score_row(rows_key: str, scope: str):
    """表单回调：先同步当前输入，再追加一空行，供本次提交后的重跑直接渲染。"""
    rows = st.session_state.get(rows_key, [])
    _sync_full_score_rows(scope, rows)
    next_rid = max((r["rid"] for r in rows), default=0) + 1
    rows.append({"rid": next_rid, "subject": "", "score": 100.0})
    st.session_state[rows_key] = rows


def _delete_full_score_row(rows_key: str, scope: str, rid: int):
    """表单回调：先同步其他输入，再删除指定行。"""
    rows = st.session_state.get(rows_key, [])
    _sync_full_score_rows(scope, rows)
    st.session_state[rows_key] = [r for r in rows if r["rid"] != rid]


def _render_full_score_rows(scope: str, rows: list[dict], rows_key: str) -> None:
    """渲染“学科 + 满分 + 删除”逐行编辑器。"""
    if rows:
        h1, h2, h3 = st.columns([3, 2, 1])
        h1.caption("学科")
        h2.caption("满分")
        h3.caption("删除")
    for row in rows:
        rid = row["rid"]
        c1, c2, c3 = st.columns([3, 2, 1])
        c1.text_input("学科", value=row.get("subject") or "",
                      placeholder="如：数学", key=f"full_subject_{scope}_{rid}",
                      label_visibility="collapsed")
        c2.number_input("满分", min_value=1.0, value=float(row.get("score") or 100.0),
                        step=10.0, key=f"full_score_{scope}_{rid}",
                        label_visibility="collapsed")
        c3.form_submit_button(
            "🗑️", key=f"full_delete_{scope}_{rid}", help="删除这一学科",
            on_click=_delete_full_score_row, args=(rows_key, scope, rid))
    if not rows:
        st.caption("还没有学科，点下方按钮添加。")


def _sync_full_score_rows(scope: str, rows: list[dict]) -> None:
    """把当前控件值同步回 session_state 中的行数据。"""
    for row in rows:
        rid = row["rid"]
        subject_key = f"full_subject_{scope}_{rid}"
        score_key = f"full_score_{scope}_{rid}"
        if subject_key in st.session_state:
            row["subject"] = str(st.session_state[subject_key] or "").strip()
        if score_key in st.session_state:
            row["score"] = st.session_state[score_key]


def _initial_exam_full_rows(exam, subjects: list[str]) -> list[dict]:
    """旧 JSON 满分配置和已录成绩科目取并集，逐行回显。"""
    try:
        saved = json.loads(exam.full_scores) if exam.full_scores else {}
    except (TypeError, ValueError):
        saved = {}
    subject_names = sorted(set(saved) | set(subjects))
    if not subject_names:
        subject_names = [DEFAULT_SUBJECT]
    return [
        {"rid": idx, "subject": name, "score": float(saved.get(name, 100.0))}
        for idx, name in enumerate(subject_names, start=1)
    ]


def _exam_manage_panel():
    """新建考试（弹窗）、逐行修改各科满分、删除考试。"""
    with SessionLocal() as session:
        exams = es.list_exams(session)
        exam_options = {f"{e.name}（{e.exam_date}）": e.id for e in exams}

    if st.button("➕ 新建考试", type="primary"):
        _clear_new_exam_dialog_state()
        st.session_state["exam_dialog_open"] = True
    # 弹窗内添加/删除学科会 rerun，必须靠持久状态继续挂载弹窗。
    if st.session_state.get("exam_dialog_open"):
        _new_exam_dialog()

    st.divider()
    if not exam_options:
        st.caption("还没有考试，先在上面新建一场。")
        return

    st.markdown("**已有考试 / 修改满分 / 删除**")
    chosen_label = st.selectbox("选择考试", list(exam_options.keys()),
                                key="exam_manage_pick")
    eid = exam_options[chosen_label]
    rows_key = f"exam_full_rows_{eid}"

    with SessionLocal() as session:
        exam = es.get_exam(session, eid)
        subjects = es.exam_subjects(session, eid)
        st.caption(f"已录科目：{('、'.join(subjects)) or '（暂无成绩）'}")
        base_rows = _initial_exam_full_rows(exam, subjects)
        if rows_key not in st.session_state:
            st.session_state[rows_key] = base_rows
        else:
            known_subjects = {r.get("subject") for r in st.session_state[rows_key]}
            next_rid = max((r["rid"] for r in st.session_state[rows_key]), default=0) + 1
            for row in base_rows:
                if row["subject"] not in known_subjects:
                    row["rid"] = next_rid
                    next_rid += 1
                    st.session_state[rows_key].append(row)

        with st.form(f"edit_full_scores_{eid}"):
            st.markdown("**学科满分设置**")
            rows = st.session_state[rows_key]
            _render_full_score_rows(f"exam_{eid}", rows, rows_key)
            st.form_submit_button(
                "➕ 添加学科", on_click=_add_full_score_row,
                args=(rows_key, f"exam_{eid}"))
            cc1, cc2 = st.columns(2)
            save_clicked = cc1.form_submit_button("💾 保存满分")
            del_clicked = cc2.form_submit_button("🗑️ 删除该考试（含全部成绩）")

        if save_clicked:
            _sync_full_score_rows(f"exam_{eid}", rows)
            try:
                parsed = es.rows_to_full_scores(rows)
            except ValueError as exc:
                st.error(str(exc))
            else:
                es.update_exam(session, eid, full_scores=parsed)
                session.commit()
                st.success("满分已更新。")
                st.rerun()
        if del_clicked:
            st.session_state["confirm_delete_exam"] = eid

    if st.session_state.get("confirm_delete_exam"):
        st.error("删除考试会连带删除这场考试的全部成绩，确定吗？")
        d1, d2 = st.columns(2)
        if d1.button("✅ 确认删除", type="primary", key="exam_del_ok"):
            with SessionLocal() as session:
                es.delete_exam(session, st.session_state["confirm_delete_exam"])
                session.commit()
            st.session_state.pop("confirm_delete_exam", None)
            st.success("已删除。")
            st.rerun()
        if d2.button("取消", key="exam_del_cancel"):
            st.session_state.pop("confirm_delete_exam", None)
            st.rerun()


def _parse_uploaded_scores(uploaded) -> tuple[pd.DataFrame | None, str]:
    """按扩展名把上传文件解析成成绩 DataFrame；返回 (df, 来源提示)。

    无法识别的 PDF 版式返回 (None, 提示语)；其它解析失败抛异常由调用方提示。
    """
    name = (uploaded.name or "").lower()
    if name.endswith((".xlsx", ".xls")):
        sheets = eh.list_sheets(uploaded)
        if len(sheets) > 1:
            sheet = st.selectbox("选择工作表", sheets, key="score_sheet")
        else:
            sheet = sheets[0]
        return _read_excel_sheet(uploaded, sheet), "excel"
    if name.endswith(".docx"):
        df = sdp.docx_score_dataframe(uploaded)
        if df is None:
            return None, "Word 里没有识别到成绩表格（需要含“姓名”列和数字分数列的表格）。"
        return df, "docx"
    if name.endswith(".pdf"):
        df = sdp.pdf_score_dataframe(uploaded)
        if df is None:
            return None, "PDF 格式较复杂，请尝试复制到 Excel 后导入，或改用 Word/Excel。"
        return df, "pdf"
    return None, "不支持的文件格式，请上传 .xlsx/.xls/.pdf/.docx。"


def _score_import_panel():
    """选考试 → 上传 Excel/Word/PDF → 识别科目 → 可编辑预览 → 确认入库。"""
    with SessionLocal() as session:
        exams = es.list_exams(session)
    if not exams:
        st.info("请先在上方“考试管理”里新建一场考试，再导入成绩。")
        return
    options = {f"{e.name}（{e.exam_date}）": e.id for e in exams}
    chosen = st.selectbox("导入到哪场考试", list(options.keys()), key="score_import_exam")
    exam_id = options[chosen]

    # 确认导入后会立刻 rerun，当帧 success 会被冲掉；用 session_state 保留下一次渲染的提示。
    last_import = st.session_state.pop("score_last_import", None)
    if last_import:
        st.success(last_import)

    uploaded = st.file_uploader(
        "选择成绩文件（Excel / Word / PDF，需含“姓名”列，其余数字列按科目识别）",
        type=["xlsx", "xls", "pdf", "docx"], key="score_upload")
    if uploaded is None:
        st.caption("数字列名就是科目，如“数学”或“数学成绩”；空格按缺考处理，不覆盖已有分数。")
        return

    try:
        df, source = _parse_uploaded_scores(uploaded)
    except Exception as exc:
        st.error(f"解析出错：{exc}")
        return

    if df is None:
        st.info(source)
        return
    if source in ("docx", "pdf"):
        st.info("请核对识别结果，如有错误请直接在下方表格修改后再导入。")

    detected = eh.detect_score_columns(df)
    if detected["problems"]:
        st.error("　".join(detected["problems"]))
        return

    st.success(f"识别到姓名列「{detected['name_col']}」，科目："
               + "、".join(s for _, s in detected["subjects"]))
    records = eh.extract_scores(df, detected)
    if not records:
        st.warning("没有有效成绩行。")
        return

    preview, subject_cols = eh.scores_preview_frame(records)
    problem_count = int((preview["问题"] != "").sum())
    if problem_count:
        st.warning(f"有 {problem_count} 行提示问题（缺姓名会跳过；缺考科目不计分），请核对。")

    # 可编辑预览：行号和问题列只读，姓名/班级/各科分数可改，允许临时增删行
    edited = st.data_editor(
        preview, num_rows="dynamic", width="stretch", hide_index=True,
        key="score_preview_editor",
        column_config={
            "Excel行号": st.column_config.NumberColumn(disabled=True),
            "问题": st.column_config.TextColumn(disabled=True),
        })

    if st.button("✅ 确认导入成绩", type="primary", key="confirm_scores"):
        final_records = eh.preview_to_records(edited, subject_cols)
        with SessionLocal() as session:
            result = es.import_scores(session, exam_id, final_records)
            session.commit()
        st.session_state["score_last_import"] = (
            f"导入完成：自动新建学生 {result['created_students']} 人，"
            f"新写入成绩 {result['scores_written']} 条，"
            f"更新已有成绩 {result['scores_updated']} 条，"
            f"跳过 {result['skipped_rows']} 行。")
        st.rerun()


def _score_manual_panel():
    """选考试和班级，用可编辑表格手动录入/修正各科分数。"""
    with SessionLocal() as session:
        exams = es.list_exams(session)
        classes = ss.list_classes(session)
    if not exams:
        st.info("还没有考试。")
        return
    exam_options = {f"{e.name}（{e.exam_date}）": e.id for e in exams}
    c1, c2 = st.columns(2)
    chosen = c1.selectbox("考试", list(exam_options.keys()), key="manual_exam")
    class_filter = c2.selectbox("班级", ["全部"] + classes, key="manual_class")
    exam_id = exam_options[chosen]

    if st.button("载入录入表", key="manual_load"):
        st.session_state["manual_loaded"] = (exam_id, class_filter)

    loaded = st.session_state.get("manual_loaded")
    if not loaded or loaded[0] != exam_id:
        st.caption("选好考试和班级后点“载入录入表”。")
        return

    with SessionLocal() as session:
        subjects = es.exam_subjects(session, exam_id)
        rows = es.exam_score_rows(session, exam_id)
        if class_filter != "全部":
            rows = [r for r in rows if r["class_name"] == class_filter]
        if not subjects:
            st.warning("这场考试还没有任何科目成绩，请先导入一次成绩（哪怕只有一列）。")
            return
        editable = pd.DataFrame([{
            "学生ID": r["student_id"], "姓名": r["name"],
            **{s: r[s] for s in subjects},
        } for r in rows])

    st.caption("直接改表格里的分数，改完点下方“保存”。空格表示缺考，不会清除已有分数。")
    edited = st.data_editor(editable, num_rows="fixed", width="stretch",
                            hide_index=True, key="manual_editor")

    if st.button("💾 保存修改", type="primary", key="manual_save"):
        records = []
        for _, row in edited.iterrows():
            scores = {}
            for s in subjects:
                v = row[s]
                if pd.isna(v) or v == "":
                    scores[s] = None
                else:
                    try:
                        scores[s] = float(v)
                    except (TypeError, ValueError):
                        scores[s] = None
            records.append({"name": row["姓名"],
                            "class_name": class_filter if class_filter != "全部" else None,
                            "scores": scores})
        with SessionLocal() as session:
            result = es.import_scores(session, exam_id, records)
            session.commit()
        st.success(f"已保存：新写入 {result['scores_written']} 条，更新 {result['scores_updated']} 条。")
        st.rerun()


def _score_export_panel():
    """把某场考试的宽表（含总分、班名）导出成 Excel。"""
    with SessionLocal() as session:
        exams = es.list_exams(session)
    if not exams:
        st.caption("暂无考试数据可导出。")
        return
    options = {f"{e.name}（{e.exam_date}）": e.id for e in exams}
    c1, c2 = st.columns([2, 1])
    chosen = c1.selectbox("选择要导出的考试", list(options.keys()), key="export_exam")
    if c2.button("生成导出表", type="primary"):
        with SessionLocal() as session:
            analysis = es.analyze_exam(session, options[chosen])
        df = pd.DataFrame([{
            "班级": r["class_name"] or "", "姓名": r["name"],
            **{s: r[s] for s in analysis["subjects"]},
            "总分": r["total"], "班级总分排名": r["total_rank"],
        } for r in analysis["rows"]])
        st.dataframe(df, width="stretch", hide_index=True)
        _download_xlsx(df, f"成绩_{chosen.split('（')[0]}.xlsx", label="⬇️ 导出 Excel")
# ---------------------------------------------------------------------------
# 标签页 3：单次考试分析
# ---------------------------------------------------------------------------

def tab_exam_analysis():
    """选考试和班级，展示指标、图表、排名（含进退步）、AI 总结。"""
    st.subheader("单次考试分析")

    with SessionLocal() as session:
        exams = es.list_exams(session)
        classes = ss.list_classes(session)
    if not exams:
        st.info("还没有考试和成绩，先到「成绩管理」导入。")
        return

    exam_options = {f"{e.name}（{e.exam_date}）": e.id for e in exams}
    c1, c2, c3 = st.columns([2, 1, 1])
    chosen = c1.selectbox("选择考试", list(exam_options.keys()), key="analysis_exam")
    class_filter = c2.selectbox("班级", ["全部"] + classes, key="analysis_class")
    exam_id = exam_options[chosen]

    # 分析视角：总分总览 + 本场已录科目；默认总分总览
    with SessionLocal() as session:
        view_subjects = es.exam_subjects(session, exam_id)
    view_options = ["总分总览"] + view_subjects
    view = c3.selectbox("分析视角", view_options, index=0,
                        key="analysis_view")

    class_arg = None if class_filter == "全部" else class_filter
    with SessionLocal() as session:
        if view == "总分总览":
            data = es.analyze_exam(session, exam_id, class_name=class_arg)
        else:
            data = es.analyze_subject(session, exam_id, view,
                                      class_name=class_arg)
    if not data or not data["rows"]:
        st.warning("这场考试还没有成绩数据。")
        return

    if view == "总分总览":
        _render_metric_cards(data)
        st.divider()
        _render_band_and_subject_charts(data)
        st.divider()
        _render_rank_table(data)
        st.divider()
        _render_ai_exam_summary(data, class_filter)
    else:
        _render_subject_view(data)


def rank_chart_data(rows: list[dict], key: str) -> tuple[list[str], list[float]]:
    """从已排名的行里取 (姓名, 分数)，按分数升序——横向条形图最高分显示在最上方。

    缺分(None)的学生不进图；同名时加班级后缀以区分。
    """
    pairs = []
    for r in rows:
        value = r.get(key)
        if value is None:
            continue
        label = r.get("name") or ""
        if r.get("class_name"):
            label = f"{label}（{r['class_name']}）"
        pairs.append((label, float(value)))
    pairs.sort(key=lambda x: x[1])
    names = [x[0] for x in pairs]
    values = [x[1] for x in pairs]
    return names, values


def _render_band_chart(bands, subject_label):
    """分数段分布：柱状图（默认）/ 饼图切换。"""
    labels = [b["label"] for b in bands]
    counts = [b["count"] for b in bands]
    chart_type = st.radio(
        "分数段图类型", ["柱状图", "饼图"], horizontal=True,
        key=f"band_chart_type_{subject_label}")
    if chart_type == "饼图":
        pie = [(lab, c) for lab, c in zip(labels, counts) if c > 0]
        fig = go.Figure(go.Pie(
            labels=[x[0] for x in pie], values=[x[1] for x in pie],
            textinfo="label+percent", hole=0.35))
        fig.update_layout(
            height=360, margin=dict(l=10, r=10, t=30, b=10),
            title=f"{subject_label}分数段占比", showlegend=True)
    else:
        fig = go.Figure(go.Bar(
            x=labels, y=counts, text=counts, marker_color="#4c78a8"))
        fig.update_layout(
            height=320, margin=dict(l=10, r=10, t=30, b=10),
            title=f"{subject_label}分数段分布",
            xaxis_title="分数段", yaxis_title="人数", showlegend=False)
    st.plotly_chart(fig, width="stretch")


def _render_rank_bar_chart(rows, key, title, x_axis_title):
    """学生排名横向条形图：y=姓名、x=分数，最高分在最上。"""
    names, values = rank_chart_data(rows, key)
    if not names:
        st.caption("暂无可绘制的分数。")
        return
    fig = go.Figure(go.Bar(
        y=names, x=values, orientation="h", text=values,
        marker_color="#1F4E79"))
    fig.update_layout(
        height=max(320, 26 * len(names) + 120),
        margin=dict(l=10, r=10, t=40, b=10),
        title=title, xaxis_title=x_axis_title, yaxis_title="学生",
        yaxis=dict(autorange="reversed"), showlegend=False)
    st.plotly_chart(fig, width="stretch")


def _fmt_pct(rate):
    """0.8276 -> '82.8%'；None -> '—'。"""
    return "—" if rate is None else f"{rate * 100:.1f}%"


def _render_metric_cards(data):
    """总分维度的关键指标卡片。"""
    t = data["total_stats"]
    cols = st.columns(6)
    cols[0].metric("参考人数", t["count"])
    cols[1].metric("平均分", "—" if t["mean"] is None else f"{t['mean']:g}")
    cols[2].metric("中位数", "—" if t["median"] is None else f"{t['median']:g}")
    cols[3].metric("标准差", "—" if t["std"] is None else f"{t['std']:g}")
    cols[4].metric("及格率", _fmt_pct(t["pass_rate"]))
    cols[5].metric("优秀率", _fmt_pct(t["excellent_rate"]))
    c1, c2 = st.columns(2)
    c1.metric("最高分", "—" if t["max"] is None else f"{t['max']:g}")
    c2.metric("最低分", "—" if t["min"] is None else f"{t['min']:g}")
    st.caption(f"及格线=满分60%，优秀线=满分85%；本次总分满分 {data['total_full']:g}。")


def _render_band_and_subject_charts(data):
    """分数段分布（柱状/饼图）+ 各科均分对比（柱状/折线）+ 学生排名条形图。"""
    subjects = data["subjects"]
    subject_stats = data["subject_stats"]

    st.markdown("**分数段分布（按科目）**")
    subj = st.selectbox("选择科目看分数段", subjects, key="band_subject")
    _render_band_chart(subject_stats[subj]["bands"], subj)

    st.markdown("**各科平均分对比**")
    means = [subject_stats[s]["mean"] for s in subjects]
    compare_type = st.radio(
        "均分对比图类型", ["柱状图", "折线图"], horizontal=True,
        key="mean_compare_type")
    if compare_type == "折线图":
        fig2 = go.Figure(go.Scatter(
            x=subjects, y=means, mode="lines+markers+text",
            text=means, line=dict(width=3, color="#59a14f")))
    else:
        fig2 = go.Figure(go.Bar(x=subjects, y=means, text=means,
                                marker_color="#59a14f"))
    fig2.update_layout(height=320, margin=dict(l=10, r=10, t=30, b=10),
                       title="各科平均分对比", xaxis_title="科目",
                       yaxis_title="平均分", showlegend=False)
    st.plotly_chart(fig2, width="stretch")

    st.markdown("**学生总分排名图**")
    _render_rank_bar_chart(data["rows"], "total", "学生总分排名（高→低）", "总分")


def _delta_html(delta_info, score_label="总分"):
    """把进退步信息渲染成带颜色的小文本；进步绿、退步红。"""
    if not delta_info:
        return "—"
    score_delta = delta_info.get("score_delta")
    rank_delta = delta_info.get("rank_delta")
    parts = []
    if score_delta is not None:
        sign = "+" if score_delta > 0 else ""
        color = "#1a9850" if score_delta > 0 else ("#d73027" if score_delta < 0 else "#666")
        parts.append(f"<span style='color:{color}'>{score_label}{sign}{score_delta:g}</span>")
    if rank_delta is not None and rank_delta != 0:
        sign = "↑" if rank_delta > 0 else "↓"
        color = "#1a9850" if rank_delta > 0 else "#d73027"
        parts.append(f"<span style='color:{color}'>名次{sign}{abs(rank_delta)}</span>")
    elif rank_delta == 0:
        parts.append("<span style='color:#666'>名次持平</span>")
    return "　".join(parts) if parts else "—"


def _render_rank_table(data):
    """排名表：班级筛选、搜索、进退步红绿标记。"""
    st.markdown("**班级排名表（含与上次考试的进退步）**")
    keyword = st.text_input("搜索姓名", key="rank_search")
    subjects = data["subjects"]
    deltas = data["deltas"]

    rows = data["rows"]
    if keyword.strip():
        rows = [r for r in rows if keyword.strip() in (r["name"] or "")]

    table = []
    for r in rows:
        row = {
            "班级": r["class_name"] or "", "姓名": r["name"],
            **{s: ("" if r[s] is None else f"{r[s]:g}") for s in subjects},
            "总分": "" if r["total"] is None else f"{r['total']:g}",
            "班名": r["total_rank"] if r["total_rank"] is not None else "—",
            "进退步": _delta_html(deltas.get(r["student_id"])),
        }
        table.append(row)
    df = pd.DataFrame(table)
    st.markdown(df.to_html(escape=False, index=False), unsafe_allow_html=True)
    st.caption("绿色=进步，红色=退步；只比较日期相邻的两次考试。")


def _render_subject_view(data):
    """单科视角：单科指标卡 + 单科分数段柱状图 + 单科排名表（同科进退步）。"""
    subject = data["subject"]
    t = data["stats"]
    cols = st.columns(6)
    cols[0].metric("参考人数", t["count"])
    cols[1].metric("平均分", "—" if t["mean"] is None else f"{t['mean']:g}")
    cols[2].metric("中位数", "—" if t["median"] is None else f"{t['median']:g}")
    cols[3].metric("标准差", "—" if t["std"] is None else f"{t['std']:g}")
    cols[4].metric("及格率", _fmt_pct(t["pass_rate"]))
    cols[5].metric("优秀率", _fmt_pct(t["excellent_rate"]))
    c1, c2 = st.columns(2)
    c1.metric("最高分", "—" if t["max"] is None else f"{t['max']:g}")
    c2.metric("最低分", "—" if t["min"] is None else f"{t['min']:g}")
    st.caption(f"当前分析科目：{subject}；满分 {data['full_score']:g}，"
               "及格线=满分60%，优秀线=满分85%。")

    st.divider()
    _render_band_chart(t["bands"], subject)

    st.divider()
    st.markdown(f"**{subject}学生排名图**")
    _render_rank_bar_chart(data["rows"], subject,
                           f"{subject}单科排名（高→低）", subject)

    st.divider()
    st.markdown(f"**{subject}班内排名表（含与上次考试同科进退步）**")
    # 复用总分排名搜索框的固定 key：两种视角切换时控件身份保持稳定，
    # 避免动态 key / 自动 id 在切换时产生孤儿状态（搜索词保留也符合预期）
    keyword = st.text_input("搜索姓名", key="rank_search")
    rows = data["rows"]
    deltas = data["deltas"]
    rank_key = f"{subject}_rank"
    if keyword.strip():
        rows = [r for r in rows if keyword.strip() in (r["name"] or "")]
    table = []
    for r in rows:
        table.append({
            "班级": r["class_name"] or "",
            "姓名": r["name"],
            subject: "" if r.get(subject) is None else f"{r[subject]:g}",
            "班名": r.get(rank_key) if r.get(rank_key) is not None else "—",
            "进退步": _delta_html(deltas.get(r["student_id"]),
                                  score_label=subject),
        })
    st.markdown(pd.DataFrame(table).to_html(escape=False, index=False),
                unsafe_allow_html=True)
    st.caption("绿色=进步，红色=退步；只比较日期相邻两次考试的同一科目。")


def _build_exam_data_text(data, class_filter) -> str:
    """把分析结果压缩成给 AI 的纯文本数据（只含统计，不含提示词指令）。"""
    lines = [f"考试：{data['exam'].name}；范围：{class_filter}；"
             f"总分满分：{data['total_full']:g}；参考人数：{data['total_stats']['count']}"]
    t = data["total_stats"]
    lines.append(f"总分：均分{t['mean']}、中位数{t['median']}、标准差{t['std']}、"
                 f"最高{t['max']}、最低{t['min']}、"
                 f"及格率{_fmt_pct(t['pass_rate'])}、优秀率{_fmt_pct(t['excellent_rate'])}")
    for s in data["subjects"]:
        ss_stat = data["subject_stats"][s]
        band_text = "，".join(f"{b['label']}{b['count']}人" for b in ss_stat["bands"])
        lines.append(f"{s}（满分{ss_stat['full_score']:g}）：均分{ss_stat['mean']}，"
                     f"及格率{_fmt_pct(ss_stat['pass_rate'])}，"
                     f"优秀率{_fmt_pct(ss_stat['excellent_rate'])}；分数段：{band_text}")
    return "\n".join(lines)


def _render_ai_exam_summary(data, class_filter):
    """AI 考试分析文字总结 + Word 导出。"""
    st.markdown("**AI 考试分析总结**")
    data_text = _build_exam_data_text(data, class_filter)
    with st.expander("查看发给 AI 的统计数据", expanded=False):
        st.code(data_text)
    _ai_button("exam", lambda: data_text, "🤖 生成考试分析",
               help_text="依据上面的统计数据生成不超过 300 字的分析")
    _export_word_report(data, class_filter)


def _export_word_report(data, class_filter):
    """把统计结果和排名表导出成可打印的 Word 报告（不含 AI 文本，AI 文本可另行复制）。"""
    if not st.button("⬇️ 导出分析报告（Word）"):
        return
    try:
        from docx import Document
        from io import BytesIO
        import config as cfg

        doc = Document()
        doc.add_heading(f"{data['exam'].name} 成绩分析", level=1)
        doc.add_paragraph(f"范围：{class_filter}　总分满分：{data['total_full']:g}")
        t = data["total_stats"]
        doc.add_paragraph(
            f"参考 {t['count']} 人，均分 {t['mean']}，中位数 {t['median']}，"
            f"标准差 {t['std']}，最高 {t['max']}，最低 {t['min']}，"
            f"及格率 {_fmt_pct(t['pass_rate'])}，优秀率 {_fmt_pct(t['excellent_rate'])}。")

        doc.add_heading("各科情况", level=2)
        for s in data["subjects"]:
            stt = data["subject_stats"][s]
            doc.add_paragraph(
                f"{s}：均分 {stt['mean']}，及格率 {_fmt_pct(stt['pass_rate'])}，"
                f"优秀率 {_fmt_pct(stt['excellent_rate'])}。", style="List Bullet")

        doc.add_heading("班级排名", level=2)
        subjects = data["subjects"]
        table = doc.add_table(rows=1, cols=4 + len(subjects))
        table.style = "Light Grid Accent 1"
        hdr = table.rows[0].cells
        headers = ["班级", "姓名"] + subjects + ["总分", "班名"]
        for i, h in enumerate(headers):
            hdr[i].text = h
        for r in data["rows"]:
            cells = table.add_row().cells
            cells[0].text = r["class_name"] or ""
            cells[1].text = r["name"]
            for j, s in enumerate(subjects):
                cells[2 + j].text = "" if r[s] is None else f"{r[s]:g}"
            cells[2 + len(subjects)].text = "" if r["total"] is None else f"{r['total']:g}"
            cells[3 + len(subjects)].text = ("" if r["total_rank"] is None
                                             else str(r["total_rank"]))

        buffer = BytesIO()
        doc.save(buffer)
        cfg.ensure_dirs()
        st.download_button(
            "💾 保存 Word 文件", buffer.getvalue(),
            file_name=f"{data['exam'].name}_成绩分析.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        st.success("报告已生成，点上方按钮保存。")
    except Exception as exc:
        st.error(f"导出失败：{exc}")
# ---------------------------------------------------------------------------
# 标签页 4：趋势分析
# ---------------------------------------------------------------------------

def tab_trends():
    """学生个人趋势 + 班级整体趋势，可选最近 3/5 次/全部考试。"""
    st.subheader("趋势分析")

    with SessionLocal() as session:
        exams = es.list_exams(session)
        classes = ss.list_classes(session)
    if len(exams) < 1:
        st.info("还没有考试数据。")
        return

    # 收集所有考试出现过的科目，作为科目选择器选项
    with SessionLocal() as session:
        trend_subjects = sorted({
            s for e in exams
            for s in es.exam_subjects(session, e.id)
        })
    subject_options = ["全部科目"] + trend_subjects
    subject_default = 0

    c1, c2, c3 = st.columns(3)
    scope = c1.selectbox("显示范围",
                         ["最近 3 次", "最近 5 次", "最近 10 次", "全部"], index=1)
    class_filter = c2.selectbox("班级", ["全部"] + classes, key="trend_class")
    trend_subject = c3.selectbox("科目", subject_options,
                                 index=subject_default, key="trend_subject")
    limit = {"最近 3 次": 3, "最近 5 次": 5,
             "最近 10 次": 10, "全部": None}[scope]
    subject_arg = None if trend_subject == "全部科目" else trend_subject

    with st.expander("📈 班级整体趋势", expanded=True):
        _class_trend_chart(class_filter, limit, subject_arg)

    st.divider()
    with st.expander("🧑‍🎓 学生个人趋势", expanded=True):
        _student_trend_panel(class_filter, limit, subject_arg)


def _apply_limit(names, limit):
    """按最后 limit 场截断（None 表示全部）。"""
    if limit and len(names) > limit:
        return names[-limit:]
    return names


def _class_trend_chart(class_filter, limit, subject=None):
    """历次考试各科均分与总分均分折线；传 subject 时只画该科。"""
    with SessionLocal() as session:
        trend = es.class_trend(
            session,
            None if class_filter == "全部" else class_filter,
            subject=subject)
    exam_names = _apply_limit(trend["exams"], limit)
    cut = len(exam_names)
    start = len(trend["exams"]) - cut

    fig = go.Figure()
    if subject is not None:
        fig.add_trace(go.Scatter(
            x=exam_names, y=trend["series"][subject][start:],
            mode="lines+markers", name=subject,
            line=dict(width=4, color="#1F4E79")))
    else:
        for s in trend["subjects"]:
            fig.add_trace(go.Scatter(
                x=exam_names, y=trend["series"][s][start:],
                mode="lines+markers", name=s))
        fig.add_trace(go.Scatter(
            x=exam_names, y=trend["series"]["total"][start:],
            mode="lines+markers", name="总分",
            line=dict(width=4, dash="dot")))
    fig.update_layout(height=420, margin=dict(l=10, r=10, t=30, b=10),
                      yaxis_title="平均分", hovermode="x unified")
    if exam_names:
        st.plotly_chart(fig, width="stretch")
    else:
        st.caption("所选范围内没有数据。")


def _student_trend_panel(class_filter, limit=None, subject=None):
    """选学生后，在一张图里同时展示总分和勾选的各科成绩。

    传 subject 时，科目多选默认只勾选该科（仍可在面板内增减）。
    """
    with SessionLocal() as session:
        students = ss.list_students(
            session,
            class_name=None if class_filter == "全部" else class_filter)
    if not students:
        st.caption("没有学生。")
        return
    options = {f"{s.name}｜{s.class_name or '未分班'}": s.id for s in students}
    chosen = st.selectbox("选择学生", list(options.keys()), key="trend_student")
    sid = options[chosen]

    with SessionLocal() as session:
        history = es.student_scores_over_time(session, sid)
    if not history:
        st.caption("该生还没有成绩。")
        return

    history = _apply_limit(history, limit)
    exam_names = [h["exam_name"] for h in history]
    subjects = [k for k in history[0].keys()
                if k not in ("exam_id", "exam_name", "exam_date", "total")]

    cc1, cc2 = st.columns(2)
    # 单科视角下默认勾选该科；该科缺考时回退为全选。
    # 多选框用固定 key（避免切科目时控件身份变化产生孤儿状态），
    # 科目选择器变化时主动清掉旧选择，让默认值重新生效。
    trend_marker = "student_trend_subject_prev"
    if st.session_state.get(trend_marker) != subject:
        st.session_state.pop("student_trend_subjects", None)
        st.session_state[trend_marker] = subject
    default_shown = [subject] if (subject is not None and subject in subjects) else subjects
    shown_subjects = cc1.multiselect(
        "显示科目", subjects, default=default_shown,
        key="student_trend_subjects")
    chart_type = cc2.radio(
        "图表类型", ["折线图", "柱状图"], horizontal=True,
        key="student_trend_chart_type")

    fig = go.Figure()
    if chart_type == "折线图":
        for subject in shown_subjects:
            fig.add_trace(go.Scatter(
                x=exam_names, y=[h.get(subject) for h in history],
                mode="lines+markers", name=subject, connectgaps=False))
        fig.add_trace(go.Scatter(
            x=exam_names, y=[h.get("total") for h in history],
            mode="lines+markers+text",
            text=[h.get("total") for h in history],
            textposition="top center",
            name="总分", line=dict(width=5, color="#1F4E79")))
    else:
        for subject in shown_subjects:
            fig.add_trace(go.Bar(
                x=exam_names, y=[h.get(subject) for h in history], name=subject))
        fig.add_trace(go.Bar(
            x=exam_names, y=[h.get("total") for h in history],
            name="总分", marker_color="#1F4E79", opacity=0.9))
        fig.update_layout(barmode="group")

    fig.update_layout(
        height=430,
        margin=dict(l=10, r=10, t=30, b=10),
        yaxis_title="分数",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    st.plotly_chart(fig, width="stretch")


# ---------------------------------------------------------------------------
# 标签页 5：学生画像
# ---------------------------------------------------------------------------

def tab_profile():
    """学生信息卡、各科雷达图、自动标签、趋势、AI 学情分析。"""
    st.subheader("学生画像")
    with SessionLocal() as session:
        students = ss.list_students(session)
    if not students:
        st.info("还没有学生，先到「学生管理」导入名单。")
        return

    options = {f"{s.name}｜{s.class_name or '未分班'}": s.id for s in students}
    chosen = st.selectbox("选择学生", list(options.keys()), key="profile_student")
    sid = options[chosen]

    with SessionLocal() as session:
        student = session.get(__import__("models.models", fromlist=["Student"]).Student, sid)
        history = es.student_scores_over_time(session, sid)

    if not history:
        st.info(f"{student.name} 还没有成绩数据。")
        return

    # 每科按历次"得分/满分"算平均得分率（雷达图用），并收集趋势得分率
    subject_rates_all = {}
    subject_latest_rate = {}
    # 逐次考试取各科满分，把原始分换算成得分率
    with SessionLocal() as session:
        for h in history:
            exam = es.get_exam(session, h["exam_id"])
            subs = es.exam_subjects(session, h["exam_id"])
            full = es.full_scores_of(exam, subs)
            for s in subs:
                if h.get(s) is not None and full.get(s):
                    subject_rates_all.setdefault(s, []).append(h[s] / full[s])

    subject_avg_rate = {s: sum(v) / len(v) for s, v in subject_rates_all.items()}
    subjects = sorted(subject_avg_rate.keys())

    # 信息卡 + 自动标签
    c1, c2 = st.columns([1, 2])
    with c1:
        st.markdown(f"#### {student.name}")
        st.write(f"**班级：** {student.class_name or '未分班'}")
        st.write(f"**学号：** {student.student_no or '—'}")
        st.write(f"**性别：** {student.gender or '—'}")
        exams_count = len(history)
        st.write(f"**参考次数：** {exams_count}")
        latest = history[-1]
        st.write(f"**最近一次：** {latest['exam_name']}，总分 {latest['total']:g}")

    # 自动标签
    overall_rate = (sum(subject_avg_rate.values()) / len(subject_avg_rate)
                    if subject_avg_rate else None)
    level = stats_mod.level_tag(overall_rate)
    # 趋势标签用总分得分率序列（需要总分满分，按各科满分之和）
    total_rates = []
    with SessionLocal() as session:
        for h in history:
            exam = es.get_exam(session, h["exam_id"])
            subs = es.exam_subjects(session, h["exam_id"])
            full_total = sum(es.full_scores_of(exam, subs).values())
            if h["total"] is not None and full_total:
                total_rates.append(h["total"] / full_total)
    trend = stats_mod.trend_label(total_rates)
    strengths = stats_mod.subject_strength(subject_avg_rate)
    strong = [s for s, t in strengths.items() if t == "强项"]
    weak = [s for s, t in strengths.items() if t == "弱项"]

    with c2:
        tag_cols = st.columns(3)
        tag_cols[0].metric("成绩层次", level)
        tag_cols[1].metric("趋势", trend)
        tag_cols[2].metric("参考", f"{len(total_rates)} 次")
        st.write("**强项科目：** " + ("、".join(strong) if strong else "暂无明显强项"))
        st.write("**薄弱科目：** " + ("、".join(weak) if weak else "暂无明显弱项"))
        if student.tags:
            st.write("**老师标签：** " + student.tags)

    st.divider()
    # 雷达图：按得分率画，满分不同也可比
    st.markdown("**各科实力雷达图（平均得分率 %）**")
    fig = go.Figure(go.Scatterpolar(
        r=[round(subject_avg_rate[s] * 100, 1) for s in subjects] + [round(subject_avg_rate[subjects[0]] * 100, 1)],
        theta=subjects + [subjects[0]],
        fill="toself", name="平均得分率"))
    fig.update_layout(polar=dict(radialaxis=dict(range=[0, 100])),
                      height=420, margin=dict(l=30, r=30, t=30, b=10))
    st.plotly_chart(fig, width="stretch")

    # 历次成绩表
    st.markdown("**历次成绩**")
    table = pd.DataFrame([{
        "考试": h["exam_name"],
        **{s: ("" if h.get(s) is None else f"{h[s]:g}") for s in subjects},
        "总分": "" if h["total"] is None else f"{h['total']:g}",
    } for h in history])
    st.dataframe(table, width="stretch", hide_index=True)

    st.divider()
    st.markdown("**AI 学情分析**")
    data_text = _build_student_data_text(
        student, history, subjects, subject_avg_rate, level, trend, strong, weak)
    with st.expander("查看发给 AI 的学生数据", expanded=False):
        st.code(data_text)
    _ai_button("student", lambda: data_text, "🤖 生成学情分析",
               help_text="结合历次成绩和标签生成 150 字内的个性化分析")


def _build_student_data_text(student, history, subjects, subject_avg_rate,
                             level, trend, strong, weak) -> str:
    """组装给 AI 的学生数据文本。"""
    lines = [f"学生：{student.name}；班级：{student.class_name or '未分班'}；"
             f"参考 {len(history)} 次。",
             f"系统标签：成绩层次「{level}」，趋势「{trend}」，"
             f"强项：{('、'.join(strong)) or '无'}，弱项：{('、'.join(weak)) or '无'}。",
             "各科平均得分率："
             + "，".join(f"{s}{subject_avg_rate[s]*100:.1f}%" for s in subjects) + "。",
             "历次成绩："]
    for h in history:
        parts = [f"{s}{h.get(s):g}" for s in subjects if h.get(s) is not None]
        lines.append(f"- {h['exam_name']}：" + "，".join(parts)
                     + f"，总分{h['total']:g}")
    return "\n".join(lines)



# ---------------------------------------------------------------------------
# 标签页 6：教学反思
# ---------------------------------------------------------------------------

def _read_prompt_file(filename: str) -> str:
    """读取 prompts 目录下的系统提示词模板。"""
    import config
    return (Path(config.BASE_DIR) / "prompts" / filename).read_text(encoding="utf-8")


def tab_reflection():
    """教学反思：单次考试或时间段，AI 基于成绩+作业错题生成四段式反思。"""
    st.subheader("教学反思")
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

    # 生成结果（可编辑、保存、导出）
    draft = st.session_state.get("reflection_draft")
    if draft:
        st.markdown("#### 反思内容（可在线编辑后保存留档）")
        title = st.text_input("标题", value=draft["title"], key="reflection_title")
        edited = {}
        for name in rs.SECTIONS:
            # 不给固定 key：生成后靠 value= 回填（有 key 时 value 只在首帧生效）
            edited[name] = st.text_area(
                f"## {name}", value=draft["sections"].get(name, ""), height=120)
        b1, b2 = st.columns(2)
        if b1.button("💾 保存留档", type="primary"):
            with SessionLocal() as session:
                rs.save_reflection(
                    session, title, draft["scope_type"], draft["start_id"],
                    draft["class_name"], edited, end_exam_id=draft["end_id"])
                session.commit()
            st.success("反思已保存，可在下方历史记录里查看或导出。")
            st.session_state.pop("reflection_draft", None)
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
    labels = [f"{r.title}｜{r.created_at:%Y-%m-%d}" for r in history]
    pick = st.selectbox("选择一条反思", labels, key="reflection_history_pick")
    row = history[labels.index(pick)]
    data = rs.load_reflection_content(row)
    for name in rs.SECTIONS:
        st.markdown(f"**{name}**")
        st.write(data["sections"].get(name) or "—")
    d1, d2 = st.columns(2)
    with SessionLocal() as session:
        blob = rs.export_word(row)
    d1.download_button(
        "⬇️ 导出 Word", blob,
        file_name=f"{row.title}.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    if d2.button("🗑️ 删除这条反思", key="del_reflection"):
        with SessionLocal() as session:
            rs.delete_reflection(session, row.id)
            session.commit()
        st.success("已删除。")
        st.rerun()



# ---------------------------------------------------------------------------
# 标签页 7：期末评语
# ---------------------------------------------------------------------------

def _generate_one_comment(session, student, term: str, style: str) -> str:
    """调主模型生成单个学生评语（数据走 user 消息注入）。"""
    data_text = cs.build_comment_input(session, student, term)
    system_prompt = _read_prompt_file("student_comment_prompt.txt")
    user_text = f"请用「{style}」风格写评语。\n\n学生数据如下：\n{data_text}"
    return llm_client.chat(system_prompt, user_text, temperature=0.7).strip()


def _render_template_library(session):
    """常用评语模板的增删查。"""
    with st.expander("📚 常用评语模板库（可增删）", expanded=False):
        with st.form("add_comment_template", clear_on_submit=True):
            tc1, tc2 = st.columns([1, 1])
            tpl_name = tc1.text_input("模板名称", placeholder="如：进步明显型")
            tpl_style = tc2.selectbox("风格", cs.STYLES, key="tpl_style")
            tpl_content = st.text_area("模板正文", height=100,
                                       placeholder="可作为生成时的参考，批量生成不自动套用。")
            if st.form_submit_button("➕ 添加模板"):
                if tpl_name.strip() and tpl_content.strip():
                    cs.create_template(session, tpl_name, tpl_content, tpl_style)
                    session.commit()
                    st.success("模板已添加。")
                    st.rerun()
                else:
                    st.error("名称和正文都要填。")
        templates = cs.list_templates(session)
        if not templates:
            st.caption("还没有模板。")
        for tpl in templates:
            c1, c2 = st.columns([6, 1])
            c1.write(f"**{tpl.name}**（{tpl.style}）：{tpl.content}")
            if c2.button("删除", key=f"del_tpl_{tpl.id}"):
                cs.delete_template(session, tpl.id)
                session.commit()
                st.rerun()


def _render_comment_batch(session, students, term, style):
    """批量逐人生成：进度条 + 成功/失败计数，单条失败不中断，可重试可编辑。"""
    system_ready = llm_client.is_configured()
    if not system_ready:
        st.warning("还没配置 AI：请到「⚙️ 设置 → 主模型配置」填写 API Key 后再批量生成。"
                   "已留档的评语仍可在下方查看、编辑和导出。")

    drafts = st.session_state.setdefault("comment_drafts", {})
    fail_msgs = st.session_state.setdefault("comment_fail", {})

    c1, c2, c3 = st.columns(3)
    if c1.button("🤖 批量生成全部评语", disabled=not system_ready, type="primary"):
        progress = st.progress(0.0, text="开始生成……")
        ok_count = fail_count = 0
        for i, student in enumerate(students):
            try:
                text = _generate_one_comment(session, student, term, style)
                drafts[(student.id, term)] = text
                fail_msgs.pop((student.id, term), None)
                ok_count += 1
            except (llm_client.LLMConfigError, llm_client.LLMCallError) as exc:
                fail_msgs[(student.id, term)] = str(exc)
                fail_count += 1
            progress.progress((i + 1) / len(students),
                              text=f"已处理 {i + 1}/{len(students)}")
        st.success(f"生成完成：成功 {ok_count} 条，失败 {fail_count} 条。"
                   + ("失败的条目可点该行“重试”。" if fail_count else ""))

    st.caption(f"共 {len(students)} 名学生，逐人调用模型，预计耗时约 "
               f"{len(students) * 8} 秒以内。")

    edited_rows = []
    for student in students:
        key = (student.id, term)
        saved = cs.get_comment(session, student.id, term)
        default_text = drafts.get(key) or (saved.content if saved else "")
        with st.container(border=True):
            head = f"**{student.name}**（{student.class_name or '未分班'}）"
            if saved:
                head += "　✅已留档"
            if key in fail_msgs:
                head += f"　❌{fail_msgs[key]}"
            st.markdown(head)
            # label 用学生 id 保证同页唯一（视觉隐藏）；不设固定 key，
            # 新生成内容靠 value= 立即回填，老师手改在当前帧仍能读到
            text = st.text_area(f"评语_{student.id}", value=default_text,
                                height=110, label_visibility="collapsed")
            b1, b2, b3 = st.columns(3)
            if b1.button("💾 保存这一条", key=f"save_c_{student.id}_{term}"):
                if text.strip():
                    cs.upsert_comment(session, student.id, term, text, style)
                    session.commit()
                    drafts[key] = text.strip()
                    st.success(f"{student.name} 的评语已保存。")
                    st.rerun()
                else:
                    st.error("评语为空，不能保存。")
            if b2.button("🔄 重试生成", key=f"retry_c_{student.id}_{term}",
                         disabled=not system_ready):
                try:
                    with st.spinner(f"正在为 {student.name} 生成……"):
                        text = _generate_one_comment(session, student, term, style)
                    drafts[key] = text
                    fail_msgs.pop(key, None)
                    st.rerun()
                except (llm_client.LLMConfigError, llm_client.LLMCallError) as exc:
                    fail_msgs[key] = str(exc)
                    st.error(str(exc))
            if b3.button("🧹 清空输入", key=f"clear_c_{student.id}_{term}"):
                drafts.pop(key, None)
                st.rerun()
            edited_rows.append({"student": student, "text": text})

    if c2.button("💾 一键保存全部已生成评语", type="primary"):
        saved_n = 0
        for item in edited_rows:
            if item["text"].strip():
                cs.upsert_comment(session, item["student"].id, term,
                                  item["text"].strip(), style)
                saved_n += 1
        session.commit()
        st.success(f"已保存 {saved_n} 条评语（按“学生+学期”留档，重复保存是更新）。")
        st.rerun()

    rows = cs.list_comments(session, term=term)
    if rows:
        blob = cs.export_comments_word(rows, f"期末评语·{term}")
        c3.download_button(
            "⬇️ 导出本学期评语 Word", blob,
            file_name=f"期末评语_{term}.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    else:
        c3.caption("还没有已留档评语，暂不可导出。")


def tab_comments():
    """期末评语：选班级+学期+风格，逐人生成、留档、批量导出。"""
    st.subheader("期末评语")
    with SessionLocal() as session:
        classes = ss.list_classes(session)
        if not ss.list_students(session):
            st.info("还没有学生，先到「学生管理」导入名单，再来生成评语。")
            return
        class_options = ["全部班级"] + classes
        cc1, cc2, cc3 = st.columns(3)
        class_choice = cc1.selectbox("班级", class_options, key="comment_class")
        term = cc2.text_input("学期", value="2026 上",
                              help="同一学生同一学期只留一条，重新生成会覆盖。")
        style = cc3.selectbox("评语风格", cs.STYLES, key="comment_style")

        if not term.strip():
            st.warning("请先填写学期。")
            return
        class_name = None if class_choice == "全部班级" else class_choice
        students = ss.list_students(session, class_name=class_name)
        _render_template_library(session)
        st.divider()
        _render_comment_batch(session, students, term.strip(), style)


# ---------------------------------------------------------------------------
# 页面入口
# ---------------------------------------------------------------------------

def show():
    """学情：顶部 7 个标签页路由。"""
    st.title("📊 学情")
    tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs(
        ["学生管理", "成绩管理", "考试分析", "趋势分析", "学生画像",
         "教学反思", "期末评语"])
    with tab1:
        tab_students()
    with tab2:
        tab_scores()
    with tab3:
        tab_exam_analysis()
    with tab4:
        tab_trends()
    with tab5:
        tab_profile()
    with tab6:
        tab_reflection()
    with tab7:
        tab_comments()
