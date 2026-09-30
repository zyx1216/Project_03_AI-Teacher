# -*- coding: utf-8 -*-
"""v2.4.0 功能合并与结构优化测试。"""

from __future__ import annotations

import json

import pytest

from tests.test_app_smoke import (
    _isolated_app_code, goto_sub, LEGACY_SUB_ALIASES)


# ---------------------------------------------------------------------------
# 纯映射：子功能名单与旧值别名
# ---------------------------------------------------------------------------

def test_legacy_alias_keys_cover_removed_subs():
    """7 个被删/改名的旧子功能值全部有迁移映射。"""
    removed = {
        "lesson_plan_tab": {"📚 RAG知识库", "PPT 生成", "🎙️ 课堂实录"},
        "homework_tab": {"📜 历史记录", "成绩录入", "作业分析"},
        "analysis_tab": {"教学反思", "期末评语", "🧠 知识图谱"},
    }
    for key, values in removed.items():
        assert values <= set(LEGACY_SUB_ALIASES[key]), key


def test_alias_independent_page_sub_value_none():
    """课堂实录/教学反思迁入独立顶级页，新子功能值为 None。"""
    assert LEGACY_SUB_ALIASES["lesson_plan_tab"]["🎙️ 课堂实录"][1] is None
    assert LEGACY_SUB_ALIASES["analysis_tab"]["教学反思"][1] is None


def test_alias_internal_modes_set():
    """RAG/历史记录的内部模式被正确设置。"""
    _, _, extra = LEGACY_SUB_ALIASES["lesson_plan_tab"]["📚 RAG知识库"]
    assert extra["material_view_mode"] == "AI智能检索"
    _, _, extra = LEGACY_SUB_ALIASES["homework_tab"]["📜 历史记录"]
    assert extra["homework_state_mode"] == "已完成"


# ---------------------------------------------------------------------------
# AppTest 夹具
# ---------------------------------------------------------------------------

def _skip_onboarding(db_file):
    (db_file.parent / "onboarding.json").write_text(json.dumps({
        "completed_steps": [], "skipped": True,
        "snooze_until": "", "updated_at": ""}, ensure_ascii=False),
        encoding="utf-8")


def _feature_file(path):
    path.write_text(json.dumps({
        "materials_subject": "数学", "lesson_plan_subject": "数学",
        "question_gen_subject": "数学", "question_bank_subject": "数学",
        "homework_list_subject": "数学", "homework_analysis_subject": "数学",
        "wrong_book_subject": "数学"}, ensure_ascii=False), encoding="utf-8")


def _make_at(tmp_path, db_name):
    db_file = tmp_path / db_name
    _skip_onboarding(db_file)
    feature = tmp_path / (db_name + "_feature.json")
    _feature_file(feature)
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_string(
        _isolated_app_code(db_file, feature), default_timeout=60)
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    return at


# ---------------------------------------------------------------------------
# 13 个子功能 + 教学反思独立页均可到达（空库）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("top,sub", [
    ("📚 备课", "资料管理"),
    ("📚 备课", "AI 备课"),
    ("📚 备课", "AI 出题"),
    ("📚 备课", "题库管理"),
    ("📝 学业测评", "作业管理"),
    ("📝 学业测评", "🤖 智能组卷"),
    ("📝 学业测评", "✏️ 批改与分析"),
    ("📝 学业测评", "错题本"),
    ("📊 学情", "学生管理"),
    ("📊 学情", "成绩管理"),
    ("📊 学情", "考试分析"),
    ("📊 学情", "趋势分析"),
    ("📊 学情", "学生画像"),
])
def test_all_13_subs_reachable_empty(tmp_path, top, sub):
    at = _make_at(tmp_path, "nav.db")
    goto_sub(at, {"📚 备课": "lesson_plan_tab",
                  "📝 学业测评": "homework_tab",
                  "📊 学情": "analysis_tab"}[top], sub, top)
    assert not at.exception, [str(e) for e in at.exception]


def test_reflection_independent_page_reachable_empty(tmp_path):
    at = _make_at(tmp_path, "ref.db")
    at.session_state["app_top_page"] = "💭 教学反思"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    assert [t.label for t in at.tabs] == [
        "🎙️ 课堂实录", "💭 教学反思", "📚 改进历史"]


