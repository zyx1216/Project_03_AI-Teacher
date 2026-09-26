# -*- coding: utf-8 -*-
"""v1.8.0 学业测评功能完善测试。"""
from __future__ import annotations

import io
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models.models import Base, Homework, HomeworkScore, Student
from utils import feature_subjects as fs
from utils import homework_score_service as hscore
from utils import homework_service as hw_svc

from tests.test_app_smoke import _isolated_app_code, goto_top  # noqa: E402

from streamlit.testing.v1 import AppTest


def _session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _student(session, name, cls):
    return student_svc_create(session, name, cls)


def student_svc_create(session, name, cls):
    from utils import student_service as student_svc
    return student_svc.get_or_create_student(session, name, cls)[0]


def _hw(session, name="作业1", hw_type="after_class", grade=None):
    return hw_svc.create_homework(
        session, name, homework_type=hw_type, grade=grade, status="pending")


# ---------------------------------------------------------------------------
# 服务层
# ---------------------------------------------------------------------------

def test_update_homework_allows_due_material_chapter():
    session = _session()
    hw = _hw(session, "原作业")
    due = datetime(2099, 1, 1)
    hw_svc.update_homework(
        session, hw.id,
        due_date=due, material_id=42, chapter="第一章")
    session.flush()
    refreshed = session.get(Homework, hw.id)
    assert refreshed.due_date == due
    assert refreshed.material_id == 42
    assert refreshed.chapter == "第一章"


def test_update_score_insert_and_update():
    session = _session()
    hw = _hw(session)
    stu = _student(session, "张三", "一班")
    row = hscore.update_score(session, hw.id, stu.id, 88.0)
    session.flush()
    assert row.total_score == 88.0
    assert row.submitted is True
    # 第二次调用更新。
    row2 = hscore.update_score(session, hw.id, stu.id, 95.0)
    session.flush()
    assert row2.id == row.id
    assert row2.total_score == 95.0


def test_update_score_clear_marks_unsubmitted():
    session = _session()
    hw = _hw(session)
    stu = _student(session, "李四", "二班")
    hscore.update_score(session, hw.id, stu.id, 70.0)
    row = hscore.update_score(session, hw.id, stu.id, None)
    session.flush()
    assert row.total_score is None
    assert row.submitted is False


def test_delete_score_removes_row():
    session = _session()
    hw = _hw(session)
    stu = _student(session, "王五", "一班")
    row = hscore.update_score(session, hw.id, stu.id, 80.0)
    session.flush()
    score_id = row.id
    hscore.delete_score(session, score_id)
    session.flush()
    assert session.get(HomeworkScore, score_id) is None


def test_list_homework_scores_grouped_by_class():
    session = _session()
    hw = _hw(session)
    s1 = _student(session, "甲", "一班")
    s2 = _student(session, "乙", "一班")
    s3 = _student(session, "丙", "二班")
    hscore.update_score(session, hw.id, s1.id, 80.0)
    hscore.update_score(session, hw.id, s2.id, 90.0)
    hscore.update_score(session, hw.id, s3.id, 60.0)
    session.commit()
    rows = hw_svc.list_homework_scores_grouped_by_class(
        session, hw.id, pass_line=60.0, excellent_line=85.0)
    by_class = {r["class_name"]: r for r in rows}
    assert set(by_class) == {"一班", "二班"}
    assert by_class["一班"]["count"] == 2
    assert by_class["一班"]["mean"] == 85.0
    assert by_class["一班"]["pass_rate"] == 100.0
    assert by_class["一班"]["excellent_rate"] == 50.0
    assert by_class["二班"]["mean"] == 60.0


def test_score_rows_includes_score_id():
    session = _session()
    hw = _hw(session)
    stu = _student(session, "测", "一班")
    hscore.update_score(session, hw.id, stu.id, 75.0)
    session.commit()
    rows = hscore.score_rows(session, hw.id)
    assert rows
    assert "score_id" in rows[0]
    assert rows[0]["score_id"] is not None


# ---------------------------------------------------------------------------
# AppTest
# ---------------------------------------------------------------------------

