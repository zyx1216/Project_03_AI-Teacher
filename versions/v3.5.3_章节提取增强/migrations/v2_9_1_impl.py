# -*- coding: utf-8 -*-
"""v2.9.1 迁移：创建 teaching_diagnosis / unit_plans / unit_lessons。

可重复执行；只创建缺失表，不修改字段类型、不删除数据。
"""

from __future__ import annotations

from sqlalchemy import inspect

NEW_TABLES = ("teaching_diagnosis", "unit_plans", "unit_lessons")


def migrate(engine=None) -> dict:
    from models.models import Base
    from utils.db import engine as default_engine

    target_engine = engine or default_engine
    Base.metadata.create_all(bind=target_engine)
    existing = set(inspect(target_engine).get_table_names())
    return {"tables": [name for name in NEW_TABLES if name in existing]}
