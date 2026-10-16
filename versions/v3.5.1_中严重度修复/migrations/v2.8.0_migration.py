# -*- coding: utf-8 -*-
"""v2.8.0 迁移（点号命名文件）：实现位于 v2_8_0_impl，这里仅转发。"""

from migrations.v2_8_0_impl import INDEX_SQL, NEW_TABLES, migrate  # noqa: F401

__all__ = ["migrate", "NEW_TABLES", "INDEX_SQL"]
