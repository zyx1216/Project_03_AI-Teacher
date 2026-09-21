# -*- coding: utf-8 -*-
"""v1.6.0 后台 OCR：暂存结果、命名确认、停止、清除进度测试。"""

import json
import time
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from models.models import Base
from utils import material_service
from utils import ocr_task_service as tasks


@pytest.fixture()
def runtime(tmp_path, monkeypatch):
    task_file = tmp_path / "ocr_tasks.json"
    result_dir = tmp_path / "ocr_results"
    source_dir = tmp_path / "ocr_source"
    original_dir = tmp_path / "original"
    static_dir = tmp_path / "static_original"
    text_dir = tmp_path / "material_text"
    monkeypatch.setattr(tasks, "OCR_TASKS_PATH", task_file)
    monkeypatch.setattr(tasks, "OCR_RESULTS_DIR", result_dir)
    monkeypatch.setattr(tasks, "OCR_SOURCE_DIR", source_dir)
    monkeypatch.setattr(material_service, "OCR_SOURCE_DIR", source_dir)
    monkeypatch.setattr(material_service, "ORIGINAL_DIR", original_dir)
    monkeypatch.setattr(material_service, "STATIC_ORIGINAL_DIR", static_dir)
    monkeypatch.setattr(tasks, "_CORRUPT_PATHS", set())
    monkeypatch.setattr(tasks, "_RECOVERED", False)
    monkeypatch.setattr(tasks, "_STOP_EVENTS", {})

    db_file = tmp_path / "ocr.db"
    engine = create_engine(
        f"sqlite:///{db_file.as_posix()}",
        connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    return {
        "task_file": task_file,
        "result_dir": result_dir,
        "source_dir": source_dir,
        "original_dir": original_dir,
        "static_dir": static_dir,
        "text_dir": text_dir,
        "engine": engine,
        "factory": factory,
    }


def _wait_status(task_file: Path, status: str, timeout: float = 3) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if task_file.exists() and f'"status": "{status}"' in task_file.read_text(encoding="utf-8"):
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


def _textbook_count(runtime):
    with runtime["engine"].connect() as conn:
        return conn.execute(text("SELECT COUNT(*) FROM textbooks")).scalar_one()


def _start_simple(runtime, name="扫描资料甲"):
    return tasks.start_ocr_task(
        pdf_bytes=b"%PDF-fake",
        name=name,
        subject="数学",
        grade="八年级",
        source_name="原始文件.pdf",
        ocr_func=_fake_ocr("第一章 有理数\n这是识别正文。"),
        total_pages=2)


def test_ocr_completes_writes_staging_file_without_material(runtime):
    task = _start_simple(runtime)
    _wait_status(runtime["task_file"], tasks.STATUS_COMPLETED)

    result = tasks.load_tasks()[task["id"]]
    assert result["current_page"] == 2
    assert result["char_count"] > 0
    assert result["textbook_id"] is None
    assert _textbook_count(runtime) == 0
    staged = runtime["result_dir"] / f"{task['id']}.txt"
    assert "这是识别正文" in staged.read_text(encoding="utf-8")
    assert tasks.load_ocr_result(task["id"]).startswith("第一章")


def test_confirm_name_creates_material_and_clears_staging(runtime):
    task = _start_simple(runtime)
    _wait_status(runtime["task_file"], tasks.STATUS_COMPLETED)

    textbook_id = tasks.confirm_ocr_material(
        task["id"], "确认后的资料名", "八年级", "数学",
        runtime["text_dir"], runtime["factory"])
    assert textbook_id == 1
    with runtime["engine"].connect() as conn:
        row = conn.execute(text(
            "SELECT name, file_type, subject, grade FROM textbooks"
        )).mappings().one()
    assert dict(row) == {
        "name": "确认后的资料名",
        "file_type": "pdf",
        "subject": "数学",
        "grade": "八年级",
    }
    saved = runtime["text_dir"] / "1.txt"
    assert "这是识别正文" in saved.read_text(encoding="utf-8")
    assert not (runtime["result_dir"] / f"{task['id']}.txt").exists()
    assert not (runtime["source_dir"] / f"{task['id']}.pdf").exists()
    assert (runtime["original_dir"] / "1.pdf").read_bytes() == b"%PDF-fake"
    assert (runtime["static_dir"] / "1.pdf").exists()
    assert tasks.load_tasks()[task["id"]]["textbook_id"] == 1


def test_unconfirmed_staging_remains_and_creates_nothing(runtime):
    task = _start_simple(runtime)
    _wait_status(runtime["task_file"], tasks.STATUS_COMPLETED)
    assert _textbook_count(runtime) == 0
    assert (runtime["result_dir"] / f"{task['id']}.txt").exists()


def test_multiple_ocr_tasks_run_and_stage_separately(runtime):
    started = []
    for index in range(2):
        started.append(tasks.start_ocr_task(
            pdf_bytes=f"pdf-{index}".encode(),
            name=f"扫描资料{index}",
            subject="数学",
            grade="八年级",
            source_name=f"原始{index}.pdf",
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

    assert _textbook_count(runtime) == 0
    assert len(list(runtime["result_dir"].glob("*.txt"))) == 2


def test_failure_is_recorded(runtime):
    def broken(pdf_bytes, progress_callback):
        raise RuntimeError("模拟识别失败")

    task = tasks.start_ocr_task(
        pdf_bytes=b"bad", name="损坏资料", subject="数学",
        grade="八年级", source_name="坏.pdf", ocr_func=broken,
        total_pages=2)
    _wait_status(runtime["task_file"], tasks.STATUS_FAILED)
    assert tasks.load_tasks()[task["id"]]["error"] == "模拟识别失败"
    assert _textbook_count(runtime) == 0


def test_stop_event_stops_before_next_page(runtime):
    def fake(pdf_bytes, progress_callback, stop_event):
        for page in range(2):
            if stop_event.is_set():
                raise RuntimeError("已停止识别")
            progress_callback(page + 1, 2)
            time.sleep(0.05)
        return "不应得到的全文"

    task = tasks.start_ocr_task(
        pdf_bytes=b"pdf", name="停止任务", subject="数学",
        ocr_func=fake, total_pages=2)
    tasks.request_stop(task["id"])
    _wait_status(runtime["task_file"], tasks.STATUS_STOPPED)
    loaded = tasks.load_tasks()[task["id"]]
    assert loaded["error"] == "已停止识别"
    assert not (runtime["result_dir"] / f"{task['id']}.txt").exists()


def test_clear_closed_tasks(runtime):
    task = _start_simple(runtime, name="失败资料")
    _wait_status(runtime["task_file"], tasks.STATUS_COMPLETED)
    # 后台线程结束后再把完成任务改成失败，避免状态被线程回写覆盖。
    items = tasks.load_tasks()
    items[task["id"]]["status"] = tasks.STATUS_FAILED
    tasks.upsert_task(items[task["id"]])
    assert tasks.clear_closed_tasks() == 1
    assert tasks.load_tasks() == {}


def test_corrupt_task_json_falls_back_without_overwrite(runtime):
    runtime["task_file"].write_text("{坏JSON", encoding="utf-8")

    assert tasks.load_tasks() == {}
    task = {"id": "abc", "name": "任务", "created_at": "2026-09-21T00:00:00"}
    tasks.upsert_task(task)

    assert runtime["task_file"].read_text(encoding="utf-8") == "{坏JSON"
    assert tasks.load_tasks()["abc"]["name"] == "任务"


def test_running_task_cannot_be_removed(runtime):
    def slow(pdf_bytes, progress_callback):
        time.sleep(0.3)
        return "正文"

    task = tasks.start_ocr_task(
        pdf_bytes=b"pdf", name="运行任务", subject="数学",
        ocr_func=slow, total_pages=1)
    with pytest.raises(ValueError, match="不能删除"):
        tasks.remove_task(task["id"])


def test_remove_completed_task(runtime):
    task = _start_simple(runtime)
    _wait_status(runtime["task_file"], tasks.STATUS_COMPLETED)
    tasks.remove_task(task["id"])
    assert tasks.load_tasks() == {}


def test_recover_stale_pending_task(runtime):
    runtime["task_file"].write_text(json.dumps({
        "tasks": [{
            "id": "old", "name": "中断任务",
            "status": tasks.STATUS_RUNNING,
            "current_page": 1, "total_pages": 3,
            "created_at": "2026-09-21T00:00:00",
        }]
    }, ensure_ascii=False), encoding="utf-8")
    # 前几个用例的后台线程可能抢先触发过恢复；写好文件后重新置位。
    tasks._RECOVERED = False

    loaded = tasks.load_tasks()
    assert loaded["old"]["status"] == tasks.STATUS_FAILED
    assert "重新上传PDF" in loaded["old"]["error"]
