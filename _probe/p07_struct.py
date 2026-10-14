# -*- coding: utf-8 -*-
"""探针 7：结构性问题定量 —— 灵摆白区、类型行、星带、裁切、性能热点。"""
import os, sys, time, cProfile, pstats, io
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"D:\workbuddy workspace\2026-10-12-12-38-13\cardforge")
import numpy as np
from PIL import Image, ImageDraw
from forge import template as T
from forge import compositor as C

OUT = r"D:\游戏王DIY设计\_probe"
CAN = T.CANVAS
sys.path.insert(0, OUT)
from p02_render import art_demo  # noqa

art = art_demo(1400, 1400, 1)
LOREM = ("①：这张卡召唤成功时才能发动。从卡组把1张「测试」卡加入手卡。"
         "②：1回合1次，以自己场上1只怪兽为对象才能发动。那只怪兽的攻击力直到回合结束时上升1000。"
         "这个效果在对方回合也能发动。③：这张卡被送去墓地的场合才能发动。自己从卡组抽1张。")

print("=" * 104)
print("① 灵摆框：官方素材自带的白区 vs 渲染器覆盖到的范围")
print("=" * 104)
fim = Image.open(T.asset_path("frame/effect-pendulum.png")).convert("RGB")
fa = np.asarray(fim.resize(CAN, Image.LANCZOS)).astype(np.int16)
m = (fa[:, :, 0] > 246) & (fa[:, :, 1] > 246) & (fa[:, :, 2] > 246)
rows = m.sum(axis=1)
runs = []
inr = False
for i, v in enumerate(rows):
    if v > 400 and not inr:
        st = i; inr = True
    elif v <= 400 and inr:
        runs.append((st, i - 1)); inr = False
if inr:
    runs.append((st, len(rows) - 1))
print("  裸卡框(1140系) 白区行段 (宽>400px 的行)：")
for s, e in runs:
    xs = np.where(m[s:e + 1].any(axis=0))[0]
    print(f"    y{s}-{e}  高{e-s+1}px  x{xs.min()}-{xs.max()}  宽{xs.max()-xs.min()+1}px")
print(f"  → 素材自带白区总高 = {sum(e-s+1 for s,e in runs)}px")
print()
g = T.region("pendulum_art_box")
pp = T.region("pendulum_panel")
mp = T.region("pendulum_monster_panel")
print(f"  渲染器覆盖：art {g[1]:.0f}-{g[1]+g[3]:.0f} | 灵摆框 {pp[1]:.0f}-{pp[1]+pp[3]:.0f} "
      f"| 怪兽框 {mp[1]:.0f}-{mp[1]+mp[3]:.0f}")
print(f"  怪兽框底 y{mp[1]+mp[3]:.0f}  vs  素材白区底 y{runs[-1][1]}  "
      f"→ 露出白条 {runs[-1][1]-(mp[1]+mp[3]):.0f}px")
# 检查 render 输出
b = np.asarray(Image.open(os.path.join(OUT, "c03_pendulum.png")).convert("RGB")).astype(np.int16)
live = np.abs(b - fa).mean(axis=2) > 6
rows2 = live[:, 90:1050].sum(axis=1)
print(f"\n  渲染图 c03 里，素材被改动过的行的范围（|diff|>6）：")
nz = np.where(rows2 > 60)[0]
print(f"    y{nz.min()}-{nz.max()}")
for seg in [(1250, 1290), (1385, 1420), (1420, 1470), (1470, 1530), (1520, 1570)]:
    y0, y1 = seg
    print(f"    行段 y{y0}-{y1}: 改动像素数 {rows2[y0:y1+1].mean():.0f}")

