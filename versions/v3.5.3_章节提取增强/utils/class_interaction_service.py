# -*- coding: utf-8 -*-
"""v3.2.0 课堂互动服务。"""
from __future__ import annotations
import json, random
from models.models import ClassInteractionLog
from utils import student_service


def log_interaction(session, class_name, interaction_type, detail=None):
    row = ClassInteractionLog(class_name=class_name, interaction_type=interaction_type,
                              detail_json=json.dumps(detail or {}, ensure_ascii=False))
    session.add(row)
    session.flush()
    return row


def list_interactions(session, class_name=None, limit=100):
    q = session.query(ClassInteractionLog)
    if class_name:
        q = q.filter(ClassInteractionLog.class_name == class_name)
    return q.order_by(ClassInteractionLog.id.desc()).limit(limit).all()


def _students(session, class_name):
    return student_service.list_students(session, class_name=class_name)


def weak_weights(session, class_name):
    from models.models import Score
    students = _students(session, class_name)
    weights = []
    for stu in students:
        vals = [float(v) for (v,) in session.query(Score.score).filter(
            Score.student_id == stu.id, Score.score.isnot(None)).all()]
        avg = sum(vals) / len(vals) if vals else 60
        weights.append(max(1.0, 100 - avg))
    return weights


def pick_student(session, class_name, mode="均匀随机", weights=None, exclude_ids=None):
    students = _students(session, class_name)
    used = set(exclude_ids or [])
    pool = [stu for stu in students if stu.id not in used]
    if not pool:
        raise ValueError("没有可点名的学生。")
    if mode == "薄弱学生优先":
        score_weights = weak_weights(session, class_name)
        mapping = {stu.id: weight for stu, weight in zip(students, score_weights)}
        chosen = random.choices(pool, weights=[mapping[stu.id] for stu in pool], k=1)[0]
    elif mode == "自定义权重" and weights:
        chosen = random.choices(
            pool,
            weights=[max(0.01, float(weights.get(str(stu.id), weights.get(stu.id, 1)))) for stu in pool],
            k=1)[0]
    else:
        chosen = random.choice(pool)
    return {"student_id": chosen.id, "name": chosen.name, "class_name": chosen.class_name}


def create_groups(session, class_name, group_count=2):
    students = _students(session, class_name)
    group_count = max(2, min(6, int(group_count)))
    random.shuffle(students)
    groups = [[] for _ in range(group_count)]
    for index, stu in enumerate(students):
        groups[index % group_count].append({"student_id": stu.id, "name": stu.name})
    return groups
