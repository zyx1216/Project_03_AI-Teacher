# -*- coding: utf-8 -*-
"""学科常量与校验。

v1.3.0 起不再保存“全局当前学科”；各功能自己的选择由 feature_subjects 管理。
"""

from __future__ import annotations

from typing import Any

DEFAULT_SUBJECT = "数学"

# 历史代码曾使用 ALL_SUBJECTS，保留别名，后续新代码请用 SUBJECT_NAMES。
SUBJECT_NAMES = ALL_SUBJECTS = [
    "语文", "数学", "英语", "物理", "化学", "生物", "政治", "历史", "地理",
]


def is_valid_subject(subject: Any) -> bool:
    """判断学科是否受支持。"""
    return isinstance(subject, str) and subject in SUBJECT_NAMES
