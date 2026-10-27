"""版面几何 —— 全部渲染的唯一数值真相源。

坐标系约定
----------
* **REF 坐标系 = 813×1185**：官方卡图原生尺寸，所有版面数值都在这个坐标系里书写。
* 任何目标画布（预览 480 / EDOPro 421×614 / 分享 813×1185 / 打印 1394×2031 /
  卡框素材原生 1394×2031）都通过 :func:`scale_rect` 等比换算。
* 官方卡框素材原生尺寸 1394×2031，其插画窗实测 (171, 375, 1051, 1052)，
  换算回 REF 得 (100, 219, 613, 613)，与真卡实测**完全一致**（误差 < 0.1%），
  所以框体与版面可以直接互换。

数值来源
--------
* 版面：真卡实测 + ``alixsep/yugilife`` 的 ``template.json``（只取几何事实，不复制文件）
* 插画窗暗环剖面：对参考 DIY 卡做 103 条样本、逐行平均亮度的最小二乘拟合
  （``art_ring=29.5``、``art_ring_alpha=0.77`` → RMSE ≈ 2.2）
* 文本框高度：官方卡框整图实测（889–1111）
"""
from __future__ import annotations

from dataclasses import dataclass

# ══════════════════════════════════════════════════════════════════════
#  坐标系与输出规格
# ══════════════════════════════════════════════════════════════════════
REF = (813.0, 1185.0)                    # 权威参考坐标系
FRAME_NATIVE = (1394, 2031)              # 官方卡框素材原生尺寸
FRAME_ART_NATIVE = (171, 375, 1051, 1052)  # 卡框素材里的插画窗（实测）

OUTPUT_SIZES: dict[str, tuple[int, int]] = {
    "edopro": (421, 614),      # EDOPro / YGOPro 主用（社区约定，非官方公布）
    "compat": (177, 254),      # 传统小图
    "mdpro3": (704, 1024),     # MDPro3 / MDPro4 整卡图尺寸。实测依据：
                               # ① 其 Settings.json 的 SavedCardSize 就是 [704,1024]
                               # ② 社区流通的 .ypk 扩展包里 pics/<卡号>.jpg 全是 704×1024
                               # 注意 MDPro3 的 Picture/Art/ 是 624×624 的**纯插画**
                               # （它自己会重新合成卡面），两条通路不要混用
    "share": (813, 1185),      # 分享/展示（= 350 dpi，基准坐标系）
    "print300": (697, 1016),   # 300 dpi 打印（59×86 mm，中文 DIY 圈常用）
    "print": (1394, 2031),     # 600 dpi 打印 / 高清分享
    "native": (1394, 2031),    # 卡框素材原生（最清晰）
    "archive": (2787, 4063),   # 1200 dpi 归档级
}
DEFAULT_OUTPUT = "edopro"

#: 卡牌物理尺寸（mm）。由卡套厂商反复确认（Konami 未公布），业界事实。
CARD_MM = (59.0, 86.0)


def dpi_of(size: str | tuple[int, int]) -> float:
    """给定像素尺寸折算 dpi（按 59×86 mm）。"""
    w = OUTPUT_SIZES.get(size, OUTPUT_SIZES[DEFAULT_OUTPUT])[0] if isinstance(size, str) else size[0]
    return round(w / (CARD_MM[0] / 25.4), 1)


#: 卡图生成推荐尺寸（宽高比 0.68421 vs 卡图窗 0.68567，误差 0.21%，**无需裁剪**）
ART_GEN_SIZE = (832, 1216)
ART_GEN_SIZE_UPSCALED = (3328, 4864)     # 4× 放大后
ART_TARGET_2X = (842, 1228)              # 421×614 的精确 2×，降采样前最后一步


