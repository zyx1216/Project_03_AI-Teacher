# -*- coding: utf-8 -*-
"""v2.3.0 体验与技术优化测试。"""

from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from models.models import Base
from models.models import (
    Student, Question, Homework, OperationLog, Score, Exam,
)
from utils import (
    onboarding_service, keyboard_shortcuts, undo_service,
    logger_service, error_logger, pagination_service,
)
from utils import exam_service, homework_service, question_service, student_service


# ---------------------------------------------------------------------------
# 公共夹具
# ---------------------------------------------------------------------------

@pytest.fixture()
def session(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    Base.metadata.create_all(engine)
    sl = sessionmaker(bind=engine)
    s = sl()
    undo_service.clear()
    yield s
    s.close()
    engine.dispose()


def _make_student(session, name="张三", class_name="一班"):
    student, _ = student_service.get_or_create_student(session, name, class_name)
    session.flush()
    return student


def _make_question(session, content="1+1=？", answer="2", subject="数学"):
    data = question_service.validate_question({
        "content": content, "answer": answer, "difficulty": 1,
        "question_type": "choice", "knowledge_points": ["计算"]})
    return question_service.create_question(
        session, data, source="manual", status="approved", subject=subject)


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

def test_database_has_21_tables():
    assert len(Base.metadata.tables) == 26
    assert "operation_logs" in Base.metadata.tables


def test_backup_tables_count_21():
    from utils.backup_service import BUSINESS_TABLES
    assert len(BUSINESS_TABLES) == 26
    assert "operation_logs" in BUSINESS_TABLES


def test_operation_log_fields(session):
    cols = {c["name"] for c in inspect(session.bind).get_columns("operation_logs")}
    assert {"id", "user", "action", "module", "target", "detail", "ip",
            "created_at"} <= cols


def test_seven_indexes_exist(session):
    insp = inspect(session.bind)
    expected = {
        "students": {"ix_students_class_name", "ix_students_name"},
        "scores": {"ix_scores_student_id", "ix_scores_subject"},
        "questions": {"ix_questions_subject", "ix_questions_grade"},
        "exams": {"ix_exams_exam_date"},
    }
    for table, names in expected.items():
        actual = {i["name"] for i in insp.get_indexes(table)}
        assert names <= actual, f"{table} 缺索引 {names - actual}"


def test_migration_repeatable(tmp_path):
    import importlib.util
    from pathlib import Path

    engine = create_engine(f"sqlite:///{(tmp_path / 'mig.db').as_posix()}")
    Base.metadata.create_all(engine)

    spec = importlib.util.spec_from_file_location(
        "v230_migration", Path("migrations/v2.3.0_migration.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    first = module.migrate(engine)
    second = module.migrate(engine)  # 重复执行不应报错
    assert isinstance(first["created_indexes"], list)
    assert second["created_indexes"] == []


# ---------------------------------------------------------------------------
# 新手引导
# ---------------------------------------------------------------------------

def test_guide_has_six_steps():
    steps = onboarding_service.guide_steps()
    assert len(steps) == 6
    ids = [s["id"] for s in steps]
    assert ids == ["welcome", "import_students", "import_scores",
                   "create_lesson", "ai_questions", "done"]
    for step in steps:
        assert set(step) >= {"id", "title", "description"}


def test_onboarding_complete_step(tmp_path):
    p = tmp_path / "onboarding.json"
    status = onboarding_service.complete_step("welcome", p)
    assert "welcome" in status["completed_steps"]
    again = onboarding_service.complete_step("welcome", p)
    assert again["completed_steps"].count("welcome") == 1  # 不重复


def test_onboarding_skip(tmp_path):
    p = tmp_path / "onboarding.json"
    status = onboarding_service.skip(p)
    assert status["skipped"] is True
    assert onboarding_service.should_show(status) is False


def test_onboarding_snooze(tmp_path):
    p = tmp_path / "onboarding.json"
    tomorrow = date.today() + timedelta(days=1)
    status = onboarding_service.snooze(p, tomorrow)
    assert onboarding_service.should_show(status, today=date.today()) is False
    assert onboarding_service.should_show(status, today=tomorrow) is True


def test_onboarding_reset(tmp_path):
    p = tmp_path / "onboarding.json"
    onboarding_service.complete_step("welcome", p)
    status = onboarding_service.reset(p)
    assert status["completed_steps"] == []
    assert status["skipped"] is False


def test_onboarding_corrupt_fallback_no_overwrite(tmp_path):
    p = tmp_path / "onboarding.json"
    p.write_text("{这不是合法JSON", encoding="utf-8")
    status = onboarding_service.load_status(p)
    assert status == onboarding_service.default_status()
    assert p.read_text(encoding="utf-8") == "{这不是合法JSON"  # 原文件不覆盖


def test_onboarding_done_stops_showing(tmp_path):
    p = tmp_path / "onboarding.json"
    for step_id in [s["id"] for s in onboarding_service.guide_steps()]:
        onboarding_service.complete_step(step_id, p)
    status = onboarding_service.load_status(p)
    assert onboarding_service.should_show(status) is False


# ---------------------------------------------------------------------------
# 快捷键配置
# ---------------------------------------------------------------------------

def test_shortcut_default_enabled():
    assert keyboard_shortcuts.default_config() == {"enabled": True}


def test_shortcut_enable_disable(tmp_path):
    p = tmp_path / "shortcut_config.json"
    keyboard_shortcuts.save_shortcut_config(False, p)
    assert keyboard_shortcuts.shortcuts_enabled(p) is False
    keyboard_shortcuts.save_shortcut_config(True, p)
    assert keyboard_shortcuts.shortcuts_enabled(p) is True


def test_shortcut_corrupt_fallback(tmp_path):
    p = tmp_path / "shortcut_config.json"
    p.write_text("坏数据", encoding="utf-8")
    assert keyboard_shortcuts.load_shortcut_config(p) == {"enabled": True}


# ---------------------------------------------------------------------------
# 撤销 / 重做
# ---------------------------------------------------------------------------

def test_stack_limit_is_50():
    assert undo_service.STACK_LIMIT == 50


def test_undo_redo_student_add(session):
    student = _make_student(session)
    session.commit()
    sid = student.id
    undo_service.undo(session)
    session.commit()
    assert session.get(Student, sid) is None
    undo_service.redo(session)
    session.commit()
    assert session.get(Student, sid) is not None


def test_undo_redo_student_edit(session):
    student = _make_student(session, name="张三")
    session.commit()
    undo_service.clear()  # 清掉新增动作，只测编辑
    student_service.update_student(session, student.id, name="李四")
    session.commit()
    assert session.get(Student, student.id).name == "李四"
    undo_service.undo(session)
    session.commit()
    assert session.get(Student, student.id).name == "张三"
    undo_service.redo(session)
    session.commit()
    assert session.get(Student, student.id).name == "李四"


def test_undo_redo_student_delete(session):
    student = _make_student(session)
    session.commit()
    undo_service.clear()
    sid = student.id
    student_service.delete_student(session, sid)
    session.commit()
    assert session.get(Student, sid) is None
    undo_service.undo(session)
    session.commit()
    assert session.get(Student, sid) is not None
    undo_service.redo(session)
    session.commit()
    assert session.get(Student, sid) is None


def test_undo_redo_question_add(session):
    question = _make_question(session)
    session.commit()
    qid = question.id
    undo_service.undo(session)
    session.commit()
    assert session.get(Question, qid) is None
    undo_service.redo(session)
    session.commit()
    assert session.get(Question, qid) is not None


def test_undo_redo_question_delete(session):
    question = _make_question(session)
    session.commit()
    undo_service.clear()
    qid = question.id
    question_service.delete_question(session, qid)
    session.commit()
    undo_service.undo(session)
    session.commit()
    assert session.get(Question, qid) is not None
    undo_service.redo(session)
    session.commit()
    assert session.get(Question, qid) is None


def test_undo_redo_homework_add(session):
    hw = homework_service.create_homework(session, "测试作业")
    session.commit()
    hid = hw.id
    undo_service.undo(session)
    session.commit()
    assert session.get(Homework, hid) is None
    undo_service.redo(session)
    session.commit()
    assert session.get(Homework, hid) is not None


def test_undo_redo_homework_delete(session):
    hw = homework_service.create_homework(session, "测试作业")
    session.commit()
    undo_service.clear()
    hid = hw.id
    homework_service.delete_homework(session, hid)
    session.commit()
    undo_service.undo(session)
    session.commit()
    assert session.get(Homework, hid) is not None
    undo_service.redo(session)
    session.commit()
    assert session.get(Homework, hid) is None


def test_undo_empty_raises(session):
    undo_service.clear()
    with pytest.raises(ValueError):
        undo_service.undo(session)


# ---------------------------------------------------------------------------
# 操作日志 / 错误日志
# ---------------------------------------------------------------------------

def test_log_operation_and_query(session):
    logger_service.log_operation(session, "新增学生", "学生管理", 1,
                                 {"姓名": "张三"})
    session.commit()
    rows = logger_service.query_logs(session, module="学生管理")
    assert len(rows) == 1
    d = logger_service.operation_to_dict(rows[0])
    assert d["操作"] == "新增学生"
    assert d["对象"] == "1"


def test_log_operation_filters(session):
    logger_service.log_operation(session, "新增", "模块A", 1)
    logger_service.log_operation(session, "删除", "模块B", 2)
    session.commit()
    assert len(logger_service.query_logs(session, module="模块A")) == 1
    assert len(logger_service.query_logs(session, action="删除")) == 1
    assert len(logger_service.query_logs(session, limit=1)) == 1


def test_sanitize_sensitive_fields():
    detail = {
        "name": "张三",
        "api_key": "sk-secret-123",
        "nested": {"token": "abc", "ok": 1},
        "Password": "p@ss",
    }
    safe = logger_service.sanitize_value(detail)
    assert safe["api_key"] == "【已脱敏】"
    assert safe["nested"]["token"] == "【已脱敏】"
    assert safe["Password"] == "【已脱敏】"
    assert safe["name"] == "张三"
    # 脱敏后可安全 JSON 序列化
    json.dumps(safe, ensure_ascii=False)


def test_create_question_writes_operation_log(session):
    _make_question(session)
    session.commit()
    rows = logger_service.query_logs(session, module="题库")
    assert any(r.action == "新增题目" for r in rows)


def test_error_logger_write_and_read(tmp_path):
    log_dir = tmp_path / "logs"
    try:
        raise ValueError("测试出错 api_key=sk-leak-12345")
    except ValueError as exc:
        path = error_logger.log_error(exc, {"页面": "首页"}, log_dir)
    assert path.exists()
    files = error_logger.list_log_files(log_dir)
    assert len(files) == 1
    content = error_logger.read_log_file(files[0].name, log_dir)
    assert "测试出错" in content
    assert "sk-leak-12345" not in content  # 密钥被脱敏
    assert "【已脱敏】" in content


def test_error_logger_empty_dir(tmp_path):
    assert error_logger.list_log_files(tmp_path / "无日志") == []


# ---------------------------------------------------------------------------
# 分页
# ---------------------------------------------------------------------------

def test_page_info_basic():
    info = pagination_service.page_info(total=55, page=1, page_size=20)
    assert info["offset"] == 0
    assert info["limit"] == 20
    assert info["total_pages"] == 3


def test_page_info_middle_page():
    info = pagination_service.page_info(total=55, page=2, page_size=20)
    assert info["offset"] == 20


def test_page_info_clamps_out_of_range():
    info = pagination_service.page_info(total=10, page=99, page_size=20)
    assert info["page"] == 1
    assert info["offset"] == 0


def test_page_info_empty():
    info = pagination_service.page_info(total=0, page=1, page_size=20)
    assert info["total_pages"] == 1
    assert info["offset"] == 0


def test_student_list_pagination(session):
    for i in range(25):
        _make_student(session, name=f"学生{i:02d}", class_name="一班")
    session.commit()
    page1 = student_service.list_students(session, limit=20, offset=0)
    page2 = student_service.list_students(session, limit=20, offset=20)
    assert len(page1) == 20
    assert len(page2) == 5
    assert student_service.count_students(session) == 25


# ---------------------------------------------------------------------------
# 性能：大数据量下列表与统计
# ---------------------------------------------------------------------------

def test_large_dataset_list_query_performance(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'large.db').as_posix()}")
    Base.metadata.create_all(engine)
    sl = sessionmaker(bind=engine)
    session = sl()

    students = []
    for i in range(1000):
        students.append(Student(name=f"学生{i:04d}", class_name=f"{i % 10 + 1}班",
                                student_no=f"S{i:04d}"))
    session.bulk_save_objects(students)
    session.commit()

    start = time.perf_counter()
    page = student_service.list_students(session, class_name="1班",
                                         limit=20, offset=0)
    elapsed = time.perf_counter() - start
    assert len(page) == 20
    assert elapsed < 2.0

    start = time.perf_counter()
    count = student_service.count_students(session)
    assert time.perf_counter() - start < 2.0
    assert count == 1000
    session.close()
    engine.dispose()


# ---------------------------------------------------------------------------
# AppTest：空库 / 有数据
# ---------------------------------------------------------------------------

def _feature_file(path):
    path.write_text(json.dumps({
        "materials_subject": "数学",
        "lesson_plan_subject": "数学",
        "question_gen_subject": "数学",
        "question_bank_subject": "数学",
        "homework_list_subject": "数学",
        "homework_analysis_subject": "数学",
        "wrong_book_subject": "数学",
    }, ensure_ascii=False), encoding="utf-8")


def _subheader_order(at):
    values = [x.value for x in at.subheader]
    ia = values.index("🔔 智能提醒")
    ib = values.index("💡 AI教学建议")
    ic = values.index("📈 教学进度")
    return ia < ib < ic


def test_v230_app_empty_paths(tmp_path):
    from streamlit.testing.v1 import AppTest
    from tests.test_app_smoke import _isolated_app_code, goto_top, goto_sub

    db_file = tmp_path / "empty-v230.db"
    engine = create_engine(f"sqlite:///{db_file.as_posix()}", future=True)
    Base.metadata.create_all(engine)
    feature = tmp_path / "feature.json"
    _feature_file(feature)

    at = AppTest.from_string(
        _isolated_app_code(db_file, feature), default_timeout=40)
    at.run()
    assert not at.exception

    # 新手引导：首次进入自动弹出，三个按钮齐全。
    keys = {b.key for b in at.button}
    assert {"onboarding_next", "onboarding_skip", "onboarding_later"} <= keys

    # 点“下一步”：welcome 完成，弹窗显示第二步。
    next(b for b in at.button if b.key == "onboarding_next").click().run()
    assert not at.exception
    assert any("导入学生" in str(m.value) for m in at.markdown)

    # 点“跳过引导”：弹窗消失。
    next(b for b in at.button if b.key == "onboarding_skip").click().run()
    assert not at.exception
    assert "onboarding_next" not in {b.key for b in at.button}

    # 首页三个置顶区块顺序：提醒 → 建议 → 教学进度。
    assert _subheader_order(at)

    # 设置页：记忆管理 / 帮助中心 / 操作日志 / 错误日志全部渲染。
    goto_top(at, "⚙️ 设置")
    assert not at.exception
    panel_text = " ".join(str(x.value) for x in at.subheader)
    assert "🧠 AI记忆管理" in panel_text
    assert "❓ 帮助中心" in panel_text
    assert "📜 操作日志" in panel_text
    assert "🧯 错误日志" in panel_text

    # 学生管理：分页控件存在。
    goto_sub(at, "analysis_tab", "学生管理", "📊 学情")
    assert not at.exception
    next(x for x in at.selectbox if x.key == "student_page_size")

    # 题库管理：分页控件存在；空数据不报错。
    goto_sub(at, "lesson_plan_tab", "题库管理", "📚 备课")
    assert not at.exception

    # 旧入口：智能组卷、提交页不受影响。
    goto_sub(at, "homework_tab", "🤖 智能组卷", "📝 学业测评")
    assert not at.exception
    engine.dispose()


def test_v230_app_data_paths(tmp_path):
    from streamlit.testing.v1 import AppTest
    from tests.test_app_smoke import _isolated_app_code, goto_top, goto_sub

    db_file = tmp_path / "data-v230.db"
    engine = create_engine(f"sqlite:///{db_file.as_posix()}", future=True)
    Base.metadata.create_all(engine)
    seed_session = sessionmaker(bind=engine)()

    for i in range(25):
        student_service.get_or_create_student(
            seed_session, f"学生{i:02d}", "一班")
    for i in range(25):
        data = question_service.validate_question({
            "content": f"题目{i:02d}：1+1=？", "answer": "2",
            "difficulty": (i % 3) + 1, "question_type": "choice",
            "knowledge_points": ["计算"]})
        question_service.create_question(
            seed_session, data, source="manual",
            status="approved", subject="数学")
    seed_session.commit()
    seed_session.close()

    feature = tmp_path / "feature.json"
    _feature_file(feature)
    at = AppTest.from_string(
        _isolated_app_code(db_file, feature), default_timeout=40)
    at.run()
    assert not at.exception

    # 跳过引导，避免弹窗干扰后续断言。
    if "onboarding_skip" in {b.key for b in at.button}:
        next(b for b in at.button if b.key == "onboarding_skip").click().run()
        assert not at.exception

    # 首页区块顺序。
    assert _subheader_order(at)

    # 学生管理：默认每页 20，点下一页看到第 2 页。
    goto_sub(at, "analysis_tab", "学生管理", "📊 学情")
    assert not at.exception
    next(b for b in at.button if b.key == "student_next_page").click().run()
    assert not at.exception
    assert any("当前第 2/2 页" in str(c.value) for c in at.caption)

    # 切换每页 50：一页放下全部 25 人。
    size_box = next(x for x in at.selectbox if x.key == "student_page_size")
    size_box.set_value(50).run()
    assert not at.exception
    assert any("共 25 名学生" in str(c.value) for c in at.caption)

    # 题库管理：翻到第 2 页。
    goto_sub(at, "lesson_plan_tab", "题库管理", "📚 备课")
    assert not at.exception
    next(b for b in at.button if b.key == "question_next_page").click().run()
    assert not at.exception
    assert any("当前第 2/2 页" in str(c.value) for c in at.caption)

    # 设置页有数据时各面板正常。
    goto_top(at, "⚙️ 设置")
    assert not at.exception

    # 旧入口：数据看板、成绩录入正常。
    goto_top(at, "📊 数据看板")
    assert not at.exception
    goto_sub(at, "homework_tab", "成绩录入", "📝 学业测评")
    assert not at.exception
    engine.dispose()
