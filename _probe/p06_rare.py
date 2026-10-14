# -*- coding: utf-8 -*-
"""探针 6：罕贵覆膜 × 8 种 + 外设（激光标/版权标/20周年）；并对覆膜做「哪些区域被改动」的量化。"""
import os, sys, json, time
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"D:\workbuddy workspace\2026-10-12-12-38-13\cardforge")
import numpy as np
from PIL import Image
from forge import compositor as C
from forge import template as T

OUT = r"D:\游戏王DIY设计\_probe"
os.makedirs(OUT, exist_ok=True)
CAN = C.CANVAS
sys.path.insert(0, OUT)
from p02_render import art_demo  # noqa

art = art_demo(1400, 1400, 1)
BASE = dict(name="罕贵覆膜测试", frame="effect", level=4, attribute="炎",
            race="战士族", atk=1700, text="①：覆膜区域测试用卡文。"
            "②：1回合1次，以自己场上1只怪兽为对象才能发动。那只怪兽的攻击力上升1000。")

print("=" * 104)
print("① 8 种罕贵：渲染耗时 + 覆膜对「文本框 / 卡图 / 卡名条」三个区域的改动量")
print("=" * 104)
pl, pt, pw, ph = T.region("text_panel")
al, at_, aw, ah = T.region("artwork")
tb = T.region("title_bevel")
regions = {
    "卡名条": (int(tb[0]), int(tb[1]), int(tb[0] + tb[2]), int(tb[1] + tb[3])),
    "插画窗": (int(al), int(at_), int(al + aw), int(at_ + ah)),
    "文本框": (int(pl), int(pt), int(pl + pw), int(pt + ph)),
    "卡框边": (int(T.sx(10)), int(T.sy(300)), int(T.sx(40)), int(T.sy(700))),
}
base_img = C.render_card(dict(BASE), art, CAN)
ba = np.asarray(base_img.convert("RGB")).astype(np.int16)

rows = []
for key in list(T.RARE.keys()):
    spec = dict(BASE); spec["rarity"] = key
    t0 = time.time()
    im = C.render_card(spec, art, CAN)
    dt = (time.time() - t0) * 1000
    p = os.path.join(OUT, f"r_{key}.png")
    im.convert("RGB").save(p)
    a = np.asarray(im.convert("RGB")).astype(np.int16)
    diff = np.abs(a - ba).mean(axis=2)
    parts = []
    for rn, (x0, y0, x1, y1) in regions.items():
        d = diff[y0:y1, x0:x1]
        parts.append(f"{rn} 改动{d.mean():6.1f}/覆盖{(d>3).mean()*100:5.1f}%")
    print(f"  {key:<11} {dt:7.1f}ms  全卡改动 {diff.mean():6.1f}  " + "  ".join(parts))
    rows.append((key, dt, diff.mean()))

print()
print("=" * 104)
print("② 覆膜是否只改动了「闪纹本身的像素」？—— 取一张放大看文本框")
print("=" * 104)
r = np.asarray(Image.open(os.path.join(OUT, "r_ur.png")).convert("RGB")).astype(np.int16)
d = np.abs(r - ba).mean(axis=2)
print(f"  ur 覆膜：文本框内改动>3 的像素占比 {(d[int(pt):int(pt+ph), int(pl):int(pl+pw)]>3).mean()*100:.1f}%")
print(f"          卡图内改动>3 的像素占比 {(d[int(at_):int(at_+ah), int(al):int(al+aw)]>3).mean()*100:.1f}%")
# 覆膜素材本身的 alpha 分布
ra = Image.open(T.asset_path("rare/ur.png")).convert("RGBA")
al_ = np.asarray(ra)[:, :, 3]
print(f"  rare/ur.png  原生 {ra.size}  alpha: min={al_.min()} max={al_.max()} "
      f"mean={al_.mean():.1f}  全透明像素占比 {(al_==0).mean()*100:.1f}%")
# 是否区分区域
for nm, (x0, y0, x1, y1) in [("卡名条", regions["卡名条"]), ("插画窗", regions["插画窗"]),
                             ("文本框", regions["文本框"])]:
    sx = ra.width / CAN[0]
    sub = al_[int(y0 * ra.height / CAN[1]):int(y1 * ra.height / CAN[1]),
              int(x0 * sx):int(x1 * sx)]
    print(f"      {nm:<6} 区域 alpha 均值 {sub.mean():6.1f}  最大 {sub.max()}")

print()
print("=" * 104)
print("③ 外设：激光标 / 版权标 三语 / 20 周年标")
print("=" * 104)
for nm, extra in [("e_laser1", dict(laser=1)), ("e_laser2", dict(laser=2)),
                  ("e_laser3", dict(laser=3)), ("e_stamp20", dict(stamp20=True)),
                  ("e_cp_sc", dict(copyright_mark="sc")), ("e_cp_jp", dict(copyright_mark="jp")),
                  ("e_cp_en", dict(copyright_mark="en"))]:
    spec = dict(BASE); spec.update(extra)
    t0 = time.time()
    im = C.render_card(spec, art, CAN)
    dt = (time.time() - t0) * 1000
    im.convert("RGB").save(os.path.join(OUT, nm + ".png"))
    a = np.asarray(im.convert("RGB")).astype(np.int16)
    d = np.abs(a - ba).mean(axis=2)
    ys, xs = np.where(d > 20)
    box = f"x{xs.min()}-{xs.max()} y{ys.min()}-{ys.max()}" if len(ys) else "无改动"
    print(f"  {nm:<12} {dt:7.1f}ms  改动区 {box}")

print()
print("=" * 104)
print("④ 激光标语版权标的几何声明 vs 实际")
print("=" * 104)
print(f"  GEO['sticker'] = {T.region('sticker')}")
print(f"  GEO['copyright'] = {T.region('copyright')}  代码锚点 sx(732)={T.sx(732):.0f} sy(1147)={T.sy(1147):.0f}")
print(f"  代码把版权标缩到宽 {T.sx(480):.0f}px，右端对齐 x={T.sx(732):.0f}，底端对齐 y={T.sy(1147):.0f}")
print(f"  → 版权标占 x{T.sx(732)-T.sx(480):.0f}-{T.sx(732):.0f} y约{T.sy(1147)-40:.0f}-{T.sy(1147):.0f}")
print(f"  卡框底线 y={CAN[1]}；版权标底边距卡底 {CAN[1]-T.sy(1147):.0f}px")
