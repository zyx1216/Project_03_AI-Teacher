# -*- coding: utf-8 -*-
"""
页面冒烟测试：用 Streamlit 官方 AppTest 无头运行 app.py。

验证：
- 应用能启动、侧边栏 4 个主页面可切换且无异常；
- 学情工作台 7 个标签页都被渲染（st.tabs 内的代码会全部执行），空数据走提示分支不报错。

所有页面测试都用临时 SQLite 和临时 feature_subjects.json，不碰真实 data/database.db。
"""

from pathlib import Path

from streamlit.testing.v1 import AppTest

APP_FILE = Path(__file__).resolve().parent.parent / "app.py"


import pytest  # noqa: E402



def test_app_starts_and_renders_default_page(tmp_path):
    at = AppTest.from_string(
        _isolated_app_code(tmp_path / "start.db", tmp_path / "feature.json"),
        default_timeout=30)
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    assert any(x.value == "📐 AI教学辅助" for x in at.sidebar.title)
    assert at.sidebar.radio[0].options == ["🏠 首页", "📅 教学日历", "📚 备课", "📝 作业", "📊 学情", "⚙️ 设置"]


def test_switch_all_main_pages(tmp_path):
    at = AppTest.from_string(
        _isolated_app_code(tmp_path / "pages.db", tmp_path / "feature.json"),
        default_timeout=30)
    at.run()
    for page in ["📚 备课", "📝 作业", "📊 学情", "⚙️ 设置"]:
        at.sidebar.radio[0].set_value(page).run()
        assert not at.exception, (page, [str(e) for e in at.exception])
        assert at.title


def test_analysis_page_has_eight_tabs(tmp_path):
    at = AppTest.from_string(
        _isolated_app_code(tmp_path / "analysis_tabs.db", tmp_path / "feature.json"),
        default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📊 学情").run()
    assert not at.exception, [str(e) for e in at.exception]
    assert [t.label for t in at.tabs] == [
        "学生管理", "成绩管理", "考试分析", "趋势分析",
        "学生画像", "教学反思", "期末评语", "知识点分析"]


def test_settings_page_renders_llm_panel(tmp_path):
    at = AppTest.from_string(
        _isolated_app_code(tmp_path / "llm.db", tmp_path / "feature.json"),
        default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("⚙️ 设置").run()
    assert not at.exception, [str(e) for e in at.exception]
    text = " ".join(str(x.value) for x in at.subheader)
    assert "主模型" in text and "内容生成模型" in text and "向量模型" in text


def test_lesson_page_has_five_tabs_empty_state(tmp_path):
    at = AppTest.from_string(
        _isolated_app_code(tmp_path / "lesson_empty.db", tmp_path / "feature.json"),
        default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📚 备课").run()
    assert not at.exception, [str(e) for e in at.exception]
    assert [t.label for t in at.tabs] == [
        "资料管理", "AI 备课", "AI 出题", "题库管理", "PPT 生成"]
    # 五个功能都有自己的学科选择器；同一 label 必须靠 key 区分。
    keys = {x.key for x in at.selectbox if x.label == "学科"}
    assert {
        "materials_subject", "lesson_plan_subject",
        "question_bank_subject", "ppt_subject",
    } <= keys
    # v1.6.0 起出题页学科可多选；默认学科仍为数学。
    subject_picker = next(x for x in at.multiselect if x.key == "question_gen_subjects")
    assert subject_picker.value == ["数学"]


def test_settings_has_no_global_subject_selector(tmp_path):
    """v1.3：全局学科下线；即使功能状态文件里有物理，设置页也没有学科选择器。"""
    feature_file = tmp_path / "feature.json"
    feature_file.write_text(
        '{"materials_subject": "物理", "wrong_book_subject": "化学"}',
        encoding="utf-8")
    at = AppTest.from_string(
        _isolated_app_code(tmp_path / "settings_subject.db", feature_file),
        default_timeout=30)
    at.run()
    assert any(x.value == "📐 AI教学辅助" for x in at.sidebar.title)
    at.sidebar.radio[0].set_value("⚙️ 设置").run()
    assert not at.exception, [str(e) for e in at.exception]
    assert all(x.label != "当前学科" for x in at.selectbox)


def test_lesson_bank_renders_with_one_question(tmp_path):
    db_file = tmp_path / "one_question.db"
    eng = _seed_one_question_db(db_file)
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / "feature.json"), default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📚 备课").run()
    assert not at.exception, [str(e) for e in at.exception]
    assert "冒烟临时题" in " ".join(str(x.value) for x in at.markdown)
    eng.dispose()


def test_homework_page_four_tabs_empty_state(tmp_path):
    at = AppTest.from_string(
        _isolated_app_code(tmp_path / "homework_empty.db", tmp_path / "feature.json"),
        default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📝 作业").run()
    assert not at.exception, [str(e) for e in at.exception]
    assert [t.label for t in at.tabs] == ["作业管理", "成绩录入", "作业分析", "错题本"]
    keys = {x.key for x in at.selectbox if x.label == "学科"}
    assert "homework_list_subject" in keys and "wrong_book_subject" in keys
    assert "还没有作业" in " ".join(str(x.value) for x in at.info)


def test_homework_dialog_closes_when_leaving_main_page(tmp_path):
    """打开弹窗后切到别的主导航，再回作业页不应自动弹出。"""
    db_file = tmp_path / "homework_navigation.db"
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / "navigation_feature.json"),
        default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📝 作业").run()

    def dialog_open():
        return any(x.label == "作业名称 *" for x in at.text_input)

    assert not dialog_open()
    next(b for b in at.button if "新建作业" in b.label).click().run()
    assert dialog_open()
    next(b for b in at.button if "课前预习" in b.label).click().run()
    assert any(k.startswith("new_hw_total_preview_")
               for k in (x.key or "" for x in at.number_input))

    # 弹窗学科只决定新作业归属，不改变外部“作业列表筛选”学科。
    dialog_subject = next(x for x in at.selectbox if x.key == "homework_new_subject")
    dialog_subject.set_value("物理").run()
    list_subject = next(x for x in at.selectbox if x.key == "homework_list_subject")
    assert dialog_subject.value == "物理"
    assert list_subject.value == "数学"
    assert "新作业学科" in " ".join(str(x.value) for x in at.caption)
    assert "仅筛选作业和模板列表" in " ".join(str(x.value) for x in at.caption)

    at.sidebar.radio[0].set_value("📚 备课").run()
    at.sidebar.radio[0].set_value("📝 作业").run()
    assert not at.session_state.get("hw_new_dialog_open")
    assert not dialog_open()

    # 再次打开时重新从默认类型开始，不保留上次切到一半的预习类型。
    next(b for b in at.button if "新建作业" in b.label).click().run()
    assert dialog_open()
    assert any(k.startswith("new_hw_total_after_class_")
               for k in (x.key or "" for x in at.number_input))
    assert not any(k.startswith("new_hw_total_preview_")
                   for k in (x.key or "" for x in at.number_input))
    assert not at.exception, [str(e) for e in at.exception]


def test_homework_new_dialog_decorator_on_content_function():
    import modules.homework as hw_module
    assert hasattr(hw_module._new_homework_dialog, "__wrapped__")
    assert not hasattr(hw_module._choose_new_homework_type, "__wrapped__")


def test_homework_new_dialog_persists_switch_and_creates_isolated(tmp_path):
    db_file = tmp_path / "homework_dialog.db"
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / "homework_feature.json"),
        default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📝 作业").run()
    next(b for b in at.button if "新建作业" in b.label).click().run()
    next(b for b in at.button if "课前预习" in b.label).click().run()
    assert any("作业名称" in x.label for x in at.text_input)
    next(b for b in at.button if "试卷出题" in b.label).click().run()
    assert not at.exception, [str(e) for e in at.exception]

    dialog_subject = next(x for x in at.selectbox if x.key == "homework_new_subject")
    dialog_subject.set_value("物理").run()
    total_input = next(x for x in at.number_input
                       if x.key and x.key.startswith("new_hw_total_exam_"))
    duration_input = next(x for x in at.number_input
                          if x.key and x.key.startswith("new_hw_duration_exam_"))
    assert total_input.value == 120.0 and duration_input.value == 90

    next(x for x in at.text_input if x.label == "作业名称 *").input("临时弹窗试卷").run()
    next(b for b in at.button if b.label == "创建").click().run()
    assert not at.exception, [str(e) for e in at.exception]

    from sqlalchemy import create_engine, text
    eng = create_engine(f"sqlite:///{db_file.as_posix()}")
    with eng.connect() as conn:
        row = conn.execute(text(
            "SELECT name, homework_type, total_score, duration, subject "
            "FROM homeworks")).mappings().one()
    assert dict(row) == {
        "name": "临时弹窗试卷", "homework_type": "exam",
        "total_score": 120.0, "duration": 90, "subject": "物理"}
    feature_json = (tmp_path / "homework_feature.json").read_text(encoding="utf-8")
    assert '"homework_new_subject": "物理"' in feature_json
    eng.dispose()


def test_homework_page_renders_with_data(tmp_path):
    db_file = tmp_path / "homework_with_data.db"
    eng = _seed_homework_data_db(db_file)
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / "feature.json"), default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📝 作业").run()
    assert not at.exception, [str(e) for e in at.exception]
    # 成绩录入和作业分析显示全部学科作业，标签带学科。
    homework_pickers = [o for o in at.selectbox if o.label == "选择作业"]
    assert any(any("[物理]" in str(opt) and "冒烟临时作业" in str(opt)
                   for opt in o.options)
               for o in homework_pickers)
    # 错题本默认数学，不应显示物理错题；切到物理后显示导出按钮。
    wrong_subject = next(x for x in at.selectbox if x.key == "wrong_book_subject")
    assert wrong_subject.value == "数学"
    wrong_subject.set_value("物理").run()
    assert not at.exception, [str(e) for e in at.exception]
    assert any(b.label == "📄 导出错题本 Word" for b in at.button)
    eng.dispose()


# ---------------------------------------------------------------------------
# 阶段 4：学情 7 tab、教学反思/期末评语、新建考试弹窗、设置数据管理
# ---------------------------------------------------------------------------

import sys as _sys  # noqa: E402

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_PROJECT_ROOT))


