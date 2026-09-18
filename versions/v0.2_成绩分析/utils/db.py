# -*- coding: utf-8 -*-
"""
数据库初始化与连接模块。

提供：
- engine：SQLAlchemy 数据库引擎（SQLite 单文件）
- SessionLocal：会话工厂
- init_db()：创建所有数据表，并对旧库做轻量补列迁移

单人单机工具不引入 Alembic 这类迁移框架：新增可空字段时，
用"检查列是否存在，不存在就 ALTER TABLE ADD COLUMN"的方式平滑升级。
"""

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

import config
from models.models import Base

# check_same_thread=False：Streamlit 每次脚本运行可能在不同线程访问 SQLite
engine: Engine = create_engine(
    config.DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},
)

# 会话工厂；业务代码用 with SessionLocal() as session 操作数据库
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

# 轻量迁移清单：表名 -> [(列名, 列的 SQLite 定义), ...]，只用于新增可空列
_PENDING_COLUMNS = {
    "exams": [
        ("full_scores", "TEXT"),
    ],
}


def _add_missing_columns() -> None:
    """对已存在的旧表补齐新增的可空列；新表由 create_all 直接建好，不受影响。"""
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table_name, columns in _PENDING_COLUMNS.items():
            if table_name not in existing_tables:
                continue
            present = {col["name"] for col in inspector.get_columns(table_name)}
            for col_name, col_type in columns:
                if col_name not in present:
                    conn.execute(
                        text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}")
                    )


def init_db() -> None:
    """创建数据目录和所有数据表，并执行轻量补列迁移（幂等，不清空数据）。"""
    config.ensure_dirs()
    Base.metadata.create_all(bind=engine)
    _add_missing_columns()