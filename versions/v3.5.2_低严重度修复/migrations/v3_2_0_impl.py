# -*- coding: utf-8 -*-
"""v3.2.0 迁移：创建互动日志、收藏和模板表。"""
from __future__ import annotations
from sqlalchemy import inspect
NEW_TABLES = ("class_interaction_logs", "favorites", "templates")
def migrate(engine=None) -> dict:
    from models.models import Base
    from utils.db import engine as default_engine
    target_engine = engine or default_engine
    Base.metadata.create_all(bind=target_engine)
    existing = set(inspect(target_engine).get_table_names())
    return {"tables": [name for name in NEW_TABLES if name in existing]}
