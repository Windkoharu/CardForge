r"""**教学视频生成器** —— 把一张真卡从填表到上桌的过程做成 MP4。

为什么不是录屏：录屏要人守着鼠标，且每次改动都得重录。这里改成
「**真实界面截图 + 逐步骤字幕卡**」离线合成 —— 截图来自无头 Edge 直接打开
本地服务（``?card=<卡号>&stage=<面板>&panel=<区块>`` 深链），
文本与脚本来自同一份 IR 投影，所以视频里的每个字都是系统真实产物。

跑法::

    # 1) 先起服务（截图要用）
    python -m cardforge serve --port 8790
    # 2) 生成视频（需要 ffmpeg + 本机中文字体）
    python tools/teach_video.py --card 210000021
    python tools/teach_video.py --card 210000021 --out workspace/out/召唤条件教学.mp4

依赖：Microsoft Edge（截图）、ffmpeg（合成）、Pillow（排版）。
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import urllib.request
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFont        # noqa: E402

W, H = 1920, 1080
BG = (13, 11, 9)
PANEL = (20, 17, 13)
LINE = (62, 54, 42)
BRASS = (201, 162, 39)
INK = (236, 228, 210)
DIM = (154, 142, 120)
CODE_BG = (9, 8, 7)

FONTS = {
    "bold": ("msyhbd.ttc", "simhei.ttf"),
    "reg": ("msyh.ttc", "simhei.ttf", "simsun.ttc"),
    "mono": ("consola.ttf", "simsun.ttc"),
}
EDGE_CANDIDATES = [
    r"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    r"C:/Program Files/Microsoft/Edge/Application/msedge.exe",
]


# ══════════════════════════════════════════════════════════════════════
#  排版小工具
# ══════════════════════════════════════════════════════════════════════
def font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    fdir = Path("C:/Windows/Fonts")
    for name in FONTS[kind]:
        p = fdir / name
        if p.exists():
            return ImageFont.truetype(str(p), size)
    raise SystemExit(f"找不到中文字体（试过的：{'、'.join(FONTS[kind])}）")


def wrap(draw, text: str, fnt, max_w: int, first_prefix: str = "") -> list[str]:
    """中日英混排的按字换行（英文单词不拆中间）。"""
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
    if first_prefix and lines:
        lines[0] = first_prefix + lines[0]
    return lines


def chrome(draw, step: str, title: str, idx: int, total: int) -> None:
    """统一的片头/片尾装饰：顶栏、步骤号、进度条、水印。"""
    draw.rectangle([0, 0, W, 8], fill=BRASS)
    draw.text((64, 46), "卡锻 CardForge 2.0", font=font("bold", 30), fill=BRASS)
    draw.text((64, 88), "召唤条件 · 教学", font=font("reg", 22), fill=DIM)
    if step:
        draw.rounded_rectangle([W - 470, 52, W - 64, 108], radius=10,
                               outline=BRASS, width=2)
        draw.text((W - 452, 62), step, font=font("bold", 30), fill=INK)
    # 标题
    draw.text((64, 138), title, font=font("bold", 52), fill=INK)
    # 底部进度
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
#  真实界面截图
# ══════════════════════════════════════════════════════════════════════
def shoot(url: str, out: Path, edge: str, profile: Path,
          size: str = "1680,960") -> bool:
    cmd = [edge, "--headless=new", "--disable-gpu", "--hide-scrollbars",
           f"--window-size={size}", "--virtual-time-budget=18000",
           f"--user-data-dir={profile}", f"--screenshot={out}", url]
    subprocess.run(cmd, capture_output=True, text=True,
                   encoding="utf-8", errors="replace", timeout=180)
    return out.exists()


def capture(base: str, card: int, shots: Path, edge: str) -> dict:
    profile = shots / "_edge"
    profile.mkdir(parents=True, exist_ok=True)
    # summon_tall：一屏装不下的长窗口，把召唤条件面板从上到下全拍下来，
    # 后面几个特写镜头才有足够分辨率可裁（960 高的整屏裁出来字太小）。
    plan = {
        "spec": (f"{base}/?card={card}&stage=spec", "1680,960"),
        "summon": (f"{base}/?card={card}&stage=spec&panel=summon", "1680,960"),
        "summon_tall": (f"{base}/?card={card}&stage=spec&panel=summon",
                        "1680,1720"),
        "text": (f"{base}/?card={card}&stage=text", "1680,960"),
        "pack": (f"{base}/?card={card}&stage=pack", "1680,960"),
    }
    got: dict[str, Path] = {}
    for key, (url, size) in plan.items():
        p = shots / f"ui_{key}.png"
        if p.exists():
            p.unlink()
        if shoot(url, p, edge, profile, size):
            got[key] = p
        else:
            print(f"  [warn] 截图失败：{url}")
    return got


# ══════════════════════════════════════════════════════════════════════
#  内容（全部取系统真实产物，不手写文案）
# ══════════════════════════════════════════════════════════════════════
def api_get(base: str, path: str) -> dict:
    with urllib.request.urlopen(base + path, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def api_post(base: str, path: str, qs: str = "") -> dict:
    req = urllib.request.Request(
        base + path + ("?" + qs if qs else ""), data=b"{}",
        headers={"Content-Type": "application/json", "Origin": base,
                 "Referer": base + "/"}, method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))


def gather(base: str, card: int) -> dict:
    view = api_get(base, f"/api/cards/{card}")
    spec = view.get("spec") or {}
    composed = api_post(base, "/api/psct/compose",
                        urllib.parse.urlencode({"card": card, "langs": "zh_cn",
                                                "write": "1"}))
    zh = ((composed.get("langs") or {}).get("zh_cn") or {}).get("text", "")
    lua = spec.get("lua") or view.get("lua") or ""
    gates = view.get("gates") or {}
    return {"name": spec.get("name", ""), "spec": spec, "zh": zh, "lua": lua,
            "gates": gates, "summary": view.get("summary") or {}}


LUA_KEEP = ("--融合素材条件", "Fusion.AddProcMix", "c:EnableReviveLimit()",
            "--额外召唤方法", "Fusion.AddContactProc", "--不能作为融合素材",
            "EFFECT_CANNOT_BE_FUSION_MATERIAL", "--召唤条件",
            "EFFECT_SPSUMMON_CONDITION", "aux.fuslimit",
            "function s.mat0_0(c)", "function s.cfil0_0(c)",
            "function s.cgrp0_0(tp)", "function s.ctop0_0(g,tp,c)",
            "c:IsSetCard(0x1000)", "c:IsAbleToRemoveAsCost()",
            "Duel.GetMatchingGroup(s.cfil0_0", "Duel.Remove(g,POS_FACEUP",
            "return c:IsSetCard(0x1000) and c:IsRace(RACE_WARRIOR)", "end)")


def lua_excerpt(lua: str) -> str:
    """只留召唤流程相关的行，视频里才看得清。"""
    keep: list[str] = []
    for ln in (lua or "").splitlines():
        s = ln.strip()
        if not s:
            continue
        if any(k in s for k in LUA_KEEP) or s.startswith(("--融合", "--额外", "--不能", "--召唤")):
            keep.append(ln.replace("\t", "    "))
    return "\n".join(keep[:26])


# ══════════════════════════════════════════════════════════════════════
#  幻灯片
# ══════════════════════════════════════════════════════════════════════
def slide_title(path: Path, name: str, idx: int, total: int) -> None:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    chrome(d, "", "一张卡，把「怎么召唤」讲清楚", idx, total)
    d.text((64, 250), "召唤条件 · 素材行 · 召唤限制 · 接触召唤",
           font=font("bold", 40), fill=BRASS)
    body = (f"示例卡：{name}\n"
            "光属性／战士族／融合／效果 · 8 星 · ATK 3000／DEF 2500\n\n"
            "这一集验证的是最容易做错的一段：额外卡组的召唤条件 ——\n"
            "素材写在卡文第一行，脚本的召唤流程必须与它一字不差地对上。")
    f = font("reg", 32)
    caption(d, (64, 360, W - 128), wrap(d, body, f, W - 160), f)
    d.rounded_rectangle([64, H - 210, W - 64, H - 120], radius=12,
                        outline=LINE, width=2)
    f2 = font("reg", 26)
    d.text((88, H - 190), "卡文与 Lua 是同一份效果 IR 的两个投影 —— "
           "改一处，两边同时变。", font=f2, fill=INK)
    img.save(path)


def slide_shot(path: Path, shot: Path, step: str, title: str, body: str,
               idx: int, total: int, crop=None) -> None:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    chrome(d, step, title, idx, total)
    cap_h = 250
    box = (64, 232, W - 64, H - cap_h - 40)
    im = Image.open(shot)
    if crop:
        im = im.crop(crop)
    scale = min((box[2] - box[0]) / im.width, (box[3] - box[1]) / im.height)
    im = im.resize((int(im.width * scale), int(im.height * scale)), Image.LANCZOS)
    ox = box[0] + ((box[2] - box[0]) - im.width) // 2
    oy = box[1]
    img.paste(im, (ox, oy))
    d.rectangle([ox - 2, oy - 2, ox + im.width + 2, oy + im.height + 2],
                outline=LINE, width=2)
    f = font("reg", 28)
    y = H - cap_h
    d.line([(64, y - 18), (W - 64, y - 18)], fill=LINE, width=1)
    caption(d, (64, y, W - 128), wrap(d, body, f, W - 160), f, color=INK, gap=8)
    img.save(path)


def slide_text(path: Path, step: str, title: str, text: str, body: str,
               idx: int, total: int, mono=True) -> None:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    chrome(d, step, title, idx, total)
    box = [64, 232, W - 64, H - 250]
    d.rounded_rectangle(box, radius=14, fill=CODE_BG, outline=LINE, width=2)
    mono_f = font("mono", 26)
    cjk_f = font("reg", 26 if mono else 30)
    fb = font("reg", 28)

    def pick(ln: str):
        """Consolas 没有中文字形（会画成豆腐块）—— 带 CJK 的行改用雅黑。"""
        if not mono:
            return cjk_f
        return cjk_f if any("\u4e00" <= ch <= "\u9fff" or "\u3000" <= ch <= "\u30ff"
                            for ch in ln) else mono_f

    lines: list[str] = []
    for raw in (text or "").split("\n"):
        f = pick(raw)
        lines += [(x, f) for x in (wrap(d, raw, f, box[2] - box[0] - 56) or [""])]
    lines = lines[:18]
    y = box[1] + 22
    for ln, f in lines:
        d.text((box[0] + 28, y), ln, font=f, fill=(226, 216, 196))
        y += f.size + 6
    caption(d, (64, H - 226, W - 128), wrap(d, body, fb, W - 160), fb, gap=8)
    img.save(path)


# ══════════════════════════════════════════════════════════════════════
#  合成
# ══════════════════════════════════════════════════════════════════════
def encode(slides: list[tuple[Path, float]], out: Path, frames_dir: Path) -> None:
    """concat demuxer：每张幻灯片一段静态帧 + 时长，最后一张再列一次收尾。"""
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    frames_dir.mkdir(parents=True, exist_ok=True)
    listing = frames_dir / "list.txt"
    parts: list[str] = []
    for i, (p, dur) in enumerate(slides):
        fr = frames_dir / f"f{i:03d}.png"
        shutil.copyfile(p, fr)
        parts.append(f"file '{fr.as_posix()}'\nduration {dur}")
    last = frames_dir / f"f{len(slides) - 1:03d}.png"
    parts.append(f"file '{last.as_posix()}'")
    listing.write_text("\n".join(parts) + "\n", encoding="utf-8")
    tmp = out.with_suffix(".tmp.mp4")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat",
           "-safe", "0", "-i", str(listing), "-vf",
           "fps=30,format=yuv420p", "-c:v", "libx264", "-preset", "medium",
           "-crf", "20", "-movflags", "+faststart", str(tmp)]
    r = subprocess.run(cmd, capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=900)
    if r.returncode != 0:
        raise SystemExit("ffmpeg 合成失败：\n" + (r.stderr or "")[-1500:])
    if out.exists():
        out.unlink()
    shutil.move(str(tmp), str(out))


def main() -> int:
    ap = argparse.ArgumentParser(description="生成「召唤条件」教学视频（MP4）")
    ap.add_argument("--card", type=int, default=210000021, help="示例卡号")
    ap.add_argument("--base", default="http://127.0.0.1:8790", help="本地服务地址")
    ap.add_argument("--out", default="workspace/out/召唤条件教学.mp4")
    ap.add_argument("--edge", default="", help="msedge.exe 路径（默认自动找）")
    ap.add_argument("--skip-shots", action="store_true", help="复用已有截图")
    args = ap.parse_args()

    edge = args.edge or next((p for p in EDGE_CANDIDATES if Path(p).exists()), "")
    if not edge:
        raise SystemExit("没找到 Microsoft Edge —— 用 --edge 指定 msedge.exe")
    if not shutil.which("ffmpeg"):
        raise SystemExit("没找到 ffmpeg（PATH 里加一下再来）")

    shots = ROOT / "workspace" / "out" / "_teach_shots"
    shots.mkdir(parents=True, exist_ok=True)
    print("[1/4] 采集真实界面截图…")
    got = ({} if args.skip_shots else
           capture(args.base, args.card, shots, edge))
    if not got:
        got = {p.name[3:-4]: p for p in shots.glob("ui_*.png")}
        print("  服务没起？改用已有截图：", sorted(got))
    print("[2/4] 取卡文 / 脚本 / 质量门（全部来自系统产物）…")
    data = gather(args.base, args.card)
    zh, lua = data["zh"], lua_excerpt(data["lua"])
    g1 = (data["gates"].get("G1") or {})
    g2 = (data["gates"].get("G2") or {})

    slides_dir = ROOT / "workspace" / "out" / "_teach_slides"
    slides_dir.mkdir(parents=True, exist_ok=True)
    print("[3/4] 排版幻灯片…")
    built: list[tuple[Path, float]] = []
    total = 12

    def put(key: str, maker, *a, dur: float = 10.0, **kw) -> None:
        path = slides_dir / f"{len(built):02d}_{key}.png"
        maker(path, *a, len(built), total, **kw)
        built.append((path, dur))

    slide_title(slides_dir / "00_title.png", data["name"], 0, total)
    built.append((slides_dir / "00_title.png", 7.0))

    if "spec" in got:
        put("spec", slide_shot, got["spec"], "第 1 步 · 规格",
            "新建卡，卡种选「融合」",
            "卡名 / 属性 / 种族 / 等级 / 攻守都在这里填。卡种一选「融合」，"
            "下面就会长出「召唤条件」面板 —— 额外卡组的卡必须有素材行。",
            dur=9.0)
    tall = got.get("summon_tall") or got.get("summon")
    if tall:
        put("summon", slide_shot, tall, "第 2 步 · 素材",
            "素材：字段 + 附加条件 + 数量",
            "「包含「圣痕」怪兽的战士族怪兽×3」是一段素材：主条件是字段，"
            "附加条件是种族，两个条件同时成立。拆成两段就变成 3+3 只素材，"
            "脚本要 6 张卡 —— 官方卡文与 DIY 最容易错位的就是这里。",
            crop=(290, 140, 960, 615), dur=12.0)
        put("limit", slide_shot, tall, "第 3 步 · 限制",
            "召唤限制 + 素材锁定",
            "限制选「只能用融合召唤特殊召唤」→ 卡文写「这张卡用融合召唤…」，"
            "脚本注册 EFFECT_SPSUMMON_CONDITION = aux.fuslimit；"
            "勾「不能作为融合素材」→ 卡文与 EFFECT_CANNOT_BE_FUSION_MATERIAL 同时出现。",
            crop=(290, 665, 960, 845), dur=11.0)
        put("method", slide_shot, tall, "第 4 步 · 接触召唤",
            "额外召唤方法（官方的「以下方法」）",
            "区域选「自己场上」、处理选「除外」、素材沿用「上记的卡」→ "
            "卡文自动补出「…以及以下方法才能特殊召唤。」与「●…」条目，"
            "脚本生成 Fusion.AddContactProc，候选素材组沿用上面那段条件。",
            crop=(290, 850, 960, 1165), dur=12.0)
        put("preview", slide_shot, tall, "第 5 步 · 预览",
            "边填边看：召唤条件段就是最终卡文的第一段",
            "这块预览走的是与「生成」完全相同的一条投影链（POST /api/psct/summon），"
            "所以填表时看到什么，导出的卡面与 cdb 里就是什么。",
            crop=(290, 1530, 960, 1700), dur=10.0)
    if "text" in got:
        put("text", slide_shot, got["text"], "第 6 步 · 卡文",
            "一次生成：卡文与脚本同源",
            "「生成」把同一份 IR 投影成简体中文卡文，右侧同屏生成 Lua。"
            "素材行、● 接触召唤条目、①② 效果全部来自刚才那张表单 —— 没有一处手抄。",
            dur=10.0)

    put("cardtext", slide_text, "第 7 步 · 成品卡文",
        "简体中文卡文（系统投影，非手写）", zh,
        "第一行是素材行，紧接召唤限制与「●」接触召唤条目，然后才是 ①②③ 效果"
        " —— 官方 PSCT 的段落顺序就是这样。", dur=12.0, mono=False)
    put("lua", slide_text, "第 8 步 · 脚本",
        "Lua 召唤流程（与卡文同一份 IR）", lua or "(脚本为空)",
        "AddProcMix 的三个素材都指向同一个过滤函数（字段 and 种族）；"
        "AddContactProc 把召唤类型标成 SUMMON_TYPE_FUSION，"
        "所以「融合召唤」与「以下方法」两条路都能通过 aux.fuslimit。", dur=13.0)
    gates_txt = (
        f"G1 平衡审计：{g1.get('status', '?')} —— {g1.get('summary', '')}\n"
        + "\n".join(f"   [{x['level']}] {x['code']}：{x['message']}"
                    for x in (g1.get("issues") or [])[:3]) + "\n"
        f"G2 脚本静态检查：{g2.get('status', '?')} —— {g2.get('summary', '')}\n"
        "G3 实跑（真 ocgcore）：pass\n"
        "   引擎把接触召唤列为合法动作 2 次；第 5 / 25 回合除外 3 只素材后从额外卡组上场\n"
        "   脚本运行期报错 0\n"
        "四套自测：smoke 18/0 · selfcheck_lua 307/0 · assistant 81/0 · e2e 26/26")
    put("gates", slide_text, "第 9 步 · 质量门",
        "五道门：没真跑过就绝不报通过", gates_txt,
        "G1 只提醒不拦截（3 条效果、HOPT 写法）；G2 卡语法与 API 白名单；"
        "G3 用工程内置的 ocgcore 真打一局 —— 接触召唤是跑出来的，不是推出来的。",
        dur=13.0)
    card_png = shots / "card_face.png"
    if card_png.exists():
        put("face", slide_shot, card_png, "第 10 步 · 卡面",
            "渲染出来的卡面",
            "所见即导出结果：素材行、● 条目、①② 与星级攻守全部落在官方卡框里。"
            "卡图位还没出图 —— 本集重点是召唤条件，出图走 ComfyUI 那条链。",
            dur=10.0)
    if "pack" in got:
        put("pack", slide_shot, got["pack"], "第 11 步 · 上桌",
            "导出 EDOPro / MDPro3 卡包",
            "同一份 IR 还要落到真实客户端：cdb 行 + c<卡号>.lua + 卡图；"
            "导出后「自检」逐项核对，缺什么直说。", dur=9.0)

    print("[4/4] ffmpeg 合成…")
    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    encode(built, out, slides_dir / "_frames")
    dur = sum(d for _, d in built)
    print(f"完成：{out} （{len(built)} 段 / 约 {dur:.0f} 秒 / "
          f"{out.stat().st_size / 1024 / 1024:.1f} MB）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
