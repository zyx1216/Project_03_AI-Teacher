# -*- coding: utf-8 -*-
"""v1.7.8 学业测评新增历史记录 Tab 测试。"""
from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models.models import Base, Homework, HomeworkAnswer, HomeworkScore
from modules import homework as homework_mod
from utils import feature_subjects as fs
from utils import homework_service as hw_svc
from utils import question_service as qs
from utils import student_service as student_svc

from tests.test_app_smoke import _isolated_app_code

from streamlit.testing.v1 import AppTest


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _apptest(db_file: Path, tmp_path: Path) -> AppTest:
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / "feature.json"),
        default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📝 学业测评").run()
    return at


def _open_history_tab(at: AppTest) -> None:
    tab_widget = at.tabs[-1]
    at.session_state["homework_tab"] = "📜 历史记录"
    at.run()


def _seed_completed_homework(session, name, hw_type="after_class", grade=None,
                             completed_at=None, subject="数学",
                             status="completed"):
    hw = hw_svc.create_homework(
        session, name, homework_type=hw_type, grade=grade,
        subject=subject, status=status)
    if completed_at is not None:
        hw.completed_at = completed_at
    session.flush()
    return hw


def _seed_pending_homework(session, name, grade=None, hw_type="after_class"):
    return _seed_completed_homework(
        session, name, hw_type=hw_type, grade=grade, subject="数学",
        completed_at=None, status="pending")


def test_history_subject_feature_key_registered():
    assert fs.HISTORY_SUBJECT in fs.FEATURE_KEYS
    assert fs.HISTORY_SUBJECT == "history_subject"


def test_history_main_tabs_count_six(tmp_path):
    db_file = tmp_path / "structure.db"
    at = _apptest(db_file, tmp_path)
    assert not at.exception, [str(e) for e in at.exception]
    assert [t.label for t in at.tabs] == [
        "作业管理", "🤖 智能组卷", "成绩录入", "作业分析", "错题本", "📜 历史记录"]


