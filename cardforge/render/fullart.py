"""出框 / 全画（官方名 オーバーフレーム / Extended Art）合成。

**关键定性**：出框是「设计处理」，**不是罕贵度**——它与罕贵正交，可任意叠加
（社区缩写 OFPSE = Over-Frame + Prismatic Secret Rare）。因此本模块独立于
:mod:`cardforge.render.rarities`。

官方视觉规格（调研自日文 Wiki 与官方商品页，本模块严格照做）
------------------------------------------------------------
* 插画覆盖文本框，但文本框做**半透明**处理（官方复用灵摆效果栏的半透明方案）。
* **版权行区域插画被截断**（不能用半透明糊过去，必须 clip）。
* **密码区被覆盖**（不截断）。
* 卡框、卡名栏、属性、等级/阶级全部**保留**；**卡名文字本身不可被遮挡**。

本模块给出 5 个自定档位（UI 中标注"非官方分类"），见 ``MODES``。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from ..core.models import CardSpec, FullArtOptions
from . import geometry as G

MODES = ("none", "overframe", "art_bleed", "art_over", "full_bleed",
         "pendulum_full", "subject_bleed")

#: 每种模式下，插画绘制完成后需要**从原卡框回贴**的区域（保证框体与卡名栏正常显示）
#: ⚠ 只回贴卡名条与魔陷标签这类**必读信息条**。绝不能回贴 ``frame_inset``——
#: 那等于把整张卡框盖回插画上，超框档位的插画会被整片擦掉（实测踩过这个坑）。
_RESTORE_REGIONS: dict[str, tuple[str, ...]] = {
    "none": (),
    # 官方超框：插画止于内框，外框由底图保留；卡名条/类型条都不回贴（官方没有名条）
    "overframe": (),
    "art_bleed": ("title_bevel", "st_label"),
    "art_over": ("title_bevel", "st_label"),
    "full_bleed": ("title_bevel", "st_label"),
    "pendulum_full": ("title_bevel", "pendulum_scale_l", "pendulum_scale_r"),
    # 主体出框：主体会压到卡名条上，所以卡名条与类型行必须回贴
    "subject_bleed": ("title_bevel", "st_label"),
}

#: 绘制次序。``art`` 出现的位置之后绘制的元素会盖在插画上。
DRAW_ORDER: dict[str, list[str]] = {
    "none": ["frame", "art", "panel", "content", "finish"],
    # 官方超框：插画先铺满内框，面板/名/星级/文本全部后画
    "overframe": ["frame", "art", "panel", "content", "finish"],
    "art_bleed": ["frame", "art", "restore", "panel", "content", "finish"],
    "art_over": ["frame", "art", "restore", "panel", "content", "finish"],
    "full_bleed": ["art", "frame_ghost", "restore", "panel", "content", "finish"],
    "pendulum_full": ["frame", "art", "restore", "panel", "content", "finish"],
    # 背景先按窗裁切 → 主体压出窗沿 → 回贴卡名条 → 文本框与正文照常绘制
    "subject_bleed": ["frame", "art", "subject", "restore", "panel", "content", "finish"],
}


@dataclass
class FullArtPlan:
    """一次出框合成所需的全部参数。"""
    mode: str = "none"
    art_rect: tuple[float, float, float, float] = (0, 0, 0, 0)
    panel_opacity: float = 1.0
    name_stroke: float = 0.0
    fade_px: float = 0.0
    restore_regions: tuple[str, ...] = ()
    clip_bottom: Optional[float] = None    # 插画下边界（版权行以上）
    frame_alpha: float = 1.0               # full_bleed 时卡框的整体不透明度
    #: subject_bleed：主体层相对卡图窗的放大倍率（1.0 = 不出框）
    subject_scale: float = 1.0
    #: subject_bleed：主体层垂直偏移（占窗高比例，负 = 上移）
    subject_offset_y: float = 0.0
    order: list[str] = field(default_factory=list)
    notes: str = ""
    #: 官方超框：面板从类型行顶部起（REF 系 y）；None = 用标准 ``text_panel``
    panel_top: Optional[float] = None
    panel_border: bool = False
    panel_shadow: bool = False
    hide_password: bool = False
    code_above_panel: bool = False
    #: 卡名填充色（官方超框在无箔罕贵下用白字 + 深描边）；None = 沿用旧逻辑
    name_fill: Optional[tuple[int, int, int]] = None
        #: 官方超框：类型行/卡种标签的矩形（默认用卡框的类型行位置）
    type_label_rect: Optional[tuple[float, float, float, float]] = None
    #: 官方超框：类型行落在浅色面板上 → 强制用面板深色墨（魔陷框默认是白字）
    type_label_dark: bool = False
    #: 官方超框：面板下沿（REF 系 y）；None = 用标准 ``text_panel`` 下沿。
    #: 官方超框的面板一直包到版权行上方，把 ATK·DEF 数值也包进框内。
    #: ⚠ 新字段一律加在末尾：旧代码用位置参数构造 FullArtPlan。
    panel_bottom: Optional[float] = None
    #: 出血类档位（art_bleed / full_bleed / pendulum_full）：类型行/卡号/密码压在
    #: 插画上 → 绘制时按底图明暗自适应墨色与描边，保证可读。
    contrast_text: bool = False

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "art_rect": tuple(round(v, 2) for v in self.art_rect),
            "panel_opacity": round(self.panel_opacity, 3),
            "name_stroke": round(self.name_stroke, 2),
            "fade_px": round(self.fade_px, 2),
            "restore_regions": list(self.restore_regions),
            "clip_bottom": (round(self.clip_bottom, 2) if self.clip_bottom is not None else None),
            "frame_alpha": round(self.frame_alpha, 3),
            "subject_scale": round(self.subject_scale, 3),
            "subject_offset_y": round(self.subject_offset_y, 3),
            "order": list(self.order),
            "notes": self.notes,
            "panel_top": (round(self.panel_top, 2) if self.panel_top is not None else None),
            "panel_bottom": (round(self.panel_bottom, 2)
                             if self.panel_bottom is not None else None),
            "panel_border": self.panel_border,
            "panel_shadow": self.panel_shadow,
            "hide_password": self.hide_password,
            "code_above_panel": self.code_above_panel,
            "name_fill": list(self.name_fill) if self.name_fill is not None else None,
            "type_label_rect": (tuple(round(v, 2) for v in self.type_label_rect)
                                if self.type_label_rect is not None else None),
            "type_label_dark": self.type_label_dark,
            "contrast_text": self.contrast_text,
        }


def supports(mode: str, frame: str = "") -> bool:
    """该卡种是否支持该出框档位。灵摆出框只对灵摆卡有效；技能卡不支持。"""
    if mode not in MODES:
        return False
    if frame == "skill":
        return False
    if mode == "pendulum_full" and "pendulum" not in frame:
        return False
    # 官方超框目前没有灵摆参考；灵摆仍走「灵摆出框」DIY 档
    if mode == "overframe" and "pendulum" in frame:
        return False
    return True


def plan(mode: str, frame_obj: G.Frame, spec: CardSpec,
         art_size: tuple[int, int], opts: Optional[FullArtOptions] = None) -> FullArtPlan:
    """计算某出框档位的几何与参数。

    ``art_size`` 是插画的像素尺寸，用于在 cover 语义下推算出溢出后的矩形。
    """
    opts = opts or (spec.render.fullart if spec.render else FullArtOptions())
    mode = mode if mode in MODES else "none"
    defaults = G.FULLART_DEFAULTS.get(mode, G.FULLART_DEFAULTS["none"])
    pendulum = "pendulum" in spec.frame

    bt = opts.bleed_top if opts.bleed_top else defaults["bleed_top"]
    bb = opts.bleed_bottom if opts.bleed_bottom else defaults["bleed_bottom"]
    panel_op = opts.panel_opacity if opts.panel_opacity else defaults["panel_opacity"]
    fade = opts.fade_px if opts.fade_px else defaults["fade_px"]

    # 标准插画窗
    win_key = G.PENDULUM_ART_KEY if pendulum else G.STANDARD_ART_KEY
    wx, wy, ww, wh = frame_obj.rect(win_key)

    if mode == "none":
        return FullArtPlan("none", (wx, wy, ww, wh), 1.0, 0.0, 0.0, (), None, 1.0,
                           1.0, 0.0, list(DRAW_ORDER["none"]))

    if mode == "overframe" and ("pendulum" in spec.frame or spec.frame == "skill"):
        # 官方暂无灵摆/技能超框参考：回退标准，避免把灵摆面板叠坏
        return FullArtPlan(
            mode="none", art_rect=(wx, wy, ww, wh), panel_opacity=1.0,
            name_stroke=0.0, fade_px=0.0, restore_regions=(),
            clip_bottom=None, frame_alpha=1.0, subject_scale=1.0,
            subject_offset_y=0.0, order=list(DRAW_ORDER["none"]),
            notes="官方超框暂无灵摆/技能参考 → 回退标准",
        )

    if mode == "art_over":
        # 旧 DIY「超框」档并入官方超框（2026-10-27 验收通过）：历史卡不静默变样，
        # 直接按官方几何渲染，notes 里写明迁移。灵摆/技能仍走回退。
        p = plan("overframe", frame_obj, spec, art_size, opts)
        if p.mode == "overframe":
            p.notes = "旧「超框」档已并入官方超框；本卡按官方几何渲染"
        else:
            p.notes = "旧「超框」档已并入官方超框；" + p.notes
        return p

    if mode == "overframe":
        # 官方超框：插画铺满**内框整片**（外框由底图保留），
        # 下方在版权表记处截断；名/星/属性、面板、文本全部后画。
        ix, iy, iw, ih = frame_obj.rect("frame_inset")
        cx, cy = frame_obj.point("copyright")
        clip_bottom = min(float(frame_obj.height), cy - frame_obj.px(6, "y"))
        bottom = min(iy + ih, clip_bottom)
        rect = (ix, iy, iw, max(1.0, bottom - iy))
        # 类型行按**官方样张**处理：面板上沿只比类型行高 ~21px（官方 18px@702 折算），
        # 类型行紧贴正文上方（间隙 ~7px），用面板同款深色墨。怪物用 type_line、
        # 魔陷用 st_label（OCG 官方把卡种印在类型行右侧，不是卡名下方）。
        box = frame_obj.rect("text_box" if spec.is_monster else "text_box_st")
        row = frame_obj.rect("type_line" if spec.is_monster else "st_label")
        il, _it, ir, _ib = G.text_inset(spec.render.lang_text)
        body_l = box[0] + frame_obj.px(il, "x")
        body_r = box[0] + box[2] - frame_obj.px(ir, "x")
        # 正文首行墨迹顶 ≈ 文本框顶 + 首行留白（经验 11.5px@813）；
        # 类型行 rect 的墨迹顶还要再往下 ~11px（字体自带行距），所以整体再提 7px。
        row_y = box[1] - frame_obj.px(33, "y")
        # 面板上沿：官方「面板边 → 类型行墨迹」= 18px@702（折算 21px@813）。
        # 类型行 rect 顶到墨迹还有 ~4px，所以 rect 上方留 17px。
        panel_top = box[1] - frame_obj.px(50, "y")
        if spec.is_monster:
            label_rect = (body_l, row_y, max(1.0, body_r - body_l), row[3])
        else:
            label_rect = (body_r - row[2], row_y, row[2], row[3])
        notes = ("官方超框：插画铺满内框、外框保留；卡名/星级/属性浮于画上；"
                 "面板半透明带金边与投影、上沿只比类型行高约 21px；"
                 "类型行贴正文上方用面板深色墨；密码隐藏；卡号在面板上沿外")
        if pendulum:
            notes += "；官方暂无灵摆超框参考，此档沿用同一内框几何"
        return FullArtPlan(
            mode="overframe", art_rect=rect, panel_opacity=0.88,
            name_stroke=4.0, fade_px=0.0, restore_regions=(),
            clip_bottom=clip_bottom, frame_alpha=1.0,
            subject_scale=1.0, subject_offset_y=0.0,
            order=list(DRAW_ORDER["overframe"]), notes=notes,
            panel_top=panel_top, panel_border=True, panel_shadow=True,
            panel_bottom=cy - frame_obj.px(20, "y"),
            hide_password=True, code_above_panel=True,
            name_fill=(255, 255, 255),
            type_label_rect=label_rect,
            type_label_dark=True,
        )

    if mode == "subject_bleed":
        # 背景**不**出血：art_rect 就是标准窗；溢出量全部体现在主体层的缩放与上移上
        d = G.FULLART_DEFAULTS["subject_bleed"]
        ssc = float(getattr(opts, "subject_scale", 0.0) or d["subject_scale"])
        soy = float(getattr(opts, "subject_offset_y", 0.0) or d["subject_offset_y"])
        return FullArtPlan(
            mode="subject_bleed", art_rect=(wx, wy, ww, wh), panel_opacity=1.0,
            name_stroke=opts.name_stroke or d.get("name_stroke", 0.0), fade_px=0.0,
            restore_regions=_RESTORE_REGIONS["subject_bleed"], clip_bottom=None,
            frame_alpha=1.0, subject_scale=max(1.0, ssc), subject_offset_y=soy,
            order=list(DRAW_ORDER["subject_bleed"]),
            notes="背景严格留在卡图窗内；只有主体层放大并压出窗沿，卡名条与类型行回贴")

    if mode == "full_bleed":
        # 全画：插画铺满**整卡**（含外框），卡框以低不透明度叠回 —— 旧版 art_rect
        # 仍框在内框里，观感与出血档几乎一样，没有兑现「铺满整卡」的档位承诺。
        # 正文/类型行压在画上，用自适应对比保证可读。
        return FullArtPlan(
            mode="full_bleed", art_rect=(0.0, 0.0, float(frame_obj.width),
                                         float(frame_obj.height)),
            panel_opacity=panel_op, name_stroke=opts.name_stroke or 2.4, fade_px=0.0,
            restore_regions=_RESTORE_REGIONS["full_bleed"], clip_bottom=None,
            frame_alpha=0.55, contrast_text=True,
            order=list(DRAW_ORDER["full_bleed"]),
            notes="插画铺满整卡（含外框），卡框以 55% 透明度叠回；类型行/卡号自适应对比")

    # 版权行以上为插画下边界（官方：版权表记处截断）
    cx, cy = frame_obj.point("copyright")
    clip_bottom = min(frame_obj.height, cy - frame_obj.px(6, "y"))

    # 向上溢出会吃掉等级星行与卡名条下沿
    top = wy - wh * bt
    bottom = wy + wh + wh * bb
    top = max(frame_obj.px(4, "y"), top)
    bottom = min(clip_bottom, bottom)

    # 横向：出框时轻微放大，避免两侧出现空框
    pad_x = ww * 0.018
    left = max(0.0, wx - pad_x)
    right = min(float(frame_obj.width), wx + ww + pad_x)

    rect = (left, top, right - left, bottom - top)
    stroke = opts.name_stroke or 0.0

    # 怪物没有卡种标签，回贴 st_label 只会留下一块空色块（2026-10-27 实测）；
    # 魔陷才需要把标签条贴回来。
    restore = _RESTORE_REGIONS.get(mode, ())
    if spec.is_monster:
        restore = tuple(rr for rr in restore if rr != "st_label")

    notes = {
        "art_bleed": "插画溢出卡图窗并压住类型行；文本框半透明；版权行截断",
        "pendulum_full": "灵摆双区分别溢出，左右刻度从原卡框回贴",
    }.get(mode, "")

    return FullArtPlan(
        mode=mode, art_rect=rect, panel_opacity=panel_op, name_stroke=stroke,
        fade_px=fade, restore_regions=restore,
        clip_bottom=clip_bottom, frame_alpha=1.0, contrast_text=True,
        order=list(DRAW_ORDER.get(mode, DRAW_ORDER["none"])), notes=notes,
    )


# ══════════════════════════════════════════════════════════════════════
#  合成
# ══════════════════════════════════════════════════════════════════════
def _fit_cover(art: Image.Image, w: int, h: int, *, offset_y: float = 0.0,
               scale: float = 1.0) -> Image.Image:
    """按 cover 语义填满目标矩形（超出部分居中裁掉），支持纵向微调与缩放。"""
    art = art.convert("RGBA")
    if art.width == 0 or art.height == 0:
        return Image.new("RGBA", (w, h), (0, 0, 0, 0))
    k = max(w / art.width, h / art.height) * max(0.05, scale)
    nw, nh = max(1, int(round(art.width * k))), max(1, int(round(art.height * k)))
    art = art.resize((nw, nh), Image.LANCZOS)
    left = (nw - w) // 2
    top = (nh - h) // 2 + int(round((nh - h) / 2 * 0 + offset_y * (nh - h) * 0.5))
    top = max(0, min(nh - h, top))
    return art.crop((left, top, left + w, top + h))


def _fade_bottom(layer: Image.Image, fade_px: float) -> Image.Image:
    """插画下缘线性渐隐到透明。"""
    if fade_px <= 0:
        return layer
    f = int(min(fade_px, layer.height * 0.6))
    mask = Image.new("L", layer.size, 255)
    d = ImageDraw.Draw(mask)
    for i in range(f):
        v = int(255 * (i / max(1, f)))
        d.line([(0, layer.height - f + i), (layer.width, layer.height - f + i)], fill=v)
    layer = layer.copy()
    layer.putalpha(ImageChops.multiply(layer.getchannel("A"), mask))
    return layer


def compose_artwork(canvas: Image.Image, art: Optional[Image.Image], frame_obj: G.Frame,
                    spec: CardSpec, plan_: FullArtPlan, *,
                    art_fit: str = "cover", offset_y: float = 0.0,
                    scale: float = 1.0, ring: float = 0.0,
                    clip_bottom: Optional[float] = None) -> None:
    """把插画按方案贴进 ``canvas``（就地修改）。

    标准模式下额外支持 ``ring``（画窗外的线性变暗暗环，还原参考 DIY 卡观感）。
    """
    if art is None:
        return
    x, y, w, h = [int(round(v)) for v in plan_.art_rect]
    if w <= 0 or h <= 0:
        return
    w = min(w, canvas.width - max(0, x))
    h = min(h, canvas.height - max(0, y))
    x = max(0, x); y = max(0, y)

    if art_fit == "contain":
        a = art.convert("RGBA")
        k = min(w / a.width, h / a.height) * max(0.05, scale)
        a = a.resize((max(1, int(a.width * k)), max(1, int(a.height * k))), Image.LANCZOS)
        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        layer.alpha_composite(a, ((w - a.width) // 2, (h - a.height) // 2))
    else:
        layer = _fit_cover(art, w, h, offset_y=offset_y, scale=scale)

    # 下缘渐隐 / 版权行截断
    layer = _fade_bottom(layer, plan_.fade_px)
    if clip_bottom is not None:
        cut = int(round(clip_bottom)) - y
        if 0 <= cut < layer.height:
            t = layer.crop((0, 0, layer.width, cut))
            m = t.getchannel("A").copy()
            ImageDraw.Draw(m).rectangle(
                [0, max(0, t.height - int(frame_obj.px(3, "y"))), t.width, t.height], fill=0)
            t.putalpha(m)
            layer = t

    canvas.alpha_composite(layer, (x, y))

    # 画窗暗环（只在标准档生效，出框时插画已越出画窗，画环反而难看）
    if ring > 0 and plan_.mode == "none":
        draw_ring(canvas, frame_obj, ring)


def compose_layers(canvas: Image.Image, bg: Optional[Image.Image],
                   subject: Optional[Image.Image], frame_obj: G.Frame,
                   spec: CardSpec, plan_: FullArtPlan, *,
                   art_fit: str = "cover", offset_y: float = 0.0,
                   scale: float = 1.0) -> None:
    """**分层卡图合成**：背景严格裁进卡图窗，主体放大后压出窗沿。

    与 :func:`compose_artwork` 的区别就是这一档需要的两件事：

    * 背景永远不出窗 —— 出框的是主体，不是环境；
    * 主体带 alpha，按 ``plan_.subject_scale`` 以**窗高为基准**放大，
      **脚底对齐窗下沿**再按 ``subject_offset_y`` 上移，于是头/武器/翅膀
      越出窗沿压到卡框上，而卡名条与类型行随后回贴保证可读。

    ``subject=None`` 时退化成只有背景（等于标准档），不会画坏；
    ``bg=None`` 时直接不画。缩放基准与 ``run._flatten_layers`` 一致，
    所以 ``subject_scale=1.0`` 时压平件与分层件看起来相同。
    """
    if bg is None:
        return
    compose_artwork(canvas, bg, frame_obj, spec, plan_, art_fit=art_fit,
                    offset_y=offset_y, scale=scale)
    if subject is None or plan_.mode != "subject_bleed":
        return
    x, y, w, h = plan_.art_rect
    sub = subject.convert("RGBA")
    if sub.width <= 0 or sub.height <= 0:
        return
    k = (h * max(0.2, plan_.subject_scale)) / sub.height
    sw, sh = max(1, int(round(sub.width * k))), max(1, int(round(sub.height * k)))
    sx = int(round(x + (w - sw) / 2))
    sy = int(round(y + h - sh + plan_.subject_offset_y * h))

    # 溢出要有上限：头/武器最多顶到卡名栏上沿，不能越过卡框外沿，
    # 否则主体会"捅破"整张卡（打印与游戏内都会露馅）。按脚底锚点回推倍率。
    try:
        top_limit = frame_obj.rect("title_bevel")[1] + frame_obj.px(4, "y")
    except Exception:
        top_limit = frame_obj.px(4, "y")
    if sy < top_limit:
        bottom = sy + sh                          # 脚底位置保持不变
        sh = max(1, int(round(bottom - top_limit)))
        sw = max(1, int(round(sub.width * (sh / max(1, sub.height)))))
        sy = int(round(bottom - sh))
        sx = int(round(x + (w - sw) / 2))

    sub = sub.resize((sw, sh), Image.LANCZOS)
    canvas.alpha_composite(sub, (sx, sy))


def draw_ring(canvas: Image.Image, frame_obj: G.Frame, width: float,
              alpha: float = G.ART_RING_ALPHA) -> None:
    """插画窗外侧的线性变暗暗环（``width`` 为 REF 系像素，0 = 关闭）。"""
    if width <= 0:
        return
    x, y, w, h = frame_obj.rect(G.STANDARD_ART_KEY)
    layers = max(1, int(round(frame_obj.px(width))))
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    for i in range(layers):
        t = 1.0 - i / layers                 # 越靠外越淡
        a = int(round(alpha * 255 * (t ** 1.15)))
        if a <= 0:
            continue
        d.rectangle([x - i - 1, y - i - 1, x + w + i, y + h + i], outline=(0, 0, 0, a))
    canvas.alpha_composite(overlay)


def restore(canvas: Image.Image, frame_img: Optional[Image.Image], frame_obj: G.Frame,
            regions) -> None:
    """从原卡框回贴指定区域（出框后仍要保证框体/卡名栏/刻度正常显示）。"""
    if frame_img is None or not regions:
        return
    src = frame_img.convert("RGBA")
    if src.size != canvas.size:
        src = src.resize(canvas.size, Image.LANCZOS)
    for name in regions:
        try:
            x, y, w, h = [int(round(v)) for v in frame_obj.rect(name)]
        except Exception:
            continue
        x = max(0, x); y = max(0, y)
        w = min(w, canvas.width - x); h = min(h, canvas.height - y)
        if w <= 0 or h <= 0:
            continue
        canvas.paste(src.crop((x, y, x + w, y + h)), (x, y))


def ghost_frame(frame_img: Optional[Image.Image], frame_obj: G.Frame,
                alpha: float) -> Optional[Image.Image]:
    """把卡框整体降到给定不透明度（全画档用）。"""
    if frame_img is None:
        return None
    f = frame_img.convert("RGBA").copy()
    a = f.getchannel("A").point(lambda v: int(v * max(0.0, min(1.0, alpha))))
    f.putalpha(a)
    return f


def capabilities() -> dict:
    return {
        "modes": list(MODES),
        "official_name": {"ja": "オーバーフレーム", "en": "Extended Art"},
        "community_name": {"zh_cn": "出框 / 全画 / 超框", "en": "Full Art（非官方俚语）"},
        "orthogonal_to_rarity": True,
        "defaults": {k: dict(v) for k, v in G.FULLART_DEFAULTS.items()},
        "restore_regions": {k: list(v) for k, v in _RESTORE_REGIONS.items()},
    }
