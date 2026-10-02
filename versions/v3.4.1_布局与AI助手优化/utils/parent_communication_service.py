# -*- coding: utf-8 -*-
"""家校沟通服务（v3.4.0）。

只做内容生成与留档，不做消息推送：
- 家长版成绩单：各科成绩、班级/年级排名、分数段、近 5 次趋势、知识点掌握；
- 学习建议：在家辅导 / 推荐练习 / 注意事项（AI 可选，规则兜底）；
- 家长会班级整体报告；
- 整班批量导出 ZIP。
生成结果可写入 parent_communication 表留档。
"""
from __future__ import annotations

import io
import zipfile

from models.models import Exam, ParentCommunication, Score, Student
from utils import full_score_service as fss


# ---------------------------------------------------------------------------
# 基础取数
# ---------------------------------------------------------------------------

def _band(rate: float | None) -> str:
    """按标准得分率给分数段标签。"""
    if rate is None:
        return "—"
    value = rate * 100 if rate <= 1 else rate
    for item in fss.rate_bands():
        if value < item["high"]:
            return item["label"]
    return "优秀"


def _recent_exams(session, student_id: int, exam_id: int | None = None,
                  limit: int = 5) -> list[dict]:
    """学生最近若干场考试（含分科、排名、满分、分数段）。"""
    query = (session.query(Score, Exam)
             .join(Exam, Score.exam_id == Exam.id)
             .filter(Score.student_id == int(student_id)))
    if exam_id is not None:
        query = query.filter(Score.exam_id == int(exam_id))
    rows = query.order_by(Exam.exam_date.desc(), Exam.id.desc()).all()
    grouped: dict[int, dict] = {}
    order: list[int] = []
    for score, exam in rows:
        bucket = grouped.get(exam.id)
        if bucket is None:
            bucket = {"exam_id": exam.id, "exam_name": exam.name,
                      "date": exam.exam_date, "subjects": {}}
            grouped[exam.id] = bucket
            order.append(exam.id)
        full = fss.get_subject_full_score(session, score.subject, exam.id)
        rate = fss.calc_rate(score.score, full)
        bucket["subjects"][score.subject] = {
            "score": score.score, "full": full,
            "class_rank": score.class_rank, "grade_rank": score.grade_rank,
            "band": _band(rate),
            "rate": round(rate * 100, 1) if rate is not None else None,
        }
    return [grouped[eid] for eid in order[:max(1, int(limit))]]


def _weak_knowledge(session, student_id: int, subject: str | None = None,
                    top_n: int = 5) -> list[dict]:
    """学生掌握最弱的知识点（只取逐题作答数据）。"""
    from utils import knowledge_graph_service as kgs
    subject = subject or "数学"
    try:
        data = kgs.build_mastery(session, subject, student_id=int(student_id))
    except Exception:  # noqa: BLE001 —— 没有作答数据时留空
        return []
    items: list[dict] = []
    for row in data.get("personal") or []:
        items = list(row.get("items") or [])
    items.sort(key=lambda x: x.get("rate") or 0)
    return items[:max(1, int(top_n))]


# ---------------------------------------------------------------------------
# 成绩单
# ---------------------------------------------------------------------------

def build_report_card(session, student_id: int, exam_id: int | None = None,
                      subject: str | None = None) -> dict:
    """家长版成绩单数据：各科/排名/分数段/近5次趋势/知识点。"""
    student = session.get(Student, int(student_id))
    if student is None:
        raise ValueError("学生不存在。")
    exams = _recent_exams(session, student_id, exam_id=exam_id)
    latest = exams[0] if exams else None
    trend = []
    for exam in reversed(exams):
        total, full_total = 0.0, 0.0
        has_value = False
        for item in exam["subjects"].values():
            if item.get("score") is None:
                continue
            total += float(item["score"])
            full_total += float(item.get("full") or 0)
            has_value = True
        if has_value:
            trend.append({
                "exam_name": exam["exam_name"],
                "total": round(total, 1),
                "full": round(full_total, 1) if full_total else None,
                "rate": (round(total / full_total * 100, 1)
                         if full_total else None),
            })
    weak = _weak_knowledge(session, student_id, subject=subject)
    return {
        "student_id": student.id, "name": student.name,
        "class_name": student.class_name or "未分班",
        "exam": ({"exam_id": latest["exam_id"], "exam_name": latest["exam_name"],
                  "date": latest["date"].isoformat() if hasattr(
                      latest["date"], "isoformat") else ""}
                 if latest else None),
        "subjects": (latest["subjects"] if latest else {}),
        "trend": trend,
        "weak_knowledge": weak,
        "has_data": bool(exams) or bool(weak),
    }


