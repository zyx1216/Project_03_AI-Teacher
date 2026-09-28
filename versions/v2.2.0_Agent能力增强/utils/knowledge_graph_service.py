# -*- coding: utf-8 -*-
"""学生知识图谱服务（v1.9.0）。

掌握度口径：
- 只用逐题批改的 HomeworkAnswer，不把考试总分分摊到知识点；
- 单条作答权重 = 时间衰减权重 × 难度权重；
- 时间权重按半衰期：0.5 ** (距今天数 / decay_days)；
- 难度权重：基础 1.0、中等 1.3、拓展 1.6；
- 有 earned_score 且题目有分值时按得分率；否则按 is_correct 取 1/0。
"""

from __future__ import annotations

from datetime import datetime

from models.models import (
    Homework, HomeworkAnswer, HomeworkQuestion, Question, Student,
)
from utils.app_config import DEFAULT_SUBJECT
from utils import llm_client
from utils import question_service as qs

DIFFICULTY_WEIGHT = {1: 1.0, 2: 1.3, 3: 1.6}


def _answer_rate(ans: HomeworkAnswer, question: Question,
                 link: HomeworkQuestion | None) -> float | None:
    """取单条作答的得分率；无法判定返回 None。"""
    if ans.earned_score is not None and link is not None and link.score:
        rate = float(ans.earned_score) / float(link.score)
        return min(1.0, max(0.0, rate))
    if ans.is_correct is not None:
        return 1.0 if ans.is_correct else 0.0
    return None


def mastery_color(rate: float) -> str:
    """红黄绿分级：<60 红，60-80 黄，>80 绿。"""
    if rate < 0.6:
        return "red"
    if rate <= 0.8:
        return "yellow"
    return "green"


def build_mastery(session, subject, grade=None, class_names=None,
                  student_id=None, homework_ids=None,
                  decay_days=180) -> dict:
    """构建学生 × 知识点掌握度。

    返回 {students, knowledge_points, matrix, personal, weak_top5, recommendations}
    matrix：{student_id: {kp: 百分制掌握度}}
    """
    subject = subject or DEFAULT_SUBJECT
    today = datetime.now()

    q = (session.query(HomeworkAnswer, Question, HomeworkQuestion, Student)
         .join(Question, HomeworkAnswer.question_id == Question.id)
         .join(Student, HomeworkAnswer.student_id == Student.id)
         .outerjoin(HomeworkQuestion,
                    (HomeworkQuestion.homework_id == HomeworkAnswer.homework_id)
                    & (HomeworkQuestion.question_id == HomeworkAnswer.question_id))
         .filter(Question.subject == subject))
    if grade:
        q = q.filter(Question.grade == grade)
    if class_names:
        q = q.filter(Student.class_name.in_(list(class_names)))
    if student_id is not None:
        q = q.filter(Student.id == student_id)
    if homework_ids:
        q = q.filter(HomeworkAnswer.homework_id.in_(list(homework_ids)))
    rows = q.all()

    # acc[student_id][kp] = {"weighted": 加权得分和, "weight": 权重和}
    acc: dict[int, dict[str, dict]] = {}
    student_meta: dict[int, Student] = {}

    for ans, question, link, stu in rows:
        rate = _answer_rate(ans, question, link)
        if rate is None:
            continue
        days = (today - (ans.created_at or today)).days
        time_weight = 0.5 ** (max(0, days) / decay_days)
        weight = time_weight * DIFFICULTY_WEIGHT.get(question.difficulty, 1.3)
        kps = qs.knowledge_points_list(question) or ["未标注"]
        bucket = acc.setdefault(stu.id, {})
        student_meta[stu.id] = stu
        for kp in kps:
            item = bucket.setdefault(kp, {"weighted": 0.0, "weight": 0.0})
            item["weighted"] += rate * weight
            item["weight"] += weight

    # 汇总成百分制矩阵。
    matrix: dict[int, dict[str, float]] = {}
    all_kps: set[str] = set()
    for sid, kp_map in acc.items():
        matrix[sid] = {}
        for kp, item in kp_map.items():
            rate = item["weighted"] / item["weight"] if item["weight"] else 0.0
            matrix[sid][kp] = round(rate * 100, 1)
            all_kps.add(kp)

    personal = _personal_lists(matrix, student_meta)
    weak_top5 = _weak_top5(matrix, student_meta)
    recommendations = _recommend_questions(session, subject, weak_top5)

    return {
        "subject": subject,
        "students": [{"student_id": sid, "name": s.name,
                      "class_name": s.class_name}
                     for sid, s in sorted(student_meta.items())],
        "knowledge_points": sorted(all_kps),
        "matrix": matrix,
        "personal": personal,
        "weak_top5": weak_top5,
        "recommendations": recommendations,
    }


