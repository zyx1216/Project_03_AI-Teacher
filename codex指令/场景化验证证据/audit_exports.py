# -*- coding: utf-8 -*-
"""审计脚本4：导出样张生成与格式检查（只读产品逻辑，不改代码）。"""
from __future__ import annotations
import io
import sys
from datetime import date
from pathlib import Path

ROOT = Path(r"D:\Codex\Project_03_AI数学教师工作台")
OUT = ROOT / ".tmp_audit"
sys.path.insert(0, str(ROOT))

import pymupdf
from docx import Document
from openpyxl import load_workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models.models import (
    Base, Exam, Homework, HomeworkQuestion, LessonPlan, Question, Score, Student,
)
from utils import exam_service, export_service, homework_service
from utils import lesson_service as lesson_svc
from utils import parent_report_service as prs
from utils import student_report_service as srs


def build_session():
    db = OUT / "audit.db"
    if db.exists():
        db.unlink()
    eng = create_engine(f"sqlite:///{db.as_posix()}",
                        connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    s1 = Student(name="张三", class_name="高一1班", gender="男", student_no="1001")
    s2 = Student(name="李四", class_name="高一1班", gender="女", student_no="1002")
    exam = Exam(name="高一数学期中考试", exam_date=date.today(),
                grade="十年级", term="2026秋",
                full_scores='{"数学": 150, "语文": 150}')
    session.add_all([s1, s2, exam])
    session.flush()
    session.add_all([
        Score(exam_id=exam.id, student_id=s1.id, subject="数学", score=132,
              class_rank=1, grade_rank=6),
        Score(exam_id=exam.id, student_id=s1.id, subject="语文", score=118,
              class_rank=2, grade_rank=20),
        Score(exam_id=exam.id, student_id=s2.id, subject="数学", score=88,
              class_rank=2, grade_rank=60),
        Score(exam_id=exam.id, student_id=s2.id, subject="语文", score=105,
              class_rank=1, grade_rank=40),
    ])
    qs = [
        Question(content="下列函数中，定义域为 R 的是（  ）\nA. $y=1/x$  B. $y=\\sqrt{x}$  C. $y=x^2$  D. $y=\\ln x$",
                 question_type="choice", answer="C", analysis="略",
                 subject="数学", grade="十年级", difficulty=1, status="approved",
                 knowledge_points='["函数"]'),
        Question(content="已知 $f(x)=2x+1$，则 $f(3)=$ ______。",
                 question_type="fill", answer="7", analysis="代入",
                 subject="数学", grade="十年级", difficulty=2, status="approved",
                 knowledge_points='["函数"]'),
        Question(content="解方程：$x^2-5x+6=0$，并说明每一步依据。",
                 question_type="solution", answer="x=2 或 x=3", analysis="因式分解",
                 subject="数学", grade="十年级", difficulty=3, status="approved",
                 knowledge_points='["方程"]'),
    ]
    session.add_all(qs)
    session.flush()
    hw = Homework(name="第一章 函数单元测试卷", homework_type="exam",
                  class_name="高一1班", subject="数学", grade="十年级",
                  total_score=100, duration=90, status="pending")
    session.add(hw)
    session.flush()
    for i, q in enumerate(qs, start=1):
        session.add(HomeworkQuestion(homework_id=hw.id, question_id=q.id,
                                     order=i, score=[4, 6, 12][i - 1]))
    plan = lesson_svc.empty_plan()
    plan["objectives"] = {"knowledge": "理解函数概念", "process": "体会对应关系",
                          "emotion": "培养严谨态度"}
    plan["key_points"] = "函数三要素"
    plan["difficult_points"] = "定义域的理解"
    plan["process"] = [
        {"stage": "导入", "minutes": 5, "content": "用生活实例引入变量关系。"},
        {"stage": "新授", "minutes": 25, "content": "讲解函数定义与三要素。"},
        {"stage": "练习", "minutes": 10, "content": "完成课本例题 1-3。"},
        {"stage": "小结", "minutes": 3, "content": "归纳本节课要点。"},
        {"stage": "作业", "minutes": 2, "content": "课本习题 1、2 题。"},
    ]
    plan["board_design"] = "函数：定义 → 三要素 → 表示法"
    plan["reflection"] = "学生对定义域理解偏弱，下节课需加强。"
    plan["subject"] = "数学"
    lesson = lesson_svc.save_plan(session, "函数的概念", plan, grade="十年级",
                                  chapter="函数", source="人教版必修一",
                                  subject="数学")
    session.commit()
    return session, hw, lesson, qs, exam, s1, s2


def docx_info(data: bytes, label: str) -> dict:
    doc = Document(io.BytesIO(data))
    fonts, sizes = set(), set()
    for p in doc.paragraphs:
        for r in p.runs:
            if r.font.name:
                fonts.add(r.font.name)
            if r.font.size:
                sizes.add(round(r.font.size.pt, 1))
    for t in doc.tables:
        for row in t.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    for r in p.runs:
                        if r.font.name:
                            fonts.add(r.font.name)
                        if r.font.size:
                            sizes.add(round(r.font.size.pt, 1))
    body = "\n".join(p.text for p in doc.paragraphs)
    table_text = "\n".join(c.text for t in doc.tables for row in t.rows
                           for c in row.cells)
    all_text = body + "\n" + table_text
    info = {
        "label": label,
        "字数": len(all_text),
        "段落数": len(doc.paragraphs),
        "表格数": len(doc.tables),
        "字体": sorted(f for f in fonts if f),
        "字号": sorted(sizes),
        "含密封线": "密封" in all_text,
        "含得分栏": "得分" in all_text,
        "含注意事项": "注意事项" in all_text,
        "含考生信息": all(k in all_text for k in ("姓名", "班级")),
        "含分值": "分" in all_text,
        "含教学反思": "反思" in all_text,
        "含板书": "板书" in all_text,
    }
    print("=" * 70)
    print(f"### {label}")
    for k, v in info.items():
        if k != "label":
            print(f"    {k}: {v}")
    return info


def pdf_info(pdf_bytes: bytes, label: str, png: str) -> dict:
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        pages = doc.page_count
        text = doc[0].get_text()
        pix = doc[0].get_pixmap(dpi=110)
        pix.save(str(OUT / png))
        size = (round(doc[0].rect.width), round(doc[0].rect.height))
    print("=" * 70)
    print(f"### {label}")
    print(f"    页数: {pages} | 首页尺寸(pt): {size} | 渲染图: {png}")
    print(f"    首页文本前 120 字: {text[:120]!r}")
    return {"页数": pages, "尺寸": size}


session, hw, lesson, qs, exam, s1, s2 = build_session()

print("#" * 70)
print("# 1. 教案 Word（lesson_service.export_word）")
print("#" * 70)
plan = lesson_svc.load_plan(lesson)
lesson_docx = lesson_svc.export_word(lesson, plan)
(OUT / "lesson.docx").write_bytes(lesson_docx)
docx_info(lesson_docx, "教案 Word")

print()
print("#" * 70)
print("# 2. 试卷 Word —— 路径A：homework_service.export_word（现有主路径）")
print("#" * 70)
hw_docx = homework_service.export_word(session, hw.id, with_answer=False)
(OUT / "exam_pathA.docx").write_bytes(hw_docx)
docx_info(hw_docx, "试卷 Word（路径A：export_word）")

print()
print("#" * 70)
print("# 3. 试卷 Word —— 路径B：export_service.standard_exam_docx（v3.4.0 新增）")
print("#" * 70)
pairs = homework_service.homework_questions(session, hw.id)
std_docx = export_service.standard_exam_docx(
    hw, pairs, school="桂林电子科技大学附属中学", header="第一章 函数单元测试卷",
    footer="第 1 页 共 2 页")
(OUT / "exam_pathB.docx").write_bytes(std_docx)
docx_info(std_docx, "试卷 Word（路径B：standard_exam_docx）")

print()
print("#" * 70)
print("# 4. 试卷 LaTeX（export_service.homework_latex）")
print("#" * 70)
latex = export_service.homework_latex(hw, pairs)
print(latex[:600])
print("    -> 含密封线:", "密封" in latex, "| 含分值:", "分" in latex,
      "| 含得分栏:", "得分" in latex)

print()
print("#" * 70)
print("# 5. 成绩 Excel（exam_service.build_score_report_xlsx）")
print("#" * 70)
xlsx = exam_service.build_score_report_xlsx(session, exam.id, class_name="高一1班")
(OUT / "scores.xlsx").write_bytes(xlsx)
wb = load_workbook(io.BytesIO(xlsx))
ws = wb[wb.sheetnames[0]]
print("    工作表:", wb.sheetnames, "| 尺寸:", ws.max_row, "x", ws.max_column)
for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row, 6), values_only=True):
    print("   ", row)
