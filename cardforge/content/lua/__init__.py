"""Lua 脚本子模块。

    apicatalog.py  ocgcore Lua API 白名单（从官方脚本库实测抽取）
    lint.py        G2 静态校验：语法 / BOM / API 存在性 / Stringid↔texts 同步
    fragments.py   效果片段库（每种效果一个模板）
    emit.py        组装器：EffectSpec → 可用的卡脚本
"""
from . import apicatalog, fragments, lint, emit  # noqa: F401

__all__ = ["apicatalog", "lint", "fragments", "emit"]