def _personal_lists(matrix, student_meta) -> list[dict]:
    """每个学生的个人掌握列表（含红黄绿等级）。"""
    result = []
    for sid, kp_map in matrix.items():
        stu = student_meta.get(sid)
        items = [{"knowledge_point": kp, "rate": rate,
                  "color": mastery_color(rate / 100)}
                 for kp, rate in kp_map.items()]
        items.sort(key=lambda x: x["rate"])
        result.append({
            "student_id": sid,
            "name": stu.name if stu else str(sid),
            "class_name": stu.class_name if stu else None,
            "items": items,
        })
    return result


def _weak_top5(matrix, student_meta, top_n: int = 5) -> list[dict]:
    """全班平均掌握度最低的 Top5 知识点。"""
    totals: dict[str, list[float]] = {}
    for sid, kp_map in matrix.items():
        for kp, rate in kp_map.items():
            totals.setdefault(kp, []).append(rate)
    ranked = sorted(
        ((kp, round(sum(v) / len(v), 1)) for kp, v in totals.items()),
        key=lambda x: x[1])
    return [{"knowledge_point": kp, "avg_rate": rate,
             "color": mastery_color(rate / 100)}
            for kp, rate in ranked[:top_n]]


def _recommend_questions(session, subject, weak_top5) -> dict:
    """按薄弱点推荐同学科、已审核题目 ID。"""
    weak_kps = [w["knowledge_point"] for w in weak_top5
                if w["knowledge_point"] != "未标注"]
    pool = qs.list_questions(session, status="approved", subject=subject)
    recs: dict[str, list[int]] = {}
    for kp in weak_kps:
        ids = [q.id for q in pool
               if kp in qs.knowledge_points_list(q)][:5]
        if ids:
            recs[kp] = ids
    return recs


# ---------------------------------------------------------------------------
# v1.9.2：知识点掌握追踪
# ---------------------------------------------------------------------------

def _answer_rate_value(ans: HomeworkAnswer, link: HomeworkQuestion | None):
    """返回单题得分率和题目原始分值。"""
    if link is not None and link.score:
        rate = _answer_rate(ans, question=None, link=link)
        return rate, float(link.score)
    if ans.is_correct is not None:
        return 1.0 if ans.is_correct else 0.0, None
    return None, None


def _question_allocations(question: Question) -> list[tuple[str, float]]:
    """题目在各知识点上的分值权重；多知识点均摊。"""
    kps = qs.knowledge_points_list(question) or ["未标注"]
    kps = [str(item).strip() or "未标注" for item in kps]
    return [(kp, 1.0 / len(kps)) for kp in kps]


def _homework_sort_time(hw: Homework):
    """趋势排序时间：优先完成时间，没有则用创建时间。"""
    return hw.completed_at or hw.created_at


def _collect_answer_rows(session, subject: str):
    """取某学科全部逐题作答及题目、关联、学生信息。"""
    return (session.query(HomeworkAnswer, Question, HomeworkQuestion, Student, Homework)
            .join(Question, HomeworkAnswer.question_id == Question.id)
            .join(Student, HomeworkAnswer.student_id == Student.id)
            .join(Homework, HomeworkAnswer.homework_id == Homework.id)
            .outerjoin(HomeworkQuestion,
                       (HomeworkQuestion.homework_id == HomeworkAnswer.homework_id)
                       & (HomeworkQuestion.question_id == HomeworkAnswer.question_id))
            .filter(Question.subject == subject)
            .filter(Homework.is_template.is_(False))
            .all())


def list_trend_subjects(session) -> list[str]:
    """列出存在逐题作答数据的学科。"""
    rows = (session.query(Question.subject)
            .join(HomeworkAnswer, HomeworkAnswer.question_id == Question.id)
            .filter(Question.subject.isnot(None))
            .distinct().all())
    return sorted({str(item[0]).strip() for item in rows if item[0]})