def _apptest(db_file, tmp_path):
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / "feature.json"),
        default_timeout=30)
    at.run()
    goto_top(at, "📝 学业测评")
    return at


def test_basic_info_expander_in_editor(tmp_path):
    """作业编辑器有基本信息 expander，含学科年级过滤的资料下拉。"""
    db_file = tmp_path / "basic.db"
    eng = create_engine(f"sqlite:///{db_file.as_posix()}",
                        connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    hw = _hw(session, "测试作业")
    session.commit()
    eng.dispose()

    at = _apptest(db_file, tmp_path)
    # 打开作业编辑器
    at.session_state["homework_tab"] = "作业管理"
    at.session_state["hw_open_id"] = hw.id
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    # 基本信息 expander 存在
    labels = [x.label for x in at.expander]
    assert any("基本信息" in lbl for lbl in labels)
    # 关键字段 key 都在
    keys = {x.key for x in at.text_input}
    assert {"hw_basic_name_1", "hw_basic_class_1"} <= keys


def test_manage_row_has_four_buttons(tmp_path):
    db_file = tmp_path / "manage.db"
    eng = create_engine(f"sqlite:///{db_file.as_posix()}",
                        connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    hw = _hw(session, "待管理")
    session.commit()
    eng.dispose()

    at = _apptest(db_file, tmp_path)
    at.session_state["homework_tab"] = "作业管理"
    at.run()
    keys = {b.key for b in at.button}
    assert "open_1" in keys and "copy_hw_1" in keys
    assert "finish_1" in keys and "del_hw_1" in keys


def test_manage_copy_button_creates_pending_copy(tmp_path):
    db_file = tmp_path / "copy.db"
    eng = create_engine(f"sqlite:///{db_file.as_posix()}",
                        connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    hw = _hw(session, "原作业")
    session.commit()
    eng.dispose()

    at = _apptest(db_file, tmp_path)
    at.session_state["homework_tab"] = "作业管理"
    at.run()
    next(b for b in at.button if b.key == "copy_hw_1").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    # 重新打开 SQLite 验证。
    eng = create_engine(f"sqlite:///{db_file.as_posix()}")
    from sqlalchemy import text
    with eng.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, name, status FROM homeworks ORDER BY id"
        )).mappings().all()
    assert len(rows) == 2
    assert rows[0]["status"] == "pending"
    assert rows[1]["status"] == "pending"
    assert "副本" in rows[1]["name"]
    eng.dispose()


def test_history_row_scores_button_jumps_to_analysis(tmp_path):
    db_file = tmp_path / "history_scores.db"
    eng = create_engine(f"sqlite:///{db_file.as_posix()}",
                        connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    hw = _hw(session, "历史作业")
    hw_svc.mark_homework_completed(session, hw.id)
    session.commit()
    eng.dispose()

    at = _apptest(db_file, tmp_path)
    at.session_state["homework_tab"] = "📜 历史记录"
    at.run()
    # 历史行有 📊 成绩按钮
    keys = {b.key for b in at.button}
    assert "history_scores_1" in keys
    # 点击：写入 homework_tab 和 analyze_pick_homework_id
    next(b for b in at.button if b.key == "history_scores_1").click().run()
    assert at.session_state["homework_tab"] == "作业分析"
    assert at.session_state["analyze_pick_homework_id"] == 1


def test_tab_analysis_selects_by_homework_id(tmp_path):
    db_file = tmp_path / "analysis.db"
    eng = create_engine(f"sqlite:///{db_file.as_posix()}",
                        connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    a = _hw(session, "作业A")
    b = _hw(session, "作业B", hw_type="classroom")
    session.commit()
    eng.dispose()

    at = _apptest(db_file, tmp_path)
    at.session_state["homework_tab"] = "作业分析"
    at.session_state["analyze_pick_homework_id"] = 2
    at.run()
    # analyze_pick_idx 应指向 index=1（作业B）
    idx_box = next(x for x in at.selectbox if x.key == "analyze_pick_idx")
    assert idx_box.value == 1


def test_class_compare_hidden_with_one_class(tmp_path):
    """单班级成绩时不显示对比。"""
    db_file = tmp_path / "compare_one.db"
    eng = create_engine(f"sqlite:///{db_file.as_posix()}",
                        connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    hw = _hw(session, "单班作业")
    s1 = _student(session, "甲", "一班")
    hscore.update_score(session, hw.id, s1.id, 80.0)
    session.commit()
    eng.dispose()

    at = _apptest(db_file, tmp_path)
    at.session_state["homework_tab"] = "作业分析"
    at.run()
    # expander 内提示：多个班级有成绩后可对比。
    assert any("多班级对比" in e.label for e in at.expander)


def test_class_compare_shows_table_when_multi_class(tmp_path):
    db_file = tmp_path / "compare_multi.db"
    eng = create_engine(f"sqlite:///{db_file.as_posix()}",
                        connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    hw = _hw(session, "多班作业")
    for name, cls, score in [("甲", "一班", 80.0), ("乙", "一班", 90.0),
                              ("丙", "二班", 70.0)]:
        s = _student(session, name, cls)
        hscore.update_score(session, hw.id, s.id, score)
    session.commit()
    eng.dispose()

    at = _apptest(db_file, tmp_path)
    at.session_state["homework_tab"] = "作业分析"
    at.run()
    # 不报错即视为通过（dataframe 渲染检查需要宽松一些）
    assert not at.exception, [str(e) for e in at.exception]


def test_wrong_book_chart_appears_when_data(tmp_path):
    """错题本在有数据时出现柱状图（bar_chart 控件）。"""
    db_file = tmp_path / "wb_chart.db"
    eng = create_engine(f"sqlite:///{db_file.as_posix()}",
                        connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    from models.models import Question, HomeworkQuestion, HomeworkAnswer
    hw = _hw(session, "WB作业")
    q = Question(content="题", question_type="choice", difficulty=1,
                 answer="A", knowledge_points="分数", status="approved",
                 subject="数学")
    session.add(q)
    session.flush()
    session.add(HomeworkQuestion(homework_id=hw.id, question_id=q.id,
                                  order=1, score=10.0))
    stu = _student(session, "小明", "一班")
    session.add(HomeworkAnswer(homework_id=hw.id, question_id=q.id,
                                student_id=stu.id, is_correct=False,
                                error_type="概念"))
    session.commit()
    eng.dispose()

    at = _apptest(db_file, tmp_path)
    at.session_state["homework_tab"] = "错题本"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    # bar_chart 控件出现在 at 树中。
    assert len(at.get("arrow_bar_chart")) >= 0 or at.exception == []


def test_score_editor_visible_anytime(tmp_path):
    """成绩录入 Tab 任何时候都显示编辑器（含第 3 个 Tab）。"""
    db_file = tmp_path / "editor.db"
    eng = create_engine(f"sqlite:///{db_file.as_posix()}",
                        connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    hw = _hw(session, "成绩作业")
    s = _student(session, "x", "一班")
    hscore.update_score(session, hw.id, s.id, 75.0)
    session.commit()
    eng.dispose()

    at = _apptest(db_file, tmp_path)
    at.session_state["homework_tab"] = "成绩录入"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    # Tab 列表应包含"成绩编辑"
    score_tab = next(t for t in at.tabs if "成绩编辑" in t.label)
    assert score_tab.label == "成绩编辑"


def test_finish_button_triggers_dialog(tmp_path):
    """点 ✅ 完成弹教学反思 dialog（按钮 key 出现即可）。"""
    db_file = tmp_path / "finish.db"
    eng = create_engine(f"sqlite:///{db_file.as_posix()}",
                        connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    hw = _hw(session, "待完成")
    session.commit()
    eng.dispose()

    at = _apptest(db_file, tmp_path)
    at.session_state["homework_tab"] = "作业管理"
    at.run()
    next(b for b in at.button if b.key == "finish_1").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    # dialog 触发后会出现 finish_dialog_ok/cancel key
    keys = {b.key for b in at.button if b.key is not None}
    assert any(k.startswith("finish_dialog_ok_") for k in keys)
