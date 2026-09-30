# -*- coding: utf-8 -*-
"""
学情页面。

顶部 8 个标签页：学生管理 / 成绩管理 / 考试分析 / 趋势分析 / 学生画像 /
教学反思 / 期末评语 / 知识点分析。
本文件只负责界面与交互；统计口径在 utils/stats.py，数据库读写在
utils/student_service.py、utils/exam_service.py，Excel 识别在 utils/excel_handler.py。
"""

import json
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from utils.db import SessionLocal
from models.models import Homework
from utils import excel_handler as eh
from utils import score_doc_parser as sdp
from utils import academic_time, analysis_settings, class_service
from utils import chart_service
from utils import exam_service as es
from utils import stats as stats_mod
from utils import student_service as ss
from utils import llm_client
from utils import agent_context
from utils.app_config import DEFAULT_SUBJECT, SUBJECT_NAMES
from utils import diagnosis_service
from utils import reflection_service as rs
from utils import comment_service as cs
from utils import term_report_service as trs
from utils import homework_service as hws
from utils import homework_score_service as hscore
from utils.navigation import goto_group
from utils import knowledge_heatmap_service as khm
from utils import knowledge_graph_service as kgs
from utils import parent_report_service
from utils import pagination_service
from utils import agent_advisor


# ---------------------------------------------------------------------------
# 通用小工具
# ---------------------------------------------------------------------------

def _sync_analysis_context(**kwargs) -> None:
    """只把明确非空字段同步到 AI 上下文。"""
    patch = {k: v for k, v in kwargs.items() if str(v or "").strip()}
    if patch:
        try:
            agent_context.update_context(**patch)
        except (ValueError, OSError):
            pass

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
    """学生名单：班级管理、Excel 导入、手动添加、筛选搜索、编辑删除。"""
    st.subheader("学生管理")

    with st.expander("🏫 班级管理", expanded=False):
        _class_management_panel()

    with st.expander("📥 从 Excel 导入学生名单", expanded=False):
        _student_import_panel()

    with st.expander("➕ 手动添加学生", expanded=False):
        _student_add_panel()

    st.divider()
    _student_list_panel()


