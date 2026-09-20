# -*- coding: utf-8 -*-
# 生成验收用的虚构示例数据（v1.2.4 起为全科 9 科版本）。
#
# 数据规模：2 个班、30 名学生、3 次考试、9 个学科。
# 语数英满分 150，其余 6 科满分 100。全部为虚构数据（学生01……学生30）。
#
# 默认运行只（重）写 Excel 到 data/uploads/demo/，不碰数据库；
# 加 --wipe 才会先清空业务表再把示例数据写入真实库：
#     python scripts/make_demo_data.py          # 只生成 Excel
#     python scripts/make_demo_data.py --wipe   # 清空业务数据并写示例库

from __future__ import annotations

import argparse
import random
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
from models.models import Score
from utils import backup_service, exam_service, student_service

SEED = 20260918

# 9 个学科及满分：语数英 150，其余 100
FULL_SCORES = {
    "语文": 150.0, "数学": 150.0, "英语": 150.0,
    "物理": 100.0, "化学": 100.0, "生物": 100.0,
    "政治": 100.0, "历史": 100.0, "地理": 100.0,
}
SUBJECTS = list(FULL_SCORES.keys())

# 三次考试：名称、日期、整场难度漂移（按得分率，正=更简单/整体进步）
EXAMS = [
    ("第一次月考", date(2026, 9, 28), -0.02),
    ("期中考试", date(2026, 11, 5), 0.0),
    ("第二次月考", date(2026, 12, 22), 0.03),
]

CLASSES = ["八年级1班", "八年级2班"]
STUDENTS_PER_CLASS = 15

# 故意保留的缺考点（学生、考试、科目）
ABSENT_POINTS = [
    ("学生05", "期中考试", "数学"),
    ("学生20", "第二次月考", "英语"),
    ("学生12", "第一次月考", "物理"),
]


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


def _is_absent(name: str, exam_name: str, subject: str) -> bool:
    return (name, exam_name, subject) in ABSENT_POINTS


def build_score_matrix(students: list[dict]) -> dict[str, pd.DataFrame]:
    """按各科能力得分率 + 波动 + 整场漂移，生成近似正态的成绩宽表。"""
    rng = random.Random(SEED)
    # 每个学生的各科能力基准（得分率 0.45~0.95）
    ability = {
        st["姓名"]: {subj: rng.uniform(0.45, 0.95) for subj in SUBJECTS}
        for st in students
    }

    result = {}
    for exam_idx, (exam_name, _exam_date, drift) in enumerate(EXAMS):
        rows = []
        for st in students:
            row = {"姓名": st["姓名"], "班级": st["班级"]}
            for subj in SUBJECTS:
                if _is_absent(st["姓名"], exam_name, subj):
                    row[subj] = None  # 缺考留空
                    continue
                base = ability[st["姓名"]][subj]
                personal = exam_idx * rng.uniform(-0.015, 0.025)
                noise = rng.gauss(0, 0.05)
                rate = base + personal + noise + drift
                rate = min(1.0, max(0.12, rate))
                row[subj] = round(rate * FULL_SCORES[subj], 1)
            rows.append(row)
        result[exam_name] = pd.DataFrame(rows)
    return result


def write_demo_excel(out_dir) -> Path:
    """把学生名单和 3 场考试成绩写成 Excel，返回输出目录。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    students = make_students()
    pd.DataFrame(students).to_excel(
        out_dir / "学生名单.xlsx", index=False, engine="openpyxl")
    for exam_name, df in build_score_matrix(students).items():
        df.to_excel(out_dir / f"成绩_{exam_name}.xlsx",
                    index=False, engine="openpyxl")
    return out_dir


def build_demo_data(session) -> dict:
    """把全科示例数据写入给定 session 的数据库（不自行提交），返回统计。"""
    students = make_students()
    student_map = {}
    for st in students:
        obj, _created = student_service.get_or_create_student(
            session, st["姓名"], st["班级"], student_no=st["学号"])
        if obj.gender is None:
            obj.gender = st["性别"]
        student_map[st["姓名"]] = obj

    matrix = build_score_matrix(students)
    score_count = 0
    absent_count = 0
    for exam_name, exam_date, _drift in EXAMS:
        exam = exam_service.create_exam(
            session, exam_name, exam_date=exam_date,
            grade="八年级", term=exam_name, full_scores=FULL_SCORES)
        df = matrix[exam_name]
        for _, row in df.iterrows():
            student = student_map[row["姓名"]]
            for subj in SUBJECTS:
                value = row[subj]
                if pd.isna(value):
                    session.add(Score(exam_id=exam.id, student_id=student.id,
                                      subject=subj, score=None))
                    absent_count += 1
                else:
                    session.add(Score(exam_id=exam.id, student_id=student.id,
                                      subject=subj, score=float(value)))
                    score_count += 1

    return {"students": len(students), "exams": len(EXAMS),
            "scores": score_count, "absent": absent_count}


def main() -> None:
    parser = argparse.ArgumentParser(description="生成全科示例数据")
    parser.add_argument("--wipe", action="store_true",
                        help="先清空业务表，再把示例数据写入真实数据库")
    args = parser.parse_args()

    out_dir = Path(config.UPLOAD_DIR) / "demo"
    write_demo_excel(out_dir)
    print(f"示例 Excel 已生成到：{out_dir}")
    print(f"学生 30 人，考试 3 场，科目 {len(SUBJECTS)} 科，缺考 {len(ABSENT_POINTS)} 处")

    if args.wipe:
        from utils.db import SessionLocal
        with SessionLocal() as session:
            wiped = backup_service.wipe_business_data(session)
            stats = build_demo_data(session)
            session.commit()
        print(f"已清空 {len(wiped)} 张业务表并写入示例数据：{stats}")
    else:
        print("未加 --wipe：只刷新了 Excel，没有改动数据库。")


if __name__ == "__main__":
    main()
