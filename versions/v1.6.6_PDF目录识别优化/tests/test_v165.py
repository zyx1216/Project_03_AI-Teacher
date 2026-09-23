# -*- coding: utf-8 -*-
"""v1.6.5：通用教案模板、出题任务栏服务测试。"""

import json
from pathlib import Path

import pytest

from utils import question_service as qs
from utils import template_service


@pytest.fixture()
def lesson_template_path(tmp_path, monkeypatch):
    path = tmp_path / "lesson_templates.json"
    monkeypatch.setattr(template_service, "LESSON_TEMPLATES_PATH", path)
    monkeypatch.setattr(template_service, "_CORRUPT", set())
    monkeypatch.setattr(template_service, "_MEMORY", {})
    return path


@pytest.fixture()
def tasks_path(tmp_path, monkeypatch):
    path = tmp_path / "question_tasks.json"
    monkeypatch.setattr(qs, "QUESTION_TASKS_PATH", path)
    return path


# ---------------------------------------------------------------------------
# 教案模板
# ---------------------------------------------------------------------------

def test_builtin_lesson_template_only_general(lesson_template_path):
    assert list(template_service.BUILTIN_LESSON_TEMPLATES) == ["通用模板"]
    content = template_service.BUILTIN_LESSON_TEMPLATES["通用模板"]
    for text in (
        "知识与技能", "过程与方法", "情感态度与价值观",
        "教学重点", "教学难点", "教学准备",
        "导入新课", "讲授新知", "课堂练习", "课堂小结", "作业布置",
        "板书设计", "教学反思",
    ):
        assert text in content

    names = [item["name"] for item in template_service.list_lesson_templates()]
    assert names == ["通用模板"]


def test_old_builtin_lesson_templates_are_filtered(lesson_template_path):
    lesson_template_path.write_text(
        json.dumps({
            "templates": [
                {"name": "通用模板", "content": "旧通用", "builtin": True},
                {"name": "语文模板", "content": "旧语文", "builtin": True},
                {"name": "数学模板", "content": "旧数学", "builtin": True},
                {"name": "我的模板", "content": "自定义正文", "builtin": False},
            ]
        }, ensure_ascii=False),
        encoding="utf-8")

    items = template_service.list_lesson_templates()
    assert [item["name"] for item in items] == ["通用模板", "我的模板"]
    assert template_service.lesson_template_content("语文模板") == ""
    assert template_service.lesson_template_content("我的模板") == "自定义正文"


def test_saving_custom_template_cleans_old_builtins(lesson_template_path):
    lesson_template_path.write_text(
        json.dumps({
            "templates": [
                {"name": "语文模板", "content": "旧语文", "builtin": True},
                {"name": "数学模板", "content": "旧数学", "builtin": True},
                {"name": "我的模板", "content": "自定义正文", "builtin": False},
            ]
        }, ensure_ascii=False),
        encoding="utf-8")

    template_service.save_custom_lesson_template("新模板", "新正文")
    raw = json.loads(lesson_template_path.read_text(encoding="utf-8"))
    names = [item["name"] for item in raw["templates"]]
    assert names == ["我的模板", "新模板"]
    assert "语文模板" not in names and "数学模板" not in names


# ---------------------------------------------------------------------------
# 出题任务 JSON
# ---------------------------------------------------------------------------

def test_question_tasks_missing_auto_create(tasks_path):
    assert qs.load_question_tasks() == []
    assert tasks_path.exists()


def test_question_tasks_save_chinese_not_escaped(tasks_path):
    task = qs.normalize_question_task({
        "subject": "数学", "grade": "初一", "question_type": "选择题",
        "difficulty": 2, "count": 3, "knowledge_points": ["有理数"],
    })
    qs.save_question_tasks([task])
    raw = tasks_path.read_text(encoding="utf-8")
    assert "有理数" in raw and "\\u" not in raw
    loaded = qs.load_question_tasks()
    assert loaded[0]["count"] == 3
    assert loaded[0]["storage_type"] == "choice"


