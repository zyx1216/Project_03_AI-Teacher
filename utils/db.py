# -*- coding: utf-8 -*-
"""
数据库初始化与连接模块。

提供：
- engine：SQLAlchemy 数据库引擎（SQLite 单文件）
- SessionLocal：会话工厂
- init_db()：创建所有数据表（表已存在时不会重建、不破坏已有数据）
"""

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

import config
from models.models import Base

# check_same_thread=False：Streamlit 每个脚本运行可能在不同线程访问 SQLite
engine: Engine = create_engine(
    config.DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},
)

# 会话工厂；业务代码用 with SessionLocal() as session 操作数据库
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    """创建数据目录和所有数据表。已存在的表保持不变。"""
    config.ensure_dirs()
    # 导入模型保证所有表都注册到 Base.metadata 上
    Base.metadata.create_all(bind=engine)