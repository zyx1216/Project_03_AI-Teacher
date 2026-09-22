# -*- coding: utf-8 -*-
# 生成验收用的虚构示例数据（当前版本：3 个班、90 名学生、10 次考试、9 个学科）。
#
# 语数英满分 150，其余 6 科满分 100。全部为虚构数据（学生01……学生90）。
# 默认运行只（重）写 Excel 到 data/uploads/demo/，不碰数据库；
# 加 --wipe 会先备份完整 data 目录，再清空业务表并写入真实库：
#     python scripts/make_demo_data.py          # 只生成 Excel
#     python scripts/make_demo_data.py --wipe   # 备份、清空业务数据并写示例库

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

SEED = 20260920

# 9 个学科及满分：语数英 150，其余 100
FULL_SCORES = {
    "语文": 150.0, "数学": 150.0, "英语": 150.0,
    "物理": 100.0, "化学": 100.0, "生物": 100.0,
    "政治": 100.0, "历史": 100.0, "地理": 100.0,
}
SUBJECTS = list(FULL_SCORES.keys())

# 一学年 10 次考试：名称、日期、学期、整场难度漂移（按得分率，正=更简单/整体发挥更好）
EXAMS = [
    ("入学摸底", date(2026, 9, 1), "2026-2027学年上", -0.03),
    ("第一次月考", date(2026, 9, 28), "2026-2027学年上", -0.01),
    ("期中考试", date(2026, 11, 5), "2026-2027学年上", 0.00),
    ("第二次月考", date(2026, 12, 22), "2026-2027学年上", 0.02),
    ("期末考试", date(2027, 1, 20), "2026-2027学年上", 0.01),
    ("开学摸底", date(2027, 2, 26), "2026-2027学年下", -0.02),
    ("第一次月考", date(2027, 3, 26), "2026-2027学年下", 0.00),
    ("期中考试", date(2027, 4, 28), "2026-2027学年下", 0.01),
    ("第二次月考", date(2027, 5, 28), "2026-2027学年下", 0.03),
    ("期末考试", date(2027, 6, 28), "2026-2027学年下", 0.04),
]

CLASSES = ["八年级1班", "八年级2班", "八年级3班"]
STUDENTS_PER_CLASS = 30
GRADE = "八年级"


def make_students() -> list[dict]:
    """构造 90 名学生的名单。"""
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


def build_score_matrix(students: list[dict]) -> dict[str, pd.DataFrame]:
    """按各科能力得分率 + 个人趋势 + 波动 + 整场漂移，生成近似正态的成绩宽表。"""
    rng = random.Random(SEED)
    # 每个学生的各科能力基准（得分率 0.45~0.95）和小幅个人趋势
    ability = {}
    personal_slope = {}
    for st in students:
        name = st["姓名"]
        ability[name] = {subj: rng.uniform(0.45, 0.95) for subj in SUBJECTS}
        personal_slope[name] = {subj: rng.uniform(-0.004, 0.012) for subj in SUBJECTS}

    result = {}
    for exam_idx, (exam_name, _exam_date, _term, drift) in enumerate(EXAMS):
        rows = []
        for st in students:
            name = st["姓名"]
            row = {"姓名": name, "班级": st["班级"]}
            for subj in SUBJECTS:
                base = ability[name][subj]
                trend = exam_idx * personal_slope[name][subj]
                noise = rng.gauss(0, 0.05)
                rate = base + trend + noise + drift
                rate = min(1.0, max(0.12, rate))
                row[subj] = round(rate * FULL_SCORES[subj], 1)
            rows.append(row)
        result[exam_name] = pd.DataFrame(rows)
    return result


def write_demo_excel(out_dir) -> Path:
    """把学生名单和 10 场考试成绩写成 Excel，返回输出目录。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 清理上一版成绩文件，避免同名考试改版后留下旧 Excel
    for old_file in out_dir.glob("成绩_*.xlsx"):
        old_file.unlink()

    students = make_students()
    pd.DataFrame(students).to_excel(
        out_dir / "学生名单.xlsx", index=False, engine="openpyxl")
    matrix = build_score_matrix(students)
    for idx, (exam_name, _exam_date, term, _drift) in enumerate(EXAMS, start=1):
        df = matrix[exam_name]
        # 上下学期存在同名考试，文件名带序号和学期，避免互相覆盖
        df.to_excel(out_dir / f"成绩_{idx:02d}_{term}_{exam_name}.xlsx",
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
    for exam_name, exam_date, term, _drift in EXAMS:
        exam = exam_service.create_exam(
            session, exam_name, exam_date=exam_date,
            grade=GRADE, term=term, full_scores=FULL_SCORES)
        df = matrix[exam_name]
        for _, row in df.iterrows():
            student = student_map[row["姓名"]]
            for subj in SUBJECTS:
                session.add(Score(exam_id=exam.id, student_id=student.id,
                                  subject=subj, score=float(row[subj])))
                score_count += 1

    return {"students": len(students), "exams": len(EXAMS),
            "scores": score_count, "absent": 0}


def main() -> None:
    parser = argparse.ArgumentParser(description="生成全科示例数据")
    parser.add_argument("--wipe", action="store_true",
                        help="先备份并清空业务表，再把示例数据写入真实数据库")
    args = parser.parse_args()

    out_dir = Path(config.UPLOAD_DIR) / "demo"
    write_demo_excel(out_dir)
    print(f"示例 Excel 已生成到：{out_dir}")
    print(f"学生 90 人，考试 10 场，科目 {len(SUBJECTS)} 科，缺考 0 处")

    if args.wipe:
        backup_path = backup_service.save_backup_to_disk()
        if not backup_path.exists() or backup_path.stat().st_size == 0:
            raise RuntimeError(f"备份失败或备份文件为空：{backup_path}")

        from utils.db import SessionLocal
        with SessionLocal() as session:
            backup_service.wipe_business_data(session)
            stats = build_demo_data(session)
            session.commit()
        print(f"写入前已备份：{backup_path}")
        print(f"已清空业务表并写入示例数据：{stats}")
    else:
        print("未加 --wipe：只刷新了 Excel，没有改动数据库。")


if __name__ == "__main__":
    main()


