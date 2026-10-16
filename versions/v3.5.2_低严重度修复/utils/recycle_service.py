# -*- coding: utf-8 -*-
"""回收站服务（v3.4.0）。

删除教案/作业(试卷)/题目时，先把整行（含子表）快照进 recycle_bin，
再由原逻辑硬删；回收站保留 30 天，支持恢复、永久删除、清空。
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from sqlalchemy import Boolean, Date, DateTime, Float, Integer

from models.models import (
    Homework, HomeworkAnswer, HomeworkQuestion, HomeworkScore, LessonPlan,
    Question, RecycleBin,
)

ITEM_LABELS = {"lesson": "教案", "homework": "作业/试卷", "question": "题目"}
MODELS = {"lesson": LessonPlan, "homework": Homework, "question": Question}
RETENTION_DAYS = 30

# 每类的子表：类型 -> [(模型, 外键字段)]
CHILDREN = {
    "homework": [
        (HomeworkQuestion, "homework_id"),
        (HomeworkScore, "homework_id"),
        (HomeworkAnswer, "homework_id"),
    ],
    "question": [
        (HomeworkQuestion, "question_id"),
        (HomeworkAnswer, "question_id"),
    ],
    "lesson": [],
}


def _session():
    from utils.db import SessionLocal
    return SessionLocal()


def _row_dict(model, row) -> dict:
    """整行转 dict；日期转 ISO 字符串，便于 JSON 往返。"""
    data = {}
    for column in model.__table__.columns:
        value = getattr(row, column.name)
        if isinstance(value, datetime):
            data[column.name] = value.isoformat(sep=" ")
        elif isinstance(value, date):
            data[column.name] = value.isoformat()
        elif value is None or isinstance(value, (bool, int, float, str)):
            data[column.name] = value
        else:
            data[column.name] = str(value)
    return data


def _coerce(model, data: dict) -> dict:
    """按列类型把 JSON 里的值还原成 Python 值。"""
    result = {}
    for column in model.__table__.columns:
        if column.name not in data:
            continue
        value = data[column.name]
        if value is None:
            result[column.name] = None
        elif isinstance(column.type, DateTime):
            result[column.name] = datetime.fromisoformat(str(value))
        elif isinstance(column.type, Date):
            result[column.name] = date.fromisoformat(str(value)[:10])
        elif isinstance(column.type, Boolean):
            result[column.name] = bool(value)
        elif isinstance(column.type, Integer):
            result[column.name] = int(value)
        elif isinstance(column.type, Float):
            result[column.name] = float(value)
        else:
            result[column.name] = value
    return result


def _title(model, row) -> str:
    if model is Question:
        return str(row.content or "")[:80]
    return str(getattr(row, "name", None) or getattr(row, "title", None)
               or f"#{row.id}")[:200]


def move_to_bin(session, item_type: str, item_id: int,
                title: str | None = None) -> int | None:
    """把对象（含子表）快照进回收站；对象不存在时返回 None。"""
    model = MODELS.get(str(item_type))
    if model is None:
        return None
    row = session.get(model, int(item_id))
    if row is None:
        return None
    payload = {"main": _row_dict(model, row), "children": {}}
    for child_model, fk in CHILDREN.get(str(item_type), []):
        rows = (session.query(child_model)
                .filter(getattr(child_model, fk) == row.id).all())
        if rows:
            payload["children"][child_model.__tablename__] = [
                _row_dict(child_model, item) for item in rows]
    now = datetime.now()
    entry = RecycleBin(
        item_type=str(item_type), item_id=int(item_id),
        title=str(title) if title else _title(model, row),
        content_json=json.dumps(payload, ensure_ascii=False),
        deleted_at=now, expire_at=now + timedelta(days=RETENTION_DAYS))
    session.add(entry)
    session.flush()
    return entry.id


def list_items(session, item_type: str | None = None) -> list[dict]:
    """列出回收站条目，附剩余天数。"""
    query = session.query(RecycleBin)
    if item_type:
        query = query.filter(RecycleBin.item_type == str(item_type))
    rows = query.order_by(RecycleBin.deleted_at.desc(),
                          RecycleBin.id.desc()).all()
    now = datetime.now()
    result = []
    for row in rows:
        expire = row.expire_at
        days_left = ((expire - now).days if expire else RETENTION_DAYS)
        result.append({
            "id": row.id, "item_type": row.item_type,
            "item_label": ITEM_LABELS.get(row.item_type, row.item_type),
            "item_id": row.item_id, "title": row.title or "",
            "deleted_at": row.deleted_at, "expire_at": expire,
            "days_left": max(0, days_left),
        })
    return result


def restore(session, bin_id: int) -> dict:
    """按原主键恢复对象及其子表。"""
    entry = session.get(RecycleBin, int(bin_id))
    if entry is None:
        raise ValueError("回收站条目不存在。")
    model = MODELS.get(entry.item_type)
    if model is None:
        raise ValueError("该类型不支持恢复。")
    payload = json.loads(entry.content_json or "{}")
    main = payload.get("main") or {}
    original_id = int(main.get("id") or entry.item_id)
    if session.get(model, original_id) is not None:
        raise ValueError(f"原记录（ID {original_id}）仍存在，无法恢复。")
    session.add(model(**_coerce(model, main)))
    session.flush()
    for table, rows in (payload.get("children") or {}).items():
        child_model = next(
            (m for m, _ in CHILDREN.get(entry.item_type, [])
             if m.__tablename__ == table), None)
        if child_model is None:
            continue
        for row in rows:
            session.add(child_model(**_coerce(child_model, row)))
    session.delete(entry)
    session.flush()
    return {"item_type": entry.item_type, "item_id": original_id,
            "title": entry.title or ""}


def purge(session, bin_id: int) -> bool:
    """永久删除某条。"""
    entry = session.get(RecycleBin, int(bin_id))
    if entry is None:
        return False
    session.delete(entry)
    session.flush()
    return True


def empty(session, item_type: str | None = None) -> int:
    """清空回收站（可只清某一类），返回删除条数。"""
    query = session.query(RecycleBin)
    if item_type:
        query = query.filter(RecycleBin.item_type == str(item_type))
    rows = query.all()
    for row in rows:
        session.delete(row)
    session.flush()
    return len(rows)


def purge_expired(days: int = RETENTION_DAYS, session=None) -> int:
    """清掉已过期的条目；不传 session 时自建（启动清理用）。"""
    owns = session is None
    session = session or _session()
    try:
        limit = datetime.now()
        rows = (session.query(RecycleBin)
                .filter(RecycleBin.expire_at.isnot(None),
                        RecycleBin.expire_at < limit).all())
        for row in rows:
            session.delete(row)
        session.commit()
        return len(rows)
    finally:
        if owns:
            session.close()
