# -*- coding: utf-8 -*-
"""卡图窗的**斜切框 + 过渡** —— 官方印刷卡上那圈"钢色内斜面"。

为什么单独一个模块
------------------
我们用的卡框素材（``kooriookami/yugioh-card``，MIT）在插画窗边缘是**硬边**：
框色一路顶到窗沿，窗内直接是纯白占位。而官方扫描实测，窗沿从外到里其实是
五层结构。少了这五层，卡面看着就是"贴图"，不是"卡"。

官方实测（813×1185 坐标系，来源：Karvp/ygocards 的官方卡扫描逐像素剖面，
普通 / 效果 / 魔法三种框结构一致）：

    框色 ──暗部渐变──▶ 暗线 ─▶ 钢色带 ─▶ 亮发丝 ─▶ 画面
     ~18px            2px    9.4px     2px

    #c29a52(框色) → #594c43(暗线) → #6c6e7a…#727989(钢带) → #8a909e(发丝) → 画面

斜切面的明暗方向：顶边与左边亮、底边与右边暗（光源在左上），四角 45° 斜接。
钢带是**低饱和蓝灰**，跨卡框基本不变色 —— 所以这里用固定色 + 极轻的框色染色，
而不是跟着卡框配色走（跟色会让橙色效果框出现脏边）。

哪些档位画
----------
只在**插画被卡图窗完整包住**时画（``fullart.mode == "none"``）。出框 / 全画 /
主体出框时官方卡的做法是"画面破坏窗边界"，那圈线不会横跨画面，硬画会穿帮。
"""
from __future__ import annotations

from typing import Optional

from ..core.models import CardSpec
from . import geometry as G
from .palettes import Palette, lerp

__all__ = ["BEZEL", "bezel_metrics", "draw_art_bezel", "svg_bezel", "capabilities"]

#: 官方实测的几何与颜色（REF 系 = 813 宽）
BEZEL = {
    "band": 9.4,          # 钢色带宽度（占卡宽约 1.15%）
    "dark_line": 2.0,     # 窗沿暗线
    "hairline": 3.0,      # 带内侧的亮发丝线
    "outer_shade": 24.0,  # 框色向窗沿压暗的渐变宽度
    "inner_vignette": 6.0,  # 画面最外圈被压暗的宽度（官方带内缘的过渡）
    "steel_outer": (108, 110, 122),   # #6c6e7a  钢带外缘（靠暗线一侧）
    "steel_inner": (114, 121, 137),   # #727989  钢带内缘（靠画面一侧）
    "dark": (52, 47, 45),             # #34302d  窗沿暗线（#594c43 压暗取中性）
    "hair": (138, 144, 158),          # #8a909e  亮发丝（官方扫描实测色）
    "tint": 0.10,                     # 钢带向框色染的比例（避免深框上发飘）
    # 斜切面的明暗：官方扫描实测顶/左 L≈96–113、底/右 L≈65，
    # 带的**内外渐变**本身就承担高光，所以亮面几乎不再额外提亮。
    "bevel_light": 1.02,              # 顶/左 提亮
    "bevel_dark": 0.62,               # 底/右 压暗
    "shade_curve": 0.85,              # 暗部渐变曲线（<1 = 更早开始变暗，铺得更宽）
}


def bezel_metrics(frame_obj: G.Frame, strength: float = 1.0) -> dict:
    """把 REF 系的实测值换算到目标画布（像素整数），供绘制与自测共用。"""
    s = max(0.0, min(2.0, float(strength)))
    px = lambda v: max(0, int(round(frame_obj.px(v, "x") * s)))
    return {
        "band": px(BEZEL["band"]),
        "dark_line": px(BEZEL["dark_line"]),
        "hairline": px(BEZEL["hairline"]),
        "outer_shade": px(BEZEL["outer_shade"]),
        "inner_vignette": px(BEZEL["inner_vignette"]),
    }


