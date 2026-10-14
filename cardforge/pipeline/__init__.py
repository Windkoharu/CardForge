"""编排层 —— 质量门与三条流水线。

    gates.py    G1–G5 质量门（**全部确定性**）· 豁免留痕 · 审计报告
    card.py     单卡流水线
    series.py   系列流水线
    deck.py     卡组流水线
    job.py      后台任务与进度事件（SSE 用）
"""
from . import gates  # noqa: F401

__all__ = ["gates"]