def _relevant_homework_ids(session, subject: str, knowledge_points: list[str],
                           class_names: list[str] | None = None) -> set[int]:
    """找出包含所选知识点的非模板作业；有题无答时用于生成 None 断点。"""
    selected = set(str(item).strip() for item in knowledge_points if str(item).strip())
    query = (session.query(Homework, Question)
             .join(HomeworkQuestion, HomeworkQuestion.homework_id == Homework.id)
             .join(Question, HomeworkQuestion.question_id == Question.id)
             .filter(Question.subject == subject)
             .filter(Homework.is_template.is_(False)))
    if class_names:
        query = query.filter(Homework.class_name.in_(list(class_names)))

    result = set()
    for hw, question in query.all():
        kps = qs.knowledge_points_list(question) or ["未标注"]
        if selected.intersection(kps):
            result.add(int(hw.id))
    return result


def list_trend_knowledge_points(session, subject: str) -> list[str]:
    """列出某学科逐题作答中出现过的知识点。"""
    result: set[str] = set()
    for _ans, question, _link, _stu, _hw in _collect_answer_rows(session, subject):
        result.update(qs.knowledge_points_list(question) or ["未标注"])
    return sorted(result)


def _slope_label(values: list[float]) -> tuple[str, float]:
    """按最近至少3个点判断趋势，返回标签和斜率。"""
    points = [float(v) for v in values if v is not None][-3:]
    if len(points) < 3:
        return "数据不足", 0.0
    xs = list(range(len(points)))
    mean_x = sum(xs) / len(xs)
    mean_y = sum(points) / len(points)
    denominator = sum((x - mean_x) ** 2 for x in xs)
    slope = sum((x - mean_x) * (y - mean_y)
                for x, y in zip(xs, points)) / denominator if denominator else 0.0
    if slope > 0.02:
        return "上升", slope
    if slope < -0.02:
        return "下降", slope
    return "稳定", slope


def _events_from_buckets(homework_meta: dict, buckets: dict) -> list[dict]:
    """把按作业聚合的结果整理成时间线事件。"""
    events = []
    for hw_id, meta in homework_meta.items():
        rates = {}
        for kp, item in buckets.get(hw_id, {}).items():
            rates[kp] = round(item["numerator"] / item["denominator"] * 100, 1) \
                if item["denominator"] else None
        events.append({
            "homework_id": hw_id,
            "homework_name": meta["name"],
            "date": meta["time"].strftime("%Y-%m-%d") if meta["time"] else "",
            "rates": rates,
        })
    return sorted(events, key=lambda item: item["date"])


def get_knowledge_trend(session, subject: str, knowledge_points: list[str],
                        class_names: list[str] | None = None) -> dict:
    """按班级统计多个知识点在历次逐题作业中的掌握率。"""
    subject = subject or DEFAULT_SUBJECT
    selected = [str(item).strip() for item in knowledge_points if str(item).strip()]
    class_set = {str(item).strip() for item in (class_names or []) if str(item).strip()}
    homework_meta: dict[int, dict] = {}
    buckets: dict[int, dict[str, dict]] = {}
    relevant_ids = _relevant_homework_ids(
        session, subject, selected, list(class_set) if class_set else None)

    for relevant_id in relevant_ids:
        hw = session.get(Homework, relevant_id)
        if hw is not None:
            homework_meta.setdefault(relevant_id, {
                "name": hw.name, "time": _homework_sort_time(hw)})

    for ans, question, link, student, hw in _collect_answer_rows(session, subject):
        if class_set and (student.class_name or "未分班") not in class_set:
            continue
        rate, _score = _answer_rate_value(ans, link)
        if rate is None:
            continue
        hw_id = int(hw.id)
        homework_meta.setdefault(hw_id, {
            "name": hw.name, "time": _homework_sort_time(hw)})
        hw_bucket = buckets.setdefault(hw_id, {})
        for kp, allocation_weight in _question_allocations(question):
            if kp not in selected:
                continue
            item = hw_bucket.setdefault(kp, {"numerator": 0.0,
                                             "denominator": 0.0})
            item["numerator"] += rate * allocation_weight
            item["denominator"] += allocation_weight

    events = _events_from_buckets(homework_meta, buckets)
    series = {kp: [event["rates"].get(kp) for event in events]
              for kp in selected}
    trends = {kp: _slope_label(values) for kp, values in series.items()}
    return {"subject": subject, "events": events, "series": series,
            "trends": trends}


