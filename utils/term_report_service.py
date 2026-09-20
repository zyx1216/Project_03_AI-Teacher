# -*- coding: utf-8 -*-
"""学期报告生成服务。

把一个学期内的考试统计、班级趋势图、高频错题和学生成绩变化组装成 Word。
本服务不调用 AI，只做确定性数据汇总；所有数据库会话由页面或测试传入。
"""

from __future__ import annotations

from datetime import datetime, time
from io import BytesIO

import plotly.graph_objects as go
from docx import Document
from docx.shared import Inches, Pt

from models.models import Homework, HomeworkAnswer, Question, Student
from utils import exam_service, question_service

DOCX_MIME = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


def _pct(value):
    return "—" if value is None else f"{value * 100:.1f}%"


def _num(value):
    return "—" if value is None else f"{value:g}"


def _date_text(value):
    return "" if value is None else str(value)


def _short(text: str, limit: int = 42) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _term_exams(session, term: str):
    if not term or not str(term).strip() or term == "全部学期":
        raise ValueError("请先选择一个具体学期，再导出学期报告。")
    exams = exam_service.list_exams(session, term=str(term).strip())
    if not exams:
        raise ValueError("该学期还没有考试。")
    return exams


def _term_wrong_questions(session, exams: list, class_name: str | None,
                          top_k: int = 5) -> list[dict]:
    """按学期考试日期圈定作业时间，聚合逐题错题；同一题跨作业合并统计。"""
    starts = [e.exam_date for e in exams if e.exam_date is not None]
    if not starts:
        return []
    start = min(starts)
    end = max(starts)

    q = (session.query(HomeworkAnswer, Homework, Question, Student)
         .join(Homework, HomeworkAnswer.homework_id == Homework.id)
         .join(Question, HomeworkAnswer.question_id == Question.id)
         .join(Student, HomeworkAnswer.student_id == Student.id)
         .filter(Homework.is_template.is_(False),
                 HomeworkAnswer.is_correct.isnot(None),
                 Homework.created_at >= datetime.combine(start, time.min),
                 Homework.created_at <= datetime.combine(end, time.max)))
    if class_name:
        q = q.filter(Student.class_name == class_name)

    grouped: dict[int, dict] = {}
    for answer, _homework, question, _student in q.all():
        item = grouped.setdefault(question.id, {
            "question_id": question.id,
            "content": question.content,
            "knowledge_points": question_service.knowledge_points_list(question),
            "judged": 0,
            "wrong": 0,
        })
        item["judged"] += 1
        if answer.is_correct is False:
            item["wrong"] += 1

    wrongs = [x for x in grouped.values() if x["wrong"] > 0]
    for item in wrongs:
        item["rate"] = round(item["wrong"] / item["judged"], 4) if item["judged"] else None
    wrongs.sort(key=lambda x: (x["wrong"], x["rate"] or 0), reverse=True)
    return wrongs[:top_k]


