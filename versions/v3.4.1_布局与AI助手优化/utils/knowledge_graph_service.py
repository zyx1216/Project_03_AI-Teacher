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


# ---------------------------------------------------------------------------
# v2.7.0：RAG 知识图谱（节点/边构建与读写）
# ---------------------------------------------------------------------------

RELATION_TYPES = ("前置", "包含", "相似", "递进")


def list_nodes(session, material_id: int | None = None) -> list[dict]:
    """列出知识图谱节点。"""
    from models.models import KnowledgeNode
    q = session.query(KnowledgeNode)
    if material_id:
        q = q.filter(KnowledgeNode.material_id == material_id)
    return [{"id": n.id, "material_id": n.material_id, "name": n.name,
             "type": n.type or "", "importance": int(n.importance or 3),
             "description": n.description or ""}
            for n in q.order_by(KnowledgeNode.id.asc()).all()]


def list_edges(session, material_id: int | None = None) -> list[dict]:
    """列出知识图谱边；给 material_id 时只取该资料节点之间的边。"""
    from models.models import KnowledgeEdge, KnowledgeNode
    q = session.query(KnowledgeEdge)
    if material_id:
        ids = [n["id"] for n in list_nodes(session, material_id)]
        if not ids:
            return []
        q = q.filter(KnowledgeEdge.source_node_id.in_(ids),
                     KnowledgeEdge.target_node_id.in_(ids))
    return [{"id": e.id, "source": e.source_node_id, "target": e.target_node_id,
             "relation_type": e.relation_type, "weight": int(e.weight or 1)}
            for e in q.all()]


def save_graph(session, material_id: int, nodes: list[dict],
               edges: list[dict]) -> dict:
    """整份覆盖某资料的知识图谱（幂等重建）。返回节点/边数量。"""
    from models.models import KnowledgeNode, KnowledgeEdge
    old = (session.query(KnowledgeNode)
           .filter(KnowledgeNode.material_id == material_id).all())
    if old:
        old_ids = [n.id for n in old]
        (session.query(KnowledgeEdge)
         .filter((KnowledgeEdge.source_node_id.in_(old_ids))
                 | (KnowledgeEdge.target_node_id.in_(old_ids)))
         .delete(synchronize_session=False))
        for n in old:
            session.delete(n)
        session.flush()
    id_by_name = {}
    for item in nodes:
        name = str(item.get("name") or "").strip()
        if not name or name in id_by_name:
            continue
        node = KnowledgeNode(
            material_id=material_id, name=name,
            type=str(item.get("type") or "")[:30] or None,
            importance=max(1, min(5, int(item.get("importance") or 3))),
            description=str(item.get("description") or "")[:500] or None)
        session.add(node)
        session.flush()
        id_by_name[name] = node.id
    saved_edges = 0
    for e in edges:
        src = id_by_name.get(str(e.get("source") or "").strip())
        dst = id_by_name.get(str(e.get("target") or "").strip())
        rel = str(e.get("relation_type") or "相似").strip()
        if not src or not dst or src == dst:
            continue
        if rel not in RELATION_TYPES:
            rel = "相似"
        session.add(KnowledgeEdge(
            source_node_id=src, target_node_id=dst, relation_type=rel,
            weight=max(1, min(5, int(e.get("weight") or 1)))))
        saved_edges += 1
    session.flush()
    return {"nodes": len(id_by_name), "edges": saved_edges}


def build_graph_from_material(session, material_id: int, chat_func=None) -> dict:
    """从资料正文构建知识图谱（v2.7.0）。

    AI 可用时抽取知识点与关系；不可用或失败时按章节标题建确定性节点。
    """
    from utils import rag_service
    import json as _json
    import re as _re

    chunks = rag_service.load_chunks_for(session, material_id)
    if not chunks:
        return {"nodes": 0, "edges": 0, "source": "empty",
                "reason": "资料没有正文，无法构建图谱。"}
    # 章节标题作为兜底节点来源
    chapter_titles = []
    for c in chunks:
        title = str(c.get("chapter_title") or c.get("chapter") or "").strip()
        if title and title not in chapter_titles:
            chapter_titles.append(title)

    text = "\n".join(str(c.get("text") or "") for c in chunks)[:6000]
    nodes, edges, source = [], [], "fallback"
    if chat_func is not None:
        system = (
            "你是知识图谱抽取助手。只输出 JSON："
            '{"nodes":[{"name":"知识点","type":"概念|公式|定理","importance":1-5,'
            '"description":"简述"}],'
            '"edges":[{"source":"知识点A","target":"知识点B",'
            '"relation_type":"前置|包含|相似|递进","weight":1-5}]}。'
            "只依据给定文本，不要编造。")
        try:
            raw = chat_func(system, f"资料文本：\n{text}")
            data = _json.loads(_re.sub(r"^```(?:json)?|```$", "",
                                       str(raw).strip(), flags=_re.M))
            nodes = [n for n in (data.get("nodes") or []) if isinstance(n, dict)]
            edges = [e for e in (data.get("edges") or []) if isinstance(e, dict)]
            if nodes:
                source = "ai"
        except Exception:  # noqa: BLE001 —— AI 失败回落到章节节点
            nodes, edges = [], []
    if not nodes:
        nodes = [{"name": t, "type": "章节", "importance": 3,
                  "description": "由章节标题生成"} for t in chapter_titles]
        edges = []
    if not nodes:
        return {"nodes": 0, "edges": 0, "source": "empty",
                "reason": "未能识别出知识点。"}
    saved = save_graph(session, material_id, nodes, edges)
    saved["source"] = source
    saved["reason"] = "" if source == "ai" else "未用 AI，按章节标题生成。"
    return saved


