# -*- coding: utf-8 -*-
"""
页面冒烟测试：用 Streamlit 官方 AppTest 无头运行 app.py。

验证：
- 应用能启动、侧边栏 4 个主页面可切换且无异常；
- 学情工作台 5 个标签页都被渲染（st.tabs 内的代码会全部执行），空数据走提示分支不报错。

注意：此测试连真实的 data/database.db（init_db 幂等，只补列、不删数据），
但当前库里没有业务数据，各页走"暂无数据"分支。
"""

from pathlib import Path

from streamlit.testing.v1 import AppTest

APP_FILE = Path(__file__).resolve().parent.parent / "app.py"


def test_app_starts_and_renders_default_page():
    at = AppTest.from_file(str(APP_FILE), default_timeout=30)
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    # 侧边栏导航 4 项
    options = at.sidebar.radio[0].options
    assert options == ["📚 备课工作台", "📝 作业工作台", "📊 学情工作台", "⚙️ 设置"]


def test_switch_all_main_pages():
    at = AppTest.from_file(str(APP_FILE), default_timeout=30)
    at.run()
    for page in ["📚 备课工作台", "📝 作业工作台", "📊 学情工作台", "⚙️ 设置"]:
        at.sidebar.radio[0].set_value(page).run()
        assert not at.exception, (page, [str(e) for e in at.exception])
        assert at.title  # 每页至少有一个标题


def test_analysis_page_has_five_tabs_empty_state():
    at = AppTest.from_file(str(APP_FILE), default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📊 学情工作台").run()
    assert not at.exception, [str(e) for e in at.exception]
    # 学情页 5 个标签页
    assert len(at.tabs) == 5
    expected = ["学生管理", "成绩管理", "考试分析", "趋势分析", "学生画像"]
    assert at.tabs[0].label == expected[0]
    # 空库时页面应给出引导提示，而不是抛异常
    assert at.subheader


def test_settings_page_renders_llm_panel():
    at = AppTest.from_file(str(APP_FILE), default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("⚙️ 设置").run()
    assert not at.exception, [str(e) for e in at.exception]
    all_text = " ".join(str(m.value) for m in at.markdown) + " " + \
               " ".join(str(s.value) for s in at.subheader)
    assert "LLM" in all_text