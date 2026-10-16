# -*- coding: utf-8 -*-
"""v2.3.0 迁移：创建 operation_logs 并补齐核心索引。

可重复执行；只创建缺失表和索引，不修改字段类型、不删除数据。
"""

from __future__ import annotations

from sqlalchemy import inspect, text

NEW_TABLES = ("operation_logs",)

INDEX_SQL = {
    "ix_students_class_name": 'CREATE INDEX ix_students_class_name ON students (class_name)',
    "ix_students_name": 'CREATE INDEX ix_students_name ON students (name)',
    "ix_scores_student_id": 'CREATE INDEX ix_scores_student_id ON scores (student_id)',
    "ix_scores_subject": 'CREATE INDEX ix_scores_subject ON scores (subject)',
    "ix_questions_subject": 'CREATE INDEX ix_questions_subject ON questions (subject)',
    "ix_questions_grade": 'CREATE INDEX ix_questions_grade ON questions (grade)',
    "ix_exams_exam_date": 'CREATE INDEX ix_exams_exam_date ON exams (exam_date)',
}


def migrate(engine=None) -> dict:
    """创建缺失表和索引。"""
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
            table_indexes = {idx["name"] for idx in inspector.get_indexes(table_name)}
            if index_name not in table_indexes:
                conn.execute(text(sql))
                created_indexes.append(index_name)

    return {
        "tables": [name for name in NEW_TABLES if name in existing_tables],
        "created_indexes": created_indexes,
    }


if __name__ == "__main__":
    print(migrate())
