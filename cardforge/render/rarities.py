"""罕贵注册表 —— 声明式「五层可叠加」模型 + 14 种闪膜花纹。

设计要点
--------
官方的罕贵**只由箔工决定**（不由封入率决定），且可分别作用于：
卡名 / 卡图 / 属性符号 / 等级·阶级星 / 文本框边框 / 卡框 / 卡框边框。

旧版把罕贵做成"整卡叠一张 RGBA"，导致不该闪的地方也闪（文本框、卡图）——本模块重做：

    ① 框底色层   ② 卡图·属性·星级层   ③ 卡名箔层   ④ 全卡闪膜层   ⑤ 浮雕层

**罕贵 = 五层的不同组合**。新增罕贵**只改数据不改代码**。

花纹来源：日文 Wiki 对平行加工模样的分类（14 种已确认）+ 金属/虹彩渐变。

依赖：Pillow（必需）、numpy（可选，缺失时自动退回纯 Pillow 实现）。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from . import geometry as G
from .palettes import Palette, lighten, darken, lerp

try:  # numpy 是可选加速项
    import numpy as _np
except Exception:  # pragma: no cover
    _np = None

RGB = tuple[int, int, int]
HAS_NUMPY = _np is not None

# ══════════════════════════════════════════════════════════════════════
#  作用区域
# ══════════════════════════════════════════════════════════════════════
REGIONS = (
    "whole", "frame", "frame_edge", "artwork", "name", "textbox", "type_line",
    "stats", "attribute", "level", "link_arrows", "copyright",
)
#: 官方罕贵可分别作用的部位（用于 UI 提示）
OFFICIAL_PARTS = ("name", "artwork", "attribute", "level", "textbox", "frame", "frame_edge")

# ══════════════════════════════════════════════════════════════════════
#  14 种闪膜花纹 + 金属/虹彩
# ══════════════════════════════════════════════════════════════════════
PATTERNS = (
    "none", "grid", "dot", "shatter", "mosaic", "bubble", "star", "wave",
    "diag_grid", "radial", "star_scale", "rising", "hieroglyph", "kc_board",
    "metal", "prism", "holo_rainbow", "silver", "gold", "dt_sparkle",
)
#: 官方平行加工的 14 种确认花纹（供 UI 分类展示）
OFFICIAL_FOIL_PATTERNS = (
    "grid", "dot", "shatter", "mosaic", "bubble", "star", "wave", "diag_grid",
    "radial", "star_scale", "rising", "hieroglyph", "kc_board", "dot",
)

_TEX_CACHE: dict[tuple, Image.Image] = {}


def _rainbow_stops(angle: float = 0.0, n: int = 7, bright: float = 1.0) -> list[RGB]:
    """虹彩停止点。``angle`` 只影响相位，让不同参数看起来不一样。"""
    base = [(255, 92, 92), (255, 196, 92), (250, 255, 120), (120, 255, 160),
            (110, 214, 255), (150, 140, 255), (255, 120, 220)]
    shift = int(round(angle / 18.0)) % n
    out = []
    for i in range(n):
        r, g, b = base[(i + shift) % n]
        out.append((min(255, int(r * bright)), min(255, int(g * bright)),
                    min(255, int(b * bright))))
    return out


def _gradient(size: tuple[int, int], stops: Iterable[RGB], angle: float
              ) -> Image.Image:
    """线性渐变（RGB）。``angle`` 单位度，0 = 从左到右。"""
    w, h = size
    stops = list(stops)
    n = max(1, len(stops) - 1)
    # 先做一条水平渐变条再旋转（比逐像素算方向快得多）
    strip_h = 1
    strip = Image.new("RGB", (max(2, w), strip_h))
    px = strip.load()
    for x in range(strip.width):
        t = x / max(1, strip.width - 1) * n
        i = min(n - 1, int(t))
        f = t - i
        a, b = stops[i], stops[min(len(stops) - 1, i + 1)]
        px[x, 0] = lerp(a, b, f)
    img = strip.resize((w, h), Image.NEAREST)
    if angle % 360:
        # 放大后旋转再裁回，避免出现空白角
        diag = int(math.hypot(w, h)) + 2
        big = img.resize((diag, diag), Image.NEAREST).rotate(
            -angle, resample=Image.BILINEAR, expand=False)
        left = (diag - w) // 2
        top = (diag - h) // 2
        img = big.crop((left, top, left + w, top + h))
    return img


def _noise(size: tuple[int, int], seed: int = 7) -> Image.Image:
    """确定性噪声（L 模式）。numpy 可用时用向量化，否则用 Pillow effect_noise。"""
    w, h = size
    if _np is not None:
        rng = _np.random.default_rng(seed)
        a = rng.integers(0, 256, size=(h, w), dtype=_np.uint8)
        return Image.fromarray(a, mode="L")
    return Image.effect_noise(size, 64)


def _shape_layer(size: tuple[int, int], draw_fn: Callable, scale: float = 1.0,
                 seed: int = 3) -> Image.Image:
    """用 ImageDraw 画一个 L 模式的花纹层（白色图形、黑底）。"""
    w, h = size
    img = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(img)
    draw_fn(d, w, h, scale, seed)
    return img


def _draw_grid(d, w, h, s, seed):
    step = max(4, int(26 * s))
    for x in range(0, w + step, step):
        d.line([(x, 0), (x, h)], fill=255, width=max(1, int(1.6 * s)))
    for y in range(0, h + step, step):
        d.line([(0, y), (w, y)], fill=255, width=max(1, int(1.6 * s)))


def _draw_diag_grid(d, w, h, s, seed):
    step = max(4, int(22 * s))
    for i in range(-h, w + h, step):
        d.line([(i, 0), (i + h, h)], fill=255, width=max(1, int(1.4 * s)))
    for i in range(-h, w + h, step):
        d.line([(i, h), (i + h, 0)], fill=255, width=max(1, int(1.4 * s)))


def _draw_dot(d, w, h, s, seed):
    step = max(4, int(11 * s))
    r = max(1, int(1.7 * s))
    for y in range(0, h + step, step):
        for x in range(0, w + step, step):
            d.ellipse([x - r, y - r, x + r, y + r], fill=255)


def _draw_mosaic(d, w, h, s, seed):
    step = max(5, int(17 * s))
    q = max(2, int(6 * s))
    for y in range(0, h + step, step):
        for x in range(0, w + step, step):
            d.rectangle([x, y, x + q, y + q], fill=255)


def _draw_shatter(d, w, h, s, seed):
    import random
    rnd = random.Random(seed)
    step = max(8, int(26 * s))
    for y in range(0, h + step, step):
        for x in range(0, w + step, step):
            pts = [(x + rnd.randint(-4, step), y + rnd.randint(-4, step))
                   for _ in range(3)]
            d.polygon(pts, fill=255)


def _draw_bubble(d, w, h, s, seed):
    import random
    rnd = random.Random(seed + 1)
    step = max(8, int(24 * s))
    for y in range(0, h + step, step):
        for x in range(0, w + step, step):
            r = int(step * rnd.uniform(0.35, 0.55))
            d.ellipse([x - r, y - r, x + r, y + r], outline=255,
                      width=max(1, int(1.5 * s)))


def _star_poly(cx, cy, r, n=5, rot=-90.0, inner=0.45):
    pts = []
    for i in range(n * 2):
        ang = math.radians(rot + i * 180.0 / n)
        rr = r if i % 2 == 0 else r * inner
        pts.append((cx + rr * math.cos(ang), cy + rr * math.sin(ang)))
    return pts


def _draw_star(d, w, h, s, seed, scale_mul=1.0, n=5):
    import random
    rnd = random.Random(seed + 2)
    step = max(10, int(30 * s))
    r = step * 0.32 * scale_mul
    for y in range(0, h + step, step):
        for x in range(0, w + step, step):
            jx, jy = rnd.randint(-3, 3), rnd.randint(-3, 3)
            d.polygon(_star_poly(x + jx, y + jy, r, n=n), fill=255)


def _draw_wave(d, w, h, s, seed):
    amp = max(2, int(6 * s))
    step = max(5, int(15 * s))
    period = max(20, int(70 * s))
    for y0 in range(0, h + step, step):
        pts = [(x, y0 + amp * math.sin(x / period * math.tau)) for x in range(0, w + 2, 2)]
        d.line(pts, fill=255, width=max(1, int(1.3 * s)))


def _draw_radial(d, w, h, s, seed):
    cx, cy = w / 2, h / 2
    n = max(16, int(96 / max(0.4, s)))
    rmax = math.hypot(w, h) / 2
    for i in range(n):
        a = math.tau * i / n
        d.line([(cx, cy), (cx + rmax * math.cos(a), cy + rmax * math.sin(a))],
               fill=255, width=max(1, int(1.5 * s)))


def _draw_rising(d, w, h, s, seed):
    step = max(6, int(20 * s))
    q = max(2, int(7 * s))
    for y in range(0, h + step, step):
        for x in range(0, w + step, step):
            d.rectangle([x, y, x + q, y + q], fill=255)
    _draw_radial(d, w, h, s * 1.6, seed)


def _draw_hieroglyph(d, w, h, s, seed):
    """象形文字闪膜（Millennium Rare 用）：抽象符号散布。"""
    import random
    rnd = random.Random(seed + 5)
    step = max(10, int(30 * s))
    glyph = [
        lambda x, y, u: d.line([(x, y), (x + u, y)], fill=255, width=2),
        lambda x, y, u: d.ellipse([x, y, x + u, y + u * 0.7], outline=255, width=2),
        lambda x, y, u: d.rectangle([x, y, x + u * 0.6, y + u * 0.8], outline=255, width=2),
        lambda x, y, u: d.line([(x, y + u), (x + u * 0.5, y), (x + u, y + u)], fill=255, width=2),
        lambda x, y, u: d.arc([x, y, x + u, y + u], 200, 340, fill=255, width=2),
    ]
    u = step * 0.45
    for y in range(0, h + step, step):
        for x in range(0, w + step, step):
            rnd.choice(glyph)(x + rnd.randint(-2, 2), y + rnd.randint(-2, 2), u)


def _draw_kc_board(d, w, h, s, seed):
    """KC 基板闪膜：电路走线 + 社章式圆点。"""
    import random
    rnd = random.Random(seed + 6)
    step = max(10, int(34 * s))
    for y in range(0, h + step, step):
        for x in range(0, w + step, step):
            x2 = x + rnd.choice([-step, step])
            y2 = y + rnd.choice([-step, step])
            d.line([(x, y), (x2, y), (x2, y2)], fill=255, width=max(1, int(1.6 * s)))
            d.ellipse([x - 3, y - 3, x + 3, y + 3], fill=255)


def _draw_metal(size: tuple[int, int], s: float = 1.0, seed: int = 7) -> Image.Image:
    """纵向拉丝金属（UR/SER 底纹）。返回 L 模式图；签名与其它花纹不同，故不入 _DRAWERS。"""
    w, h = size
    if _np is not None:
        rng = _np.random.default_rng(seed + 11)
        col = rng.normal(140, 34, size=(1, w)).clip(30, 250)
        col = _np.repeat(col, h, axis=0)
        return Image.fromarray(col.astype(_np.uint8), mode="L")
    import random
    rnd = random.Random(seed + 11)
    row = bytes(int(max(30, min(250, rnd.gauss(140, 34)))) for _ in range(w))
    return Image.frombytes("L", (w, h), row * h)


_DRAWERS: dict[str, Callable] = {
    "grid": _draw_grid, "diag_grid": _draw_diag_grid, "dot": _draw_dot,
    "mosaic": _draw_mosaic, "shatter": _draw_shatter, "bubble": _draw_bubble,
    "star": _draw_star, "wave": _draw_wave, "radial": _draw_radial,
    "rising": _draw_rising, "hieroglyph": _draw_hieroglyph, "kc_board": _draw_kc_board,
    "star_scale": lambda d, w, h, s, sd: _draw_star(d, w, h, s, sd, 1.6, 6),
}


def pattern_texture(pattern: str, size: tuple[int, int], *, angle: float = 0.0,
                    scale: float = 1.0, seed: int = 7,
                    tint: RGB | None = None) -> Image.Image:
    """生成花纹纹理（RGB，与 ``size`` 同尺寸）。结果会缓存。

    ``tint`` 给定时，明暗花纹被染成该色系；否则用虹彩/金属色。
    """
    key = (pattern, size, round(angle, 2), round(scale, 3), seed, tint)
    hit = _TEX_CACHE.get(key)
    if hit is not None:
        return hit

    if pattern in ("none", "", None):
        img = Image.new("RGB", size, (128, 128, 128))
        _TEX_CACHE[key] = img
        return img

    # 金属/银/金/虹彩类：直接给渐变
    if pattern in ("silver", "gold", "prism", "holo_rainbow"):
        if pattern == "silver":
            stops = [(214, 218, 226), (255, 255, 255), (150, 158, 172),
                     (238, 242, 250), (176, 182, 196)]
        elif pattern == "gold":
            stops = [(168, 126, 36), (255, 232, 150), (206, 162, 58),
                     (255, 246, 200), (176, 134, 42)]
        else:
            bright = 1.0 if pattern == "prism" else 1.08
            stops = _rainbow_stops(angle, bright=bright)
        img = _gradient(size, stops, angle)
        if pattern == "prism":            # 棱镜碎带细网格
            g = _shape_layer(size, _draw_grid, max(0.35, scale * 0.55), seed).point(
                lambda v: int(v * 0.55))
            img = ImageChops.screen(img, Image.merge("RGB", (g, g, g)))
        _TEX_CACHE[key] = img
        return img

    if pattern == "metal":
        m = _draw_metal(size, scale, seed)
        img = Image.merge("RGB", (m, m, m))
        if tint:
            img = ImageChops.multiply(img, Image.new("RGB", size, tint))
            img = ImageChops.screen(img, Image.new("RGB", size,
                                                   tuple(int(c * 0.35) for c in tint)))
        _TEX_CACHE[key] = img
        return img

    if pattern == "dt_sparkle":           # DT 碎钻：细密点 + 噪声
        m = _shape_layer(size, _draw_dot, max(0.4, scale * 0.45), seed)
        n = _noise(size, seed + 3).point(lambda v: int(v * 0.55))
        m = ImageChops.lighter(m, n)
        base = _gradient(size, _rainbow_stops(angle, bright=0.95), angle)
    else:
        drawer = _DRAWERS.get(pattern)
        if drawer is None:
            m = _shape_layer(size, _draw_dot, scale, seed)
        else:
            m = _shape_layer(size, drawer, scale, seed)
        base = _gradient(size, _rainbow_stops(angle), angle) if tint is None else \
            _gradient(size, [darken(tint, 0.55), lighten(tint, 0.75), tint,
                             lighten(tint, 0.35), darken(tint, 0.35)], angle)
    # 花纹处接近满亮度、空白处压到 35% —— screen 后对比清晰（细线花纹也能看见）
    m3 = Image.merge("RGB", (m, m, m))
    low = ImageChops.multiply(base, Image.new("RGB", size, (88, 88, 88)))
    hi = ImageChops.multiply(base, m3)
    img = ImageChops.screen(low, hi)
    _TEX_CACHE[key] = img
    return img


def clear_texture_cache() -> None:
    _TEX_CACHE.clear()


# ══════════════════════════════════════════════════════════════════════
#  区域遮罩
# ══════════════════════════════════════════════════════════════════════
_MASK_CACHE: dict[tuple, Image.Image] = {}


def region_mask(region: str, frame_obj: G.Frame, *, pendulum: bool = False,
                feather: float = 1.5) -> Image.Image:
    """生成某作用区域的 L 模式遮罩（255 = 完全作用）。结果缓存。"""
    key = (region, frame_obj.width, frame_obj.height, pendulum, round(feather, 2))
    hit = _MASK_CACHE.get(key)
    if hit is not None:
        return hit

    w, h = frame_obj.width, frame_obj.height
    m = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(m)

    def box(name: str, inset: float = 0.0):
        x, y, bw, bh = frame_obj.anchor_box(name)
        return [x + inset, y + inset, x + bw - inset, y + bh - inset]

    if region == "whole":
        d.rectangle([0, 0, w, h], fill=255)
    elif region == "frame":
        d.rectangle([0, 0, w, h], fill=255)
        art = box(G.PENDULUM_ART_KEY if pendulum else G.STANDARD_ART_KEY, -2)
        d.rectangle(art, fill=0)
    elif region == "frame_edge":
        d.rectangle([0, 0, w, h], fill=255)
        d.rectangle(box("frame_inset"), fill=0)
    elif region == "artwork":
        d.rectangle(box(G.PENDULUM_ART_KEY if pendulum else G.STANDARD_ART_KEY), fill=255)
    elif region == "name":
        d.rounded_rectangle(box("title_bevel"), radius=max(2, frame_obj.px(8)), fill=255)
    elif region == "textbox":
        d.rectangle(box("pendulum_panel" if pendulum else "text_panel"), fill=255)
        if pendulum:   # 灵摆还有下半段怪兽效果框
            d.rectangle(box("pendulum_monster_panel"), fill=255)
    elif region == "type_line":
        d.rectangle(box("pendulum_type_line" if pendulum else "type_line"), fill=255)
    elif region == "stats":
        x, y, bw, bh = frame_obj.rect("stats_separator")
        d.rectangle([x, y, x + bw, h], fill=255)
    elif region == "attribute":
        d.ellipse(box("badge"), fill=255)
    elif region == "level":
        # 星级行：从 rank_star 左边界到 level_star 右边界
        x1, y1, _, _ = frame_obj.rect("rank_star")
        x2, y2, sw, sh = frame_obj.rect("level_star")
        d.rectangle([x1, y1, x2 + sw, y1 + sh], fill=255)
    elif region == "link_arrows":
        d.rectangle(box(G.PENDULUM_ART_KEY if pendulum else G.STANDARD_ART_KEY), fill=255)
    elif region == "copyright":
        d.rectangle(box("copyright"), fill=255)
    else:
        d.rectangle([0, 0, w, h], fill=255)

    if feather > 0:
        m = m.filter(ImageFilter.GaussianBlur(frame_obj.px(feather)))
    _MASK_CACHE[key] = m
    return m


def clear_mask_cache() -> None:
    _MASK_CACHE.clear()


# ══════════════════════════════════════════════════════════════════════
#  层声明
# ══════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class Foil:
    """闪膜层。``asset`` 与 ``pattern`` 二选一（asset 优先，用于还原官方素材）。"""
    region: str = "whole"
    pattern: str = "grid"
    blend: str = "screen"          # screen/overlay/soft_light/hard_light/multiply/add
    opacity: float = 0.5
    angle: float = 0.0
    scale: float = 1.0
    tint: RGB | None = None
    asset: str = ""                # 形如 "rare/ur.png"，来自 assets
    feather: float = 1.5


@dataclass(frozen=True)
class Emboss:
    """浮雕/压纹层（法线模拟：双向阴影 + 多向高光）。"""
    region: str = "artwork"
    depth: float = 1.2
    angle: float = 45.0


@dataclass(frozen=True)
class NameFx:
    """卡名箔。``none`` 表示跟随卡种墨色（官方规则：超量/连接/魔陷为白字）。"""
    style: str = "none"            # none/gold/silver/diamond/rainbow/red/green/blue
    opacity: float = 0.9


@dataclass(frozen=True)
class RarityDef:
    key: str
    label: dict
    layers: tuple = ()
    name_fx: Optional[NameFx] = None
    frame_edge_fx: Optional[str] = None    # gold/silver/rainbow：卡框边框镀色
    version: int = 1
    official: bool = True
    note: str = ""


def _L(key: str, zh: str, ja: str, en: str) -> dict:
    return {"key": key, "zh_cn": zh, "ja": ja, "en": en}


#: 五种常用组合，便于声明
def _foil_art(p: str, o: float = 0.42, blend: str = "overlay", a: float = 22.0) -> Foil:
    return Foil("artwork", p, blend, o, a)


def _foil_whole(p: str, o: float = 0.40, blend: str = "overlay") -> Foil:
    return Foil("whole", p, blend, o)


# ══════════════════════════════════════════════════════════════════════
#  罕贵定义（键与 core.enums.RARITIES 一致）
# ══════════════════════════════════════════════════════════════════════
RARITY_DEFS: dict[str, RarityDef] = {
    d.key: d for d in [
        # ── 基础 ──
        RarityDef("common", _L("common", "平卡", "ノーマル", "Common"), ()),
        RarityDef("rare", _L("rare", "银字", "レア", "Rare"),
                  (Foil("name", "silver", "normal", 0.85, 0.0, 1.0),),
                  NameFx("silver", 0.9)),
        RarityDef("super", _L("super", "面闪", "スーパーレア", "Super Rare"),
                  (_foil_art("diag_grid", 0.34), _foil_art("prism", 0.30, "soft_light"),
                   Foil("attribute", "prism", "overlay", 0.5),
                   Foil("level", "prism", "overlay", 0.5))),
        RarityDef("ultra", _L("ultra", "金闪", "ウルトラレア", "Ultra Rare"),
                  (_foil_art("diag_grid", 0.34), _foil_art("gold", 0.34, "soft_light"),
                   Foil("attribute", "gold", "overlay", 0.55),
                   Foil("level", "gold", "overlay", 0.55)),
                  NameFx("gold", 0.92)),
        # ── 中高阶 ──
        RarityDef("ultimate", _L("ultimate", "浮雕", "アルティメットレア", "Ultimate Rare"),
                  (_foil_art("radial", 0.30), _foil_art("gold", 0.28, "soft_light")),
                  NameFx("gold", 0.92), note="卡图背景浮雕；Series 9 起不对角色轮廓加工"),
        RarityDef("secret", _L("secret", "银碎", "シークレットレア", "Secret Rare"),
                  (_foil_art("grid", 0.40), _foil_art("prism", 0.34, "soft_light")),
                  NameFx("diamond", 0.92),
                  note="OCG 为正井字、TCG 为斜平行线（斜碎）"),
        RarityDef("ultra_secret", _L("ultra_secret", "金碎", "ウルトラシークレットレア",
                                     "Ultra Secret Rare"),
                  (_foil_art("grid", 0.40), _foil_art("gold", 0.34, "soft_light"),
                   Foil("attribute", "gold", "overlay", 0.5)),
                  NameFx("diamond", 0.92), official=False, note="仅第 1、2 期"),
        RarityDef("extra_secret", _L("extra_secret", "斜碎", "エクストラシークレット",
                                     "Extra Secret Rare"),
                  (_foil_art("diag_grid", 0.46), _foil_art("prism", 0.30, "soft_light")),
                  NameFx("diamond", 0.92), frame_edge_fx="silver"),
        RarityDef("prismatic_secret", _L("prismatic_secret", "棱镜碎",
                                         "プリズマティックシークレット",
                                         "Prismatic Secret Rare"),
                  (_foil_whole("grid", 0.42, "overlay"), _foil_art("prism", 0.32, "soft_light")),
                  NameFx("diamond", 0.95), frame_edge_fx="silver",
                  note="箔扩大到全卡含边框；出框版即社区所称 OFPSE"),
        RarityDef("platinum_secret", _L("platinum_secret", "铂金碎",
                                        "プラチナシークレット", "Platinum Secret Rare"),
                  (_foil_whole("grid", 0.38, "overlay"), _foil_art("silver", 0.34, "soft_light")),
                  NameFx("diamond", 0.92), frame_edge_fx="silver", official=False),
        RarityDef("gold", _L("gold", "金字", "ゴールドレア", "Gold Rare"),
                  (_foil_art("radial", 0.26), Foil("stats", "gold", "overlay", 0.5),
                   Foil("level", "gold", "overlay", 0.6), Foil("textbox", "gold", "overlay", 0.16)),
                  NameFx("diamond", 0.9), frame_edge_fx="gold",
                  note="卡框/星/文本框描边镀金"),
        RarityDef("gold_secret", _L("gold_secret", "金碎（GSR）", "ゴールドシークレット",
                                    "Gold Secret Rare"),
                  (_foil_whole("grid", 0.40, "overlay"), _foil_art("gold", 0.40, "soft_light")),
                  NameFx("diamond", 0.95), frame_edge_fx="gold"),
        # ── 全息 / 平行 ──
        RarityDef("holographic", _L("holographic", "全息", "ホログラフィックレア",
                                    "Holographic Rare"),
                  (_foil_art("prism", 0.55, "screen"), _foil_art("radial", 0.34, "screen"),
                   Foil("frame", "holo_rainbow", "screen", 0.24)),
                  NameFx("diamond", 0.9), note="TCG 称 Ghost Rare；Series 13 起基本包取消"),
        RarityDef("parallel", _L("parallel", "爆闪", "パラレルレア", "Parallel Rare"),
                  (_foil_whole("diag_grid", 0.30, "screen"),)),
        RarityDef("normal_parallel", _L("normal_parallel", "平爆", "ノーマルパラレル",
                                        "Normal Parallel Rare"),
                  (_foil_whole("dot", 0.26, "screen"),)),
        RarityDef("rare_parallel", _L("rare_parallel", "面爆", "レアパラレル",
                                      "Rare Parallel Rare"),
                  (_foil_whole("diag_grid", 0.26, "screen"),
                   Foil("name", "silver", "normal", 0.85)),
                  NameFx("silver", 0.88)),
        RarityDef("collector", _L("collector", "典藏", "コレクターズレア", "Collector's Rare"),
                  (_foil_whole("radial", 0.34, "overlay"), _foil_art("shatter", 0.30),
                   Foil("frame", "prism", "soft_light", 0.26)),
                  NameFx("diamond", 0.92),
                  note="边缘与等级为不规则斜向花纹，卡图由中心向四周放射"),
        RarityDef("starlight", _L("starlight", "星光", "スターライトレア", "Starlight Rare"),
                  (_foil_whole("star_scale", 0.36, "screen"), _foil_art("prism", 0.40, "screen")),
                  NameFx("rainbow", 0.92)),
        RarityDef("quarter_century", _L("quarter_century", "四分之一世纪",
                                        "クォーターセンチュリー",
                                        "Quarter Century Secret Rare"),
                  (_foil_whole("grid", 0.42, "overlay"), _foil_art("gold", 0.40, "soft_light")),
                  NameFx("gold", 0.95), frame_edge_fx="gold",
                  note="PSER + 卡名金 + 效果栏叠「25 周年」立体水印"),
        RarityDef("20th_secret", _L("20th_secret", "20 周年版", "20thシークレットレア",
                                    "20th Secret Rare"),
                  (_foil_whole("grid", 0.42, "overlay"), _foil_art("red", 0.36, "soft_light")
                   if False else _foil_art("prism", 0.30, "soft_light"),
                   Foil("artwork", "prism", "screen", 0.22, 0.0, 1.0, (232, 60, 70))),
                  NameFx("red", 0.95), frame_edge_fx="silver"),
        RarityDef("millennium", _L("millennium", "千年", "ミレニアムレア", "Millennium Rare"),
                  (_foil_whole("hieroglyph", 0.34, "screen"),),
                  note="古埃及象形文字闪膜"),
        RarityDef("ghost", _L("ghost", "幽灵", "ゴーストレア", "Ghost Rare"),
                  (_foil_art("prism", 0.60, "screen"), _foil_art("radial", 0.40, "screen"),
                   Foil("textbox", "none", "screen", 0.0)),
                  NameFx("diamond", 0.92)),
        RarityDef("dt", _L("dt", "DT 碎钻", "デュエルターミナル", "Duel Terminal Rare"),
                  (_foil_whole("dt_sparkle", 0.36, "screen"),)),
        RarityDef("normal_rare", _L("normal_rare", "罕有平卡", "ノーマルレア", "Normal Rare"),
                  (), note="视觉与平卡完全一致，仅封入率不同；渲染器不做差异化"),
        # ── 复合标记 ──
        RarityDef("full_art", _L("full_art", "全画", "フルアート", "Full Art"),
                  (), official=False,
                  note="出框类，与覆膜正交（见 render/fullart.py），可与其他罕贵叠加"),
    ]
}

#: 出框卡常见的官方组合（供 UI 快捷选项）
COMBO_PRESETS = {
    "ofpse": ("prismatic_secret", "art_over", "出框 + 棱镜碎（OFPSE）"),
    "ofur": ("ultra", "art_bleed", "出框 + 金闪"),
    "gmr": ("quarter_century", "art_over", "Grand Master Rare 风格（虹色厚盛箔 + 序列号）"),
    "ghost_full": ("ghost", "full_bleed", "全息 + 全画"),
    "default_extended": ("secret", "art_bleed", "出血出框 + 银碎"),
}


def by_key(key: str) -> RarityDef:
    return RARITY_DEFS.get(key) or RARITY_DEFS["common"]


def list_rarities() -> list[dict]:
    return [{"key": d.key, "label": d.label, "official": d.official,
             "layers": len(d.layers), "name_fx": (d.name_fx.style if d.name_fx else "none"),
             "frame_edge_fx": d.frame_edge_fx, "note": d.note}
            for d in RARITY_DEFS.values()]


# ══════════════════════════════════════════════════════════════════════
#  应用
# ══════════════════════════════════════════════════════════════════════
_BLENDS: dict[str, Callable[[Image.Image, Image.Image], Image.Image]] = {
    "screen": ImageChops.screen,
    "multiply": ImageChops.multiply,
    "overlay": ImageChops.overlay,
    "soft_light": ImageChops.soft_light,
    "hard_light": ImageChops.hard_light,
    "add": ImageChops.add,
    "difference": ImageChops.difference,
    "lighter": ImageChops.lighter,
    "darker": ImageChops.darker,
}
BLEND_MODES = tuple(_BLENDS)


def _blend(base: Image.Image, top: Image.Image, mode: str) -> Image.Image:
    fn = _BLENDS.get(mode)
    if fn is None:
        return base
    try:
        return fn(base, top)
    except Exception:
        return base


def _emboss(img: Image.Image, mask: Image.Image, depth: float, angle: float) -> Image.Image:
    """用「位移差分 + 双向阴影/高光」近似浮雕压纹。"""
    d = max(0.5, float(depth))
    a = math.radians(angle)
    dx, dy = math.cos(a) * d * 2.0, math.sin(a) * d * 2.0
    shifted = ImageChops.offset(img, int(round(dx)), int(round(dy)))
    hi = ImageChops.subtract(shifted, img).convert("RGB")
    lo = ImageChops.subtract(img, shifted).convert("RGB")
    out = ImageChops.add(img, ImageChops.multiply(hi, Image.new("RGB", img.size, (90, 90, 90))))
    out = ImageChops.subtract(out, ImageChops.multiply(lo, Image.new("RGB", img.size, (70, 70, 70))))
    # 只在作用区域内生效
    return Image.composite(out, img, mask)


def apply_rarity(canvas: Image.Image, rarity: str, frame_obj: G.Frame, *,
                 pendulum: bool = False, palette: Optional[Palette] = None,
                 seed: int = 7, emboss_texture: Image.Image | None = None,
                 assets=None) -> Image.Image:
    """在 ``canvas`` 上叠加某罕贵的效果，返回新图（不修改入参）。

    ``canvas`` 必须是 RGB 或 RGBA，尺寸与 ``frame_obj`` 一致。
    """
    d = by_key(rarity)
    if not d.layers and not d.frame_edge_fx and (not d.name_fx or d.name_fx.style == "none"):
        return canvas

    base = canvas.convert("RGB")
    size = base.size

    for layer in d.layers:
        if not isinstance(layer, Foil):
            continue
        mask = region_mask(layer.region, frame_obj, pendulum=pendulum, feather=layer.feather)
        if layer.opacity <= 0:
            continue

        tex = None
        if layer.asset and assets is not None:
            try:
                a = assets.rarity_layer(layer.asset)
                if a is not None:
                    tex = a.convert("RGBA").resize(size, Image.LANCZOS)
            except Exception:
                tex = None
        if tex is None:
            tex = pattern_texture(layer.pattern, size, angle=layer.angle,
                                 scale=layer.scale, seed=seed, tint=layer.tint)
        else:
            tex = tex.convert("RGB")

        blended = _blend(base, tex, layer.blend)
        m = mask.point(lambda v: int(v * max(0.0, min(1.0, layer.opacity))))
        base = Image.composite(blended, base, m)

    # 浮雕层
    for layer in d.layers:
        if isinstance(layer, Emboss):
            mask = region_mask(layer.region, frame_obj, pendulum=pendulum, feather=2.0)
            src = emboss_texture.convert("RGB") if emboss_texture is not None else base
            base = _emboss(src, mask, layer.depth, layer.angle)

    # 卡框边框镀色
    if d.frame_edge_fx:
        edge = region_mask("frame_edge", frame_obj, pendulum=pendulum, feather=0.8)
        tex = pattern_texture(d.frame_edge_fx, size, angle=0.0, scale=1.0, seed=seed)
        base = Image.composite(_blend(base, tex, "soft_light"), base,
                               edge.point(lambda v: int(v * 0.72)))

    return base


def name_effect(rarity: str) -> Optional[NameFx]:
    """取该罕贵的卡名箔定义（供文字层调用）。"""
    return by_key(rarity).name_fx


def is_full_art_marker(rarity: str) -> bool:
    return rarity == "full_art"


def capabilities() -> dict:
    return {
        "numpy": HAS_NUMPY,
        "rarities": len(RARITY_DEFS),
        "patterns": len(PATTERNS) - 1,
        "official_patterns": len(set(OFFICIAL_FOIL_PATTERNS)),
        "blends": BLEND_MODES,
    }
