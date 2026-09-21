# -*- coding: utf-8 -*-
"""
作业成绩与错题服务层。

- 作业总分：Excel 导入 / 手动录入（upsert，唯一约束兜底），班内并列排名查询时算；
- 逐题作答：HomeworkAnswer 的批量录入，是题目正确率、高频错题、错题本的数据来源；
- 作业分析：概览指标、每题正确率、高频错题、与上一份作业的进退步；
- 错题本：错题查询、典型错题排序、导出 Word。

所有函数收外部 session。Excel 的表头识别仍用阶段 1 的 excel_handler，
本层只负责把 {"姓名","班级","score"} 记录写库。
"""

from __future__ import annotations

from models.models import (
    Homework, HomeworkQuestion, HomeworkScore, HomeworkAnswer, Question, Student)
from utils import student_service as student_svc
from utils import homework_stats as hstat


# ---------------------------------------------------------------------------
# 总分录入
# ---------------------------------------------------------------------------

def _get_or_create_total(session, homework_id: int, student_id: int) -> HomeworkScore:
    row = (session.query(HomeworkScore)
           .filter(HomeworkScore.homework_id == homework_id,
                   HomeworkScore.student_id == student_id).first())
    if row is None:
        row = HomeworkScore(homework_id=homework_id, student_id=student_id,
                            submitted=True)
        session.add(row)
    return row


def save_total_score(session, homework_id: int, student_id: int,
                     score: float | None) -> None:
    """手动录/改单个学生总分；分数清空视为未提交。"""
    row = _get_or_create_total(session, homework_id, student_id)
    row.total_score = score
    row.submitted = score is not None
    session.flush()


def import_total_scores(session, homework_id: int, records: list[dict]) -> dict:
    """
    批量导入总分。records: [{"name","class_name","score"(float|None)}, ...]。
    - 学生不存在自动新建（姓名+班级）；
    - 同一作业同一学生重复导入更新原分数；
    - score 为 None（空格/缺分）跳过不覆盖。
    返回 {created_students, written, updated, skipped}。
    """
    hw = session.get(Homework, homework_id)
    if hw is None:
        raise ValueError(f"作业不存在：id={homework_id}")

    created_students = written = updated = skipped = 0
    known = {}
    for rec in records:
        name = (rec.get("name") or "").strip()
        if not name:
            skipped += 1
            continue
        score = rec.get("score")
        if score is None:
            skipped += 1
            continue
        class_name = rec.get("class_name") or hw.class_name
        key = (name, class_name)
        if key in known:
            student = known[key]
        else:
            student, was_created = student_svc.get_or_create_student(
                session, name, class_name)
            known[key] = student
            if was_created:
                created_students += 1
        row = _get_or_create_total(session, homework_id, student.id)
        if row.total_score is None:
            written += 1
        else:
            updated += 1
        row.total_score = score
        row.submitted = True
    session.flush()
    return {"created_students": created_students, "written": written,
            "updated": updated, "skipped": skipped}


def score_rows(session, homework_id: int,
               class_name: str | None = None) -> list[dict]:
    """
    作业的学生总分行：以该班学生名册为主，左连接成绩（没录到的显示未提交）。
    返回 [{student_id,name,class_name,score,submitted,remark}]，并列名次另算。
    """
    hw = session.get(Homework, homework_id)
    target_class = class_name or (hw.class_name if hw else None)
    students = student_svc.list_students(session, class_name=target_class)
    score_map = {}
    for s in (session.query(HomeworkScore, Student)
              .join(Student, HomeworkScore.student_id == Student.id)
              .filter(HomeworkScore.homework_id == homework_id).all()):
        hs, stu = s
        if target_class and stu.class_name != target_class:
            continue
        score_map[stu.id] = hs
    rows = []
    for stu in students:
        hs = score_map.get(stu.id)
        rows.append({
            "student_id": stu.id, "name": stu.name,
            "class_name": stu.class_name,
            "score": hs.total_score if hs else None,
            "submitted": bool(hs and hs.submitted),
            "remark": hs.remark if hs else None,
        })
    # 名册为空时（例如没建学生就直接录了分），退而直接返回成绩行
    if not students:
        for hs, stu in (session.query(HomeworkScore, Student)
                        .join(Student, HomeworkScore.student_id == Student.id)
                        .filter(HomeworkScore.homework_id == homework_id).all()):
            rows.append({
                "student_id": stu.id, "name": stu.name,
                "class_name": stu.class_name, "score": hs.total_score,
                "submitted": bool(hs.submitted), "remark": hs.remark})
    rows.sort(key=lambda r: (-(r["score"] if r["score"] is not None else -1),
                             r["student_id"]))
    return rows

# ---------------------------------------------------------------------------
# 逐题作答（错题本数据来源）
# ---------------------------------------------------------------------------

