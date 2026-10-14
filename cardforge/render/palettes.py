"""各卡种配色表 —— 用于程序化基座、文字墨色、以及素材缺失时的回退。

数值说明
--------
框色取自 **Yugipedia ``Card colors`` 页公布的官方 CSS 色值**（可信度高）：
效果 ``#FF8B53`` / 通常 ``#FDE68A`` / 仪式 ``#9DB5CC`` / 融合 ``#A086B7`` /
同步 ``#CCCCCC`` / 超量 ``#000000`` / 连接 ``#006EAD`` / 魔法 ``#1D9E74`` /
陷阱 ``#BC5A84`` / 衍生物 ``#828E85``。

两条官方附加规则已内建：
1. **卡名墨色**：默认黑；超量 / 连接 / 魔法 / 陷阱 用**白字**（仅在无卡名箔的
   罕贵下成立，更高罕贵会被卡名箔覆盖，见 ``render/rarities.py`` 的 ``name_fx``）。
2. **Series 11+ 所有卡种底色淡一档**：``palette(..., era="11")`` 或模块级
   ``set_era("11")`` 即取淡色版，用于还原不同期数的观感。

本表还承担：素材缺失时的程序化回退基座、前端预览的 CSS 令牌。
用户可在 ``data/templates/palettes.json`` 覆盖任意一项（存在即生效）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from ..core.paths import TEMPLATES

RGB = tuple[int, int, int]


def _h(s: str) -> RGB:
    s = s.lstrip("#")
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


@dataclass(frozen=True)
class Palette:
    key: str
    zh: str
    # 程序化基座用
    frame_bg: RGB
    frame_edge: RGB
    # 卡名条
    name_bar: RGB
    name_ink: RGB
    name_outline: RGB
    # 文本面板
    text_panel: RGB
    text_ink: RGB
    type_ink: RGB
    stat_ink: RGB
    # 分隔线与描边
    hairline: RGB

    def as_css(self) -> dict:
        f = lambda c: "#%02X%02X%02X" % c
        return {
            "frameBg": f(self.frame_bg), "frameEdge": f(self.frame_edge),
            "nameBar": f(self.name_bar), "nameInk": f(self.name_ink),
            "textPanel": f(self.text_panel), "textInk": f(self.text_ink),
            "typeInk": f(self.type_ink), "statInk": f(self.stat_ink),
            "hairline": f(self.hairline),
        }


def _p(key, zh, bg, edge, bar, ink, panel, tink, tyink=None, statink=None, hair=None) -> Palette:
    return Palette(
        key=key, zh=zh,
        frame_bg=_h(bg), frame_edge=_h(edge),
        name_bar=_h(bar), name_ink=_h(ink), name_outline=(28, 24, 18),
        text_panel=_h(panel), text_ink=_h(tink),
        type_ink=_h(tyink or tink), stat_ink=_h(statink or tink),
        hairline=_h(hair or "#6b6255"),
    )


_BUILTIN: dict[str, Palette] = {
    p.key: p for p in [
        # 框色 = 官方公布值；bar/edge 由框色推导（未公布的辅助色）
        _p("normal", "通常怪兽", "#FDE68A", "#B39B3F", "#E8CE6E", "#1A1508",
           "#FBF3D2", "#1A1508", tyink="#3A2F14", statink="#1A1508"),
        _p("effect", "效果怪兽", "#FF8B53", "#B25526", "#E0743C", "#1F0E05",
           "#FFE6D5", "#1F0E05", tyink="#4A2410", statink="#1F0E05"),
        _p("ritual", "仪式怪兽", "#9DB5CC", "#5F7B96", "#84A0BA", "#0D1620",
           "#E6EEF6", "#0D1620", tyink="#26405A", statink="#0D1620"),
        _p("fusion", "融合怪兽", "#A086B7", "#644B7A", "#8A6DA4", "#170D20",
           "#EDE4F5", "#170D20", tyink="#3D2750", statink="#170D20"),
        _p("synchro", "同步怪兽", "#CCCCCC", "#8F8F8F", "#B5B5B5", "#141414",
           "#F2F2F2", "#141414", tyink="#3D3D3D", statink="#141414"),
        _p("xyz", "超量怪兽", "#000000", "#000000", "#1C1C1C", "#FFFFFF",
           "#2E2E2E", "#FFFFFF", tyink="#D9D9D9", statink="#FFFFFF", hair="#8A8A8A"),
        _p("link", "连接怪兽", "#006EAD", "#003E63", "#005A8E", "#FFFFFF",
           "#1B4F72", "#FFFFFF", tyink="#CFE4F2", statink="#FFFFFF", hair="#5B8FB0"),
        _p("pendulum", "灵摆怪兽", "#FF8B53", "#B25526", "#E0743C", "#1F0E05",
           "#FFE6D5", "#1F0E05", tyink="#4A2410", statink="#1F0E05"),
        _p("spell", "魔法卡", "#1D9E74", "#0F6146", "#17835F", "#FFFFFF",
           "#DDF3EA", "#0A2B20", tyink="#123D2D", statink="#0A2B20"),
        _p("trap", "陷阱卡", "#BC5A84", "#7A3354", "#9E486E", "#FFFFFF",
           "#F7E1EA", "#330F1F", tyink="#4A1830", statink="#330F1F"),
        _p("token", "衍生物", "#828E85", "#4F5851", "#6B756D", "#101410",
           "#E6EAE7", "#101410", tyink="#2E3630", statink="#101410"),
        _p("skill", "技能卡", "#2290D6", "#12608F", "#1B78B4", "#061826",
           "#DCEBF7", "#061826", tyink="#123A57", statink="#061826"),
        _p("dark_synchro", "暗黑同步", "#555555", "#2E2E2E", "#454545", "#FFFFFF",
           "#6E6E6E", "#FFFFFF", tyink="#D6D6D6", statink="#FFFFFF", hair="#9A9A9A"),
    ]
}

#: Series 11 起所有卡种底色「淡一档」（官方描述 slightly paler shade）
_ERA_PALE = 0.16   # 向白色插值的比例


def _pale(p: Palette) -> Palette:
    f = lambda c: lighten(c, _ERA_PALE)  # noqa: E731
    return Palette(**{**p.__dict__,
                      "frame_bg": f(p.frame_bg), "name_bar": f(p.name_bar),
                      "frame_edge": f(p.frame_edge)})


_ERA: str = "10"


def set_era(era: str) -> None:
    """设置目标版式世代：``"10"``（默认，Series 10/11 常规）或 ``"11"``（淡一档）。"""
    global _ERA
    _ERA = "11" if str(era).startswith("11") else "10"


def get_era() -> str:
    return _ERA

#: 灵摆卡按底色卡型取不同配色
_PENDULUM_BASE_PALETTE = {
    "normal": "normal", "ritual": "ritual", "fusion": "fusion",
    "synchro": "synchro", "xyz": "xyz", "link": "link", "effect": "pendulum",
}

_OVERRIDE: dict | None = None


def _load_override() -> dict:
    """用户覆盖：data/templates/palettes.json（可选，存在才生效）。"""
    global _OVERRIDE
    if _OVERRIDE is not None:
        return _OVERRIDE
    _OVERRIDE = {}
    p = TEMPLATES / "palettes.json"
    try:
        if p.exists():
            raw = json.loads(p.read_text(encoding="utf-8"))
            for key, val in (raw.get("palettes") or {}).items():
                base = _BUILTIN.get(key)
                if not base:
                    continue
                merged = {**base.__dict__}
                for k, v in val.items():
                    if k in merged and isinstance(v, str) and v.startswith("#"):
                        merged[k] = _h(v)
                    elif k in merged:
                        merged[k] = v
                _OVERRIDE[key] = Palette(**merged)
    except Exception:
        _OVERRIDE = {}
    return _OVERRIDE


#: 属性会对卡名条做一点色偏（还原官方"属性影响框色"的观感，幅度很轻）
_ATTR_TINT: dict[str, tuple[int, int, int]] = {
    "光": (12, 10, -6), "暗": (-8, -6, 6), "地": (4, 2, -8),
    "水": (-10, 4, 12), "炎": (14, -6, -8), "风": (-4, 10, 2), "神": (10, 6, 14),
}


def palette(frame: str, attribute: str = "", *, tint: bool = True,
            era: str | None = None) -> Palette:
    """取某卡种的配色。

    ``frame``    ``core.enums.FRAMES`` 的键（含 ``spell``/``trap``/``token``/``skill``）
    ``attribute`` 中文属性名，用于卡名条与框底的轻微色偏
    ``era``      ``"10"``（默认）或 ``"11"``（淡一档）；None 用 :func:`set_era` 的全局值
    """
    ov = _load_override()
    key = frame
    if "pendulum" in frame:
        base = frame.replace("_pendulum", "").replace("pendulum", "").strip("_") or "effect"
        key = _PENDULUM_BASE_PALETTE.get(base, "pendulum")
    p = ov.get(key) or _BUILTIN.get(key) or _BUILTIN["effect"]
    if (era or _ERA).startswith("11"):
        p = _pale(p)
    if not tint or attribute not in _ATTR_TINT:
        return p
    d = _ATTR_TINT[attribute]
    f = lambda c: tuple(max(0, min(255, c[i] + d[i])) for i in range(3))  # noqa: E731
    return Palette(**{**p.__dict__, "name_bar": f(p.name_bar), "frame_bg": f(p.frame_bg)})


def name_is_white(frame: str) -> bool:
    """官方规则：超量 / 连接 / 魔法 / 陷阱 的卡名用白字（无卡名箔时）。"""
    return frame in ("xyz", "link", "spell", "trap", "dark_synchro")


def lerp(a: RGB, b: RGB, t: float) -> RGB:
    """两色线性插值，t 支持 <0 与 >1（会自动截断到 0–255）。"""
    t = max(0.0, min(1.0, float(t)))
    return tuple(max(0, min(255, round(a[i] + (b[i] - a[i]) * t))) for i in range(3))  # type: ignore[return-value]


def lighten(c: RGB, t: float) -> RGB:
    return lerp(c, (255, 255, 255), t)


def darken(c: RGB, t: float) -> RGB:
    return lerp(c, (0, 0, 0), t)


def as_css_tokens() -> dict:
    """给前端用的 CSS 变量包。"""
    out = {}
    for key in _BUILTIN:
        out[key] = palette(key).as_css()
    return out


def list_palettes() -> list[dict]:
    return [{"key": p.key, "zh": p.zh, "css": p.as_css()} for p in _BUILTIN.values()]