def report_card_text(card: dict) -> str:
    """把成绩单数据渲染成可复制的纯文本（与 PDF 内容一致口径）。"""
    lines = [f"{card['name']}（{card['class_name']}）家校成绩单"]
    if card.get("exam"):
        lines.append(f"考试：{card['exam']['exam_name']}　{card['exam']['date']}")
    else:
        lines.append("考试：暂无成绩记录")
    if card.get("subjects"):
        lines.append("各科成绩：")
        for subject, item in card["subjects"].items():
            rank = item.get("class_rank")
            lines.append(
                f"  {subject}：{item.get('score')} / {item.get('full')}"
                f"　分数段 {item.get('band')}"
                + (f"　班级排名 {rank}" if rank else "")
                + (f"　年级排名 {item['grade_rank']}"
                   if item.get("grade_rank") else ""))
    if card.get("trend"):
        lines.append("近几次总分趋势：")
        for item in card["trend"]:
            rate = f"（得分率 {item['rate']}%）" if item.get("rate") else ""
            lines.append(f"  {item['exam_name']}：{item['total']}{rate}")
    if card.get("weak_knowledge"):
        weak = "、".join(
            f"{x['knowledge_point']}（{x['rate']}%）"
            for x in card["weak_knowledge"])
        lines.append(f"需关注的知识点：{weak}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 学习建议
# ---------------------------------------------------------------------------

def _rule_advice(card: dict, subject: str | None = None) -> dict:
    """无 AI 时的确定性学习建议。"""
    weak = card.get("weak_knowledge") or []
    weak_names = "、".join(x["knowledge_point"] for x in weak[:3]) or "本学科基础"
    subject_text = f"{subject}" if subject else "各科"
    return {
        "family": (f"建议每天固定 30 分钟陪孩子梳理{subject_text}当天的错题，"
                   "先让他讲一遍思路，再动笔订正；多鼓励、少比较。"),
        "practice": f"优先补{weak_names}：先做课本例题，再做 3-5 道同类基础题，隔天复测一次。",
        "cautions": ("连续两次同类题仍出错时，先回到概念和定义，不要盲目加量；"
                     "保证睡眠，避免熬夜刷题。"),
    }


def generate_advice(session, student_id: int, subject: str | None = None,
                    exam_id: int | None = None, chat_func=None) -> dict:
    """给家长的学习建议：在家辅导 / 推荐练习 / 注意事项。"""
    card = build_report_card(session, student_id, exam_id=exam_id,
                             subject=subject)
    advice = _rule_advice(card, subject=subject)
    advice["student_id"] = card["student_id"]
    advice["name"] = card["name"]
    advice["data_notice"] = ("" if card.get("has_data")
                             else "暂无成绩或作答数据，以下为通用建议。")
    if chat_func is None:
        return advice
    weak = "、".join(x["knowledge_point"] for x in
                     (card.get("weak_knowledge") or [])[:5]) or "暂无"
    system = ("你是班主任，写给家长的学习建议。只依据给定数据，"
              "语气平和具体，不做诊断、不承诺提分。")
    user = (f"学生：{card['name']}（{card['class_name']}）\n"
            f"学科：{subject or '各科'}\n需关注知识点：{weak}\n"
            '只输出 JSON：{"family": "", "practice": "", "cautions": ""}')
    try:
        import json as _json
        data = _json.loads(chat_func(system, user))
        for key in ("family", "practice", "cautions"):
            if data.get(key):
                advice[key] = str(data[key])
    except Exception:  # noqa: BLE001 —— AI 失败保留规则建议
        pass
    return advice


def advice_text(advice: dict) -> str:
    """学习建议的纯文本形式（可复制、可并入成绩单导出）。"""
    return "\n".join([
        f"{advice.get('name') or ''} 学习建议".strip(),
        f"【在家辅导】{advice.get('family', '')}",
        f"【推荐练习】{advice.get('practice', '')}",
        f"【注意事项】{advice.get('cautions', '')}",
    ])


# ---------------------------------------------------------------------------
# 班级整体报告（家长会）
# ---------------------------------------------------------------------------

def build_class_report(session, class_name: str,
                       exam_id: int | None = None) -> dict:
    """家长会用的班级整体报告：学科均分/及格率/优秀率 + 薄弱知识点。"""
    students = (session.query(Student)
                .filter(Student.class_name == class_name).all())
    if not students:
        raise ValueError("该班级还没有学生。")
    student_ids = [s.id for s in students]
    if exam_id is None:
        latest = (session.query(Exam)
                  .order_by(Exam.exam_date.desc(), Exam.id.desc()).first())
        exam_id = latest.id if latest else None
    exam = session.get(Exam, int(exam_id)) if exam_id else None
    subject_stats: dict[str, dict] = {}
    if exam_id:
        rows = (session.query(Score)
                .filter(Score.exam_id == int(exam_id),
                        Score.student_id.in_(student_ids)).all())
        for score in rows:
            item = subject_stats.setdefault(
                score.subject, {"scores": [], "full": 0, "pass": 0,
                                "excellent": 0})
            if score.score is None:
                continue
            full = fss.get_subject_full_score(session, score.subject, exam_id)
            rate = fss.calc_rate(score.score, full)
            item["scores"].append(float(score.score))
            item["full"] = full
            if rate is not None and rate >= 0.6:
                item["pass"] += 1
            if rate is not None and rate >= 0.9:
                item["excellent"] += 1
    stats = []
    for subject, item in sorted(subject_stats.items()):
        values = item["scores"]
        if not values:
            continue
        stats.append({
            "subject": subject, "count": len(values),
            "avg": round(sum(values) / len(values), 1),
            "full": item["full"],
            "pass_rate": round(item["pass"] / len(values) * 100, 1),
            "excellent_rate": round(item["excellent"] / len(values) * 100, 1),
        })
    class_weak: dict[str, list[float]] = {}
    for sid in student_ids:
        for row in _weak_knowledge(session, sid, top_n=5):
            class_weak.setdefault(row["knowledge_point"], []).append(
                row.get("rate") or 0)
    weak_points = sorted(
        ({"knowledge_point": kp, "avg_rate": round(sum(v) / len(v), 1)}
         for kp, v in class_weak.items()),
        key=lambda x: x["avg_rate"])[:5]
    return {
        "class_name": class_name,
        "student_count": len(students),
        "exam": ({"exam_id": exam.id, "exam_name": exam.name,
                  "date": exam.exam_date.isoformat() if exam.exam_date else ""}
                 if exam else None),
        "subject_stats": stats,
        "weak_points": weak_points,
        "suggestions": [
            "请家长关注孩子的作业完成质量，而不只看是否完成。",
            "对薄弱知识点，建议每周固定一次 20 分钟专项复测。",
            "保持作息稳定，考试前不做突击式加量。",
        ],
    }


def class_report_text(report: dict) -> str:
    """班级整体报告的纯文本形式。"""
    lines = [f"{report['class_name']} 家长会班级报告",
             f"学生人数：{report['student_count']}"]
    if report.get("exam"):
        lines.append(f"考试：{report['exam']['exam_name']}　"
                     f"{report['exam']['date']}")
    for item in report.get("subject_stats") or []:
        lines.append(f"  {item['subject']}：均分 {item['avg']}／{item['full']}"
                     f"　及格率 {item['pass_rate']}%"
                     f"　优秀率 {item['excellent_rate']}%")
    if report.get("weak_points"):
        lines.append("班级薄弱知识点：" + "、".join(
            f"{x['knowledge_point']}（{x['avg_rate']}%）"
            for x in report["weak_points"]))
    for tip in report.get("suggestions") or []:
        lines.append(f"- {tip}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 留档与批量导出
# ---------------------------------------------------------------------------

def save_record(session, student_id: int, exam_id: int | None, type: str,
                content: str) -> ParentCommunication:
    """把一次生成内容写进家校沟通留档。"""
    row = ParentCommunication(
        student_id=int(student_id),
        exam_id=int(exam_id) if exam_id else None,
        type=str(type), content=str(content))
    session.add(row)
    session.flush()
    return row


def list_records(session, student_id: int | None = None,
                 type: str | None = None, limit: int = 50) -> list[dict]:
    """列出留档记录（按时间倒序）。"""
    query = session.query(ParentCommunication, Student).join(
        Student, ParentCommunication.student_id == Student.id)
    if student_id:
        query = query.filter(ParentCommunication.student_id == int(student_id))
    if type:
        query = query.filter(ParentCommunication.type == str(type))
    rows = query.order_by(ParentCommunication.created_at.desc(),
                          ParentCommunication.id.desc()).limit(
        max(1, int(limit))).all()
    return [{
        "id": row.id, "student_id": stu.id, "student_name": stu.name,
        "class_name": stu.class_name or "未分班", "exam_id": row.exam_id,
        "type": row.type, "content": row.content,
        "created_at": row.created_at,
    } for row, stu in rows]


def export_family_zip(session, student_ids: list[int], exam_id: int | None = None,
                      with_advice: bool = True, chat_func=None,
                      progress=None) -> bytes:
    """整班批量导出家长版成绩单 PDF（可选合并学习建议），打包 ZIP。"""
    from utils import parent_report_service as prs
    ids = [int(x) for x in dict.fromkeys(student_ids or [])]
    out = io.BytesIO()
    total = max(1, len(ids))
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for index, sid in enumerate(ids, start=1):
            student = session.get(Student, sid)
            if student is None:
                continue
            report = prs.generate_parent_report(session, sid, exam_id=exam_id,
                                                chat_func=chat_func)
            if with_advice:
                advice = generate_advice(session, sid, exam_id=exam_id,
                                         chat_func=chat_func)
                report = dict(report)
                report["family_advice"] = (
                    f"{report.get('family_advice', '')}\n\n"
                    f"{advice_text(advice)}")
            pdf = prs.export_parent_report_pdf(report)
            zf.writestr(f"{student.name}_家校成绩单.pdf", pdf)
            if callable(progress):
                progress(index, total)
    return out.getvalue()