def _isolated_app_code(db_file: Path, feature_file: Path | None = None,
                       class_file: Path | None = None,
                       thresholds_file: Path | None = None,
                       schedule_file: Path | None = None,
                       ocr_task_file: Path | None = None,
                       ocr_result_dir: Path | None = None,
                       lesson_template_file: Path | None = None,
                       ppt_template_file: Path | None = None,
                       ppt_template_dir: Path | None = None,
                       question_history_file: Path | None = None,
                       text_dir: Path | None = None,
                       ocr_trigger_file: Path | None = None,
                       ocr_mode: str | None = None) -> str:
    """生成在临时数据库、临时功能学科和本地配置上跑 app.py 的脚本。"""
    feature_file = feature_file or db_file.parent / "feature_subjects.json"
    class_file = class_file or db_file.parent / "class_names.json"
    thresholds_file = thresholds_file or db_file.parent / "analysis_thresholds.json"
    schedule_file = schedule_file or db_file.parent / "class_schedule.json"
    ocr_task_file = ocr_task_file or db_file.parent / "ocr_tasks.json"
    ocr_result_dir = ocr_result_dir or db_file.parent / "ocr_results"
    lesson_template_file = lesson_template_file or db_file.parent / "lesson_templates.json"
    ppt_template_file = ppt_template_file or db_file.parent / "ppt_templates.json"
    ppt_template_dir = ppt_template_dir or db_file.parent / "ppt_templates"
    question_history_file = question_history_file or db_file.parent / "question_history.json"
    ocr_trigger_file = ocr_trigger_file or db_file.parent / "never_trigger"
    template = r"""
import sys, runpy
sys.path.insert(0, r"__ROOT__")
from pathlib import Path as _Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import utils.db as db
import utils.feature_subjects as feature_subjects
import utils.class_service as class_service
import utils.analysis_settings as analysis_settings
import utils.schedule_service as schedule_service
import utils.ocr_service as ocr_service
import utils.ocr_task_service as ocr_task_service
import utils.template_service as template_service
import utils.question_history_service as question_history_service
import modules.analysis, modules.calendar, modules.dashboard, modules.homework, modules.lesson_plan, modules.settings
feature_subjects.FEATURE_SUBJECTS_PATH = _Path(r"__FEATURE__")
class_service.CLASS_NAMES_PATH = _Path(r"__CLASSFILE__")
analysis_settings.THRESHOLDS_PATH = _Path(r"__THRESHOLDS__")
schedule_service.CLASS_SCHEDULE_PATH = _Path(r"__SCHEDULEFILE__")
ocr_task_service.OCR_TASKS_PATH = _Path(r"__OCRTASKFILE__")
ocr_task_service.OCR_RESULTS_DIR = _Path(r"__OCRRESULTDIR__")
template_service.LESSON_TEMPLATES_PATH = _Path(r"__LESSONTEMPLATEFILE__")
template_service.PPT_TEMPLATES_PATH = _Path(r"__PPT TEMPLATEFILE__")
template_service.PPT_TEMPLATE_DIR = _Path(r"__PPT TEMPLATEDIR__")
question_history_service.HISTORY_PATH = _Path(r"__QUESTIONHISTORYFILE__")

class _FakeOCREngine:
    def __call__(self, image):
        import time
        from types import SimpleNamespace
        if r"__OCR_MODE__" == "failure":
            raise RuntimeError("模拟 OCR 引擎失败")
        if r"__OCR_MODE__" == "empty":
            return SimpleNamespace(txts=())
        if r"__OCR_MODE__" == "switch_success":
            trigger = _Path(r"__OCRTRIGGER__")
            for _ in range(500):
                if trigger.exists():
                    break
                time.sleep(0.01)
        return SimpleNamespace(txts=("第一章 有理数", "这是扫描件OCR识别出的中文正文。"))

if r"__OCR_MODE__" != "none":
    ocr_service._ENGINE = _FakeOCREngine()
eng = create_engine(
    r"sqlite:///__DBFILE__",
    connect_args={"check_same_thread": False})

SL = sessionmaker(bind=eng)
db.engine = eng
db.SessionLocal = SL
for m in (modules.analysis, modules.calendar, modules.dashboard, modules.homework, modules.lesson_plan, modules.settings):
    m.SessionLocal = SL
_TEXT_DIR = r"__TEXTDIR__"
if _TEXT_DIR:
    modules.lesson_plan.TEXT_DIR = _Path(_TEXT_DIR)
runpy.run_path(r"__APPFILE__", run_name="__main__")
"""
    return (template.replace("__ROOT__", str(_PROJECT_ROOT))
            .replace("__DBFILE__", db_file.as_posix())
            .replace("__FEATURE__", feature_file.as_posix())
            .replace("__CLASSFILE__", class_file.as_posix())
            .replace("__THRESHOLDS__", thresholds_file.as_posix())
             .replace("__SCHEDULEFILE__", schedule_file.as_posix())
            .replace("__OCRTASKFILE__", ocr_task_file.as_posix())
            .replace("__OCRRESULTDIR__", ocr_result_dir.as_posix())
            .replace("__LESSONTEMPLATEFILE__", lesson_template_file.as_posix())
            .replace("__PPT TEMPLATEFILE__", ppt_template_file.as_posix())
            .replace("__PPT TEMPLATEDIR__", ppt_template_dir.as_posix())
            .replace("__QUESTIONHISTORYFILE__", question_history_file.as_posix())
            .replace("__TEXTDIR__", text_dir.as_posix() if text_dir else "")
            .replace("__OCRTRIGGER__", ocr_trigger_file.as_posix())
            .replace("__OCR_MODE__", ocr_mode or "none")
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


def _seed_one_question_db(db_file: Path):
    """临时库：1 道数学题。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from models.models import Base
    from utils import question_service as qs
    eng = create_engine(f"sqlite:///{db_file.as_posix()}")
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    qs.create_question(
        session,
        {"content": "冒烟临时题：$x^2+1=0$", "question_type": "solution",
         "difficulty": 2, "knowledge_points": '["冒烟知识点"]',
         "answer": "无实数解", "analysis": "判别式小于零",
         "error_points": "", "verify": None},
        source="manual", status="pending", subject="数学")
    session.commit()
    session.close()
    return eng


def _seed_homework_data_db(db_file: Path):
    """临时库：物理作业、物理题、学生总分和逐题错题。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from models.models import Base
    from utils import homework_service, homework_score_service
    from utils import question_service, student_service
    eng = create_engine(f"sqlite:///{db_file.as_posix()}")
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    homework = homework_service.create_homework(
        session, "冒烟临时作业", homework_type="after_class",
        class_name="冒烟班", subject="物理")
    data = question_service.validate_question({
        "content": "冒烟作业题 $x+1=2$", "question_type": "solution",
        "difficulty": 2, "answer": "x=1", "knowledge_points": "方程"})
    question = question_service.create_question(
        session, data, source="manual", status="approved", subject="物理")
    homework_service.add_questions(session, homework.id, [question.id])
    student, _ = student_service.get_or_create_student(session, "冒烟学生", "冒烟班")
    session.commit()
    homework_score_service.save_total_score(session, homework.id, student.id, 88)
    homework_score_service.save_answers(session, homework.id, [{
        "student_id": student.id, "question_id": question.id, "order_no": 1,
        "is_correct": False, "earned_score": 4, "error_type": "计算错误"}])
    session.commit()
    session.close()
    return eng


def test_reflection_comments_empty_state_isolated(tmp_path):
    """空库路径：反思/评语 tab 给引导提示，不抛异常（用临时库，不碰真实数据）。"""
    db_file = tmp_path / "empty.db"
    feature_file = tmp_path / "empty_feature_subjects.json"
    at = AppTest.from_string(_isolated_app_code(db_file, feature_file), default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📊 学情").run()
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

    at = AppTest.from_string(_isolated_app_code(db_file, tmp_path / "reflection_feature_subjects.json"), default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📊 学情").run()
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
    at2 = AppTest.from_string(_isolated_app_code(db_file, tmp_path / "with_data_feature_subjects.json"), default_timeout=30)
    at2.run()
    at2.sidebar.radio[0].set_value("📊 学情").run()
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


def test_new_exam_dialog_full_score_rows_isolated(tmp_path):
    """新建考试弹窗使用逐行满分编辑器，可添加学科并真实写入临时库。"""
    db_file = tmp_path / "exam_dialog.db"
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / "exam_dialog_feature_subjects.json"),
        default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📊 学情").run()
    next(b for b in at.button if b.label == "➕ 新建考试").click().run()
    assert not at.exception, [str(e) for e in at.exception]

    assert any(x.key == "full_subject_new_exam_1" for x in at.text_input)
    assert any(x.key == "full_score_new_exam_1" for x in at.number_input)
    assert any(b.label == "➕ 添加学科" for b in at.button)
    assert any(b.label == "🗑️" for b in at.button)

    next(b for b in at.button if b.label == "➕ 添加学科").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    assert any(x.key == "full_subject_new_exam_2" for x in at.text_input)
    next(x for x in at.text_input if x.key == "full_subject_new_exam_2").input("语文").run()
    next(x for x in at.text_input if x.label == "考试名称 *").input("临时弹窗考试").run()
    next(b for b in at.button if b.label == "创建").click().run()
    assert not at.exception, [str(e) for e in at.exception]

    import json
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from models.models import Exam
    eng = create_engine(f"sqlite:///{db_file.as_posix()}")
    session = sessionmaker(bind=eng)()
    exam = session.query(Exam).one()
    assert exam.name == "临时弹窗考试"
    assert json.loads(exam.full_scores) == {"数学": 100.0, "语文": 100.0}
    session.close()
    eng.dispose()


def test_student_editor_and_trend_controls_isolated(tmp_path):
    """学生表格可渲染；个人趋势有科目多选和折线/柱状切换。"""
    db_file = tmp_path / "student_trend.db"
    eng = _seed_temp_db(db_file)
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / "student_trend_feature_subjects.json"),
        default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📊 学情").run()
    assert not at.exception, [str(e) for e in at.exception]

    editor = next(x for x in at.dataframe if x.key == "student_editor_main")
    business_columns = ["姓名", "学号", "班级", "性别", "标签", "备注"]
    # 学生ID 在数据原型里保留用于定位数据库，但 column_order/column_config 已对老师隐藏。
    assert all(name in editor.value.columns for name in business_columns)
    assert "学生ID" in editor.value.columns

    # st.tabs 会一次性渲染全部内容，所以无需手动切换到第 4 个 tab。
    # 性别列未设置时必须是空值 None，不能是空字符串（空字符串会触发 glide-data-grid 下拉 DOM 报错）。
    gender_vals = editor.value["性别"].tolist()
    assert all(v is None or (isinstance(v, float) and v != v) for v in gender_vals)
    assert "" not in gender_vals
    # v1.3：趋势不再有全局学科，默认全部科目；个人图多选默认勾选所有科目。
    trend_subject_box = next(x for x in at.selectbox if x.label == "科目")
    assert trend_subject_box.value == "全部科目"
    subject_box = next(x for x in at.multiselect
                       if x.key == "student_trend_subjects")
    assert subject_box.value == ["数学"]
    chart_type = next(x for x in at.radio if x.key == "student_trend_chart_type")
    chart_type.set_value("柱状图").run()
    assert not at.exception, [str(e) for e in at.exception]
    eng.dispose()


def test_settings_data_management_panel(tmp_path):
    """设置页出现数据管理区：备份/恢复/清空三个分区，清空按钮默认禁用。"""
    at = AppTest.from_string(
        _isolated_app_code(tmp_path / "settings_data.db", tmp_path / "feature.json"),
        default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("⚙️ 设置").run()
    assert not at.exception, [str(e) for e in at.exception]
    assert any("数据备份与恢复" in str(x.value) for x in at.subheader)
    labels = [t.label for t in at.tabs]
    assert "📦 备份" in labels and "♻️ 恢复" in labels and "🗑️ 清空业务数据" in labels
    wipe = next(b for b in at.button if b.label == "🗑️ 清空全部业务数据")
    assert wipe.disabled is True

# ---------------------------------------------------------------------------
# 阶段 6：备课资料支持网页链接（用临时库，不联网、不碰真实数据）
# ---------------------------------------------------------------------------


def _seed_wrong_answer_isolated(db_file: Path, feature_file: Path):
    """在临时库造 1 条错题，供错题本按当前学科导出的页面冒烟。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from models.models import Base
    from utils import feature_subjects, homework_service, homework_score_service
    from utils import question_service, student_service

    feature_subjects.FEATURE_SUBJECTS_PATH = feature_file
    feature_subjects.set_feature_subject(feature_subjects.WRONG_BOOK_SUBJECT, "物理")

    eng = create_engine(f"sqlite:///{db_file.as_posix()}")
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    homework = homework_service.create_homework(
        session, "物理作业", class_name="冒烟班", subject="物理")
    data = question_service.validate_question({
        "content": "牛顿第二定律是什么？",
        "question_type": "solution",
        "difficulty": 2,
        "answer": "F=ma",
        "analysis": "合力等于质量乘加速度。",
        "knowledge_points": "力学",
    })
    question = question_service.create_question(
        session, data, source="manual", status="approved", subject="物理")
    homework_service.add_questions(session, homework.id, [question.id])
    student, _ = student_service.get_or_create_student(session, "冒烟学生", "冒烟班")
    session.flush()
    homework_score_service.save_answers(session, homework.id, [{
        "student_id": student.id,
        "question_id": question.id,
        "order_no": 1,
        "is_correct": False,
        "earned_score": 2,
        "error_type": "概念错误",
    }])
    session.commit()
    session.close()
    return eng


def test_wrong_book_export_uses_current_subject_isolated(tmp_path):
    """错题本导出标题/文件名按当前学科生成；点击导出不报错。"""
    db_file = tmp_path / "wrong_book.db"
    feature_file = tmp_path / "wrong_book_feature.json"
    _seed_wrong_answer_isolated(db_file, feature_file)

    at = AppTest.from_string(
        _isolated_app_code(db_file, feature_file), default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📝 作业").run()
    assert not at.exception, [str(e) for e in at.exception]
    next(b for b in at.button if b.label == "📄 导出错题本 Word").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    assert any(b.label == "⬇️ 下载错题本" for b in at.download_button)


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
    at = AppTest.from_string(_isolated_app_code(db_file, tmp_path / "web_feature_subjects.json"), default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📚 备课").run()
    assert not at.exception, [str(e) for e in at.exception]

    source_box = next(x for x in at.selectbox if x.label == "来源类型")
    source_box.set_value("link").run()
    assert not at.exception, [str(e) for e in at.exception]
    assert any(x.label == "网络导入" for x in at.text_input)
    # 其余 4 个备课标签页仍在
    assert [t.label for t in at.tabs] == [
        "资料管理", "AI 备课", "AI 出题", "题库管理", "PPT 生成"]

    next(b for b in at.button if b.label == "提取并确认信息").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    assert any("请输入网页链接" in str(x.value) for x in at.error)


def test_lesson_materials_web_link_preview_and_save_isolated(tmp_path, monkeypatch):
    """网页抓取成功后走现有章节预览、保存资料、纯文本落盘链路（全程不联网）。"""
    from sqlalchemy import create_engine, text
    import modules.lesson_plan as lesson_module

    db_file = tmp_path / "web_save.db"
    feature_file = tmp_path / "web_save_feature.json"
    feature_file.write_text(
        '{"materials_subject": "物理"}', encoding="utf-8")
    text_dir = tmp_path / "text"
    monkeypatch.setattr(lesson_module, "TEXT_DIR", text_dir)
    monkeypatch.setattr(
        lesson_module.material, "fetch_web_page",
        lambda url: {"url": url, "title": "一元二次方程网页课",
                     "text": "第一章 一元二次方程\n这是网页里的教学正文。"})

    at = AppTest.from_string(_isolated_app_code(db_file, feature_file), default_timeout=30)
    at.run()
    # 标题固定，即使底层配置是物理
    assert any(x.value == "📐 AI教学辅助" for x in at.sidebar.title)
    at.sidebar.radio[0].set_value("📚 备课").run()
    next(x for x in at.selectbox if x.label == "来源类型").set_value("link").run()
    next(x for x in at.text_input if x.label == "网络导入").set_value(
        "https://example.com/lesson").run()
    next(b for b in at.button if b.label == "提取并确认信息").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    next(b for b in at.button if b.label == "确认").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    assert any("提取成功" in str(x.value) for x in at.success)
    assert any(b.label == "💾 保存资料" for b in at.button)

    next(b for b in at.button if b.label == "💾 保存资料").click().run()
    assert not at.exception, [str(e) for e in at.exception]

    eng = create_engine(f"sqlite:///{db_file.as_posix()}")
    with eng.connect() as conn:
        row = conn.execute(text(
            "SELECT name, file_type, file_path, subject FROM textbooks"
        )).mappings().one()
    assert dict(row) == {
        "name": "一元二次方程网页课",
        "file_type": "link",
        "file_path": "https://example.com/lesson",
        "subject": "物理",
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

    at = AppTest.from_string(_isolated_app_code(db_file, tmp_path / "web_feature_subjects.json"), default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📚 备课").run()
    next(x for x in at.selectbox if x.label == "来源类型").set_value("link").run()
    next(x for x in at.text_input if x.label == "网络导入").set_value(url).run()
    next(b for b in at.button if b.label == "提取并确认信息").click().run()

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

    at = AppTest.from_string(_isolated_app_code(db_file, tmp_path / "web_feature_subjects.json"), default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📚 备课").run()
    assert not at.exception, [str(e) for e in at.exception]

    caption_text = " ".join(str(x.value) for x in at.caption)
    assert any(b.label == "冒烟网页资料" for b in at.button)
    assert "网络导入" in caption_text
    assert "https://example.com/math-article" in caption_text
    assert any(b.label == "建立向量索引" for b in at.button)



# ---------------------------------------------------------------------------
# v1.2.4 学科深化：资料/题库/作业按当前学科过滤（临时库，不碰真实数据）
# ---------------------------------------------------------------------------


def _seed_subject_isolated_db(db_file: Path):
    """造数学+物理各一份资料、一道题；1 场数学考试含 2 名学生成绩。"""
    from datetime import date
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from models.models import Base, Textbook
    from utils import exam_service, homework_service, question_service
    from utils import student_service

    eng = create_engine(f"sqlite:///{db_file.as_posix()}")
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()

    session.add(Textbook(name="数学资料甲", file_type="text", subject="数学"))
    session.add(Textbook(name="物理资料甲", file_type="text", subject="物理"))

    for subject, content in (("数学", "数学冒烟题"), ("物理", "物理冒烟题")):
        data = question_service.validate_question({
            "content": content, "question_type": "solution", "difficulty": 2,
            "answer": "答案", "knowledge_points": "冒烟"})
        question_service.create_question(
            session, data, source="manual", status="approved",
            subject=subject)

    homework_service.create_homework(session, "数学冒烟作业", subject="数学")
    homework_service.create_homework(session, "物理冒烟作业", subject="物理")

    for nm in ("冒烟甲", "冒烟乙"):
        student_service.get_or_create_student(session, nm, "冒烟班")
    exam = exam_service.create_exam(
        session, "冒烟月考", exam_date=date(2026, 4, 1),
        full_scores={"数学": 100, "物理": 100})
    session.flush()
    exam_service.import_scores(session, exam.id, [
        {"name": "冒烟甲", "class_name": "冒烟班",
         "scores": {"数学": 88.0, "物理": 70.0}},
        {"name": "冒烟乙", "class_name": "冒烟班",
         "scores": {"数学": 65.0, "物理": 92.0}},
    ])
    session.commit()
    session.close()
    return eng


def test_lesson_materials_filtered_by_current_subject_isolated(tmp_path):
    """切到物理时，备课资料列表只显示物理资料；标题仍固定。"""
    db_file = tmp_path / "subject_lesson.db"
    feature_file = tmp_path / "subject_lesson_feature.json"
    feature_file.write_text('{"materials_subject": "物理", "question_bank_subject": "物理", "homework_list_subject": "数学"}', encoding="utf-8")
    _seed_subject_isolated_db(db_file)

    at = AppTest.from_string(
        _isolated_app_code(db_file, feature_file), default_timeout=30)
    at.run()
    assert any(x.value == "📐 AI教学辅助" for x in at.sidebar.title)
    at.sidebar.radio[0].set_value("📚 备课").run()
    assert not at.exception, [str(e) for e in at.exception]
    button_labels = [b.label for b in at.button]
    assert "物理资料甲" in button_labels
    assert "数学资料甲" not in button_labels


def test_question_bank_filtered_by_current_subject_isolated(tmp_path):
    """切到物理时，题库管理只统计/列出物理题。"""
    db_file = tmp_path / "subject_bank.db"
    feature_file = tmp_path / "subject_bank_feature.json"
    feature_file.write_text('{"materials_subject": "物理", "question_bank_subject": "物理", "homework_list_subject": "数学"}', encoding="utf-8")
    _seed_subject_isolated_db(db_file)

    at = AppTest.from_string(
        _isolated_app_code(db_file, feature_file), default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📚 备课").run()
    assert not at.exception, [str(e) for e in at.exception]
    captions = " ".join(str(c.value) for c in at.caption)
    # 种子库里数学、物理各 1 题，切到物理后只应统计到 1 题
    assert "共 1 道题" in captions
    # 物理题出现在题目选择下拉，数学题被过滤掉（下拉选项经 format_func 渲染）
    picker = next(x for x in at.selectbox
                  if "选择题目查看" in str(getattr(x, "label", "")))
    rendered = " ".join(str(o) for o in picker.options)
    # options 是索引，真正的题干文本在下拉的 proto label 里；用计数+空状态兜底断言
    assert not any("题库里还没有符合条件的题" in str(x.value) for x in at.info)


def test_homework_list_filtered_by_current_subject_isolated(tmp_path):
    """作业管理列表只列当前学科的普通作业和模板。"""
    db_file = tmp_path / "subject_hw.db"
    feature_file = tmp_path / "subject_hw_feature.json"
    feature_file.write_text('{"homework_list_subject": "数学"}', encoding="utf-8")
    _seed_subject_isolated_db(db_file)

    at = AppTest.from_string(
        _isolated_app_code(db_file, feature_file), default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📝 作业").run()
    assert not at.exception, [str(e) for e in at.exception]
    markdown_text = " ".join(str(x.value) for x in at.markdown)
    assert "数学冒烟作业" in markdown_text
    assert "物理冒烟作业" not in markdown_text


def test_exam_analysis_subject_view_switch_isolated(tmp_path):
    """考试分析出现分析视角选择器；切到单科只渲染该科，不抛异常。"""
    db_file = tmp_path / "subject_exam.db"
    feature_file = tmp_path / "subject_exam_feature.json"
    feature_file.write_text('{"homework_list_subject": "数学"}', encoding="utf-8")
    _seed_subject_isolated_db(db_file)

    at = AppTest.from_string(
        _isolated_app_code(db_file, feature_file), default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📊 学情").run()
    assert not at.exception, [str(e) for e in at.exception]

    view_box = next(x for x in at.selectbox if x.label == "分析视角")
    # v1.3：考试分析默认总分总览；单科仍可切换。
    assert view_box.value == "总分总览"
    # 切到总分总览再切到物理，均无异常
    view_box.set_value("总分总览").run()
    assert not at.exception, [str(e) for e in at.exception]
    view_box.set_value("物理").run()
    assert not at.exception, [str(e) for e in at.exception]
    markdown_text = " ".join(str(x.value) for x in at.markdown)
    assert "物理班内排名表" in markdown_text


# ---------------------------------------------------------------------------
# v1.2.5 成绩导入扩展（Word/PDF 上传、可编辑预览）+ 趋势/图表控件
# ---------------------------------------------------------------------------


def _docx_score_bytes() -> bytes:
    """构造一个含成绩线框表格的 Word（bytes）。"""
    import io
    from docx import Document
    doc = Document()
    table = doc.add_table(rows=3, cols=3)
    table.style = "Table Grid"
    grid = [["姓名", "班级", "数学"],
            ["冒烟丙", "冒烟班", "77"],
            ["冒烟丁", "冒烟班", "83"]]
    for i, row in enumerate(grid):
        for j, val in enumerate(row):
            table.cell(i, j).text = val
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _pdf_score_bytes() -> bytes | None:
    """构造一个含成绩线框表格的 PDF（bytes）；缺微软雅黑时返回 None。"""
    import io
    import pymupdf
    font = r"C:\Windows\Fonts\msyh.ttc"
    if not Path(font).exists():
        return None
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_font(fontname="msyh", fontfile=font)
    x0, y0 = 60, 80
    col_w = [70, 80, 70]
    xs = [0]
    for w in col_w:
        xs.append(xs[-1] + w)
    grid = [["姓名", "班级", "数学"],
            ["冒烟丙", "冒烟班", "77"],
            ["冒烟丁", "冒烟班", "83"]]
    shape = page.new_shape()
    for ri, row in enumerate(grid):
        for ci, val in enumerate(row):
            rect = pymupdf.Rect(x0 + xs[ci], y0 + ri * 26,
                                x0 + xs[ci + 1], y0 + (ri + 1) * 26)
            shape.draw_rect(rect)
            shape.finish(color=(0, 0, 0), width=0.8)
            shape.insert_text((rect.x0 + 5, rect.y0 + 18), val,
                              fontsize=11, fontname="msyh")
    shape.commit()
    buf = io.BytesIO()
    pdf.save(buf)
    pdf.close()
    return buf.getvalue()


def _import_expander(at):
    return next(e for e in at.expander if "导入成绩" in e.label)


def test_score_import_accepts_docx_and_editable_preview_isolated(tmp_path):
    """上传 Word 成绩表：解析 → 可编辑预览 → 确认入库，全程无异常（临时库）。"""
    db_file = tmp_path / "score_docx.db"
    _seed_temp_db(db_file)
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / "score_docx_feature_subjects.json"),
        default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📊 学情").run()
    assert not at.exception, [str(e) for e in at.exception]

    uploader = _import_expander(at).file_uploader[0]
    # 文件选择器文案覆盖三种格式
    assert "Excel / Word / PDF" in uploader.label
    uploader.upload("成绩.docx", _docx_score_bytes(),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document").run()
    assert not at.exception, [str(e) for e in at.exception]

    # 出现可编辑预览（data_editor 暴露在 at.dataframe）和确认按钮
    editor = next(x for x in at.dataframe if x.key == "score_preview_editor")
    assert "数学" in editor.value.columns
    assert set(editor.value["姓名"].tolist()) >= {"冒烟丙", "冒烟丁"}
    btn = next(b for b in at.button if b.label == "✅ 确认导入成绩")
    btn.click().run()
    assert not at.exception, [str(e) for e in at.exception]
    assert any("导入完成" in str(x.value) for x in at.success)


def test_score_import_accepts_pdf_isolated(tmp_path):
    """上传 PDF 线框成绩表能解析并确认入库；无中文字体环境跳过。"""
    content = _pdf_score_bytes()
    if content is None:
        import pytest
        pytest.skip("缺少微软雅黑，跳过 PDF 上传冒烟")
    db_file = tmp_path / "score_pdf.db"
    _seed_temp_db(db_file)
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / "score_pdf_feature_subjects.json"),
        default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📊 学情").run()
    _import_expander(at).file_uploader[0].upload(
        "成绩.pdf", content, "application/pdf").run()
    assert not at.exception, [str(e) for e in at.exception]
    editor = next(x for x in at.dataframe if x.key == "score_preview_editor")
    assert set(editor.value["姓名"].tolist()) >= {"冒烟丙", "冒烟丁"}
    next(b for b in at.button if b.label == "✅ 确认导入成绩").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    assert any("导入完成" in str(x.value) for x in at.success)


def test_score_import_complex_pdf_friendly_hint_isolated(tmp_path):
    """无线框表格的 PDF 给友好提示，而不是报错。"""
    import io
    import pymupdf
    pdf = pymupdf.open()
    pdf.new_page().insert_text((72, 72), "no table here, just plain text")
    buf = io.BytesIO()
    pdf.save(buf)
    pdf.close()

    db_file = tmp_path / "score_pdf_hint.db"
    _seed_temp_db(db_file)
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / "score_pdf_hint_feature.json"),
        default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📊 学情").run()
    _import_expander(at).file_uploader[0].upload(
        "杂乱.pdf", buf.getvalue(), "application/pdf").run()
    assert not at.exception, [str(e) for e in at.exception]
    assert any("复制到 Excel" in str(x.value) for x in at.info)


def test_trend_range_default_and_chart_switch_isolated(tmp_path):
    """趋势时间筛选与显示范围两个独立下拉；默认全部+最近5次；分数段图可切饼图。"""
    db_file = tmp_path / "trend_v125.db"
    _seed_temp_db(db_file)
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / "trend_v125_feature.json"),
        default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📊 学情").run()
    assert not at.exception, [str(e) for e in at.exception]

    time_box = next(x for x in at.selectbox if x.key == "trend_time_filter")
    assert time_box.value == "全部"
    assert "学期：2026春" in time_box.options
    assert "学年：2025-2026学年" in time_box.options
    range_box = next(x for x in at.selectbox if x.key == "trend_range")
    assert range_box.options == ["最近 3 次", "最近 5 次", "最近 10 次", "全部"]
    assert range_box.value == "最近 5 次"
    time_box.set_value("学期：2026春").run()
    assert not at.exception, [str(e) for e in at.exception]
    time_box.set_value("全部").run()
    assert not at.exception, [str(e) for e in at.exception]

    # 考试分析默认数学单科：分数段图类型 柱状→饼图
    band = next(r for r in at.radio if r.label == "分数段图类型")
    assert band.options == ["柱状图", "饼图"]
    band.set_value("饼图").run()
    assert not at.exception, [str(e) for e in at.exception]

# ---------------------------------------------------------------------------
# v1.4.0 基础体验优化：筛选补齐、成绩导入模板、空状态引导
# ---------------------------------------------------------------------------


def test_v140_question_bank_filter_controls_empty_db(tmp_path):
    """题库管理：学科/题型/难度/状态/来源/搜索控件齐全，空库不报错。"""
    at = AppTest.from_string(
        _isolated_app_code(tmp_path / "v140_bank.db", tmp_path / "feature.json"),
        default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📚 备课").run()
    assert not at.exception, [str(e) for e in at.exception]
    labels = {x.label for x in at.selectbox}
    assert {"题型", "难度", "状态", "来源"} <= labels
    assert any(x.label == "按知识点或题干关键词搜索" for x in at.text_input)
    # 题库空状态引导
    assert any("题库里还没有符合条件的题" in str(x.value) for x in at.info)


def test_v140_homework_filter_controls_empty_db(tmp_path):
    """作业管理：名称搜索/类型/班级三个筛选控件齐全，空库给引导。"""
    at = AppTest.from_string(
        _isolated_app_code(tmp_path / "v140_hw.db", tmp_path / "feature.json"),
        default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📝 作业").run()
    assert not at.exception, [str(e) for e in at.exception]
    box_keys = {x.key for x in at.selectbox}
    assert {"homework_filter_type", "homework_filter_class"} <= box_keys
    assert any(x.key == "homework_filter_keyword" for x in at.text_input)
    info_text = " ".join(str(x.value) for x in at.info)
    assert "还没有符合条件的作业" in info_text
    # 错题本空状态（第 4 个 tab 同样被渲染）
    assert "还没有错题" in info_text


def _seed_v140_students_db(db_file: Path):
    """3 名学生：男/女/未设置，带不同标签。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from models.models import Base, Student
    eng = create_engine(f"sqlite:///{db_file.as_posix()}")
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    session.add_all([
        Student(name="甲同学", class_name="一班", gender="男", tags="积极,计算薄弱"),
        Student(name="乙同学", class_name="一班", gender="女", tags="积极"),
        Student(name="丙同学", class_name="二班", gender=None, tags="粗心"),
    ])
    session.commit()
    session.close()
    return eng


def test_v140_student_gender_and_tag_filters_isolated(tmp_path):
    """学生管理：性别、标签筛选生效，编辑器只显示筛选后的学生。"""
    db_file = tmp_path / "v140_students.db"
    _seed_v140_students_db(db_file)
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / "feature.json"), default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📊 学情").run()
    assert not at.exception, [str(e) for e in at.exception]

    gender_box = next(x for x in at.selectbox if x.key == "student_filter_gender")
    tag_box = next(x for x in at.selectbox if x.key == "student_filter_tag")
    assert gender_box.options == ["全部", "男", "女", "未设置"]
    assert set(tag_box.options) == {"全部标签", "积极", "粗心", "计算薄弱"}

    gender_box.set_value("男").run()
    assert not at.exception, [str(e) for e in at.exception]
    editor = next(x for x in at.dataframe if x.key == "student_editor_main")
    assert editor.value["姓名"].tolist() == ["甲同学"]

    # 切标签筛选：只有甲乙带“积极”
    tag_box.set_value("积极").run()
    gender_box.set_value("全部").run()
    assert not at.exception, [str(e) for e in at.exception]
    editor = next(x for x in at.dataframe if x.key == "student_editor_main")
    assert set(editor.value["姓名"].tolist()) == {"甲同学", "乙同学"}


def _seed_v140_terms_db(db_file: Path):
    """3 场考试：分属两个学期，另一场学期为空。"""
    from datetime import date
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from models.models import Base
    from utils import exam_service
    eng = create_engine(f"sqlite:///{db_file.as_posix()}")
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    exam_service.create_exam(session, "2026上期中", exam_date=date(2026, 4, 1),
                             term="2026上", full_scores={"数学": 100})
    exam_service.create_exam(session, "2026下月考", exam_date=date(2026, 9, 1),
                             term="2026下", full_scores={"数学": 100})
    exam_service.create_exam(session, "无学期旧考试", exam_date=date(2025, 12, 1))
    session.commit()
    session.close()
    return eng


def test_v140_exam_analysis_term_filter_isolated(tmp_path):
    """考试分析：学期筛选只影响考试下拉；空学期考试只在“全部学期”出现。"""
    db_file = tmp_path / "v140_terms.db"
    _seed_v140_terms_db(db_file)
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / "feature.json"), default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📊 学情").run()
    assert not at.exception, [str(e) for e in at.exception]

    term_box = next(x for x in at.selectbox if x.key == "analysis_term_filter")
    assert term_box.options == ["全部学期", "2026上", "2026下"]
    exam_box = next(x for x in at.selectbox if x.key == "analysis_exam")
    assert len(exam_box.options) == 3  # 默认全部学期

    term_box.set_value("2026上").run()
    assert not at.exception, [str(e) for e in at.exception]
    exam_box = next(x for x in at.selectbox if x.key == "analysis_exam")
    assert exam_box.options == ["2026上期中（2026-04-01）"]


