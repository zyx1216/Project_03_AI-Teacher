# -*- coding: utf-8 -*-
"""AI 助手意图常量与结构化校验。

v1.9.0 起自然语言助手固定支持 5 类业务意图。v1.9.4 新增修正意图，
修正只基于最近生成结果，不改变“业务执行必须走服务层”的原则。
"""

from __future__ import annotations

import re

from utils.app_config import (
    DEFAULT_SUBJECT, SUBJECT_NAMES, GRADE_CHOICES,
    to_storage_grade, is_valid_subject,
)

# 5 类业务意图
COMPOSE_PAPER = "compose_paper"      # 出题、组卷
PREPARE_LESSON = "prepare_lesson"    # 备课
ANALYZE_STUDENT = "analyze_student"  # 学生成绩/趋势分析
QUERY = "query"                      # 作业截止、题库数量等查询
MULTI_STEP = "multi_step"            # 需要拆解的复合任务
RAG_QUERY = "rag_query"              # 基于课本资料的检索问答
CORRECTION = "correction"            # 基于最近结果的修正

INTENTS = [COMPOSE_PAPER, PREPARE_LESSON, ANALYZE_STUDENT, QUERY, MULTI_STEP, RAG_QUERY]

INTENT_HINTS = {
    COMPOSE_PAPER: "出题、组卷，例如：数学高一，函数选择题5道基础题",
    PREPARE_LESSON: "备课，例如：帮我备一节初二物理《光的反射》",
    ANALYZE_STUDENT: "分析学生成绩或趋势，例如：分析张三最近两次数学考试",
    QUERY: "查询事实，例如：题库里有多少道题，最近有哪些作业要截止",
    MULTI_STEP: "复合任务，例如：备这节课并生成配套作业",
    RAG_QUERY: "从课本资料里找答案，例如：从课本里找一下函数的定义",
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

_CORRECTION_VERBS = ("改", "修改", "调整", "换成", "替换", "增加", "加", "删除", "删掉", "去掉", "再看看")


def empty_intent() -> dict:
    """空业务意图结构。"""
    return {
        "intent": "",
        "params": {
            "subject": DEFAULT_SUBJECT,
            "grade": "",             # 界面口径，如 高一
            "class_name": "",
            "chapter": "",
            "knowledge_points": [],
            "question_type": "",     # 内部值 choice/fill/judge/solution
            "count": 0,
            "difficulty": 0,         # 1/2/3，0 表示不限
            "student_name": "",
            "time_range": "",
            "topic": "",
        },
    }


def normalize_intent(raw: dict) -> dict:
    """把 LLM 返回的意图字典归一化并做基本校验。"""
    if not isinstance(raw, dict):
        raise ValueError("解析结果格式不正确。")
    intent = str(raw.get("intent") or "").strip()
    if intent not in INTENTS:
        raise ValueError(f"无法识别的指令类型：{intent or '空'}")

    src = raw.get("params") if isinstance(raw.get("params"), dict) else {}

    def text(key):
        return str(src.get(key) or "").strip()

    subject = text("subject") or DEFAULT_SUBJECT
    if subject not in SUBJECT_NAMES:
        subject = DEFAULT_SUBJECT

    grade = text("grade")
    if grade and grade not in GRADE_CHOICES and not _is_display_grade(grade):
        grade = ""

    qtype_raw = text("question_type")
    qtype = ""
    if qtype_raw:
        key = qtype_raw.lower().replace(" ", "")
        if key in SLOT_TYPES:
            qtype = key
        elif qtype_raw in TYPE_TO_SLOT:
            qtype = TYPE_TO_SLOT[qtype_raw]

    difficulty = src.get("difficulty")
    try:
        difficulty = int(difficulty)
    except (TypeError, ValueError):
        dw = text("difficulty")
        difficulty = DIFFICULTY_WORDS.get(dw, 0)
    if difficulty not in (0, 1, 2, 3):
        difficulty = 0

    try:
        count = int(src.get("count") or 0)
    except (TypeError, ValueError):
        count = 0
    count = max(0, count)

    kps = src.get("knowledge_points") or []
    if isinstance(kps, str):
        kps = [x.strip() for x in re.split(r"[，,、;；]\s*", kps) if x.strip()]
    kps = [str(x).strip() for x in kps if str(x).strip()]

    return {
        "intent": intent,
        "params": {
            "subject": subject,
            "grade": grade,
            "class_name": text("class_name"),
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


# ---------------------------------------------------------------------------
# v1.9.4：多轮修正
# ---------------------------------------------------------------------------

def is_correction_instruction(text: str, last_result: dict | None) -> bool:
    """判断一句话是否为基于最近结果的修正指令。"""
    content = str(text or "").strip()
    if not content or not isinstance(last_result, dict):
        return False
    artifact = last_result.get("artifact")
    if not isinstance(artifact, dict) or not artifact.get("artifact_type"):
        return False
    if not any(verb in content for verb in _CORRECTION_VERBS):
        return False
    if not (re.search(r"第?\d+\s*[题道个]", content) or
            _has_section_word(content, artifact.get("artifact_type"))):
        return False
    # “出一道改写句子题”是新指令，不能误判。
    if content.startswith(("出", "生成", "帮我出", "请出")) and not re.search(r"第?\d+\s*[题道]", content):
        return False
    return True


def parse_correction(text: str, last_result: dict) -> dict:
    """解析修正指令；无法定位目标时按普通指令兜底。"""
    content = str(text or "").strip()
    artifact = (last_result or {}).get("artifact") or {}
    artifact_type = artifact.get("artifact_type") or ""
    targets = _target_indexes(content)
    qtype = _question_type(content)

    if any(word in content for word in ("删掉", "删除", "去掉")):
        action = "remove"
    elif qtype and any(word in content for word in ("换成", "替换", "改成")):
        action = "replace"
    elif any(word in content for word in ("增加", "加")):
        action = "add"
    elif artifact_type == "analysis" and "再看看" in content:
        action = "change_analysis"
    else:
        action = "revise"

    count_match = re.search(r"(\d+)\s*[道个]", content)
    count = int(count_match.group(1)) if count_match else 0
    return {
        "intent": CORRECTION,
        "action": action,
        "artifact_type": artifact_type,
        "targets": targets,
        "question_type": qtype,
        "count": count,
        "instruction": content,
    }


def _target_indexes(text: str) -> list[int]:
    """提取“第2题、3题”的 1 基序号。"""
    indexes = []
    for match in re.finditer(r"第?(\d+)\s*[题道个]", text):
        index = int(match.group(1))
        if index > 0 and index not in indexes:
            indexes.append(index)
    return indexes


def _question_type(text: str) -> str:
    """识别修正中的题型。"""
    for label, value in (("选择题", "choice"), ("填空题", "fill"),
                         ("判断题", "judge"), ("解答题", "solution")):
        if label in text:
            return value
    return ""


def _has_section_word(text: str, artifact_type: str) -> bool:
    """识别教案或分析中的常见修正位置。"""
    lesson_words = ("目标", "重点", "难点", "活动", "板书", "过程", "导入", "小结")
    analysis_words = ("趋势", "数学", "语文", "英语", "物理", "化学", "上次", "上一次")
    words = lesson_words if artifact_type == "lesson_plan" else analysis_words
    return artifact_type == "homework" and any(word in text for word in ("难度", "题干", "答案", "题")) or any(word in text for word in words)

# ---------------------------------------------------------------------------
# v1.9.5：复杂度分级
# ---------------------------------------------------------------------------

SIMPLE = "simple"          # 查询类，一句话能回答
SINGLE = "single"          # 单步任务
MULTI_STEP_LEVEL = "multi_step"  # 现有固定复合任务
COMPLEX = "complex"        # 需自主规划、先确认再执行

_COMPLEX_MARKERS = (
    "下周", "下一周", "期末复习卷", "复习卷", "改进方案", "整套",
    "一整套", "全套", "这一周的课", "下周的课", "这个学期", "单元复习",
)
_QUERY_MARKERS = ("多少", "几个", "几条", "哪些", "有没有", "查一下", "名单", "数量")


def classify_complexity(text: str) -> str:
    """把一句话分成 simple/single/multi_step/complex 四级。

    - simple：纯查询；
    - complex：需要自主拆解、先出计划等确认的模糊复合任务；
    - multi_step：现有两类固定复合任务（备课+作业 / 分析+反思）；
    - single：其余单步任务。
    """
    content = str(text or "").strip()
    if not content:
        return SIMPLE

    if any(marker in content for marker in _COMPLEX_MARKERS):
        return COMPLEX

    # 固定复合任务的显式表达；“备这节课/备一节课”也算备课动作。
    has_lesson = ("备课" in content or "教案" in content
                  or __import__("re").search(r"备.{0,3}课", content) is not None)
    has_homework = ("作业" in content or "出题" in content or "组卷" in content)
    has_analysis = "分析" in content
    has_reflection = "反思" in content
    if has_lesson and has_homework and not content.startswith(("根据教案",)):
        return MULTI_STEP_LEVEL
    if has_analysis and has_reflection:
        return MULTI_STEP_LEVEL

    # “帮我准备/分析……并……”这类带并列动作的也算复合。
    if "并" in content and (has_lesson or has_analysis) and (
            has_homework or "改进" in content or "建议" in content):
        return COMPLEX

    is_query = any(marker in content for marker in _QUERY_MARKERS)
    if is_query and not (has_lesson or has_homework):
        return SIMPLE
    return SINGLE