def _trend_png(exam_infos: list[dict]) -> bytes:
    """生成班级总分/各科均分趋势 PNG，供 Word 内嵌。"""
    exam_names = [x["exam_name"] for x in exam_infos]
    subjects = sorted({s for info in exam_infos for s in info["subject_means"]})
    fig = go.Figure()
    for subject in subjects:
        fig.add_trace(go.Scatter(
            x=exam_names,
            y=[info["subject_means"].get(subject) for info in exam_infos],
            mode="lines+markers", name=subject, connectgaps=False))
    fig.add_trace(go.Scatter(
        x=exam_names, y=[info["total_mean"] for info in exam_infos],
        mode="lines+markers", name="总分均分",
        line=dict(width=4, dash="dot", color="#1F4E79")))
    fig.update_layout(
        height=420, margin=dict(l=30, r=20, t=40, b=30),
        title="班级成绩趋势", yaxis_title="平均分", hovermode="x unified",
        font=dict(family="Microsoft YaHei, SimSun, sans-serif", size=12),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    return fig.to_image(format="png", width=1100, height=520, scale=2)


def _set_doc_font(doc: Document) -> None:
    """给 Word 默认样式指定中文字体，避免不同机器打开字体回退差异过大。"""
    styles = doc.styles
    for name in ("Normal", "Title", "Heading 1", "Heading 2"):
        try:
            style = styles[name]
            style.font.name = "Microsoft YaHei"
            style.font.size = Pt(10.5 if name == "Normal" else 14)
        except KeyError:
            pass


def _add_table(doc, headers: list[str], rows: list[list[str]]):
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Light Grid Accent 1"
    for i, header in enumerate(headers):
        table.rows[0].cells[i].text = header
    for row in rows:
        cells = table.add_row().cells
        for i, value in enumerate(row):
            cells[i].text = str(value)
    return table


def build_term_report(session, term: str, class_name: str | None = None) -> bytes:
    """生成学期报告 Word，返回 docx 二进制内容。"""
    term = str(term or "").strip()
    exams = _term_exams(session, term)

    analyses = []
    exam_infos = []
    student_totals: dict[int, dict] = {}
    student_meta = {}
    participant_ids = set()

    for exam in exams:
        data = exam_service.analyze_exam(session, exam.id, class_name=class_name)
        if not data or not data.get("rows"):
            continue
        analyses.append((exam, data))
        subject_means = {
            subject: stat["mean"]
            for subject, stat in data["subject_stats"].items()
        }
        exam_infos.append({
            "exam_name": exam.name,
            "total_mean": data["total_stats"]["mean"],
            "subject_means": subject_means,
        })
        for row in data["rows"]:
            sid = row["student_id"]
            participant_ids.add(sid)
            student_meta[sid] = {"name": row["name"], "class_name": row["class_name"]}
            student_totals.setdefault(sid, {})[exam.name] = row["total"]

    if not analyses:
        raise ValueError("该学期还没有可汇总的成绩数据。")

    wrongs = _term_wrong_questions(session, [x[0] for x in analyses], class_name)

    doc = Document()
    _set_doc_font(doc)
    doc.add_heading(f"{term} 学期成绩报告", level=0)
    doc.add_paragraph(
        f"范围：{class_name or '全年级'}　学生数：{len(participant_ids)}　"
        f"考试数：{len(analyses)}　统计日期：{datetime.now().date()}")

    doc.add_heading("一、考试成绩汇总", level=1)
    summary_rows = []
    for exam, data in analyses:
        stat = data["total_stats"]
        summary_rows.append([
            exam.name, _date_text(exam.exam_date), str(stat["count"]),
            _num(stat["mean"]), _pct(stat["pass_rate"]),
            _pct(stat["excellent_rate"]),
        ])
    _add_table(doc, ["考试", "日期", "参考人数", "总分均分", "及格率", "优秀率"],
               summary_rows)

    doc.add_heading("二、各科统计", level=1)
    subject_rows = []
    for exam, data in analyses:
        for subject in data["subjects"]:
            stat = data["subject_stats"][subject]
            subject_rows.append([
                exam.name, subject, _num(stat["full_score"]),
                _num(stat["mean"]), _num(stat["median"]), _num(stat["max"]),
                _num(stat["min"]), _pct(stat["pass_rate"]),
                _pct(stat["excellent_rate"]),
            ])
    _add_table(
        doc,
        ["考试", "科目", "满分", "均分", "中位数", "最高", "最低", "及格率", "优秀率"],
        subject_rows)

    doc.add_heading("三、成绩趋势", level=1)
    png = _trend_png(exam_infos)
    doc.add_picture(BytesIO(png), width=Inches(6.5))

    doc.add_heading("四、高频错题 TOP5", level=1)
    if wrongs:
        wrong_rows = []
        for i, item in enumerate(wrongs, start=1):
            wrong_rows.append([
                str(i), _short(item["content"]),
                "、".join(item["knowledge_points"]),
                str(item["wrong"]), str(item["judged"]), _pct(item["rate"]),
            ])
        _add_table(doc, ["序号", "题干摘要", "知识点", "错误人数", "已判人数", "错误率"],
                   wrong_rows)
    else:
        doc.add_paragraph("本学期暂无逐题批改数据，无法统计高频错题。")

    doc.add_heading("五、学生成绩变化", level=1)
    exam_names = [exam.name for exam, _data in analyses]
    change_rows = []
    ordered_students = sorted(
        student_meta.items(),
        key=lambda item: (item[1]["class_name"] or "", item[1]["name"]))
    for sid, meta in ordered_students:
        totals = student_totals[sid]
        values = [totals.get(name) for name in exam_names]
        valid = [(i, v) for i, v in enumerate(values) if v is not None]
        change = ""
        if len(valid) >= 2:
            change = f"{valid[-1][1] - valid[0][1]:+g}"
        change_rows.append([
            meta["class_name"] or "", meta["name"],
            *[_num(v) for v in values], change,
        ])
    _add_table(doc, ["班级", "姓名", *exam_names, "首末总分差"], change_rows)

    buffer = BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
