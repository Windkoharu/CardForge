"""内容内核 —— PSCT 卡文、效果 DSL、Lua 脚本、设计辅助。

子模块::

    psct/       多语言术语表 / PSCT 卡文生成 / 确定性 Linter
    effects.py  效果 DSL 注册表（效果种类 → 参数 / 句式 / Lua 片段）
    lua/        Lua 片段库 / 组装 / API 白名单 / 静态校验
    design.py   平衡审计（G1）· 系列一致性（G4）· 卡组分析
"""
from . import design, effects  # noqa: F401

__all__ = ["design", "effects"]
