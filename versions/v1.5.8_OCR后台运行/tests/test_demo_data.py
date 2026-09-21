# -*- coding: utf-8 -*-
"""v1.4.2 后 demo 数据测试：3 班 90 人、10 场考试、9 科完整成绩，不碰真实库。"""

import json
from collections import Counter

import pandas as pd
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker

from models.models import Base, Exam, Score, Student
from scripts import make_demo_data as demo


def _memory_session():
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_demo_constants():
    assert demo.CLASSES == ["八年级1班", "八年级2班", "八年级3班"]
    assert demo.STUDENTS_PER_CLASS == 30
    assert len(demo.EXAMS) == 10
    assert len(demo.SUBJECTS) == 9
    assert set(demo.SUBJECTS) == set(demo.FULL_SCORES)
    assert demo.FULL_SCORES["数学"] == 150
    assert demo.FULL_SCORES["语文"] == 150
    assert demo.FULL_SCORES["英语"] == 150
    for s in ("物理", "化学", "生物", "政治", "历史", "地理"):
        assert demo.FULL_SCORES[s] == 100


def test_build_demo_data():
    session = _memory_session()
    stats = demo.build_demo_data(session)
    session.flush()

    assert stats == {
        "students": 90,
        "exams": 10,
        "scores": 8100,
        "absent": 0,
    }

    assert session.query(Student).count() == 90
    class_counts = dict(
        session.query(Student.class_name, func.count(Student.id))
        .group_by(Student.class_name)
        .all()
    )
    assert class_counts == {name: 30 for name in demo.CLASSES}

    exams = session.query(Exam).order_by(Exam.exam_date, Exam.id).all()
    assert [e.name for e in exams] == [item[0] for item in demo.EXAMS]
    assert [e.term for e in exams] == [item[2] for item in demo.EXAMS]

    for exam in exams:
        full = json.loads(exam.full_scores)
        assert set(full) == set(demo.SUBJECTS)
        assert full["数学"] == 150 and full["物理"] == 100
        assert session.query(Score).filter(Score.exam_id == exam.id).count() == 810
        subject_counts = dict(
            session.query(Score.subject, func.count(Score.id))
            .filter(Score.exam_id == exam.id)
            .group_by(Score.subject)
            .all()
        )
        assert subject_counts == {subject: 90 for subject in demo.SUBJECTS}

    subjects_in_db = {r[0] for r in session.query(Score.subject).distinct()}
    assert subjects_in_db == set(demo.SUBJECTS)
    assert session.query(Score).filter(Score.score.is_(None)).count() == 0

    bad = session.query(Score).filter(
        Score.score.isnot(None),
        ((Score.subject.in_(["语文", "数学", "英语"])) & (Score.score > 150))
        | ((Score.subject.notin_(["语文", "数学", "英语"])) & (Score.score > 100))
        | (Score.score < 0)).count()
    assert bad == 0


def test_write_demo_excel(tmp_path):
    out = demo.write_demo_excel(tmp_path)
    assert (out / "学生名单.xlsx").exists()
    score_files = sorted(out.glob("成绩_*.xlsx"))
    assert len(score_files) == 10

    students = pd.read_excel(out / "学生名单.xlsx")
    assert len(students) == 90
    assert Counter(students["班级"]) == Counter({class_name: 30 for class_name in demo.CLASSES})

    for idx, (_name, _date, _term, _drift) in enumerate(demo.EXAMS, start=1):
        path = out / f"成绩_{idx:02d}_{demo.EXAMS[idx - 1][2]}_{demo.EXAMS[idx - 1][0]}.xlsx"
        df = pd.read_excel(path)
        assert len(df) == 90
        assert list(df.columns) == ["姓名", "班级", *demo.SUBJECTS]
        assert df[demo.SUBJECTS].notna().all().all()
