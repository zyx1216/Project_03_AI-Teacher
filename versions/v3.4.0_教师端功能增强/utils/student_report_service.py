# -*- coding: utf-8 -*-
"""学生个人学情报告（v2.7.0）。

聚合基本信息、成绩趋势、知识点掌握、作业完成、错题薄弱与 AI 学习建议；
支持导出 PDF（复用微软雅黑 + PyMuPDF Story）与批量 ZIP。
"""

from __future__ import annotations

import io
import json
import zipfile


def _student(session, student_id):
    from models.models import Student
    return session.get(Student, student_id)


def _score_trend(session, student_id):
    from utils import exam_service
    rows = exam_service.student_scores_over_time(session, student_id) or []
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        out.append({"exam": r.get("exam_name") or r.get("name") or "",
                    "date": str(r.get("exam_date") or r.get("date") or ""),
                    "total": r.get("total"),
                    "subjects": r.get("subjects") or {}})
    return out


def _knowledge_rates(session, student_id):
    """按知识点聚合该生逐题得分率（只用真实作答数据）。"""
    from models.models import (HomeworkAnswer, HomeworkQuestion, Question,
                               Homework)
    rows = (session.query(HomeworkAnswer, HomeworkQuestion, Question)
            .join(HomeworkQuestion,
                  (HomeworkQuestion.homework_id == HomeworkAnswer.homework_id)
                  & (HomeworkQuestion.question_id == HomeworkAnswer.question_id))
            .join(Question, Question.id == HomeworkAnswer.question_id)
            .filter(HomeworkAnswer.student_id == student_id,
                    HomeworkAnswer.earned_score.isnot(None)).all())
    buckets = {}
    for ans, link, question in rows:
        if not link.score:
            continue
        for kp in _kps_of(question):
            b = buckets.setdefault(kp, {"earned": 0.0, "full": 0.0})
            b["earned"] += float(ans.earned_score)
            b["full"] += float(link.score)
    out = {}
    for kp, b in buckets.items():
        out[kp] = round(b["earned"] / b["full"], 4) if b["full"] else None
    return out


