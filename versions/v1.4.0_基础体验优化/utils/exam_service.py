# -*- coding: utf-8 -*-
"""
考试与成绩数据服务层。

集中处理：
- 考试的增删改查、成绩批量导入（自动建学生、重复导入更新）；
- 单次考试分析所需的数据组装（各科指标、排名、进退步）；
- 趋势分析和学生画像所需的历次成绩数据。

为便于测试，所有函数都接收外部传入的 session，不自己开关连接。
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Optional

from sqlalchemy import func

from models.models import Exam, Score, Student
from utils import stats as stats_mod
from utils.student_service import get_or_create_student


def list_exams(session, term: str | None = None) -> list[Exam]:
    """考试按日期升序返回；传 term 时只看该学期（趋势分析依赖默认顺序）。"""
    q = session.query(Exam)
    if term:
        q = q.filter(Exam.term == term)
    return q.order_by(Exam.exam_date, Exam.id).all()


def list_exam_terms(session) -> list[str]:
    """返回已使用过的非空学期，去重排序。"""
    rows = (session.query(Exam.term)
            .filter(Exam.term.isnot(None), Exam.term != "")
            .distinct().all())
    return sorted({row[0] for row in rows})


def get_exam(session, exam_id: int) -> Optional[Exam]:
    return session.get(Exam, exam_id)


def create_exam(session, name: str, exam_date=None, grade: str | None = None,
                term: str | None = None, full_scores: dict | None = None,
                remark: str | None = None) -> Exam:
    """新建一场考试；full_scores 是 {科目: 满分} 的字典，存成 JSON。"""
    if not name or not name.strip():
        raise ValueError("考试名称不能为空")
    exam = Exam(
        name=name.strip(), exam_date=exam_date, grade=grade, term=term,
        full_scores=json.dumps(full_scores or {}, ensure_ascii=False),
        remark=remark,
    )
    session.add(exam)
    session.flush()
    return exam


def update_exam(session, exam_id: int, **fields) -> None:
    allowed = {"name", "exam_date", "grade", "term", "remark"}
    exam = session.get(Exam, exam_id)
    if exam is None:
        raise ValueError(f"考试不存在：id={exam_id}")
    for key, value in fields.items():
        if key in allowed:
            setattr(exam, key, value)
    if "full_scores" in fields and isinstance(fields["full_scores"], dict):
        exam.full_scores = json.dumps(fields["full_scores"], ensure_ascii=False)


def delete_exam(session, exam_id: int) -> None:
    exam = session.get(Exam, exam_id)
    if exam is None:
        raise ValueError(f"考试不存在：id={exam_id}")
    session.delete(exam)



def rows_to_full_scores(rows: list[dict]) -> dict[str, float]:
    """
    把逐行编辑器的数据转成 Exam.full_scores 字典。

    空学科行自动忽略；同学科重复或满分不是正数时抛 ValueError。
    """
    result: dict[str, float] = {}
    for row in rows or []:
        subject = str(row.get("subject") or row.get("学科") or "").strip()
        if not subject:
            continue
        try:
            score = float(row.get("score", row.get("满分")))
        except (TypeError, ValueError):
            raise ValueError(f"“{subject}”的满分必须是数字。")
        if score <= 0:
            raise ValueError(f"“{subject}”的满分必须大于 0。")
        if subject in result:
            raise ValueError(f"学科重复：{subject}")
        result[subject] = score
    return result

def full_scores_of(exam: Exam, subjects: list[str],
                   default_full: float = 100.0) -> dict:
    """读取考试的各科满分；缺失的科目用默认满分 100 兜底。"""
    try:
        saved = json.loads(exam.full_scores) if exam.full_scores else {}
    except (TypeError, ValueError):
        saved = {}
    return {s: float(saved.get(s, default_full)) for s in subjects}


def _get_or_create_score(session, exam_id: int, student_id: int,
                         subject: str) -> Score:
    """按唯一约束取已有成绩行，没有就新建。"""
    score = (session.query(Score)
             .filter(Score.exam_id == exam_id, Score.student_id == student_id,
                     Score.subject == subject).first())
    if score is None:
        score = Score(exam_id=exam_id, student_id=student_id, subject=subject)
        session.add(score)
    return score


def import_scores(session, exam_id: int, records: list[dict]) -> dict:
    """
    批量导入成绩预览记录（excel_handler.extract_scores 的输出）。

    - 系统里没有的学生自动新建（按 姓名+班级）；
    - 同一考试/学生/科目重复导入则更新原分数；
    - 分数为 None（缺考/空格）跳过不写，避免覆盖已有分数。
    返回 {created_students, scores_written, scores_updated, skipped_rows}。
    """
    exam = session.get(Exam, exam_id)
    if exam is None:
        raise ValueError(f"考试不存在：id={exam_id}")

    # 收集本次涉及的科目，用于补全满分配置
    subjects = set()
    created_students = scores_written = scores_updated = skipped_rows = 0
    known_students = {}  # (name, class) -> Student，避免同次导入重复查库

    for rec in records:
        name = rec.get("name")
        if not name:
            skipped_rows += 1
            continue
        class_name = rec.get("class_name")
        cache_key = (name, class_name)
        student = known_students.get(cache_key)
        if student is None:
            student, was_created = get_or_create_student(session, name, class_name)
            known_students[cache_key] = student
            if was_created:
                created_students += 1

        for subject, value in rec.get("scores", {}).items():
            if value is None:
                continue
            subjects.add(subject)
            score = _get_or_create_score(session, exam_id, student.id, subject)
            if score.score is None:
                scores_written += 1
            else:
                scores_updated += 1
            score.score = value

    # 新出现的科目补进满分配置（默认 100，老师可在考试管理里改）
    if subjects:
        saved = {}
        try:
            saved = json.loads(exam.full_scores) if exam.full_scores else {}
        except (TypeError, ValueError):
            saved = {}
        changed = False
        for s in subjects:
            if s not in saved:
                saved[s] = 100.0
                changed = True
        if changed:
            exam.full_scores = json.dumps(saved, ensure_ascii=False)

    session.flush()
    return {
        "created_students": created_students,
        "scores_written": scores_written,
        "scores_updated": scores_updated,
        "skipped_rows": skipped_rows,
    }


def exam_subjects(session, exam_id: int) -> list[str]:
    """这场考试实际录过分的科目，按名字排序。"""
    rows = (session.query(Score.subject)
            .filter(Score.exam_id == exam_id)
            .distinct().all())
    return sorted({r[0] for r in rows})


def exam_score_rows(session, exam_id: int) -> list[dict]:
    """
    取一场考试的宽表数据：每个学生一行。
    返回 [{student_id, name, class_name, 各科分数..., total}], 仅包含有成绩的学生。
    """
    exam = session.get(Exam, exam_id)
    if exam is None:
        return []
    subjects = exam_subjects(session, exam_id)
    # 直接查成绩对象，按学生聚合成宽表
    by_student = defaultdict(dict)
    meta = {}
    scores = (session.query(Score)
              .filter(Score.exam_id == exam_id).all())
    student_ids = {s.student_id for s in scores}
    students = {st.id: st for st in session.query(Student)
                .filter(Student.id.in_(student_ids)).all()}
    for s in scores:
        st = students.get(s.student_id)
        if st is None:
            continue
        by_student[st.id][s.subject] = s.score
        meta[st.id] = {"name": st.name, "class_name": st.class_name}

    result = []
    for student_id, subject_scores in by_student.items():
        valid = [v for v in subject_scores.values() if v is not None]
        total = round(sum(valid), 2) if valid else None
        row = {"student_id": student_id,
               "name": meta[student_id]["name"],
               "class_name": meta[student_id]["class_name"]}
        for s in subjects:
            row[s] = subject_scores.get(s)
        row["total"] = total
        result.append(row)
    return result


def _rank_within_class(rows: list[dict], key: str) -> None:
    """给宽表按班内某列（单科或 total）降序并列排名，写回 {key}_rank。"""
    groups = defaultdict(list)
    for row in rows:
        groups[row["class_name"]].append(row)
    for class_rows in groups.values():
        values = [r[key] for r in class_rows]
        ranks = stats_mod.competition_rank(values)
        for r, rank in zip(class_rows, ranks):
            r[f"{key}_rank"] = rank


def analyze_exam(session, exam_id: int, class_name: str | None = None) -> dict:
    """
    组装单次考试分析结果：科目列表、各科统计、分数段、排名表（含进退步）。
    class_name 为空时分析所有班。
    """
    exam = session.get(Exam, exam_id)
    if exam is None:
        return {}
    subjects = exam_subjects(session, exam_id)
    full_scores = full_scores_of(exam, subjects)
    rows = exam_score_rows(session, exam_id)
    if class_name:
        rows = [r for r in rows if r["class_name"] == class_name]

    # 各科班内排名 + 总分班内排名（写回每一行）
    for s in subjects:
        _rank_within_class(rows, s)
    _rank_within_class(rows, "total")

    # 各科统计指标
    subject_stats = {}
    for s in subjects:
        values = [r[s] for r in rows]
        summary = stats_mod.subject_summary(values, full_scores[s])
        subject_stats[s] = summary
    # 总分也给一组指标（满分=各科满分之和）
    total_full = round(sum(full_scores.values()), 2)
    totals = [r["total"] for r in rows]
    total_summary = stats_mod.subject_summary(totals, total_full)

    # 与上一次考试的进退步（按考试日期取前一场）
    deltas = _previous_exam_deltas(session, exam, rows, class_name)

    return {
        "exam": exam,
        "subjects": subjects,
        "full_scores": full_scores,
        "subject_stats": subject_stats,
        "total_full": total_full,
        "total_stats": total_summary,
        "rows": sorted(rows, key=lambda r: (r["class_name"] or "",
                                           r["total_rank"] or 9999)),
        "deltas": deltas,
    }


def analyze_subject(session, exam_id: int, subject: str,
                      class_name: str | None = None) -> dict:
    """
    单科视角分析（v1.2.4）：返回该科的指标、分数段、班内并列排名，
    以及与上场考试同科的分差/名次差。该科本场无成绩时返回空字典。
    """
    exam = session.get(Exam, exam_id)
    if exam is None:
        return {}
    subjects = exam_subjects(session, exam_id)
    if subject not in subjects:
        return {}
    full_scores = full_scores_of(exam, subjects)
    full_score = full_scores[subject]
    rows = exam_score_rows(session, exam_id)
    if class_name:
        rows = [r for r in rows if r["class_name"] == class_name]
    # 只保留参加了该科考试的学生
    rows = [r for r in rows if r.get(subject) is not None]
    if not rows:
        return {}

    _rank_within_class(rows, subject)
    values = [r[subject] for r in rows]
    summary = stats_mod.subject_summary(values, full_score)
    deltas = _previous_subject_deltas(session, exam, subject, rows, class_name)

    return {
        "exam": exam,
        "subject": subject,
        "full_score": full_score,
        "stats": summary,
        "rows": sorted(rows, key=lambda r: (r["class_name"] or "",
                                            r[f"{subject}_rank"] or 9999)),
        "deltas": deltas,
    }


def _previous_subject_deltas(session, exam: Exam, subject: str,
                             current_rows: list[dict],
                             class_name: str | None) -> dict:
    """单科口径：本场相对上场考试同科的分差与班内同科名次差。"""
    prev = _previous_exam(session, exam)
    if prev is None:
        return {}
    prev_rows = exam_score_rows(session, prev.id)
    if class_name:
        prev_rows = [r for r in prev_rows if r["class_name"] == class_name]
    prev_rows = [r for r in prev_rows if r.get(subject) is not None]
    if not prev_rows:
        return {}

    cur_map = {r["student_id"]: r[subject] for r in current_rows}
    prev_map = {r["student_id"]: r[subject] for r in prev_rows}
    raw = stats_mod.score_deltas(cur_map, prev_map)

    _rank_within_class(prev_rows, subject)
    prev_rank = {r["student_id"]: r[f"{subject}_rank"] for r in prev_rows}
    cur_rank = {r["student_id"]: r[f"{subject}_rank"] for r in current_rows}
    for sid, info in raw.items():
        if sid in prev_rank and sid in cur_rank and prev_rank[sid] and cur_rank[sid]:
            info["rank_delta"] = prev_rank[sid] - cur_rank[sid]
    return raw


def _previous_exam(session, exam: Exam) -> Optional[Exam]:
    """取日期早于本场、离它最近的一场考试。"""
    return (session.query(Exam)
            .filter(Exam.exam_date < exam.exam_date)
            .order_by(Exam.exam_date.desc(), Exam.id.desc()).first())


def _previous_exam_deltas(session, exam: Exam, current_rows: list[dict],
                          class_name: str | None) -> dict:
    """
    计算当前学生相对上次考试的总分进退步。
    返回 {student_id: {"score_delta": 总分差, "rank_delta": 名次差}}。
    """
    prev = _previous_exam(session, exam)
    if prev is None:
        return {}
    prev_rows = exam_score_rows(session, prev.id)
    if class_name:
        prev_rows = [r for r in prev_rows if r["class_name"] == class_name]

    cur_map = {r["student_id"]: r["total"] for r in current_rows}
    prev_map = {r["student_id"]: r["total"] for r in prev_rows}
    raw = stats_mod.score_deltas(cur_map, prev_map)

    # 名次变化按班内总分名次算（score_deltas 给的是全场排名，这里用班内更贴合老师视角）
    _rank_within_class(prev_rows, "total")
    prev_rank = {r["student_id"]: r["total_rank"] for r in prev_rows}
    cur_rank = {r["student_id"]: r["total_rank"] for r in current_rows}
    for sid, info in raw.items():
        if sid in prev_rank and sid in cur_rank and prev_rank[sid] and cur_rank[sid]:
            info["rank_delta"] = prev_rank[sid] - cur_rank[sid]
    return raw


def student_scores_over_time(session, student_id: int) -> list[dict]:
    """
    某个学生的历次成绩（按考试日期排序）：
    [{exam_id, exam_name, exam_date, 各科..., total}]
    """
    exams = list_exams(session)
    scores = (session.query(Score)
              .filter(Score.student_id == student_id).all())
    by_exam = defaultdict(dict)
    subjects_involved = set()
    for s in scores:
        by_exam[s.exam_id][s.subject] = s.score
        subjects_involved.add(s.subject)
    result = []
    for exam in exams:
        if exam.id not in by_exam:
            continue
        subject_scores = by_exam[exam.id]
        valid = [v for v in subject_scores.values() if v is not None]
        total = round(sum(valid), 2) if valid else None
        item = {"exam_id": exam.id, "exam_name": exam.name,
                "exam_date": exam.exam_date}
        for s in subjects_involved:
            item[s] = subject_scores.get(s)
        item["total"] = total
        result.append(item)
    return result


def class_trend(session, class_name: str | None = None,
                  subject: str | None = None) -> dict:
    """
    班级整体趋势：每次考试各科均分和总分均分。
    传 subject 时只返回该科均分序列（不混总分）；不传则维持全部科目+总分。
    返回 {"exams":[考试名...], "subjects":[科目...], "series": {科目: [均分...]}}。
    """
    exams = list_exams(session)
    all_subjects = set()
    points = []
    for exam in exams:
        rows = exam_score_rows(session, exam.id)
        if class_name:
            rows = [r for r in rows if r["class_name"] == class_name]
        if not rows:
            continue
        exam_subject_list = exam_subjects(session, exam.id)
        if subject is not None:
            # 单科视角：这场没该科成绩就跳过（保持 X 轴只画有该科的考试）
            if subject not in exam_subject_list:
                continue
            vals = [r[subject] for r in rows if r.get(subject) is not None]
            if not vals:
                continue
            points.append({"exam_name": exam.name,
                           "values": {subject: round(sum(vals) / len(vals), 2)}})
            continue
        all_subjects.update(exam_subject_list)
        point = {"exam_name": exam.name, "values": {}}
        for s in exam_subject_list:
            vals = [r[s] for r in rows if r[s] is not None]
            point["values"][s] = round(sum(vals) / len(vals), 2) if vals else None
        totals = [r["total"] for r in rows if r["total"] is not None]
        point["values"]["total"] = round(sum(totals) / len(totals), 2) if totals else None
        points.append(point)
    if subject is not None:
        return {"exams": [p["exam_name"] for p in points],
                "subjects": [subject],
                "series": {subject: [p["values"].get(subject) for p in points]}}
    subjects = sorted(all_subjects)
    series = {s: [p["values"].get(s) for p in points] for s in subjects}
    series["total"] = [p["values"].get("total") for p in points]
    return {"exams": [p["exam_name"] for p in points],
            "subjects": subjects, "series": series}