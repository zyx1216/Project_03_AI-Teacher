# -*- coding: utf-8 -*-
"""v1.7.1 Prompt 学科通用化测试。"""

from pathlib import Path

from utils import app_config, material_service


PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"


def test_question_prompt_is_subject_general():
    text = (PROMPT_DIR / "question_prompt.txt").read_text(encoding="utf-8")

    assert "数学命题专家" not in text
    assert "命制高质量的数学题" not in text
    assert "数学公式" not in text
    assert "中小学各学科命题专家" in text
    assert "学科、年级、知识点、题型、难度和数量" in text
    assert "理科公式" in text
    assert "语文、英语、政治、历史、地理等文科题目不需要公式" in text
    assert "小学" in text and "初中" in text and "高中" in text


def test_question_prompt_limits_verify_to_science_formulas():
    text = (PROMPT_DIR / "question_prompt.txt").read_text(encoding="utf-8")

    assert "verify 字段只能在数学、物理、化学等有明确算式" in text
    assert "能用 SymPy 验证" in text
    assert "阅读理解、作文、材料分析" in text


def test_lesson_prompt_is_subject_general():
    text = (PROMPT_DIR / "lesson_plan_prompt.txt").read_text(encoding="utf-8")

    assert "数学教师" not in text
    assert "数学教案" not in text
    assert "数学公式" not in text
    assert "中小学各学科教师" in text
    assert "学科、课题、学情和参考资料" in text
    assert "理科公式" in text
    assert "例题 / 范文 / 实验演示" in text
    assert "小学" in text and "初中" in text and "高中" in text


def test_lesson_prompt_has_stage_differences():
    text = (PROMPT_DIR / "lesson_plan_prompt.txt").read_text(encoding="utf-8")

    assert "小学教案要生动有趣" in text
    assert "初中教案要注重" in text
    assert "高中教案要注重知识深度" in text


def test_high_school_textbook_grade_detection():
    assert app_config.detect_grade_from_title("高中化学必修一") == "高一"
    assert app_config.detect_grade_from_title("高中化学必修1") == "高一"
    assert app_config.detect_grade_from_title("高中生物必修二") == "高二"
    assert app_config.detect_grade_from_title("高中生物必修2") == "高二"
    assert app_config.detect_grade_from_title("高中地理必修三") == "高三"
    assert app_config.detect_grade_from_title("高中地理必修3") == "高三"
    assert app_config.detect_grade_from_title("英语选择性必修") == "高三"


def test_material_general_heading_rules_exclude_math_fun():
    source = Path(material_service.__file__).read_text(encoding="utf-8")

    assert "数学好玩" not in source
    assert not material_service.is_chapter_heading("数学好玩")
    chapters = material_service.split_chapters("数学好玩\n相关内容。")
    assert not any(chapter["title"] == "数学好玩" for chapter in chapters)
