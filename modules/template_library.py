# -*- coding: utf-8 -*-
"""收藏与模板库页面。"""
from __future__ import annotations
import json
import streamlit as st
from utils.db import SessionLocal
from utils import library_service


def show():
    st.subheader("📁 我的模板")
    tabs = st.tabs(["⭐ 收藏", "📚 模板库"])
    with tabs[0]:
        with SessionLocal() as session:
            rows = library_service.list_favorites(session)
        if not rows:
            st.info("暂无收藏。可在教案、试卷或题目详情中点击收藏。")
        for row in rows:
            c1, c2 = st.columns([5, 1])
            c1.write(f"**{row.title or row.item_type}**｜{row.remark or ''}")
            if c2.button("取消收藏", key=f"favorite_remove_{row.id}"):
                with SessionLocal() as session:
                    library_service.remove_favorite(session, row.item_type, row.item_id)
                    session.commit()
                st.rerun()
    with tabs[1]:
        with SessionLocal() as session:
            rows = library_service.list_templates(session)
        c1, c2, c3 = st.columns(3)
        kind = c1.selectbox("类型", ["全部", "lesson_plan", "exam", "question"], key="template_kind")
        subject = c2.text_input("学科（可空）", key="template_subject")
        keyword = c3.text_input("搜索名称或标签", key="template_keyword")
        rows = library_service.list_templates(
            session, None if kind == "全部" else kind,
            subject=subject.strip() or None, keyword=keyword.strip() or None)
        if not rows:
            st.caption("暂无模板。")
        for row in rows:
            with st.expander(f"{row.name}｜{row.template_type}"):
                st.json(json.loads(row.content_json or "{}"))
                if st.button("删除模板", key=f"template_delete_{row.id}"):
                    library_service.delete_template(session, row.id)
                    session.commit()
                    st.rerun()
        with st.expander("➕ 新建简单模板", expanded=False):
            name = st.text_input("模板名称", key="template_new_name")
            kind_new = st.selectbox("模板类型", ["lesson_plan", "exam", "question"], key="template_new_type")
            content = st.text_area("内容 JSON", value="{}", key="template_new_content")
            if st.button("保存模板", key="template_new_save"):
                try:
                    library_service.create_template(
                        session, kind_new, name, json.loads(content),
                        subject=subject.strip() or None)
                    session.commit()
                    st.toast("模板已保存。")
                    st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(f"模板保存失败：{exc}")
        if rows:
            st.download_button("导出模板 JSON", library_service.export_template_json(
                session, [r.id for r in rows]), file_name="templates.zip",
                mime="application/zip", key="template_export_zip")