def svg_bezel(rect, band: float, *, scale: float = 1.0, pal=None) -> str:
    """矢量版（浏览器端预览通道用）：四条 45° 斜接边 + 暗线 + 发丝。

    渐变在 SVG 里用四条独立多边形的实色近似 —— 矢量通道本来就是"降级预览"，
    不追求像素级一致，但**结构必须一致**：顶/左亮、底/右暗、四角斜接。
    """
    x, y, w, h = [float(v) for v in rect]
    b = max(1.0, float(band) * max(0.2, scale))
    out_c, in_c = BEZEL["steel_outer"], BEZEL["steel_inner"]
    if pal is not None and BEZEL["tint"] > 0:
        fb = getattr(pal, "frame_bg", (128, 128, 128))
        out_c = lerp(out_c, fb, BEZEL["tint"])
        in_c = lerp(in_c, fb, BEZEL["tint"])

    def hx(c, mul=1.0):
        return "#%02X%02X%02X" % tuple(min(255, max(0, int(round(v * mul)))) for v in c)

    hi_o, hi_i = hx(out_c, BEZEL["bevel_light"]), hx(in_c, BEZEL["bevel_light"])
    dk_o, dk_i = hx(out_c, BEZEL["bevel_dark"]), hx(in_c, BEZEL["bevel_dark"])
    x2, y2 = x + w, y + h
    polys = [
        # 顶 / 左：亮面
        (f"{x},{y} {x2},{y} {x2-b},{y+b} {x+b},{y+b}", hi_o),
        (f"{x},{y} {x+b},{y+b} {x+b},{y2-b} {x},{y2}", hi_o),
        # 底 / 右：暗面
        (f"{x},{y2} {x+b},{y2-b} {x2-b},{y2-b} {x2},{y2}", dk_o),
        (f"{x2},{y} {x2},{y2} {x2-b},{y2-b} {x2-b},{y+b}", dk_o),
    ]
    parts = [f'<polygon points="{p}" fill="{c}"/>' for p, c in polys]
    parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
                 f'fill="none" stroke="{hx(BEZEL["dark"])}" stroke-width="{b * 0.22:.2f}"/>')
    parts.append(f'<rect x="{x + b:.1f}" y="{y + b:.1f}" width="{max(1, w - 2 * b):.1f}" '
                 f'height="{max(1, h - 2 * b):.1f}" fill="none" stroke="{hx(BEZEL["hair"])}" '
                 f'stroke-width="{b * 0.2:.2f}"/>')
    return "".join(parts)


def capabilities() -> dict:
    """给界面/文档看：这层框的数值来源与当前值。"""
    return {"source": "官方卡扫描逐像素剖面（普通/效果/魔法三框一致）",
            "ref_space": list(G.REF), "values": dict(BEZEL),
            "modes": ("none",), "note": "出框类档位不画这层（官方由画面破坏窗边界）"}


def _side_gradient(d, rect, side: str, band: int, c_out, c_in) -> None:
    """画一条边的斜切带：沿 45° 斜接逐圈插值，天然形成斜角与内外渐变。"""
    x, y, w, h = rect
    for t in range(band):
        k = t / max(1, band - 1)
        col = lerp(c_out, c_in, k)
        if side == "top":
            d.line([(x + t, y + t), (x + w - 1 - t, y + t)], fill=col, width=1)
        elif side == "bottom":
            yy = y + h - 1 - t
            d.line([(x + t, yy), (x + w - 1 - t, yy)], fill=col, width=1)
        elif side == "left":
            d.line([(x + t, y + t), (x + t, y + h - 1 - t)], fill=col, width=1)
        else:
            xx = x + w - 1 - t
            d.line([(xx, y + t), (xx, y + h - 1 - t)], fill=col, width=1)


def _ring(d, rect, width: int, color, from_outside: bool = True) -> None:
    """沿矩形画一圈等宽线（``from_outside`` 决定往框侧长还是往画侧长）。"""
    x, y, w, h = rect
    for i in range(max(1, width)):
        o = i if from_outside else -i
        d.rectangle([x - o, y - o, x + w - 1 + o, y + h - 1 + o], outline=color)


def _shade_outside(d, rect, width: int, alpha_max: int) -> None:
    """框色向窗沿的暗部渐变：**越靠窗越暗**（官方剖面就是这个方向）。"""
    x, y, w, h = rect
    for i in range(max(1, width)):
        o = width - i                                  # o = 离窗沿的距离
        k = i / max(1, width - 1)                      # 越靠近窗 → k 越大 → 越暗
        a = int(round(alpha_max * (k ** BEZEL["shade_curve"])))
        if a <= 0:
            continue
        d.rectangle([x - o, y - o, x + w - 1 + o, y + h - 1 + o], outline=(0, 0, 0, a))


