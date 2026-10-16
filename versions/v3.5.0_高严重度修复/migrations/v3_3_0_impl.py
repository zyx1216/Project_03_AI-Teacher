# -*- coding: utf-8 -*-
"""v3.3.0 迁移：扩展 teaching_progress 并创建 reminder_settings。"""
from __future__ import annotations
from sqlalchemy import inspect, text
NEW_TABLES = ("reminder_settings",)
NEW_COLUMNS = ("class_name", "chapter", "planned_date", "actual_date", "remark", "created_at")
def migrate(engine=None) -> dict:
    from models.models import Base
    from utils.db import engine as default_engine
    target_engine = engine or default_engine
    Base.metadata.create_all(bind=target_engine)
    inspector = inspect(target_engine)
    existing = set(inspector.get_table_names())
    added = []
    if "teaching_progress" in existing:
        cols = {c["name"] for c in inspector.get_columns("teaching_progress")}
        defs = {"class_name":"VARCHAR(50)", "chapter":"VARCHAR(200)", "planned_date":"DATE",
                "actual_date":"DATE", "remark":"TEXT", "created_at":"DATETIME"}
        with target_engine.begin() as conn:
            for name in NEW_COLUMNS:
                if name not in cols:
                    conn.execute(text(f"ALTER TABLE teaching_progress ADD COLUMN {name} {defs[name]}"))
                    added.append(name)
    inspector = inspect(target_engine); existing = set(inspector.get_table_names())
    return {"tables": [n for n in NEW_TABLES if n in existing], "columns": added}
