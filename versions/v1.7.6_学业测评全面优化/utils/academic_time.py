# -*- coding: utf-8 -*-
"""按考试日期推导学期、学年、考试类型和趋势图唯一标签。"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from typing import Iterable, Mapping

AUTUMN = "秋"
SPRING = "春"
EXAM_TYPES = ["摸底", "月考", "期中", "期末", "其他"]


def semester_key(value: date) -> tuple[int, str]:
    """返回 (学年开始年份, 秋/春)；9 月至次年 1 月为秋，2 至 8 月为春。"""
    if value.month >= 9:
        return value.year, AUTUMN
    if value.month <= 1:
        return value.year - 1, AUTUMN
    return value.year, SPRING


def semester_name(value: date) -> str:
    """如 2026秋、2027春。"""
    year, season = semester_key(value)
    return f"{year}{season}"


def short_semester_name(value: date) -> str:
    """如 26秋、27春。"""
    year, season = semester_key(value)
    return f"{year % 100:02d}{season}"


def academic_year_name(value: date) -> str:
    """如 2026-2027学年；春季属于上一年秋季开始的学年。"""
    start_year, season = semester_key(value)
    if season == SPRING:
        start_year -= 1
    return f"{start_year}-{start_year + 1}学年"


def semester_order(value: date) -> tuple[int, int]:
    """学期排序键：先秋后备春，如 2026秋、2027春。"""
    start_year, season = semester_key(value)
    return start_year, 0 if season == AUTUMN else 1


def exam_type(name: str | None) -> str:
    """按考试名称关键词识别类型；无法识别归为其他。"""
    text = str(name or "")
    for kind in ("摸底", "月考", "期中", "期末"):
        if kind in text:
            return kind
    return "其他"


def unique_exam_labels(exams: Iterable[object] | Mapping[int, object]) -> dict[int, str]:
    """
    给考试生成趋势图唯一标签：26秋·第一次月考。

    同一学期同名考试追加序号；输入可以是 Exam 对象列表，也可以是
    {exam_id: {"date": date, "name": str}} 字典。
    """
    if isinstance(exams, Mapping):
        items = []
        for exam_id, item in exams.items():
            exam_date = item.get("exam_date") or item.get("date")
            items.append((int(exam_id), item.get("name") or "", exam_date))
    else:
        items = [
            (int(getattr(e, "id")), getattr(e, "name", ""), getattr(e, "exam_date", None))
            for e in exams
        ]

    grouped: dict[tuple[str, str], list[int]] = defaultdict(list)
    label_info: dict[int, tuple[str, str]] = {}
    for exam_id, name, exam_date in items:
        if not isinstance(exam_date, date):
            continue
        semester = short_semester_name(exam_date)
        key = (semester, str(name))
        grouped[key].append(exam_id)
        label_info[exam_id] = (semester, str(name))

    duplicate_ids = {
        exam_id
        for ids in grouped.values()
        if len(ids) > 1
        for exam_id in ids
    }
    seen = Counter()
    result = {}
    # 日期升序编号，显示顺序也稳定。
    for exam_id, _name, exam_date in sorted(items, key=lambda x: (x[2] or date.min, x[0])):
        semester, name = label_info[exam_id]
        base = f"{semester}·{name}"
        if exam_id not in duplicate_ids:
            result[exam_id] = base
            continue
        seen[(semester, name)] += 1
        result[exam_id] = f"{base}({seen[(semester, name)]})"
    return result
