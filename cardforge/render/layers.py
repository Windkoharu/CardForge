"""内容图层绘制器 —— 卡面三段式管线里的「第 ② 段」。

每个 ``draw_*`` 函数只做一件事，接收已有画布并就地绘制（返回绘制后的画布）。
全部坐标走 :mod:`cardforge.render.geometry`，墨色走 :mod:`cardforge.render.palettes`，
素材走 :class:`cardforge.render.assets.AssetLibrary`（缺失时自动改用程序化绘制）。

这样拆分的目的：旧版把这些全塞在一个 52KB 文件里，改一处就牵动全局；
现在每个部位独立可测、可替换、可单独预览。
"""
from __future__ import annotations

import math
from typing import Callable, Optional

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from ..core import constants as C
from ..core.enums import FRAMES, MONSTER_TAGS, SPELL_KINDS, TRAP_KINDS, label_of
from ..core.models import CardSpec
from . import geometry as G
from . import text as T
from .palettes import Palette, darken, lighten, name_is_white

FontOf = Callable[[int], Optional[ImageFont.FreeTypeFont]]

#: 行距相对字号的最小比例。官方卡文约 1.16；模板自带的 0.98–1.02 会让 CJK 行间压字。
MIN_LINE_RATIO = 1.16
#: 段间距（相对行距）。官方样张的 ①②③ 是连续行、不额外加空；留 0.12 只为
#: 让段落切换有一点点呼吸感，不能再按旧版的 0.28 撑开。
PARA_GAP = 0.12


# ══════════════════════════════════════════════════════════════════════
#  小工具
# ══════════════════════════════════════════════════════════════════════
def _rgba(img: Optional[Image.Image]) -> Optional[Image.Image]:
    return img.convert("RGBA") if img is not None else None


def paste_center(canvas: Image.Image, im: Optional[Image.Image],
                 cx: float, cy: float, size: Optional[float] = None) -> None:
    """把素材按中心点贴上，``size`` 给定时等比缩放到该尺寸（正方形边长）。"""
    if im is None:
        return
    im = _rgba(im)
    if size:
        im = im.resize((max(1, int(size)), max(1, int(size))), Image.LANCZOS)
    canvas.alpha_composite(im, (int(round(cx - im.width / 2)),
                                int(round(cy - im.height / 2))))


def _measure(draw: ImageDraw.ImageDraw, txt: str, font: ImageFont.FreeTypeFont) -> float:
    try:
        return draw.textlength(txt, font=font)
    except Exception:
        return font.size * len(txt) * 0.6


def text_with_outline(draw: ImageDraw.ImageDraw, xy, txt: str, font, fill,
                      outline=None, width: float = 2.0, anchor: str = "lm",
                      spacing: int = 0) -> None:
    """带描边的文字（出框/超框时保证卡名可读）。"""
    if outline and width > 0:
        w = max(1, int(round(width)))
        x, y = xy
        for dx in (-w, 0, w):
            for dy in (-w, 0, w):
                if dx or dy:
                    draw.text((x + dx, y + dy), txt, font=font, fill=outline,
                              anchor=anchor, spacing=spacing)
    draw.text(xy, txt, font=font, fill=fill, anchor=anchor, spacing=spacing)


def _fit_to_width(draw, txt: str, font_of: FontOf, max_w: float, base_size: float,
                  min_size: float, squeeze_attr: str = "squeeze_x") -> tuple:
    """把单行文字压到 ``max_w`` 内：先降字号，再横压。返回 (font, squeeze)。"""
    size = int(round(base_size))
    while size > min_size:
        f = font_of(size)
        if f is None:
            return None, 1.0
        if _measure(draw, txt, f) <= max_w:
            return f, 1.0
        size -= 1
    f = font_of(int(min_size))
    if f is None:
        return None, 1.0
    w = _measure(draw, txt, f)
    squeeze = max(0.70, min(1.0, max_w / w)) if w > 0 else 1.0
    return f, squeeze


# ══════════════════════════════════════════════════════════════════════
#  卡名
# ══════════════════════════════════════════════════════════════════════
def draw_name(canvas: Image.Image, spec: CardSpec, f: G.Frame, font_of: FontOf,
              pal: Palette, *, assets=None, name_fx=None, stroke: float = 0.0,
              lang: Optional[str] = None,
              fill: Optional[tuple] = None) -> None:
    """卡名条。支持卡名箔（金/银/钻石切/虹/红）与描边（超框时用）。

    ``fill`` 是官方超框的兜底填充：无箔罕贵（平卡）时用白字 + 深描边，
    保证卡名压在插画上仍然可读；有箔罕贵仍走 ``name_fx`` 的金属渐变。
    """
    lang = lang or spec.render.lang_name
    txt = spec.name_in(lang)
    if not txt:
        return
    d = ImageDraw.Draw(canvas)
    x, y, w, h = f.rect("title_bevel")
    # 右侧给属性徽记留位
    pad_l = f.px(14)
    pad_r = f.px(96)
    max_w = max(20.0, w - pad_l - pad_r)

    base_size = f.font(G.FONT_SIZE["name"])
    font, squeeze = _fit_to_width(d, txt, font_of, max_w, base_size,
                                 base_size * 0.45)
    if font is None:
        return

    ink = pal.name_ink
    style = (name_fx.style if name_fx else "none") or "none"
    if style == "none":
        ink = (255, 255, 255) if name_is_white(spec.frame) else pal.name_ink
    elif style in ("gold", "diamond"):
        ink = (255, 236, 168) if style == "gold" else (238, 244, 255)
    elif style == "silver":
        ink = (232, 238, 248)
    elif style == "rainbow":
        ink = (255, 250, 235)
    elif style == "red":
        ink = (255, 176, 176)
    elif style == "green":
        ink = (186, 246, 196)
    elif style == "blue":
        ink = (172, 214, 255)

    cy = y + h / 2.0
    if style != "none" and name_fx is not None:
        # 先渲到独立图层拿到**精确的文字 alpha 遮罩**，再用它裁切金属渐变。
        # 旧做法是"与高斯模糊背景求差"反推遮罩 —— 会把卡名条的纹理也算进去，
        # 结果文字边缘出现彩色毛边。分层渲染是唯一干净的做法。
        _draw_name_with_foil(canvas, txt, font, (x + pad_l, cy), max_w, squeeze,
                             style, getattr(name_fx, "opacity", 0.9),
                             pal, stroke)
        return

    if fill is not None:
        ink = fill
    else:
        ink = (255, 255, 255) if name_is_white(spec.frame) else pal.name_ink
    if squeeze < 0.999:
        _draw_squeezed(d, canvas, txt, font, (x + pad_l, cy), max_w, squeeze,
                       ink, pal.name_outline if stroke > 0 else None, stroke)
    else:
        text_with_outline(d, (x + pad_l, cy), txt, font, ink,
                          pal.name_outline if stroke > 0 else None, stroke, "lm")


