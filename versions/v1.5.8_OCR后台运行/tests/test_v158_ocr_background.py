# -*- coding: utf-8 -*-
"""v1.5.8 后台 OCR 任务服务测试。"""

import threading
import time
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from models.models import Base
from utils import ocr_task_service as tasks


@pytest.fixture()
def runtime(tmp_path, monkeypatch):
    task_file = tmp_path / "ocr_tasks.json"
    text_dir = tmp_path / "material_text"
    monkeypatch.setattr(tasks, "OCR_TASKS_PATH", task_file)
    monkeypatch.setattr(tasks, "_CORRUPT_PATHS", set())

    db_file = tmp_path / "ocr.db"
    engine = create_engine(
        f"sqlite:///{db_file.as_posix()}",
        connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    return {
        "task_file": task_file,
        "text_dir": text_dir,
        "engine": engine,
        "factory": factory,
    }


def _wait_status(task_file: Path, status: str, timeout: float = 3) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if f'"status": "{status}"' in task_file.read_text(encoding="utf-8"):
            return
        time.sleep(0.02)
    raise AssertionError(f"未等到状态：{status}")


def _fake_ocr(text: str, delay: float = 0.02):
    def fake(pdf_bytes, progress_callback):
        progress_callback(1, 2)
        time.sleep(delay)
        progress_callback(2, 2)
        return text

    return fake


def test_start_background_task_completes_and_saves_material(runtime):
    task = tasks.start_ocr_task(
        pdf_bytes=b"%PDF-fake",
        name="扫描资料甲",
        subject="数学",
        grade="八年级",
        source_name="原始文件.pdf",
        session_factory=runtime["factory"],
        text_dir=runtime["text_dir"],
        ocr_func=_fake_ocr("第一章 有理数\n这是识别正文。"),
        total_pages=2)

    assert task["status"] == tasks.STATUS_PENDING
    _wait_status(runtime["task_file"], tasks.STATUS_COMPLETED)

    result = tasks.load_tasks()[task["id"]]
    assert result["current_page"] == 2
    assert result["total_pages"] == 2
    assert result["char_count"] > 0
    assert result["textbook_id"] == 1

    with runtime["engine"].connect() as conn:
        row = conn.execute(text(
            "SELECT name, file_type, subject, grade FROM textbooks"
        )).mappings().one()
    assert dict(row) == {
        "name": "扫描资料甲",
        "file_type": "pdf",
        "subject": "数学",
        "grade": "八年级",
    }
    saved = (runtime["text_dir"] / "1.txt").read_text(encoding="utf-8")
    assert "这是识别正文" in saved


def test_multiple_ocr_tasks_can_run_together(runtime):
    started = []
    for index in range(2):
        started.append(tasks.start_ocr_task(
            pdf_bytes=f"pdf-{index}".encode("utf-8"),
            name=f"扫描资料{index}",
            subject="数学",
            grade="八年级",
            source_name=f"原始{index}.pdf",
            session_factory=runtime["factory"],
            text_dir=runtime["text_dir"],
            ocr_func=_fake_ocr(f"第{index}份识别正文", delay=0.05),
            total_pages=2))

    deadline = time.time() + 3
    while time.time() < deadline:
        loaded = tasks.load_tasks()
        if all(item["status"] == tasks.STATUS_COMPLETED for item in loaded.values()):
            break
        time.sleep(0.02)
    else:
        raise AssertionError("多个 OCR 任务未全部完成")

    with runtime["engine"].connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM textbooks")).scalar_one()
    assert count == 2
    assert len(list(runtime["text_dir"].glob("*.txt"))) == 2


def test_background_ocr_failure_is_recorded(runtime):
    def broken(pdf_bytes, progress_callback):
        raise RuntimeError("模拟识别失败")

    task = tasks.start_ocr_task(
        pdf_bytes=b"bad",
        name="损坏资料",
        subject="数学",
        grade="八年级",
        source_name="坏.pdf",
        session_factory=runtime["factory"],
        text_dir=runtime["text_dir"],
        ocr_func=broken,
        total_pages=2)

    _wait_status(runtime["task_file"], tasks.STATUS_FAILED)
    assert tasks.load_tasks()[task["id"]]["error"] == "模拟识别失败"
    with runtime["engine"].connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM textbooks")).scalar_one()
    assert count == 0


def test_corrupt_task_json_falls_back_without_overwrite(runtime):
    runtime["task_file"].write_text("{坏JSON", encoding="utf-8")

    assert tasks.load_tasks() == {}
    task = {"id": "abc", "name": "任务", "created_at": "2026-09-21T00:00:00"}
    tasks.upsert_task(task)

    # 原损坏文件保留，进程内仍能更新状态。
    assert runtime["task_file"].read_text(encoding="utf-8") == "{坏JSON"
    assert tasks.load_tasks()["abc"]["name"] == "任务"


def test_remove_task(runtime):
    task = {"id": "abc", "name": "任务", "created_at": "2026-09-21T00:00:00"}
    tasks.upsert_task(task)
    tasks.remove_task("abc")
    assert tasks.load_tasks() == {}

def test_recover_stale_pending_task(runtime, monkeypatch):
    """应用重启后，旧的等待/识别任务必须标失败，不能一直显示识别中。"""
    import json

    monkeypatch.setattr(tasks, "_RECOVERED", False)
    runtime["task_file"].write_text(json.dumps({
        "tasks": [{
            "id": "old",
            "name": "中断任务",
            "status": tasks.STATUS_RUNNING,
            "current_page": 1,
            "total_pages": 3,
            "created_at": "2026-09-21T00:00:00",
        }]
    }, ensure_ascii=False), encoding="utf-8")

    loaded = tasks.load_tasks()

    assert loaded["old"]["status"] == tasks.STATUS_FAILED
    assert "重新上传PDF" in loaded["old"]["error"]
