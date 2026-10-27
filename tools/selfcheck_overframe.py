#!/usr/bin/env python3
"""官方超框（overframe）自检 —— 几何、绘制语义、跨卡框回归。

跑法::

    python tools/selfcheck_overframe.py

只依赖 Pillow + 仓库素材，不碰 ComfyUI、不回写 spec。
产物（可视复核）：

    workspace/out/_diag/selfcheck_overframe.png   # 合成竖图上的实际成图
    workspace/out/_diag/selfcheck_frames.png      # 15+ 卡框缩略图

判定口径（与 docs/06 的官方实测规格一致）：

* 插画铺满内框 ``frame_inset``，最外框保留；
* 卡名条不回贴（官方没有名条），卡名浮于画上；
* 怪兽面板从类型行顶部起、含金边/投影，类型行在面板内；
  魔法/陷阱的卡种标签浮于画上，面板从标准文本框顶起；
* 卡号在面板上沿外，密码隐藏；
* 灵摆/技能没有官方参考 → 回退标准（不硬画）。
"""
from __future__ import annotations

import copy
import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cardforge.cli import _demo_spec                    # noqa: E402
from cardforge.core import paths                        # noqa: E402
from cardforge.core.enums import FRAMES, FULL_ART_MODES  # noqa: E402
from cardforge.render import compositor                 # noqa: E402
from cardforge.render import fullart as FA              # noqa: E402
from cardforge.render import geometry as G              # noqa: E402
from cardforge.render.rarities import COMBO_PRESETS      # noqa: E402

PASS = 0
FAIL = 0
_chunks: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
    else:
        FAIL += 1
    _chunks.append((name, bool(ok), detail))
    print(("  PASS  " if ok else "  FAIL  ") + name + (f"  [{detail}]" if detail else ""))


