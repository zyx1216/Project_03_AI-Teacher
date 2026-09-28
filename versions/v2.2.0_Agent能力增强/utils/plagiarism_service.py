# -*- coding: utf-8 -*-
"""作业答案抄袭检测服务（v2.1.0）。"""

from __future__ import annotations

from difflib import SequenceMatcher
import re


def normalize_answer_text(value) -> str:
    """归一化答案：统一小写、去标点和多余空白。"""
    text = str(value or "").lower()
    text = re.sub(r"[，。！？；：、“”‘’\"'`~!@#$%^&*()_\-+=\[\]{}|\\/<>《》\s]+", "", text)
    return text


def answer_similarity(text_a, text_b) -> float:
    """计算两份答案的相似度，范围 0~1。"""
    a = normalize_answer_text(text_a)
    b = normalize_answer_text(text_b)
    if not a or not b:
        return 0.0
    if len(a) < 8 or len(b) < 8:
        return 0.0
    return round(SequenceMatcher(None, a, b).ratio(), 4)


def detect_plagiarism(rows, threshold=0.8) -> dict:
    """检测两两答案相似度，超过阈值标记疑似抄袭。"""
    clean_rows = []
    for row in rows or []:
        name = str(row.get("student_name", "")).strip()
        answer = str(row.get("answer", "")).strip()
        if name and answer:
            clean_rows.append({"student_name": name, "answer": answer})

    pairs = []
    for i, row_a in enumerate(clean_rows):
        for row_b in clean_rows[i + 1:]:
            score = answer_similarity(row_a["answer"], row_b["answer"])
            if score > float(threshold):
                pairs.append({
                    "student_a": row_a["student_name"],
                    "student_b": row_b["student_name"],
                    "similarity": score,
                    "answer_a": row_a["answer"][:180],
                    "answer_b": row_b["answer"][:180],
                })

    pairs.sort(key=lambda item: item["similarity"], reverse=True)
    lines = [
        f"{item['student_a']} 与 {item['student_b']}："
        f"相似度 {item['similarity'] * 100:.1f}%"
        for item in pairs
    ]
    return {
        "pairs": pairs,
        "report": "未发现疑似抄袭。" if not pairs else "\n".join(lines),
    }
