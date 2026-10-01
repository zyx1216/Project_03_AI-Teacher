# -*- coding: utf-8 -*-
"""课堂互动轻工具：随机点名、课堂计时、分组竞赛。"""
from __future__ import annotations
import time
import streamlit as st
from utils.db import SessionLocal
from utils import student_service
from utils import class_interaction_service as svc


def _class_picker(key):
    with SessionLocal() as session:
        classes = student_service.list_classes(session)
    if not classes:
        st.info("还没有班级和学生数据。")
        return None
    return st.selectbox("班级", classes, key=key)


def _random_tab():
    class_name = _class_picker("interaction_random_class")
    if not class_name:
        return
    mode = st.radio("点名权重", ["均匀随机", "薄弱学生优先", "自定义权重"],
                    horizontal=True, key="interaction_random_mode")
    exclude = st.checkbox("排除已点名学生", key="interaction_exclude")
    picked_key = f"interaction_picked_{class_name}"
    picked = st.session_state.setdefault(picked_key, [])
    if st.button("🎲 随机点名", type="primary", key="interaction_pick"):
        try:
            with SessionLocal() as session:
                result = svc.pick_student(session, class_name, mode,
                                          exclude_ids=picked if exclude else [])
                svc.log_interaction(session, class_name, "random_pick", result)
                session.commit()
            picked.append(result["student_id"])
            st.success(f"点到：{result['name']}")
        except Exception as exc:  # noqa: BLE001
            st.warning(f"点名失败：{exc}")
    if picked:
        st.caption(f"本轮已点名 {len(picked)} 人。")
        if st.button("重置点名历史", key="interaction_pick_reset"):
            st.session_state[picked_key] = []
            st.rerun()


def _timer_tab():
    st.caption("计时器使用时间戳刷新，可同时创建多个独立计时。")
    timers = st.session_state.setdefault("interaction_timers", {})
    c1, c2, c3 = st.columns(3)
    name = c1.text_input("计时器名称", value=f"计时器{len(timers)+1}", key="timer_name")
    minutes = c2.number_input("分钟", min_value=1, max_value=120, value=5, key="timer_minutes")
    if c3.button("➕ 新建计时", key="timer_add"):
        timers[name] = {"start": time.time(), "seconds": int(minutes) * 60}
        st.rerun()
    for key, item in list(timers.items()):
        elapsed = time.time() - item.get("start", time.time())
        total = max(1, int(item.get("seconds", 1)))
        remaining = max(0, total - elapsed)
        st.progress(min(1.0, elapsed / total))
        st.write(f"**{key}**：剩余 {int(remaining)} 秒" if remaining else f"**{key}**：时间到")
        if st.button("删除", key=f"timer_delete_{key}"):
            timers.pop(key, None)
            st.rerun()


def _groups_tab():
    class_name = _class_picker("interaction_group_class")
    if not class_name:
        return
    count = st.slider("分组数量", 2, 6, 4, key="interaction_group_count")
    if st.button("🎲 自动分组", key="interaction_group_create"):
        with SessionLocal() as session:
            groups = svc.create_groups(session, class_name, count)
            svc.log_interaction(session, class_name, "grouping", {"groups": groups})
            session.commit()
        st.session_state["interaction_groups"] = groups
        st.session_state["interaction_scores"] = [0] * len(groups)
    groups = st.session_state.get("interaction_groups")
    scores = st.session_state.get("interaction_scores")
    if groups and scores is not None:
        for index, members in enumerate(groups):
            c1, c2, c3 = st.columns([4, 1, 1])
            c1.write(f"第 {index+1} 组：" + "、".join(x["name"] for x in members))
            c2.metric("积分", scores[index])
            if c3.button("+1", key=f"group_plus_{index}"):
                scores[index] += 1
                st.rerun()
        if st.button("重置积分", key="group_score_reset"):
            st.session_state["interaction_scores"] = [0] * len(groups)
            st.rerun()


def show():
    st.subheader("🎯 课堂互动")
    tabs = st.tabs(["🎲 随机点名", "⏱️ 课堂计时", "🏆 分组竞赛"])
    with tabs[0]: _random_tab()
    with tabs[1]: _timer_tab()
    with tabs[2]: _groups_tab()
    with st.expander("📜 互动历史", expanded=False):
        with SessionLocal() as session:
            rows = svc.list_interactions(session, limit=30)
        if not rows:
            st.caption("暂无互动记录。")
        for row in rows:
            st.caption(f"{row.created_at:%Y-%m-%d %H:%M}｜{row.class_name or '—'}｜{row.interaction_type}")