print()
print("=" * 104)
print("② 灵摆「类型行」是否超出怪兽效果框")
print("=" * 104)
tlx, tly, tlw, tlh = T.region("pendulum_type_line")
mxl, myl, mxw, mxh = T.region("pendulum_monster_panel")
tf = C.font("type", int(round(T.FONT_SIZE["type_line"] * T.SY)))
for txt in ("【魔法师族／灵摆／效果】", "【幻神兽族／灵摆／效果】"):
    d = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
    n = tf.size
    f = tf
    while f.size > int(round(T.sy(18))) and d.textlength(txt, font=f) > tlw:
        f = C.font("type", f.size - max(1, f.size // 24))
    w = d.textlength(txt, font=f)
    print(f"  「{txt}」 字号{f.size} 宽{w:.0f} 可用{tlw:.0f} "
          f"右端 x={tlx+w:.0f}  框右端 x={mxl+mxw:.0f} "
          f"{'⚠ 超出框！' if tlx + w > mxl + mxw else 'OK'}")

print()
print("=" * 104)
print("③ 星带：是否与卡名条/插画窗相撞（隔离星色）")
print("=" * 104)
for nm in ("c02_effect", "c07_xyz", "x10_13star", "c10_ritual"):
    a = np.asarray(Image.open(os.path.join(OUT, nm + ".png")).convert("RGB")).astype(np.int16)
    y0, y1 = int(T.sy(130)), int(T.sy(300))
    sub = a[y0:y1, :]
    # 等级星 = 金红；阶级星 = 黑金
    gold = (sub[:, :, 0] > 190) & (sub[:, :, 1] > 130) & (sub[:, :, 2] < 150)
    cols = np.where(gold.sum(axis=0) > 2)[0]
    rows = np.where(gold.sum(axis=1) > 2)[0]
    if len(cols):
        print(f"  {nm:<12} 星 y{y0+rows.min()}-{y0+rows.max()} "
              f"x{cols.min()}-{cols.max()}  横向中心 {(cols.min()+cols.max())/2:.0f} "
              f"(画布中心 {CAN[0]/2:.0f})  底边 vs 插画窗顶 {T.region('artwork')[1]:.0f} "
              f"→ 间隙 {T.region('artwork')[1]-(y0+rows.max()):.0f}px")

print()
print("=" * 104)
print("④ 插画裁切：crop_to_ratio 的行为")
print("=" * 104)
for (w, h) in [(1400, 1400), (600, 2400), (2400, 600), (1024, 1024), (832, 1216)]:
    im = Image.new("RGB", (w, h))
    out = C.crop_to_ratio(im, 860 / 860)
    print(f"  {w}x{h} (比{w/h:.2f}) → crop_to_ratio(target=1.0) = {out.size}  "
          f"丢弃 {100*(1-(out.size[0]*out.size[1])/(w*h)):.1f}% 像素")
# 实际目标比
for nm, key in (("artwork", "artwork"), ("pendulum_art_box", "pendulum_art_box")):
    l, t, aw, ah = T.region(key)
    print(f"  GEO['{key}'] 目标比 = {aw/ah:.4f}  ({aw:.0f}x{ah:.0f})")

print()
print("=" * 104)
print("⑤ 性能：cProfile 打点（普通卡 vs 长文卡）")
print("=" * 104)


def bench(n, spec, art):
    t0 = time.time()
    for _ in range(n):
        C.render_card(spec, art, CAN)
    return (time.time() - t0) / n * 1000


spec_ok = dict(name="性能测试", frame="effect", level=4, attribute="炎", race="战士族",
               atk=1700, **{"def": 1000}, text=LOREM)
spec_long = dict(spec_ok); spec_long["text"] = LOREM * 4

# 冷/热分开
C.render_card(dict(spec_ok), art, CAN)
print(f"  热缓存 普通卡       {bench(10, spec_ok, art):8.1f} ms/张")
print(f"  热缓存 长文卡(x4)   {bench(3, spec_long, art):8.1f} ms/张")
print(f"  无插画占位          {bench(10, spec_ok, None):8.1f} ms/张")

pr = cProfile.Profile()
pr.enable()
C.render_card(dict(spec_long), art, CAN)
pr.disable()
s = io.StringIO()
pstats.Stats(pr, stream=s).sort_stats("cumulative").print_stats(18)
print()
for ln in s.getvalue().splitlines()[:34]:
    print("   " + ln)
