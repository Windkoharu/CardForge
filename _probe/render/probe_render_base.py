"""渲染基础层自测 —— 只读素材、只写 _probe/。

跑法：python "D:\\游戏王DIY设计\\_probe\\render\\probe_render_base.py"
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(r"D:\游戏王DIY设计")
OUT = ROOT / "_probe" / "render"
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from cardforge.core import paths  # noqa: E402
from cardforge.render import assets, fonts  # noqa: E402

report: dict = {}


def line(msg: str) -> None:
    print(msg, flush=True)


# ── 0. 环境 ──────────────────────────────────────────────────────────
line("=" * 78)
line("[0] 环境")
line(f"  ROOT     = {paths.ROOT}")
line(f"  ASSETS   = {paths.rel(paths.ASSETS)}  存在={paths.ASSETS.is_dir()}")
line(f"  CACHE    = {paths.rel(paths.CACHE)}")
import PIL  # noqa: E402
import fontTools  # noqa: E402
line(f"  Pillow {PIL.__version__} / fontTools {fontTools.version} / python {sys.version.split()[0]}")

# ── 1. availability + diagnose ───────────────────────────────────────
line("=" * 78)
line("[1] assets.library().availability() / fonts.diagnose()")
lib = assets.library()
avail = lib.availability()
diag = fonts.diagnose("zh_cn", text="通常怪兽 效果 魔法卡 陷阱卡 ATK/3200")
report["availability"] = avail
report["diagnose"] = diag
(OUT / "availability.json").write_text(
    json.dumps(avail, ensure_ascii=False, indent=2), encoding="utf-8")
(OUT / "diagnose.json").write_text(
    json.dumps(diag, ensure_ascii=False, indent=2), encoding="utf-8")

line(f"  素材根={avail['root']} exists={avail['exists']} files={avail['files']} "
     f"digest={avail['digest']}")
for cat, st in avail["categories"].items():
    flag = "OK " if st["present"] == st["total"] else "缺 "
    line(f"    {flag}{cat:11s} {st['present']:2d}/{st['total']:2d}"
         + (f"   缺={st['missing']}" if st["missing"] else ""))
line(f"  skipped(不算素材) = {len(avail['skipped'])} 项，例：{avail['skipped'][:3]}")
line(f"  unexpected(未登记) = {avail['unexpected']}")
line("  fonts.diagnose roles:")
for role, info in diag["roles"].items():
    line(f"    {role:8s} {str(info['source']):11s} fallback={str(info['fallback']):5s} "
         f"idx={info['index']} cov={info['coverage']} -> {info['path']}")
line(f"  stack(zh_cn)={diag['stack']}  svg_rasterizer={diag['svg_rasterizer']}")
line(f"  system_candidates={diag['system_candidates']}  ok={diag['ok']}")
line(f"  notes={diag['notes']}")

# ── 2. 卡框：尺寸 / 模式 / 平均 alpha ─────────────────────────────────
line("=" * 78)
line("[2] 逐张打开 frame/*.png：断言 1394x2031 + RGBA，并算平均 alpha")
from cardforge.render.geometry import FRAME_NATIVE  # noqa: E402

frame_dir = paths.ASSETS / "frame"
frames = sorted(frame_dir.glob("*.png"))
assert frames, "没找到任何卡框素材"
frame_rows = []
bad = []
for p in frames:
    with Image.open(p) as im:
        im.load()
        size, mode = im.size, im.mode
        alpha = im.convert("RGBA").getchannel("A")
        stat = alpha.getextrema()
        avg = sum(i * c for i, c in enumerate(alpha.histogram())) / (size[0] * size[1])
    ok = (size == FRAME_NATIVE) and (mode == "RGBA") and abs(avg - 255.0) < 0.5
    if not ok:
        bad.append(p.name)
    frame_rows.append({"file": p.name, "size": list(size), "mode": mode,
                       "alpha_min": stat[0], "alpha_max": stat[1],
                       "alpha_mean": round(avg, 4), "ok": ok})
    line(f"  {'OK ' if ok else 'BAD'} frame/{p.name:24s} {size} {mode} "
         f"alpha min/max/mean = {stat[0]}/{stat[1]}/{avg:.4f}")
assert not bad, f"卡框校验失败：{bad}"
report["frames"] = frame_rows
line(f"  => {len(frames)}/{len(frames)} 张卡框全部通过（不透明整图）")

# ── 3. 字体出字冒烟测试 ──────────────────────────────────────────────
line("=" * 78)
line("[3] fonts.load() 渲染 中文 / 日文 / 英文 / ATK-3200，断言非空像素 > 1%")

SAMPLES = [
    ("zh", "青眼白龙 通常怪兽 攻击力3200 守备力2500", "sc", "zh_cn"),
    ("ja", "モンスター 効果 攻撃力 守備力 テスト", "sc", "ja"),
    ("en", "Blue-Eyes White Dragon Effect Monster", "en_name", "en"),
    ("stat", "ATK/3200", "atk_def", "en"),
]
smoke_rows = []
for tag, text, role, lang in SAMPLES:
    font = fonts.load(role, 48, lang)
    assert font is not None, f"{tag}: fonts.load({role!r},{lang!r}) 返回 None"
    img = Image.new("L", (1600, 96), 0)
    from PIL import ImageDraw  # noqa: E402
    ImageDraw.Draw(img).text((8, 16), text, font=font, fill=255)
    hist = img.histogram()
    lit = sum(hist[16:])                     # 亮度 >=16 的算「有墨」
    ratio = lit / (img.width * img.height)
    box = img.getbbox()
    assert ratio > 0.01, f"{tag}: 非空像素比例只有 {ratio:.4%}"
    src = fonts.resolve(role, lang)
    cov = fonts.coverage(src, text)
    out = OUT / f"font_smoke_{tag}.png"
    img.convert("RGB").save(out)
    smoke_rows.append({"tag": tag, "role": role, "lang": lang, "text": text,
                       "font": src, "coverage": round(cov, 4),
                       "ink_ratio": round(ratio, 4), "bbox": box, "file": out.name})
    line(f"  OK  {tag:5s} role={role:8s} lang={lang:5s} font={Path(src).name:16s} "
         f"覆盖={cov:.0%} 墨迹={ratio:.2%} bbox={box} -> {out.name}")
report["font_smoke"] = smoke_rows

# ── 4. 属性圆标 / 魔陷徽记：列真实文件并断言取图成功 ─────────────────
line("=" * 78)
line("[4] data/assets 里实际存在的属性圆标与魔陷徽记")
attr_files = sorted(p.name for p in (paths.ASSETS / "attribute").glob("*.png"))
icon_files = sorted(p.name for p in (paths.ASSETS / "icon").glob("*.png"))
line(f"  attribute/ ({len(attr_files)}) = {attr_files}")
line(f"  icon/      ({len(icon_files)}) = {icon_files}")
report["attribute_files"] = attr_files
report["icon_files"] = icon_files

checks = [
    ("spell_trap_badge('spell','quick')", lib.spell_trap_badge("spell", "quick")),
    ("spell_trap_badge('spell','quick-play')", lib.spell_trap_badge("spell", "quick-play")),
    ("spell_trap_badge('trap','counter')", lib.spell_trap_badge("trap", "counter")),
    ("spell_trap_badge('spell','normal')", lib.spell_trap_badge("spell", "normal")),
    ("attribute('暗')", lib.attribute("暗")),
    ("attribute('DARK')", lib.attribute("DARK")),
    ("attribute('神')", lib.attribute("神")),
    ("star('level')", lib.star("level")),
    ("star('rank')", lib.star("rank")),
    ("arrow('右上')", lib.arrow("右上")),
    ("arrow('左下', on=False)", lib.arrow("左下", on=False)),
    ("rarity_layer('UR')", lib.rarity_layer("UR")),
    ("rarity_layer('pser-print')", lib.rarity_layer("pser-print")),
    ("laser(1)", lib.laser(1)),
    ("stamp('20th')", lib.stamp("20th")),
    ("stamp('twentieth')", lib.stamp("twentieth")),
    ("icon('field')", lib.icon("field")),
    ("card_back()", lib.card_back()),
    ("bleeds()", lib.bleeds()),
    ("frame('effect')", lib.frame("effect")),
    ("frame('effect', pendulum=True)", lib.frame("effect", pendulum=True)),
    ("frame('link')", lib.frame("link")),
    ("frame('token')", lib.frame("token")),
    ("frame('nope')", lib.frame("nope")),
]
line("  语义 API 命中情况：")
for name, img in checks:
    desc = "None" if img is None else f"{img.size} {img.mode}"
    line(f"    {name:36s} -> {desc}")
    report.setdefault("api_checks", {})[name] = desc

badge = lib.spell_trap_badge("spell", "quick")
assert badge is not None, "spell_trap_badge('spell','quick') 返回了 None"
assert badge.size == (72, 72), f"徽记尺寸异常：{badge.size}"
for key in ("暗", "光", "地", "水", "炎", "风", "神"):
    assert lib.attribute(key) is not None, f"属性 {key} 取不到"
line("  => 断言通过：spell_trap_badge('spell','quick') 真的返回了图像；7 个中文属性名全部命中")

# ── 5. SVG 光栅化（版权标）──────────────────────────────────────────
line("=" * 78)
line("[5] copyright_mark() SVG 光栅化（svglib → PDF → PyMuPDF，缓存到 paths.CACHE/svg）")
cop_rows = []
for lang in ("sc", "jp", "en", "zh_cn", "zh_tw", "ja", "en"):
    for color in ("black", "white"):
        im = lib.copyright_mark(lang, color)
        desc = "None" if im is None else f"{im.size} {im.mode}"
        cop_rows.append({"lang": lang, "color": color, "result": desc})
        line(f"    copyright_mark({lang!r},{color!r}) -> {desc}")
        assert im is not None, f"copyright_mark({lang!r},{color!r}) 返回 None"
report["copyright"] = cop_rows
svg_cache = sorted(p.name for p in (paths.CACHE / "svg").glob("*.png")) \
    if (paths.CACHE / "svg").is_dir() else []
line(f"  SVG 缓存目录 {paths.rel(paths.CACHE / 'svg')} 内容 = {svg_cache}")

# ── 6. 缺失降级 / 指纹 ───────────────────────────────────────────────
line("=" * 78)
line("[6] 优雅降级 + 指纹")
line(f"  missing() = {sorted(lib.missing())}")
before = lib.digest()
lib.reset()
after = lib.digest()
line(f"  digest 重置前后一致 = {before == after} ({before} / {after})")
line(f"  未注入光栅化钩子时：set_svg_rasterizer(None) -> "
     f"{assets.svg_rasterizer().__name__}（默认实现）")
report["missing"] = sorted(lib.missing())
report["digest"] = after

(OUT / "probe_report.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
line("=" * 78)
line(f"全部通过。报告：{OUT / 'probe_report.json'}")
