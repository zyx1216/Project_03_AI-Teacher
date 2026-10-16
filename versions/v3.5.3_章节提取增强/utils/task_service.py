# -*- coding: utf-8 -*-
"""轻量后台任务框架（v2.8.0）。

任务队列落 background_tasks 表；threading.Thread 后台执行，不阻塞界面；
支持进度、取消、失败原因与重试。不引入 Celery 等重依赖。
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta

_cancelled: set[int] = set()
_lock = threading.Lock()

VALID_STATUS = ("pending", "running", "completed", "failed", "cancelled")


def _session():
    from utils.db import SessionLocal
    return SessionLocal()


def _to_dict(row) -> dict:
    def _loads(text):
        try:
            return json.loads(text) if text else None
        except (json.JSONDecodeError, TypeError):
            return None
    return {
        "id": row.id, "task_type": row.task_type,
        "params": _loads(row.params) or {},
        "status": row.status, "result": _loads(row.result),
        "error_message": row.error_message or "", "progress": int(row.progress or 0),
        "created_at": str(row.created_at or ""),
        "started_at": str(row.started_at or ""),
        "completed_at": str(row.completed_at or ""),
    }


def create_task(task_type: str, params: dict | None = None) -> int:
    """建一条 pending 任务，返回任务 ID。"""
    from models.models import BackgroundTask
    with _session() as session:
        task = BackgroundTask(
            task_type=str(task_type), params=json.dumps(params or {},
                                                       ensure_ascii=False),
            status="pending", progress=0, created_at=datetime.now())
        session.add(task)
        session.commit()
        return task.id


def update_progress(task_id: int, progress: int) -> None:
    """更新进度（0-100）。"""
    from models.models import BackgroundTask
    try:
        with _session() as session:
            row = session.get(BackgroundTask, int(task_id))
            if row is None:
                return
            row.progress = max(0, min(100, int(progress)))
            session.commit()
    except Exception:  # noqa: BLE001 —— 进度失败不影响任务
        pass


def _mark(task_id: int, **fields) -> None:
    from models.models import BackgroundTask
    with _session() as session:
        row = session.get(BackgroundTask, int(task_id))
        if row is None:
            return
        for key, value in fields.items():
            setattr(row, key, value)
        session.commit()


def is_cancelled(task_id: int) -> bool:
    with _lock:
        return int(task_id) in _cancelled


def request_cancel(task_id: int) -> None:
    """请求取消：标记为 cancelled，运行中的任务由 runner 自行检查退出。"""
    with _lock:
        _cancelled.add(int(task_id))
    try:
        _mark(int(task_id), status="cancelled", completed_at=datetime.now())
    except Exception:  # noqa: BLE001
        pass


def _run(task_id: int, runner) -> None:
    """后台线程：执行 runner(params, progress_cb, cancel_check)。"""
    from models.models import BackgroundTask
    try:
        with _session() as session:
            row = session.get(BackgroundTask, int(task_id))
            if row is None:
                return
            params = json.loads(row.params or "{}")
            row.status = "running"
            row.started_at = datetime.now()
            session.commit()
        if is_cancelled(task_id):
            return
        result = runner(params, lambda p: update_progress(task_id, p),
                        lambda: is_cancelled(task_id))
        if is_cancelled(task_id):
            _mark(task_id, status="cancelled", completed_at=datetime.now())
            return
        _mark(task_id, status="completed", progress=100,
              result=json.dumps(result or {}, ensure_ascii=False, default=str),
              completed_at=datetime.now())
    except Exception as exc:  # noqa: BLE001 —— 失败记原因，不抛出
        try:
            _mark(task_id, status="failed", error_message=str(exc),
                  completed_at=datetime.now())
        except Exception:  # noqa: BLE001
            pass


def submit_task(task_type: str, params: dict, runner) -> int:
    """创建并立即在后台线程执行任务，返回任务 ID。"""
    task_id = create_task(task_type, params)
    threading.Thread(target=_run, args=(task_id, runner), daemon=True).start()
    return task_id


def get_task(task_id: int) -> dict | None:
    from models.models import BackgroundTask
    with _session() as session:
        row = session.get(BackgroundTask, int(task_id))
        return _to_dict(row) if row else None


def list_tasks(limit: int = 50, days: int = 7) -> list[dict]:
    """任务列表（默认最近 7 天）。"""
    from models.models import BackgroundTask
    since = datetime.now() - timedelta(days=max(1, int(days)))
    with _session() as session:
        rows = (session.query(BackgroundTask)
                .filter(BackgroundTask.created_at >= since)
                .order_by(BackgroundTask.id.desc()).limit(limit).all())
        return [_to_dict(r) for r in rows]


def retry_task(task_id: int, runner) -> int:
    """用同一 params 重跑，返回新任务 ID。"""
    old = get_task(task_id)
    if old is None:
        raise ValueError("任务不存在。")
    return submit_task(old["task_type"], old["params"] or {}, runner)


def delete_task(task_id: int) -> None:
    from models.models import BackgroundTask
    with _session() as session:
        row = session.get(BackgroundTask, int(task_id))
        if row is not None:
            session.delete(row)
            session.commit()


def prune_old_tasks(days: int = 7) -> int:
    """删除超过 N 天且已结束的任务，返回删除条数。"""
    from models.models import BackgroundTask
    cutoff = datetime.now() - timedelta(days=max(1, int(days)))
    with _session() as session:
        n = (session.query(BackgroundTask)
             .filter(BackgroundTask.created_at < cutoff)
             .filter(BackgroundTask.status.in_(
                 ["completed", "failed", "cancelled"]))
             .delete(synchronize_session=False))
        session.commit()
        return int(n or 0)