def get_student_knowledge_trend(session, student_id: int,
                                subject: str) -> dict:
    """统计单个学生各知识点掌握率，并与所在班级平均比较。"""
    subject = subject or DEFAULT_SUBJECT
    student = session.get(Student, int(student_id))
    if student is None:
        raise ValueError(f"学生不存在：id={student_id}")

    class_names = [student.class_name] if student.class_name else None
    relevant_ids = _relevant_homework_ids(
        session, subject, list_trend_knowledge_points(session, subject),
        class_names)
    class_result = get_knowledge_trend(session, subject,
                                       list_trend_knowledge_points(session, subject),
                                       class_names)
    events = class_result["events"]
    student_set = {int(student_id)}
    student_meta: dict[int, dict] = {}
    student_buckets: dict[int, dict[str, dict]] = {}

    for relevant_id in relevant_ids:
        hw = session.get(Homework, relevant_id)
        if hw is not None:
            student_meta.setdefault(relevant_id, {
                "name": hw.name, "time": _homework_sort_time(hw)})

    for ans, question, link, row_student, hw in _collect_answer_rows(session, subject):
        if row_student.id not in student_set:
            continue
        rate, _score = _answer_rate_value(ans, link)
        if rate is None:
            continue
        hw_id = int(hw.id)
        student_meta.setdefault(hw_id, {"name": hw.name,
                                        "time": _homework_sort_time(hw)})
        hw_bucket = student_buckets.setdefault(hw_id, {})
        for kp, allocation_weight in _question_allocations(question):
            item = hw_bucket.setdefault(kp, {"numerator": 0.0,
                                             "denominator": 0.0})
            item["numerator"] += rate * allocation_weight
            item["denominator"] += allocation_weight

    student_events = _events_from_buckets(student_meta, student_buckets)
    student_by_hw = {event["homework_id"]: event["rates"]
                     for event in student_events}
    all_kps = sorted({kp for rates in student_by_hw.values() for kp in rates})
    class_by_hw = {event["homework_id"]: event["rates"]
                   for event in events}

    merged_events = []
    for event in student_events:
        hw_id = event["homework_id"]
        class_rates = class_by_hw.get(hw_id, {})
        merged_events.append({
            "homework_id": hw_id,
            "homework_name": event["homework_name"],
            "date": event["date"],
            "student_rates": event["rates"],
            "class_rates": class_rates,
        })

    student_series = {kp: [event["student_rates"].get(kp)
                           for event in merged_events] for kp in all_kps}
    class_series = {kp: [event["class_rates"].get(kp)
                         for event in merged_events] for kp in all_kps}
    latest = [(kp, values[-1]) for kp, values in student_series.items()
              if values and values[-1] is not None]
    strengths = [kp for kp, value in sorted(latest, key=lambda x: x[1], reverse=True)
                 if value >= 80]
    weak_points = [kp for kp, value in sorted(latest, key=lambda x: x[1])
                   if value < 60]
    trends = {kp: _slope_label(values) for kp, values in student_series.items()}
    return {"subject": subject, "events": merged_events,
            "student_series": student_series, "class_series": class_series,
            "strengths": strengths, "weak_points": weak_points,
            "trends": trends}


def analyze_knowledge_trend(subject: str, knowledge_points: list[str],
                            events: list[dict]) -> str:
    """让 AI 根据知识点趋势数据生成中文原因分析和教学建议。"""
    lines = [f"学科：{subject}", f"知识点：{'、'.join(knowledge_points)}"]
    for event in events:
        values = []
        for kp in knowledge_points:
            value = event["rates"].get(kp)
            values.append(f"{kp}={'数据缺失' if value is None else str(value) + '%'}")
        lines.append(f"- {event['date']} {event['homework_name']}：" + "，".join(values))
    system_prompt = "你是教学分析专家。请根据知识点掌握率变化，分析原因并给出具体教学建议。"
    user_text = "\n".join(lines)
    return llm_client.chat_content(system_prompt, user_text, temperature=0.4)
