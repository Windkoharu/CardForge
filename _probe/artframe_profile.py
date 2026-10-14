# -*- coding: utf-8 -*-
"""卡图窗边界剖面仪：给一张图（参考截图 或 我们的成图），量出插画窗四周的结构。

不预设"应该长什么样"，只输出事实：
  * 自动定位插画窗（找最大的高饱和彩色连通区的外接矩形）
  * 四边各取 3 条扫描线，输出「窗外 40px → 窗内 40px」的归一化剖面
  * 四角斜接情况（沿 45° 方向再采一条）
用法：
  python _probe/artframe_profile.py <图片路径> [标签]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
from PIL import Image  # noqa: E402


def load(p: str) -> Image.Image:
    return Image.open(p).convert("RGB")


def find_art_window(im: Image.Image, sat_min: float = 0.16, frac: float = 0.55):
    """按「彩色像素占比」的行列投影找插画窗。

    插画是彩色的、卡框/边框是低饱和的，所以：某一行里彩色像素占比 > frac 才算落在窗内。
    比对「最长连续段」稳得多（后者会被一条彩色横带骗到）。
    """
    W, H = im.size
    px = im.load()
    step = max(1, min(W, H) // 500)

    def sat(c):
        mx, mn = max(c), min(c)
        return (mx - mn) / (mx + 1)

    xs = list(range(0, W, step))
    ys = list(range(0, H, step))
    mask = {(x, y): sat(px[x, y]) >= sat_min for x in xs for y in ys}
    row_ok = [y for y in ys if sum(mask[(x, y)] for x in xs) / len(xs) >= frac]
    col_ok = [x for x in xs if sum(mask[(x, y)] for y in ys) / len(ys) >= frac]
    if not row_ok or not col_ok:
        return None

    def span(vals):
        """取最长的一段连续区间（允许 step 的跳变）。"""
        best, cur = (vals[0], vals[0]), (vals[0], vals[0])
        for v in vals[1:]:
            if v - cur[1] <= step * 3:
                cur = (cur[0], v)
            else:
                cur = (v, v)
            if cur[1] - cur[0] > best[1] - best[0]:
                best = cur
        return best

    x0, x1 = span(col_ok)
    y0, y1 = span(row_ok)
    w, h = x1 - x0, y1 - y0
    return x0, y0, w, h, (w * h) / (W * H)



def lum(c):
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def profile(px, W, H, origin, vec, n_out, n_in):
    """沿 vec 方向穿过边界的一条剖面：origin 在边界上，vec 是朝画面内的单位向量。"""
    out = []
    for k in range(-n_out, n_in):
        x = int(round(origin[0] + vec[0] * k))
        y = int(round(origin[1] + vec[1] * k))
        if 0 <= x < W and 0 <= y < H:
            c = px[x, y]
            out.append((k, c, round(lum(c), 1)))
    return out


def summarize(name, prof, band=14):
    """把剖面压成一句话：框带厚度、最暗处、内缘亮线、画面起始亮度。"""
    if not prof:
        print(f"   {name:<8} 无数据")
        return
    lums = [p[2] for p in prof]
    k0 = prof[0][0]
    dark = min(prof, key=lambda p: p[2])
    inside = lums[band + 6:band + 16]
    art_l = sum(inside) / max(1, len(inside))
    # 框带 = 边界外侧亮度显著低于画面的一段
    edge_out = sum(lums[:band]) / band
    print(f"   {name:<8} 窗外{band}px 均亮 {edge_out:6.1f} | 最暗 {dark[2]:6.1f} @ {dark[0]:+d}px "
          f"| 窗内 6..16px 均亮 {art_l:6.1f} | 反差 {art_l - edge_out:+6.1f}")


def report(path: str, tag: str = "", rect=None):
    im = load(path)
    W, H = im.size
    px = im.load()
    if rect:
        x, y, w, h = rect
        win = (x, y, w, h, w * h / (W * H))
        print(f"\n{'='*70}\n{tag or Path(path).name}  {path}\n  尺寸 {W}x{H}  （用指定矩形）")
    else:
        print(f"\n{'='*70}\n{tag or Path(path).name}  {path}\n  尺寸 {W}x{H}")
        win = find_art_window(im)
    if not win:
        print("  没能定位插画窗（整图饱和度不足？）")
        return
    x, y, w, h, cov = win
    print(f"  定位到插画窗 ≈ ({x},{y}) {w}x{h}  宽高比 {w/h:.4f}  占卡面 {cov*100:.1f}%")
    n_out, n_in = 40, 26
    cx, cy = x + w // 2, y + h // 2
    print("  四边剖面（负=窗外，正=窗内）：")
    summarize("上", profile(px, W, H, (cx, y), (0, 1), n_out, n_in))
    summarize("下", profile(px, W, H, (cx, y + h), (0, -1), n_out, n_in))
    summarize("左", profile(px, W, H, (x, cy), (1, 0), n_out, n_in))
    summarize("右", profile(px, W, H, (x + w, cy), (-1, 0), n_out, n_in))
    print("  上边逐像素（外 26 → 内 10）：")
    p = profile(px, W, H, (cx, y), (0, 1), 26, 10)
    print("    " + " ".join(f"{v[2]:.0f}" for v in p))
    print("  左上角 45° 斜向（外 26 → 内 10）：")
    p = profile(px, W, H, (x, y), (1, 1), 26, 10)
    print("    " + " ".join(f"{v[2]:.0f}" for v in p))
    return win


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(2)
    # 用法 A：多张图自动定位；用法 B：img x y w h（自动定位失败时手工给）
    if len(args) == 5:
        report(args[0], rect=tuple(int(v) for v in args[1:]))
    else:
        for p in args:
            report(p)
