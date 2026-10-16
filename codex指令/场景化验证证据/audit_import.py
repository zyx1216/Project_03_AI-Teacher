# -*- coding: utf-8 -*-
"""审计脚本1：学生/成绩导入兼容性与脏数据容错（只读产品逻辑，不改代码）。"""
from __future__ import annotations
import io
import sys
from pathlib import Path

ROOT = Path(r"D:\Codex\Project_03_AI数学教师工作台")
sys.path.insert(0, str(ROOT))

import pandas as pd
from openpyxl import Workbook

from utils import excel_handler as eh


def make_xlsx(rows, merges=None, sheet="Sheet1") -> io.BytesIO:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    for row in rows:
        ws.append(row)
    for rng in (merges or []):
        ws.merge_cells(rng)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def show(title, df):
    print("=" * 70)
    print("### " + title)
    print("-- 表头:", list(df.columns))
    det = eh.detect_student_columns(df)
    print("-- 学生列识别 mapping:", {k: v for k, v in det["mapping"].items()})
    print("-- problems:", det["problems"])
    recs = eh.extract_students(df, det["mapping"])
    for r in recs:
        print("   ", r)


print("#" * 70)
print("# A. 学生名单导入")
print("#" * 70)

# A1 标准列名
show("A1 标准列名（姓名/学号/班级/性别）",
     eh.load_dataframe(make_xlsx([["姓名", "学号", "班级", "性别"],
                                  ["张三", "1001", "高一1班", "男"],
                                  ["李四", "1002", "高一1班", "女"]])))

# A2 别名混用
show("A2 别名混用（学生姓名/name/行政班/sex）",
     eh.load_dataframe(make_xlsx([["学生姓名", "no", "行政班", "sex"],
                                  ["王五", "2001", "初二3班", "M"],
                                  ["赵六", "2002", "初二3班", "F"]])))

# A3 列序乱 + 多列（冷门字段）
show("A3 列序乱 + 冷门字段（民族/家庭住址/家长联系方式）",
     eh.load_dataframe(make_xlsx([["班级", "家庭住址", "姓名", "民族", "家长联系方式", "性别"],
                                  ["初一2班", "桂林市象山区xx路1号", "孙七", "汉", "13800000000", "男"]])))

# A4 合并单元格（班级纵向合并）
show("A4 合并单元格（班级列 A2:A4 合并）",
     eh.load_dataframe(make_xlsx([["姓名", "班级", "性别"],
                                  ["甲", "高一2班", "男"],
                                  ["乙", None, "女"],
                                  ["丙", None, "男"]],
                                 merges=["B2:B4"])))

# A5 缺姓名列
show("A5 缺姓名列（只有学号/班级）",
     eh.load_dataframe(make_xlsx([["学号", "班级"], ["3001", "初三1班"]])))

# A6 空行/空列脏数据
show("A6 空行 + 空列脏数据",
     eh.load_dataframe(make_xlsx([["姓名", None, "班级"],
                                  [None, None, None],
                                  ["丁", None, "高二1班"],
                                  ["", None, ""],
                                  ["戊", None, "高二1班"]])))


print()
print("#" * 70)
print("# B. 成绩表导入")
print("#" * 70)


def show_scores(title, df):
    print("=" * 70)
    print("### " + title)
    print("-- 表头:", list(df.columns))
    det = eh.detect_score_columns(df)
    print("-- name_col:", det["name_col"], "| class_col:", det["class_col"])
    print("-- subjects:", det["subjects"])
    print("-- problems:", det["problems"])
    try:
        recs = eh.extract_scores(df, det)
        for r in recs:
            print("   ", r)
    except Exception as exc:  # noqa: BLE001
        print("   !! extract_scores 抛异常:", type(exc).__name__, exc)


# B1 标准成绩表（含总分/平均分/排名，应被排除）
show_scores("B1 标准成绩表（含总分/平均分/排名列）",
            eh.load_dataframe(make_xlsx([
                ["姓名", "班级", "语文", "数学", "英语", "总分", "平均分", "名次"],
                ["张三", "高一1班", 88, 92, 85, 265, 88.3, 1],
                ["李四", "高一1班", 76, 64, 80, 220, 73.3, 2]])))

# B2 缺考/空值/异常分数
show_scores("B2 缺考/空值/负分/超范围分（999）",
            eh.load_dataframe(make_xlsx([
                ["姓名", "数学", "语文"],
                ["甲", "缺考", 80],      # 文本缺考
                ["乙", None, 70],        # 空值
                ["丙", -5, 60],          # 负分
                ["丁", 999, 50]])))      # 超范围

# B3 科目列名带后缀 + 英语别名
show_scores("B3 科目带后缀（数学成绩/英语分数/chinese）",
            eh.load_dataframe(make_xlsx([
                ["姓名", "数学成绩", "英语分数", "chinese"],
                ["甲", 90, 88, 77]])))

# B4 长表（姓名/科目/分数）
df_long = eh.load_dataframe(make_xlsx([
    ["姓名", "科目", "分数"],
    ["甲", "数学", 90],
    ["甲", "语文", 80],
    ["乙", "数学", 70]]))
print("=" * 70)
print("### B4 长表（姓名/科目/分数）")
print("-- 表头:", list(df_long.columns))
print("-- parse_long_table:", eh.parse_long_table(df_long))

# B5 非标科目（科学/道德与法治）
show_scores("B5 非标科目（科学 / 道德与法治）",
            eh.load_dataframe(make_xlsx([
                ["姓名", "科学", "道德与法治"],
                ["甲", 85, 90]])))

print()
print("#" * 70)
print("# C. 归一化函数边界")
print("#" * 70)
print("normalize_gender 取值:")
for v in ["男", "男生", "M", "male", "1", "女", "女生", "F", "female", "0", "", None, "未知"]:
    print(f"   {v!r:12} -> {eh.normalize_gender(v)!r}")
print("normalize_subject_name 取值:")
for v in ["数学", "数学成绩", "Math", "数学 成绩", "语 文", "英语分", "科学", "道德与法治", ""]:
    print(f"   {v!r:12} -> {eh.normalize_subject_name(v)!r}")
print("_to_score 取值（含常见脏值）:")
for v in [90, "90", "90分", "", None, -1, "缺考", "未交", "免考", 999, 1e9, "90.5"]:
    print(f"   {v!r:12} -> {eh._to_score(v)!r}")