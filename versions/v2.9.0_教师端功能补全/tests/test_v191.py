# -*- coding: utf-8 -*-
"""v1.9.1 现有功能深化批次1测试。

覆盖：
- questions.parent_question_id 补列迁移；
- AI 试讲生成、归一和 Word 导出；
- 题目变式解析、保存、计数和删除父题后的保留口径；
- AppTest：AI 试讲、单题变式、空题库路径。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from models.models import Base, Question
from streamlit.testing.v1 import AppTest

from tests.test_app_smoke import _isolated_app_code, goto_top, goto_sub


# ---------------------------------------------------------------------------
# 夹具和辅助
# ---------------------------------------------------------------------------


@pytest.fixture()
def session(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'v191.db').as_posix()}")
    Base.metadata.create_all(engine)
    sess = sessionmaker(bind=engine)()
    yield sess
    sess.close()
    engine.dispose()


def _make_question(session, *, content="原题干", qtype="choice",
                   difficulty=1, kps=None, subject="数学", grade="高一",
                   status="approved"):
    from utils import question_service as qs
    data = {
        "content": content,
        "question_type": qtype,
        "difficulty": difficulty,
        "knowledge_points": json.dumps(kps or [], ensure_ascii=False),
        "answer": "A",
        "analysis": "原解析",
        "error_points": "",
        "verify": None,
    }
    q = qs.create_question(
        session, data, source="manual", status=status,
        subject=subject, grade=grade)
    session.flush()
    return q


def _make_lesson(session, *, title="试讲教案", grade="高一"):
    from utils import lesson_service as lesson_svc
    plan = lesson_svc.empty_plan()
    plan["objectives"]["knowledge"] = "掌握核心知识"
    plan["objectives"]["process"] = "学会分析方法"
    plan["key_points"] = "核心知识"
    plan["difficult_points"] = "灵活迁移"
    plan["process"][0]["content"] = "教师导入课堂。"
    plan["subject"] = "数学"
    lesson = lesson_svc.save_plan(
        session, title, plan, grade=grade, chapter="第一章",
        source="手动", subject="数学")
    session.commit()
    return lesson, lesson_svc.load_plan(lesson)


def _variant_json(vtype="number", qtype=None, content=None, answer="B",
                  kp="新知识点"):
    return {
        "content": content or f"{vtype}变式题干",
        "answer": answer,
        "analysis": "变式解析",
        "knowledge_point": kp,
        "variant_type": vtype,
        "question_type": qtype,
    }


# ---------------------------------------------------------------------------
# 一、补列迁移
# ---------------------------------------------------------------------------


def test_pending_columns_contains_parent_question_id():
    from utils import db
    assert ("parent_question_id", "INTEGER") in db._PENDING_COLUMNS["questions"]


def test_question_model_has_parent_question_id():
    column = Question.__table__.columns.get("parent_question_id")
    assert column is not None
    assert column.nullable is True


def test_old_sqlite_add_parent_question_id_idempotent(tmp_path, monkeypatch):
    db_file = tmp_path / "old.db"
    engine = create_engine(f"sqlite:///{db_file.as_posix()}")
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE questions (
                id INTEGER PRIMARY KEY,
                content TEXT NOT NULL,
                question_type TEXT,
                difficulty INTEGER,
                knowledge_points TEXT,
                answer TEXT NOT NULL,
                analysis TEXT,
                multiple_solutions TEXT,
                error_points TEXT,
                subject TEXT,
                grade TEXT,
                source TEXT,
                status TEXT,
                usage_count INTEGER,
                correct_rate REAL,
                created_at DATETIME
            )
        """))
        conn.execute(text(
            "INSERT INTO questions(content, answer, status) VALUES "
            "('旧题', '答案', 'approved')"))

    from utils import db
    monkeypatch.setattr(db, "engine", engine)
    db._add_missing_columns()
    columns = {c["name"] for c in inspect(engine).get_columns("questions")}
    assert "parent_question_id" in columns
    # 再跑一次不能报错。
    db._add_missing_columns()
    engine.dispose()


# ---------------------------------------------------------------------------
# 二、AI 试讲服务
# ---------------------------------------------------------------------------