# ══════════════════════════════════════════════════════════════════════
#  版面区域（REF 坐标系，每项 = (x, y, w, h)）
# ══════════════════════════════════════════════════════════════════════
GEO: dict[str, tuple] = {
    # ── 卡框与底纹 ──
    "border": (0, 0, 813, 1185),
    "frame_inset": (28, 28, 757, 1128),

    # ── 卡名条 ──
    "title_bevel": (45, 47.5, 724, 91),

    # ── 插画（标准框）──
    "artwork": (100, 219, 613, 613),
    "artwork_box": (86, 205, 641, 641),
    "artwork_box_shadow": (66, 185, 681, 681),

    # ── 符号 ──
    "level_star": (680, 146, 49, 49),        # 右对齐基准（最右一颗星）
    "rank_star": (89.6, 146, 49, 49),        # 左对齐基准（超量）
    "badge": (683.5, 61.5, 67, 67),          # 属性 / 魔陷徽记中心 (717, 95)
    "sticker": (743, 1114, 42, 42),          # 激光防伪标
    "stamp20": (62, 1054, 104, 84),          # 20 周年标
    "card_full": (0, 0, 813, 1185),

    # ── 文本（标准框；文本框面板内区实测 889–1111）──
    # ⚠ type_line 与 st_label 的 y 经**像素实测修正**：卡框自带的装饰边线在 REF y≈878，
    #   米色面板内区从 889 开始，因此类型行必须画在 833–887 的橙色条带上（中心 858）。
    #   旧版把这个值写成 918，导致类型行落进文本框里、与框体自带墨迹形成 44px 重影；
    #   现已由 frameprobe 实测校准，默认值同步修正为 841（高 34 → 中心 858）。
    "type_line": (63.5, 841, 680, 34),
    "st_label": (424, 841, 308, 34),         # 魔陷「魔法卡／陷阱卡」标签（右对齐，同一带）
    "text_panel": (65.5, 889, 682.5, 222),
    "text_box": (65.5, 897, 684, 173),       # 怪兽可用区（面板内区，至分隔线 1076 前）
    "text_box_st": (65.5, 900, 684, 174),    # 魔陷可用区（无类型行）
    "stats_separator": (65, 1076, 683, 2),   # 卡框不自带，由渲染器绘制
    "atk_value": (583, 1106),                # 右对齐锚点
    "def_value": (748, 1106),
    "link_value": (747, 1105.5),
    "card_code": (727, 870),
    "copyright": (732, 1147),

    # ── 灵摆专用（真卡实测：两个独立文本框）──
    # 注意：灵摆卡框素材的中段是一整块**空窗**（实测白区 212–1116，占全卡 76%），
    # 面板与类型行全部由渲染器自行绘制，因此这里给出的是"渲染器该画在哪"。
    "pendulum_artwork": (55, 212, 703, 903),     # 灵摆空窗（= 插画 + 面板的总区域）
    "pendulum_art_box": (54, 213, 705, 523),     # 插画实际可见区（实测 212–736）
    "pendulum_panel": (32, 745, 750, 135),       # 灵摆效果框（实测 745–880）
    "pendulum_text": (118, 752, 578, 122),       # 灵摆效果文（让开左右刻度）
    "pendulum_scale_l": (45, 762, 56, 70),
    "pendulum_scale_r": (700, 762, 56, 70),
    "pendulum_monster_panel": (32, 893, 750, 197),
    "pendulum_type_line": (63.5, 841, 660, 34),
    "pendulum_monster_text": (63.5, 905, 686, 173),
    "pendulum_backing": (32, 736, 750, 380),     # 铺底：盖住两面板之间与下缘的空窗
}

#: 灵摆框的插画区在视觉上是「大窗」，出框模式下用它而非小窗
PENDULUM_ART_KEY = "pendulum_artwork"
STANDARD_ART_KEY = "artwork"

