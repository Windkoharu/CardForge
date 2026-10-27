"""卡面合成编排 —— 三段式管线，**只在最后降采样一次**。

管线
----
::

    [1] 基座 base     官方卡框整图（1394×2031）或程序化框体
    [2] 内容 content  插画（含出框溢出）→ 星级/属性/箭头/刻度 → 卡名 → 文本 → 数值 → 元信息
    [3] 完成 finish   罕贵覆膜（分层）→ 激光标/纪念标 → 版权 → 出血 → 单次降采样

为什么内部固定用 1394×2031
--------------------------
旧版把插画先缩到目标尺寸再合成，多次重采样导致发糊。新版**全程在卡框原生分辨率上作业**，
插画按 native 尺寸 cover 填充，最后一次性 LANCZOS 降到目标尺寸——细节保留最好。

跨平台降级
----------
* 无 Pillow            → :func:`capabilities` 报告 L1 不可用，调用方走浏览器 SVG 预览
* 无官方卡框素材      → 自动改用程序化基座（配色取自 ``palettes``）
* 无字体              → 文字层跳过并在返回的 report 里记 ``missing_fonts``
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from PIL import Image, ImageDraw, ImageFilter

from ..core import errors
from ..core.models import CardSpec, RenderOptions
from . import fullart as FA
from . import frameprobe as FP
from . import geometry as G
from . import layers as L
from . import rarities as R
from . import bezel as BZ
from .palettes import darken, lighten, name_is_white, palette

#: 内部作业分辨率（= 官方卡框素材原生尺寸）
WORK_SIZE = G.FRAME_NATIVE


# ══════════════════════════════════════════════════════════════════════
#  能力探测
# ══════════════════════════════════════════════════════════════════════
def _try_import():
    """惰性导入可选依赖，缺失时降级而不是崩溃。"""
    out = {"assets": None, "fonts": None, "text": None}
    try:
        from . import assets as A
        out["assets"] = A.library()
    except Exception:
        pass
    try:
        from . import fonts as F
        out["fonts"] = F
    except Exception:
        pass
    try:
        from . import text as T
        out["text"] = T
    except Exception:
        pass
    return out


def capabilities() -> dict:
    """渲染能力与降级原因（doctor / UI 用）。"""
    mods = _try_import()
    caps = {
        "L1_render": False, "pillow": False, "official_frames": False,
        "fonts": False, "text_engine": False, "numpy": R.HAS_NUMPY,
        "frames": [], "missing_assets": [], "levels": {},
    }
    try:
        import PIL  # noqa: F401
        caps["pillow"] = True
    except Exception as e:
        caps["reason"] = f"缺少 Pillow：{e}"
        return caps

    if mods["assets"] is not None:
        try:
            av = mods["assets"].availability()
            caps["assets"] = av
            caps["missing_assets"] = sorted(mods["assets"].missing())[:20]
            # availability() 的真实结构是 categories.frame.{present,total,missing}
            # —— 之前按 av["frame"] 取，永远取不到，导致界面谎报"没有官方卡框"
            cat = (av.get("categories") or {}).get("frame") or av.get("frame") or {}
            present = cat.get("present", 0) if isinstance(cat, dict) else 0
            total = cat.get("total", 0) if isinstance(cat, dict) else 0
            caps["official_frames"] = bool(present)
            caps["n_official_frames"] = int(present or 0)
            caps["n_official_frames_total"] = int(total or 0)
        except Exception as e:
            caps["assets_error"] = str(e)
    if mods["fonts"] is not None:
        try:
            d = mods["fonts"].diagnose()
            caps["fonts"] = True
            caps["font_diagnose"] = d
        except Exception as e:
            caps["font_error"] = str(e)
    caps["text_engine"] = mods["text"] is not None
    caps["L1_render"] = caps["pillow"]
    caps["levels"] = {
        "L0-data": True,
        "L1-render": caps["pillow"],
        "L2-art": None,     # 由 art 模块填
        "L3-duel": None,    # 由 duel 模块填
    }
    return caps


# ══════════════════════════════════════════════════════════════════════
#  渲染报告
# ══════════════════════════════════════════════════════════════════════
@dataclass
class RenderReport:
    """渲染过程中发生的降级与提示，供 UI 显示与质量门参考。"""
    size: tuple[int, int] = (0, 0)
    work_size: tuple[int, int] = WORK_SIZE
    used_official_frame: bool = False
    text_overflow: bool = False
    text_lines: int = 0
    text_size: int = 0
    missing_fonts: list = field(default_factory=list)
    missing_assets: list = field(default_factory=list)
    fullart: dict = field(default_factory=dict)
    layout: dict = field(default_factory=dict)
    rarity: str = "common"
    bezel: int = 0                     # 卡图窗斜切框带宽（像素，0=没画）
    warnings: list = field(default_factory=list)
    took_ms: int = 0

    def to_dict(self) -> dict:
        return {
            "size": list(self.size), "work_size": list(self.work_size),
            "used_official_frame": self.used_official_frame,
            "text_overflow": self.text_overflow, "text_lines": self.text_lines,
            "text_size": self.text_size, "missing_fonts": self.missing_fonts,
            "missing_assets": self.missing_assets, "fullart": self.fullart,
            "layout": self.layout, "rarity": self.rarity, "bezel": self.bezel,
            "warnings": self.warnings, "took_ms": self.took_ms,
        }


# ══════════════════════════════════════════════════════════════════════
#  基座
# ══════════════════════════════════════════════════════════════════════
def procedural_base(spec: CardSpec, f: G.Frame, pal) -> Image.Image:
    """程序化框体（素材缺失时的回退）。不是"色块"，带斜面、内阴影、光泽与插画窗。"""
    from .palettes import lerp
    w, h = f.width, f.height
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 外框（卡边缘）
    d.rounded_rectangle([0, 0, w, h], radius=f.px(34), fill=darken(pal.frame_bg, 0.42))
    # 主体框
    x, y, bw, bh = f.rect("frame_inset")
    d.rounded_rectangle([x, y, x + bw, y + bh], radius=f.px(24), fill=pal.frame_bg)

    # 卡名条（上亮下暗的斜面）
    tx, ty, tw, th = f.rect("title_bevel")
    d.rounded_rectangle([tx, ty, tx + tw, ty + th], radius=f.px(9),
                        fill=darken(pal.name_bar, 0.10))
    d.rounded_rectangle([tx + 1, ty + 1, tx + tw - 1, ty + th * 0.46],
                        radius=f.px(8), fill=lighten(pal.name_bar, 0.18))

    # 插画窗外框 + 投影
    ax, ay, aw, ah = f.rect(G.PENDULUM_ART_KEY if spec.is_pendulum else G.STANDARD_ART_KEY)
    pad = f.px(9)
    d.rounded_rectangle([ax - pad, ay - pad, ax + aw + pad, ay + ah + pad],
                        radius=f.px(6), fill=darken(pal.frame_bg, 0.55))
    d.rectangle([ax - f.px(3), ay - f.px(3), ax + aw + f.px(3), ay + ah + f.px(3)],
                fill=lighten(pal.hairline, 0.25))

    # 文本面板
    keys = ["pendulum_panel", "pendulum_monster_panel"] if spec.is_pendulum else ["text_panel"]
    for k in keys:
        px_, py_, pw, ph = f.rect(k)
        d.rounded_rectangle([px_, py_, px_ + pw, py_ + ph], radius=f.px(8),
                            fill=pal.text_panel)

    # 分隔线
    sx, sy, sw, sh = f.rect("stats_separator")
    d.rectangle([sx, sy, sx + sw, sy + max(1.0, f.px(1.4))], fill=pal.hairline)

    # 顶部光泽
    gloss = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(gloss)
    gd.rounded_rectangle([x, y, x + bw, y + bh], radius=f.px(24),
                         outline=(255, 255, 255, 46), width=max(1, int(f.px(2))))
    img.alpha_composite(gloss)
    return img


def _frame_base(spec: CardSpec, f: G.Frame, mods: dict, rep: RenderReport,
                pal) -> tuple[Image.Image, Optional[Image.Image]]:
    """取基座。返回 (画布, 原始卡框图或 None)。"""
    fd = spec.frame_def
    frame_img = None
    if mods["assets"] is not None:
        try:
            frame_img = mods["assets"].frame(fd.base, pendulum=spec.is_pendulum)
        except Exception as e:
            rep.warnings.append(f"卡框素材读取失败：{e}")
    if frame_img is not None:
        base = frame_img.convert("RGBA")
        if base.size != (f.width, f.height):
            base = base.resize((f.width, f.height), Image.LANCZOS)
        rep.used_official_frame = True
        return base, frame_img.convert("RGBA")

    rep.warnings.append("未找到官方卡框素材，已回退到程序化框体")
    return procedural_base(spec, f, pal), None


# ══════════════════════════════════════════════════════════════════════
#  主入口
# ══════════════════════════════════════════════════════════════════════
def render_card(spec: CardSpec, art: Optional[Image.Image] = None, *,
                size: str | tuple[int, int] = "native",
                frame_obj: Optional[G.Frame] = None,
                use_official_frame: bool = True,
                return_report: bool = False,
                layers: Optional[dict] = None,
                mods: Optional[dict] = None):
    """渲染一张卡。

    ``size`` 支持 ``"edopro"|"compat"|"share"|"print300"|"print"|"native"`` 或 ``(w, h)``。
    返回 ``PIL.Image``（RGB）；``return_report=True`` 时返回 ``(image, RenderReport)``。

    ``layers`` 给**分层卡图**（``{"background": Image, "subject": Image}``，主体带
    alpha）。只有 ``fullart.mode == "subject_bleed"``（主体出框）时才用得上：
    背景严格裁进卡图窗，主体放大压出窗沿。没给分层会自动回落到 ``art``。
    """
    import time
    t0 = time.perf_counter()
    rep = RenderReport()
    mods = mods or _try_import()

    # 目标尺寸与工作尺寸
    out_size = (G.OUTPUT_SIZES.get(size, G.OUTPUT_SIZES[G.DEFAULT_OUTPUT])
                if isinstance(size, str) else (int(size[0]), int(size[1])))
    rep.size = out_size
    work = G.make_frame(*WORK_SIZE)
    rep.work_size = WORK_SIZE
    f = frame_obj or work

    r: RenderOptions = spec.render or RenderOptions()
    pal = palette(spec.frame, spec.attribute)
    rep.rarity = r.rarity

    # ── 字体回调 ────────────────────────────────────────────────────
    # 必须**按字号记忆化**：Pillow 的 FreeTypeFont 不能跨 size 复用，
    # 而排版引擎的字宽缓存以 ``id(font)`` 为键 —— 每次新建对象会让缓存永远不命中，
    # 长卡文渲染会从 ~0.3s 劣化到 ~45s（实测）。同一字号返回同一个对象即可。
    _font_memo: dict[int, object] = {}
    _font_missing: list[str] = []

    def font_of(px: int):
        px = int(px)
        if px in _font_memo:
            return _font_memo[px]
        f = None
        if mods["fonts"] is not None:
            try:
                f = mods["fonts"].load("sc", px, r.lang_text)
            except Exception as e:
                if len(_font_missing) < 3:
                    _font_missing.append(f"{px}px: {e}")
                f = None
        _font_memo[px] = f
        return f

    # ══ 第 1 段：基座 ══
    if use_official_frame:
        canvas, frame_img = _frame_base(spec, f, mods, rep, pal)
    else:
        canvas, frame_img = procedural_base(spec, f, pal), None
        rep.warnings.append("已按要求跳过官方卡框，使用程序化基座")

    # 用**实测版面**覆盖硬编码几何：15 种卡框的类型行/面板位置各不相同，
    # 实测值能让类型行落在卡框自带的条带里，避免与框体墨迹重影（旧版 44px 错位）。
    if mods["assets"] is not None and frame_img is not None:
        try:
            fd = spec.frame_def
            f.layout = FP.analyze(frame_img, f"{spec.frame}-{fd.base}")
            rep.layout = f.layout.to_dict()
        except Exception as e:
            rep.warnings.append(f"卡框版面实测失败，沿用默认几何：{e}")

    # 出框方案
    fa_plan = FA.plan(r.fullart.mode, f, spec, art.size if art else (0, 0), r.fullart)
    rep.fullart = fa_plan.to_dict()

    # ══ 第 2 段：内容 ══
    order = fa_plan.order
    if "frame_ghost" in order:
        g = FA.ghost_frame(frame_img, f, fa_plan.frame_alpha)
        if g is not None:
            canvas = Image.alpha_composite(canvas, g)

    lay = {k: v for k, v in (layers or {}).items() if v is not None}
    if fa_plan.mode == "subject_bleed" and lay.get("background") is not None:
        FA.compose_layers(canvas, lay["background"], lay.get("subject"), f, spec,
                          fa_plan, art_fit=r.art_fit, offset_y=r.art_offset_y,
                          scale=r.art_scale)
        if lay.get("subject") is None:
            rep.warnings.append("主体出框档需要带 alpha 的主体层，当前只有背景层"
                                "→ 已按「背景填满卡图窗」绘制")
    elif art is not None:
        if fa_plan.mode == "subject_bleed":
            rep.warnings.append("主体出框档需要分层卡图（用「分层出图」重新生成即可）"
                                "→ 已回落到普通出框，画面不会溢出卡图窗")
        FA.compose_artwork(canvas, art, f, spec, fa_plan,
                           art_fit=r.art_fit, offset_y=r.art_offset_y,
                           scale=r.art_scale, ring=r.art_ring,
                           clip_bottom=fa_plan.clip_bottom)
    else:
        rep.warnings.append("未提供插画，卡图窗留空")

    # 官方斜切框 + 过渡：只在插画被窗完整包住时画（出框类由画面破坏窗边界）
    if getattr(r, "bezel", 0.0) and fa_plan.mode == "none" and art is not None:
        try:
            rep.bezel = BZ.draw_art_bezel(canvas, f, spec, pal=pal,
                                          strength=float(r.bezel)).get("band", 0)
        except Exception as e:
            rep.warnings.append(f"斜切框绘制失败（已跳过，不影响成图）：{type(e).__name__}: {e}")

    if "restore" in order:
        FA.restore(canvas, frame_img, f, fa_plan.restore_regions)

    if "panel" in order:
        # 灵摆卡框的中段是空窗，面板必须**无条件**绘制（opacity=1 也要画），
        # 否则下缘会露出纯白横条 —— 这正是旧版 35px 白条的根因。
        if spec.is_pendulum:
            L.draw_pendulum_panels(canvas, f, pal, opacity=fa_plan.panel_opacity)
        else:
            L.draw_text_panel(canvas, f, pal, opacity=fa_plan.panel_opacity,
                              top=fa_plan.panel_top, bottom=fa_plan.panel_bottom,
                              border=fa_plan.panel_border,
                              shadow=fa_plan.panel_shadow)

    # ══ 第 2.5 段：箔在下、油墨在上 ══
    # 官方罕贵的整卡/卡图/文本框箔要铺在**正文墨色之前**，文字保持实墨可读
    # （旧版一次性画在最后，PSER 的整卡闪膜会把文字糊住）。数值/星级/属性
    # 的镀色与卡框边镀仍压在墨上，见第 3 段的 phase="over"。
    if r.rarity and r.rarity != "common":
        canvas = R.apply_rarity(canvas, r.rarity, f, pendulum=spec.is_pendulum,
                                palette=pal, assets=mods["assets"],
                                art_rect=fa_plan.art_rect, phase="under").convert("RGBA")

    # 内容元素
    L.draw_badge(canvas, spec, f, assets=mods["assets"])
    L.draw_stars(canvas, spec, f, font_of, pal, assets=mods["assets"])
    L.draw_link_arrows(canvas, spec, f, assets=mods["assets"])
    L.draw_pendulum_scales(canvas, spec, f, font_of, pal)

    name_fx = R.name_effect(r.rarity)
    L.draw_name(canvas, spec, f, font_of, pal, assets=mods["assets"],
                name_fx=name_fx, stroke=fa_plan.name_stroke,
                fill=fa_plan.name_fill)

    L.draw_type_line(canvas, spec, f, font_of, pal, lang=r.lang_text,
                     pendulum=spec.is_pendulum,
                     label_rect=fa_plan.type_label_rect,
                     fill=(pal.type_ink if fa_plan.type_label_dark else None),
                     stroke=0.0,
                     size_ref=(G.FONT_SIZE["type_line"]
                               if (fa_plan.mode == "overframe" and not spec.is_monster)
                               else None),
                     contrast=fa_plan.contrast_text)

    if mods["text"] is not None:
        if spec.frame == "normal" and spec.flavor_in(r.lang_flavor):
            L.draw_flavor(canvas, spec, f, font_of, pal, lang=r.lang_flavor)
        elif spec.is_pendulum:
            # 灵摆卡是**两个独立文本框**：上半灵摆效果、下半怪兽效果
            pend = spec.pendulum_text_in(r.lang_text)
            if pend.strip():
                info = L.draw_effect_text(canvas, spec, f, font_of, pal,
                                          lang=r.lang_text, pendulum=True,
                                          box_key="pendulum_text",
                                          uniform_ink=(fa_plan.mode == "overframe"))
                rep.text_lines = info.get("lines", 0)
                rep.text_size = info.get("size", 0)
                rep.text_overflow = bool(info.get("overflow"))
            body = spec.text_in(r.lang_text)
            if body.strip():
                info2 = L.draw_effect_text(canvas, spec, f, font_of, pal,
                                           lang=r.lang_text, pendulum=False,
                                           box_key="pendulum_monster_text",
                                           uniform_ink=(fa_plan.mode == "overframe"))
                rep.text_lines += info2.get("lines", 0)
                rep.text_size = rep.text_size or info2.get("size", 0)
                rep.text_overflow = rep.text_overflow or bool(info2.get("overflow"))
            if rep.text_overflow:
                rep.warnings.append("卡文过长，已压到最小字号仍溢出一行以内，建议精简")
        else:
            info = L.draw_effect_text(canvas, spec, f, font_of, pal,
                                      lang=r.lang_text, pendulum=False,
                                      uniform_ink=(fa_plan.mode == "overframe"))
            rep.text_lines = info.get("lines", 0)
            rep.text_size = info.get("size", 0)
            rep.text_overflow = bool(info.get("overflow"))
            if rep.text_overflow:
                rep.warnings.append("卡文过长，已压到最小字号仍溢出一行以内，建议精简")
    else:
        rep.warnings.append("排版引擎不可用，已跳过卡文绘制")

    L.draw_stats(canvas, spec, f, font_of, pal)

    # ══ 第 3 段：完成 ══
    if r.rarity and r.rarity != "common":
        canvas = R.apply_rarity(canvas, r.rarity, f, pendulum=spec.is_pendulum,
                               palette=pal, assets=mods["assets"],
                               art_rect=fa_plan.art_rect, phase="over").convert("RGBA")

    L.draw_meta(canvas, spec, f, font_of, pal, assets=mods["assets"],
                overframe=(fa_plan.mode == "overframe"),
                panel_top=fa_plan.panel_top,
                contrast=fa_plan.contrast_text)

    # 单次降采样
    out = canvas.convert("RGB")
    if out.size != out_size:
        out = out.resize(out_size, Image.LANCZOS)

    rep.took_ms = int((time.perf_counter() - t0) * 1000)
    rep.missing_fonts = _font_missing
    return (out, rep) if return_report else out


def render_stages(spec: CardSpec, art: Optional[Image.Image] = None,
                  size: str | tuple[int, int] = "share") -> dict:
    """逐层输出，便于排障与做"过程可视化"。"""
    mods = _try_import()
    stages: dict[str, Image.Image] = {}
    f = G.make_frame(*WORK_SIZE)
    pal = palette(spec.frame, spec.attribute)
    rep = RenderReport()

    base, frame_img = _frame_base(spec, f, mods, rep, pal)
    stages["01_base"] = base.convert("RGB").copy()

    plan_ = FA.plan(spec.render.fullart.mode, f, spec, art.size if art else (0, 0),
                    spec.render.fullart)
    c = base.copy()
    if art is not None:
        FA.compose_artwork(c, art, f, spec, plan_, ring=spec.render.art_ring,
                           clip_bottom=plan_.clip_bottom)
    stages["02_artwork"] = c.convert("RGB").copy()

    if plan_.panel_opacity < 0.999 or plan_.panel_border:
        L.draw_text_panel(c, f, pal, opacity=plan_.panel_opacity,
                          pendulum=spec.is_pendulum,
                          top=plan_.panel_top, bottom=plan_.panel_bottom,
                          border=plan_.panel_border, shadow=plan_.panel_shadow)
    if spec.render.rarity != "common":
        # 箔在下：整卡/卡图/文本框箔铺在正文墨色之前（与 render_card 管线一致）
        c = R.apply_rarity(c, spec.render.rarity, f, pendulum=spec.is_pendulum,
                           assets=mods["assets"], art_rect=plan_.art_rect,
                           phase="under").convert("RGBA")
    stages["03_panel"] = c.convert("RGB").copy()

    _memo: dict[int, object] = {}

    def font_of(px):
        px = int(px)
        if px in _memo:
            return _memo[px]
        f = None
        if mods["fonts"] is not None:
            try:
                f = mods["fonts"].load("sc", px, spec.render.lang_text)
            except Exception:
                f = None
        _memo[px] = f
        return f

    L.draw_badge(c, spec, f, assets=mods["assets"])
    L.draw_stars(c, spec, f, font_of, pal, assets=mods["assets"])
    L.draw_link_arrows(c, spec, f, assets=mods["assets"])
    L.draw_pendulum_scales(c, spec, f, font_of, pal)
    L.draw_name(c, spec, f, font_of, pal, assets=mods["assets"],
                name_fx=R.name_effect(spec.render.rarity))
    L.draw_type_line(c, spec, f, font_of, pal, lang=spec.render.lang_text,
                     pendulum=spec.is_pendulum)
    if mods["text"] is not None:
        L.draw_effect_text(c, spec, f, font_of, pal, lang=spec.render.lang_text,
                           pendulum=spec.is_pendulum,
                           uniform_ink=(plan_.mode == "overframe"))
    L.draw_stats(c, spec, f, font_of, pal)
    stages["04_text"] = c.convert("RGB").copy()

    if spec.render.rarity != "common":
        c = R.apply_rarity(c, spec.render.rarity, f, pendulum=spec.is_pendulum,
                           assets=mods["assets"], art_rect=plan_.art_rect,
                           phase="over").convert("RGBA")
        stages["05_rarity"] = c.convert("RGB").copy()

    L.draw_meta(c, spec, f, font_of, pal, assets=mods["assets"])
    stages["06_final"] = c.convert("RGB").copy()

    out_size = (G.OUTPUT_SIZES.get(size, G.OUTPUT_SIZES["share"])
                if isinstance(size, str) else tuple(size))
    if out_size != WORK_SIZE:
        for k in stages:
            stages[k] = stages[k].resize(out_size, Image.LANCZOS)
    return stages


# ══════════════════════════════════════════════════════════════════════
#  导出
# ══════════════════════════════════════════════════════════════════════
def export_card(spec: CardSpec, art: Optional[Image.Image], out_dir,
                *, sizes=("edopro",), fmt: str = "jpg", quality: int = 92,
                name: Optional[str] = None, layers: Optional[dict] = None) -> list[str]:
    """导出成品卡图。默认写 ``<out_dir>/<id>.jpg``（EDOPro 直接可用）。

    ``layers`` 是分层卡图（``{"background": Image, "subject": Image}``），
    只有 ``fullart.mode == "subject_bleed"`` 时用得上。
    """
    from pathlib import Path
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for s in sizes:
        img = render_card(spec, art, size=s, layers=layers)
        if name:
            fn = f"{name}_{s}.{fmt}"
        else:
            fn = f"{spec.id}.{fmt}" if s in ("edopro", "compat") else f"{spec.id}_{s}.{fmt}"
        p = out_dir / fn
        if fmt.lower() in ("jpg", "jpeg"):
            img.save(p, "JPEG", quality=quality, subsampling=1, optimize=True)
        elif fmt.lower() == "webp":
            img.save(p, "WEBP", quality=quality, method=5)
        else:
            img.save(p, "PNG", optimize=True)
        written.append(str(p))
    return written


def preview_png(spec: CardSpec, art: Optional[Image.Image] = None,
                width: int = 480, **kw) -> bytes:
    """快速预览（JPEG 字节，给 HTTP 接口用）。"""
    import io
    h = max(1, int(round(width * G.REF[1] / G.REF[0])))
    img = render_card(spec, art, size=(width, h), **kw)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88, subsampling=1)
    return buf.getvalue()


def render_svg(spec: CardSpec, art_uri: Optional[str] = None, *,
               width: int = 813, **kw) -> str:
    """生成**浏览器端矢量卡面**（零延迟实时预览，与 Pillow 通道共用版面数值）。

    不追求 100% 还原卡框质感，但版面、文字排布、配色、罕贵指示与 PNG 通道一致。
    插画以 ``art_uri``（data URI 或 URL）嵌入。
    """
    r = spec.render or RenderOptions()
    w = int(width)
    h = int(round(w * G.REF[1] / G.REF[0]))
    f = G.make_frame(w, h)
    pal = palette(spec.frame, spec.attribute)
    hexs = lambda c: "#%02X%02X%02X" % tuple(c)  # noqa: E731

    def rect(name):
        x, y, rw, rh = f.rect(name)
        return f'x="{x:.1f}" y="{y:.1f}" width="{rw:.1f}" height="{rh:.1f}"'

    def anchor_pt(name):
        x, y = f.point(name)
        return x, y

    art_key = G.PENDULUM_ART_KEY if spec.is_pendulum else G.STANDARD_ART_KEY
    ax, ay, aw, ah = f.rect(art_key)
    clip_id = "artclip"

    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" font-family="Noto Serif SC, Source Han Serif SC, '
        f'Microsoft YaHei, sans-serif">')
    parts.append(f'<defs><clipPath id="{clip_id}">'
                 f'<rect x="{ax:.1f}" y="{ay:.1f}" width="{aw:.1f}" height="{ah:.1f}" '
                 f'rx="{f.px(6):.1f}"/></clipPath></defs>')
    # 卡框底
    parts.append(f'<rect width="{w}" height="{h}" rx="{f.px(34):.1f}" '
                 f'fill="{hexs(pal.frame_bg)}"/>')
    x, y, bw, bh = f.rect("frame_inset")
    parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{bh:.1f}" '
                 f'rx="{f.px(24):.1f}" fill="{hexs(pal.frame_bg)}" '
                 f'stroke="rgba(0,0,0,.35)" stroke-width="{f.px(2):.1f}"/>')
    # 卡名条
    tx, ty, tw, th = f.rect("title_bevel")
    parts.append(f'<rect x="{tx:.1f}" y="{ty:.1f}" width="{tw:.1f}" height="{th:.1f}" '
                 f'rx="{f.px(9):.1f}" fill="{hexs(pal.name_bar)}"/>')
    # 插画窗
    parts.append(f'<rect x="{ax - f.px(9):.1f}" y="{ay - f.px(9):.1f}" '
                 f'width="{aw + f.px(18):.1f}" height="{ah + f.px(18):.1f}" '
                 f'rx="{f.px(6):.1f}" fill="{hexs(darken(pal.frame_bg, 0.55))}"/>')
    if art_uri:
        parts.append(f'<image href="{art_uri}" x="{ax:.1f}" y="{ay:.1f}" '
                     f'width="{aw:.1f}" height="{ah:.1f}" preserveAspectRatio="xMidYMid slice" '
                     f'clip-path="url(#{clip_id})"/>')
    else:
        parts.append(f'<rect x="{ax:.1f}" y="{ay:.1f}" width="{aw:.1f}" height="{ah:.1f}" '
                     f'fill="rgba(0,0,0,.10)"/>')
    # 官方斜切框 + 过渡（矢量近似：四条 45° 斜接边 + 暗线 + 发丝）
    # ax/ay/aw/ah 已经按灵摆合并窗与普通窗选过 key，两种框都用它
    if getattr(r, "bezel", 0.0):
        parts.append(BZ.svg_bezel((ax, ay, aw, ah), f.px(BZ.BEZEL["band"]),
                                  scale=float(r.bezel), pal=pal))
    # 文本框
    tpx, tpy, tpw, tph = f.rect("pendulum_panel" if spec.is_pendulum else "text_panel")
    parts.append(f'<rect x="{tpx:.1f}" y="{tpy:.1f}" width="{tpw:.1f}" height="{tph:.1f}" '
                 f'rx="{f.px(8):.1f}" fill="{hexs(pal.text_panel)}"/>')
    if spec.is_pendulum:
        mpx, mpy, mpw, mph = f.rect("pendulum_monster_panel")
        parts.append(f'<rect x="{mpx:.1f}" y="{mpy:.1f}" width="{mpw:.1f}" '
                     f'height="{mph:.1f}" rx="{f.px(8):.1f}" fill="{hexs(pal.text_panel)}"/>')
    # 卡名
    nx, ny, nw, nh = f.rect("title_bevel")
    name_col = "#FFFFFF" if name_is_white(spec.frame) else hexs(pal.name_ink)
    parts.append(f'<text x="{nx + f.px(14):.1f}" y="{ny + nh * 0.68:.1f}" '
                 f'font-size="{f.font(G.FONT_SIZE["name"]) * 0.82:.1f}" '
                 f'fill="{name_col}" letter-spacing="0.5">{_esc(spec.name_in(r.lang_name))}</text>')
    # 类型行
    tl = L.type_line_text(spec, r.lang_text) if spec.is_monster else L.st_label_text(spec, r.lang_text)
    if tl:
        key = "pendulum_type_line" if spec.is_pendulum else (
            "type_line" if spec.is_monster else "st_label")
        lx, ly, lw, lh = f.rect(key)
        tx2 = lx if spec.is_monster else lx + lw
        anc = "start" if spec.is_monster else "end"
        parts.append(f'<text x="{tx2:.1f}" y="{ly + lh * 0.78:.1f}" text-anchor="{anc}" '
                     f'font-size="{f.font(G.FONT_SIZE["type_line"]) * 0.9:.1f}" '
                     f'fill="{hexs(pal.type_ink)}">{_esc(tl)}</text>')
    # 效果文本（按行切分，避免依赖浏览器的自动换行与后端不一致）
    body = spec.text_in(r.lang_text)
    if body:
        bx, by, bw2, bh2 = f.rect(
            "pendulum_text" if spec.is_pendulum else ("text_box" if spec.is_monster else "text_box_st"))
        fs = f.font(G.FONT_SIZE["description"]) * 0.9
        lh2 = fs * 1.34
        parts.append(f'<g font-size="{fs:.1f}" fill="{hexs(pal.text_ink)}">')
        for i, line in enumerate(_wrap_cjk(body, max(8, int(bw2 / (fs * 0.98))))):
            yy = by + fs * 1.05 + i * lh2
            if yy > by + bh2:
                break
            parts.append(f'<text x="{bx:.1f}" y="{yy:.1f}">{_esc(line)}</text>')
        parts.append("</g>")
    # 数值
    if spec.frame_def.has_atk:
        stx, sty = anchor_pt("link_value" if spec.frame == "link" else "def_value")
        fs2 = f.font(G.FONT_SIZE["atk_def"]) * 0.9
        if spec.frame == "link":
            parts.append(f'<text x="{stx:.1f}" y="{sty:.1f}" text-anchor="end" '
                         f'font-size="{fs2:.1f}" fill="{hexs(pal.stat_ink)}">'
                         f'ATK/{L._fmt_num(spec.atk)}</text>')
        else:
            parts.append(f'<text x="{stx:.1f}" y="{sty:.1f}" text-anchor="end" '
                         f'font-size="{fs2:.1f}" fill="{hexs(pal.stat_ink)}">'
                         f'DEF/{L._fmt_num(spec.dfd)}</text>')
        axx, ayy = anchor_pt("atk_value")
        parts.append(f'<text x="{axx:.1f}" y="{ayy:.1f}" text-anchor="end" '
                     f'font-size="{fs2:.1f}" fill="{hexs(pal.stat_ink)}">'
                     f'ATK/{L._fmt_num(spec.atk)}</text>')
    # 罕贵指示条（预览用；真正的箔在 PNG 通道）
    if r.rarity != "common":
        parts.append(f'<rect width="{w}" height="{h}" rx="{f.px(34):.1f}" fill="url(#none)" '
                     f'opacity="0.001"/>')
    parts.append("</svg>")
    return "".join(parts)


def _esc(s: str) -> str:
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _wrap_cjk(text: str, per_line: int) -> list[str]:
    """朴素按字数切分（SVG 预览用；精确断行在 PNG 通道由排版引擎负责）。"""
    out: list[str] = []
    for para in str(text).split("\n"):
        i = 0
        while i < len(para):
            out.append(para[i:i + per_line])
            i += per_line
    return out or [""]
