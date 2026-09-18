# -*- coding: utf-8 -*-
"""
生成阶段 1 验收用的虚构示例数据。

数据规模：2 个班、30 名学生、3 次考试、数学/语文/英语三科（满分均为 100）。
全部为虚构数据（学生01……学生30），不含任何真实个人信息。

产物（写到 data/uploads/demo/，该目录已被 git 忽略）：
- 学生名单.xlsx
- 成绩_第一次月考.xlsx / 成绩_期中考试.xlsx / 成绩_第二次月考.xlsx

运行：
    python scripts/make_demo_data.py
"""

from __future__ import annotations

import random
from datetime import date
from pathlib import Path

import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

SEED = 20260918
SUBJECTS = ["数学", "语文", "英语"]
FULL_SCORE = 100.0

# 三次考试：名称、日期、相对首次考试的整体难度偏移（负=更难，均分更低）
EXAMS = [
    ("第一次月考", date(2026, 9, 28), -2.0),
    ("期中考试", date(2026, 11, 5), 0.0),
    ("第二次月考", date(2026, 12, 22), 3.0),  # 整体略有进步
]

CLASSES = ["八年级1班", "八年级2班"]
STUDENTS_PER_CLASS = 15


def make_students() -> list[dict]:
    """构造 30 名学生的名单。"""
    students = []
    idx = 1
    for class_no, class_name in enumerate(CLASSES, start=1):
        for j in range(1, STUDENTS_PER_CLASS + 1):
            students.append({
                "学号": f"2026{class_no:02d}{j:02d}",
                "姓名": f"学生{idx:02d}",
                "班级": class_name,
                "性别": "男" if idx % 2 == 0 else "女",
            })
            idx += 1
    return students


def make_scores(students: list[dict]) -> dict[str, pd.DataFrame]:
    """
    给每个学生设定能力基准，再按考试波动生成成绩。
    故意制造进步、退步和个别缺考，方便验收趋势、排名和缺分排除。
    """
    rng = random.Random(SEED)
    # 每个学生的各科能力基准（55~95），数学分化大一点
    ability = {}
    for st in students:
        ability[st["姓名"]] = {
            "数学": rng.uniform(52, 96),
            "语文": rng.uniform(60, 92),
            "英语": rng.uniform(55, 94),
        }

    result = {}
    for exam_idx, (exam_name, exam_date, drift) in enumerate(EXAMS):
        rows = []
        for st in students:
            row = {"姓名": st["姓名"], "班级": st["班级"]}
            for subj in SUBJECTS:
                base = ability[st["姓名"]][subj]
                # 随考试次数的个人变化 + 本场波动 + 整场难度偏移
                personal = exam_idx * rng.uniform(-1.5, 2.5)
                noise = rng.gauss(0, 5)
                value = base + personal + noise + drift
                value = max(15.0, min(FULL_SCORE, value))

                # 故意制造 2 个缺考数据点（学生05 的期中数学、学生20 的第二次月考英语）
                if (st["姓名"] == "学生05" and exam_name == "期中考试"
                        and subj == "数学"):
                    row[subj] = None
                elif (st["姓名"] == "学生20" and exam_name == "第二次月考"
                      and subj == "英语"):
                    row[subj] = None
                else:
                    row[subj] = round(value, 1)
            rows.append(row)
        result[exam_name] = pd.DataFrame(rows)
    return result


def main() -> None:
    out_dir = Path(config.UPLOAD_DIR) / "demo"
    out_dir.mkdir(parents=True, exist_ok=True)

    students = make_students()
    pd.DataFrame(students).to_excel(
        out_dir / "学生名单.xlsx", index=False, engine="openpyxl")

    score_tables = make_scores(students)
    for exam_name, df in score_tables.items():
        df.to_excel(out_dir / f"成绩_{exam_name}.xlsx",
                    index=False, engine="openpyxl")

    print(f"示例数据已生成到：{out_dir}")
    print(f"学生 {len(students)} 人，考试 {len(EXAMS)} 场，科目 {SUBJECTS}")


if __name__ == "__main__":
    main()