def test_question_tasks_corrupt_file_falls_back_without_overwrite(tasks_path):
    tasks_path.write_text("{损坏", encoding="utf-8")
    assert qs.load_question_tasks() == []
    assert tasks_path.read_text(encoding="utf-8") == "{损坏"


def test_normalize_question_task_defaults_and_shape():
    task = qs.normalize_question_task({
        "subject": "语文", "grade": "三年级", "question_type": "作文",
        "difficulty": "难", "count": "2", "extra": "贴近生活",
        "knowledge_points": ["看图写话"],
    })
    assert set(task) == {
        "task_id", "subject", "grade", "question_type", "storage_type",
        "difficulty", "count", "material_id", "knowledge_points", "extra",
        "selected", "created_at",
    }
    assert task["subject"] == "语文"
    assert task["grade"] == "三年级"
    assert task["question_type"] == "作文题"
    assert task["storage_type"] == "solution"
    assert task["difficulty"] == 3
    assert task["count"] == 2
    assert task["material_id"] is None
    assert task["selected"] is True
    assert task["task_id"] and task["created_at"]


@pytest.mark.parametrize("field,value,match", [
    ("subject", "体育", "学科不合法"),
    ("grade", "大十二", "年级不合法"),
    ("question_type", "火星题型", "题型不符合"),
    ("count", 0, "数量必须大于 0"),
    ("knowledge_points", [], "知识点不能为空"),
])
def test_normalize_question_task_rejects_bad_data(field, value, match):
    data = {
        "subject": "数学", "grade": "初二", "question_type": "选择题",
        "difficulty": 2, "count": 1, "knowledge_points": ["函数"],
    }
    data[field] = value
    with pytest.raises(ValueError, match=match):
        qs.normalize_question_task(data)


def test_add_delete_and_clear_question_tasks(tasks_path):
    first = qs.normalize_question_task({
        "subject": "数学", "grade": "初一", "question_type": "选择题",
        "knowledge_points": ["有理数"], "count": 1,
    })
    second_data = {
        "subject": "语文", "grade": "三年级", "question_type": "填空题",
        "knowledge_points": ["字词"], "count": 2,
    }
    saved = qs.add_question_tasks([first, second_data])
    assert len(saved) == 2
    assert saved[0]["task_id"] == first["task_id"]
    assert saved[1]["task_id"] != first["task_id"]

    remaining = qs.delete_question_tasks([first["task_id"], "missing"])
    assert [task["task_id"] for task in remaining] == [saved[1]["task_id"]]
    assert qs.clear_question_tasks() == []
    assert qs.load_question_tasks() == []


def test_add_question_tasks_rejects_duplicate_id(tasks_path):
    task = qs.normalize_question_task({
        "subject": "数学", "grade": "初一", "question_type": "选择题",
        "knowledge_points": ["有理数"], "count": 1,
    })
    qs.add_question_tasks([task])
    with pytest.raises(ValueError, match="任务 ID 已存在"):
        qs.add_question_tasks([task])


def test_tasks_from_drafts_expands_each_subject_and_task():
    drafts = {
        "数学": {
            "tasks": [
                {"question_type": "选择题", "storage_type": "choice",
                 "difficulty": 1, "count": 2},
                {"question_type": "证明题", "storage_type": "solution",
                 "difficulty": 3, "count": 1},
            ],
            "material_id": 7, "knowledge_points": ["几何"], "extra": "画图",
        },
        "语文": {
            "tasks": [{"question_type": "阅读理解", "storage_type": "solution",
                       "difficulty": 2, "count": 1}],
            "material_id": None, "knowledge_points": ["散文"], "extra": "",
        },
    }

    tasks = qs.tasks_from_drafts(drafts, "初二")
    assert len(tasks) == 3
    assert [task.subject if False else task["subject"] for task in tasks[:2]] == ["数学", "数学"]
    assert tasks[0]["grade"] == tasks[2]["grade"] == "初二"
    assert tasks[0]["material_id"] == 7
    assert tasks[2]["material_id"] is None
    assert tasks[1]["question_type"] == "证明题"
    assert tasks[1]["storage_type"] == "solution"
    assert tasks[0]["knowledge_points"] == ["几何"]


