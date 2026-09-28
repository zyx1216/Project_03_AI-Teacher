# -*- coding: utf-8 -*-
"""题目相似度查重服务（v2.0.0）。

提供题库相似题查询与入库前查重。相似度为确定性算法：
知识点 Jaccard + 题干字符相似度（difflib），不依赖额外向量库。
结果不写库，不给 questions 表加字段。
"""

from __future__ import annotations

import difflib

from models.models import Question
from utils import question_service

# 知识点相似度、题干相似度的权重
_KP_WEIGHT = 0.45
_CONTENT_WEIGHT = 0.55


def _kp_set(question) -> set[str]:
    """读取题目知识点集合；dict 入参从 knowledge_points JSON 解析。"""
    if isinstance(question, dict):
        raw = question.get("knowledge_points")
        if isinstance(raw, list):
            return {str(x).strip() for x in raw if str(x).strip()}
        return set(question_service.knowledge_points_list(
            _Namespace(raw)))
    return set(question_service.knowledge_points_list(question))


class _Namespace:
    """把 dict 的 knowledge_points 包装成 knowledge_points_list 可读对象。"""
    def __init__(self, raw):
        self.knowledge_points = raw


def _content_of(question) -> str:
    if isinstance(question, dict):
        return str(question.get("content") or "")
    return str(getattr(question, "content", "") or "")


def _kp_jaccard(a: set[str], b: set[str]) -> float:
    """知识点 Jaccard；两边都为空时返回 0（不把双空当相似）。"""
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def similarity_score(a, b) -> float:
    """计算两题相似度（0-1）。"""
    kp_score = _kp_jaccard(_kp_set(a), _kp_set(b))
    content_score = difflib.SequenceMatcher(
        None, _content_of(a), _content_of(b)).ratio()
    return round(
        _KP_WEIGHT * kp_score + _CONTENT_WEIGHT * content_score, 3)


def find_similar(session, question, pool=None, threshold=0.8,
                 limit=5) -> list[dict]:
    """在同学科题库中找相似题；返回 [{question_id, score, reason}]。

    pool 不传时按同学科已审核/全部题构造；question 为 dict 时用其学科过滤。
    """
    subject = None
    if isinstance(question, dict):
        subject = question.get("subject")
    else:
        subject = getattr(question, "subject", None)
    self_id = None if isinstance(question, dict) else getattr(
        question, "id", None)

    if pool is None:
        pool = question_service.list_questions(session, subject=subject)

    results = []
    for candidate in pool:
        if getattr(candidate, "id", None) == self_id:
            continue
        score = similarity_score(question, candidate)
        if score >= threshold:
            shared = sorted(_kp_set(question) & _kp_set(candidate))
            reason = ("共同知识点：" + "、".join(shared) if shared
                      else "题干高度相近")
            results.append({
                "question_id": candidate.id, "score": score,
                "reason": reason})
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:limit]


def duplicate_on_save(session, item, subject=None) -> dict | None:
    """入库前查重；命中阈值返回最相似题，否则 None。

    item 为待入库 dict；subject 不传时取 item.subject，再缺按默认学科。
    """
    data = dict(item)
    data.setdefault("subject", subject)
    matches = find_similar(session, data, threshold=0.8)
    return matches[0] if matches else None
