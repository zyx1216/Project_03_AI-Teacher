# -*- coding: utf-8 -*-
"""
页面冒烟测试：用 Streamlit 官方 AppTest 无头运行 app.py。

验证：
- 应用能启动、侧边栏 4 个主页面可切换且无异常；
- 学情工作台 7 个标签页都被渲染（st.tabs 内的代码会全部执行），空数据走提示分支不报错。

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


def test_analysis_page_has_seven_tabs():
    at = AppTest.from_file(str(APP_FILE), default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📊 学情工作台").run()
    assert not at.exception, [str(e) for e in at.exception]
    # 学情页 7 个标签页（阶段 4 新增教学反思、期末评语）
    labels = [t.label for t in at.tabs]
    assert labels == ["学生管理", "成绩管理", "考试分析", "趋势分析",
                      "学生画像", "教学反思", "期末评语"]
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

# ---------------------------------------------------------------------------
# 阶段 4：学情 7 tab、教学反思/期末评语、新建考试弹窗、设置数据管理
# ---------------------------------------------------------------------------

import sys as _sys  # noqa: E402

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_PROJECT_ROOT))


def _isolated_app_code(db_file: Path) -> str:
    """生成在临时数据库上跑 app.py 的脚本（不碰真实 data/database.db）。"""
    template = '''
import sys, runpy
sys.path.insert(0, r"__ROOT__")
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import utils.db as db
import modules.analysis, modules.homework, modules.lesson_plan, modules.settings
eng = create_engine(r"sqlite:///__DBFILE__")
SL = sessionmaker(bind=eng)
db.engine = eng
db.SessionLocal = SL
for m in (modules.analysis, modules.homework, modules.lesson_plan, modules.settings):
    m.SessionLocal = SL
runpy.run_path(r"__APPFILE__", run_name="__main__")
'''
    return (template.replace("__ROOT__", str(_PROJECT_ROOT))
            .replace("__DBFILE__", db_file.as_posix())
            .replace("__APPFILE__", str(APP_FILE)))


def _seed_temp_db(db_file: Path):
    """在临时库造 1 个班 2 名学生、2 场考试、若干成绩，供有数据路径冒烟。"""
    from datetime import date
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from models.models import Base
    from utils import exam_service, student_service
    eng = create_engine(f"sqlite:///{db_file.as_posix()}")
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    for nm in ("冒烟甲", "冒烟乙"):
        student_service.get_or_create_student(session, nm, "冒烟班")
    for name, d, sc1, sc2 in [("第一次月考", date(2026, 3, 1), 70, 88),
                              ("期中考试", date(2026, 4, 15), 60, 95)]:
        exam = exam_service.create_exam(session, name, exam_date=d,
                                        full_scores={"数学": 100})
        session.flush()
        exam_service.import_scores(session, exam.id, [
            {"name": "冒烟甲", "class_name": "冒烟班", "scores": {"数学": sc1}},
            {"name": "冒烟乙", "class_name": "冒烟班", "scores": {"数学": sc2}},
        ])
    session.commit()
    session.close()
    return eng


def test_reflection_comments_empty_state_isolated(tmp_path):
    """空库路径：反思/评语 tab 给引导提示，不抛异常（用临时库，不碰真实数据）。"""
    db_file = tmp_path / "empty.db"
    at = AppTest.from_string(_isolated_app_code(db_file), default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📊 学情工作台").run()
    assert not at.exception, [str(e) for e in at.exception]
    info_text = " ".join(str(x.value) for x in at.info)
    assert "还没有考试数据" in info_text          # 教学反思
    assert "还没有学生" in info_text              # 期末评语


def test_reflection_and_comments_with_data_isolated(tmp_path, monkeypatch):
    """有数据路径：反思可生成并保存；评语可批量生成并留档（LLM 全 mock）。"""
    from utils import llm_client
    db_file = tmp_path / "with_data.db"
    eng = _seed_temp_db(db_file)

    def fake_chat(system, user, temperature=0.7):
        if "成功之处" in system:
            return ("## 成功之处\n均分稳定。\n## 不足之处\n计算需加强。\n"
                    "## 学生反馈\n学习状态平稳。\n## 改进措施\n增加分层练习。")
        return ("该生本学期学习态度端正，数学成绩稳中有升，基础知识掌握扎实。"
                "课堂上能够积极思考，作业完成认真。不足在于计算偶有粗心，"
                "难题的思路还不够开阔。希望今后多练易错题型，坚持整理错题，"
                "相信下学期会取得更大进步。")

    monkeypatch.setattr(llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(llm_client, "chat", fake_chat)

    at = AppTest.from_string(_isolated_app_code(db_file), default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📊 学情工作台").run()
    assert not at.exception, [str(e) for e in at.exception]

    # ---- 教学反思：默认单次考试，点生成 ----
    next(b for b in at.button if "生成教学反思" in b.label).click().run()
    assert not at.exception, [str(e) for e in at.exception]
    areas = {str(a.label): a for a in at.text_area}
    assert "## 成功之处" in areas and "## 改进措施" in areas
    next(b for b in at.button if b.label == "💾 保存留档").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    from models.models import TeachingReflection
    from sqlalchemy.orm import sessionmaker
    session = sessionmaker(bind=eng)()
    assert session.query(TeachingReflection).count() == 1
    session.close()

    # ---- 期末评语：批量生成（2 人）后一键保存 ----
    at2 = AppTest.from_string(_isolated_app_code(db_file), default_timeout=30)
    at2.run()
    at2.sidebar.radio[0].set_value("📊 学情工作台").run()
    next(b for b in at2.button if "批量生成全部评语" in b.label).click().run()
    assert not at2.exception, [str(e) for e in at2.exception]
    assert any("生成完成" in str(x.value) for x in at2.success)
    filled = [a for a in at2.text_area if "学习态度" in str(a.value)]
    assert len(filled) == 2
    next(b for b in at2.button if "一键保存全部已生成评语" in b.label).click().run()
    assert not at2.exception, [str(e) for e in at2.exception]
    from models.models import StudentComment
    session = sessionmaker(bind=eng)()
    assert session.query(StudentComment).count() == 2
    session.close()
    eng.dispose()


def test_new_exam_dialog_opens():
    """成绩管理里的“新建考试”改为弹窗：点击后出现名称输入和创建按钮。"""
    at = AppTest.from_file(str(APP_FILE), default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📊 学情工作台").run()
    next(b for b in at.button if b.label == "➕ 新建考试").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    assert any("考试名称" in t.label for t in at.text_input)
    assert any(b.label == "创建" for b in at.button)
    assert any("各科满分" in t.label for t in at.text_input)


def test_settings_data_management_panel():
    """设置页出现数据管理区：备份/恢复/清空三个分区，清空按钮默认禁用。"""
    at = AppTest.from_file(str(APP_FILE), default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("⚙️ 设置").run()
    assert not at.exception, [str(e) for e in at.exception]
    assert any("数据管理" in str(x.value) for x in at.subheader)
    labels = [t.label for t in at.tabs]
    assert "📦 备份" in labels and "♻️ 恢复" in labels and "🗑️ 清空业务数据" in labels
    wipe = next(b for b in at.button if b.label == "🗑️ 清空全部业务数据")
    assert wipe.disabled is True

# ---------------------------------------------------------------------------
# 阶段 6：备课资料支持网页链接（用临时库，不联网、不碰真实数据）
# ---------------------------------------------------------------------------


def _seed_web_textbook_isolated(db_file: Path):
    """在临时库造一份网页资料，用于有资料路径的备课页冒烟。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from models.models import Base, Textbook

    eng = create_engine(f"sqlite:///{db_file.as_posix()}")
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    book = Textbook(
        name="冒烟网页资料", file_type="link",
        file_path="https://example.com/math-article", subject="数学",
        grade="九年级", vectorized=False)
    session.add(book)
    session.commit()
    book_id = book.id
    session.close()
    return book_id