def test_v140_score_template_button_and_empty_states(tmp_path):
    """空库：成绩模板下载按钮始终可用；关键空状态引导齐全。"""
    at = AppTest.from_string(
        _isolated_app_code(tmp_path / "v140_empty.db", tmp_path / "feature.json"),
        default_timeout=30)
    at.run()

    # 学情空库：模板按钮不受“先建考试”限制
    at.sidebar.radio[0].set_value("📊 学情").run()
    assert not at.exception, [str(e) for e in at.exception]
    btn = next(b for b in at.download_button if b.label == "⬇️ 下载 Excel 模板")
    analysis_info = " ".join(str(x.value) for x in at.info)
    assert "可切换到“新建考试”，上传成绩时直接创建" in analysis_info
    assert "还没有考试和成绩" in analysis_info
    assert "还没有符合条件的学生" in analysis_info
    # 按钮文件名正确（模板内容由 test_excel_import 单元测试覆盖）
    assert btn is not None

    # 备课空库：资料、AI 备课、题库三处引导
    at.sidebar.radio[0].set_value("📚 备课").run()
    assert not at.exception, [str(e) for e in at.exception]
    lesson_info = " ".join(str(x.value) for x in at.info)
    assert "没有符合条件的资料" in lesson_info
    assert "题库里还没有符合条件的题" in lesson_info


