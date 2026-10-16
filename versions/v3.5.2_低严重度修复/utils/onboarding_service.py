# -*- coding: utf-8 -*-
"""新手引导状态服务。"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import config

ONBOARDING_PATH = config.DATA_DIR / "onboarding.json"


def guide_steps() -> list[dict]:
    """返回固定六步引导。"""
    return [
        {"id": "welcome", "title": "欢迎使用", "description": "了解首页、智能提醒和 AI 教学建议。"},
        {"id": "import_students", "title": "导入学生", "description": "在学情 → 学生管理中导入班级名单。"},
        {"id": "import_scores", "title": "导入成绩", "description": "在学情 → 成绩管理中导入第一次考试成绩。"},
        {"id": "create_lesson", "title": "创建教案", "description": "在备课 → AI 备课中生成第一份教案。"},
        {"id": "ai_questions", "title": "AI 出题", "description": "在备课 → AI 出题中生成配套练习。"},
        {"id": "done", "title": "完成", "description": "引导完成，可随时在设置 → 帮助中心查看说明。"},
    ]


def default_status() -> dict:
    """默认引导状态。"""
    return {
        "completed_steps": [],
        "skipped": False,
        "snooze_until": "",
        "updated_at": "",
    }


def load_status(path: Path | str | None = None) -> dict:
    """读取状态；文件缺失或 JSON 损坏时回退默认，不覆盖原文件。"""
    target = Path(path or ONBOARDING_PATH)
    if not target.exists():
        return default_status()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default_status()
    status = default_status()
    if isinstance(raw, dict):
        completed = raw.get("completed_steps", [])
        valid = {item["id"] for item in guide_steps()}
        if isinstance(completed, list):
            status["completed_steps"] = [x for x in completed if x in valid]
        status["skipped"] = bool(raw.get("skipped", False))
        snooze = raw.get("snooze_until")
        status["snooze_until"] = snooze if isinstance(snooze, str) else ""
        updated = raw.get("updated_at")
        status["updated_at"] = updated if isinstance(updated, str) else ""
    return status


# 计划中的别名接口
get_status = load_status


def save_status(status: dict, path: Path | str | None = None) -> None:
    """写入状态，UTF-8 且不转义中文。"""
    target = Path(path or ONBOARDING_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    status["updated_at"] = datetime.now().isoformat(timespec="seconds")
    target.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")


def complete_step(step: str, path: Path | str | None = None) -> dict:
    """标记一步完成；最后一步完成后自动取消跳过/暂缓标记。"""
    status = load_status(path)
    if step not in {item["id"] for item in guide_steps()}:
        raise ValueError(f"未知引导步骤：{step}")
    if step not in status["completed_steps"]:
        status["completed_steps"].append(step)
    if step == "done":
        status["skipped"] = False
        status["snooze_until"] = ""
    save_status(status, path)
    return status


# 计划中的别名接口
set_onboarding_step = complete_step


def skip(path: Path | str | None = None) -> dict:
    """跳过引导，之后不再自动弹出。"""
    status = load_status(path)
    status["skipped"] = True
    status["snooze_until"] = ""
    save_status(status, path)
    return status


def snooze(path: Path | str | None = None, until: date | None = None) -> dict:
    """暂缓到次日。"""
    status = load_status(path)
    day = until or (date.today() + timedelta(days=1))
    status["snooze_until"] = day.isoformat()
    save_status(status, path)
    return status


def reset(path: Path | str | None = None) -> dict:
    """重置引导，用于设置页重新观看。"""
    status = default_status()
    save_status(status, path)
    return status


def should_show(status: dict | None = None, today: date | None = None) -> bool:
    """判断首页是否需要自动弹出引导。"""
    status = status or load_status()
    if status.get("skipped"):
        return False
    day = today or date.today()
    snooze_until = status.get("snooze_until")
    if snooze_until:
        try:
            if day < date.fromisoformat(snooze_until):
                return False
        except ValueError:
            pass
    completed = set(status.get("completed_steps", []))
    return "done" not in completed and len(completed) < len(guide_steps())
