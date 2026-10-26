# -*- coding: utf-8 -*-
"""教学视频的公共排版件：片头 chrome / 截图卡 / 文本卡 / SRT / 章节 / 合成。

为什么单独抽出来：``tools/teach_video.py`` 是「召唤条件」那一集的生成器，
已经能复现；新的一集（实战案例）需要同一套版式但不同分镜。把版式放这里，
两集各自只管内容，谁也不动谁 —— 免得改一集把另一集的成片改坏。

依赖：Pillow（排版）、ffmpeg（合成）、Windows 系统字体（雅黑/黑体/Consolas）。
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1920, 1080
BG = (13, 11, 9)
LINE = (62, 54, 42)
BRASS = (201, 162, 39)
INK = (236, 228, 210)
DIM = (154, 142, 120)
CODE_BG = (9, 8, 7)
ACCENT = (232, 197, 84)

FONTS = {
    "bold": ("msyhbd.ttc", "simhei.ttf"),
    "reg": ("msyh.ttc", "simhei.ttf", "simsun.ttc"),
    "mono": ("consola.ttf", "simsun.ttc"),
}

__all__ = ["W", "H", "font", "wrap", "chrome", "caption", "title_slide",
           "shot_slide", "text_slide", "write_srt", "write_chapters",
           "encode", "Slide"]


def font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    fdir = Path("C:/Windows/Fonts")
    for name in FONTS[kind]:
        p = fdir / name
        if p.exists():
            return ImageFont.truetype(str(p), size)
    raise SystemExit(f"找不到中文字体（试过：{'、'.join(FONTS[kind])}）")


def wrap(draw, text: str, fnt, max_w: int) -> list[str]:
    """中日英混排按字换行（英文单词不拆中间）。"""
    lines: list[str] = []
    for para in (text or "").split("\n"):
        cur = ""
        for ch in para:
            trial = cur + ch
            if draw.textlength(trial, font=fnt) <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = ch.lstrip()
        lines.append(cur)
    return lines


def chrome(draw, step: str, title: str, idx: int, total: int,
           *, kicker: str = "") -> None:
    """统一的片头/片尾装饰：顶栏、步骤号、进度条、水印。"""
    draw.rectangle([0, 0, W, 8], fill=BRASS)
    draw.text((64, 46), "卡锻 CardForge 2.0", font=font("bold", 30), fill=BRASS)
    draw.text((64, 88), kicker or "实战案例 · 教学", font=font("reg", 22), fill=DIM)
    if step:
        draw.rounded_rectangle([W - 470, 52, W - 64, 108], radius=10,
                               outline=BRASS, width=2)
        draw.text((W - 452, 62), step, font=font("bold", 30), fill=INK)
    draw.text((64, 138), title, font=font("bold", 52), fill=INK)
    y = H - 54
    draw.text((64, y - 8), "卡锻 2.0 · 本地优先的游戏王 DIY 工坊",
              font=font("reg", 20), fill=DIM)
    bar_x, bar_w = W - 520, 456
    draw.rectangle([bar_x, y + 4, bar_x + bar_w, y + 10], fill=LINE)
    draw.rectangle([bar_x, y + 4, bar_x + int(bar_w * (idx + 1) / total), y + 10],
                   fill=BRASS)


def caption(draw, box, lines, fnt, color=INK, gap=12) -> int:
    x, y, w = box
    for ln in lines:
        draw.text((x, y), ln, font=fnt, fill=color)
        y += fnt.size + gap
    return y


# ══════════════════════════════════════════════════════════════════════
#  三种版面
# ══════════════════════════════════════════════════════════════════════
def title_slide(path: Path, *, title: str, subtitle: str, bullets: list[str],
                idx: int, total: int, kicker: str = "") -> None:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    chrome(d, "", title, idx, total, kicker=kicker)
    d.text((64, 250), subtitle, font=font("bold", 40), fill=BRASS)
    y = 360
    f = font("reg", 32)
    for b in bullets:
        for i, ln in enumerate(wrap(d, b, f, W - 200)):
            d.text((64 + (0 if i == 0 else 28), y), ("• " if i == 0 else "") + ln,
                   font=f, fill=INK)
            y += f.size + 10
        y += 6
    img.save(path)


def shot_slide(path: Path, shot: Path, *, step: str, title: str, body: str,
               idx: int, total: int, crop: tuple | None = None,
               kicker: str = "", badge: str = "") -> None:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    chrome(d, step, title, idx, total, kicker=kicker)
    cap_h = 250
    box = (64, 232, W - 64, H - cap_h - 40)
    im = Image.open(shot).convert("RGB")
    if crop:
        im = im.crop(crop)
    scale = min((box[2] - box[0]) / im.width, (box[3] - box[1]) / im.height)
    im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))),
                   Image.LANCZOS)
    ox = box[0] + ((box[2] - box[0]) - im.width) // 2
    oy = box[1]
    img.paste(im, (ox, oy))
    d.rectangle([ox - 2, oy - 2, ox + im.width + 2, oy + im.height + 2],
                outline=LINE, width=2)
    if badge:
        # 角标画在图上会压住界面里的字（顶部是标签页、底部是按钮），
        # 改成字幕前缀：既不遮内容，也把「这是真截图」说清楚。
        body = f"〔{badge}〕" + body
    f = font("reg", 28)
    y = H - cap_h
    d.line([(64, y - 18), (W - 64, y - 18)], fill=LINE, width=1)
    caption(d, (64, y, W - 128), wrap(d, body, f, W - 160), f, color=INK, gap=8)
    img.save(path)


def text_slide(path: Path, *, step: str, title: str, text: str, body: str,
               idx: int, total: int, mono: bool = True,
               kicker: str = "") -> None:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    chrome(d, step, title, idx, total, kicker=kicker)
    box = [64, 232, W - 64, H - 250]
    d.rounded_rectangle(box, radius=14, fill=CODE_BG, outline=LINE, width=2)
    fb = font("reg", 28)
    inner_w = box[2] - box[0] - 56

    def lay(size: int):
        """按字号排一遍，返回 [(行文本, 字体)]。"""
        cjk_f = font("reg", size if mono else size + 2)
        mono_f = font("mono", size)

        def pick(ln: str):
            """Consolas 没有中文字形（会画成豆腐块）—— 带 CJK 的行改用雅黑。"""
            if not mono:
                return cjk_f
            return cjk_f if any("\u4e00" <= ch <= "\u9fff" or "\u3000" <= ch <= "\u30ff"
                                for ch in ln) else mono_f

        rows: list[tuple[str, object]] = []
        for raw in (text or "").split("\n"):
            f = pick(raw)
            rows += [(x, f) for x in (wrap(d, raw, f, inner_w) or [""])]
        return rows

    # 自动缩字号：段落多的时候往下退，绝不画到框外面（画出去就会压住字幕）。
    avail = box[3] - box[1] - 40
    rows = lay(26)
    for size in (26, 25, 24, 23, 22, 21, 20):
        rows = lay(size)
        height = sum(f.size + 5 for _, f in rows)
        if height <= avail:
            break
    y = box[1] + 20
    for ln, f in rows:
        if y + f.size > box[3] - 8:
            break
        d.text((box[0] + 28, y), ln, font=f, fill=(226, 216, 196))
        y += f.size + 5
    caption(d, (64, H - 226, W - 128), wrap(d, body, fb, W - 160), fb, gap=8)
    img.save(path)


# ══════════════════════════════════════════════════════════════════════
#  字幕 / 章节 / 合成
# ══════════════════════════════════════════════════════════════════════
@dataclass
class Slide:
    """一张幻灯片：图片路径 + 停留秒数 + 字幕（SRT 用）。"""
    path: Path
    dur: float
    caption: str = ""
    chapter: str = ""
    meta: dict = field(default_factory=dict)


def _ts(sec: float) -> str:
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(slides: list[Slide], path: Path) -> int:
    """每张幻灯片一条字幕（时长与画面一致）。返回条数。"""
    out: list[str] = []
    t = 0.0
    n = 0
    for s in slides:
        if not (s.caption or "").strip():
            t += s.dur
            continue
        n += 1
        out += [str(n), f"{_ts(t)} --> {_ts(t + s.dur)}", s.caption.strip(), ""]
        t += s.dur
    path.write_text("\n".join(out), encoding="utf-8")
    return n


def write_chapters(slides: list[Slide], path: Path) -> int:
    """按 ``Slide.chapter`` 分组写 ffmetadata 章节。返回章节数。"""
    rows: list[tuple[str, float, float]] = []
    t = 0.0
    for s in slides:
        if s.chapter:
            if rows and rows[-1][0] == s.chapter:
                rows[-1] = (rows[-1][0], rows[-1][1], t + s.dur)
            else:
                rows.append((s.chapter, t, t + s.dur))
        t += s.dur
    lines = [";FFMETADATA1"]
    for name, start, end in rows:
        lines += ["[CHAPTER]", "TIMEBASE=1/1000",
                  f"START={int(round(start * 1000))}", f"END={int(round(end * 1000))}",
                  "title=" + name]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(rows)


def encode(slides: list[Slide], out: Path, frames_dir: Path,
           *, chapters: Path | None = None, crf: int = 20) -> Path:
    """concat demuxer：每张静态帧 + 停留时长 → H.264 MP4。"""
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    frames_dir.mkdir(parents=True, exist_ok=True)
    listing = frames_dir / "list.txt"
    parts: list[str] = []
    for i, s in enumerate(slides):
        if not s.path.exists():
            raise SystemExit(f"缺幻灯片：{s.path}")
        fr = frames_dir / f"f{i:03d}.png"
        shutil.copyfile(s.path, fr)
        parts.append(f"file '{fr.as_posix()}'\nduration {s.dur}")
    parts.append(f"file '{(frames_dir / f'f{len(slides) - 1:03d}.png').as_posix()}'")
    listing.write_text("\n".join(parts) + "\n", encoding="utf-8")

    tmp = out.with_suffix(".tmp.mp4")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
           "-i", str(listing)]
    if chapters is not None and chapters.exists():
        cmd += ["-i", str(chapters), "-map", "0:v", "-map_metadata", "1"]
    cmd += ["-vf", "fps=30,format=yuv420p", "-c:v", "libx264", "-preset", "medium",
            "-crf", str(crf), "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            str(tmp)]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=1800)
    if r.returncode != 0:
        raise SystemExit("ffmpeg 合成失败：\n" + (r.stderr or "")[-1500:])
    if out.exists():
        out.unlink()
    shutil.move(str(tmp), str(out))
    return out
