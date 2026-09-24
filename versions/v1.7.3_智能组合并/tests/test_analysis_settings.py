# -*- coding: utf-8 -*-
"""考试分析线本地配置测试。"""

import json

import pytest

from utils import analysis_settings as settings


def test_missing_file_created_with_defaults(tmp_path):
    path = tmp_path / "thresholds.json"
    result = settings.load_thresholds(path)
    assert result == {"pass_ratio": 0.60, "excellent_ratio": 0.85}
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved == result


def test_save_chinese_json_not_escaped(tmp_path):
    path = tmp_path / "thresholds.json"
    settings.save_thresholds({"pass_ratio": 0.5, "excellent_ratio": 0.8}, path)
    raw = path.read_text(encoding="utf-8")
    assert "0.5" in raw and "0.8" in raw
    assert "\\u" not in raw


def test_corrupt_json_falls_back_without_overwrite(tmp_path):
    path = tmp_path / "thresholds.json"
    path.write_text("{坏json", encoding="utf-8")
    assert settings.load_thresholds(path) == settings.DEFAULT_THRESHOLDS
    assert path.read_text(encoding="utf-8") == "{坏json"


@pytest.mark.parametrize("data", [
    {"pass_ratio": 0, "excellent_ratio": 0.8},
    {"pass_ratio": 1, "excellent_ratio": 1},
    {"pass_ratio": 0.8, "excellent_ratio": 0.8},
    {"pass_ratio": 0.9, "excellent_ratio": 0.5},
])
def test_invalid_thresholds(data):
    with pytest.raises(ValueError):
        settings.validate_thresholds(data)
