"""``cardforge.art`` —— 卡图生成模块（对接本地 ComfyUI）。

模块分工
--------
``profiles.py``  模型档案表 + 自适应选择（8 个档案：krea2 / qwen_image / illustrious /
                 noobai / pony / animagine / sdxl / sd15），每个档案带**授权要点**。
``client.py``    ``ComfyClient``：只用标准库 urllib 的 ComfyUI HTTP 客户端，
                 模型探测走 ``/object_info`` 的 COMBO 候选（唯一正确方式）。
``graph.py``     ``Graph`` 图构造器：API 格式 ↔ **可直接导入 ComfyUI 的 UI 格式**，
                 并支持按可用节点集合优雅降级。
``prompt.py``    提示词工程：中文风格 → 英文标签、卡种氛围词、系列一致性前缀。
``presets.py``   预设（t2i_single / character_sheet / upscale / remove_bg / ...）。
``library.py``   卡图资产库：``workspace/pics/art/<archetype>/<card_id>/v{n}.png`` + ``meta.json``。
``run.py``       编排：探测 → 选档案 → 建图 → 提交 → 取图 → 入库 → 返回 ``ArtResult``。

对外常用入口
------------
>>> from cardforge.art import run, capabilities          # doctest: +SKIP
>>> capabilities()["online"]                             # doctest: +SKIP
True
"""
from __future__ import annotations

__all__ = [
    "profiles", "client", "graph", "prompt", "presets", "library", "run",
    "ModelProfile", "PROFILES", "detect", "by_key", "art_size_for",
    "ComfyClient", "Graph", "ArtRequest", "ArtResult",
    "generate", "generate_series", "export_workflow", "capabilities",
]

# 只做轻量重导出：重型子模块由调用方按需 import，避免 import 副作用。
from .profiles import PROFILES, ModelProfile, art_size_for, by_key, detect  # noqa: E402
from .client import ComfyClient  # noqa: E402
from .graph import Graph  # noqa: E402
from .run import capabilities, export_workflow, generate, generate_series  # noqa: E402
from ..core.models import ArtRequest, ArtResult  # noqa: E402
