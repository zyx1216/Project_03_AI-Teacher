# -*- coding: utf-8 -*-
"""v1.2.4 全科 demo 数据测试：内存库构建 + Excel 产物校验，不碰真实库。"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models.models import Base, Exam, Score, Student
from scripts import make_demo_data as demo


def _memory_session():
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_demo_constants():
    assert len(demo.SUBJECTS) == 9
    assert set(demo.SUBJECTS) == set(demo.FULL_SCORES)
    assert demo.FULL_SCORES["数学"] == 150
    assert demo.FULL_SCORES["语文"] == 150
    assert demo.FULL_SCORES["英语"] == 150
    for s in ("物理", "化学", "生物", "政治", "历史", "地理"):
        assert demo.FULL_SCORES[s] == 100


def test_build_demo_data(session=None):
    session = _memory_session()
    stats = demo.build_demo_data(session)
    session.flush()

    assert stats["students"] == 30
    assert stats["exams"] == 3
    # 30 人 × 9 科 × 3 场 = 810，其中 3 个缺考
    assert stats["scores"] == 810 - 3
    assert stats["absent"] == 3

    assert session.query(Student).count() == 30
    exams = session.query(Exam).order_by(Exam.exam_date).all()
    assert [e.name for e in exams] == ["第一次月考", "期中考试", "第二次月考"]

    # 每场考试 9 科满分配置齐全
    import json
    for exam in exams:
        full = json.loads(exam.full_scores)
        assert set(full) == set(demo.SUBJECTS)
        assert full["数学"] == 150 and full["物理"] == 100

    # 9 科都有成绩，缺考点确实存成 NULL
    subjects_in_db = {r[0] for r in session.query(Score.subject).distinct()}
    assert subjects_in_db == set(demo.SUBJECTS)
    nulls = session.query(Score).filter(Score.score.is_(None)).count()
    assert nulls == 3

    # 分数不超满分、不低于 0
    bad = session.query(Score).filter(
        Score.score.isnot(None),
        ((Score.subject.in_(["语文", "数学", "英语"])) & (Score.score > 150))
        | ((Score.subject.notin_(["语文", "数学", "英语"])) & (Score.score > 100))
        | (Score.score < 0)).count()
    assert bad == 0


def test_write_demo_excel(tmp_path):
    out = demo.write_demo_excel(tmp_path)
    assert (out / "学生名单.xlsx").exists()
    for exam_name, _d, _drift in demo.EXAMS:
        path = out / f"成绩_{exam_name}.xlsx"
        assert path.exists()

    import pandas as pd
    students = pd.read_excel(out / "学生名单.xlsx")
    assert len(students) == 30
    df = pd.read_excel(out / "成绩_期中考试.xlsx")
    # 9 科列 + 姓名/班级
    for s in demo.SUBJECTS:
        assert s in df.columns
    # 缺考点在 Excel 里也是空
    absent = df[df["姓名"] == "学生05"]["数学"]
    assert absent.isna().all()
