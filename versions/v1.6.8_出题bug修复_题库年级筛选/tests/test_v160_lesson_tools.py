# -*- coding: utf-8 -*-
"""v1.6.0 备课区服务层测试：模板、出题任务、历史、知识点组卷、PPT 主题。"""

import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from models.models import Homework
from utils import homework_service
from utils import lesson_service
from utils import ppt_generator
from utils import question_history_service as history_svc
from utils import question_service
from utils import template_service


@pytest.fixture()
def template_paths(tmp_path, monkeypatch):
    lesson_path = tmp_path / "lesson_templates.json"
    ppt_path = tmp_path / "ppt_templates.json"
    ppt_dir = tmp_path / "ppt"
    monkeypatch.setattr(template_service, "LESSON_TEMPLATES_PATH", lesson_path)
    monkeypatch.setattr(template_service, "PPT_TEMPLATES_PATH", ppt_path)
    monkeypatch.setattr(template_service, "PPT_TEMPLATE_DIR", ppt_dir)
    monkeypatch.setattr(template_service, "_CORRUPT", set())
    monkeypatch.setattr(template_service, "_MEMORY", {})
    return {
        "lesson": lesson_path,
        "ppt": ppt_path,
        "ppt_dir": ppt_dir,
    }


def test_lesson_template_defaults_and_custom_save(template_paths):
    names = [item["name"] for item in template_service.list_lesson_templates()]
    assert names == ["通用模板"]

    template_service.save_custom_lesson_template("复习课模板", "先回顾，再练习。")
    names = [item["name"] for item in template_service.list_lesson_templates()]
    assert "复习课模板" in names

    raw = template_paths["lesson"].read_text(encoding="utf-8")
    assert "复习课模板" in raw and "\\u" not in raw


def test_lesson_template_corrupt_json_falls_back(template_paths):
    path = template_paths["lesson"]
    path.write_text("{坏JSON", encoding="utf-8")

    assert template_service.list_lesson_templates() == []
    template_service.save_custom_lesson_template("临时模板", "正文")
    assert path.read_text(encoding="utf-8") == "{坏JSON"
    assert template_service.lesson_template_content("临时模板") == "正文"


def test_save_lesson_template_rejects_empty_or_builtin_name(template_paths):
    with pytest.raises(ValueError, match="名称不能为空"):
        template_service.save_custom_lesson_template("", "正文")
    with pytest.raises(ValueError, match="内容不能为空"):
        template_service.save_custom_lesson_template("模板", "")
    with pytest.raises(ValueError, match="内置模板名称"):
        template_service.save_custom_lesson_template("通用模板", "正文")


def _pptx_bytes() -> bytes:
    prs = ppt_generator._new_presentation()
    ppt_generator._blank_slide(prs)
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def test_ppt_template_defaults_validate_and_save_custom(template_paths):
    names = [item["name"] for item in template_service.list_ppt_templates()]
    assert names == ["简约", "教育", "商务"]

    with pytest.raises(ValueError, match="不是有效的 PPTX"):
        template_service.validate_pptx(b"not pptx")

    file_bytes = _pptx_bytes()
    template_service.save_custom_ppt_template("我的模板", file_bytes)
    items = template_service.list_ppt_templates()
    assert any(item["name"] == "我的模板" for item in items)
    saved_file = template_paths["ppt_dir"] / "我的模板.pptx"
    assert saved_file.read_bytes()[:2] == b"PK"


def test_question_type_mapping():
    assert question_service.question_type_options("六年级", "数学") == [
        "选择题", "填空题", "判断题", "计算题", "操作题", "应用题", "图形与几何题"]
    assert question_service.question_type_options("八年级", "数学") == [
        "选择题", "填空题", "计算题", "解答题", "证明题", "应用题", "作图题"]
    assert question_service.question_type_options("八年级", "语文") == [
        "字音字形", "词语运用", "病句辨析与修改", "语句衔接与排序", "标点符号",
        "文学常识与名著阅读", "古诗文默写", "文言文阅读", "古代诗歌鉴赏",
        "现代文阅读", "语言文字运用", "作文"]
    assert question_service.question_type_options("八年级", "政治") == [
        "选择题", "简答题", "材料分析题", "辨析题", "实践探究题"]
    assert question_service.question_type_options("八年级", "历史") == [
        "选择题", "材料分析题", "简答题", "论述题", "识图题"]


