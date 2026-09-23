# -*- coding: utf-8 -*-
"""
后台 OCR 任务管理。

任务状态写入 data/ocr_tasks.json，识别在守护线程中执行。v1.6.0 起识别完成后
只把全文暂存到 data/ocr_results/，资料导入必须由老师命名确认；真题导入则
读取暂存文本解析题目，不创建 Textbook。
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
OCR_RESULTS_DIR = config.DATA_DIR / "ocr_results"
OCR_SOURCE_DIR = config.UPLOAD_DIR / "ocr_source"

STATUS_PENDING = "等待中"
STATUS_RUNNING = "识别中"
STATUS_COMPLETED = "已完成"
STATUS_FAILED = "失败"
STATUS_STOPPED = "已停止"

FLOW_MATERIAL = "material"
FLOW_QUESTION_IMPORT = "question_import"

_LOCK = threading.RLock()
_CORRUPT_PATHS: set[str] = set()
_MEMORY_TASKS: dict[str, dict] = {}
_RECOVERED = False
_STOP_EVENTS: dict[str, threading.Event] = {}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _result_path(task_id: str) -> Path:
    return OCR_RESULTS_DIR / f"{task_id}.txt"


def _source_path(task_id: str) -> Path:
    return OCR_SOURCE_DIR / f"{task_id}.pdf"


def _save_source(task_id: str, pdf_bytes: bytes) -> None:
    OCR_SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    _source_path(task_id).write_bytes(bytes(pdf_bytes))


def _remove_task_files(task_id: str, remove_result: bool = True) -> None:
    try:
        _source_path(task_id).unlink()
    except FileNotFoundError:
        pass
    if remove_result:
        try:
            _result_path(task_id).unlink()
        except FileNotFoundError:
            pass


def _recover_stale_tasks() -> None:
    """重启后把旧任务标失败；本函数只允许在恢复锁内执行一次。"""
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
    """写入任务状态；原 JSON 损坏时保留原文件，只维护进程内状态。"""
    if str(OCR_TASKS_PATH) in _CORRUPT_PATHS:
        _MEMORY_TASKS.clear()
        _MEMORY_TASKS.update(tasks)
        return
    OCR_TASKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    OCR_TASKS_PATH.write_text(
        json.dumps({"tasks": list(tasks.values())}, ensure_ascii=False, indent=2),
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
    """删除任务记录；运行中的任务不允许删除。"""
    task_id = str(task_id)
    with _LOCK:
        task = load_tasks().get(task_id)
        if task is not None and task.get("status") in (STATUS_PENDING, STATUS_RUNNING):
            raise ValueError("任务正在识别，不能删除，请先停止。")
        tasks = load_tasks()
        tasks.pop(task_id, None)
        _STOP_EVENTS.pop(task_id, None)
        _write_tasks(tasks)
        _remove_task_files(task_id)


def clear_closed_tasks() -> int:
    """批量清除失败和已停止任务，返回清除数量。"""
    with _LOCK:
        tasks = load_tasks()
        closed = [tid for tid, task in tasks.items()
                  if task.get("status") in (STATUS_FAILED, STATUS_STOPPED)]
        for tid in closed:
            tasks.pop(tid, None)
            _STOP_EVENTS.pop(tid, None)
            _remove_task_files(tid)
        _write_tasks(tasks)
        return len(closed)


def request_stop(task_id: str) -> None:
    """请求停止；OCR 会在当前页结束后、下一页开始前停下。"""
    event = _STOP_EVENTS.get(str(task_id))
    if event is not None:
        event.set()


def start_ocr_task(
    *,
    pdf_bytes: bytes,
    name: str,
    subject: str,
    grade: str = "",
    source_name: str = "",
    session_factory: Any | None = None,
    text_dir: Path | str | None = None,
    ocr_func: Callable[..., str] | None = None,
    total_pages: int | None = None,
    flow: str = FLOW_MATERIAL,
    source_label: str = "",
) -> dict:
    """创建并启动后台 OCR 任务。资料流不再自动创建 Textbook。"""
    from utils.ocr_service import ocr_pdf, pdf_page_count

    if flow not in (FLOW_MATERIAL, FLOW_QUESTION_IMPORT):
        raise ValueError("OCR流程类型不正确。")
    task_id = uuid.uuid4().hex
    event = threading.Event()
    _STOP_EVENTS[task_id] = event
    task = {
        "id": task_id,
        "name": name,
        "subject": subject,
        "grade": grade,
        "source_name": source_name,
        "source_label": source_label,
        "flow": flow,
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
    _save_source(task_id, pdf_bytes)

    thread = threading.Thread(
        target=_run_task,
        args=(task_id, bytes(pdf_bytes), ocr_func or ocr_pdf, event),
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



def _call_ocr_func(ocr_func, pdf_bytes, progress_callback, stop_event):
    """调用识别函数；自定义函数不接收 stop_event 时不传该参数。"""
    import inspect

    kwargs = {"progress_callback": progress_callback}
    try:
        signature = inspect.signature(ocr_func)
    except (TypeError, ValueError):
        signature = None
    if signature is None or any(
            p.kind == inspect.Parameter.VAR_KEYWORD
            or p.name == "stop_event"
            for p in signature.parameters.values()):
        kwargs["stop_event"] = stop_event
    return ocr_func(pdf_bytes, **kwargs)

def _run_task(task_id: str, pdf_bytes: bytes,
              ocr_func: Callable[..., str],
              stop_event: threading.Event) -> None:
    """后台线程入口：识别并写暂存文件，最终只更新状态。"""
    with _LOCK:
        tasks = load_tasks()
        task = tasks.get(task_id)
        if task is not None:
            task["status"] = STATUS_RUNNING
            _write_tasks(tasks)

    try:
        text = _call_ocr_func(
            ocr_func, pdf_bytes,
            lambda current, total: _update_progress(current, total, task_id),
            stop_event)
        OCR_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        _result_path(task_id).write_text(text, encoding="utf-8")
        with _LOCK:
            tasks = load_tasks()
            task = tasks.get(task_id)
            if task is not None:
                task.update({
                    "status": STATUS_COMPLETED,
                    "current_page": task["total_pages"],
                    "char_count": len(text),
                    "error": "",
                })
                _write_tasks(tasks)
    except Exception as exc:
        stopped = stop_event.is_set()
        with _LOCK:
            tasks = load_tasks()
            task = tasks.get(task_id)
            if task is not None:
                task.update({
                    "status": STATUS_STOPPED if stopped else STATUS_FAILED,
                    "error": "已停止识别" if stopped else str(exc),
                })
                _write_tasks(tasks)


def load_ocr_result(task_id: str) -> str:
    """读取 OCR 暂存全文；文件不存在时抛中文错误。"""
    path = _result_path(str(task_id))
    if not path.exists():
        raise ValueError("OCR识别结果不存在，请重新上传PDF。")
    return path.read_text(encoding="utf-8")


def confirm_ocr_material(task_id: str, name: str, grade: str,
                         subject: str | None = None,
                         text_dir: Path | str | None = None,
                         session_factory: Any | None = None) -> int:
    """老师确认资料名称和年级后创建 Textbook，复制全文并清理暂存。"""
    from utils.material_service import split_chapters

    task_id = str(task_id)
    text = load_ocr_result(task_id)
    name = str(name or "").strip()
    if not name:
        raise ValueError("资料名称不能为空。")

    with _LOCK:
        task = load_tasks().get(task_id)
        if task is None:
            raise ValueError("OCR任务不存在。")
        subject = subject or task.get("subject")

    chapters = split_chapters(text)
    session_path = Path(text_dir) if text_dir is not None else config.UPLOAD_DIR / "text"
    session_path.mkdir(parents=True, exist_ok=True)

    if session_factory is None:
        from utils.db import SessionLocal
        session_factory = SessionLocal
    session = session_factory()
    try:
        textbook = Textbook(
            name=name,
            file_type="pdf",
            file_path=task.get("source_name") or task.get("source_label", ""),
            subject=subject,
            grade=grade,
            chapter_info=json.dumps(
                [{"title": c["title"], "length": len(c["content"])}
                 for c in chapters], ensure_ascii=False),
            vectorized=False)
        session.add(textbook)
        session.commit()
        textbook_id = textbook.id
    finally:
        session.close()

    (session_path / f"{textbook_id}.txt").write_text(text, encoding="utf-8")
    try:
        _result_path(task_id).unlink()
    except FileNotFoundError:
        pass

    # OCR 原文从任务暂存目录移动到资料 canonical 目录；旧任务缺文件时不补造。
    source = _source_path(task_id)
    if source.exists():
        from utils.material_service import original_file_path, expose_original_file
        original = original_file_path(textbook_id, "pdf")
        original.parent.mkdir(parents=True, exist_ok=True)
        source.replace(original)
        expose_original_file(original)

    with _LOCK:
        tasks = load_tasks()
        task = tasks.get(task_id)
        if task is not None:
            task.update({"textbook_id": textbook_id})
            _write_tasks(tasks)
    return textbook_id
