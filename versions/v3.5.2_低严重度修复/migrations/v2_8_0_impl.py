# -*- coding: utf-8 -*-
"""v2.8.0 迁移：创建 background_tasks / llm_cache 并补齐性能索引。

可重复执行；只创建缺失表和索引，不修改字段类型、不删除数据。
"""

from __future__ import annotations

from sqlalchemy import inspect

NEW_TABLES = ("background_tasks", "llm_cache")

# 幂等 SQL（IF NOT EXISTS），避免重复执行报错
INDEX_SQL = {
    "ix_scores_exam_id": "CREATE INDEX IF NOT EXISTS ix_scores_exam_id ON scores (exam_id)",
    "ix_questions_difficulty": "CREATE INDEX IF NOT EXISTS ix_questions_difficulty ON questions (difficulty)",
    "ix_homeworks_subject": "CREATE INDEX IF NOT EXISTS ix_homeworks_subject ON homeworks (subject)",
    "ix_homeworks_status": "CREATE INDEX IF NOT EXISTS ix_homeworks_status ON homeworks (status)",
    "ix_homework_answers_homework_id": "CREATE INDEX IF NOT EXISTS ix_homework_answers_homework_id ON homework_answers (homework_id)",
    "ix_homework_answers_student_id": "CREATE INDEX IF NOT EXISTS ix_homework_answers_student_id ON homework_answers (student_id)",
}


def migrate(engine=None) -> dict:
    """创建缺失表和性能索引；返回 {tables, indexes}。"""
    from models.models import Base
    from utils.db import engine as default_engine

    target_engine = engine or default_engine
    Base.metadata.create_all(bind=target_engine)
    inspector = inspect(target_engine)
    existing_tables = set(inspector.get_table_names())
    created_indexes: list[str] = []

    with target_engine.begin() as conn:
        for index_name, sql in INDEX_SQL.items():
            table_name = sql.split(" ON ")[1].split(" (")[0]
            if table_name not in existing_tables:
                continue
            present = {idx["name"] for idx in inspector.get_indexes(table_name)}
            if index_name in present:
                continue
            conn.exec_driver_sql(sql)
            created_indexes.append(index_name)

    return {"tables": [t for t in NEW_TABLES if t in existing_tables],
            "indexes": created_indexes}