def _draw_name_with_foil(canvas: Image.Image, txt: str, font, xy, max_w: float,
                         squeeze: float, style: str, opacity: float,
                         pal: Palette, stroke: float) -> None:
    """卡名金属箔：文本 → alpha 遮罩 → 金属渐变 → 合成。"""
    x0, cy = xy
    # 1) 把文字画到透明层（白色），得到精确遮罩
    pad = max(6, int(font.size * 0.6))
    tw = int((max_w / max(0.05, squeeze)) + pad * 2)
    th = int(font.size * 2.0) + pad * 2
    layer = Image.new("L", (max(2, tw), max(2, th)), 0)
    ld = ImageDraw.Draw(layer)
    ld.text((pad, th / 2), txt, font=font, fill=255, anchor="lm")

    if stroke > 0:
        # 2) 超框/全画时加描边：先把遮罩膨胀一圈作为描边层
        grow = max(1, int(round(stroke)))
        edge = layer.filter(ImageFilter.MaxFilter(min(9, grow * 2 + 1)))
    else:
        edge = None

    if squeeze < 0.999:
        nw = max(1, int(layer.width * squeeze))
        layer = layer.resize((nw, th), Image.LANCZOS)
        if edge is not None:
            edge = edge.resize((nw, th), Image.LANCZOS)

    # 3) 金属渐变（斜向条纹，模拟烫箔反光）
    stops = _NAME_FOIL_GRAD.get(style) or _NAME_FOIL_GRAD["silver"]
    grad = Image.new("RGB", layer.size, stops[0])
    gd = ImageDraw.Draw(grad)
    band = max(3.0, layer.height * 0.26)
    yy, i = -layer.height, 0
    while yy < layer.height * 2:
        gd.polygon([(0, yy), (layer.width, yy + band),
                    (layer.width, yy + band * 2), (0, yy + band)], fill=stops[i % len(stops)])
        yy += band * 2
        i += 1
    foil = grad.convert("RGBA")
    alpha = layer.point(lambda v: int(v * max(0.0, min(1.0, opacity))))
    foil.putalpha(alpha)

    px = int(round(x0)) - pad
    py = int(round(cy)) - th // 2
    if edge is not None:
        oc = Image.new("RGBA", layer.size, pal.name_outline + (0,))
        oc.putalpha(edge.point(lambda v: int(v * 0.92)))
        canvas.alpha_composite(oc, (px, py))
    canvas.alpha_composite(foil, (px, py))


def _draw_squeezed(d, canvas, txt, font, xy, max_w, squeeze, fill, outline, stroke):
    """横向压缩绘制单行文字（Pillow 无直接字距缩放，先画后缩）。"""
    tmp = Image.new("RGBA", (int(max_w / squeeze) + 8, int(font.size * 1.8) + 8),
                    (0, 0, 0, 0))
    td = ImageDraw.Draw(tmp)
    td.text((2, tmp.height / 2), txt, font=font, fill=fill, anchor="lm")
    if outline and stroke > 0:
        td.text((2, tmp.height / 2), txt, font=font, fill=fill, anchor="lm")
    tmp = tmp.resize((max(1, int(tmp.width * squeeze)), tmp.height), Image.LANCZOS)
    canvas.alpha_composite(tmp, (int(xy[0]), int(xy[1] - tmp.height / 2)))


_NAME_FOIL_GRAD: dict[str, list] = {
    "gold": [(196, 148, 44), (255, 246, 200), (168, 126, 36), (255, 232, 150)],
    "diamond": [(150, 168, 200), (255, 255, 255), (176, 190, 220), (240, 248, 255)],
    "silver": [(178, 186, 200), (255, 255, 255), (196, 204, 216)],
    "rainbow": [(255, 120, 120), (255, 232, 130), (140, 255, 180),
                (130, 210, 255), (200, 150, 255)],
    "red": [(196, 40, 52), (255, 190, 190), (168, 28, 40)],
    "green": [(60, 168, 96), (200, 255, 210), (40, 140, 80)],
    "blue": [(48, 118, 200), (196, 226, 255), (36, 96, 176)],
}


# ══════════════════════════════════════════════════════════════════════
#  属性 / 星级 / 阶级 / 连接箭头
# ══════════════════════════════════════════════════════════════════════
#: 魔法 / 陷阱 用官方「魔」「罠」圆标，其余按属性取
_ATTR_BY_FRAME = {"spell": "魔", "trap": "罠"}


def draw_badge(canvas: Image.Image, spec: CardSpec, f: G.Frame, *, assets=None) -> None:
    """右上角属性圆标（魔法/陷阱用「魔」「罠」圆标）。"""
    key = _ATTR_BY_FRAME.get(spec.frame, spec.attribute)
    im = None
    if assets is not None:
        try:
            im = assets.attribute(key)
        except Exception:
            im = None
    x, y, w, h = f.rect("badge")
    if im is None:
        d = ImageDraw.Draw(canvas, "RGBA")
        r = min(w, h) / 2
        cx, cy = x + w / 2, y + h / 2
        col = {"光": (255, 236, 140), "暗": (128, 96, 190), "地": (176, 132, 72),
               "水": (96, 168, 232), "炎": (232, 104, 64), "风": (120, 208, 152),
               "神": (240, 200, 96), "魔": (72, 176, 148), "罠": (200, 88, 136)}.get(
                   key, (170, 170, 170))
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col + (236,),
                  outline=darken(col, 0.45) + (255,), width=max(1, int(f.px(2))))
        fnt = None
        return
    paste_center(canvas, im, x + w / 2, y + h / 2, min(w, h))


