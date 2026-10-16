# -*- coding: utf-8 -*-
"""v3.2.0 收藏与模板库服务。"""
from __future__ import annotations
import io, json, zipfile
from models.models import Favorite, Template
from utils import homework_service, lesson_service, question_service


def _json(value):
    return json.dumps(value or {}, ensure_ascii=False)


def add_favorite(session, item_type, item_id, title="", tags=None, remark=""):
    if item_type not in ("lesson_plan", "exam", "question"):
        raise ValueError("不支持的收藏类型。")
    row = session.query(Favorite).filter(Favorite.item_type == item_type,
                                         Favorite.item_id == int(item_id)).first()
    if row is None:
        row = Favorite(item_type=item_type, item_id=int(item_id))
    row.title = title or row.title
    row.tags = _json(tags or [])
    row.remark = remark
    session.add(row); session.flush(); return row


def remove_favorite(session, item_type, item_id):
    row = session.query(Favorite).filter(Favorite.item_type == item_type,
                                         Favorite.item_id == int(item_id)).first()
    if row:
        session.delete(row); session.flush()
    return bool(row)


def list_favorites(session, item_type=None, keyword=None):
    q = session.query(Favorite)
    if item_type:
        q = q.filter(Favorite.item_type == item_type)
    rows = q.order_by(Favorite.id.desc()).all()
    if keyword:
        key = str(keyword).lower()
        rows = [r for r in rows if key in (r.title or "").lower() or key in (r.tags or "").lower()]
    return rows


def resolve_favorite(session, row):
    if row.item_type == "lesson_plan":
        return session.get(lesson_service.LessonPlan, row.item_id)
    if row.item_type == "exam":
        return session.get(homework_service.Homework, row.item_id)
    if row.item_type == "question":
        return session.get(question_service.Question, row.item_id)
    return None


def create_template(session, template_type, name, content_json, tags=None, subject=None, grade=None):
    if template_type not in ("lesson_plan", "exam", "question"):
        raise ValueError("不支持的模板类型。")
    row = Template(template_type=template_type, name=str(name).strip(),
                   content_json=_json(content_json), tags=_json(tags or []),
                   subject=subject, grade=grade)
    session.add(row); session.flush(); return row


def list_templates(session, template_type=None, subject=None, grade=None, keyword=None, tag=None):
    q = session.query(Template)
    if template_type: q = q.filter(Template.template_type == template_type)
    if subject: q = q.filter(Template.subject == subject)
    if grade: q = q.filter(Template.grade == grade)
    rows = q.order_by(Template.id.desc()).all()
    if keyword:
        key = str(keyword).lower()
        rows = [r for r in rows if key in r.name.lower() or key in (r.tags or "").lower()]
    if tag:
        rows = [r for r in rows if str(tag) in (r.tags or "")]
    return rows


def delete_template(session, template_id):
    row = session.get(Template, int(template_id))
    if row:
        session.delete(row); session.flush()
    return bool(row)


def export_template_json(session, template_ids=None):
    q = session.query(Template)
    if template_ids:
        q = q.filter(Template.id.in_([int(x) for x in template_ids]))
    data = []
    for row in q.all():
        data.append({"id": row.id, "template_type": row.template_type,
                     "name": row.name, "content_json": json.loads(row.content_json or "{}"),
                     "tags": json.loads(row.tags or "[]"), "subject": row.subject,
                     "grade": row.grade})
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("templates.json", json.dumps(data, ensure_ascii=False, indent=2))
    return out.getvalue()