#: GEO 里这些键是**锚点**（2 元组）而非矩形（4 元组）——文本按右对齐锚点定位
POINT_KEYS = frozenset({"atk_value", "def_value", "link_value", "card_code", "copyright"})
#: 需要矩形时给锚点键的默认尺寸（宽, 高），仅用于遮罩/区域计算
POINT_DEFAULT_SIZE: dict[str, tuple[float, float]] = {
    "atk_value": (200, 40), "def_value": (200, 40), "link_value": (220, 40),
    "card_code": (200, 60), "copyright": (300, 30),
}



# ══════════════════════════════════════════════════════════════════════
#  字号 / 行距 / 容量（REF 坐标系）
# ══════════════════════════════════════════════════════════════════════
FONT_SIZE: dict[str, float] = {
    "name": 90,              # 卡名（MatrixRegularSmallCaps 风格）
    "type_line": 31,
    "st_label": 40,          # 魔陷「魔法卡／陷阱卡」
    "description": 30,       # 效果正文
    "description_lore": 28,  # 通常怪兽说明文
    "atk_def": 37,
    "link": 25,              # LINK-4 之类的标记
    "card_code": 23,
    "copyright": 21,
    "sticker": 42,
    "pendulum_scale": 48,    # 左右刻度数字
}
LINE_HEIGHT: dict[str, float] = {"description": 30.0, "description_lore": 28.0}
TEXT_MAX_H: dict[str, float] = {"monster": 160.0, "spell_trap": 210.0, "pendulum": 122.0}

#: 文字自动压缩（来自 yugilife textDefaults 实测）
COMPRESS = {
    "autoScaleXQuantifier": 0.01,   # 横向压缩步长 1%
    "maxAutoCompressionX": 0.20,    # 最多横压 20%，再压不动就降档换字号
}

#: 自适应档位：宽 → 窄。每档 (fontSize, lineHeight, maxLines)
FIT_PROFILES: dict[str, list[dict]] = {
    "description": [
        {"id": "large", "fontSize": 30.0, "lineHeight": 30.0, "maxLines": 5},
        {"id": "medium", "fontSize": 24.4, "lineHeight": 25.0, "maxLines": 6},
        {"id": "small", "fontSize": 21.0, "lineHeight": 22.0, "maxLines": 7},
        {"id": "extra-small", "fontSize": 17.0, "lineHeight": 16.67, "maxLines": 9},
    ],
    "lore": [
        {"id": "large", "fontSize": 28.0, "lineHeight": 28.0, "maxLines": 2},
        {"id": "medium", "fontSize": 26.5, "lineHeight": 27.0, "maxLines": 3},
        {"id": "small", "fontSize": 25.0, "lineHeight": 25.5, "maxLines": 4},
        {"id": "extra-small", "fontSize": 22.0, "lineHeight": 22.5, "maxLines": 5},
    ],
    "type_line": [
        {"id": "type-big", "fontSize": 31.0},
        {"id": "type-small", "fontSize": 24.0},
    ],
}

# ══════════════════════════════════════════════════════════════════════
#  插画边缘过渡（REF 坐标系像素）
# ══════════════════════════════════════════════════════════════════════
#: 画窗外的「线性变暗暗环」。真卡实测只有 2–3px 印刷柔化、不含暗环；
#: 设 0 即回到"严格按实卡"，设 29.5/0.77 则贴近参考 DIY 卡观感。
ART_RING_DEFAULT = 29.5
ART_RING_ALPHA = 0.77
#: 「羽化外溢」：把插画边缘像素向外晕开（画面颜色的溢出，不是暗环）。与暗环可叠加。
ART_FADE_DEFAULT = 0.0
ART_FADE_BLUR = 0.55
ART_FADE_MASK_BLUR = 0.75