def test_trial_lecture_returns_normalized_script(monkeypatch):
    from utils import lesson_service as lesson_svc
    captured = {}

    def fake_chat(system, user, temperature=0.8):
        captured["system"] = system
        captured["user"] = user
        return json.dumps({
            "import": "【关键提问】从哪里导入？",
            "lecture": "【学生回答】学生可能回答",
            "practice": "【应对策略】放慢节奏",
            "summary": "总结要点",
        }, ensure_ascii=False)

    monkeypatch.setattr(lesson_svc.llm_client, "chat_content", fake_chat)
    lesson, plan = _make_lesson.__wrapped__ if False else (None, None)

    from models.models import LessonPlan
    lesson = LessonPlan(title="测试教案")
    plan = lesson_svc.empty_plan()
    plan["objectives"]["knowledge"] = "理解概念"
    plan["key_points"] = "重点"
    plan["difficult_points"] = "难点"
    settings = {"class_level": "重点班", "duration": 45, "activity": "高"}
    script = lesson_svc.trial_lecture(lesson, plan, settings)

    assert "【关键提问】" in script["import"]
    assert "board_design" in script and script["board_design"] == ""
    assert "重点班" in captured["user"]
    assert "45" in captured["user"] and "高" in captured["user"]
    assert "只输出 JSON" in captured["system"]


def test_normalize_trial_script_rejects_non_object():
    from utils import lesson_service as lesson_svc
    with pytest.raises(ValueError):
        lesson_svc.normalize_trial_script([])


def test_trial_lecture_invalid_json_raises(monkeypatch):
    from utils import lesson_service as lesson_svc
    monkeypatch.setattr(
        lesson_svc.llm_client, "chat_content", lambda *a, **k: "不是JSON")
    from models.models import LessonPlan
    with pytest.raises(ValueError):
        lesson_svc.trial_lecture(
            LessonPlan(title="x"), lesson_svc.empty_plan(), {})


def test_export_trial_word_contains_sections(monkeypatch):
    from utils import lesson_service as lesson_svc
    from models.models import LessonPlan
    script = lesson_svc.normalize_trial_script({
        "import": "导入", "lecture": "讲解", "practice": "练习",
        "summary": "总结", "board_design": "板书"})
    data = lesson_svc.export_trial_word(
        LessonPlan(title="教案"), lesson_svc.empty_plan(), script,
        {"class_level": "平行班", "duration": 40, "activity": "中"})
    assert data[:2] == b"PK"


# ---------------------------------------------------------------------------
# 三、变式服务
# ---------------------------------------------------------------------------


def test_parse_variants_three_types_and_invalid_rows(session):
    from utils import question_service as qs
    parent = _make_question(session, difficulty=2, kps=["原知识点"])
    raw = json.dumps([
        _variant_json("number", content="数字变式"),
        _variant_json("context", content="情境变式"),
        _variant_json("difficulty", content="难度变式", kp="拓展点"),
        {"content": "缺答案", "variant_type": "number"},
        {"answer": "B", "variant_type": "number"},
    ], ensure_ascii=False)
    variants = qs.parse_variant_questions(
        raw, parent, ["number", "context", "difficulty"], 1, "higher")
    assert [v["variant_type"] for v in variants] == [
        "number", "context", "difficulty"]
    # 数字/情境保持原难度；难度变式提高。
    assert [v["difficulty"] for v in variants] == [2, 2, 3]
    assert json.loads(variants[0]["knowledge_points"]) == ["原知识点", "新知识点"]
    assert json.loads(variants[2]["knowledge_points"]) == ["原知识点", "拓展点"]


def test_parse_variants_difficulty_clamp(session):
    from utils import question_service as qs
    parent = _make_question(session, difficulty=1)
    raw = json.dumps([_variant_json("difficulty")], ensure_ascii=False)
    lower = qs.parse_variant_questions(raw, parent, ["difficulty"], 1, "lower")
    assert lower[0]["difficulty"] == 1

    parent.difficulty = 3
    raw = json.dumps([_variant_json("difficulty")], ensure_ascii=False)
    higher = qs.parse_variant_questions(raw, parent, ["difficulty"], 1, "higher")
    assert higher[0]["difficulty"] == 3


