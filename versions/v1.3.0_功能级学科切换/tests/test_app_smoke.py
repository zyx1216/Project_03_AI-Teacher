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
    assert at.sidebar.radio[0].options == ["📚 备课", "📝 作业", "📊 学情", "⚙️ 设置"]


def test_switch_all_main_pages(tmp_path):
    at = AppTest.from_string(
        _isolated_app_code(tmp_path / "pages.db", tmp_path / "feature.json"),
        default_timeout=30)
    at.run()
    for page in ["📚 备课", "📝 作业", "📊 学情", "⚙️ 设置"]:
        at.sidebar.radio[0].set_value(page).run()
        assert not at.exception, (page, [str(e) for e in at.exception])
        assert at.title


def test_analysis_page_has_seven_tabs(tmp_path):
    at = AppTest.from_string(
        _isolated_app_code(tmp_path / "analysis_tabs.db", tmp_path / "feature.json"),
        default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📊 学情").run()
    assert not at.exception, [str(e) for e in at.exception]
    assert [t.label for t in at.tabs] == [
        "学生管理", "成绩管理", "考试分析", "趋势分析",
        "学生画像", "教学反思", "期末评语"]


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
        "materials_subject", "lesson_plan_subject", "question_gen_subject",
        "question_bank_subject", "ppt_subject",
    } <= keys
    info_text = " ".join(str(x.value) for x in at.info)
    assert "数学" in info_text


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


def _isolated_app_code(db_file: Path, feature_file: Path | None = None) -> str:
    """生成在临时数据库和临时功能学科状态上跑 app.py 的脚本。"""
    feature_file = feature_file or db_file.parent / "feature_subjects.json"
    template = r"""
import sys, runpy
sys.path.insert(0, r"__ROOT__")
from pathlib import Path as _Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import utils.db as db
import utils.feature_subjects as feature_subjects
import modules.analysis, modules.homework, modules.lesson_plan, modules.settings
feature_subjects.FEATURE_SUBJECTS_PATH = _Path(r"__FEATURE__")
eng = create_engine(r"sqlite:///__DBFILE__")
SL = sessionmaker(bind=eng)
db.engine = eng
db.SessionLocal = SL
for m in (modules.analysis, modules.homework, modules.lesson_plan, modules.settings):
    m.SessionLocal = SL
runpy.run_path(r"__APPFILE__", run_name="__main__")
"""
    return (template.replace("__ROOT__", str(_PROJECT_ROOT))
            .replace("__DBFILE__", db_file.as_posix())
            .replace("__FEATURE__", feature_file.as_posix())
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
    assert any("数据管理" in str(x.value) for x in at.subheader)
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

    at = AppTest.from_string(_isolated_app_code(db_file, tmp_path / "web_feature_subjects.json"), default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📚 备课").run()
    assert not at.exception, [str(e) for e in at.exception]

    markdown_text = " ".join(str(x.value) for x in at.markdown)
    caption_text = " ".join(str(x.value) for x in at.caption)
    assert "冒烟网页资料" in markdown_text
    assert "网页链接" in markdown_text
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
    markdown_text = " ".join(str(x.value) for x in at.markdown)
    assert "物理资料甲" in markdown_text
    assert "数学资料甲" not in markdown_text


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
    """趋势默认最近5次、含最近10次；单科分数段图可切饼图，无异常。"""
    db_file = tmp_path / "trend_v125.db"
    _seed_temp_db(db_file)
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / "trend_v125_feature.json"),
        default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📊 学情").run()
    assert not at.exception, [str(e) for e in at.exception]

    scope = next(x for x in at.selectbox if x.label == "显示范围")
    assert scope.options == ["最近 3 次", "最近 5 次", "最近 10 次", "全部"]
    assert scope.value == "最近 5 次"
    scope.set_value("全部").run()
    assert not at.exception, [str(e) for e in at.exception]

    # 考试分析默认数学单科：分数段图类型 柱状→饼图
    band = next(r for r in at.radio if r.label == "分数段图类型")
    assert band.options == ["柱状图", "饼图"]
    band.set_value("饼图").run()
    assert not at.exception, [str(e) for e in at.exception]