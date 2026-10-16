# -*- coding: utf-8 -*-
"""审计脚本3：题型 × 学段 / 学科 匹配（只读产品逻辑）。"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(r"D:\Codex\Project_03_AI数学教师工作台")
sys.path.insert(0, str(ROOT))

from utils import question_service as qs
from utils.app_config import SUBJECT_NAMES, DISPLAY_GRADE_CHOICES, to_storage_grade

print("学科清单:", SUBJECT_NAMES)
print("界面年级:", [g for g in DISPLAY_GRADE_CHOICES if g != "未指定"])
print()

SAMPLES = [
    ("小学低段", "三年级"),
    ("小学高段", "六年级"),
    ("初中", "八年级"),
    ("高中", "高一"),
]
print("#" * 70)
print("# 各学科 × 学段 可用题型（界面口径 -> 存储口径）")
print("#" * 70)
matrix = {}
for subject in SUBJECT_NAMES:
    print("=" * 70)
    print(f"## {subject}")
    for label, display_grade in SAMPLES:
        storage = to_storage_grade(display_grade)
        types = qs.question_type_options(storage, subject)
        matrix[(subject, label)] = types
        print(f"  [{label} {display_grade}->{storage}] {len(types)} 种: " + "、".join(types))

print()
print("#" * 70)
print("# 重点规则核查")
print("#" * 70)

def has(subject, label, keyword):
    return any(keyword in t for t in matrix.get((subject, label), []))

checks = [
    ("小学英语不应有听力", not has("英语", "小学低段", "听力") and not has("英语", "小学高段", "听力")),
    ("高中英语应有听力", has("英语", "高中", "听力")),
    ("小学语文应有看图写话/作文", has("语文", "小学低段", "看图写话")),
    ("初中数学应有解答/证明", has("数学", "初中", "解答") or has("数学", "初中", "证明")),
    ("高中数学应有解答", has("数学", "高中", "解答")),
    ("初中物理（按文档应无）", bool(matrix.get(("物理", "初中")))),
    ("初中化学（按文档应无）", bool(matrix.get(("化学", "初中")))),
    ("初中生物（按文档应无）", bool(matrix.get(("生物", "初中")))),
    ("初中政治（按文档应无）", bool(matrix.get(("政治", "初中")))),
]
for name, ok in checks:
    print(f"  [{'符合预期' if ok else '不符'}] {name}")

print()
print("空结果检查（任何组合返回空列表都算异常）:")
empty = [(s, l) for (s, l), v in matrix.items() if not v]
print("   ", empty or "无空结果")

print()
print("小学英语题型明细:", matrix.get(("英语", "小学低段")))
print("高中英语题型明细:", matrix.get(("英语", "高中")))
print("初中物理题型明细:", matrix.get(("物理", "初中")))
print("初中政治题型明细:", matrix.get(("政治", "初中")))