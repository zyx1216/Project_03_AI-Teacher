# -*- coding: utf-8 -*-
"""v1.7.3 智能组合并测试。"""

from pathlib import Path

from models.models import Homework
from utils import llm_client
from utils import homework_service as hw_svc
from utils import question_service as qs
from utils import homework_stats as hstat


def _question(session, subject="数学", qtype="choice", diff=1, kps=None, grade=None):
    data = qs.validate_question({
        "content": f"{subject}{qtype}{diff}{kps}{grade}",
        "question_type": qtype,
        "difficulty": diff,
        "answer": "答案",
        "knowledge_points": kps or "通用",
    })
    question = qs.create_question(
        session, data, source="manual", status="approved",
        subject=subject, grade=grade)
    session.flush()
    return question


def test_smart_compose_all_from_bank_without_ai(session, monkeypatch):
    _question(session, qtype="choice", kps="函数")
    _question(session, qtype="choice", kps="方程")

    def _no_ai(*args, **kwargs):
        raise AssertionError("题库足量时不应调用 AI")

    monkeypatch.setattr(hw_svc, "_ai_generate_for_shortage", _no_ai)
    homework = hw_svc.create_homework(session, "智能组卷")
    result = hw_svc.auto_compose(
        session, homework.id,
        {"counts": {"choice": 2}, "difficulty_ratio": {1: 100, 2: 0, 3: 0}},
        ["函数", "方程"])

    assert result["rule_picked"] == 2
    assert result["ai_generated"] == 0
    assert result["shortage_count"] == 0
    assert result["coverage"]["missing"] == []


def test_smart_compose_knowledge_filter(session):
    wanted = _question(session, qtype="choice", kps="函数")
    _question(session, qtype="choice", kps="几何")
    homework = hw_svc.create_homework(session, "知识点过滤")

    result = hw_svc.auto_compose(
        session, homework.id,
        {"counts": {"choice": 1}, "difficulty_ratio": {1: 100, 2: 0, 3: 0}},
        ["函数"], ai_context={"chapters": []})

    pairs = hw_svc.homework_questions(session, homework.id)
    assert result["rule_picked"] == 1
    assert [q.id for _link, q in pairs] == [wanted.id]


def test_smart_compose_ai_context_enters_request(session, monkeypatch):
    captured = {}

    def _fake_chat(system, user, temperature=0.8):
        captured["system"] = system
        captured["user"] = user
        return '''[
            {
                "content": "AI 补题题干",
                "question_type": "choice",
                "difficulty": 1,
                "knowledge_points": ["补题知识点"],
                "answer": "A"
            }
        ]'''

    monkeypatch.setattr(llm_client, "chat_content", _fake_chat)
    homework = hw_svc.create_homework(session, "AI 上下文")
    result = hw_svc.auto_compose(
        session, homework.id,
        {"counts": {"choice": 1}, "difficulty_ratio": {1: 100, 2: 0, 3: 0}},
        ["补题知识点"],
        ai_context={
            "textbook_id": 7,
            "chapters": ["第一单元 混合运算"],
            "grade": None,
        })

    user_text = captured["user"]
    assert "学科：数学" in user_text
    assert "资料ID：7" in user_text
    assert "参考章节：第一单元 混合运算" in user_text
    assert "年级：未指定" in user_text
    assert result["ai_generated"] == 1
    pairs = hw_svc.homework_questions(session, homework.id)
    assert pairs[0][1].status == "pending"


def test_smart_compose_ai_failure_keeps_bank_questions(session, monkeypatch):
    kept = _question(session, qtype="choice", kps="函数")

    def _fail(*args, **kwargs):
        raise RuntimeError("模拟网络失败")

    monkeypatch.setattr(hw_svc, "_ai_generate_for_shortage", _fail)
    homework = hw_svc.create_homework(session, "AI 失败")
    result = hw_svc.auto_compose(
        session, homework.id,
        {"counts": {"choice": 3}, "difficulty_ratio": {1: 100, 2: 0, 3: 0}},
        ["函数"])

    assert result["rule_picked"] == 1
    assert result["shortage_count"] == 2
    pairs = hw_svc.homework_questions(session, homework.id)
    assert [q.id for _link, q in pairs] == [kept.id]


def test_smart_compose_excludes_existing_homework_questions(session, monkeypatch):
    first = _question(session, qtype="choice", kps="函数")
    second = _question(session, qtype="choice", kps="函数")
    homework = hw_svc.create_homework(session, "已有题不重复")
    hw_svc.add_questions(session, homework.id, [first.id])

    def _fail(*args, **kwargs):
        raise RuntimeError("不进入 AI 补缺")

    monkeypatch.setattr(hw_svc, "_ai_generate_for_shortage", _fail)
    result = hw_svc.auto_compose(
        session, homework.id,
        {"counts": {"choice": 2}, "difficulty_ratio": {1: 100, 2: 0, 3: 0}},
        ["函数"])

    pairs = hw_svc.homework_questions(session, homework.id)
    ids = [q.id for _link, q in pairs]
    assert ids == [first.id, second.id]
    assert ids.count(first.id) == 1
    assert result["rule_picked"] == 1
    assert result["shortage_count"] == 1