# ---------------------------------------------------------------------------
# 合并入口：内部模式/tabs 渲染
# ---------------------------------------------------------------------------

def test_materials_mode_switch_renders_rag(tmp_path):
    at = _make_at(tmp_path, "mat.db")
    goto_sub(at, "lesson_plan_tab", "资料管理", "📚 备课")
    radio = next(x for x in at.radio if x.key == "material_view_mode")
    radio.set_value("AI智能检索").run()
    assert not at.exception, [str(e) for e in at.exception]
    # RAG 模式渲染问答控件。
    assert any(x.key == "rag_question_input" for x in at.text_input)


def test_lesson_ppt_panel_present(tmp_path):
    at = _make_at(tmp_path, "ppt.db")
    goto_sub(at, "lesson_plan_tab", "AI 备课", "📚 备课")
    assert any("生成配套PPT" in e.label for e in at.expander)


def test_homework_state_switch(tmp_path):
    at = _make_at(tmp_path, "hwm.db")
    goto_sub(at, "homework_tab", "作业管理", "📝 学业测评")
    radio = next(x for x in at.radio if x.key == "homework_state_mode")
    radio.set_value("已完成").run()
    assert not at.exception, [str(e) for e in at.exception]


def test_grading_analysis_two_tabs(tmp_path):
    # v2.4.1：页面无数据会提前返回；造一份作业后才渲染两标签。
    db_file = tmp_path / "ga.db"
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from models.models import Base
    from utils import homework_service
    eng = create_engine(f"sqlite:///{db_file.as_posix()}")
    Base.metadata.create_all(eng)
    sess = sessionmaker(bind=eng)()
    homework_service.create_homework(sess, "批改作业", subject="数学")
    sess.commit(); eng.dispose()

    at = _make_at(tmp_path, "ga.db")
    goto_sub(at, "homework_tab", "✏️ 批改与分析", "📝 学业测评")
    assert not at.exception, [str(e) for e in at.exception]
    # 外层两标签（内层批改面板还有自己的 tabs，只断言包含且各一个）
    outer = [t.label for t in at.tabs]
    assert outer.count("✏️ 作业批改") == 1
    assert outer.count("📊 批改分析") == 1


def test_score_management_three_tabs(tmp_path):
    at = _make_at(tmp_path, "scm.db")
    goto_sub(at, "analysis_tab", "成绩管理", "📊 学情")
    assert not at.exception, [str(e) for e in at.exception]
    assert [t.label for t in at.tabs] == [
        "📝 成绩录入", "✏️ 成绩编辑", "📋 考试管理"]


def test_exam_analysis_two_tabs(tmp_path):
    at = _make_at(tmp_path, "exa.db")
    goto_sub(at, "analysis_tab", "考试分析", "📊 学情")
    # v2.5.0 新增「多考试对比」「教学效果评估」两个标签
    assert [t.label for t in at.tabs] == [
        "📊 成绩分析", "🧩 知识点掌握", "📊 多考试对比", "📈 教学效果评估"]


def test_profile_two_tabs(tmp_path):
    at = _make_at(tmp_path, "prof.db")
    goto_sub(at, "analysis_tab", "学生画像", "📊 学情")
    assert [t.label for t in at.tabs] == ["👤 学生画像", "💬 学生评语"]


# ---------------------------------------------------------------------------
# 旧值迁移：通过 goto_sub 别名进入后，页面与正常入口一致
# ---------------------------------------------------------------------------

def test_legacy_rag_alias_lands_in_ai_mode(tmp_path):
    at = _make_at(tmp_path, "lrag.db")
    goto_sub(at, "lesson_plan_tab", "📚 RAG知识库", "📚 备课")
    assert at.session_state["app_top_page"] == "📚 备课"
    assert at.session_state["material_view_mode"] == "AI智能检索"
    assert at.session_state["lesson_plan_tab"] == "资料管理"
    assert not at.exception, [str(e) for e in at.exception]


def test_legacy_history_alias_lands_completed(tmp_path):
    at = _make_at(tmp_path, "lhis.db")
    goto_sub(at, "homework_tab", "📜 历史记录", "📝 学业测评")
    assert at.session_state["homework_tab"] == "作业管理"
    assert at.session_state["homework_state_mode"] == "已完成"
    assert not at.exception, [str(e) for e in at.exception]
