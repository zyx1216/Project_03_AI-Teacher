# -*- coding: utf-8 -*-
"""
pytest 公共夹具。

数据库测试全部用内存 SQLite，不碰真实的 data/database.db。
"""

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# 把项目根加入模块搜索路径（tests 在子目录里运行）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from models.models import Base  # noqa: E402


@pytest.fixture()
def session():
    """提供一个空的内存数据库会话，每个测试函数独立。"""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    test_session = sessionmaker(bind=engine)()
    try:
        yield test_session
    finally:
        test_session.close()

@pytest.fixture(autouse=True)
def isolated_class_names_path(tmp_path, monkeypatch):
    """所有测试默认使用临时班级名单，绝不创建真实 data/class_names.json。"""
    from utils import class_service
    monkeypatch.setattr(
        class_service, "CLASS_NAMES_PATH", tmp_path / "class_names.json")