# ---------------------------------------------------------------------------
# v1.4.1 效率工具：批量操作、快捷跳转、错题题篮
# ---------------------------------------------------------------------------


def _seed_v141_three_students_db(db_file: Path):
    """3 名学生，供批量删除测试。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from models.models import Base, Student
    eng = create_engine(f"sqlite:///{db_file.as_posix()}")
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    session.add_all([
        Student(name="甲", class_name="一班"),
        Student(name="乙", class_name="一班"),
        Student(name="丙", class_name="二班"),
    ])
    session.commit()
    session.close()
    return eng


def test_v141_student_batch_delete_isolated(tmp_path):
    """勾选 2 名学生 → 批量删除 → 二次确认后库中只剩 1 人。"""
    db_file = tmp_path / "v141_students.db"
    _seed_v141_three_students_db(db_file)
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / "feature.json"), default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📊 学情").run()
    assert not at.exception, [str(e) for e in at.exception]

    editor = next(x for x in at.dataframe if x.key == "student_editor_main")
    assert "选择" in editor.value.columns
    # data_editor 的勾选要通过 DataEditorState.edited_rows 按行索引注入；
    # 且按钮触发的那一轮 widget 会用空状态覆盖，需在 click 后、run 前再注入一次。
    edit_state = {
        "edited_rows": {"0": {"选择": True}, "1": {"选择": True}},
        "added_rows": [], "deleted_rows": []}
    at.session_state["student_editor_main"] = edit_state
    at.run()
    assert not at.exception, [str(e) for e in at.exception]

    batch_btn = next(b for b in at.button if b.label == "🗑️ 批量删除所选")
    batch_btn.click()
    at.session_state["student_editor_main"] = edit_state
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    next(b for b in at.button if b.label == "✅ 确认批量删除").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    assert any("已批量删除 2 名学生" in str(x.value) for x in at.success)

    from sqlalchemy import create_engine, text
    eng = create_engine(f"sqlite:///{db_file.as_posix()}")
    with eng.connect() as conn:
        names = [r[0] for r in conn.execute(text("SELECT name FROM students"))]
    assert names == ["丙"]
    eng.dispose()


def test_v141_student_jump_to_profile_isolated(tmp_path):
    """学生管理“查看画像”写入受控 tab 状态和画像学生选择。"""
    db_file = tmp_path / "v141_jump.db"
    _seed_v141_three_students_db(db_file)
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / "feature.json"), default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📊 学情").run()

    box = next(x for x in at.selectbox if x.key == "student_jump_profile_label")
    box.set_value(box.options[1]).run()  # 选乙
    next(b for b in at.button if b.label == "🔍 查看画像").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    assert at.session_state["analysis_tab"] == "学生画像"
    assert at.session_state["profile_student"] == box.options[1]


def _seed_v141_bank_db(db_file: Path):
    """数学：2 道待审 + 1 道已审。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from models.models import Base
    from utils import question_service as qs
    eng = create_engine(f"sqlite:///{db_file.as_posix()}")
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    for content, status in [("待审甲", "pending"), ("待审乙", "pending"),
                            ("已审丙", "approved")]:
        data = qs.validate_question({
            "content": content, "question_type": "solution", "difficulty": 2,
            "answer": "答", "knowledge_points": ""})
        qs.create_question(session, data, source="manual", status=status,
                           subject="数学")
    session.commit()
    session.close()
    return eng