def draw_stars(canvas: Image.Image, spec: CardSpec, f: G.Frame, font_of: FontOf,
               pal: Palette, *, assets=None) -> None:
    """等级星（右对齐，红金）／阶级星（左对齐，黑）。灵摆卡另有刻度数字。"""
    fd = spec.frame_def
    if not fd.has_level:
        return
    n = spec.effective_level
    if n <= 0:
        return
    is_rank = fd.level_is_rank
    key = "rank_star" if is_rank else "level_star"
    x, y, sw, sh = f.rect(key)
    gap = f.px(1.0)

    # 星太多时缩小（官方的 12 星会改居中并缩小间距）
    max_n = 8
    scale = 1.0
    if n > max_n:
        avail = (f.rect("title_bevel")[2])
        need = n * (sw + gap)
        scale = max(0.55, avail / need) if need > 0 else 1.0
    sw2, sh2 = sw * scale, sh * scale
    gap = gap * scale

    star = None
    if assets is not None:
        try:
            star = assets.star("rank" if is_rank else "level")
        except Exception:
            star = None

    for i in range(n):
        if is_rank:
            cx = x + sw2 / 2 + i * (sw2 + gap)
        else:
            # 右对齐：最后一颗在 x 处，向左排
            cx = x + sw2 / 2 - (n - 1 - i) * (sw2 + gap) + (sw2 / 2 - sw2 / 2)
            cx = (x + sw2 / 2) - (n - 1 - i) * (sw2 + gap)
        cy = y + sh2 / 2
        if star is not None:
            paste_center(canvas, star, cx, cy, max(sw2, sh2))
        else:
            d = ImageDraw.Draw(canvas, "RGBA")
            col = (40, 40, 40) if is_rank else (232, 168, 32)
            r = min(sw2, sh2) * 0.46
            d.polygon(_star_pts(cx, cy, r, r * 0.44), fill=col + (240,),
                      outline=darken(col, 0.5) + (255,))


def _star_pts(cx, cy, r_out, r_in, rot=-90.0, n=5):
    pts = []
    for i in range(n * 2):
        a = math.radians(rot + i * 180.0 / n)
        rr = r_out if i % 2 == 0 else r_in
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    return pts


def draw_link_arrows(canvas: Image.Image, spec: CardSpec, f: G.Frame, *, assets=None,
                     weight: float = 0.135) -> None:
    """连接箭头：按卡图窗的**八方位**定位，on/off 两态。

    旧版把箭头一律贴到插画窗中心，且按最长边缩放 —— 素材长宽比极不统一
    （水平箭头 281×98、对角 168×168），结果 8 个箭头的视觉重量完全不同。
    这里改为：① 按方位贴到画窗边缘/角；② **按面积归一**缩放，保证观感一致；
    ③ off 态加一层暗底，避免落在亮色插画上时看不见。
    """
    if spec.frame != "link":
        return
    x, y, w, h = f.rect(G.STANDARD_ART_KEY)
    L, T, R, B = x, y, x + w, y + h
    cx, cy = x + w / 2, y + h / 2
    positions = {
        "上": (cx, T), "下": (cx, B), "左": (L, cy), "右": (R, cy),
        "左上": (L, T), "右上": (R, T), "左下": (L, B), "右下": (R, B),
    }
    on = set(spec.link_markers or [])
    target = min(w, h) * max(0.05, weight)        # 归一化后的等效边长

    for zh, (px_, py_) in positions.items():
        is_on = zh in on
        im = None
        if assets is not None:
            try:
                im = assets.arrow(zh, on=is_on)
            except Exception:
                im = None
        if im is None:
            _arrow_fallback(canvas, f, px_, py_, is_on, target)
            continue
        im = im.convert("RGBA")
        if im.width == 0 or im.height == 0:
            continue
        # 按面积归一，而不是按最长边 —— 这样横/竖/对角箭头的视觉重量一致
        k = target / max(1.0, (im.width * im.height) ** 0.5)
        im = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))),
                       Image.LANCZOS)
        left = int(round(px_ - im.width / 2))
        top = int(round(py_ - im.height / 2))
        if not is_on:
            # off 态：先垫一层柔和暗底，保证在亮色插画上仍可辨识
            pad = max(1, int(f.px(3)))
            plate = Image.new("RGBA", (im.width + pad * 2, im.height + pad * 2), (0, 0, 0, 0))
            ImageDraw.Draw(plate).rounded_rectangle(
                [0, 0, plate.width - 1, plate.height - 1], radius=f.px(6),
                fill=(0, 0, 0, 96))
            canvas.alpha_composite(plate, (left - pad, top - pad))
        canvas.alpha_composite(im, (left, top))


def _arrow_fallback(canvas: Image.Image, f: G.Frame, px_: float, py_: float,
                    is_on: bool, target: float) -> None:
    """无素材时用三角形画一个箭头占位（保证 8 向仍可辨识）。"""
    d = ImageDraw.Draw(canvas, "RGBA")
    r = target * 0.42
    col = (255, 214, 92, 235) if is_on else (60, 60, 60, 150)
    d.polygon([(px_, py_ - r), (px_ + r, py_ + r * 0.8), (px_ - r, py_ + r * 0.8)],
              fill=col, outline=(20, 20, 20, 220))


def draw_pendulum_scales(canvas: Image.Image, spec: CardSpec, f: G.Frame,
                         font_of: FontOf, pal: Palette) -> None:
    """灵摆刻度数字（左蓝右红）。"""
    if not spec.is_pendulum or spec.pendulum_scale is None:
        return
    d = ImageDraw.Draw(canvas)
    size = int(round(f.font(G.FONT_SIZE["pendulum_scale"])))
    font = font_of(size)
    for key, col in (("pendulum_scale_l", (56, 108, 200)),
                     ("pendulum_scale_r", (200, 64, 72))):
        x, y, w, h = f.rect(key)
        txt = str(spec.pendulum_scale)
        if font is not None:
            d.text((x + w / 2, y + h / 2), txt, font=font, fill=col, anchor="mm")
        else:
            d.text((x + w / 2, y + h / 2), txt, fill=col, anchor="mm")