def draw_art_bezel(canvas, frame_obj: G.Frame, spec: Optional[CardSpec] = None,
                   *, pal: Optional[Palette] = None, strength: float = 1.0,
                   rect: Optional[tuple] = None) -> dict:
    """在 ``canvas``（RGBA）上画卡图窗斜切框。就地修改，返回用量报告。

    :param pal: 传入卡框调色板时，钢带会向其轻微染色（见 ``BEZEL["tint"]``）。
    :param rect: 覆盖默认窗矩形（灵摆卡要传合并窗）。
    :return: ``{"drawn", "band", "rect", "note"}``
    """
    from PIL import Image, ImageDraw

    s = float(strength)
    if s <= 0:
        return {"drawn": False, "band": 0, "note": "strength=0 → 不画"}

    if rect is None:
        key = G.PENDULUM_ART_KEY if (spec is not None and spec.is_pendulum) \
            else G.STANDARD_ART_KEY
        rect = frame_obj.rect(key)
    x, y, w, h = [int(round(v)) for v in rect]
    m = bezel_metrics(frame_obj, s)
    band = m["band"]
    if band <= 0 or w <= band * 4 or h <= band * 4:
        return {"drawn": False, "band": band, "note": "窗过小或换算后带宽为 0 → 不画"}

    # 钢带基色 + 极轻框色染色
    base_out, base_in = BEZEL["steel_outer"], BEZEL["steel_inner"]
    if pal is not None and BEZEL["tint"] > 0:
        tint = BEZEL["tint"]
        fb = getattr(pal, "frame_bg", (128, 128, 128))
        base_out = lerp(base_out, fb, tint)
        base_in = lerp(base_in, fb, tint)

    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)

    # 1) 框侧暗部渐变（压在卡框上，越靠窗越暗）
    _shade_outside(d, (x, y, w, h), m["outer_shade"], 96)
    # 2) 窗沿暗线
    _ring(d, (x, y, w, h), m["dark_line"], (*BEZEL["dark"], 255), from_outside=False)
    # 3) 四条斜切边：顶/左提亮，底/右压暗（光源在左上）。
    #    四条边都以**窗矩形**为基准向内画，画到 inner 为止 —— 用 inner 当基准
    #    会只盖住带的内半，外半露出画面（实测踩过）。
    hi_o = tuple(min(255, int(c * BEZEL["bevel_light"])) for c in base_out)
    hi_i = tuple(min(255, int(c * BEZEL["bevel_light"])) for c in base_in)
    dk_o = tuple(int(c * BEZEL["bevel_dark"]) for c in base_out)
    dk_i = tuple(int(c * BEZEL["bevel_dark"]) for c in base_in)
    inner = (x + band, y + band, w - 2 * band, h - 2 * band)
    _side_gradient(d, (x, y, w, h), "top", band, hi_o, hi_i)
    _side_gradient(d, (x, y, w, h), "left", band, hi_o, hi_i)
    _side_gradient(d, (x, y, w, h), "bottom", band, dk_o, dk_i)
    _side_gradient(d, (x, y, w, h), "right", band, dk_o, dk_i)
    # 4) 画面最外圈轻微压暗（带与画面的过渡）→ 再压上带内侧的亮发丝，
    #    发丝必须**最后画**且长在带的一侧，否则会被压暗吃掉（实测踩过）。
    vig = m["inner_vignette"]
    ix, iy, iw, ih = inner
    for i in range(max(1, vig)):
        k = 1.0 - i / max(1, vig - 1)                  # 越靠带边越暗，往画面里淡出
        a = int(round(46 * (k ** 1.3)))
        if a > 0:
            d.rectangle([ix + i, iy + i, ix + iw - 1 - i, iy + ih - 1 - i],
                        outline=(0, 0, 0, a))
    _ring(d, inner, m["hairline"], (*BEZEL["hair"], 255), from_outside=True)

    canvas.alpha_composite(overlay)
    return {"drawn": True, "band": band, "rect": (x, y, w, h),
            "metrics": m, "note": "官方实测五层：暗部渐变/暗线/钢带/发丝/内圈压暗"}
