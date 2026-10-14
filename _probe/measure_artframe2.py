# -*- coding: utf-8 -*-
"""精确量参考图里「卡图窗口的金属斜切框」：内框矩形、四边厚度、斜面色、内侧暗角宽度。

判据：框是**低饱和偏蓝灰**的像素带（画面本身是彩色插画），因此按
「饱和度 < S_MAX 且 亮度 < V_MAX」认定框，逐行/逐列找转折点。
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
from PIL import Image  # noqa: E402

REF = Path(r"C:\Users\Administrator\Desktop\卡图.png")
im = Image.open(REF).convert("RGB")
W, H = im.size
px = im.load()


def is_frame(c):
    """低饱和 + 中低亮度 + 不偏暖 → 归为框。"""
    r, g, b = c[0], c[1], c[2]
    mx, mn = max(r, g, b), min(r, g, b)
    sat = (mx - mn) / (mx + 1)
    return sat < 0.30 and 20 <= mx <= 200


def run_from_edge(line, forward=True):
    """从边缘往里，连续「框像素」的长度（允许 1px 噪声）。"""
    seq = line if forward else line[::-1]
    n = miss = 0
    for c in seq:
        if is_frame(c):
            n += 1
            miss = 0
        else:
            miss += 1
            if miss > 2:
                break
            n += 1
    return n


rows = {y: [px[x, y] for x in range(W)] for y in range(H)}
cols = {x: [px[x, y] for y in range(H)] for x in range(W)}

print("[1] 四边框厚（多条平行线取中位数，单位=参考图像素）")
for name, vals in {
    "上": [run_from_edge(rows[y][:], True) for y in (H // 4, H // 2, 3 * H // 4)],
    "下": [run_from_edge(list(reversed(rows[y])), True) for y in (H // 4, H // 2, 3 * H // 4)],
    "左": [run_from_edge(cols[x][:], True) for x in (W // 4, W // 2, 3 * W // 4)],
    "右": [run_from_edge(list(reversed(cols[x])), True) for x in (W // 4, W // 2, 3 * W // 4)],
}.items():
    vals.sort()
    print(f"   {name}  {vals}  中位 {vals[len(vals)//2]}px")

# 内框矩形：从上/下/左/右各自中位厚度推，再逐边校准
top = run_from_edge(rows[H // 2][:], True)
bot = run_from_edge(list(reversed(rows[H // 2])), True)
lft = run_from_edge(cols[W // 2][:], True)
rgt = run_from_edge(list(reversed(cols[W // 2])), True)
print(f"\n[2] 内框矩形（画面窗口）= x{lft} y{top} .. {W-rgt} {H-bot}  "
      f"尺寸 {W-lft-rgt}x{H-top-bot}  宽高比 {(W-lft-rgt)/(H-top-bot):.4f}")
print(f"   整图宽高比 {W/H:.4f}   框厚/画面宽 = 上{top/(W-lft-rgt):.4f} "
      f"下{bot/(W-lft-rgt):.4f} 左{lft/(H-top-bot):.4f} 右{rgt/(H-top-bot):.4f}")

print("\n[3] 斜面的明暗方向（框带里由外到内的亮度序列，取上边中点）")
seq = [sum(rows[y][W // 2]) / 3 for y in range(0, top + 6)]
print("   " + " ".join(f"{v:.0f}" for v in seq))
seq2 = [sum(cols[x][H // 2]) / 3 for x in range(0, lft + 6)]
print("   左边由外到内：" + " ".join(f"{v:.0f}" for v in seq2))
seq3 = [sum(rows[y][W // 2]) / 3 for y in range(H - 1, H - bot - 6, -1)]
print("   下边由外到内：" + " ".join(f"{v:.0f}" for v in seq3))

print("\n[4] 框带代表色（各边中点，从外 1/4 到内 3/4 位置）")
for name, y, x in [("上", top // 2, W // 2), ("下", H - 1 - bot // 2, W // 2),
                   ("左", H // 2, lft // 2), ("右", H // 2, W - 1 - rgt // 2)]:
    print(f"   {name}  rgb{px[x, y]}")

print("\n[5] 内侧暗角：画面第一行/第一列往里 0..24px 的亮度（看有没有内阴影）")
for name, vals in {
    "上内": [sum(rows[top + k][W // 2]) / 3 for k in range(0, 24)],
    "左内": [sum(cols[lft + k][H // 2]) / 3 for k in range(0, 24)],
    "中": [sum(rows[H // 2 + k][W // 2]) / 3 for k in range(0, 24)],
}.items():
    print(f"   {name:<4} " + " ".join(f"{v:.0f}" for v in vals))

# 把「框带」本身抠出来存图，方便肉眼确认结构
band = im.crop((0, 0, W, top + 30)).resize((W * 2, (top + 30) * 2), Image.NEAREST)
band.save(Path("D:/游戏王DIY设计/_probe/artframe_topband2x.png"))
miter = im.crop((0, 0, lft + 30, top + 30)).resize(((lft + 30) * 6, (top + 30) * 6), Image.NEAREST)
miter.save(Path("D:/游戏王DIY设计/_probe/artframe_miter6x.png"))
print("\n   已存 _probe/artframe_topband2x.png 与 _probe/artframe_miter6x.png")