def test_generate_variants_validates_arguments(session):
    from utils import question_service as qs
    parent = _make_question(session)
    with pytest.raises(ValueError):
        qs.generate_variants(parent, [])
    with pytest.raises(ValueError):
        qs.generate_variants(parent, ["数字变式"], count=9)
    with pytest.raises(ValueError):
        qs.generate_variants(parent, ["数字变式"], difficulty_adjust="bad")


def test_generate_variants_uses_llm(monkeypatch, session):
    from utils import question_service as qs
    parent = _make_question(session, difficulty=2, kps=["方程"])
    captured = {}

    def fake_chat(system, user, temperature=0.8):
        captured["system"] = system
        captured["user"] = user
        return json.dumps([_variant_json("number")], ensure_ascii=False)

    monkeypatch.setattr(qs.llm_client, "chat_content", fake_chat)
    variants = qs.generate_variants(parent, ["数字变式"], 2, "keep")
    assert len(variants) == 1
    assert "原题ID" in captured["user"]
    assert "每种类型生成：2" in captured["user"]


def test_save_variants_writes_pending_parent(session):
    from utils import question_service as qs
    parent = _make_question(session, subject="数学", grade="高一",
                            kps=["原K"])
    raw = json.dumps([_variant_json("number")], ensure_ascii=False)
    variants = qs.parse_variant_questions(
        raw, parent, ["number"], 1, "keep")
    ids = qs.save_variants(session, variants, parent.id)
    session.commit()
    child = session.get(Question, ids[0])
    assert child.parent_question_id == parent.id
    assert child.status == "pending"
    assert child.subject == "数学"
    assert child.grade == "高一"  # 界面口径原样继承
    assert qs.knowledge_points_list(child) == ["原K", "新知识点"]


def test_variant_counts(session):
    from utils import question_service as qs
    parent = _make_question(session)
    raw = json.dumps([_variant_json("number"), _variant_json("context")],
                     ensure_ascii=False)
    variants = qs.parse_variant_questions(
        raw, parent, ["number", "context"], 1, "keep")
    qs.save_variants(session, variants, parent.id)
    session.commit()
    assert qs.variant_counts(session) == {parent.id: 2}


def test_delete_parent_relinks_to_grandparent(session):
    """祖父→父→子：删除父题后，子题改挂祖父；再删祖父则脱离来源但保留。"""
    from utils import question_service as qs
    grand = _make_question(session, content="祖父题")
    parent = _make_question(session, content="父题")
    parent.parent_question_id = grand.id
    child = _make_question(session, content="子题")
    child.parent_question_id = parent.id
    session.commit()

    qs.delete_question(session, parent.id)
    session.flush()
    assert session.get(Question, child.id).parent_question_id == grand.id
    assert session.get(Question, parent.id) is None

    qs.delete_question(session, grand.id)
    session.flush()
    assert session.get(Question, child.id).parent_question_id is None
    assert session.get(Question, child.id) is not None




def test_undo_delete_parent_restores_child_link(session):
    """撤销删除父题：父题恢复，子题重新指向父题。"""
    from utils import question_service as qs, undo_service
    parent = _make_question(session, content="待撤销父题")
    child = _make_question(session, content="待撤销子题")
    child.parent_question_id = parent.id
    session.commit()

    undo_service.record(
        session, "delete_question", {"target": (Question, parent.id)},
        f"删除题目 #{parent.id}")
    qs.delete_question(session, parent.id)
    session.flush()
    assert session.get(Question, child.id).parent_question_id is None

    undo_service.undo(session)
    session.flush()
    assert session.get(Question, parent.id) is not None
    assert session.get(Question, child.id).parent_question_id == parent.id

# ---------------------------------------------------------------------------
# 四、AppTest
# ---------------------------------------------------------------------------


def _isolated_at(db_file: Path, tmp_path: Path):
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / "feature.json"),
        default_timeout=30)
    at.run()
    return at