# ══════════════════════════════════════════════════════════════════════
#  出框（Full Art）溢出的默认幅度（相对卡图窗高度的比例）
# ══════════════════════════════════════════════════════════════════════
FULLART_DEFAULTS: dict[str, dict] = {
    "none":         {"bleed_top": 0.00, "bleed_bottom": 0.00, "panel_opacity": 1.00, "fade_px": 0.0},
    # 官方超框：插画铺满内框，面板含类型行；数值只给 UI/capabilities 看
    "overframe":    {"bleed_top": 0.00, "bleed_bottom": 0.00, "panel_opacity": 0.88, "fade_px": 0.0},
    "art_bleed":    {"bleed_top": 0.13, "bleed_bottom": 0.10, "panel_opacity": 0.86, "fade_px": 0.0},
    "art_over":     {"bleed_top": 0.34, "bleed_bottom": 0.18, "panel_opacity": 0.78, "fade_px": 0.0},
    "full_bleed":   {"bleed_top": 1.00, "bleed_bottom": 1.00, "panel_opacity": 0.72, "fade_px": 26.0},
    "pendulum_full": {"bleed_top": 0.16, "bleed_bottom": 0.12, "panel_opacity": 0.85, "fade_px": 0.0},
    # 主体出框：背景**不**出血（art_rect 就是标准窗），溢出量体现在主体层的放大与上移上
    "subject_bleed": {"bleed_top": 0.00, "bleed_bottom": 0.00, "panel_opacity": 1.00,
                      "fade_px": 0.0, "subject_scale": 1.30, "subject_offset_y": -0.10},
}

# ══════════════════════════════════════════════════════════════════════
#  换算
# ══════════════════════════════════════════════════════════════════════


@dataclass
class Frame:
    """一个目标画布的换算上下文。

    ``layout`` 可挂一个实测版面对象（见 :mod:`cardforge.render.frameprobe`）。
    挂了之后，``rect()`` 会优先返回该对象给出的实测矩形 —— 这样 15 种卡框各自
    不同的「类型行 / 文本框面板」位置都能自动适配，而不必维护 15 套硬编码数值。
    （用鸭子类型而不是直接 import，避免 geometry ↔ frameprobe 循环依赖。）
    """
    width: int
    height: int
    layout: object | None = None

    @property
    def kx(self) -> float:
        return self.width / REF[0]

    @property
    def ky(self) -> float:
        return self.height / REF[1]

    @property
    def k(self) -> float:
        """等比缩放系数（取较小者，保证不撑破）。"""
        return min(self.kx, self.ky)

    def _override(self, name: str):
        lay = self.layout
        if lay is None:
            return None
        rects = getattr(lay, "rects", None)
        if isinstance(rects, dict) and name in rects:
            return rects[name]
        return None

    def rect(self, name: str) -> tuple[float, float, float, float]:
        """取矩形区域。锚点键请改用 :meth:`point` 或 :meth:`anchor_box`。"""
        ov = self._override(name)
        if ov is not None:
            return scale_rect(ov, self)
        v = GEO[name]
        if len(v) != 4:
            raise ValueError(
                f"GEO['{name}'] 是锚点而非矩形（{len(v)} 个值）；"
                f"请用 Frame.point('{name}') 取锚点，或用 Frame.anchor_box('{name}') 取默认矩形")
        return scale_rect(v, self)

    def point(self, name: str) -> tuple[float, float]:
        return scale_point(GEO[name][:2], self)

    def anchor_box(self, name: str, w: float | None = None,
                   h: float | None = None) -> tuple[float, float, float, float]:
        """把锚点键当作矩形：以锚点为**右上角**向左下展开默认尺寸。"""
        if name in GEO and len(GEO[name]) == 4:
            return self.rect(name)
        x, y = self.point(name)
        dw, dh = POINT_DEFAULT_SIZE.get(name, (200.0, 40.0))
        dw = self.px(dw) if w is None else w
        dh = self.px(dh, "y") if h is None else h
        return x - dw, y, dw, dh

    def px(self, v: float, axis: str = "x") -> float:
        return v * (self.kx if axis == "x" else self.ky)

    def font(self, v: float) -> float:
        """字号按等比系数缩放（用 k 而非 kx，避免非等比画布把字压扁）。"""
        return v * self.k

    def box(self, name: str) -> tuple[int, int, int, int]:
        """取整后的矩形 (x, y, w, h)，直接可用于 Pillow。"""
        x, y, w, h = self.rect(name)
        return round(x), round(y), round(w), round(h)