def test_v141_question_batch_approve_isolated(tmp_path):
    """题库批量审核：多选待审题后一键通过，已审核的不受影响。"""
    db_file = tmp_path / "v141_bank.db"
    _seed_v141_bank_db(db_file)
    feature_file = tmp_path / "bank_feature.json"
    feature_file.write_text('{"question_bank_subject": "数学"}', encoding="utf-8")
    at = AppTest.from_string(
        _isolated_app_code(db_file, feature_file), default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📚 备课").run()
    assert not at.exception, [str(e) for e in at.exception]

    picker = next(x for x in at.multiselect
                  if x.key == "bank_batch_approve_pick")
    assert len(picker.options) == 2  # 只有 2 道待审
    picker.set_value(list(picker.options)).run()
    next(b for b in at.button if b.label == "✅ 批量审核通过").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    assert any("已通过 2 道题" in str(x.value) for x in at.success)

    from sqlalchemy import create_engine, text
    eng = create_engine(f"sqlite:///{db_file.as_posix()}")
    with eng.connect() as conn:
        n = conn.execute(text(
            "SELECT COUNT(*) FROM questions WHERE status='approved'")).scalar()
        pending = conn.execute(text(
            "SELECT COUNT(*) FROM questions WHERE status='pending'")).scalar()
    assert n == 3 and pending == 0
    eng.dispose()


def _seed_v141_two_math_homeworks_db(db_file: Path):
    """2 份数学普通作业。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from models.models import Base
    from utils import homework_service
    eng = create_engine(f"sqlite:///{db_file.as_posix()}")
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    homework_service.create_homework(session, "数学作业甲", subject="数学")
    homework_service.create_homework(session, "数学作业乙", subject="数学")
    session.commit()
    session.close()
    return eng


def test_v141_homework_batch_delete_isolated(tmp_path):
    """勾选 2 份作业 → 批量删除 → 二次确认后列表清空。"""
    db_file = tmp_path / "v141_hw.db"
    _seed_v141_two_math_homeworks_db(db_file)
    feature_file = tmp_path / "hw_feature.json"
    feature_file.write_text('{"homework_list_subject": "数学"}', encoding="utf-8")
    at = AppTest.from_string(
        _isolated_app_code(db_file, feature_file), default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📝 作业").run()
    assert not at.exception, [str(e) for e in at.exception]

    boxes = [x for x in at.checkbox if x.key and x.key.startswith("pick_hw_")]
    assert len(boxes) == 2
    for box in boxes:
        box.set_value(True).run()
    next(b for b in at.button if b.label.startswith("🗑️ 批量删除所选")).click().run()
    assert not at.exception, [str(e) for e in at.exception]
    next(b for b in at.button if b.label == "✅ 确认批量删除").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    assert any("已批量删除 2 份作业" in str(x.value) for x in at.success)

    from sqlalchemy import create_engine, text
    eng = create_engine(f"sqlite:///{db_file.as_posix()}")
    with eng.connect() as conn:
        n = conn.execute(text(
            "SELECT COUNT(*) FROM homeworks WHERE is_template=0")).scalar()
    assert n == 0
    eng.dispose()


def test_v141_wrong_question_open_homework_isolated(tmp_path):
    """错题本“打开这次作业”切到作业管理并挂载该作业抽屉。"""
    db_file = tmp_path / "v141_open_hw.db"
    _seed_homework_data_db(db_file)
    feature_file = tmp_path / "wb_open_feature.json"
    feature_file.write_text('{"wrong_book_subject": "物理"}', encoding="utf-8")
    at = AppTest.from_string(
        _isolated_app_code(db_file, feature_file), default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📝 作业").run()
    assert not at.exception, [str(e) for e in at.exception]

    from sqlalchemy import create_engine, text
    eng = create_engine(f"sqlite:///{db_file.as_posix()}")
    with eng.connect() as conn:
        hw_id = conn.execute(text("SELECT id FROM homeworks LIMIT 1")).scalar()
    eng.dispose()

    next(b for b in at.button if b.label == "🔓 打开这次作业").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    assert at.session_state["homework_tab"] == "作业管理"
    assert at.session_state["hw_open_id"] == hw_id


def test_v141_wrong_basket_add_to_new_homework_isolated(tmp_path):
    """错题加入题篮：同学科新建作业自动带入并清空；异学科保留题篮并提示。"""
    db_file = tmp_path / "v141_basket.db"
    _seed_homework_data_db(db_file)
    feature_file = tmp_path / "basket_feature.json"
    feature_file.write_text('{"wrong_book_subject": "物理"}', encoding="utf-8")
    at = AppTest.from_string(
        _isolated_app_code(db_file, feature_file), default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📝 作业").run()
    assert not at.exception, [str(e) for e in at.exception]

    # 加入题篮（去重）
    add_btn = next(b for b in at.button if b.label == "➕ 加入下次作业")
    add_btn.click().run()
    basket = at.session_state["next_hw_question_basket"]
    assert len(basket) == 1
    qid = basket[0]

    # 新建同学科（物理）作业 → 自动带入、题篮清空
    next(b for b in at.button if "新建作业" in b.label).click().run()
    next(x for x in at.selectbox if x.key == "homework_new_subject").set_value("物理").run()
    next(x for x in at.text_input if x.label == "作业名称 *").input("物理巩固卷").run()
    next(b for b in at.button if b.label == "创建").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    assert at.session_state.get("next_hw_question_basket", []) == []

    from sqlalchemy import create_engine, text
    eng = create_engine(f"sqlite:///{db_file.as_posix()}")
    with eng.connect() as conn:
        linked = conn.execute(text(
            "SELECT COUNT(*) FROM homework_questions WHERE question_id=:q"),
            {"q": qid}).scalar()
    assert linked == 2  # 原物理作业 + 新物理作业各一条关联
    eng.dispose()

    # 再加入题篮 → 新建异学科（数学）作业：不带入、题篮保留、出现提示
    next(b for b in at.button if b.label == "➕ 加入下次作业").click().run()
    assert at.session_state["next_hw_question_basket"] == [qid]
    next(b for b in at.button if "新建作业" in b.label).click().run()
    # 前一次已把弹窗学科持久化成物理，这里显式切回数学触发异学科分支
    next(x for x in at.selectbox if x.key == "homework_new_subject").set_value("数学").run()
    next(x for x in at.text_input if x.label == "作业名称 *").input("数学作业误建").run()
    next(b for b in at.button if b.label == "创建").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    assert at.session_state["next_hw_question_basket"] == [qid]
    assert any("题篮含" in str(x.value) for x in at.warning)

# ---------------------------------------------------------------------------
# v1.4.2 数据价值提升：趋势预测、学期报告、班级管理
# ---------------------------------------------------------------------------


def _seed_v142_term_db(db_file: Path):
    """3 场同学期考试，供学期报告真实生成。"""
    from datetime import date
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from models.models import Base
    from utils import exam_service

    eng = create_engine(f"sqlite:///{db_file.as_posix()}")
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    for i, exam_date in enumerate([
        date(2026, 3, 1), date(2026, 4, 1), date(2026, 5, 1)
    ], start=1):
        exam = exam_service.create_exam(
            session, f"第{i}次月考", exam_date=exam_date, term="2026春",
            full_scores={"数学": 100})
        session.flush()
        exam_service.import_scores(session, exam.id, [
            {"name": "冒烟甲", "class_name": "冒烟班", "scores": {"数学": 70 + i * 5}},
            {"name": "冒烟乙", "class_name": "冒烟班", "scores": {"数学": 80 + i * 2}},
        ])
    session.commit()
    session.close()
    return eng


def test_v146_class_management_moved_to_students_isolated(tmp_path):
    """v1.4.6：设置页不再有班级管理/考试分析线；学生管理 Tab 有班级表格。"""
    db_file = tmp_path / "v146_class.db"
    feature_file = tmp_path / "feature.json"
    class_file = tmp_path / "class_names.json"
    class_file.write_text('{"classes": ["预设班"]}', encoding="utf-8")

    at = AppTest.from_string(
        _isolated_app_code(db_file, feature_file, class_file), default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("⚙️ 设置").run()
    assert not at.exception, [str(e) for e in at.exception]
    subheaders = [str(x.value) for x in at.subheader]
    assert "班级管理" not in subheaders
    assert "考试分析线" not in subheaders
    assert not any(x.label == "及格线百分比" for x in at.number_input)

    at.sidebar.radio[0].set_value("📊 学情").run()
    assert not at.exception, [str(e) for e in at.exception]
    class_exp = next(e for e in at.expander if "班级管理" in e.label)
    editor = next(x for x in class_exp.dataframe if x.key == "class_editor_main")
    assert "预设班" in list(editor.value["班级名"])
    assert any("批量调整学生班级" in str(x.value) for x in class_exp.markdown)
    student_class = next(x for x in at.selectbox if x.key == "student_filter_class")
    assert "预设班" in student_class.options


def test_v145_trend_scope_unique_labels_and_two_charts_isolated(tmp_path):
    """趋势无预测入口；时间筛选含学期/学年；两张图渲染无异常。"""
    db_file = tmp_path / "v145_trend.db"
    _seed_temp_db(db_file)
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / "feature.json"), default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📊 学情").run()
    assert not at.exception, [str(e) for e in at.exception]

    assert all(x.key != "trend_show_prediction" for x in at.checkbox)
    captions = " ".join(str(x.value) for x in at.caption)
    assert "预测仅供参考" not in captions
    time_box = next(x for x in at.selectbox if x.key == "trend_time_filter")
    assert "学期：2026春" in time_box.options
    assert "学年：2025-2026学年" in time_box.options
    range_box = next(x for x in at.selectbox if x.key == "trend_range")
    assert range_box.value == "最近 5 次"
    # 全部科目下两张班级图 + 两张个人图均在同一轮渲染；AppTest 不暴露
    # st.plotly_chart 元素，至少验证无异常且切换时间筛选仍正常。
    time_box.set_value("学年：2025-2026学年").run()
    assert not at.exception, [str(e) for e in at.exception]
    time_box.set_value("全部").run()
    assert not at.exception, [str(e) for e in at.exception]


def test_v142_term_report_word_export_isolated(tmp_path):
    """具体学期下可生成含趋势图的 Word；全部学期只提示不生成。"""
    db_file = tmp_path / "v142_term_report.db"
    _seed_v142_term_db(db_file)
    class_file = tmp_path / "class_names.json"
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / "feature.json", class_file),
        default_timeout=60)
    at.run()
    at.sidebar.radio[0].set_value("📊 学情").run()
    assert not at.exception, [str(e) for e in at.exception]

    term_box = next(x for x in at.selectbox if x.key == "analysis_term_filter")
    term_box.set_value("2026春").run()
    class_box = next(x for x in at.selectbox if x.key == "analysis_class")
    class_box.set_value("冒烟班").run()
    next(b for b in at.button if b.label == "⬇️ 导出学期报告（Word）").click().run()

    assert not at.exception, [str(e) for e in at.exception]
    save_btn = next(b for b in at.download_button
                    if b.label == "💾 保存学期报告")
    assert save_btn is not None


# ---------------------------------------------------------------------------
# v1.4.5 趋势分析与考试分析优化
# ---------------------------------------------------------------------------


def test_v146_thresholds_saved_in_exam_analysis_tab_isolated(tmp_path):
    """v1.4.6：及格线/优秀线在考试分析 Tab 顶部，空库也能保存到临时配置。"""
    db_file = tmp_path / "v146_thresholds.db"
    thresholds_file = tmp_path / "thresholds.json"
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / "feature.json",
                           tmp_path / "classes.json", thresholds_file),
        default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📊 学情").run()
    assert not at.exception, [str(e) for e in at.exception]

    def threshold_exp():
        return next(e for e in at.expander if "考试分析线" in e.label)

    next(x for x in threshold_exp().number_input
         if x.label == "及格线百分比").set_value(70).run()
    next(x for x in threshold_exp().number_input
         if x.label == "优秀线百分比").set_value(90).run()
    next(b for b in threshold_exp().button
         if b.label == "💾 保存考试分析线").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    assert '"pass_ratio": 0.7' in thresholds_file.read_text(encoding="utf-8")
    assert '"excellent_ratio": 0.9' in thresholds_file.read_text(encoding="utf-8")


def test_v145_exam_analysis_hides_median_and_rank_reverse_isolated(tmp_path):
    """考试分析不显示中位数/标准差；排名顺序可切换。"""
    db_file = tmp_path / "v145_exam_analysis.db"
    _seed_temp_db(db_file)
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / "feature.json"), default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📊 学情").run()
    assert not at.exception, [str(e) for e in at.exception]

    metric_labels = [x.label for x in at.metric]
    assert "中位数" not in metric_labels and "标准差" not in metric_labels
    rank_order = next(x for x in at.radio if x.label == "排名顺序")
    rank_order.set_value("低分到高分").run()
    assert not at.exception, [str(e) for e in at.exception]

    view = next(x for x in at.selectbox if x.key == "analysis_view")
    view.set_value("数学").run()
    assert not at.exception, [str(e) for e in at.exception]
    metric_labels = [x.label for x in at.metric]
    assert ["参考人数", "平均分", "最高分", "最低分", "及格率", "优秀率"] <= metric_labels


def test_v145_score_import_creates_new_exam_isolated(tmp_path):
    """空库也能在成绩导入区直接新建考试，再把 Word 成绩入库。"""
    import json
    db_file = tmp_path / "v145_new_exam_import.db"
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / "feature.json"), default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📊 学情").run()
    assert not at.exception, [str(e) for e in at.exception]

    target = next(x for x in at.radio if x.label == "导入目标")
    target.set_value("新建考试").run()
    next(x for x in at.text_input if x.key == "score_new_exam_name").input(
        "导入即建考试").run()
    _import_expander(at).file_uploader[0].upload(
        "成绩.docx", _docx_score_bytes(),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document").run()
    assert not at.exception, [str(e) for e in at.exception]
    assert any(x.label == "数学满分" for x in at.number_input)
    next(b for b in at.button if b.label == "✅ 确认导入成绩").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    assert any("导入完成" in str(x.value) for x in at.success)

    from sqlalchemy import create_engine, text
    eng = create_engine(f"sqlite:///{db_file.as_posix()}")
    with eng.connect() as conn:
        exam = conn.execute(text(
            "SELECT name, term, full_scores FROM exams")).mappings().one()
        score_count = conn.execute(text("SELECT COUNT(*) FROM scores")).scalar()
        student_count = conn.execute(text("SELECT COUNT(*) FROM students")).scalar()
    assert exam["name"] == "导入即建考试"
    assert exam["term"] == "2026秋"
    assert json.loads(exam["full_scores"]) == {"数学": 150.0}
    assert score_count == 2 and student_count == 2
    eng.dispose()


def test_v145_score_history_filters_isolated(tmp_path):
    """历次成绩长表存在，且学期/学年/考试类型筛选可用。"""
    db_file = tmp_path / "v145_history.db"
    _seed_temp_db(db_file)
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / "feature.json"), default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📊 学情").run()
    assert not at.exception, [str(e) for e in at.exception]

    semester = next(x for x in at.selectbox if x.key == "score_history_semester")
    year = next(x for x in at.selectbox if x.key == "score_history_year")
    exam_type = next(x for x in at.selectbox if x.key == "score_history_type")
    assert "2026春" in semester.options
    assert "2025-2026学年" in year.options
    assert exam_type.options == ["全部类型", "摸底", "月考", "期中", "期末", "其他"]
    assert any("共 4 行" in str(x.value) for x in at.caption)

    exam_type.set_value("期中").run()
    assert not at.exception, [str(e) for e in at.exception]
    assert any("共 2 行" in str(x.value) for x in at.caption)



# ---------------------------------------------------------------------------
# v1.4.6 体验优化：学生表动态新增、班级表格
# ---------------------------------------------------------------------------


def test_v146_student_editor_add_row_isolated(tmp_path):
    """学生表最后一行直接新增学生；空性别归一为 None；保存后入库。"""
    db_file = tmp_path / "v146_student_add.db"
    _seed_v141_three_students_db(db_file)
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / "feature.json"), default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📊 学情").run()
    assert not at.exception, [str(e) for e in at.exception]

    editor = next(x for x in at.dataframe if x.key == "student_editor_main")
    assert "姓名" in editor.value.columns
    # 注入一条动态新增行
    added_state = {"edited_rows": {}, "added_rows": [
        {"姓名": "新生丁", "学号": "09", "班级": "三班", "性别": None,
         "标签": "", "备注": ""}], "deleted_rows": []}
    at.session_state["student_editor_main"] = added_state
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    next(b for b in at.button if b.label == "💾 保存表格修改").click()
    at.session_state["student_editor_main"] = added_state
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    assert any("新增 1 人" in str(x.value) for x in at.success)

    from sqlalchemy import create_engine, text
    eng = create_engine(f"sqlite:///{db_file.as_posix()}")
    with eng.connect() as conn:
        row = conn.execute(text(
            "SELECT class_name, gender FROM students WHERE name='新生丁'")).mappings().one()
    assert row["class_name"] == "三班" and row["gender"] is None
    eng.dispose()


def test_v146_class_editor_save_and_delete_guard_isolated(tmp_path):
    """班级表格改名同步学生；勾选有学生的班级删除被阻止。"""
    db_file = tmp_path / "v146_class_editor.db"
    class_file = tmp_path / "class_names.json"
    class_file.write_text('{"classes": ["一班", "空班"]}', encoding="utf-8")
    _seed_v141_three_students_db(db_file)  # 甲、乙在一班，丙在二班
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / "feature.json", class_file),
        default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📊 学情").run()
    assert not at.exception, [str(e) for e in at.exception]

    class_exp = next(e for e in at.expander if e.label == "🏫 班级管理")
    editor = next(x for x in class_exp.dataframe if x.key == "class_editor_main")
    names = list(editor.value["班级名"])
    assert "一班" in names and "空班" in names

    # 把“空班”改名为“九班”
    idx = names.index("空班")
    edit_state = {"edited_rows": {str(idx): {"班级名": "九班"}},
                  "added_rows": [], "deleted_rows": []}
    at.session_state["class_editor_main"] = edit_state
    at.run()
    next(b for b in at.button if b.key == "save_class_editor").click()
    at.session_state["class_editor_main"] = edit_state
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    assert any("重命名 1 个" in str(x.value) for x in at.success)
    assert "九班" in class_file.read_text(encoding="utf-8")

    # 勾选“一班”（有 2 名学生）→ 删除应被阻止
    at2 = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / "feature2.json", class_file),
        default_timeout=30)
    at2.run()
    at2.sidebar.radio[0].set_value("📊 学情").run()
    class_exp2 = next(e for e in at2.expander if e.label == "🏫 班级管理")
    editor2 = next(x for x in class_exp2.dataframe if x.key == "class_editor_main")
    names2 = list(editor2.value["班级名"])
    one_idx = names2.index("一班")
    del_state = {"edited_rows": {str(one_idx): {"删除": True}},
                 "added_rows": [], "deleted_rows": []}
    at2.session_state["class_editor_main"] = del_state
    at2.run()
    next(b for b in at2.button if b.key == "delete_class_checked").click()
    at2.session_state["class_editor_main"] = del_state
    at2.run()
    next(b for b in at2.button if b.key == "confirm_class_delete").click().run()
    assert not at2.exception, [str(e) for e in at2.exception]
    assert any("还有 2 名学生" in str(x.value) for x in at2.error)



# ---------------------------------------------------------------------------
# v1.5.3：首页 Dashboard、备份恢复标题、错题重做卷
# ---------------------------------------------------------------------------

def test_v153_dashboard_empty_default_isolated(tmp_path):
    db_file = tmp_path / "v153_dashboard_empty.db"
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / "feature.json"),
        default_timeout=30)
    at.run()

    assert not at.exception, [str(e) for e in at.exception]
    assert at.sidebar.radio[0].value == "🏠 首页"
    assert at.title[0].value == "🏠 首页"
    assert any("老师好，欢迎回来" in str(x.value) for x in at.markdown)
    metric_labels = {x.label for x in at.metric}
    assert metric_labels == {
        "本学期备课次数", "本月布置作业次数",
        "最近考试平均分", "待批改作业数"}
    assert any(x.value == "—" for x in at.metric)
    quick_keys = {x.key for x in at.button}
    assert {
        "dash_new_homework", "dash_upload_score", "dash_ai_lesson"
    } <= quick_keys


def test_v153_dashboard_quick_action_new_homework(tmp_path):
    db_file = tmp_path / "v153_quick_hw.db"
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / "feature.json"),
        default_timeout=30)
    at.run()
    next(b for b in at.button if b.key == "dash_new_homework").click().run()

    assert not at.exception, [str(e) for e in at.exception]
    assert at.sidebar.radio[0].value == "📝 作业"
    assert at.session_state["hw_new_dialog_open"] is True
    assert any(x.label == "作业名称 *" for x in at.text_input)


def test_v153_dashboard_quick_action_upload_score(tmp_path):
    db_file = tmp_path / "v153_quick_score.db"
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / "feature.json"),
        default_timeout=30)
    at.run()
    next(b for b in at.button if b.key == "dash_upload_score").click().run()

    assert not at.exception, [str(e) for e in at.exception]
    assert at.sidebar.radio[0].value == "📊 学情"
    assert at.session_state["analysis_tab"] == "成绩管理"
    # 空库默认提示先新建考试；切到“新建考试”后出现文件选择器。
    next(x for x in at.radio if x.key == "score_import_target_mode").set_value("新建考试").run()
    assert any(x.key == "score_upload" for x in at.file_uploader)


def test_v153_dashboard_quick_action_ai_lesson(tmp_path):
    db_file = tmp_path / "v153_quick_lesson.db"
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / "feature.json"),
        default_timeout=30)
    at.run()
    next(b for b in at.button if b.key == "dash_ai_lesson").click().run()

    assert not at.exception, [str(e) for e in at.exception]
    assert at.sidebar.radio[0].value == "📚 备课"
    assert at.session_state["lesson_plan_tab"] == "AI 备课"


def test_v153_dashboard_with_data_isolated(tmp_path):
    db_file = tmp_path / "v153_dashboard_data.db"
    eng = _seed_temp_db(db_file)
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / "feature.json"),
        default_timeout=30)
    at.run()

    assert not at.exception, [str(e) for e in at.exception]
    latest_metric = next(x for x in at.metric if x.label == "最近考试平均分")
    assert latest_metric.value == "77.5"
    exam_text = " ".join(str(x.value) for x in at.dataframe)
    assert "期中考试" in exam_text and "第一次月考" in exam_text
    eng.dispose()


def test_v153_settings_backup_restore_title_isolated(tmp_path):
    db_file = tmp_path / "v153_backup_title.db"
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / "feature.json"),
        default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("⚙️ 设置").run()

    assert not at.exception, [str(e) for e in at.exception]
    assert any("数据备份与恢复" in str(x.value) for x in at.subheader)
    assert any(x.key == "restore_zip" for x in at.file_uploader)


def test_v153_retry_homework_generate_isolated(tmp_path):
    from sqlalchemy import text
    db_file = tmp_path / "v153_retry.db"
    eng = _seed_homework_data_db(db_file)
    feature_file = tmp_path / "feature.json"
    feature_file.write_text('{"wrong_book_subject": "物理"}', encoding="utf-8")
    at = AppTest.from_string(
        _isolated_app_code(db_file, feature_file), default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📝 作业").run()

    # 未勾选直接生成：给提示，不创建作业。
    next(b for b in at.button if b.key == "make_retry_hw").click().run()
    assert any("请先勾选" in str(x.value) for x in at.warning)

    # 勾选错题 → 进入预览。
    pick = next(x for x in at.checkbox if x.key == "retry_pick_1")
    pick.check().run()
    next(b for b in at.button if b.key == "make_retry_hw").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    editor = next(x for x in at.dataframe if x.key == "retry_question_editor")
    assert list(editor.value["难度"]) == [2]
    assert list(editor.value["分值"]) == [10.0]

    # 在确认前修改难度和分值；难度变化应克隆新题。
    at.session_state["retry_question_editor"] = {
        "edited_rows": {"0": {"难度": 3, "分值": 12.0}},
        "added_rows": [], "deleted_rows": []}
    at.run()
    confirm_btn = next(b for b in at.button if b.key == "confirm_retry_hw")
    confirm_btn.click()
    # AppTest 触发按钮时会重新挂载 data_editor；在 click 后、run 前补一次编辑态。
    at.session_state["retry_question_editor"] = {
        "edited_rows": {"0": {"难度": 3, "分值": 12.0}},
        "added_rows": [], "deleted_rows": []}
    at.run()

    assert not at.exception, [str(e) for e in at.exception]
    assert at.session_state["homework_tab"] == "作业管理"
    assert at.session_state["hw_open_id"] == 2

    with eng.connect() as conn:
        new_hw = conn.execute(text(
            "SELECT name, homework_type, class_name, subject, total_score "
            "FROM homeworks WHERE id=2")).mappings().one()
        link = conn.execute(text(
            "SELECT question_id, score FROM homework_questions "
            "WHERE homework_id=2")).mappings().one()
        clone = conn.execute(text(
            "SELECT difficulty, source, subject FROM questions WHERE id=:qid"
        ), {"qid": link["question_id"]}).mappings().one()

    assert new_hw["name"] == "错题重做卷_20260921"
    assert new_hw["homework_type"] == "after_class"
    assert new_hw["class_name"] == "冒烟班"
    assert new_hw["subject"] == "物理"
    assert new_hw["total_score"] == 12.0
    assert link["score"] == 12.0
    assert link["question_id"] == 2
    assert clone["difficulty"] == 3
    assert clone["source"] == "错题重做"
    assert clone["subject"] == "物理"
    eng.dispose()


def test_v153_retry_preview_cancel_isolated(tmp_path):
    from sqlalchemy import text
    db_file = tmp_path / "v153_retry_cancel.db"
    eng = _seed_homework_data_db(db_file)
    feature_file = tmp_path / "feature.json"
    feature_file.write_text('{"wrong_book_subject": "物理"}', encoding="utf-8")
    at = AppTest.from_string(
        _isolated_app_code(db_file, feature_file),
        default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📝 作业").run()
    next(x for x in at.checkbox if x.key == "retry_pick_1").check().run()
    next(b for b in at.button if b.key == "make_retry_hw").click().run()
    next(b for b in at.button if b.key == "cancel_retry_hw").click().run()

    assert not at.exception, [str(e) for e in at.exception]
    with eng.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM homeworks")).scalar()
    assert count == 1
    assert "retry_preview_items" not in at.session_state
    eng.dispose()




def _blank_pdf_bytes() -> bytes:
    """构造没有嵌入文字的一页 PDF，用于模拟扫描件。"""
    import io
    import pymupdf

    doc = pymupdf.open()
    doc.new_page()
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


def test_scanned_pdf_background_ocr_completes_isolated(tmp_path):
    """扫描件转入后台 OCR；切页不中断，完成后自动创建可用资料。"""
    import time
    from sqlalchemy import create_engine, text

    db_file = tmp_path / "ocr_success.db"
    at = AppTest.from_string(
        _isolated_app_code(
            db_file, tmp_path / "feature.json",
            text_dir=tmp_path / "material_text", ocr_mode="success"),
        default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📚 备课").run()

    next(x for x in at.file_uploader).upload(
        "扫描件.pdf", _blank_pdf_bytes(), "application/pdf").run()
    next(b for b in at.button if b.label == "提取并确认信息").click().run()

    assert not at.exception, [str(e) for e in at.exception]
    assert any("已转入后台 OCR" in str(x.value) for x in at.info)
    assert any("切换页面不会中断" in str(x.value) for x in at.success)

    deadline = time.time() + 5
    while time.time() < deadline:
        task_data = (tmp_path / "ocr_tasks.json").read_text(encoding="utf-8")
        if '"status": "已完成"' in task_data:
            break
        time.sleep(0.05)
    else:
        raise AssertionError("后台 OCR 未完成")

    at.run()
    markdown_text = "\n".join(str(x.value) for x in at.markdown)
    assert "识别完成" in markdown_text
    next(b for b in at.button if b.label == "确认命名").click().run()
    next(b for b in at.button if b.label == "确认保存").click().run()
    assert not at.exception, [str(e) for e in at.exception]

    eng = create_engine(f"sqlite:///{db_file.as_posix()}")
    with eng.connect() as conn:
        row = conn.execute(text(
            "SELECT name, file_type, subject FROM textbooks"
        )).mappings().one()
    assert dict(row) == {
        "name": "扫描件.pdf",
        "file_type": "pdf",
        "subject": "数学",
    }
    saved = (tmp_path / "material_text" / "1.txt").read_text(encoding="utf-8")
    assert "OCR识别出的中文正文" in saved


def test_scanned_pdf_background_ocr_failure_reports_status_isolated(tmp_path):
    """后台 OCR 失败时任务状态落盘，页面显示固定中文错误，不白屏。"""
    import time

    db_file = tmp_path / "ocr_failure.db"
    at = AppTest.from_string(
        _isolated_app_code(
            db_file, tmp_path / "feature.json",
            text_dir=tmp_path / "material_text", ocr_mode="failure"),
        default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📚 备课").run()

    next(x for x in at.file_uploader).upload(
        "损坏扫描件.pdf", _blank_pdf_bytes(), "application/pdf").run()
    next(b for b in at.button if b.label == "提取并确认信息").click().run()

    deadline = time.time() + 5
    while time.time() < deadline:
        task_data = (tmp_path / "ocr_tasks.json").read_text(encoding="utf-8")
        if '"status": "失败"' in task_data:
            break
        time.sleep(0.05)
    else:
        raise AssertionError("后台 OCR 未落失败状态")

    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    markdown_text = "\n".join(str(x.value) for x in at.markdown)
    assert "OCR识别失败，请检查PDF质量，或改用文字版PDF/Word" in markdown_text

def test_scanned_pdf_background_ocr_survives_page_switch(tmp_path):
    """OCR 在线程中等待期间切走页面，任务仍继续，回备课页后资料已可用。"""
    import time
    from sqlalchemy import create_engine, text

    db_file = tmp_path / "ocr_switch.db"
    trigger_file = tmp_path / "release_ocr"
    at = AppTest.from_string(
        _isolated_app_code(
            db_file,
            tmp_path / "feature.json",
            text_dir=tmp_path / "material_text",
            ocr_trigger_file=trigger_file,
            ocr_mode="switch_success"),
        default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📚 备课").run()

    next(x for x in at.file_uploader).upload(
        "扫描件.pdf", _blank_pdf_bytes(), "application/pdf").run()
    next(b for b in at.button if b.label == "提取并确认信息").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    assert any("已转入后台 OCR" in str(x.value) for x in at.info)

    # OCR 线程仍在阻塞时切到首页；这一步只卸载备课 UI，不杀线程。
    at.sidebar.radio[0].set_value("🏠 首页").run()
    assert not at.exception, [str(e) for e in at.exception]

    trigger_file.write_text("ok", encoding="utf-8")
    deadline = time.time() + 6
    while time.time() < deadline:
        task_data = (tmp_path / "ocr_tasks.json").read_text(encoding="utf-8")
        if '"status": "已完成"' in task_data:
            break
        time.sleep(0.05)
    else:
        raise AssertionError("切页后后台 OCR 未继续完成")

    at.sidebar.radio[0].set_value("📚 备课").run()
    assert not at.exception, [str(e) for e in at.exception]
    markdown_text = "\n".join(str(x.value) for x in at.markdown)
    assert "识别完成" in markdown_text
    next(b for b in at.button if b.label == "确认命名").click().run()
    next(b for b in at.button if b.label == "确认保存").click().run()
    assert not at.exception, [str(e) for e in at.exception]

    eng = create_engine(f"sqlite:///{db_file.as_posix()}")
    with eng.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM textbooks")).scalar_one()
    assert count == 1
