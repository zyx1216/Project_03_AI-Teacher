# -*- coding: utf-8 -*-
"""v3.4.1 侧边栏布局 / AI助手上下文 / 模型设置 测试。"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from streamlit.testing.v1 import AppTest

from models.models import Base, Textbook
from tests.test_app_smoke import _isolated_app_code, goto_assistant


def _app(tmp_path, name="v341"):
    db_file = tmp_path / f"{name}.db"
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / f"{name}_feature.json"),
        default_timeout=30)
    at.run()
    return at, db_file


OLD_NAV = ("nav_calendar", "nav_class_interaction", "nav_template_library",
           "nav_reflection")


def test_sidebar_layout_rebuilt(tmp_path):
    """3 个独立按钮 + 5 个折叠组；旧独立按钮不再存在。"""
    at, _ = _app(tmp_path, "layout")
    assert not at.exception, [str(e) for e in at.exception]
    keys = {b.key for b in at.sidebar.button}
    assert {"nav_home", "nav_ai_assistant", "nav_databoard",
            "nav_settings"} <= keys
    assert not set(OLD_NAV) & keys
    # 5 个折叠组的子按钮都在（能渲染出子按钮即说明组存在）。
    assert {"resource_sub_📚 资料管理", "resource_sub_📁 我的模板",
            "teaching_sub_📅 教学日历", "teaching_sub_🎯 课堂互动",
            "teaching_sub_💭 教学反思", "lesson_sub_AI 备课",
            "hw_sub_作业管理", "analysis_sub_学生管理"} <= keys


def test_resource_and_teaching_groups_switch(tmp_path):
    """资源中心 / 教学工具的子按钮能切换，含点已选中项。"""
    at, _ = _app(tmp_path, "groups")
    next(b for b in at.sidebar.button
         if b.key == "resource_sub_📁 我的模板").click().run()
    assert at.session_state["app_top_page"] == "📂 资源中心"
    assert at.session_state["resource_tab"] == "📁 我的模板"
    assert not at.exception, [str(e) for e in at.exception]

    # 再点已在同一组里的项（切换回来）
    next(b for b in at.sidebar.button
         if b.key == "resource_sub_📚 资料管理").click().run()
    assert at.session_state["resource_tab"] == "📚 资料管理"
    assert any(x.key == "materials_subject" for x in at.selectbox)

    next(b for b in at.sidebar.button
         if b.key == "teaching_sub_💭 教学反思").click().run()
    assert at.session_state["app_top_page"] == "🎓 教学工具"
    assert at.session_state["teaching_tab"] == "💭 教学反思"
    assert not at.exception, [str(e) for e in at.exception]


def test_legacy_resource_state_migrates(tmp_path):
    """旧状态 lesson_plan_tab='资料管理' 自动迁到资源中心。"""
    at, _ = _app(tmp_path, "legacy")
    at.session_state["lesson_plan_tab"] = "资料管理"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    assert at.session_state["app_top_page"] == "📂 资源中心"
    assert at.session_state["resource_tab"] == "📚 资料管理"
    # 备课组里的旧值被归位
    assert at.session_state["lesson_plan_tab"] == "AI 备课"
    assert any(x.key == "materials_subject" for x in at.selectbox)


def test_legacy_top_page_migrates_to_group(tmp_path):
    """旧顶级页（教学日历）自动迁到教学工具组。"""
    at, _ = _app(tmp_path, "legacy_top")
    at.session_state["app_top_page"] = "📅 教学日历"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    assert at.session_state["app_top_page"] == "🎓 教学工具"
    assert at.session_state["teaching_tab"] == "📅 教学日历"


def test_context_dialog_chapter_link_and_no_autopopup(tmp_path):
    """上下文弹窗：点修改才弹、章节走资料联动、无班级字段、切页不残留。"""
    at, db_file = _app(tmp_path, "ctx")
    # 插一份本学科资料，供章节联动
    engine = create_engine(f"sqlite:///{db_file.as_posix()}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(Textbook(name="高一数学必修一", file_type="pdf",
                         subject="数学", grade=None))
    session.commit()
    session.close()
    engine.dispose()

    goto_assistant(at)
    next(b for b in at.button
         if b.key == "ai_assistant_ctx_edit").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    assert any(b.key == "ai_ctx_save" for b in at.button)
    assert not any(x.key == "ai_ctx_class_name" for x in at.text_input)
    assert any(x.key == "ai_ctx_book" for x in at.selectbox)

    # 切到别的页面后不再自动弹出
    at.session_state["app_top_page"] = "🏠 首页"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    assert not any(b.key == "ai_ctx_save" for b in at.button)


def test_model_labels_have_no_status_words():
    """模型下拉标签只保留纯模型名，不带稳定/下线等状态词。"""
    from modules import settings
    models = [
        {"id": "deepseek-chat", "name": "DeepSeek Chat",
         "status_label": "✅稳定"},
        {"id": "old-model", "name": "Old Model",
         "status_label": "⚠️即将下线（10月9日）"},
    ]
    labels = settings._model_option_labels(models)
    assert labels["deepseek-chat"] == "DeepSeek Chat"
    assert labels["old-model"] == "Old Model"
    for text in labels.values():
        assert "稳定" not in text and "下线" not in text
