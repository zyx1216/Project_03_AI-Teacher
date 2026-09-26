# -*- coding: utf-8 -*-
"""功能级学科状态测试：全部使用临时 JSON，不碰真实 data/feature_subjects.json。"""

import json

import pytest

from utils import feature_subjects as fs


@pytest.fixture()
def state_path(tmp_path, monkeypatch):
    path = tmp_path / "feature_subjects.json"
    monkeypatch.setattr(fs, "FEATURE_SUBJECTS_PATH", path)
    return path


def test_missing_file_uses_math_defaults_and_creates_file(state_path):
    states = fs.load_feature_subjects()

    assert set(states) == set(fs.FEATURE_KEYS)
    assert set(states.values()) == {"数学"}
    assert state_path.exists()


def test_each_feature_key_can_be_set_independently(state_path):
    fs.set_feature_subject(fs.MATERIALS_SUBJECT, "物理")
    fs.set_feature_subject(fs.QUESTION_BANK_SUBJECT, "化学")

    assert fs.get_feature_subject(fs.MATERIALS_SUBJECT) == "物理"
    assert fs.get_feature_subject(fs.QUESTION_BANK_SUBJECT) == "化学"
    assert fs.get_feature_subject(fs.LESSON_PLAN_SUBJECT) == "数学"
    assert fs.get_feature_subject(fs.HOMEWORK_NEW_SUBJECT) == "数学"
    assert fs.get_feature_subject(fs.WRONG_BOOK_SUBJECT) == "数学"


def test_roundtrip_and_chinese_not_escaped(state_path):
    fs.set_feature_subject(fs.PPT_SUBJECT, "地理")

    raw = state_path.read_text(encoding="utf-8")
    assert '"ppt_subject": "地理"' in raw
    assert "\\u" not in raw
    assert json.loads(raw)["ppt_subject"] == "地理"


def test_invalid_subject_raises(state_path):
    with pytest.raises(ValueError):
        fs.set_feature_subject(fs.MATERIALS_SUBJECT, "体育")
    assert not state_path.exists()


def test_unknown_key_uses_default_read_and_rejects_write(state_path):
    assert fs.get_feature_subject("not_a_key") == "数学"
    with pytest.raises(ValueError):
        fs.set_feature_subject("not_a_key", "物理")


def test_corrupt_json_falls_back_without_overwriting(state_path):
    state_path.write_text("{坏 JSON", encoding="utf-8")

    assert fs.get_feature_subject(fs.MATERIALS_SUBJECT) == "数学"
    assert state_path.read_text(encoding="utf-8") == "{坏 JSON"


def test_extra_and_invalid_json_fields_ignored(state_path):
    state_path.write_text(
        json.dumps({"materials_subject": "物理", "unknown": "x"}, ensure_ascii=False),
        encoding="utf-8")

    states = fs.load_feature_subjects()
    assert states[fs.MATERIALS_SUBJECT] == "物理"
    assert states[fs.QUESTION_GEN_SUBJECT] == "数学"
