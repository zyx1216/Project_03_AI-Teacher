# -*- coding: utf-8 -*-
"""智能组卷方案与历史的 JSON 存取。"""

from __future__ import annotations

import json
import uuid
from datetime import datetime

import config

TEMPLATES_PATH = config.DATA_DIR / "smart_compose_templates.json"
HISTORY_PATH = config.DATA_DIR / "smart_compose_history.json"


def _load_json(path) -> list[dict]:
    """文件缺失自建；损坏回退空列表且不覆盖原文件。"""
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except FileNotFoundError:
        _save_json(path, [])
        return []
    except (json.JSONDecodeError, OSError, TypeError, AttributeError):
        return []


def _save_json(path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_matrix_rows(rows) -> list[dict]:
    """归一题型矩阵行。"""
    result = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        type_name = str(row.get("type") or "").strip()
        if not type_name:
            continue
        try:
            easy = int(row.get("easy") or 0)
            medium = int(row.get("medium") or 0)
            hard = int(row.get("hard") or 0)
        except (TypeError, ValueError):
            continue
        if easy < 0 or medium < 0 or hard < 0:
            continue
        result.append({"type": type_name, "easy": easy, "medium": medium, "hard": hard})
    return result


def load_templates() -> list[dict]:
    return _load_json(TEMPLATES_PATH)


def save_templates(rows: list[dict]) -> None:
    _save_json(TEMPLATES_PATH, rows)


def save_template(name: str, subject: str, grade: str, total_score: float,
                  duration: int, rows: list[dict]) -> dict:
    """保存一个组卷方案。"""
    name = str(name or "").strip()
    if not name:
        raise ValueError("请填写方案名称。")
    items = load_templates()
    if any(str(item.get("name") or "") == name for item in items):
        raise ValueError("已存在同名组卷方案，请换个名称。")
    item = {
        "template_id": uuid.uuid4().hex,
        "name": name,
        "subject": subject,
        "grade": grade,
        "total_score": float(total_score),
        "duration": int(duration),
        "rows": normalize_matrix_rows(rows),
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    if not item["rows"]:
        raise ValueError("请先配置题型数量。")
    items.insert(0, item)
    save_templates(items)
    return item


def delete_template(template_id: str) -> list[dict]:
    items = [item for item in load_templates()
             if item.get("template_id") != template_id]
    save_templates(items)
    return items


def load_history() -> list[dict]:
    return _load_json(HISTORY_PATH)


def save_history(rows: list[dict]) -> None:
    _save_json(HISTORY_PATH, rows)


def add_history(subject: str, grade: str, homework_id: int, result: dict) -> dict:
    """追加最近组卷历史，只保留 50 条。"""
    item = {
        "history_id": uuid.uuid4().hex,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "subject": subject,
        "grade": grade,
        "homework_id": int(homework_id),
        "total_questions": int(result.get("total_questions") or 0),
        "rule_picked": int(result.get("rule_picked") or 0),
        "ai_generated": int(result.get("ai_generated") or 0),
        "shortage_count": int(result.get("shortage_count") or 0),
    }
    items = load_history()
    items.insert(0, item)
    save_history(items[:50])
    return item

# ---------------------------------------------------------------------------
# v1.9.2：双向细目表
# ---------------------------------------------------------------------------

DIFFICULTY_NAMES = {1: "基础", 2: "中等", 3: "拓展"}


def _question_kps(question) -> list[str]:
    """读取题目知识点；空知识点归入“未标注”。"""
    from utils import question_service
    kps = question_service.knowledge_points_list(question)
    result = [str(item).strip() for item in kps if str(item).strip()]
    return result or ["未标注"]


def _split_score(score: float, count: int) -> list[float]:
    """把分值均摊到多个知识点，尾差计入第一个知识点。"""
    if count <= 0:
        return []
    part = round(float(score) / count, 2)
    if count == 1:
        return [round(float(score), 2)]
    return [round(float(score) - part * (count - 1), 2)] + [part] * (count - 1)


def build_specification_table(questions: list, question_scores: dict) -> dict:
    """构建“知识点 × 难度”的双向细目表。

    返回 JSON 安全结构，cells 按知识点和难度两级存放。
    """
    difficulties = [{"id": d, "name": DIFFICULTY_NAMES[d]} for d in (1, 2, 3)]
    kp_set: set[str] = set()
    cells: dict[str, dict[int, dict]] = {}

    for question in questions:
        qid = int(question.id)
        score = float((question_scores or {}).get(qid) or 0.0)
        kps = _question_kps(question)
        allocations = _split_score(score, len(kps))
        for kp, allocated_score in zip(kps, allocations):
            kp_set.add(kp)
            row = cells.setdefault(kp, {d: {"count": 0, "score": 0.0,
                                            "question_ids": []}
                                        for d in (1, 2, 3)})
            cell = row[int(question.difficulty)]
            cell["count"] += 1
            cell["score"] = round(cell["score"] + allocated_score, 2)
            cell["question_ids"].append(qid)

    knowledge_points = sorted(kp_set)
    kp_totals: dict[str, dict] = {}
    difficulty_totals = {str(d): {"count": 0, "score": 0.0}
                         for d in (1, 2, 3)}
    total_score = 0.0
    difficulty_question_ids = {d: set() for d in (1, 2, 3)}
    all_question_ids = set()

    for question in questions:
        difficulty_question_ids[int(question.difficulty)].add(int(question.id))
        all_question_ids.add(int(question.id))

    for kp in knowledge_points:
        kp_count = 0
        kp_score = 0.0
        for difficulty in (1, 2, 3):
            cell = cells[kp][difficulty]
            kp_count += cell["count"]
            kp_score = round(kp_score + cell["score"], 2)
            item = difficulty_totals[str(difficulty)]
            item["score"] = round(item["score"] + cell["score"], 2)
        kp_totals[kp] = {"count": kp_count, "score": kp_score}
        total_score = round(total_score + kp_score, 2)

    for difficulty in (1, 2, 3):
        difficulty_totals[str(difficulty)]["count"] = len(
            difficulty_question_ids[difficulty])

    return {
        "knowledge_points": knowledge_points,
        "difficulties": difficulties,
        "cells": {kp: {str(d): cells[kp][d] for d in (1, 2, 3)}
                  for kp in knowledge_points},
        "kp_totals": kp_totals,
        "difficulty_totals": difficulty_totals,
        "total": {"count": len(all_question_ids), "score": total_score},
    }


def get_questions_by_cell(questions: list, knowledge_point: str,
                          difficulty: int) -> list:
    """返回指定知识点和难度格子内的题目。"""
    difficulty = int(difficulty)
    result = []
    for question in questions:
        if int(question.difficulty) != difficulty:
            continue
        if knowledge_point in _question_kps(question):
            result.append(question)
    return result
