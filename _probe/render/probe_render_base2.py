"""渲染基础层第二轮自测（只读素材、只写 _probe/）。

覆盖：
* 覆盖率挑字体（fonts.resolve_for / coverage_candidates）—— 中文不能变方框
* 素材缺失时的系统字体回退（把 fonts 的素材解析强制置空后诊断）
* 位图模块在 woff2 被清空后的兜底链路：ttf 缺失 → 由 fonts 转换 woff2 到缓存
* 路径解析的大小写/容错（lib.path）
* assets.measure() 度量缓存
* 素材缺失时的不抛异常承诺（随机乱名批量请求）
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(r"D:\游戏王DIY设计")
OUT = ROOT / "_probe" / "render"
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))

from cardforge.core import paths  # noqa: E402
from cardforge.render import assets, fonts  # noqa: E402

out: dict = {}
line = lambda m: print(m, flush=True)  # noqa: E731

# ── 0. 先把 SVG 缓存挪开：G 段要验证「钩子失败 → 降级」，缓存命中会掩盖它 ──
svg_cache_dir = paths.CACHE / "svg"
stash = None
if svg_cache_dir.is_dir() and any(svg_cache_dir.glob("*.png")):
    stash = svg_cache_dir.with_name("svg_probe_stash")
    if stash.is_dir():
        import shutil
        shutil.rmtree(stash, ignore_errors=True)
    svg_cache_dir.rename(stash)

# ── A. 覆盖率挑字体 ──────────────────────────────────────────────────
line("=" * 78)
line("[A] coverage() / resolve_for() —— 中文不得变方框")
CASES = [
    ("zh_cn", "通常怪兽 效果 魔法卡 陷阱卡 攻击力 守备力 灵摆 连接 超量 同调 融合 仪式"),
    ("ja", "モンスター 効果 魔法 罠 攻撃力 守備力 ペンデュラム エクシーズ"),
    ("en", "Warrior Effect Monster ATK/3200 DEF/2500 Link-4"),
    ("zh_tw", "協調 超量 靈擺 鏈接 怪獸 魔法 陷阱"),
]
for lang, text in CASES:
    p, role = fonts.resolve_for(text, lang)
    cov = fonts.coverage(p, text) if p else 0.0
    line(f"  {lang:6s} 最佳 role={role:8s} 覆盖={cov:.1%} font={p and Path(p).name}")
    assert p is not None, f"{lang} 挑不到字体"
    assert cov >= 1.0, f"{lang} 覆盖率不足 {cov:.1%} —— 会出现方框"
    out.setdefault("resolve_for", {})[lang] = {"role": role, "coverage": cov,
                                               "font": Path(p).name}

line("  候选打分（en 文本）：")
for path, score in fonts.coverage_candidates("ATK/3200 LINK", "en")[:8]:
    line(f"    {score:5.1%}  {Path(path).name}")
line("  候选打分（中文文本）：")
for path, score in fonts.coverage_candidates("青眼白龙 通常怪兽", "zh_cn")[:6]:
    line(f"    {score:5.1%}  {Path(path).name}")

# 方框检测：用挑出来的字体渲染中文，看字形是否真的不是 .notdef
from PIL import Image, ImageDraw  # noqa: E402

font = fonts.load_for("中文渲染测试 通常怪兽", 48, "zh_cn")
assert font is not None
img = Image.new("L", (900, 80), 0)
ImageDraw.Draw(img).text((8, 12), "中文渲染测试", font=font, fill=255)
ratio = sum(img.histogram()[16:]) / (img.width * img.height)
line(f"  load_for() 出字墨迹比例 = {ratio:.2%}（阈值 1%）")
assert ratio > 0.01
img.convert("RGB").save(OUT / "font_smoke_zh_load_for.png")
out["load_for_ink_ratio"] = round(ratio, 4)

# ── B. 素材缺失 → 系统字体回退（不写任何文件，纯内存降级）───────────
line("=" * 78)
line("[B] 素材字体全部置为不可用时的系统回退（monkeypatch，不落盘）")
real_materialize = fonts._materialize
try:
    fonts._materialize = lambda role: None          # 模拟 data/assets 里没有字体
    fonts.clear_cache()
    d = fonts.diagnose("zh_cn", text="通常怪兽 攻击力3200")
    for role, info in d["roles"].items():
        line(f"    {role:8s} source={info['source']:12s} fallback={info['fallback']} "
             f"cov={info['coverage']} -> {info['path']}")
    assert all(v["path"] for v in d["roles"].values()), "系统回退没兜住"
    zh = d["roles"]["sc"]
    assert zh["fallback"] and zh["source"].startswith("system"), "sc 没走系统回退"
    assert zh["coverage"] == 1.0, f"回退字体覆盖不了中文：{zh['coverage']}"
    f2 = fonts.load("sc", 40, "zh_cn")
    assert f2 is not None
    line(f"    回退后 load('sc',40) 可加载：{f2.getname()}")
    out["system_fallback"] = {r: {"path": v["path"], "coverage": v["coverage"]}
                              for r, v in d["roles"].items()}
    line(f"    notes = {d['notes']}")
finally:
    fonts._materialize = real_materialize
    fonts.clear_cache()

# ── C. woff2 → ttf 转换链路（在临时素材根上真跑一次，不碰 data/assets）──
line("=" * 78)
line("[C] woff2 → ttf 转换：在临时根上真跑（原素材只读）")
with tempfile.TemporaryDirectory(prefix="cf_font_probe_") as tmp:
    tmp_assets = Path(tmp) / "assets"
    tmp_assets.mkdir(parents=True)
    src = paths.ASSETS / "ygo-link.woff2"
    (tmp_assets / "ygo-link.woff2").write_bytes(src.read_bytes())
    real_assets, real_cache = paths.ASSETS, paths.CACHE
    paths.ASSETS = tmp_assets
    paths.CACHE = Path(tmp) / "cache"
    try:
        fonts.clear_cache()
        got = fonts._materialize("link")
        line(f"    _materialize('link') -> {got}")
        assert got is not None and got[1] == "converted", f"转换失败：{got}"
        conv = Path(got[0])
        assert conv.is_file() and conv.stat().st_size > 0
        line(f"    转换产物 {conv.name} {conv.stat().st_size} 字节（源 woff2 "
             f"{src.stat().st_size} 字节）")
        line(f"    sfnt 版本 = {__import__('fontTools.ttLib', fromlist=['TTFont']).TTFont(str(conv)).sfntVersion!r}")
        f3 = fonts.load("link", 40, "en")
        assert f3 is not None, "转换出来的 ttf 装不进 Pillow"
        line(f"    Pillow 可加载转换产物：{f3.getname()}")
        img = Image.new("L", (400, 60), 0)
        ImageDraw.Draw(img).text((8, 8), "LINK-4", font=f3, fill=255)
        r2 = sum(img.histogram()[16:]) / (img.width * img.height)
        line(f"    LINK-4 墨迹比例 = {r2:.2%}")
        assert r2 > 0.01
        out["woff2_convert"] = {"file": conv.name, "size": conv.stat().st_size,
                                "pillow_name": f3.getname(), "ink": round(r2, 4)}
        # 二次调用应命中缓存（source == cache-ttf）
        fonts.clear_cache()
        again = fonts._materialize("link")
        line(f"    二次 _materialize('link') -> {again[1]}（应命中 cache-ttf 不再转换）")
        assert again[1] == "cache-ttf", again
    finally:
        paths.ASSETS, paths.CACHE = real_assets, real_cache
        fonts.clear_cache()

# ── D. 路径解析大小写/容错 ───────────────────────────────────────────
line("=" * 78)
line("[D] AssetLibrary.path() 大小写不敏感与容错")
lib = assets.AssetLibrary()
for probe in ("frame/EFFECT.PNG", "FRAME/Effect.png", r"frame\effect.png",
              "Attribute/Dark.png", "STAR/LEVEL", "rare/pser-print",
              "icon/quick-play", "copyright/sc-black.svg", "frame\\Token.PNG"):
    hit = lib.path(probe)
    line(f"    {probe:28s} -> {paths.rel(hit) if hit else None}")
    assert hit is not None, f"{probe} 没解析出来"

# ── E. measure() 度量缓存 ────────────────────────────────────────────
line("=" * 78)
line("[E] assets.measure() 度量")
for role, txt, size in (("sc", "青眼白龙", 90), ("atk_def", "ATK/3200", 37),
                        ("en_name", "Blue-Eyes", 90)):
    w1 = lib.measure(role, txt, size)
    w2 = lib.measure(role, txt, size)
    line(f"    measure({role!r},{txt!r},{size}) = {w1}（二次调用 {w2}，应一致）")
    assert w1 == w2 and w1[0] > 0 and w1[1] > 0, (role, txt, w1)
line(f"    measure(不存在的 role) = {lib.measure('nope', 'x', 20)}（应 (0,0) 不抛异常）")

# ── F. 乱名批量请求：不抛异常、不误报 ────────────────────────────────
line("=" * 78)
line("[F] 乱名批量请求：承诺不抛异常")
junk = ["", "  ", "frame/", "../../etc/passwd", "attr/zzz", "star/", "rarity/xx",
        "\u0000bad", "a" * 300, "frame/effect.PNG.EXE"]
before = lib.missing()
errs = []
for name in junk:
    for fn in (lambda n: lib.frame(n), lambda n: lib.attribute(n),
               lambda n: lib.star(n), lambda n: lib.arrow(n),
               lambda n: lib.rarity_layer(n), lambda n: lib.icon(n),
               lambda n: lib.spell_trap_badge(n, n), lambda n: lib.copyright_mark(n),
               lambda n: lib.stamp(n)):
        try:
            fn(name)
        except Exception as exc:  # pragma: no cover
            errs.append(f"{name!r}: {type(exc).__name__}: {exc}")
line(f"    9 个 API × {len(junk)} 个乱名 = {9 * len(junk)} 次调用，异常数 = {len(errs)}")
assert not errs, errs
line(f"    新增 missing 登记 {len(lib.missing() - before)} 条（乱名不误判为素材）")

# ── G. 钩子未注入 / 钩子失败时的降级 ────────────────────────────────
line("=" * 78)
line("[G] set_svg_rasterizer 钩子行为（已先把 paths.CACHE/svg 缓存挪走）")
assets.set_svg_rasterizer(lambda s, d: None)
l2 = assets.AssetLibrary()
line(f"    钩子返回假值 -> copyright_mark('sc') = {l2.copyright_mark('sc')}（应 None）")
assert l2.copyright_mark("sc") is None
line(f"    且已记入 missing = {sorted(l2.missing())}")
assert "copyright/sc-black.svg" in l2.missing()
assets.set_svg_rasterizer(lambda s, d: (_ for _ in ()).throw(RuntimeError("boom")))
l3 = assets.AssetLibrary()
line(f"    钩子抛异常 -> copyright_mark('sc') = "
     f"{l3.copyright_mark('sc')}（应 None，不冒泡）")
assert l3.copyright_mark("sc") is None
assets.set_svg_rasterizer(None)
line(f"    恢复默认钩子 -> {assets.svg_rasterizer().__name__}")
l4 = assets.AssetLibrary()          # 新实例：l2 已把「失败」结果缓存进自身
img_ok = l4.copyright_mark("sc")
line(f"    默认钩子 -> copyright_mark('sc') = "
     f"{None if img_ok is None else (img_ok.size, img_ok.mode)}")
assert img_ok is not None
line(f"    并写回缓存 {paths.rel(paths.CACHE / 'svg')}："
     f"{sorted(p.name for p in (paths.CACHE / 'svg').glob('*.png'))}")
out["hook_degrade"] = {"failed_hook": "None + missing 登记",
                       "raising_hook": "None（异常被吞）",
                       "restored": "rasterize_svg"}

# ── 收尾：把挪走的 SVG 缓存放回去 ────────────────────────────────────
if stash is not None and stash.is_dir():
    import shutil
    shutil.rmtree(svg_cache_dir, ignore_errors=True)
    stash.rename(svg_cache_dir)
    line(f"    已把预光栅化缓存放回 {paths.rel(svg_cache_dir)}"
         f"（{len(list(svg_cache_dir.glob('*.png')))} 个 png）")

(OUT / "probe_report2.json").write_text(json.dumps(out, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
line("=" * 78)
line(f"第二轮全部通过。报告：{OUT / 'probe_report2.json'}")