def art(size=(832, 1216), color=(255, 0, 255)) -> Image.Image:
    im = Image.new("RGB", size, color)
    d = ImageDraw.Draw(im)
    # 几条标记线，方便肉眼确认没有二次裁剪
    d.line([(0, size[1] // 2), (size[0], size[1] // 2)], fill=(0, 255, 0), width=3)
    d.line([(size[0] // 2, 0), (size[0] // 2, size[1])], fill=(0, 0, 255), width=3)
    return im


def near(px, rgb, tol=18) -> bool:
    return all(abs(int(a) - int(b)) <= tol for a, b in zip(px[:3], rgb))


def dark_pixels(im: Image.Image, box) -> int:
    x0, y0, x1, y1 = [int(v) for v in box]
    seg = im.crop((x0, y0, x1, y1)).convert("RGB")
    n = 0
    for p in seg.getdata():
        if sum(p) < 420:
            n += 1
    return n


def main() -> int:
    os.makedirs(paths.OUT / "_diag", exist_ok=True)
    f813 = G.make_frame(813, 1185)          # 验收看图尺寸
    spec = _demo_spec()
    spec.render.rarity = "common"
    spec.render.fullart.mode = "overframe"
    spec.render.show_password = True
    spec.render.set_number = "CF01-JP011"

    # ── 1. 档位/预设 ─────────────────────────────────────────────
    check("档位存在", "overframe" in FULL_ART_MODES, FULL_ART_MODES["overframe"].zh_cn)
    check("官方档名为「官方超框」", FULL_ART_MODES["overframe"].zh_cn == "官方超框")
    check("旧 art_over 已并入官方", "并入官方" in FULL_ART_MODES["art_over"].zh_cn)
    check("OFPSE 预设走官方档", COMBO_PRESETS["ofpse"][1] == "overframe")
    check("OFUR 预设走官方档", COMBO_PRESETS["ofur"][1] == "overframe")

    # ── 2. 支持矩阵 ─────────────────────────────────────────────
    check("融合支持官方超框", FA.supports("overframe", "fusion"))
    check("技能不支持官方超框", not FA.supports("overframe", "skill"))
    check("灵摆暂无官方参考", not FA.supports("overframe", "normal_pendulum"))

    # ── 3. 几何 ─────────────────────────────────────────────────
    plan = FA.plan("overframe", f813, spec, (832, 1216), spec.render.fullart)
    fee = f813.rect("frame_inset")
    check("插画起点=内框左上", abs(plan.art_rect[0] - fee[0]) < 0.6
          and abs(plan.art_rect[1] - fee[1]) < 0.6,
          f"{plan.art_rect[:2]} vs {fee[:2]}")
    check("插画宽度=内框宽", abs(plan.art_rect[2] - fee[2]) < 0.6, f"{plan.art_rect[2]:.1f}")
    check("插画在版权上方截断", plan.clip_bottom is not None
          and plan.art_rect[1] + plan.art_rect[3] <= plan.clip_bottom + 0.6,
          f"bottom={plan.art_rect[1] + plan.art_rect[3]:.1f} clip={plan.clip_bottom:.1f}")
    check("不设回贴区（无名条/类型条）", plan.restore_regions == ())
    check("面板从类型行上方起", plan.panel_top is not None
          and plan.panel_top < f813.rect("text_panel")[1],
          f"panel_top={plan.panel_top:.1f} < {f813.rect('text_panel')[1]:.1f}")
    check("面板有金边/投影", plan.panel_border and plan.panel_shadow)
    check("类型行贴正文上方（在面板内）", plan.type_label_rect is not None
          and plan.type_label_rect[1] > plan.panel_top
          and plan.type_label_rect[1] + plan.type_label_rect[3]
          < f813.rect("text_box")[1] + 12,
          f"row_y={plan.type_label_rect[1]:.1f} panel_top={plan.panel_top:.1f}")
    check("类型行用面板深色墨", plan.type_label_dark)
    check("面板包住 ATK·DEF", plan.panel_bottom is not None
          and plan.panel_bottom >= f813.point("def_value")[1] + 4,
          f"panel_bottom={plan.panel_bottom:.1f} def_y={f813.point('def_value')[1]:.1f}")
    check("密码隐藏标记", plan.hide_password)
    check("卡号标记为面板外", plan.code_above_panel)
    check("平卡兜底白字", plan.name_fill == (255, 255, 255))

    # ── 4. 灵摆/技能回退 ────────────────────────────────────────
    pend = copy.deepcopy(spec)
    pend.frame = "normal_pendulum"
    pplan = FA.plan("overframe", f813, pend, (832, 1216), pend.render.fullart)
    check("灵摆选官方档→回退标准", pplan.mode == "none", pplan.notes)
    skill = copy.deepcopy(spec)
    skill.frame = "skill"
    splan = FA.plan("overframe", f813, skill, (832, 1216), skill.render.fullart)
    check("技能选官方档→回退标准", splan.mode == "none", splan.notes)

    # ── 4b. 魔法/陷阱：卡种标签在类型行右侧（OCG 官方位置）─────────
    for fkey, zh in (("spell", "魔法"), ("trap", "陷阱")):
        s = copy.deepcopy(spec)
        s.frame = fkey
        sp = FA.plan("overframe", f813, s, (832, 1216), s.render.fullart)
        top = sp.panel_top or 0.0
        row = sp.type_label_rect
        check(f"{zh}：卡种标签在面板内、贴正文上方",
              row is not None and row[1] > top
              and row[1] + row[3] < f813.rect("text_box_st")[1] + 12,
              f"row_y={row[1]:.1f} panel_top={top:.1f}" if row else "no rect")
        check(f"{zh}：标签用面板深色墨", sp.type_label_dark)
        check(f"{zh}：面板从类型行上方起", top < f813.rect("text_panel")[1],
              f"{top:.1f}")
        check(f"{zh}：密码隐藏", sp.hide_password)

    # ── 4c. DIY 档改版（2026-10-27 验收通过后统一收拾）──────────────
    ab = copy.deepcopy(spec)
    ab.render.fullart.mode = "art_bleed"
    pab = FA.plan("art_bleed", f813, ab, (832, 1216), ab.render.fullart)
    check("出血档类型行自适应对比", pab.contrast_text)
    check("出血档怪物不回贴空标签条", pab.restore_regions == ("title_bevel",),
          str(pab.restore_regions))
    ab_sp = copy.deepcopy(spec)
    ab_sp.frame = "spell"
    ab_sp.render.fullart.mode = "art_bleed"
    pabs = FA.plan("art_bleed", f813, ab_sp, (832, 1216), ab_sp.render.fullart)
    check("出血档魔陷仍回贴标签条", pabs.restore_regions == ("title_bevel", "st_label"),
          str(pabs.restore_regions))
    fb = copy.deepcopy(spec)
    fb.render.fullart.mode = "full_bleed"
    pfb = FA.plan("full_bleed", f813, fb, (832, 1216), fb.render.fullart)
    check("全画档铺满整卡", pfb.art_rect[0] <= 0.5 and pfb.art_rect[1] <= 0.5
          and pfb.art_rect[2] >= f813.width - 1 and pfb.art_rect[3] >= f813.height - 1,
          str(tuple(round(v) for v in pfb.art_rect)))
    check("全画档卡框半透明叠回", 0.3 <= pfb.frame_alpha < 1.0, f"alpha={pfb.frame_alpha}")
    check("全画档类型行自适应对比", pfb.contrast_text)
    ao = copy.deepcopy(spec)
    ao.render.fullart.mode = "art_over"
    pao = FA.plan("art_over", f813, ao, (832, 1216), ao.render.fullart)
    check("旧超框档并入官方几何", pao.mode == "overframe"
          and pao.panel_top == plan.panel_top and pao.panel_bottom == plan.panel_bottom)
    from cardforge.render.rarities import region_mask
    m_default = region_mask("artwork", f813)
    m_full = region_mask("artwork", f813, art_rect=(0, 0, 813, 1185))
    check("箔纸遮罩跟插画矩形", m_full.getextrema() == (255, 255)
          and m_default.getextrema() != (255, 255))

    # ── 5. 像素语义（813 验收尺寸）─────────────────────────────
    img = compositor.render_card(spec, art(), size="share")
    magenta = (255, 0, 255)
    check("外边(5,5)不是插画", not near(img.getpixel((5, 5)), magenta), str(img.getpixel((5, 5))))
    check("外边(807,600)不是插画", not near(img.getpixel((807, 600)), magenta), str(img.getpixel((807, 600))))
    check("外底(400,1170)不是插画", not near(img.getpixel((400, 1170)), magenta), str(img.getpixel((400, 1170))))
    check("内框(200,300)是插画", near(img.getpixel((200, 300)), magenta), str(img.getpixel((200, 300))))
    # 名条区：顶部往下一小条，允许名字笔画，其余应为插画
    band = 0
    total = 0
    for x in range(110, 700, 11):
        for y in range(52, 72, 5):
            total += 1
            if near(img.getpixel((x, y)), magenta, 28):
                band += 1
    check("名条区被插画覆盖（无实心名条）", band / max(1, total) > 0.55,
          f"{band}/{total} 像素为插画")
    # 面板：上沿内侧应是面板填充（卡框实测会把文本框整体挪几像素，
    # 所以取样点从计划上沿再往里让 18px，仍落在类型行墨迹上方）
    pt = int(round(plan.panel_top))
    check("面板上沿内侧不是插画", not near(img.getpixel((400, pt + 18)), magenta, 45),
          str(img.getpixel((400, pt + 18))))
    pnl = img.getpixel((400, pt + 45))
    check("面板内部是半透明混合", pnl[1] > 55 and not near(pnl, magenta, 12), str(pnl))
    check("ATK·DEF 区在面板内（非插画）",
          not near(img.getpixel((200, 1120)), magenta, 45),
          str(img.getpixel((200, 1120))))

    # 密码：白底图上，标准档有 8 位数字、官方超框没有
    white = Image.new("RGB", (832, 1216), (255, 255, 255))
    ccx, ccy = f813.point("card_code")
    pw_box = (ccx - 170, ccy + 16, ccx + 4, ccy + 40)
    std = copy.deepcopy(spec)
    std.render.fullart.mode = "none"
    std_img = compositor.render_card(std, white, size="share")
    over_img = compositor.render_card(spec, white, size="share")
    std_dark = dark_pixels(std_img, pw_box)
    over_dark = dark_pixels(over_img, pw_box)
    check("标准档密码存在（对照组）", std_dark > 40, f"{std_dark} 像素")
    check("官方超框密码隐藏", over_dark == 0, f"{over_dark} 像素")
    # 卡号在面板上沿外：面板上方 10..30px 一带应有可读的卡号笔画
    code_box = (ccx - 170, int(plan.panel_top) - 30, ccx + 4, int(plan.panel_top) - 4)
    check("卡号在面板上沿外", dark_pixels(over_img, code_box) > 20,
          f"{dark_pixels(over_img, code_box)} 像素")

    # ── 6. 跨卡框回归 ──────────────────────────────────────────
    diag = paths.OUT / "_diag"
    ok_frames = 0
    thumb = []
    for key in FRAMES:
        s = copy.deepcopy(_demo_spec())
        s.frame = key
        s.render.rarity = "common"
        s.render.fullart.mode = "overframe"
        try:
            im = compositor.render_card(s, art(), size="share")
            thumb.append((key, im))
            ok_frames += 1
        except Exception as e:                     # noqa: BLE001
            check(f"卡框 {key} 渲染", False, f"{type(e).__name__}: {e}")
    check("全部卡框不崩溃", ok_frames == len(FRAMES), f"{ok_frames}/{len(FRAMES)}")

    # 存可视复核图
    img.save(diag / "selfcheck_overframe.png")
    cols = 6
    rows = (len(thumb) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 208 + 8, rows * 322 + 8), (24, 26, 31))
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 14)
    except Exception:
        font = ImageFont.load_default()
    for i, (key, im) in enumerate(thumb):
        x = (i % cols) * 208 + 4
        y = (i // cols) * 322 + 26
        sheet.paste(im.resize((200, 292), Image.LANCZOS), (x, y))
        d.text((x, y - 20), key, font=font, fill=(230, 230, 235))
    sheet.save(diag / "selfcheck_frames.png")

    print(f"\n{PASS} PASS / {FAIL} FAIL")
    print(f"  可视复核：{paths.rel(diag / 'selfcheck_overframe.png')}")
    print(f"  卡框矩阵：{paths.rel(diag / 'selfcheck_frames.png')}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
