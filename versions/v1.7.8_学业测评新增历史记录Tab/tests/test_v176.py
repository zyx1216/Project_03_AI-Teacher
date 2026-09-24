# -*- coding: utf-8 -*-
"""v1.7.6 学业测评全面优化测试。"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from models.models import Base, Homework, HomeworkAnswer, HomeworkScore
from modules import homework as homework_mod
from utils import db
from utils import excel_handler as eh
from utils import homework_score_service as hscore
from utils import homework_service as hw_svc
from utils import question_service as qs
from utils import smart_compose_service as scs
from utils import stats as stats_mod
from utils import student_service as student_svc


# ---------------------------------------------------------------------------
# 补列迁移
# ---------------------------------------------------------------------------

def test_homework_pending_columns_contains_status_columns():
    columns = db._PENDING_COLUMNS["homeworks"]
    assert ("status", "VARCHAR(20) DEFAULT 'pending'") in columns
    assert ("completed_at", "DATETIME") in columns
    assert ("last_opened_at", "DATETIME") in columns


def test_legacy_homework_add_columns_and_repeat(tmp_path, monkeypatch):
    db_file = tmp_path / "legacy_homework.db"
    engine = create_engine(f"sqlite:///{db_file.as_posix()}")
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE homeworks ("
            "id INTEGER PRIMARY KEY, name TEXT, homework_type TEXT, "
            "class_name TEXT, total_score FLOAT, duration INTEGER, "
            "remark TEXT, is_template BOOLEAN, subject TEXT, grade TEXT, "
            "created_at TEXT)"
        )
        conn.exec_driver_sql(
            "INSERT INTO homeworks (id, name, homework_type, subject) "
            "VALUES (1, '旧作业', 'after_class', '数学')"
        )
    monkeypatch.setattr(db, "engine", engine)

    db._add_missing_columns()
    columns = {col["name"] for col in inspect(engine).get_columns("homeworks")}
    assert {"status", "completed_at", "last_opened_at"} <= columns
    with engine.connect() as conn:
        status = conn.execute(text("SELECT status FROM homeworks WHERE id=1")).scalar()
    assert status == "pending"

    db._add_missing_columns()
    engine.dispose()


# ---------------------------------------------------------------------------
# 作业服务
# ---------------------------------------------------------------------------

def _make_homework(session, name, grade=None, hw_type="after_class",
                   status="pending", created=None, opened=None):
    hw = hw_svc.create_homework(
        session, name, homework_type=hw_type, grade=grade, status=status)
    if created is not None:
        hw.created_at = created
    if opened is not None:
        hw.last_opened_at = opened
    session.flush()
    return hw


def test_list_homeworks_filters_and_sorting(session):
    t0 = datetime(2026, 9, 1, 8, 0)
    daily = _make_homework(
        session, "一年级日常作业", grade="一年级", created=t0,
        opened=t0 + timedelta(hours=3))
    _make_homework(
        session, "二年级日常作业", grade="二年级",
        created=t0 + timedelta(hours=1), opened=t0)
    _make_homework(
        session, "数学试卷", grade="一年级", hw_type="exam",
        created=t0 + timedelta(hours=2))
    completed = _make_homework(
        session, "已完成作业", grade="一年级", status="completed",
        created=t0 + timedelta(hours=4))
    session.commit()

    no_exam = hw_svc.list_homeworks(session, exclude_types=["exam"])
    assert {item.id for item in no_exam} == {daily.id, completed.id - 2, completed.id}
    assert all(item.homework_type != "exam" for item in no_exam)

    grade_rows = hw_svc.list_homeworks(session, grade="一年级", exclude_types=["exam"])
    assert {item.id for item in grade_rows} == {daily.id, completed.id}

    pending_rows = hw_svc.list_homeworks(session, status="pending", exclude_types=["exam"])
    assert [item.id for item in pending_rows] == [completed.id - 2, daily.id]

    asc_rows = hw_svc.list_homeworks(
        session, exclude_types=["exam"], sort_order="created_asc")
    assert [item.id for item in asc_rows] == [daily.id, completed.id - 2, completed.id]
    opened_rows = hw_svc.list_homeworks(
        session, exclude_types=["exam"], sort_order="opened_desc")
    assert opened_rows[0].id == daily.id


def test_complete_reopen_touch(session):
    hw = hw_svc.create_homework(session, "待完成")
    completed = hw_svc.mark_homework_completed(session, hw.id)
    assert completed.status == "completed"
    assert completed.completed_at is not None

    reopened = hw_svc.reopen_homework(session, hw.id)
    assert reopened.status == "pending"
    assert reopened.completed_at is None

    assert hw.last_opened_at is None
    hw_svc.touch_homework(session, hw.id)
    assert hw.last_opened_at is not None


def test_duplicate_homework_copies_questions_only(session):
    hw = hw_svc.create_homework(session, "原作业")
    data = qs.validate_question({
        "content": "原题", "question_type": "choice", "difficulty": 1,
        "answer": "A", "knowledge_points": "知识点"})
    question = qs.create_question(
        session, data, source="manual", status="approved", subject="数学")
    hw_svc.add_questions(session, hw.id, [question.id])
    student, _ = student_svc.get_or_create_student(session, "学生", "一班")
    hscore.save_total_score(session, hw.id, student.id, 90)
    hscore.save_answers(session, hw.id, [{
        "student_id": student.id, "question_id": question.id, "order_no": 1,
        "is_correct": True, "earned_score": 10}])
    session.flush()

    clone = hw_svc.duplicate_homework(session, hw.id)
    session.flush()
    assert clone.name == "原作业（副本）"
    assert len(hw_svc.homework_questions(session, clone.id)) == 1
    assert session.query(HomeworkScore).filter(
        HomeworkScore.homework_id == clone.id).count() == 0
    assert session.query(HomeworkAnswer).filter(
        HomeworkAnswer.homework_id == clone.id).count() == 0


def test_export_homeworks_zip(session):
    hw1 = hw_svc.create_homework(session, "作业一")
    hw2 = hw_svc.create_homework(session, "作业二")
    data = hw_svc.export_homeworks_zip(session, [hw1.id, hw2.id])
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
    assert len(names) == 2
    assert all(name.endswith(".docx") for name in names)


# ---------------------------------------------------------------------------
# 智能组卷槽位
# ---------------------------------------------------------------------------

def test_normalize_new_and_legacy_compose_slots(session):
    hw = hw_svc.create_homework(session, "槽位作业")
    new_spec = {"slots": [{
        "question_type": "choice", "difficulty": 1, "count": 2}]}
    slots = hw_svc.normalize_compose_slots(new_spec)
    assert slots == [
        {"question_type": "choice", "difficulty": 1},
        {"question_type": "choice", "difficulty": 1}]

    legacy_spec = {
        "counts": {"choice": 10},
        "difficulty_ratio": {1: 30, 2: 50, 3: 20}}
    legacy_slots = hw_svc.normalize_compose_slots(legacy_spec)
    counts = {1: 0, 2: 0, 3: 0}
    for slot in legacy_slots:
        counts[slot["difficulty"]] += 1
    assert counts == {1: 3, 2: 5, 3: 2}

    invalid_specs = [
        {"slots": [{"question_type": "bad", "difficulty": 1, "count": 1}]},
        {"slots": [{"question_type": "choice", "difficulty": 4, "count": 1}]},
        {"slots": [{"question_type": "choice", "difficulty": 1, "count": 0}]},
        {"slots": []},
    ]
    for spec in invalid_specs:
        with pytest.raises(ValueError):
            hw_svc.normalize_compose_slots(spec)


def test_slots_from_type_matrix():
    rows = [{"type": "选择题", "easy": 2, "medium": 1, "hard": 0}]
    slots = hw_svc.slots_from_type_matrix(rows)
    assert len(slots) == 3
    assert [slot["difficulty"] for slot in slots] == [1, 1, 2]

    with pytest.raises(ValueError):
        hw_svc.slots_from_type_matrix(
            [{"type": "不存在题型", "easy": 1, "medium": 0, "hard": 0}])
    with pytest.raises(ValueError):
        hw_svc.slots_from_type_matrix(
            [{"type": "选择题", "easy": -1, "medium": 0, "hard": 0}])
    with pytest.raises(ValueError):
        hw_svc.slots_from_type_matrix([])


# ---------------------------------------------------------------------------
# 智能组卷 JSON
# ---------------------------------------------------------------------------

def test_smart_compose_json_files(tmp_path, monkeypatch):
    templates_path = tmp_path / "smart_compose_templates.json"
    history_path = tmp_path / "smart_compose_history.json"
    monkeypatch.setattr(scs, "TEMPLATES_PATH", templates_path)
    monkeypatch.setattr(scs, "HISTORY_PATH", history_path)

    assert scs.load_templates() == []
    assert templates_path.exists()
    rows = [{"type": "选择题", "easy": 1, "medium": 2, "hard": 1}]
    scs.save_template("中文方案", "数学", "一年级", 100.0, 60, rows)
    raw = templates_path.read_text(encoding="utf-8")
    assert "中文方案" in raw and "\\u" not in raw

    history_path.write_text("损坏JSON", encoding="utf-8")
    assert scs.load_history() == []
    assert history_path.read_text(encoding="utf-8") == "损坏JSON"


# ---------------------------------------------------------------------------
# 成绩录入
# ---------------------------------------------------------------------------

class _NamedFile:
    def __init__(self, name, stream):
        self.name = name
        self._stream = stream

    def __getattr__(self, item):
        return getattr(self._stream, item)


def test_load_csv_and_clear_score_as_unsubmitted(tmp_path):
    csv_file = _NamedFile(
        "成绩.csv", io.StringIO("姓名,分数\n张三,90\n李四,80\n"))
    df = eh.load_dataframe(csv_file)
    assert list(df.columns) == ["姓名", "分数"]
    assert len(df) == 2

    db_file = tmp_path / "score.db"
    engine = create_engine(f"sqlite:///{db_file.as_posix()}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    hw = hw_svc.create_homework(session, "作业")
    student, _ = student_svc.get_or_create_student(session, "张三", "一班")
    hscore.save_total_score(session, hw.id, student.id, 90)
    hscore.save_total_score(session, hw.id, student.id, None)
    data = hscore.analyze_homework(session, hw.id)
    assert data["overall"]["submitted"] == 0
    assert data["overall"]["mean"] is None
    session.close()
    engine.dispose()


# ---------------------------------------------------------------------------
# 作业分析
# ---------------------------------------------------------------------------

def test_pass_excellent_rates_and_custom_segments():
    rates = stats_mod.pass_and_excellent(
        [50, 60, 90, 100], 100, pass_ratio=0.6, excellent_ratio=0.85)
    assert rates["pass_count"] == 3
    assert rates["excellent_count"] == 2

    bands = stats_mod.score_bands(
        [40, 70], 100, edges=[0, 60, 101], labels=["不及格", "及格以上"])
    assert [band["count"] for band in bands] == [1, 1]


# ---------------------------------------------------------------------------
# 错题本
# ---------------------------------------------------------------------------

def _wrong_question(session, grade, student_name, knowledge_point="知识点"):
    hw = hw_svc.create_homework(session, f"{student_name}作业", grade=grade)
    data = qs.validate_question({
        "content": f"{knowledge_point}题干", "question_type": "solution",
        "difficulty": 2, "answer": "答案",
        "knowledge_points": knowledge_point})
    question = qs.create_question(
        session, data, source="manual", status="approved", subject="数学")
    hw_svc.add_questions(session, hw.id, [question.id])
    student, _ = student_svc.get_or_create_student(
        session, student_name, "一班")
    hscore.save_answers(session, hw.id, [{
        "student_id": student.id, "question_id": question.id, "order_no": 1,
        "is_correct": False, "error_type": "概念错误"}])
    session.flush()
    return hw, question, student


def test_wrong_grade_filter_remove_and_knowledge_groups(session):
    _wrong_question(session, "一年级", "小学学生", "小学知识点")
    _wrong_question(session, "七年级", "初中学生", "初中知识点")

    grade_rows = hscore.list_wrong_answers(session, grade="一年级")
    assert len(grade_rows) == 1
    assert grade_rows[0]["student_name"] == "小学学生"

    answer_id = grade_rows[0]["answer_id"]
    question_id = grade_rows[0]["question_id"]
    hscore.remove_answer(session, answer_id)
    session.flush()
    assert session.query(HomeworkAnswer).count() == 1
    all_questions = session.query(qs.Question).all()
    assert any(item.id == question_id for item in all_questions)

    rows = hscore.list_wrong_answers(session)
    groups = homework_mod._wrong_knowledge_groups(rows)
    assert groups[0]["知识点"] == "初中知识点"
    assert groups[0]["错题数"] == 1


# ---------------------------------------------------------------------------
# AppTest
# ---------------------------------------------------------------------------

def _open_homework(at):
    at.run()
    at.sidebar.radio[0].set_value("📝 学业测评").run()


def _app_code(db_file, tmp_path, fake_ai=False):
    from tests import test_app_smoke as smoke

    code = smoke._isolated_app_code(db_file, tmp_path / "feature.json")
    if not fake_ai:
        return code

    run_line = f'runpy.run_path(r"{smoke.APP_FILE}", run_name="__main__")'
    patch = f'''
import utils.llm_client as _llm_client
import json
def _fake_chat_content(system_prompt, user_text, temperature=0.8):
    return json.dumps([
        {{
            "content": "智能矩阵题",
            "question_type": "choice",
            "difficulty": 2,
            "knowledge_points": ["矩阵知识点"],
            "answer": "A"
        }}
    ], ensure_ascii=False)
_llm_client.chat_content = _fake_chat_content
{run_line}
'''
    assert code.count(run_line) == 1
    return code.replace(run_line, patch.strip(), 1)


def test_homework_management_filters_and_status_apptest(tmp_path):
    db_file = tmp_path / "manage.db"
    engine = create_engine(f"sqlite:///{db_file.as_posix()}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    hw_svc.create_homework(session, "一年级作业", grade="一年级")
    hw_svc.create_homework(session, "数学试卷", grade="一年级", homework_type="exam")
    session.commit()
    session.close()

    from streamlit.testing.v1 import AppTest
    at = AppTest.from_string(_app_code(db_file, tmp_path), default_timeout=30)
    _open_homework(at)
    assert not at.exception

    page_text = " ".join(str(x.value) for x in at.markdown)
    assert any("一年级作业" in str(x.value) for x in at.markdown)

    next(x for x in at.selectbox if x.key == "homework_filter_type").set_value("after_class").run()
    next(x for x in at.selectbox if x.key == "homework_filter_grade").set_value("一年级").run()
    next(x for x in at.selectbox if x.key == "homework_filter_sort").set_value("最新创建").run()
    assert not at.session_state.get("hw_new_dialog_open")
    assert not at.exception

    next(b for b in at.button if b.key == "finish_1").click().run()
    assert not at.exception
    # v1.7.8 后作业管理只保留进行中；"重新打开"操作从历史页走。
    # 点完成后该行从作业管理消失，迁移到历史页。
    assert not any(b.key == "reopen_1" for b in at.button)
    at.session_state["homework_tab"] = "📜 历史记录"
    at.run()
    assert not at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert metrics.get("历史记录总数") == "1"
    engine.dispose()


def test_smart_compose_matrix_template_history_and_confirm_apptest(tmp_path):
    from streamlit.testing.v1 import AppTest

    db_file = tmp_path / "smart_matrix.db"
    at = AppTest.from_string(
        _app_code(db_file, tmp_path, fake_ai=True), default_timeout=30)
    _open_homework(at)
    assert not at.exception

    assert not any(item.key.startswith("smart_compose_p") for item in at.slider)
    number_keys = {item.key for item in at.number_input}
    assert {
        "smart_easy_0", "smart_medium_0", "smart_hard_0",
        "smart_compose_total", "smart_compose_duration"} <= number_keys

    next(x for x in at.text_input if x.key == "smart_template_name").input("我的矩阵方案").run()
    next(b for b in at.button if b.key == "smart_save_template").click().run()
    assert not at.exception

    next(b for b in at.button if b.key == "smart_compose_run").click().run()
    assert not at.exception
    next(b for b in at.button if b.key == "confirm_smart_paper").click().run()
    assert not at.exception

    engine = create_engine(f"sqlite:///{db_file.as_posix()}")
    session = sessionmaker(bind=engine)()
    paper = session.query(Homework).one()
    assert paper.homework_type == "exam"
    assert paper.is_template is False
    assert paper.grade == "一年级"
    assert paper.total_score == 100
    assert paper.duration == 60
    session.close()
    engine.dispose()

    templates_file = db_file.parent / "smart_compose_templates.json"
    history_file = db_file.parent / "smart_compose_history.json"
    assert "我的矩阵方案" in templates_file.read_text(encoding="utf-8")
    history = json.loads(history_file.read_text(encoding="utf-8"))
    assert history and history[0]["subject"] == "数学"


def test_scores_analysis_and_wrong_book_apptest(tmp_path):
    from tests import test_app_smoke as smoke
    from streamlit.testing.v1 import AppTest

    db_file = tmp_path / "full_features.db"
    smoke._seed_homework_data_db(db_file)
    at = AppTest.from_string(_app_code(db_file, tmp_path), default_timeout=30)
    _open_homework(at)
    assert not at.exception

    # 成绩 CSV 导入。
    at.file_uploader[0].upload(
        "成绩.csv", "姓名,分数\n冒烟学生,95\n".encode("utf-8"),
        "text/csv").run()
    next(b for b in at.button if b.key == "import_hw_score").click().run()
    assert not at.exception
    assert any(str(x.value) in {"95", "95.0"} for x in at.metric)

    # 作业分析：种子数据是物理作业。
    next(x for x in at.selectbox if x.key == "homework_analysis_subject").set_value("物理").run()
    assert any(x.key == "hw_pass_line_1" for x in at.number_input)
    assert any(x.key == "hw_excellent_line_1" for x in at.number_input)
    assert any(x.key == "rank_excel_1" for x in at.download_button)

    # 错题本：切学科、知识点聚合、单题移除。
    next(x for x in at.selectbox if x.key == "wrong_book_subject").set_value("物理").run()
    assert not at.exception
    next(x for x in at.radio if x.key == "wb_view_mode").set_value("按知识点聚合").run()
    assert not at.exception
    next(x for x in at.radio if x.key == "wb_view_mode").set_value("按题目列表").run()
    next(b for b in at.button if b.key == "wb_remove_1").click().run()
    assert not at.exception