def test_difficulty_ratio_expands_slots():
    spec = {
        "counts": {"choice": 10},
        "difficulty_ratio": {1: 30, 2: 50, 3: 20},
    }
    slots = hstat.plan_paper_slots(spec)
    counts = {diff: 0 for diff in (1, 2, 3)}
    for slot in slots:
        assert slot["question_type"] == "choice"
        counts[slot["difficulty"]] += 1
    assert counts == {1: 3, 2: 5, 3: 2}


def test_homework_analysis_subject_filter(session):
    math_hw = hw_svc.create_homework(session, "数学作业", subject="数学")
    physics_hw = hw_svc.create_homework(session, "物理作业", subject="物理")

    math_items = hw_svc.list_homeworks(session, subject="数学")
    physics_items = hw_svc.list_homeworks(session, subject="物理")

    assert [item.id for item in math_items] == [math_hw.id]
    assert [item.id for item in physics_items] == [physics_hw.id]


def test_question_bank_grade_filter(session):
    graded = _question(session, qtype="choice", grade="三年级")
    ungraded = _question(session, qtype="choice", grade=None)

    assert [q.id for q in qs.list_questions(session, grade="三年级")] == [graded.id]
    all_items = qs.list_questions(session)
    assert {q.id for q in all_items} == {graded.id, ungraded.id}

def test_create_paper_by_rules_still_available(session):
    question = _question(session, qtype="solution", kps="函数")
    result = hw_svc.create_paper_by_rules(
        session,
        [{"知识点": "函数", "难度": 1, "数量": 1}],
        "旧知识点组卷", per_question_score=10, subject="数学")
    paper = session.get(Homework, result["homework_id"])

    assert paper.homework_type == "exam"
    assert result["question_count"] == 1
    assert [q.id for _link, q in hw_svc.homework_questions(session, paper.id)] == [question.id]


# ---------------------------------------------------------------------------
# AppTest
# ---------------------------------------------------------------------------

def _apptest(db_file: Path, tmp_path: Path):
    from streamlit.testing.v1 import AppTest
    from tests import test_app_smoke as smoke

    return AppTest.from_string(
        smoke._isolated_app_code(db_file, tmp_path / "feature.json"),
        default_timeout=30)


def test_smart_compose_panel_is_available_for_non_exam_isolated(tmp_path):
    from tests import test_app_smoke as smoke

    db_file = tmp_path / "smart_homework.db"
    engine = smoke._seed_homework_data_db(db_file)
    at = _apptest(db_file, tmp_path)
    at.run()
    at.sidebar.radio[0].set_value("📝 学业测评").run()
    assert not at.exception

    analysis_subject = next(
        item for item in at.selectbox if item.key == "homework_analysis_subject")
    analysis_subject.set_value("物理").run()
    list_subject = next(
        item for item in at.selectbox if item.key == "homework_list_subject")
    list_subject.set_value("物理").run()
    assert not at.exception

    next(item for item in at.button if item.key == "open_1").click().run()
    assert not at.exception

    expected = ["从题库选题", "🤖 智能组卷", "AI 即时出题", "外部导入", "手动添加"]
    inner_labels = [item.label for item in at.tabs if item.label in expected]
    assert inner_labels == expected

    select_labels = " ".join(item.label for item in at.selectbox)
    multi_labels = " ".join(item.label for item in at.multiselect)
    slider_labels = " ".join(item.label for item in at.slider)
    assert "选择资料（可选）" in select_labels
    assert "选择知识点（可选，题库和 AI 都按此约束）" in multi_labels
    assert "选择章节（可选，用于约束 AI 补题）" in multi_labels
    assert {"基础占比%", "中等占比%", "拓展占比%"} <= set(slider_labels.split())
    assert any(item.key == "smart_type_rows_1" for item in at.dataframe)
    assert any(item.key == "smart_run_1" for item in at.button)
    assert any(item.key == "bank_grade_1" for item in at.selectbox)
    engine.dispose()


def test_lesson_bank_no_longer_shows_knowledge_paper_isolated(tmp_path):
    db_file = tmp_path / "lesson_bank.db"
    at = _apptest(db_file, tmp_path)
    at.run()
    at.sidebar.radio[0].set_value("📚 备课").run()

    assert not at.exception
    assert not any(item.key == "create_knowledge_paper" for item in at.button)
    all_labels = " ".join(
        [item.value for item in at.markdown] +
        [item.label for item in at.button])
    assert "按知识点组卷" not in all_labels

