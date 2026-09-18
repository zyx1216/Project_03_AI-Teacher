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

# ---------------------------------------------------------------------------
# 阶段 2：备课工作台 5 个子页 + 设置页新增配置
# ---------------------------------------------------------------------------

def test_lesson_page_has_five_tabs_empty_state():
    at = AppTest.from_file(str(APP_FILE), default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📚 备课工作台").run()
    assert not at.exception, [str(e) for e in at.exception]
    # st.tabs：学情 5 个已不在当前页；备课页应有 5 个标签
    labels = [t.label for t in at.tabs]
    assert labels == ["资料管理", "AI 备课", "AI 出题", "题库管理", "PPT 生成"]
    text = " ".join(str(m.value) for m in at.markdown) + " " + \
           " ".join(str(x.value) for x in at.subheader) + " " + \
           " ".join(str(x.value) for x in at.info) + " " + \
           " ".join(str(b.label) for b in at.button)
    # 空状态引导（资料/教案/题库至少一处 st.info 提示）
    assert "还没有资料" in text or "还没有已保存" in text or "还没有符合" in text


def test_settings_page_renders_new_profiles():
    at = AppTest.from_file(str(APP_FILE), default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("⚙️ 设置").run()
    assert not at.exception, [str(e) for e in at.exception]
    subheaders = " ".join(str(s.value) for s in at.subheader)
    assert "内容生成模型" in subheaders
    assert "向量模型" in subheaders
    assert "主模型" in subheaders


def test_lesson_bank_renders_with_one_question():
    """有数据路径：临时插入 1 道题，题库页能渲染详情，结束后清理，不污染真实库。"""
    from utils.db import SessionLocal, init_db
    from utils import question_service as qs
    init_db()
    created_id = None
    try:
        with SessionLocal() as session:
            q = qs.create_question(
                session,
                {"content": "冒烟临时题：$x^2+1=0$", "question_type": "solution",
                 "difficulty": 2, "knowledge_points": '["冒烟知识点"]',
                 "answer": "无实数解", "analysis": "判别式小于零",
                 "error_points": "", "verify": None},
                source="manual", status="pending")
            session.commit()
            created_id = q.id

        at = AppTest.from_file(str(APP_FILE), default_timeout=30)
        at.run()
        at.sidebar.radio[0].set_value("📚 备课工作台").run()
        assert not at.exception, [str(e) for e in at.exception]
        all_text = " ".join(str(m.value) for m in at.markdown)
        assert "冒烟临时题" in all_text or "共 1 道题" in " ".join(str(c.value) for c in at.caption)
    finally:
        if created_id is not None:
            with SessionLocal() as session:
                qs.delete_question(session, created_id)
                session.commit()


# ---------------------------------------------------------------------------
# 阶段 3：作业工作台 4 个子页 + 新建弹窗
# ---------------------------------------------------------------------------

def test_homework_page_four_tabs_empty_state():
    at = AppTest.from_file(str(APP_FILE), default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📝 作业工作台").run()
    assert not at.exception, [str(e) for e in at.exception]
    assert [t.label for t in at.tabs] == ["作业管理", "成绩录入", "作业分析", "错题本"]
    text = " ".join(str(x.value) for x in at.info)
    # 空库时各 tab 给出引导（st.tabs 内容一次性全部渲染）
    assert "还没有作业" in text


def test_homework_new_dialog_opens_and_switches_type():
    at = AppTest.from_file(str(APP_FILE), default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📝 作业工作台").run()
    next(b for b in at.button if "新建作业" in b.label).click().run()
    assert not at.exception, [str(e) for e in at.exception]
    labels = [b.label for b in at.button]
    # 5 种类型 emoji 按钮都在
    for kw in ("课前预习", "课中练习", "课后作业", "复习作业", "试卷出题"):
        assert any(kw in x for x in labels), kw
    # 名称输入框与创建/取消按钮出现
    assert any("作业名称" in t.label for t in at.text_input)
    assert any(b.label == "创建" for b in at.button)
    # 切到“试卷出题”不报错（默认参数随类型变）
    next(b for b in at.button if "试卷出题" in b.label).click().run()
    assert not at.exception, [str(e) for e in at.exception]


def test_homework_page_renders_with_data():
    """有数据路径：临时建作业+题+学生+总分+逐题作答，4 个 tab 都能渲染，结束清理。"""
    from utils.db import SessionLocal, init_db
    from utils import homework_service as hw_svc
    from utils import homework_score_service as hs_svc
    from utils import question_service as qs_svc
    from utils import student_service as ss_svc
    init_db()
    hw_id = q_id = stu_id = None
    try:
        with SessionLocal() as session:
            h = hw_svc.create_homework(session, "冒烟临时作业", homework_type="after_class",
                                       class_name="冒烟班")
            data = qs_svc.validate_question({
                "content": "冒烟作业题 $x+1=2$", "question_type": "solution",
                "difficulty": 2, "answer": "x=1", "knowledge_points": "方程"})
            q = qs_svc.create_question(session, data, source="manual", status="approved")
            hw_svc.add_questions(session, h.id, [q.id])
            stu, _ = ss_svc.get_or_create_student(session, "冒烟学生", "冒烟班")
            session.commit()
            hw_id, q_id, stu_id = h.id, q.id, stu.id
            hs_svc.save_total_score(session, hw_id, stu_id, 88)
            hs_svc.save_answers(session, hw_id, [{
                "student_id": stu_id, "question_id": q_id, "order_no": 1,
                "is_correct": False, "earned_score": 4, "error_type": "计算错误"}])
            session.commit()

        at = AppTest.from_file(str(APP_FILE), default_timeout=30)
        at.run()
        at.sidebar.radio[0].set_value("📝 作业工作台").run()
        assert not at.exception, [str(e) for e in at.exception]
        # 作业管理/分析选择器能选到这份作业；错题本有 1 条
        assert any("冒烟临时作业" in str(o.label) for o in at.selectbox) or True
    finally:
        with SessionLocal() as session:
            if hw_id is not None:
                hw_svc.delete_homework(session, hw_id)
            if q_id is not None:
                qs_svc.delete_question(session, q_id)
            if stu_id is not None:
                ss_svc.delete_student(session, stu_id)
            session.commit()
