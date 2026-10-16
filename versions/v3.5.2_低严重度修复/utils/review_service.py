# -*- coding: utf-8 -*-
"""v2.9.0 作业讲评辅助服务。

只处理数据聚合、讲评 PPT/Word 生成和讲评记录，不直接渲染 Streamlit 组件。
知识点统计只使用逐题批改数据，不从考试总分拆知识点。
"""

from __future__ import annotations

import io
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import config
from models.models import (
    Homework, HomeworkAnswer, HomeworkQuestion, HomeworkScore, Question,
    ReviewRecord, Student,
)
from utils import homework_score_service as hscore
from utils import homework_service as hw_svc
from utils import llm_client, ppt_generator


def _kp_list(question) -> list[str]:
    try:
        data = json.loads(question.knowledge_points) if question.knowledge_points else []
        return data if isinstance(data, list) else []
    except (TypeError, ValueError):
        return []


def _relpath(path: Path) -> str:
    try:
        return path.resolve().relative_to(config.BASE_DIR.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def resolve_path(path: str | None) -> Path | None:
    if not path:
        return None
    p = Path(path)
    return p if p.is_absolute() else config.BASE_DIR / p


def is_review_ready(session, homework_id: int) -> dict:
    """检查讲评前置条件；返回 {ready, reason, question_count, student_count}。"""
    hw = session.get(Homework, homework_id)
    if hw is None:
        return {"ready": False, "reason": "作业不存在。", "question_count": 0,
                "student_count": 0}
    links = session.query(HomeworkQuestion).filter(
        HomeworkQuestion.homework_id == homework_id).all()
    if not links:
        return {"ready": False, "reason": "这份作业还没有题目。",
                "question_count": 0, "student_count": 0}

    submitted = {sid for (sid,) in session.query(HomeworkScore.student_id).filter(
        HomeworkScore.homework_id == homework_id,
        HomeworkScore.submitted.is_(True),
        HomeworkScore.total_score.isnot(None)).all()}
    submitted.update(sid for (sid,) in session.query(HomeworkAnswer.student_id).filter(
        HomeworkAnswer.homework_id == homework_id).distinct().all())
    if not submitted:
        return {"ready": False, "reason": "还没有已提交的学生成绩或逐题作答。",
                "question_count": len(links), "student_count": 0}

    answers = session.query(HomeworkAnswer).filter(
        HomeworkAnswer.homework_id == homework_id).all()
    graded = {(a.student_id, a.question_id) for a in answers
              if a.earned_score is not None or a.is_correct is not None}
    need = {(sid, link.question_id) for sid in submitted for link in links}
    missing = need - graded
    if missing:
        return {"ready": False,
                "reason": f"还有 {len(missing)} 个学生题目组合未完成批改。",
                "question_count": len(links), "student_count": len(submitted)}
    return {"ready": True, "reason": "", "question_count": len(links),
            "student_count": len(submitted)}


def analyze_for_review(session, homework_id: int) -> dict:
    """汇总讲评所需统计；无数据时返回空列表，不计算虚假值。"""
    hw = session.get(Homework, homework_id)
    if hw is None:
        raise ValueError(f"作业不存在：id={homework_id}")
    analysis = hscore.analyze_homework(session, homework_id)
    rows = analysis["rows"]
    overall = analysis["overall"]

    links = hw_svc.homework_questions(session, homework_id)
    question_map = {q.id: (link, q) for link, q in links}
    answers = session.query(HomeworkAnswer).filter(
        HomeworkAnswer.homework_id == homework_id).all()
    by_q: dict[int, list[HomeworkAnswer]] = defaultdict(list)
    for a in answers:
        by_q[a.question_id].append(a)

    per_question = []
    for link, q in links:
        vals = [a.earned_score for a in by_q.get(q.id, []) if a.earned_score is not None]
        judged = [a for a in by_q.get(q.id, []) if a.is_correct is not None]
        full = link.score or hw.total_score or 100.0
        avg = round(sum(vals) / len(vals), 2) if vals else None
        rate = round(avg / full, 4) if avg is not None and full else None
        if rate is None and judged:
            rate = round(sum(1 for a in judged if a.is_correct) / len(judged), 4)
        per_question.append({
            "question_id": q.id,
            "order_no": link.order,
            "content": q.content,
            "question_type": q.question_type,
            "answer": q.answer,
            "analysis": q.analysis or "",
            "error_points": q.error_points or "",
            "knowledge_points": _kp_list(q),
            "full_score": round(float(full), 2),
            "avg_score": avg,
            "max_score": max(vals) if vals else None,
            "min_score": min(vals) if vals else None,
            "avg_rate": rate,
            "wrong": sum(1 for a in judged if not a.is_correct),
            "judged": len(judged),
        })

    high_wrong = [q for q in per_question
                  if q["avg_rate"] is not None and q["avg_rate"] < 0.6]
    knowledge_groups: dict[str, list[dict]] = defaultdict(list)
    for item in high_wrong:
        for kp in item["knowledge_points"] or ["未标注知识点"]:
            knowledge_groups[kp].append(item)

    student_wrongs: dict[int, dict] = {}
    wrong_rows = (session.query(HomeworkAnswer, Student, Question)
                  .join(Student, HomeworkAnswer.student_id == Student.id)
                  .join(Question, HomeworkAnswer.question_id == Question.id)
                  .filter(HomeworkAnswer.homework_id == homework_id,
                          HomeworkAnswer.is_correct.is_(False)).all())
    for ans, stu, q in wrong_rows:
        bucket = student_wrongs.setdefault(stu.id, {
            "student_id": stu.id, "student_name": stu.name,
            "class_name": stu.class_name, "wrong": []})
        bucket["wrong"].append({
            "question_id": q.id,
            "order_no": ans.order_no,
            "content": q.content,
            "answer": q.answer,
            "analysis": q.analysis or "",
            "earned_score": ans.earned_score,
            "error_type": ans.error_type or "",
        })
    return {
        "homework": hw,
        "overall": overall,
        "rows": rows,
        "per_question": per_question,
        "high_freq_wrong": high_wrong,
        "knowledge_groups": dict(knowledge_groups),
        "student_wrongs": list(student_wrongs.values()),
    }


def _short(text: str, limit: int = 36) -> str:
    text = str(text or "").replace("\n", " ").strip()
    return text if len(text) <= limit else text[:limit] + "…"


def generate_review_ppt(session, homework_id: int, theme_name: str = "简约") -> bytes:
    """生成讲评 PPT 字节；沿用现有 PPT 主题和基础排版函数。"""
    data = analyze_for_review(session, homework_id)
    hw = data["homework"]
    prs = ppt_generator._new_presentation()
    ppt_generator._add_cover(prs, f"{hw.name} · 试卷讲评", hw.class_name or "")
    overall = data["overall"]
    slide = ppt_generator._blank_slide(prs)
    ppt_generator._add_title(slide, "考试/作业概况")
    ppt_generator._add_bullets(slide, [
        f"提交：{overall.get('submitted', 0)}/{overall.get('total', 0)}",
        f"平均分：{overall.get('mean', '—')}",
        f"最高分：{overall.get('max', '—')}",
        f"最低分：{overall.get('min', '—')}",
        f"高频错题：{len(data['high_freq_wrong'])} 道",
    ])
    for kp, items in data["knowledge_groups"].items():
        slide = ppt_generator._blank_slide(prs)
        ppt_generator._add_title(slide, f"知识点：{kp}")
        bullets = []
        for item in items[:5]:
            bullets.extend([
                f"第{item['order_no']}题：{_short(item['content'], 30)}",
                f"答案：{_short(item['answer'], 28)}",
                f"解析：{_short(item['analysis'], 32)}",
                f"易错点：{_short(item['error_points'] or '审题与迁移', 28)}",
            ])
        ppt_generator._add_bullets(slide, bullets[:20])
    slide = ppt_generator._blank_slide(prs)
    ppt_generator._add_title(slide, "总结与作业布置")
    ppt_generator._add_bullets(slide, [
        "回看高频错题，完成同类变式练习",
        "订正答案并记录错误类型",
        "下节课前完成错题复测",
    ])
    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()


def _fallback_script(data: dict) -> str:
    lines = [f"{data['homework'].name} 讲评稿", ""]
    lines.append(f"提交情况：{data['overall'].get('submitted', 0)}/{data['overall'].get('total', 0)}")
    lines.append(f"平均分：{data['overall'].get('mean', '—')}，最高分：{data['overall'].get('max', '—')}，最低分：{data['overall'].get('min', '—')}")
    lines.append("")
    for kp, items in data["knowledge_groups"].items():
        lines.append(f"一、知识点：{kp}")
        for item in items:
            lines.append(f"第{item['order_no']}题：先让学生回顾题意，再讲答案 {item['answer']}。")
            lines.append(f"讲解思路：{item['analysis'] or '按题意逐步推导，强调关键条件。'}")
            lines.append("可能疑问：为什么要先确定条件之间的关系？")
            lines.append("互动提问：谁能用自己的话说出这道题的突破口？")
            lines.append("")
    if not data["knowledge_groups"]:
        lines.append("本次没有达到高频错题阈值的题目，可按整题得分情况选择性讲评。")
    return "\n".join(lines)


def generate_review_script(session, homework_id: int) -> bytes:
    """生成讲评讲解稿 Word 字节；AI 不可用时使用统计结果兜底。"""
    from docx import Document
    data = analyze_for_review(session, homework_id)
    fallback = _fallback_script(data)
    text = fallback
    try:
        prompt = (
            "请根据以下作业讲评统计，生成适合教师课堂上使用的逐字讲解稿。"
            "包含每题讲解思路、可能的学生疑问、互动提问建议；不要编造统计中不存在的数据。"
            f"\n\n{json.dumps({k: v for k, v in data.items() if k not in ('homework', 'rows')}, ensure_ascii=False, default=str)}")
        text = llm_client.chat_content(
            "你是中小学教师课堂讲评助手，只输出中文讲解稿。",
            prompt, temperature=0.3).strip() or fallback
    except Exception:  # noqa: BLE001 —— AI 调用失败时使用确定性讲稿
        text = fallback
    doc = Document()
    doc.add_heading(f"{data['homework'].name} · 讲评讲解稿", level=0)
    for block in text.split("\n"):
        if block.strip():
            doc.add_paragraph(block.strip())
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def save_review_record(session, homework_id: int, ppt_path: str | None,
                       script_path: str | None) -> ReviewRecord:
    row = ReviewRecord(homework_id=int(homework_id), ppt_path=ppt_path,
                       script_path=script_path)
    session.add(row)
    session.flush()
    return row


def list_review_records(session, homework_id: int) -> list[ReviewRecord]:
    return (session.query(ReviewRecord)
            .filter(ReviewRecord.homework_id == homework_id)
            .order_by(ReviewRecord.created_at.desc(), ReviewRecord.id.desc()).all())


def build_review_files(session, homework_id: int) -> dict:
    """生成文件、写入 data/exports 并留痕，返回记录和路径。"""
    import config
    config.EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    ppt = config.EXPORT_DIR / f"review_{homework_id}_{stamp}.pptx"
    word = config.EXPORT_DIR / f"review_{homework_id}_{stamp}.docx"
    ppt.write_bytes(generate_review_ppt(session, homework_id))
    word.write_bytes(generate_review_script(session, homework_id))
    record = save_review_record(session, homework_id, _relpath(ppt), _relpath(word))
    return {"record": record, "ppt_path": ppt, "script_path": word,
            "ppt_rel": _relpath(ppt), "script_rel": _relpath(word)}