def test_question_generation_task_validation():
    rows = [
        {"题型": "选择题", "难度": 1, "数量": 2},
        {"题型": "证明题", "难度": 3, "数量": 1},
    ]
    result = question_service.validate_generation_tasks(
        rows, ["选择题", "证明题"])
    assert result == [
        {"question_type": "选择题", "storage_type": "choice",
         "difficulty": 1, "count": 2},
        {"question_type": "证明题", "storage_type": "solution",
         "difficulty": 3, "count": 1},
    ]

    with pytest.raises(ValueError, match="题型不符合"):
        question_service.validate_generation_tasks(
            [{"题型": "作文题", "难度": 1, "数量": 1}], ["选择题"])
    with pytest.raises(ValueError, match="必须大于 0"):
        question_service.validate_generation_tasks(
            [{"题型": "选择题", "难度": 1, "数量": 0}], ["选择题"])
    with pytest.raises(ValueError, match="必须是整数"):
        question_service.validate_generation_tasks(
            [{"题型": "选择题", "难度": 1, "数量": ""}], ["选择题"])


def test_question_history_add_restore_and_limit(tmp_path, monkeypatch):
    path = tmp_path / "history.json"
    monkeypatch.setattr(history_svc, "HISTORY_PATH", path)
    monkeypatch.setattr(history_svc, "_CORRUPT", False)
    monkeypatch.setattr(history_svc, "_MEMORY", {})

    assert history_svc.list_history() == []
    for i in range(51):
        item = history_svc.add_history(
            {"grade": "八年级", "subjects": ["数学"], "index": i}, i)
    items = history_svc.list_history()
    assert len(items) == 50
    assert items[0]["config"]["index"] == 1
    assert history_svc.restore_config(item["id"])["index"] == 50
    with pytest.raises(ValueError, match="出题历史不存在"):
        history_svc.restore_config("missing")


def _make_approved_question(session, knowledge_point, qid):
    data = question_service.validate_question({
        "content": f"题目{qid}",
        "question_type": "solution",
        "difficulty": 2,
        "knowledge_points": knowledge_point,
        "answer": "答案",
    })
    question = question_service.create_question(
        session, data, source="manual", status="approved", subject="数学")
    session.flush()
    return question


def test_create_paper_by_rules_success(session):
    question = _make_approved_question(session, "函数", 1)
    rules = [{"知识点": "函数", "难度": 2, "数量": 1}]

    result = homework_service.create_paper_by_rules(
        session, rules, "函数测试", 10, "数学")
    session.commit()

    hw = session.get(Homework, result["homework_id"])
    assert hw.homework_type == "exam"
    assert result == {
        "homework_id": hw.id,
        "question_count": 1,
        "total_score": 10.0,
    }
    assert hw.questions[0].question_id == question.id


def test_create_paper_by_rules_shortage_does_not_create(session):
    rules = [{"知识点": "函数", "难度": 2, "数量": 2}]

    with pytest.raises(ValueError, match="题量不足，未创建试卷"):
        homework_service.create_paper_by_rules(
            session, rules, "不应创建的试卷", 10, "数学")
    session.commit()
    assert session.query(Homework).count() == 0


def test_generate_ppt_builtin_themes():
    lesson = SimpleNamespace(
        title="函数课", grade="八年级", chapter="函数")
    plan = lesson_service.empty_plan()

    for theme in ("简约", "教育", "商务"):
        data = ppt_generator.generate_ppt(lesson, plan, theme_name=theme)
        assert data[:2] == b"PK"


def test_generate_ppt_with_custom_template(template_paths):
    template_service.save_custom_ppt_template("自定义", _pptx_bytes())
    info = next(item for item in template_service.list_ppt_templates()
                 if item["name"] == "自定义")
    template_file = Path(info["file"])

    lesson = SimpleNamespace(title="自定义模板课", grade="八年级", chapter="")
    data = ppt_generator.generate_ppt(
        lesson, lesson_service.empty_plan(),
        theme_name="自定义模板", custom_template_path=str(template_file))

    from pptx import Presentation
    prs = Presentation(io.BytesIO(data))
    assert len(prs.slides) >= 1