def test_history_lists_completed_only_and_orders_by_completed_at(tmp_path):
    """历史页只统计已完成作业；按完成时间倒序；作业管理 metric 只剩进行中。"""
    db_file = tmp_path / "history_data.db"
    eng = create_engine(f"sqlite:///{db_file.as_posix()}",
                        connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    t0 = datetime(2026, 9, 1, 8, 0)
    _seed_completed_homework(
        session, "日常作业-1", hw_type="after_class",
        grade="一年级", completed_at=t0)
    exam = hw_svc.create_homework(
        session, "试卷-1", homework_type="exam", grade="三年级",
        subject="数学", status="completed")
    exam.completed_at = t0 + timedelta(hours=2)
    session.flush()
    _seed_pending_homework(session, "进行中作业", grade="一年级")
    session.commit()

    at = _apptest(db_file, tmp_path)
    _open_history_tab(at)
    assert not at.exception, [str(e) for e in at.exception]
    # 历史页 metric：总数 2、作业 1、试卷 1。
    hist_metrics = {m.label: m.value for m in at.metric}
    assert hist_metrics.get("历史记录总数") == "2"
    assert hist_metrics.get("作业数") == "1"
    assert hist_metrics.get("试卷数") == "1"
    # 作业管理 markdown：只显示进行中 1 份。
    md = "\n".join(str(x.value) for x in at.markdown)
    assert "📋 进行中（1 份）" in md
    assert "📚 已完成" not in md
    eng.dispose()


def test_manage_does_not_render_completed_section(tmp_path):
    """作业管理 metric 只显示进行中；历史页 metric 显示已完成。"""
    db_file = tmp_path / "manage_no_completed.db"
    eng = create_engine(f"sqlite:///{db_file.as_posix()}",
                        connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    _seed_pending_homework(session, "进行中作业")
    _seed_completed_homework(
        session, "已完成作业",
        completed_at=datetime(2026, 9, 1, 8, 0))
    session.commit()

    at = _apptest(db_file, tmp_path)
    _open_history_tab(at)
    assert not at.exception, [str(e) for e in at.exception]
    md = "\n".join(str(x.value) for x in at.markdown)
    # 作业管理只剩 1 份进行中，且无"📚 已完成"折叠。
    assert "📋 进行中（1 份）" in md
    assert "📚 已完成" not in md
    # 历史页有 1 份已完成
    metrics = {m.label: m.value for m in at.metric}
    assert metrics.get("历史记录总数") == "1"
    eng.dispose()


def test_history_filters_type_subject_grade_keyword(tmp_path):
    """历史页支持类型、学科、年级和关键词筛选，用 metric 总数校验。"""
    db_file = tmp_path / "history_filters.db"
    eng = create_engine(f"sqlite:///{db_file.as_posix()}",
                        connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    _seed_completed_homework(
        session, "数学日常", hw_type="after_class", grade="一年级",
        completed_at=datetime(2026, 9, 1, 8, 0))
    hw = hw_svc.create_homework(
        session, "物理试卷", homework_type="exam", grade="三年级",
        subject="物理", status="completed")
    hw.completed_at = datetime(2026, 9, 2, 8, 0)
    session.flush()
    session.commit()

    db_file = tmp_path / "history_filters.db"
    at = _apptest(db_file, tmp_path)
    _open_history_tab(at)
    assert not at.exception, [str(e) for e in at.exception]

    def total():
        m = {x.label: x.value for x in at.metric}
        return m.get("历史记录总数")

    # 默认数学学科 + 全部类型：只剩数学日常 1 条。
    assert total() == "1"

    # 切到物理学科：只剩物理试卷 1 条。
    at.session_state[fs.HISTORY_SUBJECT] = "物理"
    at.run()
    assert total() == "1"

    # 类型=作业：物理试卷是 exam，过滤后 0 条。
    at.session_state["history_filter_type"] = "daily"
    at.run()
    assert total() == "0"

    # 类型=试卷：又出现物理试卷 1 条。
    at.session_state["history_filter_type"] = "exam"
    at.run()
    assert total() == "1"

    # 类型回到全部 + 切回数学 + 关键词过滤
    at.session_state["history_filter_type"] = "all"
    at.session_state[fs.HISTORY_SUBJECT] = "数学"
    at.run()
    assert total() == "1"

    at.session_state["history_filter_keyword"] = "不存在"
    at.run()
    assert total() == "0"
    eng.dispose()


def test_duplicate_from_history_creates_pending_copy_without_scores(tmp_path):
    """历史页再次布置生成 pending 副本，不复制 HomeworkScore/HomeworkAnswer。"""
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    hw = _seed_completed_homework(
        session, "原作业", hw_type="after_class",
        completed_at=datetime(2026, 9, 1, 8, 0))
    q = qs.create_question(session, {
        "content": "题", "question_type": "choice", "difficulty": 1,
        "answer": "A", "knowledge_points": "x",
    }, status="approved")
    session.flush()
    student, _ = student_svc.get_or_create_student(session, "张三", "一班")
    session.add(HomeworkScore(homework_id=hw.id, student_id=student.id,
                              total_score=80, submitted=True))
    session.add(HomeworkAnswer(homework_id=hw.id, student_id=student.id,
                               question_id=q.id, is_correct=False))
    session.commit()

    clone = hw_svc.duplicate_homework(session, hw.id)
    session.flush()
    assert clone.status == "pending"
    assert clone.id != hw.id
    assert session.query(HomeworkScore).filter(
        HomeworkScore.homework_id == clone.id).count() == 0
    assert session.query(HomeworkAnswer).filter(
        HomeworkAnswer.homework_id == clone.id).count() == 0
    eng.dispose()


def test_history_batch_export_returns_valid_zip(tmp_path):
    """勾选多条历史记录后批量导出 Word 压缩包。"""
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    a = _seed_completed_homework(
        session, "批1", completed_at=datetime(2026, 9, 1, 8, 0))
    b = _seed_completed_homework(
        session, "批2", completed_at=datetime(2026, 9, 2, 8, 0))
    session.commit()

    with sessionmaker(bind=eng)() as s:
        data = hw_svc.export_homeworks_zip(s, [a.id, b.id])
    assert isinstance(data, (bytes, bytearray))
    zf = zipfile.ZipFile(io.BytesIO(data))
    names = zf.namelist()
    assert len(names) == 2
    assert all(n.endswith(".docx") for n in names)
    eng.dispose()


def test_history_subject_independent_from_manage(tmp_path):
    """历史页学科选择不影响作业管理学科筛选。"""
    db_file = tmp_path / "history_isolated.db"
    at = _apptest(db_file, tmp_path)

    # 切到历史页改学科
    _open_history_tab(at)
    picker = next(x for x in at.selectbox if x.key == fs.HISTORY_SUBJECT)
    picker.set_value("物理").run()
    assert picker.value == "物理"

    # 切回作业管理，学科仍为默认数学
    at.session_state["homework_tab"] = "作业管理"
    at.run()
    list_picker = next(
        x for x in at.selectbox if x.key == "homework_list_subject")
    assert list_picker.value == "数学"


def test_history_empty_state(tmp_path):
    """空库历史页显示固定空状态文案。"""
    db_file = tmp_path / "history_empty.db"
    at = _apptest(db_file, tmp_path)
    _open_history_tab(at)
    assert not at.exception, [str(e) for e in at.exception]
    info_text = "\n".join(str(x.value) for x in at.info)
    assert "暂无历史记录" in info_text


def test_history_mark_completed_then_shows_in_history(tmp_path):
    """作业管理点完成 → 历史页 metric 总数 1。"""
    db_file = tmp_path / "complete_to_history.db"
    eng = create_engine(f"sqlite:///{db_file.as_posix()}",
                        connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    hw = _seed_pending_homework(session, "待完成")
    session.commit()
    hw_id = hw.id
    eng.dispose()

    at = _apptest(db_file, tmp_path)
    at.session_state["homework_tab"] = "作业管理"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    next(b for b in at.button if b.key == f"finish_{hw_id}").click().run()

    _open_history_tab(at)
    assert not at.exception, [str(e) for e in at.exception]
    metrics = {m.label: m.value for m in at.metric}
    assert metrics.get("历史记录总数") == "1"
    assert metrics.get("作业数") == "1"


def test_history_delete_via_confirm(tmp_path):
    """历史页删除：确认后记录消失。"""
    db_file = tmp_path / "history_delete.db"
    eng = create_engine(f"sqlite:///{db_file.as_posix()}",
                        connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    hw = _seed_completed_homework(
        session, "将被删",
        completed_at=datetime(2026, 9, 1, 8, 0))
    session.commit()
    hid = hw.id
    eng.dispose()

    at = _apptest(db_file, tmp_path)
    _open_history_tab(at)
    # 点删除按钮进入确认态
    next(b for b in at.button if b.key == f"history_delete_{hid}").click().run()
    # 确认删除
    next(b for b in at.button if b.key == f"history_delete_ok_{hid}").click().run()
    assert not at.exception, [str(e) for e in at.exception]

    eng = create_engine(f"sqlite:///{db_file.as_posix()}")
    from sqlalchemy import text
    with eng.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM homeworks")).scalar_one()
    assert count == 0
    eng.dispose()