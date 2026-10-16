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


def _band_text(rate: float | None) -> str:
    """按得分率给文字评价（v3.5.1）。"""
    if rate is None:
        return ""
    value = rate * 100 if rate <= 1 else rate
    for threshold, label in ((90, "优秀"), (80, "良好"), (70, "中等"),
                             (60, "及格")):
        if value >= threshold:
            return label
    return "待提高"


def _subject_reference(session, student_id: int, exam_id: int,
                       subject: str, score) -> dict:
    """单科参照信息：满分、得分率、班级/年级排名、文字评价（v3.5.1）。"""
    from utils import exam_service, full_score_service

    try:
        full = full_score_service.get_subject_full_score(session, subject,
                                                         exam_id)
    except Exception:  # noqa: BLE001
        full = None
    rate = None
    if full and score is not None:
        try:
            rate = float(score) / float(full)
        except (TypeError, ValueError, ZeroDivisionError):
            rate = None
    ranks = {"class_rank": None, "class_size": 0,
             "grade_rank": None, "grade_size": 0}
    try:
        ranks = exam_service.student_ranks(session, exam_id, student_id,
                                           subject=subject)
    except Exception:  # noqa: BLE001 —— 排名失败不影响报告
        pass
    return {"full": full, "rate": rate, "band": _band_text(rate), **ranks}


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
                "exam_id": exam.id, "exam_name": exam.name,
                "date": exam.exam_date, "subjects": {}}
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
    enriched = []
    for item in exams:
        details = {}
        for subject, score in (item["subjects"] or {}).items():
            details[subject] = dict(
                _subject_reference(session, student_id, item["exam_id"],
                                   subject, score),
                score=score)
        enriched.append({
            "exam_id": item["exam_id"], "exam_name": item["exam_name"],
            "date": item["date"].isoformat() if hasattr(
                item["date"], "isoformat") else "",
            "subjects": item["subjects"], "subject_details": details,
        })
    return {
        "has_student": True,
        "student_name": student.name,
        "class_name": student.class_name or "未分班",
        "exams": enriched,
        "answer_rate": answer_rate,
    }


def _template_report(facts) -> dict:
    """无 LLM 时的确定性报告模板。"""
    exams = facts["exams"]
    latest = exams[0] if exams else None
    def _subject_line(subject: str, score) -> str:
        detail = ((latest or {}).get("subject_details") or {}).get(subject) or {}
        parts = [f"{score:g}分" if isinstance(score, (int, float))
                 else f"{score}"]
        if detail.get("full"):
            parts.append(f"满分{float(detail['full']):g}")
        if detail.get("rate") is not None:
            parts.append(f"得分率{float(detail['rate']) * 100:.1f}%")
        if detail.get("class_rank"):
            parts.append(
                f"班级{detail['class_rank']}/{detail.get('class_size') or '—'}")
        if detail.get("grade_rank"):
            parts.append(
                f"年级{detail['grade_rank']}/{detail.get('grade_size') or '—'}")
        if detail.get("band"):
            parts.append(detail["band"])
        return f"{subject} " + "（" + "，".join(parts) + "）"

    subjects_text = "、".join(
        _subject_line(s, v)
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
    _latest = (f.get("exams") or [{}])[0]
    _details = _latest.get("subject_details") or {}

    def _cell(subject, score) -> str:
        detail = _details.get(subject) or {}
        score_text = (f"{score:g}" if isinstance(score, (int, float))
                      else str(score))
        full_text = (f"{float(detail['full']):g}"
                     if detail.get("full") else "—")
        rate_text = (f"{float(detail['rate']) * 100:.1f}%"
                     if detail.get("rate") is not None else "—")
        class_text = (f"{detail['class_rank']}/{detail.get('class_size')}"
                      if detail.get("class_rank") else "—")
        grade_text = (f"{detail['grade_rank']}/{detail.get('grade_size')}"
                      if detail.get("grade_rank") else "—")
        return ("<tr>"
                f"<td>{html.escape(str(subject))}</td>"
                f"<td style='text-align:right'>{html.escape(score_text)}</td>"
                f"<td style='text-align:right'>{html.escape(full_text)}</td>"
                f"<td style='text-align:right'>{html.escape(rate_text)}</td>"
                f"<td style='text-align:center'>{html.escape(class_text)}</td>"
                f"<td style='text-align:center'>{html.escape(grade_text)}</td>"
                f"<td style='text-align:center'>"
                f"{html.escape(detail.get('band') or '—')}</td>"
                "</tr>")

    rows = "".join(
        _cell(s, v)
        for s, v in (_latest.get("subjects") or {}).items())
    return f"""
    <h1>{html.escape(title)}</h1>
    <p class='muted'>{html.escape(f.get('class_name', ''))}</p>
    {'<p class=notice>' + html.escape(notice) + '</p>' if notice else ''}
    <h2>近期表现</h2><p>{html.escape(report['overview'])}</p>
    <h2>各科情况</h2>
    <table border=1 cellspacing=0 cellpadding=6 width='100%'>
    <tr><th>学科</th><th>分数</th><th>满分</th><th>得分率</th>
    <th>班级排名</th><th>年级排名</th><th>评价</th></tr>{rows}</table>
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
