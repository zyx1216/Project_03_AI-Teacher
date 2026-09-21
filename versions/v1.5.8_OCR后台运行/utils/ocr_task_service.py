# -*- coding: utf-8 -*-
"""
后台 OCR 任务管理。

任务状态写入本地 JSON，识别在独立守护线程中执行。切换 Streamlit 页面只会
停止渲染，不会终止 Python 线程；识别完成后自动创建可用资料。
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import config
from models.models import Textbook

OCR_TASKS_PATH = config.DATA_DIR / "ocr_tasks.json"

STATUS_PENDING = "等待中"
STATUS_RUNNING = "识别中"
STATUS_COMPLETED = "已完成"
STATUS_FAILED = "失败"

_LOCK = threading.RLock()
_CORRUPT_PATHS: set[str] = set()
_MEMORY_TASKS: dict[str, dict] = {}
_RECOVERED = False


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _recover_stale_tasks() -> None:
    """应用重启后，把没有线程继续执行的旧任务标为失败，避免永远显示识别中。"""
    global _RECOVERED
    if _RECOVERED:
        return
    _RECOVERED = True

    try:
        raw = OCR_TASKS_PATH.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return

    tasks = data.get("tasks", []) if isinstance(data, dict) else []
    changed = False
    for task in tasks:
        if (isinstance(task, dict)
                and task.get("status") in (STATUS_PENDING, STATUS_RUNNING)):
            task["status"] = STATUS_FAILED
            task["error"] = "应用已重启或任务中断，请重新上传PDF"
            changed = True
    if changed:
        OCR_TASKS_PATH.write_text(
            json.dumps({"tasks": tasks}, ensure_ascii=False, indent=2),
            encoding="utf-8")


def load_tasks() -> dict[str, dict]:
    """读取全部任务；文件缺失返回空结构，JSON 损坏时回退且不覆盖原文件。"""
    _recover_stale_tasks()
    try:
        raw = OCR_TASKS_PATH.read_text(encoding="utf-8")
        data = json.loads(raw)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        _CORRUPT_PATHS.add(str(OCR_TASKS_PATH))
        return dict(_MEMORY_TASKS)

    tasks = data.get("tasks", []) if isinstance(data, dict) else []
    return {
        str(item["id"]): item
        for item in tasks
        if isinstance(item, dict) and item.get("id")
    }


def _write_tasks(tasks: dict[str, dict]) -> None:
    """写入任务状态；原文件损坏时保留原文件，只保留进程内状态。"""
    if str(OCR_TASKS_PATH) in _CORRUPT_PATHS:
        _MEMORY_TASKS.clear()
        _MEMORY_TASKS.update(tasks)
        return
    OCR_TASKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"tasks": list(tasks.values())}
    OCR_TASKS_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8")


def list_tasks() -> list[dict]:
    """按创建时间返回任务列表。"""
    with _LOCK:
        return sorted(load_tasks().values(), key=lambda item: item["created_at"])


def upsert_task(task: dict) -> dict:
    """新增或更新一个任务。"""
    with _LOCK:
        tasks = load_tasks()
        task = dict(task)
        task["updated_at"] = _now()
        tasks[task["id"]] = task
        _write_tasks(tasks)
        return task


def remove_task(task_id: str) -> None:
    """删除一条任务通知。"""
    with _LOCK:
        tasks = load_tasks()
        tasks.pop(str(task_id), None)
        _write_tasks(tasks)


def start_ocr_task(
    *,
    pdf_bytes: bytes,
    name: str,
    subject: str,
    grade: str,
    source_name: str,
    session_factory: Any,
    text_dir: Path,
    ocr_func: Callable[..., str] | None = None,
    total_pages: int | None = None,
) -> dict:
    """创建并启动一个后台 OCR 任务，返回初始任务状态。"""
    from utils.ocr_service import ocr_pdf, pdf_page_count

    task_id = uuid.uuid4().hex
    task = {
        "id": task_id,
        "name": name,
        "subject": subject,
        "grade": grade,
        "source_name": source_name,
        "status": STATUS_PENDING,
        "current_page": 0,
        "total_pages": total_pages if total_pages is not None else pdf_page_count(pdf_bytes),
        "error": "",
        "textbook_id": None,
        "char_count": 0,
        "created_at": _now(),
        "updated_at": _now(),
    }
    upsert_task(task)

    thread = threading.Thread(
        target=_run_task,
        args=(task_id, bytes(pdf_bytes), session_factory, Path(text_dir),
              ocr_func or ocr_pdf),
        name=f"ocr-task-{task_id}",
        daemon=True,
    )
    thread.start()
    return task


def _update_progress(current_page: int, total_pages: int, task_id: str) -> None:
    with _LOCK:
        tasks = load_tasks()
        task = tasks.get(str(task_id))
        if task is None:
            return
        task["status"] = STATUS_RUNNING
        task["current_page"] = current_page
        task["total_pages"] = total_pages
        _write_tasks(tasks)


def _run_task(task_id: str, pdf_bytes: bytes, session_factory: Any,
              text_dir: Path, ocr_func: Callable[..., str]) -> None:
    """后台线程入口：识别、保存资料、更新最终状态。"""
    with _LOCK:
        tasks = load_tasks()
        task = tasks.get(task_id)
        if task is not None:
            task["status"] = STATUS_RUNNING
            _write_tasks(tasks)

    try:
        text = ocr_func(
            pdf_bytes,
            progress_callback=lambda current, total:
                _update_progress(current, total, task_id),
        )
        textbook_id = _save_textbook(
            task_id, text, session_factory, text_dir)
        with _LOCK:
            tasks = load_tasks()
            task = tasks.get(task_id)
            if task is not None:
                task.update({
                    "status": STATUS_COMPLETED,
                    "current_page": task["total_pages"],
                    "textbook_id": textbook_id,
                    "char_count": len(text),
                    "error": "",
                })
                _write_tasks(tasks)
    except Exception as exc:  # 后台任务必须落失败状态，不能卡在识别中
        with _LOCK:
            tasks = load_tasks()
            task = tasks.get(task_id)
            if task is not None:
                task.update({
                    "status": STATUS_FAILED,
                    "error": str(exc),
                })
                _write_tasks(tasks)


def _save_textbook(task_id: str, text: str, session_factory: Any,
                   text_dir: Path) -> int:
    """识别成功后创建资料记录，并把全文写入既有文本目录。"""
    from utils.material_service import split_chapters

    with _LOCK:
        task = load_tasks()[task_id]

    chapters = split_chapters(text)
    session = session_factory()
    try:
        textbook = Textbook(
            name=task["name"],
            file_type="pdf",
            file_path=task["source_name"],
            subject=task["subject"],
            grade=task["grade"],
            chapter_info=json.dumps(
                [{"title": c["title"], "length": len(c["content"])}
                 for c in chapters],
                ensure_ascii=False),
            vectorized=False)
        session.add(textbook)
        session.commit()
        textbook_id = textbook.id
    finally:
        session.close()

    text_dir.mkdir(parents=True, exist_ok=True)
    (text_dir / f"{textbook_id}.txt").write_text(text, encoding="utf-8")
    return textbook_id