# ══════════════════════════════════════════════════════════════════════
#  类型行 / 魔陷标签
# ══════════════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════════════
#  多语言术语查询（惰性 + 可降级）
# ══════════════════════════════════════════════════════════════════════
_LEX_REVERSE: dict | None = None
_LEX_FAILED = False


def _lex_reverse() -> dict:
    """建「中文名 → {lang: 译名}」的反向索引。术语表不可用时返回空 dict。"""
    global _LEX_REVERSE, _LEX_FAILED
    if _LEX_REVERSE is not None or _LEX_FAILED:
        return _LEX_REVERSE or {}
    try:
        from ..content.psct import lexicon as LX          # 惰性：渲染器不硬依赖 content
        table = LX.terms()
    except Exception:
        _LEX_FAILED = True
        _LEX_REVERSE = {}
        return {}
    rev: dict[str, dict] = {}
    for key, item in (table or {}).items():
        if not isinstance(item, dict):
            continue
        zh = item.get("zh_cn")
        if not zh:
            continue
        rev.setdefault(str(zh), item)
        # 属性在术语表里带「属性」后缀（暗属性），而 CardSpec 存的是「暗」
        if str(zh).endswith("属性"):
            rev.setdefault(str(zh)[:-2], item)
    _LEX_REVERSE = rev
    return rev


def lex(zh_value: str, lang: str, fallback: str | None = None) -> str:
    """把中文术语翻成目标语言。查不到就返回原值（**永远不抛异常**）。"""
    if not zh_value or lang in ("zh_cn", "zh_tw"):
        return zh_value or (fallback or "")
    item = _lex_reverse().get(str(zh_value))
    if not item:
        return fallback if fallback is not None else zh_value
    got = item.get(lang)
    if got:
        return str(got)
    # 该语言缺这条 → 回落 en → 原值
    return str(item.get("en") or zh_value)


#: 怪兽标签（MONSTER_TAGS 的键）→ 术语表 key
_TAG_LEX_KEY = {
    "tuner": "card_tuner", "spirit": "card_spirit", "union": "card_union",
    "gemini": "card_gemini", "flip": "card_flip", "toon": "card_toon",
    "special_summon": "card_special_summon",
}

def type_line_text(spec: CardSpec, lang: str = "zh_cn") -> str:
    """怪兽类型行：「【种族／属性／标签】」。官方 Series 10 起通常怪兽显式写「通常」。"""
    fd = spec.frame_def
    if not fd.is_monster:
        return ""
    # 术语一律走术语表（查不到自动回落原值），保证英文卡不会出现中英混排
    race = lex(spec.race, lang)
    parts = [race, lex(spec.attribute, lang)]
    if spec.frame == "normal":
        parts.append("Normal" if lang == "en" else "通常")
    for t in spec.tags or []:
        meta = MONSTER_TAGS.get(t)
        if meta:
            # 回落链必须经过 en：否则 ko/de 这类缺译语言会掉回中文，
            # 在一张纯西文卡上突然出现两个汉字
            parts.append(meta.get(lang) or meta.get("en") or meta["zh_cn"])
    if spec.frame == "link":
        parts.append("Link" if lang == "en" else "连接")
    elif "pendulum" in spec.frame:
        parts.append("Pendulum" if lang == "en" else "灵摆")
    # ⚠ 括号与分隔符按语言区分：官方英文卡用半角方括号与 " / "，
    #   中日文用全角【】与全角斜杠。之前所有语言都用【】，英文卡是错的。
    if lang in ("zh_cn", "zh_tw", "ja"):
        sep, (lb, rb) = "／", ("【", "】")
    else:
        sep, (lb, rb) = " / ", ("[", "]")
    return lb + sep.join(p for p in parts if p) + rb


def st_label_text(spec: CardSpec, lang: str = "zh_cn") -> str:
    k = None
    if spec.frame == "spell":
        k = SPELL_KINDS.get(spec.spell_kind) or SPELL_KINDS["normal"]
    elif spec.frame == "trap":
        k = TRAP_KINDS.get(spec.trap_kind) or TRAP_KINDS["normal"]
    if k is None:
        return ""
    txt = k.get(lang) or k["zh_cn"]
    if lang in ("zh_cn", "zh_tw", "ja"):
        return "【" + txt + "】"
    return "[" + txt + "]"


def _bg_lum(canvas: Image.Image, box) -> float:
    """采样一块区域的平均亮度（0-255），给压字元素选墨色用。失败按浅底处理。"""
    try:
        x0, y0, x1, y1 = [max(0, int(v)) for v in box]
        g = canvas.convert("L").crop((x0, y0, x1, y1))
        if g.width < 1 or g.height < 1:
            return 200.0
        px = list(g.resize((16, 4), Image.LANCZOS).getdata())
        return sum(px) / float(len(px))
    except Exception:
        return 200.0


def draw_type_line(canvas: Image.Image, spec: CardSpec, f: G.Frame, font_of: FontOf,
                   pal: Palette, *, lang: str = "zh_cn", pendulum: bool = False,
                   label_rect=None, fill=None, stroke: float = 0.0,
                   size_ref: Optional[float] = None,
                   contrast: bool = False) -> None:
    """类型行 / 魔陷类型标签。

    官方超框里魔陷标签也在类型行位置（OCG 官方做法）并用面板深色墨，字号
    与怪物类型行一致（``size_ref``）；``label_rect`` / ``fill`` / ``stroke``
    只由 ``overframe`` 传入，旧档不传，行为不变。
    """
    d = ImageDraw.Draw(canvas)
    txt = type_line_text(spec, lang) if spec.is_monster else st_label_text(spec, lang)
    if not txt:
        return
    key = "pendulum_type_line" if pendulum else ("type_line" if spec.is_monster else "st_label")
    x, y, w, h = (tuple(label_rect) if label_rect is not None else f.rect(key))
    ref = (G.FONT_SIZE["st_label"] if not spec.is_monster else G.FONT_SIZE["type_line"])
    if size_ref is not None:
        ref = float(size_ref)
    base = f.font(ref)
    base *= G.font_scale(lang) * (spec.render.font_scale_text or 1.0)
    anchor_x = x + w if not spec.is_monster else x
    anc = "rm" if not spec.is_monster else "lm"
    font, squeeze = _fit_to_width(d, txt, font_of, w, base, base * 0.6)
    if font is None:
        return
    ink = fill if fill is not None else (
        (255, 255, 255) if name_is_white(spec.frame) else pal.type_ink)
    if contrast and fill is None and stroke <= 0:
        # 出血档：类型行压在插画上 → 按底图明暗自适应墨色与描边
        lum = _bg_lum(canvas, (x, y, x + w, y + h))
        if lum < 120:
            ink, out_c, sw = (255, 255, 255), (32, 26, 20), 1.8
        else:
            ink, out_c, sw = (pal.type_ink if not name_is_white(spec.frame)
                              else (40, 34, 28)), (246, 240, 228), 1.4
        text_with_outline(d, (anchor_x, y + h / 2), txt, font, ink, out_c, sw, anc)
        return
    if stroke and stroke > 0:
        text_with_outline(d, (anchor_x, y + h / 2), txt, font, ink,
                          pal.name_outline, stroke, anc)
    else:
        d.text((anchor_x, y + h / 2), txt, font=font, fill=ink, anchor=anc)


