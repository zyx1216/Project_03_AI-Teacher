# -*- coding: utf-8 -*-
"""v3.4.0 迁移：家校沟通留档、版本历史、回收站、导出模板四张表。"""
from __future__ import annotations
from sqlalchemy import inspect
NEW_TABLES = ("parent_communication", "version_history", "recycle_bin", "export_templates")
def migrate(engine=None) -> dict:
    from models.models import Base
    from utils.db import engine as default_engine
    target_engine = engine or default_engine
    Base.metadata.create_all(bind=target_engine)
    inspector = inspect(target_engine)
    existing = set(inspector.get_table_names())
    return {"tables": [n for n in NEW_TABLES if n in existing], "columns": []}