def test_question_task_request_text_uses_own_grade_and_subject():
    task = qs.normalize_question_task({
        "subject": "英语", "grade": "高一", "question_type": "填空题",
        "difficulty": 2, "count": 4, "knowledge_points": ["定语从句"],
        "extra": "语境真实",
    })
    text = qs.question_task_request_text(task)
    assert "学科：英语" in text
    assert "年级：高一" in text
    assert "填空题" in text
    assert "定语从句" in text
    assert "语境真实" in text


# ---------------------------------------------------------------------------
# v1.6.5 AppTest：任务栏添加、删除、混合生成、入库、历史恢复
# ---------------------------------------------------------------------------

from streamlit.testing.v1 import AppTest  # noqa: E402
from tests.test_app_smoke import _isolated_app_code  # noqa: E402


def _question_app(tmp_path: Path):
    db_file = tmp_path / "question_tasks_ui.db"
    feature_file = tmp_path / "question_tasks_feature.json"
    feature_file.write_text(
        '{"question_gen_subject": "数学", "question_bank_subject": "数学"}',
        encoding="utf-8")
    at = AppTest.from_string(
        _isolated_app_code(
            db_file, feature_file,
            question_tasks_file=tmp_path / "question_tasks.json"),
        default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("📚 备课").run()
    return at, db_file, tmp_path / "question_tasks.json"


def test_app_add_question_tasks_for_different_subject_and_grade(tmp_path):
    at, _, tasks_file = _question_app(tmp_path)

    # 第一条：初一数学选择题。
    grade = next(x for x in at.selectbox if x.key == "question_gen_grade")
    grade.set_value("初一").run()
    at.session_state["question_gen_manual_kps"] = "有理数"
    at.run()
    add_btn = next(b for b in at.button if b.key == "add_current_question_tasks")
    add_btn.click()
    at.session_state["question_task_editor"] = {
        "edited_rows": {},
        "added_rows": [{"题型": "选择题", "难度": 1, "数量": 2}],
        "deleted_rows": [],
    }
    at.run()
    assert not at.exception, [str(e) for e in at.exception]

    saved = json.loads(tasks_file.read_text(encoding="utf-8"))
    assert len(saved) == 1
    assert saved[0]["subject"] == "数学"
    assert saved[0]["grade"] == "初一"
    assert saved[0]["knowledge_points"] == ["有理数"]

    # 第二条：三年级语文作文题。
    at.sidebar.radio[0].set_value("📚 备课").run()
    grade = next(x for x in at.selectbox if x.key == "question_gen_grade")
    grade.set_value("三年级").run()
    subject = next(x for x in at.radio if x.key == "question_gen_subject")
    subject.set_value("语文").run()
    at.session_state["question_gen_manual_kps"] = "看图写话"
    at.run()
    add_btn = next(b for b in at.button if b.key == "add_current_question_tasks")
    add_btn.click()
    at.session_state["question_task_editor"] = {
        "edited_rows": {},
        "added_rows": [{"题型": "作文", "难度": 2, "数量": 1}],
        "deleted_rows": [],
    }
    at.run()
    assert not at.exception, [str(e) for e in at.exception]

    saved = json.loads(tasks_file.read_text(encoding="utf-8"))
    assert len(saved) == 2
    assert saved[1]["subject"] == "语文"
    assert saved[1]["grade"] == "三年级"
    assert saved[1]["question_type"] == "作文题"
    assert saved[1]["storage_type"] == "solution"


def test_app_delete_and_clear_question_tasks(tmp_path):
    at, _, tasks_file = _question_app(tmp_path)
    qs.save_question_tasks([
        {
            "task_id": "t1", "subject": "数学", "grade": "初一",
            "question_type": "选择题", "difficulty": 1, "count": 1,
            "knowledge_points": ["有理数"],
        },
        {
            "task_id": "t2", "subject": "语文", "grade": "三年级",
            "question_type": "填空题", "difficulty": 2, "count": 1,
            "knowledge_points": ["字词"],
        },
    ])
    at.run()

    # 模拟只勾选第一行；AppTest 不运行 AgGrid，直接写 data_editor 状态。
    delete_btn = next(b for b in at.button if b.key == "delete_question_tasks")
    delete_btn.click()
    at.session_state["question_task_bar"] = {
        "edited_rows": {
            "0": {"勾选": True},
            "1": {"勾选": False},
        },
        "added_rows": [],
        "deleted_rows": [],
    }
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    saved = json.loads(tasks_file.read_text(encoding="utf-8"))
    assert [item["task_id"] for item in saved] == ["t2"]

    next(b for b in at.button if b.key == "clear_all_question_tasks").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    assert json.loads(tasks_file.read_text(encoding="utf-8")) == []


def test_app_generate_mixed_tasks_preview_save_and_restore_history(
        tmp_path, monkeypatch):
    from utils import llm_client
    from sqlalchemy import create_engine, text

    at, db_file, tasks_file = _question_app(tmp_path)
    qs.save_question_tasks([
        {
            "task_id": "math1", "subject": "数学", "grade": "初一",
            "question_type": "选择题", "difficulty": 1, "count": 1,
            "knowledge_points": ["有理数"],
        },
        {
            "task_id": "chinese1", "subject": "语文", "grade": "三年级",
            "question_type": "填空题", "difficulty": 2, "count": 1,
            "knowledge_points": ["字词"],
        },
    ])

    def fake_chat(system_prompt, user_prompt, temperature=0.8):
        if "学科：数学" in user_prompt:
            return json.dumps([{
                "content": "数学题：初一有理数",
                "question_type": "选择题",
                "difficulty": 1,
                "answer": "A",
                "knowledge_points": ["有理数"],
            }], ensure_ascii=False)
        return json.dumps([{
            "content": "语文题：三年级字词",
            "question_type": "填空题",
            "difficulty": 2,
            "answer": "春",
            "knowledge_points": ["字词"],
        }], ensure_ascii=False)

    monkeypatch.setattr(llm_client, "chat_content", fake_chat)
    at.run()
    generate_btn = next(
        b for b in at.button
        if b.key == "generate_selected_question_tasks")
    generate_btn.click()
    at.session_state["question_task_bar"] = {
        "edited_rows": {},
        "added_rows": [],
        "deleted_rows": [],
    }
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    markdown = " ".join(str(x.value) for x in at.markdown)
    assert "数学题：初一有理数" in markdown
    assert "语文题：三年级字词" in markdown

    next(b for b in at.button if b.key == "save_multi_questions").click().run()
    assert not at.exception, [str(e) for e in at.exception]

    eng = create_engine(f"sqlite:///{db_file.as_posix()}")
    with eng.connect() as conn:
        rows = conn.execute(text(
            "SELECT subject, content FROM questions ORDER BY id"
        )).fetchall()
    assert rows == [
        ("数学", "数学题：初一有理数"),
        ("语文", "语文题：三年级字词"),
    ]
    eng.dispose()

    # 出题历史“带回配置”应写回 question_tasks.json，而不是自动生成。
    history_path = tmp_path / "question_history.json"
    item = json.loads(history_path.read_text(encoding="utf-8"))["items"][-1]
    at.session_state[f"restore_history_{item['id']}"] = True
    next(b for b in at.button
         if b.key == f"restore_history_{item['id']}").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    restored = json.loads(tasks_file.read_text(encoding="utf-8"))
    assert len(restored) == 2
    assert restored[0]["grade"] == "初一"
    assert restored[1]["subject"] == "语文"