# ══════════════════════════════════════════════════════════════════════
#  效果文本 / 说明文
# ══════════════════════════════════════════════════════════════════════
def _count_effect_icons(kind: str, spell_kind: str, trap_kind: str):
    return None


def split_paragraphs(body: str) -> list[str]:
    """把卡文切成「段」，每段独占一行块。

    官方卡文里**每条编号效果独占一段**（①②③ 是段落起始标记，不是行内装饰）。
    规则：
      1. 显式换行 ``\\n`` 一律断段；
      2. 行中间出现的 ``①：`` 形式（编号紧跟冒号 = PSCT 的段落起始标记）也在其前断段；
      3. **行内引用不断段**：``这个卡名的①②的效果1回合各能使用1次。`` 里的 ①②
         后面跟的是「的」而不是冒号，官方卡文把它整句排在同一行，绝不能拆；
      4. 空段丢弃。
    """
    import re
    text = str(body or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(?<!^)(?<!\n)(?=[①-⑳][：:])", "\n", text, flags=re.M)
    out = []
    for para in text.split("\n"):
        p = para.strip()
        if p:
            out.append(p)
    return out


def draw_effect_text(canvas: Image.Image, spec: CardSpec, f: G.Frame, font_of: FontOf,
                     pal: Palette, *, lang: Optional[str] = None,
                     pendulum: bool = False, box_key: Optional[str] = None,
                     profile: str = "description",
                     uniform_ink: bool = False) -> dict:
    """效果正文：**按段逐块排版**，逐段自适应字号，段间留白。

    ``uniform_ink=True`` 关掉 PSCT 强调（编号/「」/关键词加粗），用于官方超框：
    官方卡文是同一墨色同一字重，只有 DIY 档才做关键词强调。

    返回 ``{lines, size, overflow, paragraphs}`` 供调用方做溢出提示。
    """
    lang = lang or spec.render.lang_text
    body = spec.text_in(lang)
    if not body.strip():
        return {"lines": 0, "size": 0, "overflow": False, "paragraphs": 0}

    if box_key is None:
        if pendulum:
            box_key = "pendulum_text"
        elif spec.is_monster:
            box_key = "text_box"
        else:
            box_key = "text_box_st"
    x, y, w, h = f.rect(box_key)
    il, it, ir, ib = G.text_inset(lang)
    x += f.px(il); y += f.px(it, "y")
    w -= f.px(il + ir); h -= f.px(ib, "y")

    # 缩放链说明（很容易踩坑，写清楚）：
    #   FIT_PROFILES 的字号是 REF 坐标系数值 →
    #   ``text.fit()`` 内部会乘一次 ``font_scale(lang)`` 并把结果交给 ``font_of`` →
    #   而作业画布是卡框原生 1394×2031（比 REF 大 1.71 倍），所以 ``font_of`` 里
    #   **必须再乘 f.k**。这里只额外叠用户自己的 ``font_scale_text``，语言缩放不重复乘。
    user_scale = float(spec.render.font_scale_text or 1.0)
    lang_scale = G.font_scale(lang)

    def font_of_scaled(size: float):
        return font_of(max(8, int(round(size * f.k * user_scale))))

    def lh_px(tier: dict) -> float:
        """档位行距 → 作业画布像素。

        带一个**下限**：`FIT_PROFILES` 的行距系数来自社区模板（约 0.98–1.02 倍字号），
        直接照用会让 CJK 行与行轻微压字。官方卡文的字距/行距比约 1.16，这里取 1.12
        作为下限，既保持紧凑又不糊成一片。
        """
        ref = max(float(tier["lineHeight"]),
                  float(tier["fontSize"]) * MIN_LINE_RATIO)
        return ref * lang_scale * f.ky * user_scale

    paragraphs = split_paragraphs(body)
    d = ImageDraw.Draw(canvas)
    tiers = G.FIT_PROFILES.get(profile, G.FIT_PROFILES["description"])

    # ⚠ 单位三件套必须落在同一个刻度上，否则行数会算错（实测踩过两次，见文件末尾注记）：
    #     · box 宽高      → **画布像素**（w / h 本来就是）
    #     · 字号          → ``size_scale`` 让 fit 内部把档位字号乘成画布像素
    #     · 行距          → fit 内部的 lh 同样被 size_scale 放大，与我们用的 lh_px 一致
    #   三者统一之后 ``font_of`` 只需按像素字号直取字体，不再自己缩放。
    fit_w = max(10.0, w)
    fit_h = max(10.0, h)
    px_scale = f.k * user_scale

    def _fit_at(para: str, tier_fs: float, avail_h: float):
        """在**指定档位字号**下排版一段。

        为什么要传一个"钉死字号"的 font_of：``text.fit()`` 内部会自己从最大档往下挑，
        我们没法让它只用某一档（``min_size`` 只是抬下限）。把 font_of 固定成该档字号后，
        断行结果对所有内部档位都相同（= 该档的真实断行），于是 ``len(fit.lines)``
        就是该档的行数，可以拿来比较总高度。绘制前再把 ``fit.size`` 还原成该档即可。
        """
        # 该档在画布上的真实像素字号
        px = max(8, int(round(tier_fs * lang_scale * f.k * user_scale)))

        def pinned(_size, _px=px):
            return font_of(_px)

        runs = (T.mark_psct(para, lang)
                if (spec.render.psct_bold and not uniform_ink)
                else [T.TextRun(para)])
        fit = T.fit(runs, pinned, (fit_w, max(10.0, avail_h)), lang,
                    profile=profile, max_lines=None, min_size=1, apply_inset=False,
                    size_scale=px_scale)
        # fit.size 作为唯一真相源：此时它就是画布像素字号
        fit.size = px
        return fit

    # ① 整篇试档：找到"所有段都放得下"的最大档位，保证整篇字号统一（官方观感）。
    #    试排结果按段留下来，命中档位后直接复用 —— 长卡文能省掉一整轮重排。
    best_tier = None
    trial: list = []
    for tier in tiers:
        fs = float(tier["fontSize"])
        lh_tier = lh_px(tier)          # 画布像素，与 fit_h 同刻度
        total_h = 0.0
        fits: list = []
        ok = True
        for pi, para in enumerate(paragraphs):
            fit = _fit_at(para, fs, fit_h - total_h)
            if fit.overflow:
                ok = False
                break
            # 段间距只加在段与段之间：旧版连最后一段也算一次，
            # 长卡文会被误报「溢出」（实际画得下）。
            total_h += len(fit.lines) * lh_tier
            if pi < len(paragraphs) - 1:
                total_h += lh_tier * PARA_GAP
            if total_h > fit_h + 0.5:
                ok = False
                break
            fits.append(fit)
        if ok and len(fits) == len(paragraphs):
            best_tier, trial = tier, fits
            break

    if best_tier is None:
        # 连最小档都放不下：仍然按最小档排出**能画多少画多少**，
        # 宁可"看得见一部分 + 明确溢出提示"，也不要空着文本框什么都不显示。
        best_tier = tiers[-1]
        fs_min = float(best_tier["fontSize"])
        lh_floor = lh_px(best_tier)     # 画布像素
        trial = []
        used = 0.0
        for para in paragraphs:
            avail = fit_h - used
            if avail <= lh_floor:
                break
            fit = _fit_at(para, fs_min, avail)
            keep = max(0, int(avail // lh_floor))
            if keep < len(fit.lines):
                fit.lines = fit.lines[:keep]
                fit.indents = list(fit.indents)[:keep]
                fit.overflow = True
            if not fit.lines:
                break
            trial.append(fit)
            used += len(fit.lines) * lh_floor + lh_floor * 0.28

    pin_fs = float(best_tier["fontSize"])
    lh = lh_px(best_tier)
    cy = y
    overflow = False
    total_lines = 0
    for i, para in enumerate(paragraphs):
        remain = h - (cy - y)
        if remain <= lh * 0.7:
            overflow = True
            break
        fit = (trial[i] if i < len(trial)
               else _fit_at(para, pin_fs, remain))
        fit.line_height = lh          # 行距钉到画布像素（与 fit_h 同刻度）
        if len(fit.lines) * lh > remain + lh * 0.5:
            # 这一段放不进剩余高度：只画放得下的行，其余裁掉并标记溢出
            keep = max(0, int(remain // lh))
            if keep <= 0:
                overflow = True
                break
            fit.lines = fit.lines[:keep]
            fit.indents = list(fit.indents)[:keep]
            fit.overflow = True
        # fit.size 已是画布像素字号 → 这里用 font_of（按像素直取），不再二次缩放
        T.draw_fitted(d, fit, (x, cy), font_of, pal.text_ink,
                      squeeze_x=fit.squeeze_x,
                      bold_fill=(darken(pal.text_ink, 0.12)
                                 if (spec.render.psct_bold and not uniform_ink)
                                 else None))
        total_lines += len(fit.lines)
        cy += len(fit.lines) * lh + lh * (PARA_GAP if i < len(paragraphs) - 1 else 0.0)
        if fit.overflow:
            overflow = True
            if i < len(paragraphs) - 1:
                break

    # 字号单一来源：与 draw_fitted 用的完全一致，避免调用方再乘一次导致 3% 偏差
    eff_size = float(best_tier["fontSize"]) * lang_scale * f.k * user_scale
    return {"lines": total_lines, "size": round(eff_size, 1),
            "size_px": int(round(eff_size)),
            "overflow": overflow, "paragraphs": len(paragraphs),
            "tier": best_tier.get("id", "")}





def draw_flavor(canvas: Image.Image, spec: CardSpec, f: G.Frame, font_of: FontOf,
                pal: Palette, *, lang: Optional[str] = None) -> None:
    """通常怪兽/灵摆的说明文（斜体观感，居中偏上）。"""
    lang = lang or spec.render.lang_flavor
    body = spec.flavor_in(lang)
    if not body.strip():
        return
    x, y, w, h = f.rect("text_box")
    il, it, ir, ib = G.text_inset(lang)
    x += f.px(il); y += f.px(it, "y"); w -= f.px(il + ir); h -= f.px(ib, "y")
    runs = [T.TextRun(body, italic=True)]
    # 同样要把 REF 系字号换算到作业画布（见 draw_effect_text 的说明）
    scale = G.font_scale(lang) * (spec.render.font_scale_text or 1.0) * f.k
    fit = T.fit(runs, lambda s: font_of(max(8, int(round(s * scale)))), (w, h),
                lang, profile="lore")
    d = ImageDraw.Draw(canvas)
    T.draw_fitted(d, fit, (x, y), lambda s: font_of(max(8, int(round(s * scale)))),
                  pal.text_ink, squeeze_x=fit.squeeze_x)


# ══════════════════════════════════════════════════════════════════════
#  数值行
# ══════════════════════════════════════════════════════════════════════
def _fmt_num(v) -> str:
    if v is None or v == "":
        return "?"
    if isinstance(v, str):
        return v if v.strip() else "?"
    try:
        n = int(v)
    except Exception:
        return str(v)
    return "?" if n < 0 else str(n)


def draw_stats(canvas: Image.Image, spec: CardSpec, f: G.Frame, font_of: FontOf,
               pal: Palette, *, separator: bool = True) -> None:
    """ATK/DEF（连接怪兽显示 LINK-n 与 ATK）。含卡框不自带的数值分隔线。"""
    fd = spec.frame_def
    if not fd.has_atk:
        return
    d = ImageDraw.Draw(canvas)
    ink = pal.stat_ink
    size = int(round(f.font(G.FONT_SIZE["atk_def"])))
    font = font_of(size)

    if separator:
        x, y, w, h = f.rect("stats_separator")
        d.rectangle([x, y, x + w, y + max(1.0, f.px(1.2))], fill=pal.hairline)

    if spec.frame == "link":
        # LINK-4  [箭头图标]  ATK/2500
        lx, ly, lw, lh = f.rect("level_star")
        small = font_of(int(round(f.font(G.FONT_SIZE["link"]))))
        if small is not None:
            d.text((lx - f.px(4), ly + lh / 2), f"LINK-{spec.effective_level}",
                   font=small, fill=ink, anchor="rm")
        ax, ay = f.point("link_value")
        if font is not None:
            d.text((ax, ay), f"ATK/{_fmt_num(spec.atk)}", font=font, fill=ink, anchor="rm")
        return

    ax, ay = f.point("atk_value")
    if fd.has_def:
        # ATK 与 DEF 之间要留出官方卡面那样的空隙：两个数值各自右对齐到自己的
        # 锚点，画布窄的时候会贴成「1600DEF/1200」（2026-10-26 实测）。
        # 这里按字号留 0.32em 的缝，只动 ATK 的落点，不影响 DEF 与分隔线。
        gap = max(float(f.px(3)), size * 0.32)
        if font is not None:
            d.text((ax - gap, ay), f"ATK/{_fmt_num(spec.atk)}", font=font,
                   fill=ink, anchor="rm")
    elif font is not None:
        d.text((ax, ay), f"ATK/{_fmt_num(spec.atk)}", font=font, fill=ink, anchor="rm")
    if fd.has_def:
        dx, dy = f.point("def_value")
        if font is not None:
            d.text((dx, dy), f"DEF/{_fmt_num(spec.dfd)}", font=font, fill=ink, anchor="rm")


# ══════════════════════════════════════════════════════════════════════
#  元信息（卡号 / 密码 / 版权 / 激光标 / 纪念标）
# ══════════════════════════════════════════════════════════════════════
_COPYRIGHT_LANG = {"zh_cn": "sc", "zh_tw": "sc", "ja": "jp", "en": "en",
                   "ko": "en", "de": "en", "fr": "en", "it": "en",
                   "pt": "en", "es": "en"}


def draw_meta(canvas: Image.Image, spec: CardSpec, f: G.Frame, font_of: FontOf,
              pal: Palette, *, assets=None, overframe: bool = False,
              panel_top: Optional[float] = None,
              contrast: bool = False) -> None:
    d = ImageDraw.Draw(canvas)
    r = spec.render

    def _contrast_ink(cx: float, cyy: float):
        """卡号/密码压在插画上时按底图明暗选墨色（白字深边 / 深字浅边）。"""
        lum = _bg_lum(canvas, (cx - 240, cyy - 22, cx + 6, cyy + 22))
        if lum < 120:
            return (255, 248, 228), pal.name_outline
        return pal.text_ink, (246, 240, 228)

    # 卡号（右上，斜体小字观感）
    ccx, ccy = f.point("card_code")
    if overframe:
        # 官方超框：卡号在面板上沿外侧，白/金 + 深描边（压在画上）；
        # 右列对齐——与 ATK·DEF 共用一条右基线，别比数值缩进 20px。
        if getattr(spec.frame_def, "has_def", False):
            ccx = f.point("def_value")[0]
        ccy = (float(panel_top) if panel_top is not None
               else f.rect("type_line")[1]) - f.px(18, "y")
    if r.set_number:
        fnt = font_of(int(round(f.font(G.FONT_SIZE["card_code"]))))
        if fnt is not None:
            if overframe:
                d.text((ccx, ccy), r.set_number, font=fnt,
                       fill=(255, 248, 228), anchor="rm",
                       stroke_width=max(1, int(round(f.px(1.6)))),
                       stroke_fill=pal.name_outline)
            elif contrast:
                cfill, cout = _contrast_ink(ccx, ccy)
                d.text((ccx, ccy), r.set_number, font=fnt, fill=cfill, anchor="rm",
                       stroke_width=max(1, int(round(f.px(1.4)))), stroke_fill=cout)
            else:
                d.text((ccx, ccy), r.set_number, font=fnt, fill=pal.text_ink, anchor="rm")

    # 密码（8 位数字，在卡号下方的固定位置）。官方超框把密码区交给画面盖住。
    if r.show_password and spec.id and not overframe:
        fnt = font_of(int(round(f.font(G.FONT_SIZE["card_code"]) * 0.92)))
        if fnt is not None:
            if contrast:
                cfill, cout = _contrast_ink(ccx, ccy + f.px(26, "y"))
                d.text((ccx, ccy + f.px(26, "y")), f"{int(spec.id):08d}", font=fnt,
                       fill=cfill, anchor="rm",
                       stroke_width=max(1, int(round(f.px(1.4)))), stroke_fill=cout)
            else:
                d.text((ccx, ccy + f.px(26, "y")), f"{int(spec.id):08d}", font=fnt,
                       fill=pal.text_ink, anchor="rm")

    # 版权标（矢量素材，失败则画占位小字）
    if r.show_copyright:
        lang = r.copyright_lang or _COPYRIGHT_LANG.get(spec.render.lang_text, "sc")
        cx, cy = f.point("copyright")
        im = None
        if assets is not None:
            try:
                im = assets.copyright_mark(lang, "white" if name_is_white(spec.frame) else "black")
            except Exception:
                im = None
        if im is not None:
            _paste_right_bottom(canvas, im, cx, cy, f)
        else:
            fnt = font_of(int(round(f.font(G.FONT_SIZE["copyright"]))))
            if fnt is not None:
                txt = {"sc": "©スタジオ・ダイス／集英社・テレビ東京・ＫＯＮＡＭＩ",
                       "jp": "©スタジオ・ダイス／集英社・テレビ東京・ＫＯＮＡＭＩ",
                       "en": "©2020 Studio Dice/SHUEISHA, TV TOKYO, KONAMI"}.get(
                           lang, "©2020 Studio Dice/SHUEISHA, TV TOKYO, KONAMI")
                d.text((cx, cy), txt, font=fnt, fill=pal.text_ink, anchor="rm")

    # 激光防伪标（右下）
    if r.show_laser and assets is not None:
        x, y, w, h = f.rect("sticker")
        try:
            im = assets.laser(1)
        except Exception:
            im = None
        if im is not None:
            paste_center(canvas, im, x + w / 2, y + h / 2, min(w, h))

    # 20 周年标（左下）
    if r.show_stamp20 and assets is not None:
        x, y, w, h = f.rect("stamp20")
        try:
            im = assets.stamp("20th")
        except Exception:
            im = None
        if im is not None:
            paste_center(canvas, im, x + w / 2, y + h / 2, max(w, h))


def _paste_right_bottom(canvas: Image.Image, im: Image.Image, right: float,
                        bottom: float, f: G.Frame) -> None:
    """把版权标按「右下角对齐」贴上，宽度限制在卡宽的一个比例内。"""
    im = _rgba(im)
    target_w = min(im.width, f.px(300))
    if im.width > 0:
        k = target_w / im.width
        im = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))), Image.LANCZOS)
    canvas.alpha_composite(im, (int(right - im.width), int(bottom - im.height)))


# ══════════════════════════════════════════════════════════════════════
#  文本框面板（出框模式下需要半透明）
# ══════════════════════════════════════════════════════════════════════
def draw_pendulum_panels(canvas: Image.Image, f: G.Frame, pal: Palette, *,
                         opacity: float = 1.0, radius_px: float = 10.0) -> None:
    """灵摆卡的面板铺底。

    灵摆卡框素材的中段是一整块**空窗**（实测白区 REF 212–1116，占全卡 76%），
    卡框本身不提供任何面板美术 —— 因此两块面板与它们之间的连接带必须由渲染器绘制。
    旧版只画了三块矩形，导致下缘露出 35px 纯白横条、两面板间露出 13px 框原色。
    这里改为「先铺一整块底 → 再画面板」，从根上消除缝隙。
    """
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    a = int(round(max(0.0, min(1.0, opacity)) * 255))

    bx, by, bw, bh = f.rect("pendulum_backing")
    d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=f.px(radius_px),
                        fill=pal.text_panel + (a,))
    for key in ("pendulum_panel", "pendulum_monster_panel"):
        px_, py_, pw, ph = f.rect(key)
        d.rounded_rectangle([px_, py_, px_ + pw, py_ + ph], radius=f.px(radius_px),
                            fill=pal.text_panel + (a,))
        d.rectangle([px_, py_, px_ + pw, py_ + ph], outline=pal.hairline + (a,),
                    width=max(1, int(f.px(1.2))))
    canvas.alpha_composite(overlay)


