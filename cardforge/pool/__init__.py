"""卡池层 —— 官方池查询（只读）、项目仓库（含版本快照）、cdb 读写。

分模块职责::

    cdb.py       .cdb（SQLite）读写：datas/texts、strings.conf、多语言导出
    official.py  官方卡池**只读**查询：全文检索、字段查重、卡号/setcode 占用
    repo.py      workspace/cards|archetypes|decks 的 CRUD + 快照与回滚

依赖方向：本层只允许 import ``core``。``cdb.write_strings_conf`` 在**函数内**延迟
import ``export.strings``（那是 ``strings.conf`` 的规范实现），不构成模块级反向依赖。
"""
from __future__ import annotations

from . import cdb, official, repo

__all__ = ["cdb", "official", "repo"]
