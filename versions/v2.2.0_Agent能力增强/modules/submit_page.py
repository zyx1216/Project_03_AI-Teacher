# -*- coding: utf-8 -*-
"""免登录学生在线提交页。"""
from __future__ import annotations

import streamlit as st

from utils.db import SessionLocal, init_db
from utils import homework_submit_service as submit_svc


def show_submit_page(code: str | None = None) -> None:
    """渲染学生提交页；只根据提交码读取作业，不进入主导航。"""
    st.title("📝 在线提交")
    init_db()

    code = (code or st.text_input("请输入 6 位提交码", value="")).strip()
    if not code:
        st.caption("向老师获取提交码后进入作业。")
        return

    with SessionLocal() as session:
        try:
            hw = submit_svc.get_homework_by_code(session, code)
            questions = submit_svc.ordered_questions(session, hw.id)
        except ValueError as exc:
            st.error(exc)
            return

        st.subheader("在线提交")
        st.caption(f"{hw.name}｜{hw.class_name or '未分班'}")
        answers = {}
        with st.form("student_submit_form"):
            for index, question in questions:
                st.markdown(f"**{index}. {question.content}**")
                if question.question_type == "choice":
                    answers[str(index)] = st.text_input(
                        f"第{index}题答案", key=f"submit_q_{index}")
                elif question.question_type == "judge":
                    answers[str(index)] = st.selectbox(
                        f"第{index}题判断", ["正确", "错误"],
                        key=f"submit_q_{index}")
                else:
                    answers[str(index)] = st.text_area(
                        f"第{index}题作答", key=f"submit_q_{index}")
            student_name = st.text_input("你的姓名", key="submit_student_name")
            submitted = st.form_submit_button("✅ 提交", type="primary")

        if submitted:
            try:
                row = submit_svc.save_submission(
                    session, code, student_name, answers)
                session.commit()
                st.toast(f"{row.student_name}，提交成功。")
            except ValueError as exc:
                st.error(exc)
