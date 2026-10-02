# -*- coding: utf-8 -*-
"""v2.9.0 迁移：创建 review_records，并补齐 homeworks.level。

可重复执行；只创建缺失表和缺失列，不修改字段类型、不删除数据。
"""

from __future__ import annotations

from sqlalchemy import inspect, text

NEW_TABLES = ("review_records",)


def migrate(engine=None) -> dict:
    """创建 v2.9.0 表和列；返回迁移摘要。"""
    from models.models import Base
    from utils.db import engine as default_engine

    target_engine = engine or default_engine
    Base.metadata.create_all(bind=target_engine)
    inspector = inspect(target_engine)
    existing_tables = set(inspector.get_table_names())
    added_columns: list[str] = []
    if "homeworks" in existing_tables:
        columns = {c["name"] for c in inspector.get_columns("homeworks")}
        if "level" not in columns:
            with target_engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE homeworks ADD COLUMN level VARCHAR(5)"))
            added_columns.append("homeworks.level")
    inspector = inspect(target_engine)
    existing_tables = set(inspector.get_table_names())
    return {
        "tables": [name for name in NEW_TABLES if name in existing_tables],
        "added_columns": added_columns,
    }
