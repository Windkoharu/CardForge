"""卡框版面实测 —— 运行时从卡框素材反推可用区域，取代"一套 GEO 套所有框"。

为什么需要
----------
15 种官方卡框的「类型行条带 / 文本框面板」起始位置**各不相同**（实测标准框装饰边线在
REF y≈878、米色面板内区从 ≈907 开始，而灵摆框整个中段是纯白空窗）。用单一
``GEO`` 数值去适配所有框必然错位 —— 旧版就是这样把类型行画进了文本框里，造成 44px 重影。

做法
----
对卡框图做**行剖面分析**：
1. 找「近白窗」→ 插画窗上下边界（标准框）或整块空窗（灵摆框）。
2. 在插画窗下方找「米色面板」的连续行区间 → 文本框面板。
3. 面板上沿到插画窗下沿之间就是**类型行条带**。
结果按 ``(frame_key, 素材指纹)`` 缓存，框体换素材会自动失效。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from PIL import Image

from . import geometry as G

try:
    import numpy as _np
except Exception:  # pragma: no cover
    _np = None

#: 探测结果默认值（探测失败时回退到 GEO）
FALLBACK = {
    "art": G.GEO[G.STANDARD_ART_KEY],
    "panel": G.GEO["text_panel"],
    "type_line": (63.5, 840.0, 680.0, 34.0),
    "panel_top": 889.0,
    "art_bottom": 832.6,
}

_CACHE: dict[tuple, dict] = {}


@dataclass
class FrameLayout:
    """一张卡框实测出的版面（REF 坐标系）。"""
    key: str = ""
    art: tuple = FALLBACK["art"]
    panel: tuple = FALLBACK["panel"]
    type_line: tuple = FALLBACK["type_line"]
    art_bottom: float = FALLBACK["art_bottom"]
    panel_top: float = FALLBACK["panel_top"]
    blank_window: bool = False        # 灵摆框：中段整块空白，内区全靠渲染器绘制
    measured: bool = False
    warnings: list = field(default_factory=list)
    #: 供 ``geometry.Frame`` 直接覆盖同名区域（鸭子类型，避免循环 import）
    rects: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "key": self.key, "art": [round(v, 1) for v in self.art],
            "panel": [round(v, 1) for v in self.panel],
            "type_line": [round(v, 1) for v in self.type_line],
            "art_bottom": round(self.art_bottom, 1),
            "panel_top": round(self.panel_top, 1),
            "blank_window": self.blank_window, "measured": self.measured,
            "rects": {k: [round(x, 1) for x in v] for k, v in self.rects.items()},
            "warnings": self.warnings,
        }


def _runs(mask, thr: float = 0.5, min_len: int = 6) -> list[tuple[int, int]]:
    out, start = [], None
    for i, v in enumerate(mask):
        if v >= thr and start is None:
            start = i
        elif v < thr and start is not None:
            if i - start >= min_len:
                out.append((start, i - 1))
            start = None
    if start is not None and len(mask) - start >= min_len:
        out.append((start, len(mask) - 1))
    return out


def analyze(img: Image.Image, key: str = "", *, force: bool = False) -> FrameLayout:
    """从卡框图反推版面。失败时返回带默认值的 :class:`FrameLayout`（``measured=False``）。"""
    if _np is None:
        return FrameLayout(key=key, warnings=["numpy 不可用，无法实测卡框版面"])

    im = img.convert("RGB")
    if im.size != G.FRAME_NATIVE:
        im = im.resize(G.FRAME_NATIVE, Image.LANCZOS)
    ck = (key, im.size, _quick_hash(im))
    if not force and ck in _CACHE:
        return _CACHE[ck]

    lay = FrameLayout(key=key)
    a = _np.asarray(im).astype(_np.int16)
    h, w, _ = a.shape
    ky = G.REF[1] / h
    kx = G.REF[0] / w

    mn = a.min(axis=2)
    mx = a.max(axis=2)
    sat = mx - mn
    white = (mn > 225) & (sat < 18)
    white_frac = white.mean(axis=1)

    # ── 1. 插画窗下沿：找「起点落在卡名条下方、且足够高」的最长白色行区间 ──
    #    注意：同调框自身是白色（框体全白），所以**不能**用"最长白区"直接当插画窗；
    #    改为要求起点落在 REF y 150–330（卡名条下沿附近）且高度 ≥ 400 REF。
    def _ref_y(row: int) -> float:
        return row * ky

    cands = []
    for s, e in _runs(white_frac, 0.5, 60):
        ys, ye = _ref_y(s), _ref_y(e)
        if not (140.0 <= ys <= 340.0):
            continue
        h_ref = ye - ys
        # 合理性：标准框插画窗 ≈ 613 REF；灵摆空窗 ≈ 900 REF。
        # 同调框自身是白色，会把白区往上扩（实测误判到 672），这里用高度区间挡掉。
        if not (560.0 <= h_ref <= 660.0) and not (850.0 <= h_ref <= 950.0):
            continue
        cands.append((s, e, ys, ye))
    if cands:
        s, e, ys, ye = max(cands, key=lambda t: t[3] - t[2])
        lay.art_bottom = round(ye, 1)
        lay.blank_window = (ye - ys) > G.REF[1] * 0.62
        # 插画窗左右：只取该区间**中间 40% 行**的列剖面，避免被框体边缘污染
        mid0 = s + int((e - s) * 0.30)
        mid1 = s + int((e - s) * 0.70)
        cols = white[mid0:mid1 + 1].mean(axis=0)
        cruns = _runs(cols, 0.7, 40)
        if cruns:
            cs, ce = max(cruns, key=lambda t: t[1] - t[0])
            lay.art = (round(cs * kx, 1), round(ys, 1),
                       round((ce - cs) * kx, 1), round(ye - ys, 1))
    else:
        lay.warnings.append("未找到插画窗，沿用 GEO 默认值")

    # ── 2. 米色面板：白色区下方「亮但不白」的连续行 ──
    beige = (mn > 140) & (mn <= 252) & (sat < 60)
    center = beige[:, int(w * 0.22):int(w * 0.78)]
    bfrac = center.mean(axis=1)
    # 把插画窗以上的行强制置为非面板，避免同调框那种「框体本身也是浅色」导致
    # 面板区间从行 0 就开始、被 start_row 过滤后整段丢失。
    start_row = int(round(lay.art_bottom / ky)) if lay.art_bottom else 0
    bfrac = bfrac.copy()
    bfrac[:max(0, start_row)] = 0.0
    bruns = [(s, e) for (s, e) in _runs(bfrac, 0.80, 20) if (e - s) * ky >= 150.0]
    if not lay.blank_window and bruns:
        s, e = max(bruns, key=lambda t: t[1] - t[0])
        colf = beige[s:e + 1].mean(axis=0)
        cruns = [(a, b) for (a, b) in _runs(colf, 0.80, 20)
                 if (b - a) * kx >= 500.0]      # 面板宽度合理性
        if cruns:
            cs, ce = max(cruns, key=lambda t: t[1] - t[0])
            lay.panel_top = round(s * ky, 1)
            lay.panel = (round(cs * kx, 1), lay.panel_top,
                         round((ce - cs) * kx, 1), round((e - s) * ky, 1))
            lay.measured = True
        else:
            lay.warnings.append("面板宽度不合理，回退到 GEO 默认值")
    elif lay.blank_window:
        # 灵摆框：中段是整块空窗，面板与类型行全部由渲染器自行绘制
        lay.panel = G.GEO["pendulum_monster_panel"]
        lay.panel_top = G.GEO["pendulum_panel"][1]
        lay.measured = True
        lay.warnings.append("灵摆框为空窗设计，面板与类型行由渲染器自行绘制")
    else:
        lay.warnings.append("未能实测到文本框面板，回退到 GEO 默认值")

    # ── 3. 类型行条带 = 插画窗下沿 ~ 面板上沿 ──
    band_top = lay.art_bottom
    band_bot = lay.panel_top
    if band_bot - band_top >= 16:
        bh = min(34.0, (band_bot - band_top) - 8)
        lay.type_line = (63.5, round(band_top + (band_bot - band_top - bh) * 0.42, 1),
                         680.0, round(bh, 1))
    else:
        lay.type_line = (63.5, round(max(8.0, band_bot - 46), 1), 680.0, 30.0)
        lay.warnings.append("类型行条带过窄，已改用面板上沿推算")

    # ── 4. 产出覆盖表：交给 geometry.Frame 直接用实测值 ──
    lay.rects = {
        "type_line": lay.type_line,
        "pendulum_type_line": (lay.type_line[0], lay.type_line[1], 660.0,
                               lay.type_line[3]),
    }
    if not lay.blank_window and lay.measured:
        # 面板内区 = 实测外框内缩一个金边宽度（实测约 9 REF px）
        px_, py_, pw, ph = lay.panel
        inset = 9.0
        lay.rects["text_panel"] = (px_ + inset, py_ + inset,
                                   pw - inset * 2, ph - inset * 2)
        lay.rects["text_box"] = (px_ + inset + 8.0, py_ + inset + 8.0,
                                 pw - inset * 2 - 16.0, ph - inset * 2 - 40.0)
        lay.rects["text_box_st"] = (px_ + inset + 8.0, py_ + inset + 10.0,
                                    pw - inset * 2 - 16.0, ph - inset * 2 - 42.0)

    _CACHE[ck] = lay
    return lay


def _quick_hash(im: Image.Image) -> int:
    """8×8 灰度均值哈希，用于缓存失效判定（比整图哈希快几个数量级）。"""
    t = im.convert("L").resize((8, 8), Image.BILINEAR)
    return hash(t.tobytes())


def clear_cache() -> None:
    _CACHE.clear()


def layout_for(frame_key: str, assets=None, pendulum: bool = False,
               base: str = "") -> FrameLayout:
    """取某卡种卡框的实测版面（带缓存）。取不到素材时返回默认值。"""
    if assets is None:
        return FrameLayout(key=frame_key, warnings=["无素材库，使用默认版面"])
    try:
        img = assets.frame(base or frame_key, pendulum=pendulum)
    except Exception as e:
        return FrameLayout(key=frame_key, warnings=[f"卡框读取失败：{e}"])
    if img is None:
        return FrameLayout(key=frame_key, warnings=["未找到该卡框素材，使用默认版面"])
    ck = f"{frame_key}{'-pend' if pendulum else ''}"
    return analyze(img, ck)


def diagnose_all(assets=None) -> list[dict]:
    """对全部卡框跑一遍实测，返回汇总（doctor / 自检用）。"""
    if assets is None:
        from . import assets as A
        assets = A.library()
    out = []
    for base in ("normal", "effect", "ritual", "fusion", "synchro", "xyz", "link",
                 "spell", "trap", "token"):
        for pend in (False, True):
            lay = layout_for(base, assets, pendulum=pend, base=base)
            if not lay.measured and not lay.warnings:
                continue
            d = lay.to_dict()
            d["pendulum"] = pend
            out.append(d)
    return out