def _get_or_create_answer(session, homework_id: int, student_id: int,
                          question_id: int) -> HomeworkAnswer:
    row = (session.query(HomeworkAnswer)
           .filter(HomeworkAnswer.homework_id == homework_id,
                   HomeworkAnswer.student_id == student_id,
                   HomeworkAnswer.question_id == question_id).first())
    if row is None:
        row = HomeworkAnswer(homework_id=homework_id, student_id=student_id,
                             question_id=question_id)
        session.add(row)
    return row


def save_answers(session, homework_id: int, entries: list[dict]) -> dict:
    """
    批量保存逐题批改结果。
    entries: [{"student_id","question_id","order_no","is_correct":bool|None,
               "earned_score":float|None,"error_type":str|None}, ...]
    is_correct 为 None 表示未判，跳过。返回写入条数。
    """
    if session.get(Homework, homework_id) is None:
        raise ValueError(f"作业不存在：id={homework_id}")
    written = 0
    for e in entries:
        if e.get("is_correct") is None and e.get("earned_score") is None:
            continue
        row = _get_or_create_answer(session, homework_id,
                                    int(e["student_id"]), int(e["question_id"]))
        row.order_no = e.get("order_no")
        if e.get("is_correct") is not None:
            row.is_correct = bool(e["is_correct"])
        if e.get("earned_score") is not None:
            row.earned_score = float(e["earned_score"])
        row.error_type = e.get("error_type") or None
        written += 1
    session.flush()
    return {"written": written}


# ---------------------------------------------------------------------------
# 作业分析聚合
# ---------------------------------------------------------------------------

def previous_homework(session, homework_id: int) -> Homework | None:
    """同班级、id 更小（更早）的最近一份普通作业。"""
    hw = session.get(Homework, homework_id)
    if hw is None:
        return None
    q = (session.query(Homework)
         .filter(Homework.id < homework_id, Homework.is_template.is_(False)))
    if hw.class_name:
        q = q.filter(Homework.class_name == hw.class_name)
    return q.order_by(Homework.id.desc()).first()


def analyze_homework(session, homework_id: int) -> dict:
    """汇总一次作业分析所需的全部数据（页面只负责展示）。"""
    hw = session.get(Homework, homework_id)
    if hw is None:
        raise ValueError(f"作业不存在：id={homework_id}")

    rows = score_rows(session, homework_id)
    overall = hstat.overall_scores(rows)

    # 并列同名次（缺考不参与）
    values = [r["score"] for r in rows]
    ranks = _competition_rank_values(values)
    for r, rank in zip(rows, ranks):
        r["rank"] = rank

    # 每题正确率（需要逐题作答数据 + 每题满分取作业内设置分值）
    answer_rows = (session.query(HomeworkAnswer)
                   .filter(HomeworkAnswer.homework_id == homework_id).all())
    answers_payload = [{
        "question_id": a.question_id,
        "order_no": a.order_no,
        "is_correct": a.is_correct,
        "earned_score": a.earned_score,
        "full_score": _link_score(session, homework_id, a.question_id),
    } for a in answer_rows]
    per_question = hstat.question_correct_rate(answers_payload)
    top_wrong = hstat.top_wrong_questions(per_question)

    # 进退步
    prev = previous_homework(session, homework_id)
    deltas = {}
    if prev is not None:
        prev_rows = score_rows(session, prev.id)
        deltas = hstat.homework_deltas(rows, prev_rows)

    return {
        "homework": hw,
        "rows": rows,
        "overall": overall,
        "per_question": per_question,
        "top_wrong": top_wrong,
        "previous": prev,
        "deltas": deltas,
    }


def _competition_rank_values(values: list[float | None]) -> list[int | None]:
    """对含 None（缺考）的分数列给并列竞赛名次。"""
    scored = sorted((v for v in values if v is not None), reverse=True)
    rank_map = {}
    for i, v in enumerate(scored):
        if v not in rank_map:
            rank_map[v] = i + 1
    return [rank_map.get(v) if v is not None else None for v in values]


def _link_score(session, homework_id: int, question_id: int) -> float | None:
    link = (session.query(HomeworkQuestion)
            .filter(HomeworkQuestion.homework_id == homework_id,
                    HomeworkQuestion.question_id == question_id).first())
    return link.score if link is not None else None


def homework_svc_homework_questions(session, homework_id: int):
    """延迟引入，避免与 homework_service 循环依赖。"""
    from utils import homework_service as hw_svc
    return hw_svc.homework_questions(session, homework_id)

# ---------------------------------------------------------------------------
# 错题本（HomeworkAnswer 中 is_correct=False 的视图）
# ---------------------------------------------------------------------------

