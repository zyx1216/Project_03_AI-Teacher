# -*- coding: utf-8 -*-
"""题目质量审核服务（v2.0.0）。

提供单题/批量质量审核与一键修复。质量分为确定性算法：
没配置 chat_func 时按规则扣分；配置了 chat_func 时由 LLM 评判再归一。
结果不写库，按当次缓存使用，不给 questions 表加字段。
"""

from __future__ import annotations

import json

from utils import question_service


def _rule_audit(question) -> dict:
    """确定性规则审核：按硬伤逐项扣分，返回质量分与问题清单。"""
    score = 100
    issues, suggestions = [], []

    answer = (getattr(question, "answer", None) or "").strip()
    if not answer:
        score -= 40
        issues.append("答案为空")
        suggestions.append("补充标准答案")

    kps = question_service.knowledge_points_list(question)
    if not kps:
        score -= 20
        issues.append("未标注知识点")
        suggestions.append("标注考察知识点")

    content = (getattr(question, "content", None) or "").strip()
    if len(content) < 5:
        score -= 20
        issues.append("题干过短，可能不完整")
        suggestions.append("补全题干表述")

    difficulty = getattr(question, "difficulty", None)
    if difficulty not in (1, 2, 3):
        score -= 20
        issues.append("难度取值非法")
        suggestions.append("把难度归一为 1-3")

    analysis = (getattr(question, "analysis", None) or "").strip()
    if not analysis:
        score -= 10
        suggestions.append("补充解题解析，便于学生自学")

    score = max(0, score)
    return {
        "passed": score >= 80 and not issues,
        "score": score,
        "issues": issues,
        "suggestions": _dedup(suggestions),
    }


def _dedup(items) -> list[str]:
    """保序去重。"""
    result = []
    for item in items:
        if item and item not in result:
            result.append(item)
    return result


def _normalize_llm(raw: dict, fallback: dict) -> dict:
    """把 LLM 返回归一为 {passed, score, issues, suggestions}。"""
    if not isinstance(raw, dict):
        return fallback
    try:
        score = int(raw.get("score", fallback["score"]))
    except (TypeError, ValueError):
        score = fallback["score"]
    score = max(0, min(100, score))
    issues = _dedup([str(x) for x in raw.get("issues", [])])
    suggestions = _dedup([str(x) for x in raw.get("suggestions", [])])
    passed = bool(raw.get("passed", score >= 80 and not issues))
    return {"passed": passed, "score": score,
            "issues": issues, "suggestions": suggestions}


def audit_question(question, chat_func=None) -> dict:
    """审核单题。chat_func(system, user) 返回 JSON 字符串；异常时回退规则。"""
    fallback = _rule_audit(question)
    if chat_func is None:
        return fallback
    system = (
        "你是中小学命题质量审核专家。只依据题目内容评判，"
        "检查知识点是否超纲、难度是否匹配年级、题干是否清晰无歧义、"
        "答案是否准确、解析是否完整。")
    user = (
        f"题型：{getattr(question, 'question_type', '')}\n"
        f"年级：{getattr(question, 'grade', '')}\n"
        f"题干：{getattr(question, 'content', '')}\n"
        f"答案：{getattr(question, 'answer', '')}\n"
        f"解析：{getattr(question, 'analysis', '')}\n"
        f"知识点：{getattr(question, 'knowledge_points', '')}\n"
        "只输出 JSON："
        '{"passed": true/false, "score": 0-100, '
        '"issues": [], "suggestions": []}')
    try:
        data = json.loads(chat_func(system, user))
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback
    return _normalize_llm(data, fallback)


def batch_audit(questions, chat_func=None) -> list[dict]:
    """批量审核；单题异常不阻断整批。"""
    results = []
    for question in questions:
        try:
            results.append(audit_question(question, chat_func=chat_func))
        except Exception:
            results.append({"passed": False, "score": 0,
                            "issues": ["审核异常"], "suggestions": []})
    return results


def repair_question(question, audit, chat_func) -> dict | None:
    """按审核建议生成修复后的题目 dict（不改库），再过现有校验。

    chat_func 不可用或返回非法时返回 None。
    """
    if chat_func is None:
        return None
    system = (
        "你是中小学命题修复专家。只根据审核问题修改题目，"
        "保持原有数学结构，输出修复后的完整题目 JSON。")
    suggestions = "；".join(audit.get("suggestions", []))
    user = (
        f"原题题干：{getattr(question, 'content', '')}\n"
        f"原题答案：{getattr(question, 'answer', '')}\n"
        f"原题解析：{getattr(question, 'analysis', '')}\n"
        f"知识点：{getattr(question, 'knowledge_points', '')}\n"
        f"需要修复：{suggestions}\n"
        "只输出 JSON："
        '{"content": "", "question_type": "choice/fill/judge/solution", '
        '"difficulty": 1-3, "knowledge_points": [], '
        '"answer": "", "analysis": ""}')
    try:
        data = json.loads(chat_func(system, user))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return question_service.validate_question(data)
