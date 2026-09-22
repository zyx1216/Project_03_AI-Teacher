# -*- coding: utf-8 -*-
"""v1.5.5 课程安排表与首页日历预览测试。"""

from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from streamlit.testing.v1 import AppTest

from models.models import Base, Exam, Homework, LessonPlan, Student
from utils import schedule_service as svc

PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_FILE = PROJECT_ROOT / "app.py"


@pytest.fixture()
def schedule_path(tmp_path, monkeypatch):
    path = tmp_path / "class_schedule.json"
    monkeypatch.setattr(svc, "CLASS_SCHEDULE_PATH", path)
    return path


def test_load_creates_file_when_missing(schedule_path):
    assert svc.load_schedule() == {"entries": []}
    assert schedule_path.exists()


def test_save_chinese_without_escape(schedule_path):
    svc.save_entries([{
        "class_name": "八年级1班", "weekday": 1, "period": 1,
        "subject": "数学"}])
    text = schedule_path.read_text(encoding="utf-8")
    assert "八年级1班" in text and "数学" in text
    assert "\\u" not in text


def test_corrupt_json_falls_back_without_overwrite(schedule_path):
    schedule_path.write_text("{损坏", encoding="utf-8")
    assert svc.load_schedule() == {"entries": []}
    assert schedule_path.read_text(encoding="utf-8") == "{损坏"


def test_upsert_overwrite_list_and_delete(schedule_path):
    svc.upsert_entry("一班", 1, 1, "数学")
    svc.upsert_entry("一班", 1, 1, "物理")
    assert svc.list_entries("一班") == [{
        "class_name": "一班", "weekday": 1, "period": 1,
        "subject": "物理"}]

    svc.delete_entry("一班", 1, 1)
    assert svc.list_entries("一班") == []


def test_invalid_class_subject_weekday_period(schedule_path):
    with pytest.raises(ValueError, match="班级名称不能为空"):
        svc.upsert_entry("", 1, 1, "数学")
    with pytest.raises(ValueError, match="学科不受支持"):
        svc.upsert_entry("一班", 1, 1, "体育")
    with pytest.raises(ValueError, match="星期"):
        svc.upsert_entry("一班", 8, 1, "数学")
    with pytest.raises(ValueError, match="节次"):
        svc.upsert_entry("一班", 1, 9, "数学")


def test_sync_week_grid_replaces_only_selected_class(schedule_path):
    svc.upsert_entry("一班", 1, 1, "数学")
    svc.upsert_entry("一班", 1, 2, "英语")
    svc.upsert_entry("二班", 2, 3, "物理")

    rows = svc.week_grid("一班")
    rows[0]["周一"] = ""
    rows[1]["周一"] = "数学"
    result = svc.sync_week_grid("一班", rows)

    assert result == {"saved": 1, "deleted": 1}
    assert svc.list_entries("一班") == [{
        "class_name": "一班", "weekday": 1, "period": 2,
        "subject": "数学"}]
    assert svc.list_entries("二班") == [{
        "class_name": "二班", "weekday": 2, "period": 3,
        "subject": "物理"}]


def test_schedule_template_columns_and_example():
    df = svc.schedule_template_dataframe()
    assert list(df.columns) == ["星期", "节次", "科目", "班级"]
    assert df.iloc[0].to_dict() == {
        "星期": "周一", "节次": 1, "科目": "数学",
        "班级": "八年级1班"}


def test_parse_weekday_period_variants():
    df = pd.DataFrame([
        {"星期": "周一", "节次": "第1节", "科目": "数学", "班级": "一班"},
        {"星期": "星期一", "节次": 1, "科目": "语文", "班级": "一班"},
        {"星期": 1, "节次": "2", "科目": "英语", "班级": "一班"},
    ])
    rows = svc.parse_schedule_dataframe(df, ["一班"])
    assert [(r["weekday"], r["period"], r["subject"]) for r in rows] == [
        (1, 1, "语文"), (1, 2, "英语")]
    # 前两行时间格重复；导入时以后一行覆盖前一行。
    result = svc.import_schedule_entries(df, ["一班"])
    assert result == {"imported": 2}
    assert svc.list_entries("一班")[0]["subject"] == "语文"


def test_parse_unknown_class_is_rejected():
    df = svc.schedule_template_dataframe()
    with pytest.raises(ValueError, match="班级不存在"):
        svc.parse_schedule_dataframe(df, ["二班"])


