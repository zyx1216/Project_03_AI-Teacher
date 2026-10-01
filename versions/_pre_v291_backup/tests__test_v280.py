# -*- coding: utf-8 -*-
"""v2.8.0 性能与稳定性优化（方向四）测试。"""

from __future__ import annotations

import time

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from models.models import Base


@pytest.fixture()
def session(tmp_path, monkeypatch):
    eng = create_engine(f"sqlite:///{(tmp_path/'t.db').as_posix()}")
    Base.metadata.create_all(eng)
    import config
    monkeypatch.setattr(config, "LOG_DIR", tmp_path / "logs", raising=False)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()
    eng.dispose()


# --- 表口径与迁移 ---

def test_26_tables():
    assert len(Base.metadata.tables) == 26
    assert "background_tasks" in Base.metadata.tables
    assert "llm_cache" in Base.metadata.tables


def test_business_tables_26():
    from utils import backup_service
    assert len(backup_service.BUSINESS_TABLES) == 26


def test_migration_idempotent_and_indexes():
    from migrations.v2_8_0_migration import INDEX_SQL, migrate
    eng = create_engine("sqlite:///:memory:")
    r1 = migrate(eng)
    r2 = migrate(eng)
    assert len(r1["indexes"]) == len(INDEX_SQL) == 6
    assert r2["indexes"] == []          # 幂等
    names = {i["name"] for t in inspect(eng).get_table_names()
             for i in inspect(eng).get_indexes(t)}
    for name in INDEX_SQL:
        assert name in names
    eng.dispose()


# --- 缓存 ---

def test_llm_cache_roundtrip(session, monkeypatch, tmp_path):
    from utils import cache_service as cs
    monkeypatch.setattr(cs, "_MEM_MAX", 10, raising=False)
    key = cs.make_llm_key("sys", "user", 0.0, "m", "u")
    cs._llm_mem.clear()
    assert cs.get_llm_cache(key) is None
    # 用临时库写读（把 SessionLocal 指到测试库）
    import utils.db as db
    eng = create_engine(f"sqlite:///{(tmp_path/'c.db').as_posix()}")
    Base.metadata.create_all(eng)
    monkeypatch.setattr(db, "SessionLocal",
                        sessionmaker(bind=eng), raising=False)
    cs.set_llm_cache(key, "回答", model="m")
    assert cs.get_llm_cache(key) == "回答"
    stats = cs.cache_stats()
    assert stats["entries"] >= 1 and stats["hits"] >= 1
    assert cs.clear_llm_cache() >= 1
    eng.dispose()


def test_query_cache_and_invalidate():
    from utils import cache_service as cs
    cs.clear_query_cache()
    calls = {"n": 0}
    def fn():
        calls["n"] += 1
        return [1, 2]
    assert cs.cached_query("students", "all", fn) == [1, 2]
    assert cs.cached_query("students", "all", fn) == [1, 2]
    assert calls["n"] == 1                     # 命中缓存
    assert cs.invalidate("students") == 1
    cs.cached_query("students", "all", fn)
    assert calls["n"] == 2                     # 失效后重算


def test_file_cache():
    from utils import cache_service as cs
    sig = cs.file_signature("a.xlsx", b"data")
    assert cs.get_file_cache(sig) is None
    cs.set_file_cache(sig, {"rows": 3})
    assert cs.get_file_cache(sig) == {"rows": 3}


# --- 任务框架 ---

def test_task_success_flow(tmp_path, monkeypatch):
    from utils import task_service as ts
    import utils.db as db
    eng = create_engine(f"sqlite:///{(tmp_path/'t1.db').as_posix()}")
    Base.metadata.create_all(eng)
    monkeypatch.setattr(db, "SessionLocal",
                        sessionmaker(bind=eng), raising=False)

    def runner(params, progress, cancel_check):
        progress(50)
        return {"ok": params.get("x")}
    tid = ts.submit_task("demo", {"x": 1}, runner)
    for _ in range(50):
        t = ts.get_task(tid)
        if t and t["status"] in ("completed", "failed"):
            break
        time.sleep(0.05)
    t = ts.get_task(tid)
    assert t["status"] == "completed" and t["progress"] == 100
    assert t["result"]["ok"] == 1
    eng.dispose()


def test_task_failure_records_reason(tmp_path, monkeypatch):
    from utils import task_service as ts
    import utils.db as db
    eng = create_engine(f"sqlite:///{(tmp_path/'t2.db').as_posix()}")
    Base.metadata.create_all(eng)
    monkeypatch.setattr(db, "SessionLocal",
                        sessionmaker(bind=eng), raising=False)

    def boom(params, progress, cancel_check):
        raise RuntimeError("炸了")
    tid = ts.submit_task("bad", {}, boom)
    for _ in range(50):
        t = ts.get_task(tid)
        if t and t["status"] in ("completed", "failed"):
            break
        time.sleep(0.05)
    t = ts.get_task(tid)
    assert t["status"] == "failed" and "炸了" in t["error_message"]
    eng.dispose()


