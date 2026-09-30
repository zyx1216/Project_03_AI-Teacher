# -*- coding: utf-8 -*-
"""v2.4.1 试卷批改与分析快速入口优化测试。"""

from __future__ import annotations

import json

import pytest

from tests.test_app_smoke import _isolated_app_code, goto_sub


def _skip_onboarding(db_file):
    (db_file.parent / "onboarding.json").write_text(json.dumps({
        "completed_steps": [], "skipped": True,
        "snooze_until": "", "updated_at": ""}, ensure_ascii=False),
        encoding="utf-8")


def _feature_file(path):
    path.write_text(json.dumps({
        "materials_subject": "数学", "lesson_plan_subject": "数学",
        "question_gen_subject": "数学", "question_bank_subject": "数学",
        "homework_list_subject": "数学", "homework_analysis_subject": "数学",
        "wrong_book_subject": "数学"}, ensure_ascii=False), encoding="utf-8")


def _at(tmp_path, name):
    db_file = tmp_path / name
    _skip_onboarding(db_file)
    feat = tmp_path / (name + "_feature.json")
    _feature_file(feat)
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_string(_isolated_app_code(db_file, feat),
                             default_timeout=60)
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    return at, db_file


# ---------------------------------------------------------------------------
# 数据模型：homework_id 字段
# ---------------------------------------------------------------------------

def test_exam_homework_id_column_nullable():
    from models.models import Exam
    col = Exam.__table__.columns.get("homework_id")
    assert col is not None and col.nullable


def test_get_or_create_exam_for_homework_idempotent(tmp_path):
    """同一试卷两次调用返回同一考试、不产生重复。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from models.models import Base
    from utils import homework_service, exam_service

    eng = create_engine(f"sqlite:///{(tmp_path/'t.db').as_posix()}")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    hw = homework_service.create_homework(s, "组卷测试", homework_type="exam",
                                          subject="数学")
    s.commit()
    e1 = exam_service.get_or_create_exam_for_homework(s, hw)
    s.commit()
    e2 = exam_service.get_or_create_exam_for_homework(s, hw)
    s.commit()
    assert e1.id == e2.id
    assert e1.homework_id == hw.id
    assert s.query(exam_service.Exam).count() == 1
    eng.dispose()


# ---------------------------------------------------------------------------
# AppTest：改名与类型筛选
# ---------------------------------------------------------------------------

def test_hw_subs_renamed(tmp_path):
    at, _ = _at(tmp_path, "subs.db")
    at.session_state["app_top_page"] = "📝 学业测评"
    at.run()
    radio = next(x for x in at.sidebar.radio if x.key == "homework_tab")
    assert "✏️ 批改与分析" in radio.options
    assert "作业批改与分析" not in radio.options


def test_grading_page_type_filter_options(tmp_path):
    at, _ = _at(tmp_path, "tf.db")
    goto_sub(at, "homework_tab", "✏️ 批改与分析", "📝 学业测评")
    assert not at.exception, [str(e) for e in at.exception]
    picker = next(x for x in at.selectbox if x.key == "grading_type_filter")
    assert picker.options == ["全部", "📝 作业", "📄 试卷"]


def test_grading_page_empty_state(tmp_path):
    at, _ = _at(tmp_path, "empty.db")
    goto_sub(at, "homework_tab", "✏️ 批改与分析", "📝 学业测评")
    assert not at.exception, [str(e) for e in at.exception]
    assert any("可批改" in str(x.value) for x in at.info)


def test_quick_entry_buttons_present_with_homework(tmp_path):
    """有进行中作业时，作业行出现去批改/查看分析按钮。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from models.models import Base
    from utils import homework_service

    db_file = tmp_path / "qe.db"
    eng = create_engine(f"sqlite:///{db_file.as_posix()}")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    homework_service.create_homework(s, "日常", subject="数学")
    s.commit(); eng.dispose()

    at, _ = _at(tmp_path, "qe.db")
    at.session_state["app_top_page"] = "📝 学业测评"
    at.run()
    keys = {b.key for b in at.button}
    assert "quick_grade_1" in keys and "quick_an_1" in keys


def test_auto_open_id_consumed_and_selected(tmp_path):
    """从快速入口跳来：hw_open_id 被消费且选择框选中对应作业。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from models.models import Base
    from utils import homework_service

    db_file = tmp_path / "ao.db"
    eng = create_engine(f"sqlite:///{db_file.as_posix()}")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    homework_service.create_homework(s, "目标作业", subject="数学")
    s.commit(); eng.dispose()

    at, _ = _at(tmp_path, "ao.db")
    at.session_state["app_top_page"] = "📝 学业测评"
    at.session_state["homework_tab"] = "✏️ 批改与分析"
    at.session_state["hw_open_id"] = 1
    at.run()
    assert "hw_open_id" not in at.session_state
    picker = next(x for x in at.selectbox if x.key == "grading_pick_idx")
    assert picker.value == 0  # 候选第一份即 id=1


def test_exam_quick_entry_buttons_with_paper(tmp_path):
    """有已生成试卷时，试卷行出现去批改/查看分析按钮。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from models.models import Base
    from utils import homework_service

    db_file = tmp_path / "ep.db"
    eng = create_engine(f"sqlite:///{db_file.as_posix()}")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    homework_service.create_homework(s, "正式试卷", homework_type="exam",
                                     subject="数学")
    s.commit(); eng.dispose()

    at, _ = _at(tmp_path, "ep.db")
    goto_sub(at, "homework_tab", "🤖 智能组卷", "📝 学业测评")
    keys = {b.key for b in at.button}
    assert "grade_exam_1" in keys and "an_exam_1" in keys
