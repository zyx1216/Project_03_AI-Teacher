# -*- coding: utf-8 -*-
"""学科常量测试。v1.3.0 起不再有全局当前学科配置。"""

import config
from utils import app_config


def test_subject_constants_complete():
    assert app_config.SUBJECT_NAMES == [
        "语文", "数学", "英语", "物理", "化学", "生物", "政治", "历史", "地理"
    ]
    assert app_config.ALL_SUBJECTS is app_config.SUBJECT_NAMES
    assert len(app_config.SUBJECT_NAMES) == 9


def test_default_subject_and_validation():
    assert app_config.DEFAULT_SUBJECT == "数学"
    assert app_config.is_valid_subject("物理")
    assert not app_config.is_valid_subject("体育")
    assert not app_config.is_valid_subject(None)


def test_global_subject_config_api_removed():
    for name in (
        "APP_CONFIG_PATH", "load_app_config", "save_app_config",
        "get_current_subject", "set_current_subject",
        "SUBJECT_ICONS", "get_subject_icon",
    ):
        assert not hasattr(app_config, name)


def test_app_name_is_fixed():
    assert config.APP_NAME == "AI教学辅助"
    assert not hasattr(config, "get_app_name")