def test_task_cancel_and_prune(tmp_path, monkeypatch):
    from utils import task_service as ts
    import utils.db as db
    eng = create_engine(f"sqlite:///{(tmp_path/'t3.db').as_posix()}")
    Base.metadata.create_all(eng)
    monkeypatch.setattr(db, "SessionLocal",
                        sessionmaker(bind=eng), raising=False)
    tid = ts.create_task("demo", {})
    ts.request_cancel(tid)
    assert ts.get_task(tid)["status"] == "cancelled"
    assert ts.prune_old_tasks(days=0) >= 0
    eng.dispose()


# --- 监控 ---

def test_monitor_metrics():
    from utils import monitor_service as ms
    ms.reset()
    ms.record_metric("db", "select_scores", 120)
    ms.record_metric("db", "select_scores", 80)
    rows = ms.stats("db")
    assert rows and rows[0]["count"] == 2
    assert rows[0]["p50"] in (80.0, 120.0)
    assert "db" in ms.summary()
    with ms.track("llm", "chat"):
        pass
    assert any(r["name"] == "chat" for r in ms.stats("llm"))


# --- 错误处理 ---

def test_error_handler_friendly_message_hides_paths():
    from utils import error_handler as eh
    msg = eh.friendly_message(ValueError("/secret/path.py boom"), "首页")
    assert "secret" not in msg and "/" not in msg
    assert "首页" in msg


def test_error_handler_records(tmp_path, monkeypatch):
    from utils import error_handler as eh
    import utils.error_logger as el
    monkeypatch.setattr(el, "ERROR_LOG_DIR", tmp_path, raising=False)
    msg = eh.handle_page_error("测试页", RuntimeError("boom"))
    assert msg and "测试页" in msg
    assert list(tmp_path.glob("error_*.log"))


def test_error_stats(tmp_path):
    from utils import error_logger as el
    (tmp_path / "error_20260930.log").write_text(
        "错误类型：ValueError\n错误类型：ValueError\n"
        "错误类型：RuntimeError\n", encoding="utf-8")
    stats = el.error_stats(tmp_path)
    assert stats["total"] == 3
    assert stats["by_type"]["ValueError"] == 2


def test_slow_query_logging(tmp_path):
    from utils import error_logger as el
    p = el.write_slow_query("SELECT * FROM scores", 150.0, log_dir=tmp_path)
    assert p.exists()
    assert "150.0ms" in p.read_text(encoding="utf-8")
    assert el.list_slow_query_files(tmp_path)


# --- 数据库 ---

def test_session_scope_rollback(tmp_path, monkeypatch):
    from utils import db
    eng = create_engine(f"sqlite:///{(tmp_path/'t4.db').as_posix()}")
    Base.metadata.create_all(eng)
    SL = sessionmaker(bind=eng)
    monkeypatch.setattr(db, "SessionLocal", SL, raising=False)
    with pytest.raises(RuntimeError):
        with db.session_scope() as s:
            s.execute(text("INSERT INTO students (name, class_name) "
                           "VALUES ('x','y')"))
            raise RuntimeError("rollback please")
    with eng.connect() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM students")).scalar()
    assert n == 0                            # 已回滚
    eng.dispose()


def test_optimize_database_runs(tmp_path, monkeypatch):
    from utils import db
    eng = create_engine(f"sqlite:///{(tmp_path/'t5.db').as_posix()}")
    Base.metadata.create_all(eng)
    monkeypatch.setattr(db, "engine", eng, raising=False)
    out = db.optimize_database()
    assert out["ok"] is True
    eng.dispose()


def test_integrity_ok(tmp_path, monkeypatch):
    from utils import db
    eng = create_engine(f"sqlite:///{(tmp_path/'t6.db').as_posix()}")
    Base.metadata.create_all(eng)
    monkeypatch.setattr(db, "engine", eng, raising=False)
    assert db.integrity_ok() is True
    eng.dispose()


# --- LLM 错误分类与缓存口径 ---

def test_llm_error_classification():
    from utils import llm_client
    assert llm_client.classify_error(RuntimeError("connection timeout")) == "网络错误"
    assert llm_client.classify_error(RuntimeError("429 rate limit")) == "API错误"
    assert llm_client.classify_error(RuntimeError("content_filter hit")) == "内容过滤"
    assert llm_client.classify_error(RuntimeError("unexpected")) == "其他"
    assert llm_client.MAX_RETRIES == 2
    assert llm_client.RETRY_BACKOFF == [1, 2]