def graph_for_visual(session, material_id: int | None = None,
                     subject: str | None = None) -> dict:
    """图谱可视化数据：节点（含掌握度颜色/大小）+ 边。

    掌握度颜色复用 build_mastery（绿/黄/红），匹配不上时用默认灰。
    """
    nodes = list_nodes(session, material_id)
    if not nodes:
        return {"nodes": [], "edges": [], "empty": True}
    rate_by_kp = {}
    if subject:
        try:
            matrix = build_mastery(session, subject)
            for row in (matrix.get("kps") or []):
                name = row.get("knowledge_point") or row.get("name")
                if name is not None:
                    rate_by_kp[str(name)] = row.get("rate")
        except Exception:  # noqa: BLE001
            rate_by_kp = {}
    for n in nodes:
        rate = rate_by_kp.get(n["name"])
        n["rate"] = rate
        if rate is None:
            n["color"] = "#9ca3af"
        elif rate >= 0.8:
            n["color"] = "#16a34a"
        elif rate >= 0.6:
            n["color"] = "#f59e0b"
        else:
            n["color"] = "#dc2626"
        n["size"] = 12 + int(n.get("importance") or 3) * 4
    return {"nodes": nodes, "edges": list_edges(session, material_id),
            "empty": False}


def prerequisites_of(session, material_id: int, name: str) -> list[str]:
    """某知识点的前置知识（沿“前置/递进”边反向追溯一层）。"""
    from models.models import KnowledgeNode, KnowledgeEdge
    node = (session.query(KnowledgeNode)
            .filter(KnowledgeNode.material_id == material_id,
                    KnowledgeNode.name == name).first())
    if node is None:
        return []
    edges = (session.query(KnowledgeEdge)
             .filter(KnowledgeEdge.target_node_id == node.id,
                     KnowledgeEdge.relation_type.in_(["前置", "递进"])).all())
    names = []
    for e in edges:
        src = session.get(KnowledgeNode, e.source_node_id)
        if src is not None:
            names.append(src.name)
    return names


def learning_path(session, material_id: int, name: str, depth: int = 5) -> list[str]:
    """想学某知识点，按前置关系回溯出学习路径（先学的排前面）。"""
    path, seen, queue = [], {name}, [name]
    for _ in range(max(1, int(depth))):
        nxt = []
        for target in queue:
            for pre in prerequisites_of(session, material_id, target):
                if pre not in seen:
                    seen.add(pre)
                    path.append(pre)
                    nxt.append(pre)
        if not nxt:
            break
        queue = nxt
    path.reverse()
    path.append(name)
    return path
# ---------------------------------------------------------------------------
# v3.3.0：知识点详情、备课推荐、出题覆盖率
# ---------------------------------------------------------------------------

def _approved_kp_count(session, subject) -> dict:
    """{知识点: 已审核题数}。"""
    counts: dict[str, int] = {}
    questions = (session.query(Question)
                 .filter(Question.subject == subject,
                         Question.status == "approved").all())
    for q in questions:
        for kp in qs.knowledge_points_list(q) or []:
            counts[kp] = counts.get(kp, 0) + 1
    return counts


def _node_by_name(session) -> dict:
    """{知识点名称: 节点}，同名取重要程度最高的那个。"""
    from models.models import KnowledgeNode
    result: dict = {}
    for node in session.query(KnowledgeNode).all():
        cur = result.get(node.name)
        if cur is None or int(node.importance or 3) > int(cur.importance or 3):
            result[node.name] = node
    return result


