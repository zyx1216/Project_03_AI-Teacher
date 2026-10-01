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
# v2.8.0：加连接超时（等锁最多 30s）与 pool_pre_ping（连接失效自动重连）
engine: Engine = create_engine(
    config.DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False, "timeout": 30},
)

# 会话工厂；业务代码用 with SessionLocal() as session 操作数据库
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

# v2.8.0：慢查询阈值（毫秒）；超过则记日志（含脱敏后的语句与耗时）
SLOW_QUERY_MS = 100.0


def _register_slow_query_logger(target_engine: Engine) -> None:
    """注册 SQLAlchemy 慢查询监听（>SLOW_QUERY_MS 记日志，不影响业务）。"""
    from sqlalchemy import event

    @event.listens_for(target_engine, "before_cursor_execute")
    def _before(conn, cursor, statement, parameters, context, executemany):
        conn.info.setdefault("_q_start", []).append(__import__("time").time())

    @event.listens_for(target_engine, "after_cursor_execute")
    def _after(conn, cursor, statement, parameters, context, executemany):
        import time as _t
        starts = conn.info.get("_q_start") or []
        if not starts:
            return
        elapsed = (_t.time() - starts.pop()) * 1000
        if elapsed < SLOW_QUERY_MS:
            return
        try:
            from utils import error_logger
            error_logger.write_slow_query(statement, elapsed)
        except Exception:  # noqa: BLE001 —— 日志失败不影响查询
            pass


_register_slow_query_logger(engine)


from contextlib import contextmanager  # noqa: E402


@contextmanager
def session_scope():
    """事务性会话：正常提交，异常自动 rollback，退出必关闭。"""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def integrity_ok() -> bool:
    """启动时检查数据库完整性（PRAGMA quick_check）。失败返回 False。"""
    try:
        with engine.connect() as conn:
            row = conn.execute(text("PRAGMA quick_check")).fetchone()
            return bool(row) and str(row[0]).lower() == "ok"
    except Exception:  # noqa: BLE001 —— 检查失败不阻断启动
        return False


def optimize_database() -> dict:
    """手动维护：VACUUM + ANALYZE。返回 {ok, detail}。"""
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("VACUUM")
            conn.exec_driver_sql("ANALYZE")
        return {"ok": True, "detail": "已完成 VACUUM 与 ANALYZE。"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": f"优化失败：{exc}"}

# 轻量迁移清单：表名 -> [(列名, 列的 SQLite 定义), ...]，只用于新增可空列
_PENDING_COLUMNS = {
    "textbooks": [
        ("type", "VARCHAR(20) DEFAULT 'textbook'"),
    ],
    "exams": [
        ("full_scores", "TEXT"),
        ("homework_id", "INTEGER"),
    ],
    "homeworks": [
        ("is_template", "BOOLEAN DEFAULT 0"),
        ("subject", "TEXT DEFAULT '数学'"),
        ("grade", "VARCHAR(20)"),
        ("status", "VARCHAR(20) DEFAULT 'pending'"),
        ("completed_at", "DATETIME"),
        ("last_opened_at", "DATETIME"),
        ("submit_code", "VARCHAR(10)"),
        ("lesson_plan_id", "INTEGER"),
    ],
    "questions": [
        ("subject", "TEXT DEFAULT '数学'"),
        ("grade", "VARCHAR(30)"),
        ("parent_question_id", "INTEGER"),
        ("custom_tags", "TEXT"),
        ("ai_difficulty", "VARCHAR(10)"),
        ("calibrated_difficulty", "INTEGER"),
        ("difficulty_evidence", "TEXT"),
        ("source_id", "INTEGER"),
        ("source_info", "VARCHAR(200)"),
    ],
    "teaching_reflections": [
        ("has_plan", "INTEGER DEFAULT 0"),
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
    if not integrity_ok():
        # 不抛出：只提示，避免打断启动；具体问题引导到错误日志
        import logging
        logging.getLogger(__name__).warning("数据库完整性检查未通过")
    Base.metadata.create_all(bind=engine)
    _add_missing_columns()
    _migrate_due_date()
    _cleanup_ai_difficulty()


def _cleanup_ai_difficulty():
    """v2.5.1：ai_difficulty 改为「易/中/难」字符串口径后，清掉历史整数值。

    幂等：只把不是 易/中/难 的非空值置空，不动合法标签。
    """
    from sqlalchemy import text, create_engine
    import config
    engine = create_engine(config.DATABASE_URL)
    with engine.connect() as conn:
        try:
            conn.execute(text(
                "UPDATE questions SET ai_difficulty = NULL "
                "WHERE ai_difficulty IS NOT NULL "
                "AND ai_difficulty NOT IN ('易','中','难')"))
            conn.commit()
        except Exception:  # noqa: BLE001 —— 表不存在时不阻断启动
            pass

def _migrate_due_date():
    """v1.7.8：给homeworks表加due_date、material_id、chapter列。"""
    from sqlalchemy import text, create_engine
    import config
    engine = create_engine(config.DATABASE_URL)
    with engine.connect() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(homeworks)"))]
        if "due_date" not in cols:
            conn.execute(text("ALTER TABLE homeworks ADD COLUMN due_date DATETIME"))
        if "material_id" not in cols:
            conn.execute(text("ALTER TABLE homeworks ADD COLUMN material_id INTEGER"))
        if "chapter" not in cols:
            conn.execute(text("ALTER TABLE homeworks ADD COLUMN chapter VARCHAR(200)"))
        conn.commit()
