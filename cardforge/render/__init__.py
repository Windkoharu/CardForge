"""卡面渲染层 —— 只做 re-export，不放任何逻辑。

分模块职责::

    geometry.py  版面几何：REF 坐标系 / 输出规格 / 换算（唯一数值真相源）
    assets.py    素材库：卡框、属性圆标、魔陷徽记、星级、箭头、覆膜、版权标
    fonts.py     字体解析：role → ttf/otf 路径、woff2 转换、覆盖率检测、SVG 光栅化

本模块用 PEP 562 的 ``__getattr__`` **惰性**转出子模块符号：``import cardforge.render``
不会因此加载 25MB 的中文字体索引或扫描素材树，只有真正访问
``cardforge.render.library`` / ``load`` 之类名字时才付出代价。
"""
from __future__ import annotations

from .geometry import (  # noqa: F401  —— 轻量，直接转出
    ART_GEN_SIZE,
    ART_RING_ALPHA,
    ART_RING_DEFAULT,
    FRAME_NATIVE,
    GEO,
    OUTPUT_SIZES,
    REF,
    Frame,
    make_frame,
    rect_of,
    scale_point,
    scale_rect,
)

__all__ = [
    # geometry
    "Frame", "make_frame", "rect_of", "scale_rect", "scale_point", "GEO",
    "REF", "FRAME_NATIVE", "OUTPUT_SIZES", "ART_GEN_SIZE",
    "ART_RING_DEFAULT", "ART_RING_ALPHA",
    # assets
    "AssetLibrary", "library", "set_svg_rasterizer", "svg_rasterizer",
    "FRAME_BASES", "ATTRIBUTE_KEYS", "SPELL_TRAP_KINDS", "ARROW_DIRECTIONS",
    "RARITY_KEYS", "CATEGORIES",
    # fonts
    "FONT_ROLES", "FONT_FILES", "resolve", "load", "load_for", "stack",
    "coverage", "coverage_candidates", "system_font_candidates", "diagnose",
    "rasterize_svg", "font_cache_dir", "clear_cache",
]

#: 名字 → 所在子模块（供 ``__getattr__`` 惰性转发）
_LAZY: dict[str, str] = {
    # ── assets ──
    "AssetLibrary": "assets", "library": "assets",
    "set_svg_rasterizer": "assets", "svg_rasterizer": "assets",
    "FRAME_BASES": "assets", "PENDULUM_BASES": "assets",
    "ATTRIBUTE_KEYS": "assets", "SPELL_TRAP_KINDS": "assets",
    "ARROW_DIRECTIONS": "assets", "RARITY_KEYS": "assets",
    "CATEGORIES": "assets", "DEFAULT_EXPECTED": "assets",
    # ── fonts ──
    "FONT_ROLES": "fonts", "FONT_FILES": "fonts", "FONT_ROLE_ALIASES": "fonts",
    "LANG_STACKS": "fonts", "resolve": "fonts", "load": "fonts",
    "load_for": "fonts", "stack": "fonts", "coverage": "fonts",
    "coverage_candidates": "fonts", "system_font_candidates": "fonts",
    "diagnose": "fonts", "rasterize_svg": "fonts", "font_cache_dir": "fonts",
    "clear_cache": "fonts", "truetype_index": "fonts",
}


def __getattr__(name: str):
    """PEP 562 惰性转发：``cardforge.render.<name>`` 按需加载 assets / fonts。"""
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module
    value = getattr(import_module(f".{module}", __name__), name)
    globals()[name] = value          # 转发后固定下来，后续访问不再走 __getattr__
    return value


def __dir__() -> list[str]:
    """让 ``dir(cardforge.render)`` 同时列出已转发符号与尚未加载的惰性符号。"""
    return sorted(set(globals()) | set(_LAZY))