# 批改界面可选的错误类型
ERROR_TYPES = ["概念错误", "计算错误", "审题错误", "书写规范", "其他"]


def list_wrong_answers(session, student_id: int | None = None,
                       homework_id: int | None = None,
                       knowledge_keyword: str | None = None,
                       error_type: str | None = None,
                       subject: str | None = None) -> list[dict]:
    """
    查询错题，返回扁平行（含学生、作业、题目、作答信息）。
    knowledge_keyword 同时匹配题干和知识点 JSON；subject 传值时按作业学科过滤。
    典型错题（该题在所属作业错误率达标）排前面。
    """
    q = (session.query(HomeworkAnswer, Student, Homework, Question)
         .join(Student, HomeworkAnswer.student_id == Student.id)
         .join(Homework, HomeworkAnswer.homework_id == Homework.id)
         .join(Question, HomeworkAnswer.question_id == Question.id)
         .filter(HomeworkAnswer.is_correct.is_(False)))
    if subject:
        q = q.filter(Homework.subject == subject)
    if student_id:
        q = q.filter(HomeworkAnswer.student_id == student_id)
    if homework_id:
        q = q.filter(HomeworkAnswer.homework_id == homework_id)
    if error_type:
        q = q.filter(HomeworkAnswer.error_type == error_type)
    if knowledge_keyword:
        like = f"%{knowledge_keyword}%"
        q = q.filter((Question.content.like(like)) |
                     (Question.knowledge_points.like(like)))

    rows = []
    # 预计算每个 (作业,题) 的错误率，用于"典型错题"标记
    typical = _typical_question_map(session, homework_id)
    hq_score_map = {
        (homework_id, question_id): score
        for homework_id, question_id, score in session.query(
            HomeworkQuestion.homework_id,
            HomeworkQuestion.question_id,
            HomeworkQuestion.score).all()}
    for ans, stu, hw, question in q.all():
        rows.append({
            "answer_id": ans.id,
            "student_id": stu.id, "student_name": stu.name,
            "class_name": stu.class_name,
            "homework_id": hw.id, "homework_name": hw.name,
            "question_id": question.id,
            "order_no": ans.order_no,
            "content": question.content,
            "answer": question.answer,
            "analysis": question.analysis,
            "question_type": question.question_type,
            "difficulty": question.difficulty,
            "knowledge_points": _kp_list(question),
            "earned_score": ans.earned_score,
            "error_type": ans.error_type,
            "typical": typical.get((hw.id, question.id), False),
            "original_score": hq_score_map.get((hw.id, question.id)),
        })
    # 典型错题优先，再按作业、题号、学生排序
    rows.sort(key=lambda r: (not r["typical"], -r["homework_id"],
                             r["order_no"] or 0, r["student_name"]))
    return rows


def _kp_list(question: Question) -> list[str]:
    import json
    try:
        data = json.loads(question.knowledge_points) if question.knowledge_points else []
        return data if isinstance(data, list) else []
    except (ValueError, TypeError):
        return []


def _typical_question_map(session, homework_id: int | None = None) -> dict[tuple, bool]:
    """计算 {(作业id, 题id): 是否典型错题}，判定阈值见 homework_stats。"""
    q = session.query(HomeworkAnswer)
    if homework_id:
        q = q.filter(HomeworkAnswer.homework_id == homework_id)
    stat: dict[tuple, list[int]] = {}
    for a in q.all():
        if a.is_correct is None:
            continue
        bucket = stat.setdefault((a.homework_id, a.question_id), [0, 0])
        bucket[0] += 1                 # 已判人数
        if not a.is_correct:
            bucket[1] += 1             # 错误人数
    result = {}
    for key, (judged, wrong) in stat.items():
        result[key] = bool(judged and wrong / judged >= hstat.TYPICAL_WRONG_RATE)
    return result


def export_wrong_word(rows: list[dict], title: str = "错题本") -> bytes:
    """把错题导成可打印的 Word（原题 + 正确答案 + 解析 + 错误类型）。"""
    import io
    from docx import Document

    doc = Document()
    doc.add_heading(title, level=0)
    for i, r in enumerate(rows, start=1):
        kps = "、".join(r["knowledge_points"])
        head = f"{i}. {r['student_name']}｜{r['homework_name']}"
        if r["error_type"]:
            head += f"｜{r['error_type']}"
        if r["typical"]:
            head += "｜典型错题"
        doc.add_paragraph(head)
        if kps:
            doc.add_paragraph(f"知识点：{kps}")
        doc.add_paragraph(f"题目：{r['content']}")
        doc.add_paragraph(f"正确答案：{r['answer']}")
        if r.get("analysis"):
            doc.add_paragraph(f"解析：{r['analysis']}")
        doc.add_paragraph("")
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()

