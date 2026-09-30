# -*- coding: utf-8 -*-
"""家校沟通报告服务（v2.0.0）。

整合学生真实成绩与逐题作答，生成通俗、鼓励为主的家校报告。
数值由服务层聚合，chat_func 只负责组织措辞；数据不足明确提示，不编造。
PDF 复用 PyMuPDF Story + 微软雅黑，适合打印。
"""

from __future__ import annotations

import html
import json
from datetime import date

from models.models import (
    Exam, HomeworkAnswer, HomeworkQuestion, Question, Score, Student)


def _student(session, student_id) -> Student | None:
    return session.get(Student, student_id)


def _recent_scores(session, student_id, exam_id=None, limit=5):
    """取学生最近若干场考试的分科成绩；exam_id 指定时只取该场。"""
    query = (session.query(Score, Exam)
             .join(Exam, Score.exam_id == Exam.id)
             .filter(Score.student_id == student_id))
    if exam_id is not None:
        query = query.filter(Score.exam_id == exam_id)
    rows = query.order_by(Exam.exam_date.desc(), Exam.id.desc()).all()
    grouped = {}
    order = []
    for score, exam in rows:
        if exam.id not in grouped:
            grouped[exam.id] = {
                "exam_name": exam.name, "date": exam.exam_date,
                "subjects": {}}
            order.append(exam.id)
        grouped[exam.id]["subjects"][score.subject] = score.score
    return [grouped[eid] for eid in order[:limit]]


def _recent_answer_rate(session, student_id, limit=20):
    """从逐题作答统计最近作业正确率。"""
    rows = (session.query(HomeworkAnswer.is_correct)
            .filter(HomeworkAnswer.student_id == student_id,
                    HomeworkAnswer.is_correct.isnot(None))
            .order_by(HomeworkAnswer.id.desc()).limit(limit).all())
    values = [x[0] for x in rows if x[0] is not None]
    if not values:
        return None
    return round(sum(values) / len(values) * 100, 1)


def _facts(session, student_id, exam_id=None) -> dict:
    """汇总报告所需确定性事实。"""
    student = _student(session, student_id)
    if student is None:
        return {"has_student": False}
    exams = _recent_scores(session, student_id, exam_id=exam_id)
    answer_rate = _recent_answer_rate(session, student_id)
    return {
        "has_student": True,
        "student_name": student.name,
        "class_name": student.class_name or "未分班",
        "exams": [
            {"exam_name": e["exam_name"],
             "date": e["date"].isoformat() if hasattr(
                 e["date"], "isoformat") else "",
             "subjects": e["subjects"]}
            for e in exams],
        "answer_rate": answer_rate,
    }


def _template_report(facts) -> dict:
    """无 LLM 时的确定性报告模板。"""
    exams = facts["exams"]
    latest = exams[0] if exams else None
    subjects_text = "、".join(
        f"{s}{v:g}分"
        for s, v in (latest["subjects"].items() if latest else []))

    strengths, improvements = [], []
    if latest:
        for s, v in latest["subjects"].items():
            if v >= 90:
                strengths.append(f"{s}发挥出色")
            elif v < 60:
                improvements.append(f"{s}还需加强")

    overview = (
        f"{facts['student_name']}近期学习态度认真，请继续保持。"
        if facts["answer_rate"] is None or facts["answer_rate"] >= 70
        else f"{facts['student_name']}近期作业正确率有提升空间，建议加强练习。")

    return {
        "overview": overview,
        "subjects": subjects_text or "近期暂无考试成绩，以作业表现为主。",
        "strengths": "、".join(strengths) or "学习踏实，进步值得肯定。",
        "improvements": "、".join(improvements) or "继续巩固各科基础，保持稳定。",
        "family_advice": (
            "建议每天固定一段安静时间陪孩子完成作业，多鼓励、少比较，"
            "有问题及时和老师沟通。"),
        "teacher_words": "感谢家长配合，我们一起关注孩子的成长。",
    }


