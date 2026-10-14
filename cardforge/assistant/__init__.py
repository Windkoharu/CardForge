"""内置助手「星奏·艾莉娅」—— 质量门的**表达层**。

她的定位（见 ``docs/01-总体设计.md`` §5）只有三件事：**翻译、向导、参谋**。
**她绝不参与裁决**：所有结论一律来自 ``tools.py`` 转调的确定性内核
（``pipeline.gates`` / ``content.*`` / ``pool.*`` / ``render.*`` / ``duel.*``）。

四个子模块：

    persona.py     三档人格与话术模板（只影响表达，不影响数字与规则号）
    providers.py   LLM 探测与统一接口 + 无 LLM 降级（NullProvider）
    tools.py       OpenAI function-calling 工具表（全部转调内核）
    knowledge.py   data/knowledge/*.md 切块与纯 Python 检索
    chat.py        会话编排：意图 → 工具 → 人格化转述
"""
from __future__ import annotations

from . import chat, knowledge, persona, providers, tools  # noqa: F401

__all__ = ["persona", "providers", "tools", "knowledge", "chat",
           "ASSISTANT_NAME", "ASSISTANT_NAME_SHORT"]

ASSISTANT_NAME = persona.ASSISTANT_NAME
ASSISTANT_NAME_SHORT = persona.ASSISTANT_NAME_SHORT