def _class_management_panel():
    """班级名单维护（从设置页迁入）：可编辑表格新增/改名，勾选删除，批量调班。"""
    notice = st.session_state.pop("class_management_notice", None)
    if notice:
        st.toast(notice)

    with SessionLocal() as session:
        classes = class_service.list_class_names(session)
        usage = {name: class_service.class_usage(session, name) for name in classes}
        students = ss.list_students(session)

        class_df = pd.DataFrame([{
            "删除": False,
            "原班级名": name,
            "班级名": name,
            "学生数": usage[name]["students"],
        } for name in classes])
        if class_df.empty:
            class_df = pd.DataFrame({
                "删除": pd.Series(dtype="bool"),
                "原班级名": pd.Series(dtype="object"),
                "班级名": pd.Series(dtype="object"),
                "学生数": pd.Series(dtype="int64"),
            })

        st.caption("直接在表格里新增或改班级名，点“保存班级修改”生效；学生数自动统计，不用填写。")
        edited_class_df = st.data_editor(
            class_df,
            num_rows="dynamic",
            hide_index=True,
            key="class_editor_main",
            column_order=["删除", "班级名", "学生数"],
            column_config={
                "原班级名": None,
                "删除": st.column_config.CheckboxColumn(
                    "删除", help="勾选后用下方按钮删除，仅允许删除空班级", default=False),
                "班级名": st.column_config.TextColumn("班级名", required=True, width="medium"),
                "学生数": st.column_config.NumberColumn("学生数", disabled=True),
            },
            height=min(300, 80 + max(4, len(class_df)) * 36),
        )
        class_rows = edited_class_df.where(
            pd.notna(edited_class_df), None).to_dict("records")

        cc1, cc2 = st.columns(2)
        if cc1.button("💾 保存班级修改", type="primary", key="save_class_editor"):
            try:
                with SessionLocal() as save_session:
                    result = class_service.sync_classes(save_session, class_rows)
                    save_session.commit()
                st.session_state.pop("class_editor_main", None)
                st.session_state["class_management_notice"] = (
                    f"已保存班级：新增 {result['added']} 个，重命名 {result['renamed']} 个。")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

        checked = [str(r["原班级名"]).strip() for r in class_rows
                   if r.get("原班级名") is not None and bool(r.get("删除"))]
        if cc2.button("🗑️ 删除勾选班级", disabled=not checked, key="delete_class_checked"):
            st.session_state["class_delete_pending"] = checked

        if st.session_state.get("class_delete_pending"):
            pending = list(st.session_state["class_delete_pending"])
            st.error(f"将删除勾选的 {len(pending)} 个空班级。若仍有学生或作业会被阻止，确定继续吗？")
            dc1, dc2 = st.columns(2)
            if dc1.button("✅ 确认删除", type="primary", key="confirm_class_delete"):
                try:
                    with SessionLocal() as del_session:
                        for name in pending:
                            used = class_service.class_usage(del_session, name)
                            if used["students"]:
                                raise ValueError(f"该班还有 {used['students']} 名学生，无法删除：{name}")
                            if used["homeworks"]:
                                raise ValueError(
                                    f"班级 {name} 还有 {used['homeworks']} 份普通作业，请先改名或处理作业。")
                            class_service.delete_class(del_session, name)
                        del_session.commit()
                    st.session_state.pop("class_delete_pending", None)
                    st.session_state.pop("class_editor_main", None)
                    st.session_state["class_management_notice"] = f"已删除 {len(pending)} 个空班级。"
                    st.rerun()
                except ValueError as exc:
                    st.session_state.pop("class_delete_pending", None)
                    st.error(str(exc))
            if dc2.button("取消", key="cancel_class_delete"):
                st.session_state.pop("class_delete_pending", None)
                st.rerun()

        st.divider()
        st.write("**批量调整学生班级**")
        student_options = {
            f"{s.name}｜{s.class_name or '未分班'}": s.id for s in students
        }
        class_options = classes or ["（暂无班级）"]
        picked_labels = st.multiselect(
            "选择学生", list(student_options.keys()), key="class_move_students")
        target_class = st.selectbox("目标班级", class_options, key="class_move_target")
        if st.button("➡️ 批量调班", disabled=not classes, key="move_class_button"):
            try:
                ids = [student_options[label] for label in picked_labels]
                with SessionLocal() as move_session:
                    count = class_service.move_students(move_session, ids, target_class)
                    move_session.commit()
                st.session_state["class_management_notice"] = (
                    f"已调整 {count} 名学生到 {target_class}。")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))


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
        st.toast(f"导入完成：新增 {result['created']} 人，更新 {result['updated']} 人，"
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
        st.toast(f"已添加学生：{name.strip()}")
        st.rerun()


def _student_list_panel():
    """学生表格：可直接编辑、动态新增；删除需二次确认。"""
    # 保存/删除成功后跨 rerun 保留提示（同一帧 success+rerun 会被冲掉）。
    last_batch = st.session_state.pop("student_batch_last", None)
    if last_batch:
        st.toast(last_batch)
    last_save = st.session_state.pop("student_save_last", None)
    if last_save:
        st.toast(last_save)
    with SessionLocal() as session:
        classes = ss.list_classes(session)
        tags = ss.list_student_tags(session)

    c1, c2, c3, c4 = st.columns(4)
    class_filter = c1.selectbox("按班级筛选", ["全部"] + classes,
                                key="student_filter_class",
                                on_change=lambda: _sync_analysis_context(
                                    class_name=None if st.session_state["student_filter_class"] == "全部"
                                    else st.session_state["student_filter_class"]))
    keyword = c2.text_input("搜索姓名或学号", key="student_filter_keyword")
    gender_filter = c3.selectbox(
        "性别", ["全部", "男", "女", "未设置"], key="student_filter_gender")
    tag_filter = c4.selectbox(
        "标签", ["全部标签"] + tags, key="student_filter_tag")

    # 表格 key 固定，筛选/搜索变化时不主动 pop key，避免组件重建引发表格 DOM 冲突。
    # data_editor 会自然合并新数据到已有状态中。
    page_size = st.selectbox("每页显示", [20, 50, 100], key="student_page_size")
    page_number = st.session_state.get("student_page_number", 1)
    with SessionLocal() as session:
        filters = {
            "class_name": None if class_filter == "全部" else class_filter,
            "keyword": keyword.strip() or None,
            "gender": None if gender_filter == "全部" else gender_filter,
            "tag": None if tag_filter == "全部标签" else tag_filter,
        }
        total_count = ss.count_students(session, **filters)
        page = pagination_service.page_info(total_count, page_number, page_size)
        if page["page"] != page_number:
            st.session_state["student_page_number"] = page["page"]
            page_number = page["page"]
        students = ss.list_students(session, limit=page["limit"],
                                    offset=page["offset"], **filters)
        filtered_ids = ss.list_student_ids(session, **filters)
        existing_ids = {student.id for student in students}
        initial_df = pd.DataFrame([{
            "选择": False,
            "学生ID": s.id,
            "姓名": s.name,
            "学号": s.student_no or "",
            "班级": s.class_name or "",
            "性别": s.gender if s.gender in ("男", "女") else None,
            "标签": s.tags or "",
            "备注": s.remark or "",
        } for s in students])

    cur_page = page["page"]
    total_pages = page["total_pages"]
    st.caption(f"共 {total_count} 名学生，当前第 {cur_page}/{total_pages} 页。可直接改表格，也可用最后一行新增学生；改完点下方“保存表格修改”。")
    if initial_df.empty:
        st.info("还没有符合条件的学生；如果还没导入名单，请先用上方 Excel 导入。")
        initial_df = pd.DataFrame({
            "选择": pd.Series(dtype="bool"),
            "学生ID": pd.Series(dtype="int64"),
            "姓名": pd.Series(dtype="object"),
            "学号": pd.Series(dtype="object"),
            "班级": pd.Series(dtype="object"),
            "性别": pd.Series(dtype="object"),
            "标签": pd.Series(dtype="object"),
            "备注": pd.Series(dtype="object"),
        })

    if total_count > 0:
        pc1, pc2, pc3 = st.columns([1, 1, 3])
        if pc1.button("⬅️ 上一页", disabled=page["page"] <= 1, key="student_prev_page", use_container_width=True):
            st.session_state["student_page_number"] = page["page"] - 1
            st.rerun()
        if pc2.button("下一页 ➡️", disabled=page["page"] >= page["total_pages"], key="student_next_page", use_container_width=True):
            st.session_state["student_page_number"] = page["page"] + 1
            st.rerun()
        pc3.caption(f"第 {cur_page} / {total_pages} 页")

    # 快捷跳转：在当前筛选结果里选一个学生，直接切到“学生画像”tab。
    if students:
        jc1, jc2 = st.columns([3, 1])
        profile_labels = {
            f"{s.name}｜{s.class_name or '未分班'}": s.id for s in students}
        jc1.selectbox("查看学生画像", list(profile_labels.keys()),
                      key="student_jump_profile_label")
        if jc2.button("🔍 查看画像", use_container_width=True):
            _sync_analysis_context(
                class_name=(st.session_state["student_jump_profile_label"].split("｜")[1]
                            if "｜" in st.session_state["student_jump_profile_label"] else ""),
                last_action="打开学生画像")
            goto_group("📊 学情", "学生画像",
                profile_student=st.session_state["student_jump_profile_label"])

    edited_df = st.data_editor(
        initial_df,
        num_rows="dynamic",
        hide_index=True,
        key="student_editor_main",
        column_order=["选择", "姓名", "学号", "班级", "性别", "标签", "备注"],
        column_config={
            "学生ID": None,
            "选择": st.column_config.CheckboxColumn(
                "选择", help="勾选后可用下方按钮批量删除", default=False),
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

    # 分页后其他页学生不在编辑表格里；整批同步时把他们作为未改行透传，避免误删。
    with SessionLocal() as passthrough_session:
        other_rows = [{
            "学生ID": stu.id, "姓名": stu.name, "学号": stu.student_no or "",
            "班级": stu.class_name or "",
            "性别": stu.gender if stu.gender in ("男", "女") else None,
            "标签": stu.tags or "", "备注": stu.remark or "",
        } for stu in ss.list_students(passthrough_session)
          if stu.id in (filtered_ids - existing_ids)]
    combined_rows = rows + other_rows

    # 勾选批量删除：独立于“保存表格修改”，只删勾选行，不写字段编辑。
    checked_ids = {int(r["学生ID"]) for r in rows
                   if r.get("学生ID") is not None and bool(r.get("选择"))}

    c_save, c_batch, c_tip = st.columns([1, 1, 3])
    if c_save.button("💾 保存表格修改", type="primary"):
        if deleted_ids:
            st.session_state["student_delete_pending"] = deleted_ids
        else:
            st.session_state["student_save_pending"] = True
    if c_batch.button("🗑️ 批量删除所选", disabled=not checked_ids):
        st.session_state["student_batch_delete_pending"] = checked_ids
    c_tip.caption("删除学生会级联删除成绩和评语；批量删除会先要求二次确认。")

    if st.session_state.get("student_batch_delete_pending"):
        pending_ids = set(st.session_state["student_batch_delete_pending"])
        st.error(f"将删除勾选的 {len(pending_ids)} 名学生，其成绩和评语也会级联删除。确定继续吗？")
        bc1, bc2 = st.columns(2)
        if bc1.button("✅ 确认批量删除", type="primary", key="confirm_student_batch_del"):
            with SessionLocal() as del_session:
                deleted_n = ss.delete_students(del_session, list(pending_ids))
                del_session.commit()
            st.session_state.pop("student_batch_delete_pending", None)
            st.session_state.pop("student_editor_main", None)
            st.session_state["student_batch_last"] = f"已批量删除 {deleted_n} 名学生。"
            st.rerun()
        if bc2.button("取消", key="cancel_student_batch_del"):
            st.session_state.pop("student_batch_delete_pending", None)
            st.rerun()

    if st.session_state.get("student_delete_pending"):
        pending_ids = set(st.session_state["student_delete_pending"])
        st.error(f"本次将删除 {len(pending_ids)} 名学生，其成绩和评语也会级联删除。确定继续吗？")
        cc1, cc2 = st.columns(2)
        if cc1.button("✅ 确认保存并删除", type="primary"):
            try:
                with SessionLocal() as save_session:
                    result = ss.sync_students(
                        save_session, combined_rows, filtered_ids)
                    save_session.commit()
                st.session_state.pop("student_delete_pending", None)
                st.session_state.pop("student_editor_main", None)
                st.session_state["student_editor_version"] = st.session_state.get(
                    "student_editor_version", 0) + 1
                st.session_state["student_save_last"] = (
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
                result = ss.sync_students(save_session, combined_rows, filtered_ids)
                save_session.commit()
            st.session_state.pop("student_save_pending", None)
            st.session_state.pop("student_editor_main", None)
            st.session_state["student_editor_version"] = st.session_state.get(
                "student_editor_version", 0) + 1
            st.session_state["student_save_last"] = (
                f"已保存：新增 {result['created']} 人，更新 {result['updated']} 人。")
            st.rerun()
        except ValueError as exc:
            st.session_state.pop("student_save_pending", None)
            st.error(str(exc))




def _auto_verify_plans(session, exam_id: int) -> None:
    """成绩写入后尝试自动验证改进计划；失败不影响成绩保存。"""
    try:
        rs.check_and_verify_pending_plans(session, exam_id)
    except Exception:
        pass

# ---------------------------------------------------------------------------
# 标签页 2：成绩管理
# ---------------------------------------------------------------------------

def tab_scores():
    """成绩管理：成绩录入 / 成绩编辑 / 考试管理（v2.4.0 三标签）。"""
    st.subheader("成绩管理")
    # 兼容旧跳转标记（expander 已改为常驻标签，标记仅消费、不再控制展开）。
    st.session_state.pop("score_import_expander", None)
    tabs = st.tabs(["📝 成绩录入", "✏️ 成绩编辑", "📋 考试管理"])
    with tabs[0]:
        _score_import_panel()
        st.divider()
        _score_manual_panel()
    with tabs[1]:
        _score_history_panel()
    with tabs[2]:
        _exam_manage_panel()

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
        st.toast(f"已新建考试：{name.strip()}")
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
                st.toast("满分已更新。")
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
            st.toast("已删除。")
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
    if name.endswith(".txt"):
        return sdp.txt_score_dataframe(
            uploaded.getvalue().decode("utf-8-sig")), "txt"
    return None, "不支持的文件格式，请上传 .xlsx/.xls/.pdf/.docx/.txt。"


def _default_full_score(subject: str) -> float:
    """语文、数学、英语满分 150，其余科目默认 100。"""
    return 150.0 if subject in ("语文", "数学", "英语") else 100.0



def _sync_score_new_exam_term():
    """新建考试改日期时，学期输入同步到按日期推导出的学期。"""
    chosen_date = st.session_state.get("score_new_exam_date") or date.today()
    st.session_state["score_new_exam_term"] = academic_time.semester_name(chosen_date)


def _score_import_panel():
    """上传 Excel/Word/PDF → 可编辑预览；可导入已有考试，也可直接新建考试。"""
    template_df = eh.score_template_dataframe()
    _download_xlsx(template_df, "成绩导入模板.xlsx", label="⬇️ 下载 Excel 模板")

    with SessionLocal() as session:
        exams = es.list_exams(session)

    if not exams:
        st.info("还没有考试；可切换到“新建考试”，上传成绩时直接创建。")

    target_mode = st.radio(
        "导入目标", ["选择已有考试", "新建考试"], horizontal=True,
        key="score_import_target_mode")

    exam_id = None
    new_exam_info = None
    full_scores = None

    if target_mode == "选择已有考试":
        if not exams:
            st.info("还没有考试；可切换到“新建考试”，上传成绩时直接创建。")
            return
        options = {f"{e.name}（{e.exam_date}）": e.id for e in exams}
        chosen = st.selectbox("导入到哪场考试", list(options.keys()),
                              key="score_import_exam")
        exam_id = options[chosen]
    else:
        c1, c2, c3, c4 = st.columns(4)
        new_name = c1.text_input("考试名称 *", placeholder="如：第一次月考",
                                 key="score_new_exam_name")
        new_date = c2.date_input(
            "考试日期", value=date.today(), key="score_new_exam_date",
            on_change=_sync_score_new_exam_term)
        new_grade = c3.text_input("年级", value="八年级",
                                  key="score_new_exam_grade")
        new_term = c4.text_input("学期", value=academic_time.semester_name(new_date),
                                 key="score_new_exam_term")
        new_exam_info = {
            "name": new_name,
            "date": new_date,
            "grade": new_grade.strip() or "八年级",
            "term": new_term.strip() or academic_time.semester_name(new_date),
        }

    last_import = st.session_state.pop("score_last_import", None)
    if last_import:
        st.toast(last_import)

    uploaded = st.file_uploader(
        "选择成绩文件（Excel / Word / PDF / TXT，需含“姓名”列，其余数字列按科目识别）",
        type=["xlsx", "xls", "pdf", "docx", "txt"], key="score_upload")
    if uploaded is None:
        st.caption("可先下载模板；数字列名就是科目，如“数学”或“数学成绩”；空格按缺考处理，不覆盖已有分数。")
        return

    try:
        df, source = _parse_uploaded_scores(uploaded)
    except Exception as exc:
        st.error(f"解析出错：{exc}")
        return
    if df is None:
        st.info(source)
        return
    if source in ("docx", "pdf", "txt"):
        st.info("请核对识别结果，如有错误请直接在下方表格修改后再导入。")

    # 先尝试长表（姓名/科目/分数），不满足三要素再走宽表识别。
    long_records = eh.parse_long_table(df)
    if long_records is not None:
        records = long_records
        score_cols = []
        for rec in records:
            for subject in rec.get("scores", {}):
                if subject not in score_cols:
                    score_cols.append(subject)
        non_standard = eh.collect_non_standard_subjects(records)
        st.toast("已按长表识别，科目：" + "、".join(score_cols))
    else:
        detected = eh.detect_score_columns(df)
        if detected["problems"]:
            st.error("　".join(detected["problems"]))
            return
        score_cols = [subject for _col, subject in detected["subjects"]]
        non_standard = detected.get("non_standard_subjects", [])
        st.toast(f"识别到姓名列「{detected['name_col']}」，科目："
                   + "、".join(score_cols))
        records = eh.extract_scores(df, detected)

    # 非标科目保留原值入库（不阻断），只提示其不计入九科分析。
    if non_standard:
        st.info("以下科目不在九个标准学科内，已原样保留但不计入学科分析："
                + "、".join(non_standard))

    if new_exam_info is not None:
        st.markdown("**新考试满分设置**")
        fc1, fc2, fc3 = st.columns(3)
        full_scores = {}
        for idx, subject in enumerate(score_cols):
            col = (fc1, fc2, fc3)[idx % 3]
            full_scores[subject] = col.number_input(
                f"{subject}满分", min_value=1.0, step=10.0,
                value=_default_full_score(subject),
                key=f"score_new_full_{subject}")

    if not records:
        st.warning("没有有效成绩行。")
        return

    preview, subject_cols = eh.scores_preview_frame(records)
    problem_count = int((preview["问题"] != "").sum())
    if problem_count:
        st.warning(f"有 {problem_count} 行提示问题（缺姓名会跳过；缺考科目不计分），请核对。")

    edited = st.data_editor(
        preview, num_rows="dynamic", width="stretch", hide_index=True,
        key="score_preview_editor",
        column_config={
            "Excel行号": st.column_config.NumberColumn(disabled=True),
            "问题": st.column_config.TextColumn(disabled=True),
        })

    if st.button("✅ 确认导入成绩", type="primary", key="confirm_scores"):
        final_records = eh.preview_to_records(edited, subject_cols)
        try:
            with SessionLocal() as session:
                if new_exam_info is not None:
                    if not new_exam_info["name"].strip():
                        st.error("考试名称必填。")
                        return
                    exam = es.create_exam(
                        session,
                        new_exam_info["name"].strip(),
                        exam_date=new_exam_info["date"],
                        grade=new_exam_info["grade"],
                        term=new_exam_info["term"],
                        full_scores=full_scores)
                    session.flush()
                    exam_id = exam.id
                result = es.import_scores(session, exam_id, final_records)
                _auto_verify_plans(session, exam_id)
                session.commit()
        except ValueError as exc:
            st.error(str(exc))
            return

        st.session_state.pop("score_upload", None)
        st.session_state.pop("score_preview_editor", None)
        if new_exam_info is not None:
            for key in ("score_new_exam_name", "score_new_exam_date",
                        "score_new_exam_grade", "score_new_exam_term"):
                st.session_state.pop(key, None)
            for subject in subject_cols:
                st.session_state.pop(f"score_new_full_{subject}", None)
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
            _auto_verify_plans(session, exam_id)
            session.commit()
        st.toast(f"已保存：新写入 {result['scores_written']} 条，更新 {result['scores_updated']} 条。")
        st.rerun()


def _score_export_panel():
    """导出格式化成绩单 Excel。"""
    with SessionLocal() as session:
        exams = es.list_exams(session)
        classes = ss.list_classes(session)
    if not exams:
        st.caption("暂无考试数据可导出。")
        return

    options = {f"{e.name}（{e.exam_date}）": e.id for e in exams}
    chosen = st.selectbox("选择考试", list(options.keys()), key="score_report_exam")
    class_filter = st.selectbox(
        "选择班级", ["全部班级"] + classes, key="score_report_class")

    if st.button("生成成绩单", type="primary", key="make_score_report"):
        target_class = None if class_filter == "全部班级" else class_filter
        try:
            with SessionLocal() as session:
                data = es.build_score_report_xlsx(
                    session, options[chosen], class_name=target_class)
        except ValueError as exc:
            st.error(str(exc))
            return

        exam_name = chosen.split("（", 1)[0]
        prefix = class_filter if class_filter != "全部班级" else "全年级"
        raw_name = f"{prefix}_{exam_name}_成绩单.xlsx"
        filename = "".join("_" if char in r'<>:"/\|?*' else char
                           for char in raw_name).strip()
        st.download_button(
            "⬇️ 下载成绩单", data, file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_score_report")
def _score_history_panel():
    """跨考试历次成绩长表：按班级、学期、学年、考试类型筛选并导出 Excel。"""
    with SessionLocal() as session:
        exams = es.list_exams(session)
        classes = ss.list_classes(session)
    if not exams:
        st.caption("还没有考试成绩；新建考试并导入成绩后，这里会生成跨考试长表。")
        return

    semester_options = sorted(
        {academic_time.semester_name(e.exam_date) for e in exams
         if e.exam_date is not None},
        key=lambda name: min(
            academic_time.semester_order(e.exam_date) for e in exams
            if e.exam_date is not None
            and academic_time.semester_name(e.exam_date) == name))
    year_options = sorted(
        {academic_time.academic_year_name(e.exam_date) for e in exams
         if e.exam_date is not None})

    c1, c2, c3, c4 = st.columns(4)
    class_filter = c1.selectbox("班级", ["全部"] + classes, key="score_history_class")
    semester_filter = c2.selectbox(
        "学期", ["全部学期"] + semester_options, key="score_history_semester")
    year_filter = c3.selectbox(
        "学年", ["全部学年"] + year_options, key="score_history_year")
    type_filter = c4.selectbox(
        "考试类型", ["全部类型", "摸底", "月考", "期中", "期末", "其他"],
        key="score_history_type")

    selected_exam_ids = []
    for exam in exams:
        if exam.exam_date is None:
            continue
        if (semester_filter != "全部学期" and
                academic_time.semester_name(exam.exam_date) != semester_filter):
            continue
        if (year_filter != "全部学年" and
                academic_time.academic_year_name(exam.exam_date) != year_filter):
            continue
        if (type_filter != "全部类型" and
                academic_time.exam_type(exam.name) != type_filter):
            continue
        selected_exam_ids.append(exam.id)

    if not selected_exam_ids:
        st.caption("当前筛选条件下没有考试。")
        return

    with SessionLocal() as session:
        rows = es.student_score_history_rows(
            session,
            class_name=None if class_filter == "全部" else class_filter,
            exam_ids=selected_exam_ids)
    if not rows:
        st.caption("当前筛选条件下还没有成绩。")
        return

    history_df = pd.DataFrame(rows)
    st.caption(f"共 {len(history_df)} 行；一行代表一名学生、一场考试和一个科目。")
    st.dataframe(history_df, width="stretch", hide_index=True)
    _download_xlsx(history_df, "历次考试成绩长表.xlsx", label="⬇️ 导出 Excel")


# ---------------------------------------------------------------------------
# 标签页 3：单次考试分析
# ---------------------------------------------------------------------------

def _analysis_thresholds_panel():
    """考试分析及格线、优秀线（从设置页迁入，读写同一个本地 JSON）。"""
    with st.expander("⚙️ 考试分析线（及格线 / 优秀线）", expanded=False):
        current = analysis_settings.load_thresholds()
        st.caption("比例按各科或总分满分计算，保存后考试分析、Word、反思和学期报告统一使用。")
        with st.form("analysis_thresholds_form"):
            c1, c2 = st.columns(2)
            pass_value = c1.number_input(
                "及格线百分比", min_value=1, max_value=99, step=1,
                value=int(round(current["pass_ratio"] * 100)),
                help="例如 60 表示达到满分 60% 为及格。")
            excellent_value = c2.number_input(
                "优秀线百分比", min_value=1, max_value=99, step=1,
                value=int(round(current["excellent_ratio"] * 100)),
                help="必须高于及格线，例如 85 表示达到满分 85% 为优秀。")
            submitted = st.form_submit_button("💾 保存考试分析线", type="primary")
        if submitted:
            try:
                analysis_settings.save_thresholds({
                    "pass_ratio": pass_value / 100,
                    "excellent_ratio": excellent_value / 100,
                })
                st.toast("考试分析线已保存。")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))


def _ai_teaching_advice_panel(data, class_filter):
    """AI 教学建议（v2.6.0）：识别问题并给操作化入口。"""
    st.markdown("**🤖 AI教学建议**")
    subject = (data.get("subjects") or [None])[0]
    advice = []
    try:
        for subj, stt in (data.get("subject_stats") or {}).items():
            if stt.get("mean") is not None and stt.get("full_score"):
                ratio = stt["mean"] / stt["full_score"]
                if ratio < 0.6:
                    advice.append(f"{subj}均分偏低（得分率 {ratio*100:.0f}%），建议复习相关知识点。")
        total = data.get("total_stats") or {}
        if (total.get("std") or 0) and total.get("mean"):
            if total["std"] / max(total["mean"], 1) > 0.25:
                advice.append("成绩两极分化较明显，建议分层教学与分层作业。")
    except Exception:  # noqa: BLE001 —— 数据不全不影响给建议
        pass
    if not advice:
        advice.append("本次成绩整体平稳，可按计划推进；可针对薄弱知识点做小测巩固。")
    for a in advice:
        st.info(a)
    c1, c2 = st.columns(2)
    if c1.button("📝 根据建议生成复习课教案", key="advice_to_lesson"):
        st.session_state["_pending_app_route"] = "📚 备课"
        st.session_state["_pending_app_sub"] = "AI 备课"
        st.session_state["_pending_app_sub_key"] = "lesson_plan_tab"
        st.session_state["lesson_topic_prefill"] = f"{subject or ''}复习课"
        st.rerun()
    if c2.button("🧩 根据建议生成专项练习题", key="advice_to_questions"):
        st.session_state["_pending_app_route"] = "📚 备课"
        st.session_state["_pending_app_sub"] = "AI 出题"
        st.session_state["_pending_app_sub_key"] = "lesson_plan_tab"
        st.rerun()


def _student_watchlist_panel():
    """学生预警名单（v2.6.0）：按风险排序 + 生成辅导方案。"""
    from utils import agent_watchlist
    with st.expander("🚨 学生预警名单", expanded=False):
        with SessionLocal() as session:
            result = agent_watchlist.build_watchlist(session)
        items = result.get("items") or []
        if not items:
            st.success("当前没有需要预警的学生/班级。")
            return
        st.dataframe(pd.DataFrame([{
            "风险": "★" * int(it.get("risk") or 1),
            "对象": it.get("student_name") or it.get("title"),
            "原因": it.get("reason"),
            "建议": it.get("suggestion"),
        } for it in items]), hide_index=True, width="stretch")
        names = [it.get("student_name") or it.get("title") for it in items]
        pick = st.selectbox("选择要生成辅导方案的对象", names,
                            key="watchlist_pick")
        if st.button("🤖 生成辅导方案", key="watchlist_plan"):
            with SessionLocal() as session:
                out = agent_watchlist.generate_tutoring_plan(
                    session, student_name=str(pick))
            st.session_state["watchlist_plan_text"] = (
                out.get("plan") or out.get("reason") or "")
        text = st.session_state.get("watchlist_plan_text")
        if text:
            st.info(text)

def tab_exam_analysis():
    """考试分析：成绩分析 / 知识点掌握 / 多考试对比 / 教学效果评估（v2.5.0）。"""
    tabs = st.tabs(["📊 成绩分析", "🧩 知识点掌握",
                    "📊 多考试对比", "📈 教学效果评估"])
    with tabs[0]:
        _exam_analysis_panel()
    with tabs[1]:
        _knowledge_tab()
    with tabs[2]:
        _multi_exam_compare_panel()
    with tabs[3]:
        _teaching_effect_panel()


def _multi_exam_compare_panel():
    """多考试对比（v2.5.0）：选 2-5 场，对比均分/各科/及格率/分数段。"""
    st.subheader("📊 多考试对比")
    with SessionLocal() as session:
        exams = es.list_exams(session)
        classes = ss.list_classes(session)
    if len(exams) < 2:
        st.info("至少需要 2 场考试才能对比，先到「成绩管理」导入成绩。")
        return
    labels = {e.id: f"{e.name}（{e.exam_date}）" for e in exams}
    picked = st.multiselect("选择 2-5 场考试", list(labels),
                            format_func=lambda x: labels[x],
                            key="compare_exam_pick")
    class_choice = st.selectbox("班级", ["全部"] + classes, key="compare_exam_class")
    if not (2 <= len(picked) <= 5):
        st.caption("请选择 2-5 场考试。")
        return
    class_name = None if class_choice == "全部" else class_choice
    with SessionLocal() as session:
        data = es.compare_exams(session, picked, class_name=class_name,
                                thresholds=analysis_settings.load_thresholds())
    rows = data["exams"]
    if not rows:
        st.warning("所选考试没有可比数据。")
        return
    names = [r["name"] for r in rows]
    c1, c2 = st.columns(2)
    with c1:
        line = go.Figure(go.Scatter(x=names, y=[r["mean"] for r in rows],
                                    mode="lines+markers", line=dict(width=3),
                                    marker=dict(size=10)))
        line.update_layout(title="平均分变化", yaxis_title="平均分", height=340,
                           margin=dict(l=10, r=10, t=50, b=10))
        st.plotly_chart(line, use_container_width=True)
    with c2:
        subj_fig = go.Figure()
        for subj in data["subjects"]:
            subj_fig.add_trace(go.Bar(
                name=subj, x=names,
                y=[(r["subject_means"].get(subj) or 0) for r in rows]))
        subj_fig.update_layout(title="各科平均分对比", barmode="group",
                               yaxis_title="平均分", height=340,
                               margin=dict(l=10, r=10, t=50, b=10))
        st.plotly_chart(subj_fig, use_container_width=True)
    c3, c4 = st.columns(2)
    with c3:
        rate_fig = go.Figure()
        rate_fig.add_trace(go.Scatter(
            name="及格率", x=names,
            y=[(r["pass_rate"] or 0) * 100 for r in rows],
            mode="lines+markers"))
        rate_fig.add_trace(go.Scatter(
            name="优秀率", x=names,
            y=[(r["excellent_rate"] or 0) * 100 for r in rows],
            mode="lines+markers"))
        rate_fig.update_layout(title="及格率 / 优秀率变化", yaxis_title="比例(%)",
                               height=340, margin=dict(l=10, r=10, t=50, b=10))
        st.plotly_chart(rate_fig, use_container_width=True)
    with c4:
        band_fig = go.Figure()
        band_labels = ["不及格", "及格", "良好", "优秀"]
        for r in rows:
            bands = r.get("rate_bands") or []
            vals = [b.get("count", 0) for b in bands]
            band_fig.add_trace(go.Bar(name=r["name"], x=band_labels[:len(vals)],
                                      y=vals))
        band_fig.update_layout(title="得分率分布变化", barmode="stack",
                               yaxis_title="人数", height=340,
                               margin=dict(l=10, r=10, t=50, b=10))
        st.plotly_chart(band_fig, use_container_width=True)
    _render_multi_exam_ai_report(rows)


def _render_multi_exam_ai_report(rows: list[dict]):
    """多考试对比 AI 报告；AI 不可用给规则兜底小结。"""
    if st.button("🤖 生成考试对比分析报告", key="compare_exam_ai"):
        means = [(r["name"], r["mean"]) for r in rows if r["mean"] is not None]
        if len(means) >= 2:
            first, last = means[0], means[-1]
            diff = last[1] - first[1]
            trend_text = ("整体呈上升趋势" if diff > 0
                          else ("整体下滑" if diff < 0 else "整体持平"))
            fallback = (f"从「{first[0]}」到「{last[0]}」，班级平均分"
                        f"{'+' if diff >= 0 else ''}{diff:.1f} 分，{trend_text}。")
        else:
            fallback = "可比数据不足，无法给出趋势结论。"
        advice = fallback
        if llm_client.is_configured():
            try:
                text = "；".join(
                    f"{r['name']}：均分{r['mean']}，及格率{(r['pass_rate'] or 0) * 100:.0f}%，"
                    f"优秀率{(r['excellent_rate'] or 0) * 100:.0f}%" for r in rows)
                advice = llm_client.chat(
                    "你是教学分析助手。根据多次考试数据写一段简洁的中文对比分析，"
                    "指出进步与退步，给出可执行建议，不超过150字。",
                    text, temperature=0.4).strip() or fallback
            except Exception:  # noqa: BLE001
                advice = fallback
        st.session_state["compare_exam_ai_report"] = advice
    report = st.session_state.get("compare_exam_ai_report")
    if report:
        st.info(report)


def _teaching_effect_panel():
    """教学效果评估（v2.5.0）：基于逐题批改的知识点时间序列。"""
    st.subheader("📈 教学效果评估")
    st.caption("知识点数据只来自逐题批改；普通考试分科分不拆分知识点。")
    with SessionLocal() as session:
        subjects = kgs.list_trend_subjects(session)
    if not subjects:
        st.info("还没有逐题批改数据，先去「作业批改」批改作业。")
        return
    subject = st.selectbox("学科", subjects, key="teach_effect_subject")
    with SessionLocal() as session:
        timeline = hscore.subject_knowledge_timeline(session, subject)
    summary = stats_mod.summarize_teaching_effect(timeline.get("series") or {})
    if not summary["rows"]:
        st.info("该学科暂无可用于评估的知识点数据。")
        return
    st.dataframe(pd.DataFrame(summary["rows"]),
                 hide_index=True, width="stretch")
    if summary["good"]:
        st.success("教学效果较好：" + "、".join(summary["good"]))
    if summary["need_improve"]:
        st.warning("需要改进：" + "、".join(summary["need_improve"]))
    _render_teaching_effect_ai(subject, summary)


def _render_teaching_effect_ai(subject: str, summary: dict):
    """教学效果评估 AI 报告；AI 不可用给规则兜底。"""
    if st.button("🤖 生成教学效果评估报告", key="teach_effect_ai"):
        fallback = ("效果较好的知识点：" + ("、".join(summary["good"]) or "暂无")
                    + "；需改进的知识点："
                    + ("、".join(summary["need_improve"]) or "暂无") + "。")
        advice = fallback
        if llm_client.is_configured():
            try:
                text = "；".join(
                    f"{r['知识点']}：教学前{r['教学前']}→教学后{r['教学后']}，"
                    f"效果{r['效果']}" for r in summary["rows"][:10])
                advice = llm_client.chat(
                    "你是教学分析助手。根据知识点掌握率变化，写一段中文教学效果评估，"
                    "指出教学效果好与需改进的知识点并给建议，不超过150字。",
                    f"学科：{subject}\n{text}", temperature=0.4).strip() or fallback
            except Exception:  # noqa: BLE001
                advice = fallback
        st.session_state["teach_effect_ai_report"] = advice
    report = st.session_state.get("teach_effect_ai_report")
    if report:
        st.info(report)


def _exam_analysis_panel():
    """选学期、考试和班级，展示指标、图表、排名（含进退步）、AI 总结。"""
    st.subheader("单次考试分析")

    _analysis_thresholds_panel()

    with SessionLocal() as session:
        all_exams = es.list_exams(session)
        terms = es.list_exam_terms(session)
        classes = ss.list_classes(session)

    term_filter = st.selectbox(
        "学期", ["全部学期"] + terms, key="analysis_term_filter")
    exams = [e for e in all_exams
             if term_filter == "全部学期" or (e.term or "") == term_filter]
    if not exams:
        st.info("还没有考试和成绩，先到「成绩管理」新建考试并导入成绩。")
        return

    exam_options = {f"{e.name}（{e.exam_date}）": e.id for e in exams}
    c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
    # v2.4.1：从智能组卷“查看分析”跳来的预选考试，命中即同步并消费。
    preset_label = st.session_state.pop("analysis_exam_pick_label", None)
    if preset_label and preset_label not in exam_options:
        preset_label = None
    chosen = c1.selectbox(
        "选择考试", list(exam_options.keys()),
        index=(list(exam_options).index(preset_label)
               if preset_label else 0),
        key="analysis_exam")
    class_filter = c2.selectbox("班级", ["全部"] + classes, key="analysis_class")
    exam_id = exam_options[chosen]

    with SessionLocal() as session:
        view_subjects = es.exam_subjects(session, exam_id)
    view_options = ["总分总览"] + view_subjects
    view = c3.selectbox("分析视角", view_options, index=0, key="analysis_view")
    rank_order = c4.radio(
        "排名顺序", ["高分到低分", "低分到高分"], horizontal=False,
        key="analysis_rank_order")

    class_arg = None if class_filter == "全部" else class_filter
    thresholds = analysis_settings.load_thresholds()
    with SessionLocal() as session:
        if view == "总分总览":
            data = es.analyze_exam(
                session, exam_id, class_name=class_arg, thresholds=thresholds)
        else:
            data = es.analyze_subject(
                session, exam_id, view, class_name=class_arg,
                thresholds=thresholds)
    if not data or not data["rows"]:
        st.warning("这场考试还没有成绩数据。")
        return
    data["rows"] = _rows_in_rank_order(
        data["rows"], "total" if view == "总分总览" else view, rank_order)

    _term_report_export(term_filter, class_filter, thresholds)

    if view == "总分总览":
        _render_metric_cards(data)
        st.divider()
        _render_band_and_subject_charts(data, rank_order)
        st.divider()
        _render_rank_table(data)
        st.divider()
        _render_ai_exam_summary(data, class_filter)
        st.divider()
        _ai_teaching_advice_panel(data, class_filter)
    else:
        _render_subject_view(data, rank_order)



def _render_class_compare_entry(session, exam_id, classes):
    """v1.9.0：班级对比入口，支持 2-5 个班，输出表格、图表和 Word 报告。"""
    with st.expander("📊 班级对比（2-5 个班）"):
        if len(classes) < 2:
            st.caption("至少要有 2 个班级的成绩才能对比。")
            return
        picked = st.multiselect("选择对比班级", classes,
                                default=classes[:min(3, len(classes))],
                                key="class_compare_pick")
        if st.button("开始对比", key="class_compare_run"):
            from utils import class_compare_service
            result = class_compare_service.compare_exam_classes(
                session, exam_id, picked)
            st.dataframe(pd.DataFrame([{
                "班级": c["class_name"], "人数": c["count"],
                "平均分": c["mean"], "最高": c["max"], "最低": c["min"],
                "及格率": c["pass_rate"], "优秀率": c["excellent_rate"],
            } for c in result["classes"]]), hide_index=True, width="stretch")
            _chart_df = pd.DataFrame({
                "班级": [c["class_name"] for c in result["classes"]],
                "平均分": [c["mean"] for c in result["classes"]]})
            st.bar_chart(_chart_df.set_index("班级"), use_container_width=True)
            _blob = class_compare_service.export_compare_report(session, result)
            st.download_button(
                "⬇️ 导出对比报告 Word", _blob,
                file_name="班级对比报告.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


def _rows_in_rank_order(rows, score_key: str, rank_order: str):
    """按分数展示排序；并列名次保持稳定，缺考放最后。"""
    reverse = rank_order == "低分到高分"
    return sorted(
        rows,
        key=lambda row: (
            row.get(score_key) is None,
            -(row.get(score_key) or 0) if not reverse else (row.get(score_key) or 0),
            row.get("class_name") or "",
            row.get("student_id") or 0,
        ))


DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _safe_filename(text: str) -> str:
    """清理 Windows 文件名里不能出现的字符。"""
    for ch in '\\/:*?"<>|':
        text = text.replace(ch, "_")
    return text.strip(" _") or "学期报告"


def _threshold_caption(thresholds: dict, full_score: float | None = None) -> str:
    """当前及格线/优秀线说明。"""
    pass_pct = thresholds["pass_ratio"] * 100
    excellent_pct = thresholds["excellent_ratio"] * 100
    text = f"及格线=满分{pass_pct:g}%，优秀线=满分{excellent_pct:g}%"
    if full_score:
        text += f"；本次满分 {full_score:g}"
    return text + "。"


def _term_report_export(term_filter: str, class_filter: str, thresholds: dict):
    """考试分析页的学期报告 Word 导出入口。"""
    if term_filter == "全部学期":
        st.info("请先在上方选择具体学期，再导出学期报告。")
        return
    if not st.button("⬇️ 导出学期报告（Word）"):
        return
    try:
        with SessionLocal() as session:
            blob = trs.build_term_report(
                session, term_filter,
                None if class_filter == "全部" else class_filter,
                thresholds=thresholds)
        scope = "" if class_filter == "全部" else f"_{class_filter}"
        st.download_button(
            "💾 保存学期报告", blob,
            file_name=f"{_safe_filename(term_filter)}{scope}_学期报告.docx",
            mime=DOCX_MIME)
        st.toast("学期报告已生成，点上方按钮保存。")
    except Exception as exc:
        st.error(f"学期报告生成失败：{exc}")


def rank_chart_data(rows: list[dict], key: str,
                    descending: bool = False) -> tuple[list[str], list[float]]:
    """取姓名和分数；默认升序，条形图反转轴后最高分在最上方。"""
    pairs = []
    for r in rows:
        value = r.get(key)
        if value is None:
            continue
        label = r.get("name") or ""
        if r.get("class_name"):
            label = f"{label}（{r['class_name']}）"
        pairs.append((label, float(value)))
    pairs.sort(key=lambda x: x[1], reverse=descending)
    return [x[0] for x in pairs], [x[1] for x in pairs]


def _render_band_chart(bands, subject_label):
    """得分率分段：柱状图（默认）/ 饼图切换。"""
    labels = [b["label"] for b in bands]
    counts = [b["count"] for b in bands]
    chart_type = st.radio(
        "得分率分段图类型", ["柱状图", "饼图"], horizontal=True,
        key=f"band_chart_type_{subject_label}")
    if chart_type == "饼图":
        pie = [(lab, c) for lab, c in zip(labels, counts) if c > 0]
        fig = go.Figure(go.Pie(
            labels=[x[0] for x in pie], values=[x[1] for x in pie],
            textinfo="label+percent", hole=0.35))
        fig.update_layout(
            height=360, margin=dict(l=10, r=10, t=30, b=10),
            title=f"{subject_label}得分率分段占比", showlegend=True)
    else:
        fig = go.Figure(go.Bar(
            x=labels, y=counts, text=counts, marker_color="#4c78a8"))
        fig.update_layout(
            height=320, margin=dict(l=10, r=10, t=30, b=10),
            title=f"{subject_label}得分率分段",
            xaxis_title="得分率分段", yaxis_title="人数", showlegend=False)
    st.plotly_chart(fig, width="stretch")


def _render_rank_bar_chart(rows, key, title, x_axis_title, high_to_low=True,
                           full_score=None):
    """学生排名横向条形图；传满分时悬停显示得分率。"""
    names, values = rank_chart_data(rows, key, descending=not high_to_low)
    if not names:
        st.caption("暂无可绘制的分数。")
        return
    hover_texts = []
    for name, value in zip(names, values):
        if full_score and full_score > 0:
            rate = value / full_score * 100
            hover_texts.append(f"{name}<br>原始分：{value:g}<br>满分：{full_score:g}<br>得分率：{rate:.1f}%")
        else:
            hover_texts.append(f"{name}<br>分数：{value:g}")
    fig = go.Figure(go.Bar(
        y=names, x=values, orientation="h", text=values,
        marker_color="#1F4E79", customdata=hover_texts,
        hovertemplate="%{customdata}<extra></extra>"))
    fig.update_layout(
        height=max(320, 26 * len(names) + 120),
        margin=dict(l=10, r=10, t=40, b=10),
        title=title, xaxis_title=x_axis_title, yaxis_title="学生",
        yaxis=dict(autorange="reversed"), showlegend=False)
    st.plotly_chart(fig, width="stretch")


def _fmt_pct(rate):
    return "—" if rate is None else f"{rate * 100:.1f}%"


def _render_six_metric_cards(stats_data: dict, thresholds: dict, full_score: float):
    """总分和单科统一只展示 6 项指标，不显示中位数和标准差。"""
    cols = st.columns(6)
    cols[0].metric("参考人数", stats_data["count"])
    cols[1].metric("平均分", "—" if stats_data["mean"] is None else f"{stats_data['mean']:g}")
    cols[2].metric("最高分", "—" if stats_data["max"] is None else f"{stats_data['max']:g}")
    cols[3].metric("最低分", "—" if stats_data["min"] is None else f"{stats_data['min']:g}")
    cols[4].metric("及格率", _fmt_pct(stats_data["pass_rate"]))
    cols[5].metric("优秀率", _fmt_pct(stats_data["excellent_rate"]))
    st.caption(_threshold_caption(thresholds, full_score))


def _render_metric_cards(data):
    _render_six_metric_cards(
        data["total_stats"], data["thresholds"], data["total_full"])


def _render_band_and_subject_charts(data, rank_order):
    """分数段、各科均分对比和总分排名图。"""
    subjects = data["subjects"]
    subject_stats = data["subject_stats"]
    high_to_low = rank_order == "高分到低分"

    st.markdown("**分数段分布（按科目）**")
    subj = st.selectbox("选择科目看分数段", subjects, key="band_subject")
    _render_band_chart(subject_stats[subj]["rate_bands"], subj)

    st.markdown("**各科得分率对比**")
    rates = []
    hover_texts = []
    for item_subject in subjects:
        stt = subject_stats[item_subject]
        avg = stt["mean"]
        full = stt["full_score"]
        rate = round(avg / full * 100, 1) if avg is not None and full else None
        rates.append(rate or 0)
        hover_texts.append(f"{item_subject}<br>原始分：{avg if avg is None else format(avg, 'g')}<br>满分：{full:g}<br>得分率：{rate}%")
    compare_type = st.radio(
        "得分率对比图类型", ["柱状图", "折线图"], horizontal=True,
        key="mean_compare_type")
    if compare_type == "折线图":
        fig2 = go.Figure(go.Scatter(
            x=subjects, y=rates, mode="lines+markers+text",
            text=rates, line=dict(width=3, color="#59a14f"),
            customdata=hover_texts,
            hovertemplate="%{customdata}<extra></extra>"))
    else:
        fig2 = go.Figure(go.Bar(
            x=subjects, y=rates, text=rates, marker_color="#59a14f",
            customdata=hover_texts,
            hovertemplate="%{customdata}<extra></extra>"))
    fig2.update_layout(height=320, margin=dict(l=10, r=10, t=30, b=10),
                       title="各科得分率对比", xaxis_title="科目",
                       yaxis_title="得分率(%)", yaxis=dict(range=[0, 100]),
                       showlegend=False)
    st.plotly_chart(fig2, width="stretch")

    st.markdown(f"**学生总分排名图（总分满分 {data['total_full']:g}）**")
    title = f"学生总分排名（{rank_order}）"
    _render_rank_bar_chart(
        data["rows"], "total", title, "总分", high_to_low,
        full_score=data["total_full"])

    # v1.9.8：成绩分布箱线图改为得分率。
    st.markdown("**成绩得分率箱线图**")
    box_groups = {}
    for row in data.get("rows", []):
        if row.get("total") is None:
            continue
        rate = row["total"] / data["total_full"] * 100 if data["total_full"] else None
        if rate is None:
            continue
        box_groups.setdefault(row.get("class_name") or "未分班", []).append(rate)
    if box_groups:
        box_fig = go.Figure()
        for class_name, values in box_groups.items():
            box_fig.add_trace(go.Box(y=values, name=class_name, boxmean=True))
        box_fig.update_layout(
            title="成绩得分率箱线图", yaxis_title="得分率(%)",
            yaxis=dict(range=[0, 100]), height=380, showlegend=True)
        st.plotly_chart(box_fig, width="stretch")
    else:
        st.caption("暂无成绩数据可绘制箱线图。")


def _delta_html(delta_info, score_label="总分"):
    if not delta_info:
        return "—"
    parts = []
    score_delta = delta_info.get("score_delta")
    if score_delta is not None:
        sign = "↑" if score_delta > 0 else "↓" if score_delta < 0 else "—"
        color = "#1a9850" if score_delta > 0 else "#d73027" if score_delta < 0 else "#666"
        parts.append(f"<span style='color:{color}'>{score_label}{sign}{abs(score_delta):g}</span>")
    rank_delta = delta_info.get("rank_delta")
    if rank_delta is not None and rank_delta != 0:
        sign = "↑" if rank_delta > 0 else "↓"
        color = "#1a9850" if rank_delta > 0 else "#d73027"
        parts.append(f"<span style='color:{color}'>名次{sign}{abs(rank_delta)}</span>")
    elif rank_delta == 0:
        parts.append("<span style='color:#666'>名次持平</span>")
    return "　".join(parts) if parts else "—"


def _render_rank_table(data):
    """排名表：搜索、并列名次、进退步红绿标记。"""
    st.markdown("**班级排名表（含与上次考试的进退步）**")
    keyword = st.text_input("搜索姓名", key="rank_search")
    subjects = data["subjects"]
    deltas = data["deltas"]
    rows = data["rows"]
    if keyword.strip():
        rows = [r for r in rows if keyword.strip() in (r["name"] or "")]

    table = []
    for r in rows:
        table.append({
            "班级": r["class_name"] or "", "姓名": r["name"],
            **{s: ("" if r[s] is None else f"{r[s]:g}") for s in subjects},
            "总分": "" if r["total"] is None else f"{r['total']:g}",
            "班名": r["total_rank"] if r["total_rank"] is not None else "—",
            "进退步": _delta_html(deltas.get(r["student_id"])),
        })
    st.markdown(pd.DataFrame(table).to_html(escape=False, index=False),
                unsafe_allow_html=True)
    st.caption("绿色=进步，红色=退步；只比较日期相邻的两次考试；缺考不参与排名。")


def _render_subject_view(data, rank_order):
    """单科视角：指标、三段分数分布、单科排名图和排名表。"""
    subject = data["subject"]
    high_to_low = rank_order == "高分到低分"
    _render_six_metric_cards(data["stats"], data["thresholds"], data["full_score"])

    st.divider()
    _render_band_chart(data["stats"]["rate_bands"], subject)

    st.divider()
    st.markdown(f"**{subject}学生排名图**")
    _render_rank_bar_chart(
        data["rows"], subject, f"{subject}单科排名（{rank_order}，满分 {data['full_score']:g}）",
        subject, high_to_low, full_score=data["full_score"])

    st.divider()
    st.markdown(f"**{subject}班内排名表（含与上次考试同科进退步）**")
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
            "进退步": _delta_html(deltas.get(r["student_id"]), score_label=subject),
        })
    st.markdown(pd.DataFrame(table).to_html(escape=False, index=False),
                unsafe_allow_html=True)
    st.caption("绿色=进步，红色=退步；只比较日期相邻两次考试的同一科目。")


def _build_exam_data_text(data, class_filter) -> str:
    """发给 AI 的统计数据；不含中位数、标准差。"""
    lines = [f"考试：{data['exam'].name}；范围：{class_filter}；"
             f"总分满分：{data['total_full']:g}；参考人数：{data['total_stats']['count']}"]
    t = data["total_stats"]
    lines.append(
        f"总分：均分{t['mean']}、最高{t['max']}、最低{t['min']}、"
        f"及格率{_fmt_pct(t['pass_rate'])}、优秀率{_fmt_pct(t['excellent_rate'])}")
    for subject in data["subjects"]:
        stt = data["subject_stats"][subject]
        band_text = "，".join(f"{b['label']}{b['count']}人" for b in stt["bands"])
        lines.append(f"{subject}（满分{stt['full_score']:g}）：均分{stt['mean']}，"
                     f"及格率{_fmt_pct(stt['pass_rate'])}，"
                     f"优秀率{_fmt_pct(stt['excellent_rate'])}；分数段：{band_text}")
    return "\n".join(lines)


def _render_ai_exam_summary(data, class_filter):
    st.markdown("**AI 考试分析总结**")
    data_text = _build_exam_data_text(data, class_filter)
    with st.expander("查看发给 AI 的统计数据", expanded=False):
        st.code(data_text)
    _ai_button("exam", lambda: data_text, "🤖 生成考试分析",
               help_text="依据上面的统计数据生成不超过 300 字的分析")
    _export_word_report(data, class_filter)


def _export_word_report(data, class_filter):
    """导出单次考试 Word；只写界面保留的 6 项指标。"""
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
            f"参考 {t['count']} 人，均分 {t['mean']}，最高 {t['max']}，最低 {t['min']}，"
            f"及格率 {_fmt_pct(t['pass_rate'])}，优秀率 {_fmt_pct(t['excellent_rate'])}。")

        doc.add_heading("各科情况", level=2)
        for subject in data["subjects"]:
            stt = data["subject_stats"][subject]
            doc.add_paragraph(
                f"{subject}：均分 {stt['mean']}，及格率 {_fmt_pct(stt['pass_rate'])}，"
                f"优秀率 {_fmt_pct(stt['excellent_rate'])}。", style="List Bullet")

        doc.add_heading("班级排名", level=2)
        subjects = data["subjects"]
        table = doc.add_table(rows=1, cols=4 + len(subjects))
        table.style = "Light Grid Accent 1"
        headers = ["班级", "姓名"] + subjects + ["总分", "班名"]
        for i, header in enumerate(headers):
            table.rows[0].cells[i].text = header
        for r in data["rows"]:
            cells = table.add_row().cells
            cells[0].text = r["class_name"] or ""
            cells[1].text = r["name"]
            for j, subject in enumerate(subjects):
                cells[2 + j].text = "" if r[subject] is None else f"{r[subject]:g}"
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
        st.toast("报告已生成，点上方按钮保存。")
    except Exception as exc:
        st.error(f"导出失败：{exc}")


# ---------------------------------------------------------------------------
# 标签页 4：趋势分析
# ---------------------------------------------------------------------------

def _trend_time_options(exams) -> list[str]:
    """时间筛选选项：全部 + 学期（按学期内最早考试日期升序）+ 学年（升序）。"""
    dated = [e for e in exams if e.exam_date is not None]
    first_date: dict[str, object] = {}
    for exam in dated:
        name = academic_time.semester_name(exam.exam_date)
        if name not in first_date or exam.exam_date < first_date[name]:
            first_date[name] = exam.exam_date
    semester_names = sorted(first_date, key=lambda name: first_date[name])
    years = sorted({academic_time.academic_year_name(e.exam_date)
                    for e in dated})
    return (["全部"]
            + [f"学期：{name}" for name in semester_names]
            + [f"学年：{name}" for name in years])


def _trend_filter_exams(exams, time_filter: str, range_value: str) -> tuple[list[int], int | None]:
    """先按时间筛选过滤，再返回考试 ID 与最近 N 场截断数；考试按日期升序。"""
    dated = [e for e in exams if e.exam_date is not None]
    if time_filter == "全部":
        filtered = list(exams)  # 含日期为空的旧考试，仅在“全部”出现
    elif time_filter.startswith("学期："):
        wanted = time_filter.replace("学期：", "", 1)
        filtered = [e for e in dated
                    if academic_time.semester_name(e.exam_date) == wanted]
    elif time_filter.startswith("学年："):
        wanted = time_filter.replace("学年：", "", 1)
        filtered = [e for e in dated
                    if academic_time.academic_year_name(e.exam_date) == wanted]
    else:
        filtered = list(exams)

    filtered = sorted(filtered,
                      key=lambda e: (e.exam_date is None, e.exam_date, e.id))
    limit = None
    if range_value.startswith("最近") and range_value.endswith("次"):
        try:
            limit = int(range_value.replace("最近", "").replace("次", "").strip())
        except ValueError:
            limit = None
    return [e.id for e in filtered], limit


def tab_trends():
    """班级趋势和个人趋势；时间筛选与最近场数两个维度叠加。"""
    st.subheader("趋势分析")

    with SessionLocal() as session:
        exams = es.list_exams(session)
        classes = ss.list_classes(session)
    if not exams:
        st.info("还没有考试数据。")
        return

    with SessionLocal() as session:
        trend_subjects = sorted({
            subject for exam in exams
            for subject in es.exam_subjects(session, exam.id)
        })

    c1, c2, c3, c4 = st.columns(4)
    time_filter = c1.selectbox(
        "时间筛选", _trend_time_options(exams), index=0, key="trend_time_filter")
    range_value = c2.selectbox(
        "显示范围",
        ["最近 3 次", "最近 5 次", "最近 10 次", "全部"],
        index=1, key="trend_range")
    class_filter = c3.selectbox("班级", ["全部"] + classes, key="trend_class")
    trend_subject = c4.selectbox(
        "科目", ["全部科目"] + trend_subjects, index=0, key="trend_subject")

    selected_exam_ids, limit = _trend_filter_exams(
        exams, time_filter, range_value)
    if not selected_exam_ids:
        st.caption("所选范围内没有考试。")
        return
    subject_arg = None if trend_subject == "全部科目" else trend_subject

    with st.expander("📈 班级整体趋势", expanded=True):
        _class_trend_chart(
            class_filter, subject_arg, selected_exam_ids, limit)

    st.divider()
    with st.expander("🧑‍🎓 学生个人趋势", expanded=True):
        _student_trend_panel(
            class_filter, subject_arg, selected_exam_ids, limit)

    st.divider()
    with st.expander("🏆 班级进步追踪", expanded=False):
        _class_progress_panel(
            None if class_filter == "全部" else class_filter,
            subject_arg, selected_exam_ids)

    st.divider()
    with st.expander("🧑‍🏫 班级分层与分层作业", expanded=False):
        _tiered_homework_panel(classes)


def _class_progress_panel(class_filter, subject, exam_ids):
    """班级进步追踪（v2.5.0）：名次变化、进步榜、退步预警、进步分布。"""
    with SessionLocal() as session:
        data = es.class_progress_tracking(
            session, class_name=class_filter, subject=subject,
            exam_ids=exam_ids)
    if data.get("need") or not data.get("rows"):
        st.info("至少需要同一班级的两场考试才能追踪进步。")
        return
    rows = data["rows"]
    st.dataframe(pd.DataFrame([{
        "学生": r["name"], "上次名次": r["prev_rank"],
        "本次名次": r["curr_rank"], "进步指数": r["index"]}
        for r in rows]), hide_index=True, width="stretch")
    c1, c2 = st.columns(2)
    with c1:
        top = data["improve_top"]
        if top:
            st.markdown("**进步榜 TOP10**")
            st.dataframe(pd.DataFrame([{
                "学生": r["name"], "进步指数": r["index"]} for r in top]),
                hide_index=True, width="stretch")
    with c2:
        dist = data["distribution"]
        pie = go.Figure(go.Pie(labels=list(dist.keys()),
                               values=list(dist.values()), hole=0.4,
                               marker_colors=["#16a34a", "#9ca3af", "#dc2626"]))
        pie.update_layout(title="进步 / 持平 / 退步 分布", height=300,
                          margin=dict(l=10, r=10, t=50, b=10))
        st.plotly_chart(pie, use_container_width=True)
    warn = data["regress_warn"]
    if warn:
        st.warning("退步预警（退步>10%）："
                   + "、".join(r["name"] for r in warn))


def _trend_compare_neighbor(session, class_filter, subject, exam_ids,
                             kind="mom"):
    """计算相邻考试（环比）或上学年同学期考试（同比）的均分对比。

    返回 [{label, current, compare, delta}]；缺可比数据的点 compare 为 None。
    """
    trend = es.class_trend(
        session, None if class_filter == "全部" else class_filter,
        subject=subject, exam_ids=exam_ids)
    exams_meta = trend["exam_meta"]
    key = subject or "total"
    result = []
    for i, point in enumerate(exams_meta):
        current = point["values"].get(key)
        current_full = _point_full_score(point, key)
        current_rate = _rate_value(current, current_full)
        compare = None
        if kind == "mom":
            if i > 0:
                compare = exams_meta[i - 1]["values"].get(key)
                compare_full = _point_full_score(exams_meta[i - 1], key)
        else:
            # 同比：找上学年同学期（学期键相同、年份早一年）的考试。
            cur_year, cur_season = academic_time.semester_key(
                point["exam_date"])
            compare_full = None
            for prev in exams_meta[:i]:
                py, ps = academic_time.semester_key(prev["exam_date"])
                if ps == cur_season and py == cur_year - 1:
                    compare = prev["values"].get(key)
                    compare_full = _point_full_score(prev, key)
                    break
        compare_rate = _rate_value(compare, compare_full)
        delta = (round(current - compare, 2)
                 if current is not None and compare is not None else None)
        result.append({
            "label": point.get("label") or point["exam_name"],
            "current": current, "current_full": current_full,
            "current_rate": current_rate,
            "compare": compare, "compare_full": compare_full,
            "compare_rate": compare_rate, "delta": delta})
    return result


def _render_trend_mom(class_filter, subject, exam_ids):
    """环比 / 同比：与上一相邻考试、上学年同学期考试对比。"""
    with SessionLocal() as session:
        mom = _trend_compare_neighbor(
            session, class_filter, subject, exam_ids, "mom")
        yoy = _trend_compare_neighbor(
            session, class_filter, subject, exam_ids, "yoy")
    st.caption("环比（相邻考试均分变化）")
    st.dataframe(pd.DataFrame([{
        "考试": r["label"], "本次均分": r["current"],
        "本次满分": r["current_full"], "本次得分率": r["current_rate"],
        "上次均分": r["compare"], "上次满分": r["compare_full"],
        "上次得分率": r["compare_rate"], "变化": r["delta"],
    } for r in mom]), hide_index=True, width="stretch")
    valid_yoy = [r for r in yoy if r["compare"] is not None]
    st.caption("同比（上学年同学期）")
    if valid_yoy:
        st.dataframe(pd.DataFrame([{
            "考试": r["label"], "本次均分": r["current"],
            "本次得分率": r["current_rate"],
            "去年同期": r["compare"], "去年得分率": r["compare_rate"],
            "变化": r["delta"],
        } for r in valid_yoy]), hide_index=True, width="stretch")
    else:
        st.caption("暂无上学年同学期的可比考试，不编造同比结果。")


def _render_multi_class_trend(classes, subject, exam_ids):
    """跨班级均分走势对比（2-5 个班）。"""
    picked = st.multiselect("选择对比班级", classes,
                            default=classes[:min(3, len(classes))],
                            key="trend_compare_pick")
    if not st.button("生成对比走势", key="trend_compare_run"):
        return
    if not 2 <= len(picked) <= 5:
        st.warning("请选择 2-5 个班级。")
        return
    with SessionLocal() as session:
        from utils import class_compare_service
        result = class_compare_service.compare_class_trends(
            session, picked, subject=subject, exam_ids=exam_ids)
    if not result["points"]:
        st.caption("所选范围内没有可对比的成绩。")
        return
    score_mode = st.radio(
        "跨班趋势显示", ["原始分", "得分率"], horizontal=True,
        index=1 if subject else 0, key="trend_compare_score_mode")
    fig = go.Figure()
    use_rate = score_mode == "得分率" and bool(subject)
    for cls in result["class_names"]:
        y_values = (result["rate_series"][cls] if use_rate
                    else result["series"][cls])
        fig.add_trace(go.Scatter(
            x=result["exams"], y=y_values,
            mode="lines+markers", name=cls, connectgaps=False))
    fig.update_layout(
        height=420,
        yaxis_title="得分率(%)" if use_rate else "平均分",
        title="跨班级得分率走势" if use_rate else "跨班级均分走势")
    if use_rate:
        fig.update_layout(yaxis=dict(range=[0, 100]))
    st.plotly_chart(fig, width="stretch")
    st.caption("各次考试满分可能不同；总分趋势保留原始分。")
    st.dataframe(pd.DataFrame(result["points"]), hide_index=True,
                 width="stretch")


def _apply_limit(names, limit):
    """按最后 limit 场截断（None 表示全部）。"""
    if limit and len(names) > limit:
        return names[-limit:]
    return names


def _point_full_score(point, key):
    """读取趋势点某科或总分满分。"""
    if key == "total":
        return point.get("total_full_score")
    return point.get("full_scores", {}).get(key)


def _rate_value(score, full_score):
    """计算单点得分率。"""
    if score is None or full_score is None:
        return None
    try:
        if float(full_score) <= 0:
            return None
        return round(float(score) / float(full_score) * 100, 1)
    except (TypeError, ValueError):
        return None


def _class_trend_chart(class_filter, subject=None, exam_ids=None, limit=None):
    """班级趋势；单科默认得分率、可切回原始分，总分始终保留原始分。

    以 exam_id 作为多线对齐的类目键；头部只放考试/日期，各科满分进每条线。
    """
    with SessionLocal() as session:
        trend = es.class_trend(
            session,
            None if class_filter == "全部" else class_filter,
            subject=subject, exam_ids=exam_ids)

    count = len(_apply_limit(trend["exams"], limit))
    start = len(trend["exams"]) - count
    points_shown = trend["exam_meta"][start:]
    if not points_shown:
        st.caption("所选范围内没有数据。")
        return

    # 统一头部类目：编号在当前显示范围内从 1，不含满分（各科满分不同）
    headers = [
        chart_service.trend_header(
            index, point["exam_name"],
            point["exam_date"].isoformat() if hasattr(
                point["exam_date"], "isoformat") else "")
        for index, point in enumerate(points_shown, start=1)
    ]
    id_to_header = {point["exam_id"]: headers[i]
                    for i, point in enumerate(points_shown)}

    score_mode = st.radio(
        "班级趋势显示", ["原始分", "得分率"], horizontal=True, index=1,
        key="trend_class_score_mode")

    def build_line(item_subject, is_total):
        point_map = {}
        for point in points_shown:
            header = id_to_header[point["exam_id"]]
            raw_value = point["values"].get(item_subject)
            full_score = (point.get("total_full_score") if is_total
                          else point.get("full_scores", {}).get(item_subject))
            if raw_value is None:
                continue
            point_map[header] = {
                "score": raw_value,
                "full": full_score,
                "rate": _rate_value(raw_value, full_score),
            }
        name = "总分" if is_total else item_subject
        return {"name": name, "points": point_map}

    def show_figure(series_keys, title, total_chart=False):
        # 单科图随开关切原始分/得分率；总分图恒为原始分
        rate_only = score_mode == "得分率" and not total_chart
        lines = [build_line(key, total_chart) for key in series_keys]
        y_title = "得分率(%)" if rate_only else "平均分"
        fig = chart_service.build_trend_figure(
            lines, headers, title=title, y_title=y_title,
            fixed_percent=rate_only, rate_only=rate_only)
        st.plotly_chart(fig, width="stretch")

    if subject is not None:
        show_figure([subject], f"{subject}得分率趋势")
    else:
        show_figure(trend["subjects"], "各科得分率趋势")
        show_figure(["total"], "总分平均分趋势", total_chart=True)
    st.caption("各次考试满分可能不同；单科按当次考试满分换算，总分保持原始分。")


def _student_trend_panel(class_filter, subject=None, exam_ids=None, limit=None):
    """学生个人趋势；单科默认得分率、可切回原始分，总分恒为原始分。

    以 exam_id 对齐；头部只放考试/日期，各科满分和原始分放每条线。
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
        history = es.student_scores_over_time(session, sid, exam_ids=exam_ids)
    if limit:
        history = _apply_limit(history, limit)
    if not history:
        st.caption("该生在所选范围内没有成绩。")
        return

    subjects = [k for k in history[0].keys()
                if k not in ("exam_id", "exam_name", "exam_date", "total",
                             "full_scores")]

    cc1, cc2 = st.columns(2)
    trend_marker = "student_trend_subject_prev"
    if st.session_state.get(trend_marker) != subject:
        st.session_state.pop("student_trend_subjects", None)
        st.session_state[trend_marker] = subject
    default_shown = [subject] if subject and subject in subjects else subjects
    shown_subjects = cc1.multiselect(
        "显示科目", subjects, default=default_shown,
        key="student_trend_subjects")
    chart_type = cc2.radio(
        "图表类型", ["折线图", "柱状图"], horizontal=True,
        key="student_trend_chart_type")
    score_mode = st.radio(
        "学生趋势显示", ["原始分", "得分率"], horizontal=True, index=1,
        key="trend_student_score_mode")

    # 统一头部类目（不含满分）；编号在显示范围内从 1
    headers = [
        chart_service.trend_header(
            index, h["exam_name"],
            h["exam_date"].isoformat() if hasattr(
                h["exam_date"], "isoformat") else "")
        for index, h in enumerate(history, start=1)
    ]
    id_to_header = {h["exam_id"]: headers[i]
                    for i, h in enumerate(history)}

    is_bar = chart_type == "柱状图"
    use_rate = score_mode == "得分率"

    def point_of(h, item_subject):
        raw_value = h.get(item_subject)
        full_score = h.get("full_scores", {}).get(item_subject)
        rate = _rate_value(raw_value, full_score)
        return raw_value, full_score, rate

    # 单科图
    if is_bar:
        subject_fig = go.Figure()
        for item_subject in shown_subjects:
            xs, ys, hover_lines = [], [], []
            for h in history:
                raw_value, full_score, rate = point_of(h, item_subject)
                if raw_value is None:
                    continue
                header = id_to_header[h["exam_id"]]
                xs.append(header)
                ys.append(rate if use_rate else raw_value)
                rate_text = f"{rate:g}%" if rate is not None else "—"
                hover_lines.append(
                    f"{item_subject}：{raw_value:g}/{full_score:g}"
                    f"（{rate_text}）")
            subject_fig.add_trace(go.Bar(
                x=xs, y=ys, name=item_subject, customdata=hover_lines,
                hovertemplate="%{customdata}<extra></extra>"))
        subject_fig.update_layout(barmode="group")
    else:
        lines = []
        for item_subject in shown_subjects:
            point_map = {}
            for h in history:
                raw_value, full_score, rate = point_of(h, item_subject)
                if raw_value is None:
                    continue
                point_map[id_to_header[h["exam_id"]]] = {
                    "score": raw_value, "full": full_score, "rate": rate}
            lines.append({"name": item_subject, "points": point_map})
        subject_fig = chart_service.build_trend_figure(
            lines, headers,
            title="各科得分率趋势" if use_rate else "各科成绩趋势",
            y_title="得分率(%)" if use_rate else "分数",
            fixed_percent=use_rate, rate_only=use_rate)

    # 总分图：恒为原始分
    if is_bar:
        xs, ys = [], []
        for h in history:
            if h.get("total") is None:
                continue
            xs.append(id_to_header[h["exam_id"]])
            ys.append(h["total"])
        total_fig = go.Figure(go.Bar(
            x=xs, y=ys, name="总分", marker_color="#1F4E79", opacity=0.9))
        total_fig.update_layout(barmode="group")
    else:
        total_line = {"name": "总分", "points": {}}
        for h in history:
            if h.get("total") is None:
                continue
            total_line["points"][id_to_header[h["exam_id"]]] = {
                "score": h["total"], "full": None, "rate": None}
        total_fig = chart_service.build_trend_figure(
            [total_line], headers, title="总分趋势", y_title="分数")

    base_layout = dict(
        height=420, xaxis=dict(showticklabels=False, showgrid=True),
        hovermode="x unified", hoverlabel=dict(align="left", font_size=13),
        margin=dict(l=60, r=30, t=60, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02))
    if is_bar:
        subject_fig.update_layout(
            title="各科得分率趋势" if use_rate else "各科成绩趋势",
            yaxis_title="得分率(%)" if use_rate else "分数", **base_layout)
        if use_rate:
            subject_fig.update_layout(yaxis=dict(range=[0, 100]))
        total_fig.update_layout(
            title="总分趋势", yaxis_title="分数", **base_layout)
    st.plotly_chart(subject_fig, width="stretch")
    st.plotly_chart(total_fig, width="stretch")
    st.caption("单科按当次考试满分换算；总分保留原始分。")



def _parent_report_panel(student_id: int, student) -> None:
    """家校沟通报告：生成、编辑预览和导出 PDF。"""
    key = f"parent_report_{student_id}"
    with st.container(border=True):
        st.markdown("**📨 家校沟通报告**")
        c1, c2 = st.columns(2)
        if c1.button("📨 生成家校报告", key=f"parent_generate_{student_id}"):
            with SessionLocal() as session:
                chat_func = (llm_client.chat_content
                             if llm_client.is_configured() else None)
                st.session_state[key] = parent_report_service.generate_parent_report(
                    session, student_id, chat_func=chat_func)
            st.rerun()
        report = st.session_state.get(key)
        if report is None:
            st.caption("基于真实考试和逐题作答生成；数据不足会明确提示。")
            return
        for field, label in (
                ("overview", "近期表现"),
                ("strengths", "优点与进步"),
                ("improvements", "需改进点"),
                ("family_advice", "家庭配合建议"),
                ("teacher_words", "老师寄语")):
            report[field] = st.text_area(
                label, value=report.get(field, ""), height=90,
                key=f"parent_{field}_{student_id}")
        if report.get("data_notice"):
            st.caption(report["data_notice"])
        try:
            pdf_bytes = parent_report_service.export_parent_report_pdf(report)
            c2.download_button(
                "⬇️ 导出 PDF", pdf_bytes,
                file_name=f"{student.name}_家校沟通报告.pdf",
                mime="application/pdf", key=f"parent_pdf_{student_id}")
        except Exception as exc:
            st.warning(f"PDF 暂不可用：{exc}")


def _tiered_homework_panel(classes: list[str]) -> None:
    """按最近一次考试显示 A/B/C 名单，并一键生成三份分层作业。"""
    if not classes:
        st.caption("先导入学生和考试成绩后才能分层。")
        return
    class_name = st.selectbox(
        "选择班级", classes, key="tiered_homework_class")
    subject = st.selectbox(
        "学科", SUBJECT_NAMES if False else __import__('utils.app_config', fromlist=['SUBJECT_NAMES']).SUBJECT_NAMES,
        index=1, key="tiered_homework_subject")
    per_layer = st.slider(
        "每层题量", min_value=3, max_value=12, value=5,
        key="tiered_homework_count")

    with SessionLocal() as session:
        exams = es.list_exams(session)
        latest = None
        rows = []
        for exam in reversed(exams):
            candidate = agent_advisor._exam_totals(session, exam.id, class_name)
            candidate = [r for r in candidate if r["total"] is not None]
            if candidate:
                latest, rows = exam, candidate
                break
        if latest is None:
            st.caption("该班暂无可用于分层的考试成绩。")
            return
        tiers = agent_advisor._tier_names(rows)
        for tier in ("A", "B", "C"):
            st.caption(
                f"{tier} 层（{len(tiers[tier])}人）："
                + "、".join(x["name"] for x in tiers[tier]))
        if st.button("📚 一键生成分层作业", type="primary",
                     key="generate_tiered_homework"):
            result = agent_advisor.generate_tiered_homework(
                session, class_name, subject,
                questions_per_layer=per_layer)
            st.success("已生成三份分层作业。")
            for tier, homework_id in result["homework_ids"].items():
                st.caption(f"{tier} 层作业 ID：{homework_id}")


# ---------------------------------------------------------------------------
# 标签页 5：学生画像
# ---------------------------------------------------------------------------

def _exam_profile():
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
    _parent_report_panel(sid, student)

    if not history:
        st.info(f"{student.name} 还没有考试总分数据，但下方可查看逐题知识点追踪。")
    else:
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

    return sid

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
                    st.toast("模板已添加。")
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
        st.toast(f"生成完成：成功 {ok_count} 条，失败 {fail_count} 条。"
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
                    _sync_analysis_context(class_name=student.class_name,
                                           last_action="保存期末评语")
                    st.toast(f"{student.name} 的评语已保存。")
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
        st.toast(f"已保存 {saved_n} 条评语（按“学生+学期”留档，重复保存是更新）。")
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


def _comments_panel():
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

# ---------------------------------------------------------------------------
# 标签页 8：知识点掌握分析（v1.5.2，基于作业逐题批改）
# ---------------------------------------------------------------------------

# 掌握等级对应颜色（优秀/良好=绿，一般=黄，薄弱=红）
_LEVEL_COLOR = {
    "优秀": "background-color:#c6efce;",
    "良好": "background-color:#c6efce;",
    "一般": "background-color:#ffeb9c;",
    "薄弱": "background-color:#ffc7ce;",
}


def _single_homework_legacy_panel():
    """选一份已逐题批改的作业，看全班知识图谱、个人雷达和薄弱点。"""
    st.subheader("🧠 知识图谱")

    with SessionLocal() as session:
        homeworks = hws.list_homeworks(session, templates=False)

    if not homeworks:
        st.info("还没有普通作业；先到「📝 学业测评」新建作业并布置给学生。")
        return

    options = {
        f"[{hw.subject or '未分学科'}] {hw.name}"
        f"（{hw.class_name or '未分班'}）": hw.id for hw in homeworks}
    chosen = st.selectbox("选择作业", list(options.keys()),
                          key="kp_homework")
    hw_id = options[chosen]

    with SessionLocal() as session:
        selected_hw = session.get(Homework, hw_id)
        rows = hscore.knowledge_mastery(session, hw_id)
        student_rows = hscore.score_rows(session, hw_id)

    if not rows:
        st.info("这份作业还没有逐题批改数据；先到「📝 学业测评 → 成绩录入」逐题打分。")
        return

    st.write("**全班知识点统计表**")
    class_df = pd.DataFrame([{
        "知识点": r["knowledge_point"],
        "满分": r["full_score"],
        "实得分": r["earned_score"],
        "得分率": f"{r['rate'] * 100:.1f}%" if r["rate"] is not None else "—",
        "掌握情况": r["level"],
        "参与人数": r["participants"],
    } for r in rows])
    st.dataframe(class_df, hide_index=True, width="stretch")

    with SessionLocal() as session:
        heatmap = khm.build_heatmap(
            session,
            subject=selected_hw.subject or DEFAULT_SUBJECT,
            class_names=[selected_hw.class_name] if selected_hw.class_name else None,
            homework_ids=[selected_hw.id])
    if heatmap["z"]:
        st.write("**知识点掌握热力图**")
        hover_text = []
        for kp_index, kp in enumerate(heatmap["y"]):
            row_text = []
            for class_name in heatmap["x"]:
                items = heatmap["details"].get((class_name, kp), [])
                row_text.append("\n".join(
                    f"{x['student']}：{x['question']}（{x['rate']:.0%}）"
                    for x in items[:5]) or "暂无数据")
            hover_text.append(row_text)
        matrix = pd.DataFrame(heatmap["z"], index=heatmap["y"],
                              columns=heatmap["x"])
        fig = px.imshow(
            matrix, color_continuous_scale="RdYlGn", zmin=0, zmax=1,
            aspect="auto", labels={"color": "正确率"})
        fig.update_traces(
            text=hover_text, hovertemplate="%{text}<extra></extra>")
        st.plotly_chart(fig, use_container_width=True)

    st.write("**知识点掌握度仪表盘**")
    try:
        from utils import chart_service
        gauge_items = [{"knowledge_point": r["knowledge_point"],
                        "rate": (r["rate"] or 0) * 100} for r in rows[:6]]
        if gauge_items:
            gauges = chart_service.knowledge_gauges(gauge_items)
            gauge_cols = st.columns(3)
            for i, gauge_fig in enumerate(gauges):
                with gauge_cols[i % 3]:
                    st.plotly_chart(gauge_fig, use_container_width=True)
        else:
            st.caption("暂无知识点数据。")
    except Exception as gauge_exc:
        st.caption(f"仪表盘加载失败：{gauge_exc}")

    green = [r["knowledge_point"] for r in rows if r["level"] in ("优秀", "良好")]
    yellow = [r["knowledge_point"] for r in rows if r["level"] == "一般"]
    red = [r["knowledge_point"] for r in rows if r["level"] == "薄弱"]
    st.caption("🟢 掌握较好：" + ("、".join(green) if green else "无"))
    if yellow:
        st.caption("🟡 一般：" + "、".join(yellow))
    if red:
        st.caption("🔴 薄弱：" + "、".join(red))

    st.write("**全班最薄弱知识点**")
    with SessionLocal() as session:
        weak = hscore.weakest_knowledge(session, hw_id, 3)
    if weak:
        weak_df = pd.DataFrame([{
            "知识点": r["knowledge_point"],
            "得分率": f"{r['rate'] * 100:.1f}%" if r["rate"] is not None else "—",
            "建议": r["suggestion"],
        } for r in weak])
        st.dataframe(weak_df, hide_index=True, width="stretch")

    st.write("**学生知识点掌握**")
    present = [r for r in student_rows if r["score"] is not None]
    if not present:
        st.caption("还没有学生成绩。")
        return
    student_options = {f"{r['name']}（{r['class_name'] or '未分班'}）": r["student_id"]
                       for r in present}
    chosen_student = st.selectbox("选择学生", list(student_options.keys()),
                                  key="kp_student")
    sid = student_options[chosen_student]
    with SessionLocal() as session:
        srows = hscore.student_knowledge_mastery(session, hw_id, sid)

    sdf = pd.DataFrame([{
        "知识点": r["knowledge_point"],
        "满分": r["full_score"],
        "实得分": r["earned_score"],
        "得分率": f"{r['rate'] * 100:.1f}%" if r["rate"] is not None else "—",
        "掌握情况": r["level"],
    } for r in srows])

    def _paint(data):
        return [_LEVEL_COLOR[level] for level in data["掌握情况"]]

    st.dataframe(sdf.style.apply(_paint, axis=None, subset=["掌握情况"]),
                 width="stretch")


# ---------------------------------------------------------------------------
def _single_homework_knowledge():
    """单作业知识图谱；内部无数据返回时，不影响下方跨作业追踪。"""
    _single_homework_legacy_panel()


# ---------------------------------------------------------------------------
# v1.9.2：知识点掌握追踪 UI
# ---------------------------------------------------------------------------

def _trend_figure(events: list[dict], series: dict[str, list],
                  class_series: dict[str, list] | None = None) -> go.Figure:
    """生成知识点掌握率折线图（v1.9.9 统一样式）。

    x 用按作业编号的隐藏头部类目，多线对齐；线宽 3、点 10，点上显示数值；
    class_series 用灰色虚线表示班级平均。
    """
    # 统一头部类目：编号在当前范围内从 1（知识点图无满分口径）
    headers = [
        chart_service.trend_header(
            index, event["homework_name"], event.get("date"))
        for index, event in enumerate(events, start=1)
    ]

    fig = go.Figure()
    colors = ["#2563eb", "#dc2626", "#16a34a", "#9333ea", "#ea580c"]

    def add_lines(data_series, *, is_class):
        for index, (kp, values) in enumerate(data_series.items()):
            xs, ys, labels, hover_lines = [], [], [], []
            for header, value in zip(headers, values):
                if value is None:
                    continue  # 缺数据断开，不补造
                xs.append(header)
                ys.append(value)
                labels.append(f"{value:g}")
                tag = "班级平均" if is_class else kp
                hover_lines.append(f"{tag}：{value:g}%")
            if is_class:
                trace = go.Scatter(
                    x=xs, y=ys, mode="lines", name="班级平均",
                    line=dict(color="#6b7280", dash="dash", width=3),
                    showlegend=(index == 0), connectgaps=False,
                    customdata=hover_lines,
                    hovertemplate="%{customdata}<extra></extra>",
                    hoverlabel=dict(namelength=-1))
            else:
                trace = go.Scatter(
                    x=xs, y=ys, mode="lines+markers+text",
                    text=labels, textposition="top center", name=kp,
                    line=dict(color=colors[index % len(colors)], width=3),
                    marker=dict(size=10), connectgaps=False,
                    customdata=hover_lines,
                    hovertemplate="%{customdata}<extra></extra>",
                    hoverlabel=dict(namelength=-1))
            fig.add_trace(trace)

    add_lines(series, is_class=False)
    if class_series:
        add_lines(class_series, is_class=True)

    fig.update_layout(
        height=420, yaxis=dict(range=[0, 100], title="掌握率"),
        xaxis=dict(showticklabels=False, showgrid=True),
        hovermode="x unified",
        hoverlabel=dict(align="left", font_size=13),
        margin=dict(l=60, r=30, t=60, b=40))
    return fig


def _render_class_knowledge_tracking() -> None:
    """班级维度的知识点掌握追踪。"""
    st.divider()
    st.markdown("### 📈 知识点掌握追踪")

    with SessionLocal() as session:
        subjects = kgs.list_trend_subjects(session)
        classes = ss.list_classes(session)

    if not subjects:
        st.info("还没有逐题批改数据；先在成绩录入中完成逐题打分。")
        return

    filter_cols = st.columns([1, 1, 2])
    default_subject = "数学" if "数学" in subjects else subjects[0]
    subject_index = subjects.index(default_subject)
    subject = filter_cols[0].selectbox(
        "学科", subjects, index=subject_index, key="knowledge_trend_subject")
    class_choice = filter_cols[1].selectbox(
        "班级", ["全部班级"] + classes, key="knowledge_trend_class")

    with SessionLocal() as session:
        all_kps = kgs.list_trend_knowledge_points(session, subject)

    selected_kps = filter_cols[2].multiselect(
        "选择知识点（最多3个）", all_kps,
        default=all_kps[:1], key="knowledge_trend_picks", max_selections=3)

    if not selected_kps:
        st.caption("请选择至少一个知识点。")
        return

    class_names = None if class_choice == "全部班级" else [class_choice]
    with SessionLocal() as session:
        result = kgs.get_knowledge_trend(
            session, subject, selected_kps, class_names)

    if not result["events"]:
        st.info("所选范围暂时没有趋势数据。")
        return

    st.plotly_chart(
        _trend_figure(result["events"], result["series"]), width="stretch")

    icon_map = {"上升": "🟢 上升", "下降": "🔴 下降",
                "稳定": "🟡 稳定", "数据不足": "数据不足"}
    for kp, (label, slope) in result["trends"].items():
        st.caption(f"{kp}：{icon_map.get(label, label)}（斜率 {slope:.3f}）")

    descending = [kp for kp, (label, _slope) in result["trends"].items()
                  if label == "下降"]
    if descending:
        st.info("教学建议：对 " + "、".join(descending)
                + " 安排回看例题、专项练习和下次作业复测。")

    with st.expander("AI 分析原因与建议", expanded=False):
        if st.button("生成 AI 分析", key="knowledge_trend_ai"):
            try:
                st.session_state["knowledge_trend_ai_result"] = (
                    kgs.analyze_knowledge_trend(
                        subject, selected_kps, result["events"]))
            except Exception as exc:
                st.warning(f"AI 暂时不可用：{exc}")
        ai_result = st.session_state.get("knowledge_trend_ai_result")
        if ai_result:
            st.markdown(ai_result)


def _render_personal_knowledge_tracking(sid: int | None = None) -> None:
    """个人维度知识点追踪，并与班级平均比较。"""
    st.divider()
    st.markdown("### 📈 个人知识点追踪")

    with SessionLocal() as session:
        students = ss.list_students(session)
        subjects = kgs.list_trend_subjects(session)

    if not students:
        st.info("还没有学生，先到学生管理导入名单。")
        return
    if not subjects:
        st.info("还没有逐题批改数据。")
        return

    options = {f"{student.name}｜{student.class_name or '未分班'}": student.id
               for student in students}
    default_label = next(
        (label for label, student_id in options.items() if student_id == sid),
        list(options.keys())[0])
    chosen_label = st.selectbox(
        "选择学生", list(options.keys()),
        index=list(options.keys()).index(default_label),
        key="profile_trend_student")
    chosen_sid = options[chosen_label]

    default_subject = "数学" if "数学" in subjects else subjects[0]
    subject = st.selectbox(
        "学科", subjects, index=subjects.index(default_subject),
        key="profile_trend_subject")

    with SessionLocal() as session:
        result = kgs.get_student_knowledge_trend(session, chosen_sid, subject)

    if not result["events"]:
        st.info("这名学生暂时没有逐题作答数据。")
        return

    st.plotly_chart(_trend_figure(
        result["events"], result["student_series"], result["class_series"]),
        width="stretch")
    st.caption("优势知识点：" + ("、".join(result["strengths"]) or "暂无"))
    st.caption("薄弱知识点：" + ("、".join(result["weak_points"]) or "暂无"))


def tab_profile():
    """学生画像：画像 / 学生评语（v2.4.0 评语并入；v2.6.0 加预警名单）。"""
    tabs = st.tabs(["👤 学生画像", "💬 学生评语"])
    with tabs[0]:
        _profile_panel()
    with tabs[1]:
        _comments_panel()


def _profile_panel():
    """学生画像：考试画像 + 个人知识点追踪（v2.6.0 加预警；v2.7.0 加学情报告）。"""
    selected_id = _exam_profile()
    _render_personal_knowledge_tracking(selected_id)
    _student_report_panel(selected_id)
    _student_watchlist_panel()


def _student_report_panel(selected_id):
    """学生个人学情报告（v2.7.0）：生成、预览、导出 PDF、批量 ZIP。"""
    from utils import student_report_service as srs
    with st.expander("📄 学生个人学情报告", expanded=False):
        if not selected_id:
            st.caption("请先在上方选择一名学生。")
            return
        if st.button("📄 生成学情报告", key="stu_report_gen"):
            with SessionLocal() as session:
                try:
                    report = srs.generate_student_report(session, int(selected_id))
                except ValueError as exc:
                    st.warning(str(exc))
                    return
            st.session_state["stu_report_data"] = report
        report = st.session_state.get("stu_report_data")
        if report and report.get("student_id") == int(selected_id):
            st.markdown(srs.render_student_report_html(report),
                        unsafe_allow_html=True)
            pdf = srs.export_student_report_pdf(report)
            st.download_button(
                "⬇️ 下载学情报告 PDF", pdf,
                file_name=f"{report.get('name')}_学情报告.pdf",
                mime="application/pdf", key="stu_report_pdf")
        # v2.8.0：批量导出走后台任务，不阻塞界面
        if st.button("📦 后台生成全班报告 ZIP", key="stu_report_zip"):
            from utils import task_service
            with SessionLocal() as session:
                ids = [x.id for x in ss.list_students(session)]

            def _runner(params, progress, cancel_check):
                from utils.db import SessionLocal as _SL
                out = []
                total = max(len(params.get("ids") or []), 1)
                with _SL() as sess:
                    for i, sid in enumerate(params.get("ids") or [], start=1):
                        if cancel_check():
                            break
                        progress(int(i / total * 90))
                        try:
                            rep = srs.generate_student_report(sess, sid)
                            out.append(rep["name"])
                        except Exception:  # noqa: BLE001
                            continue
                    data = srs.export_reports_zip(sess, params.get("ids") or [])
                progress(100)
                return {"count": len(out), "size": len(data),
                        "zip_b64": __import__("base64").b64encode(data).decode()}

            tid = task_service.submit_task("批量导出学情报告",
                                           {"ids": ids}, _runner)
            st.session_state["stu_report_zip_task"] = tid
            st.toast(f"已提交后台任务 #{tid}，可在「⚙️ 设置 → 📋 任务管理」查看。")
        _tid = st.session_state.get("stu_report_zip_task")
        if _tid:
            from utils import task_service
            _t = task_service.get_task(_tid)
            if _t:
                st.caption(f"报告打包任务 #{_tid}：{_t['status']}（{_t['progress']}%）")
                if _t["status"] == "completed" and _t.get("result", {}).get("zip_b64"):
                    import base64 as _b64
                    data = _b64.b64decode(_t["result"]["zip_b64"])
                    st.download_button(
                        "⬇️ 下载全班报告 ZIP", data,
                        file_name="全班学情报告.zip", mime="application/zip",
                        key="stu_report_zip_dl")


def _knowledge_tab():
    """知识图谱：单作业掌握分析 + 跨作业追踪。"""
    _single_homework_knowledge()
    _render_class_knowledge_tracking()




def tab_diagnosis():
    """AI 教学诊断：范围选择、结构化报告、历史对比与建议跳转。"""
    st.subheader("🔍 AI教学诊断")
    with SessionLocal() as session:
        classes = ss.list_classes(session)
    if not classes:
        st.info("还没有班级和学生数据，先到「学生管理」导入名单。")
        return
    c1, c2, c3, c4, c5 = st.columns(5)
    class_name = c1.selectbox("班级", classes, key="diagnosis_class")
    subject = c2.selectbox("学科", SUBJECT_NAMES, key="diagnosis_subject")
    grade = c3.text_input("年级（可空）", key="diagnosis_grade")
    mode = c4.selectbox("诊断范围", ["近一个月", "近一学期", "自定义"], key="diagnosis_mode")
    start_date = end_date = None
    if mode == "自定义":
        start_date = c5.date_input("开始日期", key="diagnosis_start")
        end_date = c5.date_input("结束日期", key="diagnosis_end")
    elif mode == "近一学期":
        period_type = "semester"
    else:
        period_type = "month"
    period = {"type": period_type}
    if mode == "自定义":
        period.update({"type": "custom", "start_date": str(start_date),
                       "end_date": str(end_date)})
    if st.button("🤖 生成诊断", type="primary", key="diagnosis_generate"):
        try:
            with SessionLocal() as session:
                row = diagnosis_service.generate_diagnosis(
                    session, class_name, subject, grade or None, period)
                session.commit()
                st.session_state["diagnosis_last_id"] = row.id
                st.toast("诊断报告已生成。")
        except Exception as exc:  # noqa: BLE001
            st.error(f"生成诊断失败：{exc}")
    row = None
    last_id = st.session_state.get("diagnosis_last_id")
    if last_id:
        with SessionLocal() as session:
            row = session.get(diagnosis_service.TeachingDiagnosis, int(last_id))
    if row is not None:
        parsed = json.loads(row.report_content or "{}")
        report = parsed.get("report") or {}
        data = parsed.get("data") or {}
        st.metric("诊断评分", row.score or "—")
        st.caption(f"整体评价：{report.get('overall_rating', '—')}｜节奏：{report.get('pace', '—')}")
        kp = data.get("knowledge") or []
        if kp:
            fig = go.Figure(go.Scatterpolar(
                r=[x["mastery"] * 100 for x in kp],
                theta=[x["knowledge_point"] for x in kp], fill="toself"))
            st.plotly_chart(fig, use_container_width=True)
        tiers = data.get("tiers") or {}
        if tiers:
            fig = go.Figure(go.Pie(labels=list(tiers), values=list(tiers.values())))
            st.plotly_chart(fig, use_container_width=True)
        for item in report.get("problems", []):
            with st.expander(item.get("problem", "问题"), expanded=True):
                st.write(item.get("suggestion", ""))
                b1, b2, b3 = st.columns(3)
                if b1.button("生成对应教案", key=f"diag_lesson_{row.id}_{item.get('id')}"):
                    st.session_state["pending_lesson_topic"] = item.get("problem", "")
                    st.session_state["lesson_plan_tab"] = "AI 备课"
                    st.session_state["app_top_page"] = "📚 备课"
                    st.rerun()
                if b2.button("生成专项练习", key=f"diag_questions_{row.id}_{item.get('id')}"):
                    st.session_state["pending_question_knowledge"] = item.get("problem", "")
                    st.session_state["lesson_plan_tab"] = "AI 出题"
                    st.session_state["app_top_page"] = "📚 备课"
                    st.rerun()
                if b3.button("加入教学计划", key=f"diag_plan_{row.id}_{item.get('id')}"):
                    st.session_state["teaching_plan_note"] = item.get("problem", "")
                    st.session_state["app_top_page"] = "📅 教学日历"
                    st.rerun()
        if st.button("导出诊断 Word", key=f"diagnosis_word_{row.id}"):
            st.download_button("下载 Word", diagnosis_service.export_diagnosis_word(row),
                               file_name=f"教学诊断_{row.id}.docx",
                               mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                               key=f"diagnosis_word_download_{row.id}")
    with st.expander("📜 历史诊断与对比", expanded=False):
        with SessionLocal() as session:
            rows = diagnosis_service.list_diagnoses(session, class_name, subject)
        if not rows:
            st.caption("暂无诊断历史。")
        else:
            st.dataframe(pd.DataFrame([{"ID": r.id, "时间": str(r.created_at),
                                         "评分": r.score} for r in rows]),
                         hide_index=True, width="stretch")
            if len(rows) >= 2:
                opts = [r.id for r in rows]
                a = st.selectbox("旧诊断", opts, key="diag_cmp_a")
                b = st.selectbox("新诊断", opts, key="diag_cmp_b")
                if st.button("开始对比", key="diag_compare"):
                    with SessionLocal() as session:
                        result = diagnosis_service.compare_diagnoses(session, a, b)
                    st.write(result)
