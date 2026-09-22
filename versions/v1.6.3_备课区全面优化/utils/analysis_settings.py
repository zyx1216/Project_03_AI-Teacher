# -*- coding: utf-8 -*-
"""考试分析的本地及格线/优秀线配置。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import config

THRESHOLDS_PATH = config.DATA_DIR / "analysis_thresholds.json"
DEFAULT_PASS_RATIO = 0.60
DEFAULT_EXCELLENT_RATIO = 0.85
DEFAULT_THRESHOLDS = {
    "pass_ratio": DEFAULT_PASS_RATIO,
    "excellent_ratio": DEFAULT_EXCELLENT_RATIO,
}


def validate_thresholds(data: dict[str, Any]) -> dict[str, float]:
    """校验比例配置，返回归一化后的浮点数。"""
    try:
        pass_ratio = float(data.get("pass_ratio", DEFAULT_PASS_RATIO))
        excellent_ratio = float(data.get("excellent_ratio", DEFAULT_EXCELLENT_RATIO))
    except (TypeError, ValueError) as exc:
        raise ValueError("及格线和优秀线必须是数字。") from exc
    if not (0.01 <= pass_ratio <= 0.99):
        raise ValueError("及格线比例必须在 1% 到 99% 之间。")
    if not (0.01 <= excellent_ratio <= 0.99):
        raise ValueError("优秀线比例必须在 1% 到 99% 之间。")
    if excellent_ratio <= pass_ratio:
        raise ValueError("优秀线必须高于及格线。")
    return {"pass_ratio": pass_ratio, "excellent_ratio": excellent_ratio}


def normalize_thresholds(thresholds: dict[str, Any] | None = None) -> dict[str, float]:
    """页面传字典则校验；不传则读取本地配置。"""
    if thresholds is not None:
        return validate_thresholds(thresholds)
    return load_thresholds()


def load_thresholds(path: Path | str | None = None) -> dict[str, float]:
    """读取配置；文件缺失自动创建，内容损坏时回退默认值且不覆盖。"""
    path = Path(path or THRESHOLDS_PATH)
    if not path.exists():
        save_thresholds(DEFAULT_THRESHOLDS, path)
        return dict(DEFAULT_THRESHOLDS)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return validate_thresholds(data)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return dict(DEFAULT_THRESHOLDS)


def save_thresholds(thresholds: dict[str, Any],
                    path: Path | str | None = None) -> dict[str, float]:
    """校验并保存配置。"""
    normalized = validate_thresholds(thresholds)
    path = Path(path or THRESHOLDS_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return normalized
