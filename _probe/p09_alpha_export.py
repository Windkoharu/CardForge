# -*- coding: utf-8 -*-
"""探针 9：alpha/圆角、类型行压框、文字贴边、导出管线画质、剩余边界。"""
import os, sys, io, time
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

print("=" * 104)
print("① 卡框素材的 alpha：圆角是否保留")
print("=" * 104)
fr = Image.open(T.asset_path("frame/effect.png"))
print(f"  卡框模式 = {fr.mode}  size={fr.size}")
if fr.mode == "RGBA":
    al = np.asarray(fr)[:, :, 3]
    print(f"  alpha: min={al.min()} max={al.max()}  非不透明像素 {int((al<255).sum())} "
          f"({(al<255).mean()*100:.2f}%)")
    print(f"  四角 alpha = {al[0,0]}, {al[0,-1]}, {al[-1,0]}, {al[-1,-1]}")
else:
    print("  → 无 alpha 通道，卡框是纯矩形不透明图（圆角是画上去的，不是透明的）")
r = C.render_card(dict(name="alpha测试", frame="effect", level=4, attribute="炎",
                       race="战士族", atk=1000, **{"def": 1000}, text="①：alpha 测试。"),
                  art, CAN)
print(f"  渲染结果模式 = {r.mode}  角落 alpha = "
      f"{r.getpixel((0,0))[3]}, {r.getpixel((CAN[0]-1,0))[3]}  "
      f"全不透明像素占比 {np.asarray(r)[:,:,3].mean()/255*100:.2f}%")
print(f"  覆膜素材 rare/ur.png 模式 = {Image.open(T.asset_path('rare/ur.png')).mode}")

print()
print("=" * 104)
print("② 类型行是否压住文本框顶边")
print("=" * 104)
pl, pt, pw, ph = T.region("text_panel")
tlr = T.region("type_line")
print(f"  GEO['text_panel'] = y{pt:.0f}-{pt+ph:.0f}   GEO['type_line'] = y{tlr[1]:.0f} (基线)")
print(f"  类型行字号 = {int(round(T.FONT_SIZE['type_line']*T.SY))}px @ {T.FONT_SIZE['type_line']} (813系)")
for nm in ("c02_effect", "c07_xyz", "c04_link", "c01_normal", "c09_fusion", "c08_synchro"):
    a = np.asarray(Image.open(os.path.join(OUT, nm + ".png")).convert("RGB")).astype(np.int16)
    # 文本框顶边上下 30px 条带里的深色墨迹
    y0, y1 = int(pt) - 26, int(pt) + 30
    band = a[y0:y1, int(pl) + 6:int(pl + pw) - 6]
    dark = band.mean(axis=2) < 120
    rows = np.where(dark.sum(axis=1) > 3)[0]
    if len(rows):
        top = y0 + rows.min()
        print(f"  {nm:<12} 类型行墨迹 y{top}-{y0+rows.max()}  "
              f"面板顶 y{pt:.0f}  → 越出面板顶 {max(0, int(pt)-top)}px  "
              f"{'⚠ 压框' if top < pt else 'OK'}")

print()
print("=" * 104)
print("③ 效果文左右贴边检查（文本框内边距）")
print("=" * 104)
print(f"  代码 tpad = T.sx(8) = {T.sx(8):.1f}px  → 文字左起点 x={pl+T.sx(8):.0f}")
for nm in ("c02_effect", "x06_longtext"):
    a = np.asarray(Image.open(os.path.join(OUT, nm + ".png")).convert("RGB")).astype(np.int16)
    # 只在效果文区域（类型行以下、分隔线以上）找墨
    y0, y1 = int(T.region("text_box")[1]), int(T.sy(1070))
    sub = a[y0:y1, int(pl) + 2:int(pl + pw) - 2]
    bg = np.median(sub.reshape(-1, 3), axis=0)
    dark = (np.abs(sub - bg).sum(axis=2) > 110)
    cols = np.where(dark.sum(axis=0) > 2)[0]
    if len(cols):
        L = int(pl) + 2 + cols.min(); R = int(pl) + 2 + cols.max()
        print(f"  {nm:<12} 墨迹 x{L}-{R}  左内边距 {L-(pl+T.sx(8)):+.0f}px  "
              f"右内边距 {(pl+pw-T.sx(8))-R:+.0f}px  文本框宽 {pw:.0f}")
    # 垂直溢出
    rows = np.where(dark.sum(axis=1) > 2)[0]
    if len(rows):
        print(f"               墨迹 y{y0+rows.min()}-{y0+rows.max()}  "
              f"分隔线 y{T.sy(1076):.0f}  "
              f"{'⚠ 越过分隔线 ' + str(int(y0+rows.max()-T.sy(1076))) + 'px' if y0+rows.max() > T.sy(1076) else 'OK'}")

print()
print("=" * 104)
print("④ 导出管线：降采样次数与最终画质")
print("=" * 104)
spec = dict(name="导出画质测试", frame="effect", level=4, attribute="炎", race="战士族",
            atk=1700, **{"def": 1000}, text="①：导出画质测试。②：细节锐度测试文字 ABC 123。")
big = C.render_card(spec, art, CAN)
print(f"  合成画布 {big.size}")
one = big.convert("RGB").resize(C.EXPORT_MAIN, Image.LANCZOS)
two = one.resize((177, 254), Image.LANCZOS)
direct = big.convert("RGB").resize(C.EXPORT_COMPAT, Image.LANCZOS)
print(f"  export_card: canvas_1140 PNG + main_421 JPEG(q92) + compat_177 = 421→177 二次降采样")
import numpy as np
def sharp(im):
    g = np.asarray(im.convert("L")).astype(np.float32)
    return float(np.abs(np.diff(g, axis=0)).mean() + np.abs(np.diff(g, axis=1)).mean())
print(f"  锐度指标 1140={sharp(big):.2f}  421={sharp(one):.2f}  "
      f"421→177 链式={sharp(two):.2f}  1140→177 直降={sharp(direct):.2f}")
print(f"  链式与直降差异 = {abs(sharp(two)-sharp(direct)):.2f}")
# 有效分辨率
print(f"  421 宽 / 813 系参考 = {421/813:.3f} 倍 → 1px 参考 = {421/813:.2f}px 输出")
print(f"  1140 宽 / 1394 卡框原生 = {1140/1394:.3f} 倍 → 卡框素材被降采样后再放大到 421")
print(f"  最终 421 宽相对卡框原生丢失 {(1-421/1394)*100:.1f}% 细节")

print()
print("=" * 104)
print("⑤ 缓存：同一 spec 重复渲染是否重复解码素材")
print("=" * 104)
t0 = time.time(); C.render_card(dict(spec), art, CAN); t1 = time.time()
print(f"  第 2 次渲染（素材已缓存）: {(t1-t0)*1000:.1f} ms")
print(f"  template._img_cache 条目数 = {len(T._img_cache)}")
print(f"  其中卡框/覆膜大图条目：")
for k in sorted(T._img_cache.keys()):
    v = T._img_cache[k]
    if hasattr(v, "size") and v.size[0] > 800:
        print(f"    {k:<28} {v.size}")