def make_frame(width: int, height: int) -> Frame:
    return Frame(int(width), int(height))


def rect_of(size: tuple[int, int] | str) -> Frame:
    """把 'edopro' 或 (w,h) 变成 Frame。"""
    if isinstance(size, str):
        size = OUTPUT_SIZES.get(size, OUTPUT_SIZES[DEFAULT_OUTPUT])
    return make_frame(*size)


def scale_rect(r: tuple, f: Frame) -> tuple[float, float, float, float]:
    x, y, w, h = r
    return x * f.kx, y * f.ky, w * f.kx, h * f.ky


def scale_point(p: tuple, f: Frame) -> tuple[float, float]:
    return p[0] * f.kx, p[1] * f.ky


def to_ref(px: float, f: Frame, axis: str = "x") -> float:
    """把某画布的像素长度换算回 REF 系（用于把实测值写回 GEO）。"""
    return px / (f.kx if axis == "x" else f.ky)


# ══════════════════════════════════════════════════════════════════════
#  多语言排版微调（按语言对文本框做小的内缩/字号修正）
# ══════════════════════════════════════════════════════════════════════
#: 不同语言的视觉密度不同：日文最密、英文最长。数值为 REF 系的额外内缩 (l,t,r,b)。
LANG_TEXT_INSET: dict[str, tuple[float, float, float, float]] = {
    "zh_cn": (8.0, 4.0, 8.0, 2.0),
    "zh_tw": (8.0, 4.0, 8.0, 2.0),
    "ja": (7.0, 3.0, 7.0, 2.0),
    "en": (6.0, 3.0, 6.0, 2.0),
    "ko": (7.0, 3.0, 7.0, 2.0),
}
LANG_FONT_SCALE: dict[str, float] = {
    "zh_cn": 1.00, "zh_tw": 1.00, "ja": 0.97,
    "en": 1.00, "ko": 0.98, "de": 0.92, "fr": 0.94,
    "it": 0.95, "pt": 0.95, "es": 0.95,
}


def text_inset(lang: str) -> tuple[float, float, float, float]:
    return LANG_TEXT_INSET.get(lang, (8.0, 4.0, 8.0, 2.0))


def font_scale(lang: str) -> float:
    return LANG_FONT_SCALE.get(lang, 1.0)


# ══════════════════════════════════════════════════════════════════════
#  自检
# ══════════════════════════════════════════════════════════════════════
def verify_frame_consistency() -> dict:
    """验证「卡框素材原生坐标 ↔ REF 坐标」一致（移植时的回归检查）。"""
    fx, fy, fw, fh = FRAME_ART_NATIVE
    kx = REF[0] / FRAME_NATIVE[0]
    ky = REF[1] / FRAME_NATIVE[1]
    derived = (fx * kx, fy * ky, fw * kx, fh * ky)
    actual = GEO["artwork"]
    diff = [abs(a - b) for a, b in zip(derived, actual)]
    rel = [d / max(1.0, b) for d, b in zip(diff, actual)]
    return {
        "derived": tuple(round(v, 2) for v in derived),
        "geo_artwork": actual,
        "abs_diff": tuple(round(v, 3) for v in diff),
        "max_rel": round(max(rel), 5),
        # 实测最大相对误差 0.27%（高度方向 0.8px）—— 阈值取 0.5%，
        # 既容得下浮点舍入，又能抓住真正的坐标漂移。
        "consistent": max(rel) < 0.005,
    }


if __name__ == "__main__":  # pragma: no cover
    import json
    print(json.dumps(verify_frame_consistency(), ensure_ascii=False, indent=2))
