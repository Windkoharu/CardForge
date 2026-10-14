# -*- coding: utf-8 -*-
"""探针 11：灵摆其它底色变体 / 20周年标与版权标在灵摆卡上的落点 / 收尾核查。"""
import os, sys, time
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"D:\workbuddy workspace\2026-10-12-12-38-13\cardforge")
import numpy as np
from PIL import Image
from forge import template as T
from forge import compositor as C

OUT = r"D:\游戏王DIY设计\_probe"
CAN = T.CANVAS
sys.path.insert(0, OUT)
from p02_render import art_demo  # noqa

art = art_demo(1400, 1400, 1)

print("=" * 104)
print("① 灵摆各底色变体：白条残留是否一致")
print("=" * 104)
for base in ("normal", "effect", "ritual", "fusion", "synchro", "xyz"):
    spec = dict(name=f"灵摆 {base}", frame="pendulum", pendulum_base=base, level=7,
                attribute="光", race="魔法师族", atk=2500, **{"def": 2000}, pendulum=4,
                pendulum_text="①：灵摆效果测试文本。",
                text="①：怪兽效果测试文本。")
    t0 = time.time()
    im = C.render_card(dict(spec), art, CAN)
    dt = (time.time() - t0) * 1000
    im.convert("RGB").save(os.path.join(OUT, f"p2_{base}.png"))
    a = np.asarray(im.convert("RGB")).astype(np.int16)
    m = (a[:, :, 0] > 246) & (a[:, :, 1] > 246) & (a[:, :, 2] > 246)
    rows = m[1400:].sum(axis=1)
    nz = np.where(rows > 200)[0]
    rng = f"y{1400+nz.min()}-{1400+nz.max()}" if len(nz) else "无"
    # 全卡白像素
    tot = int(m.sum())
    print(f"  base={base:<9} {dt:6.1f}ms  卡底白条 {rng}  全卡白像素 {tot}")
print()
print("  素材本身的白窗（1140系）：")
for base in ("normal", "effect", "ritual", "fusion", "synchro", "xyz"):
    p = T.asset_path(T.frame_asset("pendulum", True, base))
    if not p:
        print(f"    {base:<9} 素材缺失"); continue
    im = Image.open(p).convert("RGB").resize(CAN, Image.LANCZOS)
    a = np.asarray(im).astype(np.int16)
    m = (a[:, :, 0] > 246) & (a[:, :, 1] > 246) & (a[:, :, 2] > 246)
    ys, xs = np.where(m)
    print(f"    {base:<9} 白区 y{ys.min()}-{ys.max()} x{xs.min()}-{xs.max()} "
          f"占全卡 {m.mean()*100:.1f}%")

print()
print("=" * 104)
print("② 灵摆卡上的 20 周年标 / 版权标 / 激光标 落点")
print("=" * 104)
st = T.region("stamp20")
print(f"  GEO['stamp20'] = x{st[0]:.0f}-{st[0]+st[2]:.0f} y{st[1]:.0f}-{st[1]+st[3]:.0f}")
print(f"  灵摆怪兽效果框 = y{T.region('pendulum_monster_panel')[1]:.0f}-"
      f"{T.region('pendulum_monster_panel')[1]+T.region('pendulum_monster_panel')[3]:.0f}")
print(f"  → 20 周年标与效果框{'重叠' if st[1] < T.region('pendulum_monster_panel')[1]+T.region('pendulum_monster_panel')[3] else '不重叠'}")
base = dict(name="灵摆外设", frame="pendulum", pendulum_base="effect", level=7, attribute="光",
            race="魔法师族", atk=2500, **{"def": 2000}, pendulum=4,
            pendulum_text="①：灵摆效果。", text="①：怪兽效果。")
plain = C.render_card(dict(base), art, CAN).convert("RGB")
pa = np.asarray(plain).astype(np.int16)
for nm, extra in [("stamp20", dict(stamp20=True)), ("laser1", dict(laser=1)),
                  ("cp_sc", dict(copyright_mark="sc"))]:
    sp = dict(base); sp.update(extra)
    im = C.render_card(sp, art, CAN).convert("RGB")
    im.save(os.path.join(OUT, f"p2_{nm}.png"))
    a = np.asarray(im).astype(np.int16)
    d = np.abs(a - pa).mean(axis=2)
    ys, xs = np.where(d > 20)
    print(f"  {nm:<9} 改动区 x{xs.min()}-{xs.max()} y{ys.min()}-{ys.max()}" if len(ys)
          else f"  {nm:<9} 无改动")

print()
print("=" * 104)
print("③ 灵摆效果文与刻度的关系（是否被刻度遮住 / 是否压到面板边）")
print("=" * 104)
pt_ = T.region("pendulum_text")
pp_ = T.region("pendulum_panel")
sl = T.region("pendulum_scale_l")
sr = T.region("pendulum_scale_r")
print(f"  pendulum_panel  x{pp_[0]:.0f}-{pp_[0]+pp_[2]:.0f} y{pp_[1]:.0f}-{pp_[1]+pp_[3]:.0f}")
print(f"  pendulum_text   x{pt_[0]:.0f}-{pt_[0]+pt_[2]:.0f} y{pt_[1]:.0f}-{pt_[1]+pt_[3]:.0f}")
print(f"  scale_l         x{sl[0]:.0f}-{sl[0]+sl[2]:.0f} y{sl[1]:.0f}-{sl[1]+sl[3]:.0f}")
print(f"  scale_r         x{sr[0]:.0f}-{sr[0]+sr[2]:.0f} y{sr[1]:.0f}-{sr[1]+sr[3]:.0f}")
print(f"  文本底线 y{pt_[1]+pt_[3]:.0f}  面板底线 y{pp_[1]+pp_[3]:.0f} "
      f"→ 文本底距面板底 {pp_[1]+pp_[3]-(pt_[1]+pt_[3]):.0f}px")
print(f"  刻度底 y{sl[1]+sl[3]:.0f} vs 面板底 y{pp_[1]+pp_[3]:.0f} "
      f"→ {'刻度溢出面板 ' + str(round(sl[1]+sl[3]-(pp_[1]+pp_[3]))) + 'px' if sl[1]+sl[3] > pp_[1]+pp_[3] else 'OK'}")
print(f"  刻度色块高度 {sl[3]:.0f}px = 813系 {sl[3]/T.SY:.0f}px（真卡刻度菱形约 39px）")
print(f"  数字画在 cy + gh*0.30 = y{sl[1]+sl[3]/2+sl[3]*0.30:.0f} → 已到面板外")

print()
print("=" * 104)
print("④ preview_png / render_card(size=...) 的缩放路径")
print("=" * 104)
import io
b = C.preview_png(dict(base), art, width=430)
im = Image.open(io.BytesIO(b))
print(f"  preview_png(width=430) -> {im.size}  {len(b)} bytes")
print(f"  内部：render_card(spec, art, (430,466)) → 直接从 1140 画布一次 LANCZOS 到 430")
print(f"  但 render_card 内部仍先在 1140 画布全量合成，再单次缩到 430 —— 没有多次降采样")
for w in (430, 421, 177):
    im2 = C.render_card(dict(base), art, (w, int(round(w * CAN[1] / CAN[0]))))
    print(f"  render_card(size=({w},...)) -> {im2.size}")
