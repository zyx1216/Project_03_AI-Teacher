# -*- coding: utf-8 -*-
"""教案服务测试：JSON 解析修复、归一化、存读、列表删除、Word 导出。"""

import io
import json

from utils import lesson_service as ls
from models.models import LessonPlan


def test_empty_plan_structure():
    plan = ls.empty_plan()
    stages = [p["stage"] for p in plan["process"]]
    assert stages == ["导入", "新授", "巩固练习", "课堂小结", "作业布置"]
    assert set(plan["objectives"]) == {"knowledge", "process", "emotion"}


def test_strip_code_fence():
    assert ls.strip_code_fence("```json\n{\"a\": 1}\n```") == '{"a": 1}'


def test_parse_with_fence_and_garbage():
    payload = "好的，教案如下：\n```json\n" + json.dumps({
        "教学目标": {"知识与技能": "学会", "过程与方法": "探究", "情感态度与价值观": "兴趣"},
        "教学重点": "重点", "教学难点": "难点",
        "教学过程": {"导入": "复习旧知", "新授": "讲解新知"},
        "板书设计": "主板书", "教学反思": "注意节奏",
    }, ensure_ascii=False) + "\n```\n以上。"
    plan = ls.parse_lesson_plan(payload)
    assert plan is not None
    assert plan["objectives"]["knowledge"] == "学会"
    assert plan["key_points"] == "重点"
    assert plan["difficult_points"] == "难点"
    assert plan["board_design"] == "主板书"
    assert plan["reflection"] == "注意节奏"
    # 缺的环节补空，识别到的环节保留
    stages = [p["stage"] for p in plan["process"]]
    assert "导入" in stages and "新授" in stages


def test_parse_unparseable_returns_none():
    assert ls.parse_lesson_plan("完全不是 JSON 的一堆字") is None


def test_save_load_list_delete(session):
    plan = ls.empty_plan()
    plan["key_points"] = "测试重点"
    lesson = ls.save_plan(session, "测试课题", plan, grade="九年级",
                          chapter="第21章", source="课本")
    session.commit()
    assert lesson.id is not None

    loaded = ls.load_plan(session.get(LessonPlan, lesson.id))
    assert loaded["key_points"] == "测试重点"
    assert len(ls.list_plans(session)) == 1

    # 更新同一条
    plan["key_points"] = "改过的重点"
    ls.save_plan(session, "测试课题", plan, plan_id=lesson.id)
    session.commit()
    assert ls.load_plan(session.get(LessonPlan, lesson.id))["key_points"] == "改过的重点"
    assert len(ls.list_plans(session)) == 1

    ls.delete_plan(session, lesson.id)
    session.commit()
    assert ls.list_plans(session) == []


def test_export_word_has_sections(session):
    plan = ls.empty_plan()
    plan["process"][0]["content"] = "教师提问：同学们好"
    lesson = ls.save_plan(session, "Word 导出课题", plan)
    session.commit()
    data = ls.export_word(lesson, plan)
    from docx import Document
    text = "\n".join(p.text for p in Document(io.BytesIO(data)).paragraphs)
    for heading in ["Word 导出课题", "教学目标", "教学重点", "教学难点",
                    "教学过程", "板书设计", "教学反思预设", "教师提问：同学们好"]:
        assert heading in text