wb.close()

print()
print("#" * 70)
print("# 6. 家长报告 PDF")
print("#" * 70)
report = prs.generate_parent_report(session, s1.id, exam_id=exam.id)
pdf = prs.export_parent_report_pdf(report)
pdf_info(pdf, "家长报告 PDF", "parent_report.png")

print()
print("#" * 70)
print("# 7. 学生学情报告 PDF")
print("#" * 70)
try:
    sreport = srs.generate_student_report(session, s1.id)
    spdf = srs.export_student_report_pdf(sreport)
    pdf_info(spdf, "学生学情报告 PDF", "student_report.png")
except Exception as exc:  # noqa: BLE001
    print("    !! 生成失败:", type(exc).__name__, exc)

print()
print("#" * 70)
print("# 8. 多 Sheet Excel + 学校模板填充（v3.4.0）")
print("#" * 70)
import pandas as pd
multi = export_service.multi_sheet_excel([
    {"name": "成绩明细", "df": pd.DataFrame([{"姓名": "张三", "数学": 132}])},
    {"name": "统计", "df": pd.DataFrame([{"项目": "均分", "值": 110}])},
])
wb2 = load_workbook(io.BytesIO(multi))
print("    多 Sheet 结果:", wb2.sheetnames)
wb2.close()

tpl = OUT / "school_template.xlsx"
from openpyxl import Workbook
wbx = Workbook()
wsx = wbx.active
wsx.append(["姓名", "数学", "总分"])
wbx.save(tpl)
filled = export_service.fill_school_template(tpl, {"姓名": ["张三", "李四"],
                                                   "数学": [132, 88]})
wb3 = load_workbook(io.BytesIO(filled))
ws3 = wb3[wb3.sheetnames[0]]
print("    学校 Excel 模板填充结果:", [ws3.cell(row=r, column=1).value for r in (2, 3)])
wb3.close()

dtpl = OUT / "school_template.docx"
d = Document()
d.add_paragraph("学校：{{学校}}　班级：{{班级}}")
d.add_paragraph("学生：{{姓名}}　总分：{{总分}}")
d.save(dtpl)
dfilled = export_service.docx_from_school_template(
    dtpl, {"学校": "桂电附中", "班级": "高一1班", "姓名": "张三", "总分": "265"})
d2 = Document(io.BytesIO(dfilled))
print("    Word 模板填充结果:", [p.text for p in d2.paragraphs if p.text])

session.close()
print()
print("样张已写入:", OUT)