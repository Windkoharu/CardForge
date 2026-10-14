"""对局验证 —— 三层降级。

    engine.py    探测 ocgcore（Windows dll / Linux so / macOS dylib）+ 平台指引
    ocgcore.py   ctypes 绑定（探测到引擎时才用）
    bot.py       简易决策器（驱动对局以暴露脚本错误）
    scenario.py  场景单测（摆场面 → 发动 → 断言）

设计立场：**宁可诚实降级，绝不假装跑过对局。**
未检测到引擎时，G3 返回 ``status="skipped"`` 并写明原因与获取指引。
"""
from . import engine  # noqa: F401

__all__ = ["engine"]
