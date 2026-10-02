# -*- coding: utf-8 -*-
"""v1.8.1 高优先级功能优化测试。

覆盖：
- 全局搜索服务 search_all：四类命中、limit、空结果、通配符转义；
- 题库批量编辑 batch_update_questions；
- AppTest：侧边栏搜索框与四类跳转、AI 备课重生成/继续、出题重生成/追加、题库批量编辑。
全部使用临时 SQLite、临时 JSON、隔离脚本，不碰真实数据库。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models.models import (
    Base, Homework, LessonPlan, Question, Student, Textbook)
from utils import global_search_service as gs_search
from utils import question_service as qs
from utils import homework_service as hw_svc
from utils import lesson_service as lesson_svc
from utils import student_service as student_svc

from streamlit.testing.v1 import AppTest

from tests.test_app_smoke import (  # noqa: E402
    _isolated_app_code, goto_sub, goto_top, inline_tasks)


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _memory_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _make_question(session, content, subject="数学", grade=None,
                   kps=None, diff=2):
    data = qs.validate_question({
        "content": content,
        "question_type": "solution",
        "difficulty": diff,
        "answer": "答案",
        "knowledge_points": kps if kps is not None else [],
    })
    q = qs.create_question(
        session, data, source="manual", status="approved",
        subject=subject, grade=grade)
    session.flush()
    return q


# ---------------------------------------------------------------------------
# 全局搜索：服务层
# ---------------------------------------------------------------------------

def test_search_all_four_categories_hit():
    session = _memory_session()
    _make_question(session, "一元二次方程求根题目", kps=["方程"])
    plan = LessonPlan(
        title="函数的图象教案", chapter="第三章",
        content=json.dumps({"subject": "数学"}, ensure_ascii=False))
    session.add(plan)
    session.add(Student(name="张三", class_name="一班"))
    session.add(Homework(name="期中作业", is_template=False))
    session.commit()

    result = gs_search.search_all(session, "函数")
    assert len(result["questions"]) == 0  # 题干不含“函数”
    assert [p.id for p in result["plans"]] == [plan.id]

    result_q = gs_search.search_all(session, "方程")
    assert len(result_q["questions"]) == 1
    result_s = gs_search.search_all(session, "张三")
    assert [s.name for s in result_s["students"]] == ["张三"]
    result_h = gs_search.search_all(session, "期中")
    assert [h.name for h in result_h["homeworks"]] == ["期中作业"]


def test_search_homework_excludes_templates_and_drafts():
    session = _memory_session()
    session.add(Homework(name="普通作业", is_template=False))
    session.add(Homework(name="模板作业", is_template=True))
    session.add(Homework(name="__smart_compose_draft__草稿",
                         is_template=True))
    session.commit()

    result = gs_search.search_all(session, "作业")
    names = [h.name for h in result["homeworks"]]
    assert names == ["普通作业"]
    assert "模板作业" not in names


def test_search_empty_result():
    session = _memory_session()
    result = gs_search.search_all(session, "不存在的关键词xyz")
    assert result == {
        "questions": [], "plans": [], "students": [], "homeworks": []}


def test_search_wildcard_escaped():
    """输入 %、_、\\ 不会报错，也不被当成通配符匹配全部。"""
    session = _memory_session()
    _make_question(session, "普通题干")
    for token in ("%", "_", "\\", "a_b", "100%"):
        result = gs_search.search_all(session, token)
        assert set(result) == {"questions", "plans", "students", "homeworks"}
    # “%”不应该匹配到全部题目。
    assert gs_search.search_all(session, "%")["questions"] == []


def test_search_limit_five():
    session = _memory_session()
    for i in range(7):
        _make_question(session, f"重复关键词题目{i}")
    session.commit()
    result = gs_search.search_all(session, "重复关键词")
    assert len(result["questions"]) == 5


# ---------------------------------------------------------------------------
# 批量编辑：服务层
# ---------------------------------------------------------------------------

def test_batch_update_difficulty_integer():
    session = _memory_session()
    q1 = _make_question(session, "题1", diff=1)
    q2 = _make_question(session, "题2", diff=1)
    n = qs.batch_update_questions(session, [q1.id, q2.id], difficulty=3)
    session.flush()
    assert n == 2
    assert session.get(Question, q1.id).difficulty == 3
    assert session.get(Question, q2.id).difficulty == 3


def test_batch_update_subject_and_display_grade():
    session = _memory_session()
    q = _make_question(session, "题", subject="数学", grade=None)
    qs.batch_update_questions(
        session, [q.id], subject="物理", grade="高一")
    session.flush()
    refreshed = session.get(Question, q.id)
    assert refreshed.subject == "物理"
    assert refreshed.grade == "高一"  # 界面口径原样写入


def test_batch_update_merges_knowledge_points_json():
    session = _memory_session()
    q = _make_question(session, "题", kps=["方程", "函数"])
    qs.batch_update_questions(
        session, [q.id], add_knowledge_points=["函数", "几何", ""])
    session.flush()
    kps = qs.knowledge_points_list(session.get(Question, q.id))
    assert kps == ["方程", "函数", "几何"]  # 合并去重保序


def test_batch_update_only_selected():
    session = _memory_session()
    q1 = _make_question(session, "题1", diff=1)
    q2 = _make_question(session, "题2", diff=1)
    qs.batch_update_questions(session, [q1.id], difficulty=2)
    session.flush()
    assert session.get(Question, q1.id).difficulty == 2
    assert session.get(Question, q2.id).difficulty == 1


def test_batch_update_invalid_difficulty_raises():
    session = _memory_session()
    q = _make_question(session, "题")
    with pytest.raises(ValueError):
        qs.batch_update_questions(session, [q.id], difficulty=9)


# ---------------------------------------------------------------------------
# AppTest
# ---------------------------------------------------------------------------

def _make_app(db_file, tmp_path, ai_response=None):
    """构造隔离 AppTest；ai_response 非空时替换 chat_content。"""
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / "feature.json"),
        default_timeout=30)
    at.run()
    return at


def _seed_search_db(db_file: Path):
    """造题目/教案/学生/作业各 1，返回各自 id。"""
    engine = create_engine(
        f"sqlite:///{db_file.as_posix()}",
        connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    q = _make_question(session, "光合作用题目", kps=["生物"])
    plan = LessonPlan(
        title="细胞呼吸教案", chapter="第二章",
        content=json.dumps({"subject": "生物"}, ensure_ascii=False))
    session.add(plan)
    stu = Student(name="李四", class_name="二班")
    session.add(stu)
    hw = Homework(name="课后作业", is_template=False)
    session.add(hw)
    session.commit()
    ids = {"q": q.id, "plan": plan.id, "stu": stu.id, "hw": hw.id}
    session.close()
    engine.dispose()
    return ids


def test_sidebar_search_box_exists(tmp_path):
    at = _make_app(tmp_path / "s.db", tmp_path)
    assert at.sidebar.text_input[0].key == "global_search"


def test_search_jump_question(tmp_path):
    db_file = tmp_path / "search.db"
    ids = _seed_search_db(db_file)
    at = _make_app(db_file, tmp_path)
    at.sidebar.text_input[0].set_value("光合作用").run()
    assert not at.exception, [str(e) for e in at.exception]
    next(b for b in at.sidebar.button if b.key == f"search_q_{ids['q']}").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    assert at.session_state["app_top_page"] == "📚 备课"
    assert at.session_state["lesson_plan_tab"] == "题库管理"
    assert at.session_state["bank_search_keyword"] == "光合作用"


def test_search_jump_plan(tmp_path):
    db_file = tmp_path / "searchp.db"
    ids = _seed_search_db(db_file)
    at = _make_app(db_file, tmp_path)
    at.sidebar.text_input[0].set_value("细胞").run()
    next(b for b in at.sidebar.button if b.key == f"search_plan_{ids['plan']}").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    assert at.session_state["lesson_plan_tab"] == "AI 备课"
    assert "lp_plan" in at.session_state
    assert at.session_state["lp_meta"]["plan_id"] == ids["plan"]


def test_search_jump_student(tmp_path):
    db_file = tmp_path / "searchs.db"
    ids = _seed_search_db(db_file)
    at = _make_app(db_file, tmp_path)
    at.sidebar.text_input[0].set_value("李四").run()
    next(b for b in at.sidebar.button if b.key == f"search_stu_{ids['stu']}").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    assert at.session_state["app_top_page"] == "📊 学情"
    assert at.session_state["analysis_tab"] == "学生管理"
    assert at.session_state["student_filter_keyword"] == "李四"


def test_search_jump_homework(tmp_path):
    db_file = tmp_path / "searchh.db"
    ids = _seed_search_db(db_file)
    at = _make_app(db_file, tmp_path)
    at.sidebar.text_input[0].set_value("课后").run()
    next(b for b in at.sidebar.button if b.key == f"search_hw_{ids['hw']}").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    assert at.session_state["app_top_page"] == "📝 学业测评"
    assert at.session_state["homework_tab"] == "作业管理"
    assert at.session_state["hw_open_id"] == ids["hw"]


def test_search_no_result_message(tmp_path):
    at = _make_app(tmp_path / "none.db", tmp_path)
    at.sidebar.text_input[0].set_value("zzz无结果").run()
    assert any("未找到匹配结果" in str(c.value) for c in at.sidebar.caption)


def test_empty_pages_no_exception(tmp_path):
    at = _make_app(tmp_path / "empty.db", tmp_path)
    for page in ["📚 备课", "📝 学业测评", "📊 学情"]:
        goto_top(at, page)
        assert not at.exception, (page, [str(e) for e in at.exception])


# ---------------------------------------------------------------------------
# AI 备课：重新生成 / 继续补充
# ---------------------------------------------------------------------------

def _lesson_ai_response():
    plan = lesson_svc.empty_plan()
    plan["subject"] = "数学"
    return "```json\n" + json.dumps(plan, ensure_ascii=False) + "\n```"


def _lesson_app(tmp_path, monkeypatch, calls):
    from utils import llm_client
    db_file = tmp_path / "lesson.db"

    def _fake_chat(system, user, temperature=0.7):
        calls.append(user)
        return _lesson_ai_response()

    monkeypatch.setattr(llm_client, "chat_content", _fake_chat)
    monkeypatch.setattr(llm_client, "is_content_configured", lambda: True)
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / "feature.json"),
        default_timeout=30)
    at.run()
    goto_sub(at, "lesson_plan_tab", "AI 备课", "📚 备课")
    return at


def test_lesson_regen_and_continue(tmp_path, monkeypatch):
    calls = []
    at = _lesson_app(tmp_path, monkeypatch, calls)
    # v3.3.1：生成教案走后台任务，测试里用同步实现跑一遍。
    inline_tasks(monkeypatch)
    # 填课题并生成。
    topic_input = next(x for x in at.text_input if x.label == "课题 *")
    topic_input.set_value("测试课题").run()
    next(b for b in at.button if b.key == "generate_lesson_button").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    assert len(calls) == 1
    # 后台任务完成后，手动载入到编辑区。
    next(b for b in at.button if b.key == "lesson_bg_load").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    # 出现 重新生成/继续补充 按钮。
    keys = {b.key for b in at.button}
    assert "lesson_regen" in keys and "lesson_continue" in keys
    # 重新生成：再调一次，参数保留。
    next(b for b in at.button if b.key == "lesson_regen").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    assert len(calls) == 2
    assert "测试课题" in calls[1]
    # 继续补充：进入模式 -> 填写 -> 确认，请求含“额外要求”。
    next(b for b in at.button if b.key == "lesson_continue").click().run()
    next(x for x in at.text_area if x.key == "lesson_extra_req").set_value(
        "多举一个生活例子").run()
    next(b for b in at.button if b.key == "lesson_continue_ok").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    assert len(calls) == 3
    assert "额外要求：多举一个生活例子" in calls[2]


# ---------------------------------------------------------------------------
# AI 出题：重新生成 / 追加
# ---------------------------------------------------------------------------

def _question_ai_response():
    return json.dumps([
        {
            "content": "AI生成选择题干",
            "question_type": "选择题",
            "difficulty": 1,
            "knowledge_points": ["知识点"],
            "answer": "A",
        }
    ], ensure_ascii=False)


def _question_gen_app(tmp_path, monkeypatch, calls):
    """直接注入预览所需的 multi_gen 状态与可复用 tasks，绕过任务栏生成。"""
    from utils import llm_client
    db_file = tmp_path / "qgen.db"

    def _fake_chat(system, user, temperature=0.8):
        calls.append(user)
        return _question_ai_response()

    monkeypatch.setattr(llm_client, "chat_content", _fake_chat)
    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / "feature.json"),
        default_timeout=30)
    at.run()
    goto_sub(at, "lesson_plan_tab", "AI 出题", "📚 备课")
    return at


def _inject_preview(at):
    task = {
        "subject": "数学",
        "grade": "一年级",
        "question_type": "选择题",
        "difficulty": 1,
        "count": 1,
        "chapters": [],
        "knowledge_points": ["知识点"],
        "extra": "",
        "material_id": None,
    }
    at.session_state["multi_gen_questions"] = {
        "数学": {"valid": [{
            "content": "AI生成选择题干",
            "question_type": "choice",
            "difficulty": 1,
            "knowledge_points": '["知识点"]',
            "answer": "A",
            "analysis": "",
            "error_points": "",
            "grade": "一年级",
        }], "rejected": 0}}
    at.session_state["multi_gen_config"] = {
        "mode": "question_tasks", "grade": "",
        "subjects": ["数学"], "tasks": [task]}


def test_question_regen_and_append(tmp_path, monkeypatch):
    calls = []
    at = _question_gen_app(tmp_path, monkeypatch, calls)
    _inject_preview(at)
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    keys = {b.key for b in at.button}
    assert "question_regen" in keys and "question_append" in keys
    # 追加：同学科题数从 1 变 2。
    next(b for b in at.button if b.key == "question_append").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    grouped = at.session_state["multi_gen_questions"]
    assert len(grouped["数学"]["valid"]) == 2
    # 重新生成：清旧预览后重新生成 1 条。
    next(b for b in at.button if b.key == "question_regen").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    grouped = at.session_state["multi_gen_questions"]
    assert len(grouped["数学"]["valid"]) == 1


# ---------------------------------------------------------------------------
# 题库批量编辑：AppTest
# ---------------------------------------------------------------------------

def _bank_db_with_one(db_file: Path):
    engine = create_engine(
        f"sqlite:///{db_file.as_posix()}",
        connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    q = _make_question(session, "待批量编辑题干", diff=1, kps=["旧知识点"])
    session.commit()
    qid = q.id
    session.close()
    engine.dispose()
    return qid


def test_bank_batch_edit_app(tmp_path, monkeypatch):
    import modules.lesson_plan as lesson_module
    db_file = tmp_path / "bank.db"
    qid = _bank_db_with_one(db_file)

    def fake_aggrid(df, gridOptions=None, key=None, **kwargs):
        return {
            "data": df,
            "selected_rows": df.head(0)  # 默认无勾选
        }

    # 让假 AgGrid 返回勾选行。
    import pandas as pd
    def fake_aggrid_selected(df, gridOptions=None, key=None, **kwargs):
        rows = df.to_dict("records")
        return {
            "data": df,
            "selected_rows": pd.DataFrame(rows[:1]),
        }

    monkeypatch.setattr(lesson_module, "AgGrid", fake_aggrid_selected)

    at = AppTest.from_string(
        _isolated_app_code(db_file, tmp_path / "feature.json"),
        default_timeout=30)
    at.run()
    goto_top(at, "📚 备课")
    at.session_state["lesson_plan_tab"] = "题库管理"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    # 批量编辑控件出现。
    keys = {x.key for x in at.selectbox}
    assert {"batch_diff", "batch_subject", "batch_grade"} <= keys
    # 设置：难度=拓展，学科=物理，年级=高一，追加知识点。
    next(x for x in at.selectbox if x.key == "batch_diff").set_value(3).run()
    next(x for x in at.selectbox if x.key == "batch_subject").set_value("物理").run()
    next(x for x in at.selectbox if x.key == "batch_grade").set_value("高一").run()
    next(x for x in at.text_input if x.key == "batch_kp").set_value("新知识点").run()
    next(b for b in at.button if b.key == "apply_batch_edit").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    # 回库验证。
    engine = create_engine(f"sqlite:///{db_file.as_posix()}")
    session = sessionmaker(bind=engine)()
    q = session.get(Question, qid)
    assert q.difficulty == 3
    assert q.subject == "物理"
    assert q.grade == "高一"
    assert qs.knowledge_points_list(q) == ["旧知识点", "新知识点"]
    session.close()
    engine.dispose()