# ---------------------------------------------------------------------------
# 知识点掌握度分析（v1.5.2）：基于作业逐题批改
# ---------------------------------------------------------------------------

# 无知识点标签的题统一归入此桶
UNLABELED_KP = "未标注知识点"

# 各薄弱等级对应的固定中文建议
KP_SUGGESTIONS = {
    "优秀": "保持现有节奏，可适当增加拓展题。",
    "良好": "针对易错小题再做一轮巩固练习。",
    "一般": "建议重讲核心概念，并安排基础题专项训练。",
    "薄弱": "建议从零重讲本知识点，先做最基础的例题，再逐步提升。",
}


def mastery_level(rate: float | None) -> str:
    """按得分率给掌握等级：>85%优秀 / 60-85%良好 / 40-60%一般 / <40%薄弱。"""
    if rate is None:
        return "薄弱"
    if rate > 0.85:
        return "优秀"
    if rate >= 0.60:
        return "良好"
    if rate >= 0.40:
        return "一般"
    return "薄弱"


def _new_kp_bucket() -> dict:
    return {"full_total": 0.0, "earned_total": 0.0,
            "judge_count": 0, "students": set()}


def _question_kps(question: Question) -> list[str]:
    kps = [k.strip() for k in _kp_list(question) if str(k).strip()]
    return kps or [UNLABELED_KP]


def _accumulate_knowledge(session, homework_id: int,
                          student_id: int | None = None) -> dict[str, dict]:
    """
    按“一道题的分值/实得分分别计入它的每个知识点”聚合。
    student_id 不为 None 时只统计该生；只统计 earned_score 非空的已判作答。
    """
    buckets: dict[str, dict] = {}
    hq_rows = (session.query(HomeworkQuestion)
               .filter(HomeworkQuestion.homework_id == homework_id).all())
    for hq in hq_rows:
        full = hq.score
        if full is None:
            # 没有该题分值就无法算得分率，跳过
            continue
        question = session.get(Question, hq.question_id)
        if question is None:
            continue
        ans_q = (session.query(HomeworkAnswer)
                 .filter(HomeworkAnswer.homework_id == homework_id,
                         HomeworkAnswer.question_id == hq.question_id,
                         HomeworkAnswer.earned_score.isnot(None)))
        if student_id is not None:
            ans_q = ans_q.filter(HomeworkAnswer.student_id == student_id)
        for ans in ans_q.all():
            for kp in _question_kps(question):
                bucket = buckets.setdefault(kp, _new_kp_bucket())
                bucket["full_total"] += float(full)
                bucket["earned_total"] += float(ans.earned_score)
                bucket["judge_count"] += 1
                bucket["students"].add(ans.student_id)
    return buckets


def knowledge_mastery(session, homework_id: int) -> list[dict]:
    """
    全班知识点掌握：返回每个知识点的满分、实得分、得分率、掌握等级、参与人数。
    得分率 = 已判作答实得之和 / 对应题满分之和；按满分降序排列。
    """
    buckets = _accumulate_knowledge(session, homework_id)
    rows = []
    for kp, b in buckets.items():
        rate = (b["earned_total"] / b["full_total"]
                if b["full_total"] else None)
        rows.append({
            "knowledge_point": kp,
            "full_score": round(b["full_total"], 2),
            "earned_score": round(b["earned_total"], 2),
            "rate": round(rate, 4) if rate is not None else None,
            "level": mastery_level(rate),
            "participants": len(b["students"]),
            "judge_count": b["judge_count"],
        })
    rows.sort(key=lambda r: (-(r["full_score"]), r["knowledge_point"]))
    return rows


def student_knowledge_mastery(session, homework_id: int,
                              student_id: int) -> list[dict]:
    """单个学生每个知识点的满分、实得分、得分率与掌握等级。"""
    buckets = _accumulate_knowledge(session, homework_id, student_id)
    rows = []
    for kp, b in buckets.items():
        rate = (b["earned_total"] / b["full_total"]
                if b["full_total"] else None)
        rows.append({
            "knowledge_point": kp,
            "full_score": round(b["full_total"], 2),
            "earned_score": round(b["earned_total"], 2),
            "rate": round(rate, 4) if rate is not None else None,
            "level": mastery_level(rate),
        })
    rows.sort(key=lambda r: (-(r["full_score"]), r["knowledge_point"]))
    return rows


def weakest_knowledge(session, homework_id: int, n: int = 3) -> list[dict]:
    """全班最薄弱的 n 个知识点（得分率升序），各附中文建议。"""
    rows = knowledge_mastery(session, homework_id)
    weak = sorted(rows, key=lambda r: (r["rate"] is None, r["rate"]))[:n]
    for r in weak:
        r["suggestion"] = KP_SUGGESTIONS.get(r["level"], KP_SUGGESTIONS["薄弱"])
    return weak
