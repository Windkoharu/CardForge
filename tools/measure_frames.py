"""量测官方卡框素材的实际版面 —— 用像素说话，修正标定值。

用法: python tools/measure_frames.py
输出: workspace/logs/frame_measure.json + 控制台表格
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image  # noqa: E402
import numpy as np  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "data", "assets", "frame")
NATIVE = (1394, 2031)
REF = (813.0, 1185.0)
KX, KY = REF[0] / NATIVE[0], REF[1] / NATIVE[1]


def to_ref(v, axis="y"):
    return round(v * (KY if axis == "y" else KX), 1)


def analyse(path: str) -> dict:
    im = Image.open(path).convert("RGB")
    if im.size != NATIVE:
        im = im.resize(NATIVE, Image.LANCZOS)
    a = np.asarray(im).astype(np.int16)
    h, w, _ = a.shape
    out: dict = {"file": os.path.basename(path), "size": [w, h]}

    # ── 1. 找「近白窗」：整行都是高亮且低饱和的行 ──
    mx = a.max(axis=2); mn = a.min(axis=2)
    sat = mx - mn
    bright = (mn > 225) & (sat < 18)
    row_white = bright.mean(axis=1)
    col_white = bright.mean(axis=0)

    def runs(mask, thr=0.5, min_len=8):
        r, start = [], None
        for i, v in enumerate(mask):
            if v >= thr and start is None:
                start = i
            elif v < thr and start is not None:
                if i - start >= min_len:
                    r.append((start, i - 1))
                start = None
        if start is not None and len(mask) - start >= min_len:
            r.append((start, len(mask) - 1))
        return r

    wr = runs(row_white)
    wc = runs(col_white)
    out["white_row_runs_native"] = wr
    out["white_col_runs_native"] = wc
    out["white_row_runs_ref"] = [[to_ref(s), to_ref(e)] for s, e in wr]
    out["white_col_runs_ref"] = [[to_ref(s, "x"), to_ref(e, "x")] for s, e in wc]

    # ── 2. 在「插画窗下方 ~ 数值行上方」找横向墨迹带（类型行/分隔线）──
    band_top = int(NATIVE[1] * 0.56)
    band_bot = int(NATIVE[1] * 0.98)
    strip = a[band_top:band_bot, int(w * 0.10):int(w * 0.90)]
    dark = (strip.mean(axis=2) < 150)
    frac = dark.mean(axis=1)
    ink = runs(frac, thr=0.06, min_len=2)
    out["ink_bands_native"] = [[s + band_top, e + band_top] for s, e in ink]
    out["ink_bands_ref"] = [[to_ref(s + band_top), to_ref(e + band_top)] for s, e in ink]

    # ── 3. 底部 12% 的「版权/数值」区域墨迹 ──
    low = a[int(NATIVE[1] * 0.88):, :]
    out["bottom_ink_rows_ref"] = [
        to_ref(i + int(NATIVE[1] * 0.88)) for i in range(low.shape[0])
        if (low[i].mean(axis=1) < 150).mean() > 0.01
    ][:40]
    return out


def main() -> int:
    files = sorted(f for f in os.listdir(ASSETS) if f.lower().endswith(".png"))
    report = {"native": NATIVE, "ref": REF, "frames": []}
    print(f"{'file':<28} {'白色行区间(REF y)':<28} {'墨迹带(REF y)'}")
    print("-" * 100)
    for fn in files:
        try:
            r = analyse(os.path.join(ASSETS, fn))
        except Exception as e:
            print(f"{fn:<28} ERROR {e}")
            continue
        report["frames"].append(r)
        wr = r["white_row_runs_ref"][:3]
        ib = r["ink_bands_ref"][:4]
        print(f"{fn:<28} {str(wr):<28} {ib}")

    outp = os.path.join(ROOT, "workspace", "logs", "frame_measure.json")
    os.makedirs(os.path.dirname(outp), exist_ok=True)
    with open(outp, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n完整数据 -> {outp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