def draw_text_panel(canvas: Image.Image, f: G.Frame, pal: Palette, *,
                    opacity: float = 1.0, pendulum: bool = False,
                    radius_px: float = 10.0, top: Optional[float] = None,
                    bottom: Optional[float] = None,
                    border: bool = False, shadow: bool = False) -> None:
    """效果文本框底色。

    ``opacity < 1`` 用于出框（官方做法：复用灵摆效果栏的半透明方案）。

    官方超框额外用这几个参数（旧档不传，行为完全不变）：

    * ``top``：面板上沿（REF 系 y）。官方超框从类型行顶部起，把类型行一起包进面板；
    * ``bottom``：面板下沿。官方超框一直包到版权行上方，把 ATK·DEF 也包进框内；
    * ``border``：金边 + 深色外线 + 内侧高光；
    * ``shadow``：面板向画面上方投下的软阴影。
    """
    if pendulum:
        draw_pendulum_panels(canvas, f, pal, opacity=opacity, radius_px=radius_px)
        return
    if opacity >= 0.999 and not border and not shadow and top is None and bottom is None:
        return
    x, py, w, ph = f.rect("text_panel")
    panel_bottom = py + ph
    if bottom is not None:
        panel_bottom = float(bottom)
    if top is not None:
        py = float(top)
        ph = max(1.0, panel_bottom - py)
    elif bottom is not None:
        ph = max(1.0, panel_bottom - py)
    if border:
        # 官方超框：边框要包住类型行的【】；标准 text_panel 比 type_line 窄 2px
        pad_x = float(f.px(3.0))
        x -= pad_x
        w += pad_x * 2
    r = max(1.0, float(f.px(radius_px)))

    if shadow:
        sh = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        sd = ImageDraw.Draw(sh)
        sd.rounded_rectangle([x + f.px(2), py + f.px(3),
                              x + w + f.px(2), py + ph + f.px(3)],
                             radius=r, fill=(0, 0, 0, 80))
        sh = sh.filter(ImageFilter.GaussianBlur(max(1.0, f.px(4.0))))
        canvas.alpha_composite(sh)

    if opacity < 0.999:
        overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay)
        a = int(round(max(0.0, min(1.0, opacity)) * 255))
        d.rounded_rectangle([x, py, x + w, py + ph], radius=r,
                            fill=pal.text_panel + (a,))
        canvas.alpha_composite(overlay)

    if border:
        bd = ImageDraw.Draw(canvas)
        w_out = max(1, int(round(f.px(1.2))))
        w_gold = max(1, int(round(f.px(1.8))))
        bd.rounded_rectangle([x, py, x + w, py + ph], radius=r,
                             outline=(38, 30, 20, 235), width=w_out)
        inset = w_out + 0.5 * w_gold
        bd.rounded_rectangle([x + inset, py + inset, x + w - inset, py + ph - inset],
                             radius=max(1.0, r - inset),
                             outline=(208, 174, 108, 238), width=w_gold)
        inset2 = inset + w_gold + 0.5
        bd.rounded_rectangle([x + inset2, py + inset2,
                              x + w - inset2, py + ph - inset2],
                             radius=max(1.0, r - inset2),
                             outline=(255, 244, 214, 90), width=1)


def module_capabilities() -> dict:
    return {
        "layers": ["name", "badge", "stars", "link_arrows", "pendulum_scales",
                   "type_line", "effect_text", "flavor", "stats", "meta", "text_panel"],
        "frames": list(FRAMES),
    }
