# -*- coding: utf-8 -*-
"""v2.3.0 迁移的可导入别名。

实际文件名为 v2.3.0_migration.py；Python 模块名不能含点，
因此用这个包装文件供 app.py 导入。
"""

from migrations.v2_3_0_impl import migrate

__all__ = ["migrate"]