def test_ai_trial_apptest(tmp_path, monkeypatch):
    import modules.lesson_plan as lesson_module
    from utils import llm_client

    db_file = tmp_path / "trial.db"
    engine = create_engine(f"sqlite:///{db_file.as_posix()}")
    Base.metadata.create_all(engine)
    db_session = sessionmaker(bind=engine)()
    lesson, plan = _make_lesson(db_session)
    lesson_id = lesson.id
    db_session.close()

    monkeypatch.setattr(
        llm_client, "chat_content",
        lambda *a, **k: json.dumps({
            "import": "【关键提问】怎么引入？",
            "lecture": "【学生回答】学生想法",
            "practice": "【应对策略】增加提示",
            "summary": "回顾总结",
            "board_design": "主板书",
        }, ensure_ascii=False))

    at = _isolated_at(db_file, tmp_path)
    at.session_state["app_top_page"] = "📚 备课"
    at.session_state["lesson_plan_tab"] = "AI 备课"
    at.session_state["lp_plan"] = plan
    at.session_state["lp_meta"] = {
        "title": lesson.title, "grade": "高一", "chapter": "第一章",
        "source": "手动", "subject": "数学", "plan_id": lesson_id,
    }
    at.run()
    assert not at.exception, [str(x) for x in at.exception]
    next(b for b in at.button if b.key == "lesson_trial").click().run()
    assert not at.exception, [str(x) for x in at.exception]
    next(b for b in at.button if b.key == "trial_start").click().run()
    assert not at.exception, [str(x) for x in at.exception]

    expander_labels = {x.label for x in at.expander}
    assert {"课堂导入", "新知讲解", "课堂练习", "课堂总结", "板书设计"} <= expander_labels
    next(b for b in at.button if b.key == "trial_export_word").click().run()
    assert not at.exception, [str(x) for x in at.exception]
    engine.dispose()


def test_single_question_variant_apptest(tmp_path, monkeypatch):
    import modules.lesson_plan as lesson_module
    from utils import llm_client, question_service as qs

    db_file = tmp_path / "single_variant.db"
    engine = create_engine(
        f"sqlite:///{db_file.as_posix()}",
        connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    db_session = sessionmaker(bind=engine)()
    parent = _make_question(db_session, content="变式父题", kps=["父K"])
    parent_id = parent.id
    db_session.commit()
    db_session.close()

    def fake_aggrid(df, gridOptions=None, key=None, **kwargs):
        return {"data": df, "selected_rows": df.head(0)}

    monkeypatch.setattr(lesson_module, "AgGrid", fake_aggrid)
    monkeypatch.setattr(
        llm_client, "chat_content",
        lambda *a, **k: json.dumps([_variant_json("number")],
                                   ensure_ascii=False))

    at = _isolated_at(db_file, tmp_path)
    goto_sub(at, "lesson_plan_tab", "题库管理", "📚 备课")
    assert not at.exception, [str(x) for x in at.exception]
    next(b for b in at.button
         if b.key == f"variant_generate_{parent_id}").click().run()
    type_picker = next(x for x in at.multiselect if x.key == "variant_types")
    type_picker.set_value(["换数字"]).run()
    next(b for b in at.button if b.key == "variant_start").click().run()
    assert not at.exception, [str(x) for x in at.exception]

    groups = at.session_state["variant_groups"]
    variant = groups[0]["variants"][0]
    pick_key = f"variant_pick_{parent_id}_{variant['temp_id']}"
    next(x for x in at.checkbox if x.key == pick_key).check().run()
    next(b for b in at.button if b.key == "variant_save").click().run()
    assert not at.exception, [str(x) for x in at.exception]

    check_session = sessionmaker(bind=engine)()
    child = check_session.query(Question).filter(
        Question.parent_question_id == parent_id).one()
    assert child.status == "pending"
    assert child.grade == "高一"
    assert qs.knowledge_points_list(child) == ["父K", "新知识点"]
    check_session.close()
    engine.dispose()


def test_bank_empty_page_no_exception(tmp_path):
    at = _isolated_at(tmp_path / "empty_bank.db", tmp_path)
    goto_sub(at, "lesson_plan_tab", "题库管理", "📚 备课")
    assert not at.exception, [str(x) for x in at.exception]
    assert any("题库里还没有符合条件的题" in str(x.value) for x in at.info)