def subject_graph(session, subject: str | None = None,
                  grade: str | None = None) -> dict:
    """按学科汇总知识图谱：同名知识点合并，边按名称重挂。"""
    from models.models import KnowledgeEdge, KnowledgeNode, Textbook
    q = (session.query(KnowledgeNode)
         .outerjoin(Textbook, KnowledgeNode.material_id == Textbook.id))
    if subject:
        q = q.filter(Textbook.subject == subject)
    if grade:
        q = q.filter(Textbook.grade == grade)
    nodes = q.all()

    by_name: dict[str, dict] = {}
    for n in nodes:
        cur = by_name.get(n.name)
        item = {"id": n.name, "name": n.name, "type": n.type or "",
                "importance": int(n.importance or 3),
                "description": n.description or ""}
        if cur is None or item["importance"] > cur["importance"]:
            by_name[n.name] = item

    id_to_name = {n.id: n.name for n in nodes}
    edges, seen = [], set()
    for e in session.query(KnowledgeEdge).all():
        src = id_to_name.get(e.source_node_id)
        dst = id_to_name.get(e.target_node_id)
        if not src or not dst or src == dst:
            continue
        key = (src, dst, e.relation_type)
        if key in seen:
            continue
        seen.add(key)
        edges.append({"source": src, "target": dst,
                      "relation_type": e.relation_type,
                      "weight": int(e.weight or 1)})
    return {"nodes": list(by_name.values()), "edges": edges}


def prerequisites_of_node(session, node) -> list[str]:
    """沿“前置/递进”边反向找一层（直接收节点对象）。"""
    from models.models import KnowledgeEdge, KnowledgeNode
    edges = (session.query(KnowledgeEdge)
             .filter(KnowledgeEdge.target_node_id == node.id,
                     KnowledgeEdge.relation_type.in_(["前置", "递进"])).all())
    names = []
    for e in edges:
        src = session.get(KnowledgeNode, e.source_node_id)
        if src is not None:
            names.append(src.name)
    return names


def node_detail_by_name(session, name: str, subject: str | None = None,
                        importance=None, type_name: str = "",
                        description: str = "") -> dict:
    """知识点详情：题量、相关教案、班级平均掌握度、教学建议。"""
    from sqlalchemy import func

    from models.models import KnowledgeNode, LessonPlan
    node = (session.query(KnowledgeNode)
            .filter(KnowledgeNode.name == name).first())
    counts = _approved_kp_count(session, subject) if subject else {}
    plan_count = (session.query(func.count(LessonPlan.id))
                  .filter(LessonPlan.chapter.like(f"%{name}%")).scalar()) or 0

    avg_mastery = None
    if subject:
        try:
            mastery = build_mastery(session, subject)
            rates = [kp_map[name] for kp_map in mastery["matrix"].values()
                     if name in kp_map]
            if rates:
                avg_mastery = round(sum(rates) / len(rates), 1)
        except Exception:  # noqa: BLE001 —— 没有作答数据时留空
            avg_mastery = None

    level = int(importance if importance is not None
                else (node.importance if node else 3) or 3)
    if avg_mastery is not None and avg_mastery < 60:
        suggestion = "该知识点当前掌握薄弱，建议先复习概念再安排过关小测。"
    elif level >= 4:
        suggestion = "这是重点知识点，建议课堂重点讲解并配典型例题。"
    else:
        suggestion = "按正常课时讲解，配合基础练习即可。"
    return {
        "id": node.id if node else None,
        "name": name,
        "type": type_name or (node.type if node else "") or "",
        "importance": level,
        "description": description or (node.description if node else "") or "",
        "question_count": counts.get(name, 0),
        "plan_count": int(plan_count),
        "avg_mastery": avg_mastery,
        "suggestion": suggestion,
    }


def node_detail(session, node_id: int, subject: str | None = None) -> dict:
    """单个知识点详情（按节点 ID）。"""
    from models.models import KnowledgeNode
    node = session.get(KnowledgeNode, int(node_id))
    if node is None:
        return {"error": "知识点不存在。"}
    return node_detail_by_name(
        session, node.name, subject, importance=int(node.importance or 3),
        type_name=node.type or "", description=node.description or "")


def recommend_for_chapter(session, subject: str, chapter_text: str,
                          limit: int = 8) -> list[dict]:
    """备课时按章节推荐知识点：名称匹配、题多的排前面，带前置关系。"""
    chapter_text = str(chapter_text or "")
    counts = _approved_kp_count(session, subject)
    by_name = _node_by_name(session)
    prereq = {}
    for name, node in by_name.items():
        pre = prerequisites_of_node(session, node)
        if pre:
            prereq[name] = pre

    def sort_key(name: str):
        node = by_name.get(name)
        importance = int(node.importance) if node else 3
        return (0 if name in chapter_text else 1,
                -counts.get(name, 0), -importance)

    result = []
    for name in sorted(set(counts) | set(by_name), key=sort_key)[:max(1, int(limit))]:
        node = by_name.get(name)
        result.append({
            "name": name,
            "question_count": counts.get(name, 0),
            "importance": int(node.importance) if node else 3,
            "description": (node.description or "") if node else "",
            "prerequisites": prereq.get(name, []),
        })
    return result


def coverage_rows(session, subject: str,
                  selected_kps: list[str]) -> list[dict]:
    """出题覆盖率：每个知识点是否已选、题库里有几道题。"""
    selected = {str(x) for x in (selected_kps or [])}
    counts = _approved_kp_count(session, subject)
    names = set(counts) | set(_node_by_name(session))
    return [{"name": n, "covered": n in selected,
             "question_count": counts.get(n, 0)} for n in sorted(names)]
