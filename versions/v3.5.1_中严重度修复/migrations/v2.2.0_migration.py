# -*- coding: utf-8 -*-
"""v2.2.0 迁移：创建 teaching_progress、agent_memory 两张表。

可重复执行；只创建缺失表，不修改已有 18 张表结构。
"""

from __future__ import annotations

from sqlalchemy import inspect

NEW_TABLES = ("teaching_progress", "agent_memory")


def migrate(engine=None) -> dict:
    """检查并创建 v2.2.0 新表。"""
    from utils.db import engine as default_engine
    from models.models import Base

    target_engine = engine or default_engine
    Base.metadata.create_all(bind=target_engine)
    existing = set(inspect(target_engine).get_table_names())
    return {
        "created": [name for name in NEW_TABLES if name in existing],
        "missing": [name for name in NEW_TABLES if name not in existing],
    }


if __name__ == "__main__":
    print(migrate())