def test_import_schedule_entries_merges_existing(schedule_path):
    svc.upsert_entry("一班", 1, 1, "数学")
    df = pd.DataFrame([
        {"星期": "周一", "节次": 2, "科目": "物理", "班级": "一班"}])
    assert svc.import_schedule_entries(df, ["一班"]) == {"imported": 1}
    assert [(e["period"], e["subject"]) for e in svc.list_entries("一班")] == [
        (1, "数学"), (2, "物理")]


def _seed_week_db(db_file: Path):
    """临时库：一个班级和本周内的考试、作业、教案。"""
    eng = create_engine(f"sqlite:///{db_file.as_posix()}")
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    session.add(Student(name="甲", class_name="一班"))
    session.add_all([
        Exam(name="周测", exam_date=date(2026, 9, 21)),
        Homework(name="本周作业", is_template=False, class_name="一班",
                 subject="数学", created_at=datetime(2026, 9, 21, 9, 0)),
        LessonPlan(title="本周教案", created_at=datetime(2026, 9, 22, 9, 0)),
    ])
    session.commit()
    session.close()
    return eng


def _isolated_code(db_file: Path) -> str:
    return f'''
import sys, runpy
sys.path.insert(0, r"{PROJECT_ROOT}")
from pathlib import Path as _Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import utils.db as db
import utils.feature_subjects as fs
import utils.class_service as cs
import utils.analysis_settings as ast
import utils.schedule_service as ss
import modules.analysis, modules.calendar, modules.dashboard, modules.homework, modules.lesson_plan, modules.settings
fs.FEATURE_SUBJECTS_PATH = _Path(r"{db_file.parent / 'feature.json'}")
cs.CLASS_NAMES_PATH = _Path(r"{db_file.parent / 'class.json'}")
ast.THRESHOLDS_PATH = _Path(r"{db_file.parent / 'th.json'}")
ss.CLASS_SCHEDULE_PATH = _Path(r"{db_file.parent / 'schedule.json'}")
eng = create_engine(r"sqlite:///{db_file.as_posix()}")
SL = sessionmaker(bind=eng)
db.engine = eng
db.SessionLocal = SL
for m in (modules.analysis, modules.calendar, modules.dashboard, modules.homework, modules.lesson_plan, modules.settings):
    m.SessionLocal = SL
runpy.run_path(r"{APP_FILE}", run_name="__main__")
'''


def test_dashboard_week_preview_and_calendar_jump(tmp_path):
    db_file = tmp_path / "week.db"
    eng = _seed_week_db(db_file)
    at = AppTest.from_string(_isolated_code(db_file), default_timeout=30)
    at.run()

    assert not at.exception, [str(e) for e in at.exception]
    assert any(x.value == "本周日历预览" for x in at.subheader)
    preview = next(x for x in at.dataframe if set(x.value.columns) >= {
        "状态", "考试", "作业", "教案"})
    text = str(preview.value.to_dict("records"))
    assert "周测" in text and "本周作业" in text and "本周教案" in text
    assert any(x.key == "home_schedule_class" for x in at.selectbox)

    next(b for b in at.button if b.key == "dash_open_calendar").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    assert at.sidebar.radio[0].value == "📅 教学日历"
    eng.dispose()


def test_calendar_schedule_editor_save_isolated(tmp_path):
    db_file = tmp_path / "schedule.db"
    eng = _seed_week_db(db_file)
    schedule_json = db_file.parent / "schedule.json"
    at = AppTest.from_string(_isolated_code(db_file), default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📅 教学日历").run()

    assert not at.exception, [str(e) for e in at.exception]
    assert any(x.value == "课程安排表" for x in at.subheader)
    assert any(x.key == "class_schedule_editor" for x in at.dataframe)
    assert any(x.key == "schedule_excel_file" for x in at.file_uploader)
    assert any(x.key == "download_schedule_template" for x in at.download_button)

    edit_state = {
        "edited_rows": {"0": {"周一": "数学"}},
        "added_rows": [], "deleted_rows": []}
    at.session_state["class_schedule_editor"] = edit_state
    at.run()
    next(b for b in at.button if b.key == "save_class_schedule").click()
    at.session_state["class_schedule_editor"] = edit_state
    at.run()

    assert not at.exception, [str(e) for e in at.exception]
    assert any("已保存 1 节课" in str(x.value) for x in at.success)
    saved = schedule_json.read_text(encoding="utf-8")
    assert '"class_name": "一班"' in saved
    assert '"weekday": 1' in saved
    assert '"period": 1' in saved
    assert '"subject": "数学"' in saved
    eng.dispose()
