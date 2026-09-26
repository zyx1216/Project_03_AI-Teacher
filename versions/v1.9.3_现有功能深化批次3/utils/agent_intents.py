# -*- coding: utf-8 -*-
"""AI 助手意图常量与结构化校验。

v1.9.0 起自然语言助手固定支持 5 类意图。LLM 只负责把老师的话
解析成下面的标准结构，不允许直接返回“已执行”；真正执行走服务层。
"""

from __future__ import annotations

from utils.app_config import (
    DEFAULT_SUBJECT, SUBJECT_NAMES, GRADE_CHOICES,
    to_storage_grade, is_valid_subject,
)

# 5 类意图
COMPOSE_PAPER = "compose_paper"      # 出题、组卷
PREPARE_LESSON = "prepare_lesson"    # 备课
ANALYZE_STUDENT = "analyze_student"  # 学生成绩/趋势分析
QUERY = "query"                      # 作业截止、题库数量等查询
MULTI_STEP = "multi_step"            # 需要拆解的复合任务

INTENTS = [COMPOSE_PAPER, PREPARE_LESSON, ANALYZE_STUDENT, QUERY, MULTI_STEP]

INTENT_HINTS = {
    COMPOSE_PAPER: "出题、组卷，例如：数学高一，函数选择题5道基础题",
    PREPARE_LESSON: "备课，例如：帮我备一节初二物理《光的反射》",
    ANALYZE_STUDENT: "分析学生成绩或趋势，例如：分析张三最近两次数学考试",
    QUERY: "查询事实，例如：题库里有多少道题，最近有哪些作业要截止",
    MULTI_STEP: "复合任务，例如：备这节课并生成配套作业",
}

# 四类内部题型（与 auto_compose 槽位口径一致）
SLOT_TYPES = {"choice": "选择题", "fill": "填空题",
              "judge": "判断题", "solution": "解答题"}
# 中文题型 -> 内部值（支持常见简称）
TYPE_TO_SLOT = {
    "选择题": "choice", "单选题": "choice", "单选": "choice", "选择": "choice",
    "填空题": "fill", "填空": "fill",
    "判断题": "judge", "判断": "judge",
    "解答题": "solution", "解答": "solution", "计算题": "solution",
}
DIFFICULTY_WORDS = {"基础": 1, "中等": 2, "拓展": 3, "难": 3}


def empty_intent() -> dict:
    """空意图结构。"""
    return {
        "intent": "",
        "params": {
            "subject": DEFAULT_SUBJECT,
            "grade": "",            # 界面口径，如 高一
            "chapter": "",
            "knowledge_points": [],
            "question_type": "",    # 内部值 choice/fill/judge/solution
            "count": 0,
            "difficulty": 0,        # 1/2/3，0 表示不限
            "student_name": "",
            "time_range": "",
            "topic": "",
        },
    }


def normalize_intent(raw: dict) -> dict:
    """把 LLM 返回的意图字典归一化并做基本校验。

    非法意图直接抛 ValueError，由上层转成中文提示；不静默兜底成 query。
    """
    if not isinstance(raw, dict):
        raise ValueError("解析结果格式不正确。")
    intent = str(raw.get("intent") or "").strip()
    if intent not in INTENTS:
        raise ValueError(f"无法识别的指令类型：{intent or '空'}")

    src = raw.get("params") if isinstance(raw.get("params"), dict) else {}

    def text(key):
        return str(src.get(key) or "").strip()

    # 学科
    subject = text("subject") or DEFAULT_SUBJECT
    if subject not in SUBJECT_NAMES:
        subject = DEFAULT_SUBJECT

    # 年级：LLM 返回界面口径；非法年级清空
    grade = text("grade")
    if grade and grade not in GRADE_CHOICES and not _is_display_grade(grade):
        grade = ""

    # 题型：允许中文或内部值
    qtype_raw = text("question_type")
    qtype = ""
    if qtype_raw:
        key = qtype_raw.lower().replace(" ", "")
        if key in SLOT_TYPES:
            qtype = key
        elif qtype_raw in TYPE_TO_SLOT:
            qtype = TYPE_TO_SLOT[qtype_raw]

    # 难度
    difficulty = src.get("difficulty")
    try:
        difficulty = int(difficulty)
    except (TypeError, ValueError):
        dw = text("difficulty")
        difficulty = DIFFICULTY_WORDS.get(dw, 0)
    if difficulty not in (0, 1, 2, 3):
        difficulty = 0

    # 数量
    try:
        count = int(src.get("count") or 0)
    except (TypeError, ValueError):
        count = 0
    count = max(0, count)

    kps = src.get("knowledge_points") or []
    if isinstance(kps, str):
        import re
        kps = [x.strip() for x in re.split(r"[，,、;；]\s*", kps) if x.strip()]
    kps = [str(x).strip() for x in kps if str(x).strip()]

    return {
        "intent": intent,
        "params": {
            "subject": subject,
            "grade": grade,
            "chapter": text("chapter"),
            "knowledge_points": kps,
            "question_type": qtype,
            "count": count,
            "difficulty": difficulty,
            "student_name": text("student_name"),
            "time_range": text("time_range"),
            "topic": text("topic"),
        },
    }


def _is_display_grade(grade: str) -> bool:
    """兼容 LLM 返回界面年级（初一/高一）的情况。"""
    return grade in ("初一", "初二", "初三", "高一", "高二", "高三")


def storage_grade(params: dict) -> str:
    """从参数取数据库存储年级；未指定/为空返回空串。"""
    grade = params.get("grade") or ""
    return to_storage_grade(grade) if grade else ""
