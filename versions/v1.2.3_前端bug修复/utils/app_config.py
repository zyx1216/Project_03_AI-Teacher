# -*- coding: utf-8 -*-
"""
全局应用配置服务。

v1.2 起应用支持多学科切换：当前任教科目保存在 data/app_config.json。
这里只管轻量 JSON 配置，不碰数据库；历史成绩不会因为切换学科而改变。
"""

from __future__ import annotations

import json
from typing import Any

import config

DEFAULT_SUBJECT = "数学"

ALL_SUBJECTS = [
    "语文", "数学", "英语", "物理", "化学", "生物", "政治", "历史", "地理",
]

SUBJECT_ICONS = {
    "语文": "📖",
    "数学": "📐",
    "英语": "🔤",
    "物理": "⚛️",
    "化学": "🧪",
    "生物": "🧬",
    "政治": "⚖️",
    "历史": "📜",
    "地理": "🌍",
}

APP_CONFIG_PATH = config.DATA_DIR / "app_config.json"


def default_config() -> dict[str, str]:
    """返回应用默认配置。"""
    return {"current_subject": DEFAULT_SUBJECT}


def is_valid_subject(subject: Any) -> bool:
    """判断学科是否在支持列表内。"""
    return isinstance(subject, str) and subject in ALL_SUBJECTS


def load_app_config() -> dict[str, str]:
    """
    读取全局配置。

    文件不存在时创建默认文件；文件损坏或字段非法时回退到默认值，
    但不覆盖原文件，避免一次解析异常把用户配置彻底删掉。
    """
    try:
        raw = APP_CONFIG_PATH.read_text(encoding="utf-8")
        data = json.loads(raw)
        subject = data.get("current_subject") if isinstance(data, dict) else None
        if is_valid_subject(subject):
            return {"current_subject": subject}
    except FileNotFoundError:
        config_data = default_config()
        save_app_config(config_data)
        return config_data
    except (json.JSONDecodeError, OSError, TypeError, AttributeError):
        pass
    return default_config()


def save_app_config(config_data: dict[str, Any]) -> None:
    """保存全局配置；非法学科直接报错，不写文件。"""
    subject = config_data.get("current_subject") if isinstance(config_data, dict) else None
    if not is_valid_subject(subject):
        raise ValueError(f"不支持的学科：{subject}")
    APP_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    APP_CONFIG_PATH.write_text(
        json.dumps({"current_subject": subject}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_current_subject() -> str:
    """获取当前学科；配置缺失或损坏时默认数学。"""
    return load_app_config().get("current_subject", DEFAULT_SUBJECT)


def set_current_subject(subject: str) -> None:
    """设置当前学科。"""
    save_app_config({"current_subject": subject})


def get_subject_icon(subject: str | None = None) -> str:
    """获取学科图标；未传学科时使用当前学科。"""
    subject = subject or get_current_subject()
    return SUBJECT_ICONS.get(subject, SUBJECT_ICONS[DEFAULT_SUBJECT])