def _kps_of(question) -> list[str]:
    try:
        data = json.loads(question.knowledge_points or "[]")
        return [str(x).strip() for x in data if str(x).strip()] \
            if isinstance(data, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _homework_completion(session, student_id):
    from models.models import HomeworkScore, HomeworkAnswer
    from utils import homework_service
    total = (session.query(HomeworkScore)
             .filter(HomeworkScore.student_id == student_id,
                     HomeworkScore.total_score.isnot(None)).count())
    answers = (session.query(HomeworkAnswer)
               .filter(HomeworkAnswer.student_id == student_id).count())
    return {"scored_homework": total, "answer_records": answers}


def _weak_points(session, student_id, limit=5):
    rates = _knowledge_rates(session, student_id)
    items = [(kp, r) for kp, r in rates.items() if r is not None]
    items.sort(key=lambda x: x[1])
    return [{"knowledge_point": kp, "rate": r} for kp, r in items[:limit]]


def generate_student_report(session, student_id: int, chat_func=None) -> dict:
    """生成学生个人学情报告。

    返回 dict；数据不足时在 notes 里明确说明，不编造。
    """
    stu = _student(session, student_id)
    if stu is None:
        raise ValueError("学生不存在。")
    trend = _score_trend(session, student_id)
    rates = _knowledge_rates(session, student_id)
    completion = _homework_completion(session, student_id)
    weak = _weak_points(session, student_id)
    notes = []
    if not trend:
        notes.append("尚无考试成绩数据。")
    if not rates:
        notes.append("尚无逐题批改数据，知识点分析不可用。")

    advice = _build_advice(stu, trend, weak, help_text=notes, chat_func=chat_func)
    return {
        "student_id": stu.id,
        "name": stu.name,
        "class_name": stu.class_name or "",
        "trend": trend,
        "knowledge_rates": rates,
        "weak_points": weak,
        "completion": completion,
        "advice": advice,
        "notes": notes,
    }


def _build_advice(stu, trend, weak, help_text=None, chat_func=None) -> str:
    """学习建议：AI 优先，失败给确定性兜底。"""
    weak_text = "、".join(w["knowledge_point"] for w in weak) or "暂无明确薄弱点"
    fallback = (f"{stu.name}近期薄弱点：{weak_text}。"
                "建议先补基础概念，再做同类变式练习，每两天一次小过关。")
    if chat_func is None:
        try:
            from utils import llm_client
            if not llm_client.is_configured():
                return fallback
            chat_func = lambda s, u: llm_client.chat_content(s, u)
        except Exception:  # noqa: BLE001
            return fallback
    try:
        system = ("你是教学助手。根据学生成绩趋势与薄弱知识点，写一段中文学习建议，"
                  "鼓励为主、具体可执行，不超过120字。")
        user = (f"学生：{stu.name}；成绩点数：{len(trend or [])}；"
                f"薄弱点：{weak_text}")
        text = str(chat_func(system, user) or "").strip()
        return text or fallback
    except Exception:  # noqa: BLE001
        return fallback


def render_student_report_html(report: dict) -> str:
    """报告 HTML（供预览与 PDF）。"""
    s = report or {}
    parts = [f"<h1>{_esc(s.get('name'))} 学情报告</h1>"]
    if s.get("class_name"):
        parts.append(f"<p class='muted'>班级：{_esc(s['class_name'])}</p>")
    parts.append("<h2>成绩概览</h2>")
    if s.get("trend"):
        rows = "".join(
            f"<tr><td>{_esc(t.get('exam'))}</td><td>{_esc(t.get('date'))}</td>"
            f"<td>{_fmt(t.get('total'))}</td></tr>" for t in s["trend"][:10])
        parts.append("<table border='1' cellpadding='4'>"
                     "<tr><th>考试</th><th>日期</th><th>总分</th></tr>"
                     f"{rows}</table>")
    else:
        parts.append("<p class='muted'>暂无考试成绩数据。</p>")
    parts.append("<h2>知识点掌握</h2>")
    if s.get("knowledge_rates"):
        rows = "".join(
            f"<tr><td>{_esc(kp)}</td><td>{_pct(r)}</td></tr>"
            for kp, r in s["knowledge_rates"].items())
        parts.append("<table border='1' cellpadding='4'>"
                     "<tr><th>知识点</th><th>得分率</th></tr>"
                     f"{rows}</table>")
    else:
        parts.append("<p class='muted'>暂无逐题批改数据。</p>")
    parts.append("<h2>薄弱知识点</h2>")
    if s.get("weak_points"):
        parts.append("<ul>" + "".join(
            f"<li>{_esc(w['knowledge_point'])}（{_pct(w['rate'])}）</li>"
            for w in s["weak_points"]) + "</ul>")
    else:
        parts.append("<p class='muted'>暂无明显薄弱点。</p>")
    c = s.get("completion") or {}
    parts.append("<h2>作业完成</h2>")
    parts.append(f"<p>已录分作业：{int(c.get('scored_homework') or 0)} 次；"
                 f"逐题作答记录：{int(c.get('answer_records') or 0)} 条</p>")
    parts.append("<h2>学习建议</h2>")
    parts.append(f"<p>{_esc(s.get('advice'))}</p>")
    if s.get("notes"):
        parts.append("<p class='notice'>" + _esc("；".join(s["notes"])) + "</p>")
    return "".join(parts)


def _esc(value) -> str:
    import html
    return html.escape(str(value if value is not None else "—"))


def _fmt(value):
    return "—" if value is None else value


def _pct(rate):
    return "—" if rate is None else f"{float(rate) * 100:.0f}%"


def _pdf_archive():
    import pymupdf
    from pathlib import Path
    font = Path(r"C:\Windows\Fonts\msyh.ttc")
    if not font.exists():
        return None, "body { font-family: china-s, sans-serif; }"
    archive = pymupdf.Archive()
    archive.add(font.read_bytes(), "yh.ttc")
    return archive, ("@font-face { font-family: yh; src: url(yh.ttc); } "
                     "body { font-family: yh, china-s, sans-serif; }")


def export_student_report_pdf(report: dict) -> bytes:
    """把学情报告导出为 PDF 字节。"""
    import pymupdf
    archive, font_css = _pdf_archive()
    body = render_student_report_html(report)
    page_html = (
        "<html><head><meta charset='utf-8'><style>"
        "h1 { font-size: 20px; } h2 { font-size: 15px; margin-top: 14px; }"
        "table { border-collapse: collapse; } .muted { color: #666; }"
        ".notice { background: #fff3cd; padding: 8px; }"
        f"{font_css}</style></head><body>{body}</body></html>")
    story = pymupdf.Story(html=page_html, archive=archive)
    buffer = io.BytesIO()
    writer = pymupdf.DocumentWriter(buffer)
    mediabox = pymupdf.paper_rect("a4")
    where = mediabox + (36, 36, -36, -36)
    more = 1
    while more:
        dev = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(dev)
        writer.end_page()
    writer.close()
    return buffer.getvalue()


def export_reports_zip(session, student_ids: list[int],
                       chat_func=None) -> bytes:
    """批量生成学生报告并打包为 ZIP（每个学生一个 PDF）。"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for sid in dict.fromkeys(int(x) for x in (student_ids or [])):
            try:
                report = generate_student_report(session, sid,
                                                 chat_func=chat_func)
                pdf = export_student_report_pdf(report)
                zf.writestr(f"{report['name']}_学情报告.pdf", pdf)
            except Exception:  # noqa: BLE001 —— 单个失败不阻断整包
                continue
    return buffer.getvalue()
