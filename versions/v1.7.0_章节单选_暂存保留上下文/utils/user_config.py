# -*- coding: utf-8 -*-
"""用户配置持久化：记忆年级选择等用户偏好。

存储位置：data/user_config.json
新用户默认一年级，选择后自动保存，下次打开自动恢复。
"""

from __future__ import annotations

import json
from pathlib import Path

import config

USER_CONFIG_FILE = Path(config.DATA_DIR) / "user_config.json"

# 默认配置：新用户默认一年级
DEFAULT_CONFIG = {
    "last_grade_display": "一年级",  # 界面显示口径的年级
}


def load_user_config() -> dict:
    """读取用户配置；文件不存在或损坏时返回默认配置。"""
    if USER_CONFIG_FILE.exists():
        try:
            with open(USER_CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            result = dict(DEFAULT_CONFIG)
            result.update({k: v for k, v in saved.items() if v is not None})
            return result
        except (OSError, json.JSONDecodeError):
            pass
    return dict(DEFAULT_CONFIG)


def save_user_config(**kwargs) -> dict:
    """保存用户配置（合并更新，不覆盖未传入的字段）。"""
    config.ensure_dirs()
    current = load_user_config()
    for key, value in kwargs.items():
        if value is not None:
            current[key] = value
    try:
        with open(USER_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(current, f, ensure_ascii=False, indent=2)
    except OSError:
        pass  # 保存失败不影响使用
    return current


def get_last_grade_display() -> str:
    """获取上次选择的年级（界面显示口径），新用户默认一年级。"""
    return load_user_config().get("last_grade_display", "一年级")


def set_last_grade_display(grade_display: str) -> None:
    """保存当前选择的年级（界面显示口径）。"""
    save_user_config(last_grade_display=grade_display)
