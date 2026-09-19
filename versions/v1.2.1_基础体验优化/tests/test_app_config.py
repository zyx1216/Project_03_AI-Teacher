# -*- coding: utf-8 -*-
"""全局学科配置测试：全部使用临时文件，不碰真实 data/app_config.json。"""

import json

import pytest

import config
from utils import app_config


@pytest.fixture()
def temp_config_path(tmp_path, monkeypatch):
    path = tmp_path / "app_config.json"
    monkeypatch.setattr(app_config, "APP_CONFIG_PATH", path)
    return path


def test_missing_config_returns_default_and_creates_file(temp_config_path):
    result = app_config.load_app_config()

    assert result == {"current_subject": "数学"}
    assert temp_config_path.exists()
    assert json.loads(temp_config_path.read_text(encoding="utf-8")) == result


def test_save_and_load_roundtrip(temp_config_path):
    app_config.save_app_config({"current_subject": "物理"})

    assert app_config.load_app_config() == {"current_subject": "物理"}


def test_set_current_subject_can_be_read_back(temp_config_path):
    app_config.set_current_subject("化学")

    assert app_config.get_current_subject() == "化学"


def test_default_current_subject_is_math(temp_config_path):
    assert app_config.get_current_subject() == "数学"


def test_nine_subjects_and_icons_complete():
    assert app_config.ALL_SUBJECTS == [
        "语文", "数学", "英语", "物理", "化学", "生物", "政治", "历史", "地理"
    ]
    assert len(app_config.ALL_SUBJECTS) == 9
    assert set(app_config.SUBJECT_ICONS) == set(app_config.ALL_SUBJECTS)


def test_get_subject_icon(temp_config_path):
    assert app_config.get_subject_icon("物理") == "⚛️"
    app_config.set_current_subject("地理")
    assert app_config.get_subject_icon() == "🌍"


def test_json_keeps_chinese_readable(temp_config_path):
    app_config.set_current_subject("生物")

    raw = temp_config_path.read_text(encoding="utf-8")
    assert '"current_subject": "生物"' in raw
    assert "\\u" not in raw


def test_invalid_subject_raises_value_error(temp_config_path):
    with pytest.raises(ValueError):
        app_config.set_current_subject("体育")
    assert not temp_config_path.exists()


def test_corrupt_config_falls_back_without_overwriting(temp_config_path):
    temp_config_path.write_text("{损坏的 JSON", encoding="utf-8")

    assert app_config.load_app_config() == {"current_subject": "数学"}
    assert temp_config_path.read_text(encoding="utf-8") == "{损坏的 JSON"


def test_get_app_name_follows_current_subject(temp_config_path):
    app_config.set_current_subject("物理")

    assert config.get_app_name() == "AI教学辅助·物理"
