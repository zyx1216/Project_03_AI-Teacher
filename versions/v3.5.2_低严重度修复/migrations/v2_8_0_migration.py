# -*- coding: utf-8 -*-
"""v2.8.0 迁移的可导入别名。

实际实现见 migrations/v2_8_0_impl.py；Python 模块名不能含点，
因此用这个包装文件供其它模块导入。
"""

from migrations.v2_8_0_impl import INDEX_SQL, NEW_TABLES, migrate

__all__ = ["migrate", "NEW_TABLES", "INDEX_SQL"]