def generate_parent_report(session, student_id, exam_id=None,
                           chat_func=None) -> dict:
    """生成家校报告；chat_func 非空时让 LLM 组织措辞，失败回退模板。"""
    facts = _facts(session, student_id, exam_id=exam_id)
    if not facts.get("has_student"):
        raise ValueError("学生不存在。")

    report = _template_report(facts)
    report["facts"] = facts
    if not facts["exams"] and facts["answer_rate"] is None:
        report["data_notice"] = "需要更多成绩数据，本报告基于有限信息生成。"

    if chat_func is None:
        return report

    system = (
        "你是有经验的班主任，擅长用通俗、温暖、鼓励为主的语言"
        "和家长沟通。只依据给定的真实数据，不编造分数。")
    user = (
        f"学生：{facts['student_name']}（{facts['class_name']}）\n"
        f"近期考试：{json.dumps(facts['exams'], ensure_ascii=False)}\n"
        f"作业正确率：{facts['answer_rate']}\n"
        "只输出 JSON："
        '{"overview": "", "strengths": "", "improvements": "", '
        '"family_advice": "", "teacher_words": ""}')
    try:
        data = json.loads(chat_func(system, user))
        for key in ("overview", "strengths", "improvements",
                    "family_advice", "teacher_words"):
            if data.get(key):
                report[key] = str(data[key])
    except (TypeError, ValueError, json.JSONDecodeError):
        pass  # LLM 失败保留模板，不阻断
    return report


def render_html(report) -> str:
    """构造报告的 HTML（供 PDF）。"""
    return _render_html(report)


def render_report(report) -> str:
    """页面预览/编辑入口；返回报告 HTML。"""
    return _render_html(report)


def _render_html(report) -> str:
    f = report.get("facts", {})
    title = f"{f.get('student_name', '')}同学家校沟通报告"
    notice = report.get("data_notice")
    rows = "".join(
        f"<tr><td>{html.escape(s)}</td><td>{html.escape(f'{v:g}')}</td></tr>"
        for e in f.get("exams", [])[:1]
        for s, v in e.get("subjects", {}).items())
    return f"""
    <h1>{html.escape(title)}</h1>
    <p class='muted'>{html.escape(f.get('class_name', ''))}</p>
    {'<p class=notice>' + html.escape(notice) + '</p>' if notice else ''}
    <h2>近期表现</h2><p>{html.escape(report['overview'])}</p>
    <h2>各科情况</h2>
    <table border=1 cellspacing=0 cellpadding=6>
    <tr><th>学科</th><th>分数</th></tr>{rows}</table>
    <p>{html.escape(report['subjects'])}</p>
    <h2>优点与进步</h2><p>{html.escape(report['strengths'])}</p>
    <h2>需要改进</h2><p>{html.escape(report['improvements'])}</p>
    <h2>家庭配合建议</h2><p>{html.escape(report['family_advice'])}</p>
    <h2>老师寄语</h2><p>{html.escape(report['teacher_words'])}</p>
    """


def _pdf_archive():
    """微软雅黑存在时嵌入。"""
    import pymupdf
    from pathlib import Path
    font = Path(r"C:\Windows\Fonts\msyh.ttc")
    if not font.exists():
        return None, "body { font-family: china-s, sans-serif; }"
    archive = pymupdf.Archive()
    archive.add(font.read_bytes(), "yh.ttc")
    return archive, (
        "@font-face { font-family: yh; src: url(yh.ttc); } "
        "body { font-family: yh, china-s, sans-serif; }")


def export_parent_report_pdf(report) -> bytes:
    """把家校报告导出为适合打印的 PDF。"""
    import io
    import pymupdf

    archive, font_css = _pdf_archive()
    body = render_html(report)
    page_html = f"""
    <html><head><meta charset='utf-8'><style>
    h1 {{ font-size: 20px; }} h2 {{ font-size: 15px; margin-top: 14px; }}
    table {{ border-collapse: collapse; }} .muted {{ color: #666; }}
    .notice {{ background: #fff3cd; padding: 8px; }}
    {font_css}</style></head><body>{body}</body></html>"""

    story = pymupdf.Story(html=page_html, archive=archive)
    buffer = io.BytesIO()
    writer = pymupdf.DocumentWriter(buffer)
    mediabox = pymupdf.paper_rect("a4")
    while True:
        dev = writer.begin_page(mediabox)
        more, _ = story.place(mediabox + (46, 48, -46, -48))
        story.draw(dev)
        writer.end_page()
        if not more:
            break
    writer.close()
    return buffer.getvalue()
