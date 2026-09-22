# -*- coding: utf-8 -*-
from pathlib import Path
from datetime import date, datetime

from streamlit.testing.v1 import AppTest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models.models import (
    Base, Homework, HomeworkAnswer, HomeworkQuestion, Question, Student)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_FILE = _PROJECT_ROOT / "app.py"


def _seed_kp_db(db_file: Path):
    """临时库：2 名学生 + 1 份作业 + 3 道题（含多标签/无标签）+ 逐题作答。"""
    import json
    eng = create_engine(f"sqlite:///{db_file.as_posix()}")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    s.add_all([
        Student(name="甲", class_name="一班"),
        Student(name="乙", class_name="一班"),
    ])
    s.flush()
    hw = Homework(name="第一次作业", is_template=False, class_name="一班",
                  subject="数学", created_at=datetime(2026, 9, 10, 9, 0))
    s.add(hw)
    s.flush()

    questions = [
        (1, ["方程", "计算"], 10),
        (2, ["方程"], 10),
        (3, [], 10),
    ]
    for qid, kps, full in questions:
        s.add(Question(
            id=qid, content=f"题{qid}", question_type="solution",
            difficulty=2, knowledge_points=json.dumps(kps, ensure_ascii=False),
            answer="ans"))
        s.add(HomeworkQuestion(
            homework_id=hw.id, question_id=qid, order=qid, score=full))
    s.flush()

    # 甲：题1=8，题2=5，题3=2；乙：题1=9，题2=9，题3=7
    answers = [
        (1, 8, True), (2, 5, True), (3, 2, False),
    ]
    for qid, earned, correct in answers:
        s.add(HomeworkAnswer(
            homework_id=hw.id, student_id=1, question_id=qid, order_no=qid,
            earned_score=earned, is_correct=correct))
    for qid, earned in [(1, 9), (2, 9), (3, 7)]:
        s.add(HomeworkAnswer(
            homework_id=hw.id, student_id=2, question_id=qid, order_no=qid,
            earned_score=earned, is_correct=True))
    s.commit()
    s.close()
    return eng


def _isolated_code(db_file: Path) -> str:
    return f'''
import sys, runpy
sys.path.insert(0, r"{_PROJECT_ROOT}")
from pathlib import Path as _Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import utils.db as db
import utils.feature_subjects as fs
import utils.class_service as cs
import utils.analysis_settings as ast
import modules.analysis, modules.calendar, modules.homework, modules.lesson_plan, modules.settings
fs.FEATURE_SUBJECTS_PATH = _Path(r"{db_file.parent / 'feature.json'}")
cs.CLASS_NAMES_PATH = _Path(r"{db_file.parent / 'class.json'}")
ast.THRESHOLDS_PATH = _Path(r"{db_file.parent / 'th.json'}")
eng = create_engine(r"sqlite:///{db_file.as_posix()}")
SL = sessionmaker(bind=eng)
db.engine = eng
db.SessionLocal = SL
for m in (modules.analysis, modules.calendar, modules.homework, modules.lesson_plan, modules.settings):
    m.SessionLocal = SL
runpy.run_path(r"{APP_FILE}", run_name="__main__")
'''


def test_knowledge_tab_renders_with_graded_homework(tmp_path):
    db_file = tmp_path / "kp.db"
    _seed_kp_db(db_file)
    at = AppTest.from_string(_isolated_code(db_file), default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📊 学情").run()
    assert not at.exception, [str(e) for e in at.exception]

    # AppTest 会执行所有 tab 的脚本内容，知识点 Tab 已渲染，直接断言
    subheaders = [str(x.value) for x in at.subheader]
    assert "知识点掌握分析" in subheaders
    md = " ".join(str(x.value) for x in at.markdown)
    assert "全班知识点统计" in md
    assert "学生知识点掌握" in md
    assert not at.exception, [str(e) for e in at.exception]


def test_knowledge_tab_empty_state_no_homework(tmp_path):
    db_file = tmp_path / "empty.db"
    eng = create_engine(f"sqlite:///{db_file.as_posix()}")
    Base.metadata.create_all(eng)
    eng.dispose()
    at = AppTest.from_string(_isolated_code(db_file), default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📊 学情").run()
    assert not at.exception
    assert any("还没有普通作业" in str(x.value) for x in at.info)


def test_calendar_page_renders(tmp_path):
    db_file = tmp_path / "cal.db"
    _seed_kp_db(db_file)
    at = AppTest.from_string(_isolated_code(db_file), default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📅 教学日历").run()
    assert not at.exception, [str(e) for e in at.exception]
    subheaders = [str(x.value) for x in at.subheader]
    assert "查看某天" in subheaders and "本周概览" in subheaders