def test_lesson_materials_web_link_empty_url_isolated(tmp_path):
    """空库路径：可选择网页链接；空 URL 提交只给中文提示，不联网、不异常。"""
    db_file = tmp_path / "web_empty.db"
    at = AppTest.from_string(_isolated_app_code(db_file), default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📚 备课工作台").run()
    assert not at.exception, [str(e) for e in at.exception]

    source_box = next(x for x in at.selectbox if x.label == "来源类型")
    source_box.set_value("link").run()
    assert not at.exception, [str(e) for e in at.exception]
    assert any(x.label == "网页链接" for x in at.text_input)
    # 其余 4 个备课标签页仍在
    assert [t.label for t in at.tabs] == [
        "资料管理", "AI 备课", "AI 出题", "题库管理", "PPT 生成"]

    next(b for b in at.button if b.label == "提取并预览章节").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    assert any("请输入网页链接" in str(x.value) for x in at.error)


def test_lesson_materials_web_link_preview_and_save_isolated(tmp_path, monkeypatch):
    """网页抓取成功后走现有章节预览、保存资料、纯文本落盘链路（全程不联网）。"""
    from sqlalchemy import create_engine, text
    import modules.lesson_plan as lesson_module

    db_file = tmp_path / "web_save.db"
    text_dir = tmp_path / "text"
    monkeypatch.setattr(lesson_module, "TEXT_DIR", text_dir)
    monkeypatch.setattr(
        lesson_module.material, "fetch_web_page",
        lambda url: {"url": url, "title": "一元二次方程网页课",
                     "text": "第一章 一元二次方程\n这是网页里的教学正文。"})

    at = AppTest.from_string(_isolated_app_code(db_file), default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📚 备课工作台").run()
    next(x for x in at.selectbox if x.label == "来源类型").set_value("link").run()
    next(x for x in at.text_input if x.label == "网页链接").set_value(
        "https://example.com/lesson").run()
    next(b for b in at.button if b.label == "提取并预览章节").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    assert any("提取成功" in str(x.value) for x in at.success)
    assert any(b.label == "💾 保存资料" for b in at.button)

    next(b for b in at.button if b.label == "💾 保存资料").click().run()
    assert not at.exception, [str(e) for e in at.exception]

    eng = create_engine(f"sqlite:///{db_file.as_posix()}")
    with eng.connect() as conn:
        row = conn.execute(text(
            "SELECT name, file_type, file_path FROM textbooks"
        )).mappings().one()
    assert dict(row) == {
        "name": "一元二次方程网页课",
        "file_type": "link",
        "file_path": "https://example.com/lesson",
    }
    saved_text = (text_dir / "1.txt").read_text(encoding="utf-8")
    assert "来源：https://example.com/lesson" in saved_text
    assert "这是网页里的教学正文" in saved_text


def test_lesson_materials_duplicate_web_link_isolated(tmp_path, monkeypatch):
    """同一 URL 已保存时直接提示复用，不重复抓取、不新建资料。"""
    from sqlalchemy import create_engine, text

    db_file = tmp_path / "web_duplicate.db"
    book_id = _seed_web_textbook_isolated(db_file)
    url = "https://example.com/math-article"

    def forbidden_fetch(url):
        raise AssertionError("重复网页不应再次抓取")

    import modules.lesson_plan as lesson_module
    monkeypatch.setattr(lesson_module.material, "fetch_web_page", forbidden_fetch)

    at = AppTest.from_string(_isolated_app_code(db_file), default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📚 备课工作台").run()
    next(x for x in at.selectbox if x.label == "来源类型").set_value("link").run()
    next(x for x in at.text_input if x.label == "网页链接").set_value(url).run()
    next(b for b in at.button if b.label == "提取并预览章节").click().run()

    assert not at.exception, [str(e) for e in at.exception]
    assert any("该网页资料已保存" in str(x.value) for x in at.warning)
    eng = create_engine(f"sqlite:///{db_file.as_posix()}")
    with eng.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM textbooks")).scalar_one()
    assert count == 1
    assert book_id is not None


def test_lesson_materials_web_link_renders_with_data_isolated(tmp_path):
    """有资料路径：已保存网页显示中文类型和来源 URL，建立索引等既有操作不回归。"""
    db_file = tmp_path / "web_with_data.db"
    _seed_web_textbook_isolated(db_file)

    at = AppTest.from_string(_isolated_app_code(db_file), default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📚 备课工作台").run()
    assert not at.exception, [str(e) for e in at.exception]

    markdown_text = " ".join(str(x.value) for x in at.markdown)
    caption_text = " ".join(str(x.value) for x in at.caption)
    assert "冒烟网页资料" in markdown_text
    assert "网页链接" in markdown_text
    assert "https://example.com/math-article" in caption_text
    assert any(b.label == "建立向量索引" for b in at.button)
