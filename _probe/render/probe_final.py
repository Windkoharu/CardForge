"""渲染基础层收尾校验：包导出面 / 用户指定命令 / 视觉产物核对。"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(r"D:\游戏王DIY设计")
OUT = ROOT / "_probe" / "render"
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))
line = lambda m: print(m, flush=True)  # noqa: E731

# ── A. 用户指定的那条命令（写成 JSON 再读，绕开控制台代码页）────────
line("=" * 78)
line("[A] python -c \"... from cardforge.render import assets,fonts; "
     "print(assets.library().availability()); print(fonts.diagnose())\"")
cmd = ("import sys,json;sys.path.insert(0,r'D:\\游戏王DIY设计');"
       "from cardforge.render import assets,fonts;"
       "open(r'D:\\游戏王DIY设计\\_probe\\render\\spec_cmd.json','w',encoding='utf-8')"
       ".write(json.dumps({'availability':assets.library().availability(),"
       "'diagnose':fonts.diagnose()},ensure_ascii=False,indent=2))")
proc = subprocess.run([sys.executable, "-c", cmd], capture_output=True, text=True,
                      encoding="utf-8", errors="replace")
line(f"  returncode = {proc.returncode}")
line(f"  stdout = {proc.stdout.strip()!r}   stderr = {proc.stderr.strip()[:300]!r}")
assert proc.returncode == 0, proc.stderr
spec = json.loads((OUT / "spec_cmd.json").read_text(encoding="utf-8"))
line(f"  availability.digest = {spec['availability']['digest']}  "
     f"files = {spec['availability']['files']}")
line("  availability.categories：")
for cat, st in spec["availability"]["categories"].items():
    line(f"    {cat:11s} {st['present']:2d}/{st['total']:2d}"
         + (f"  缺 {st['missing']}" if st["missing"] else ""))
line(f"  availability.unexpected = {spec['availability']['unexpected']}")
line("  diagnose.roles：")
for role, info in spec["diagnose"]["roles"].items():
    line(f"    {role:8s} source={info['source']:11s} fallback={info['fallback']} "
         f"-> {info['path']}")
line(f"  diagnose.cache = {spec['diagnose']['cache']}")
line(f"  diagnose.ok = {spec['diagnose']['ok']}  "
     f"svg_rasterizer = {spec['diagnose']['svg_rasterizer']}")

# ── B. 包导出面（__init__ 只做 re-export）───────────────────────────
line("=" * 78)
line("[B] cardforge.render 惰性 re-export 面")
import cardforge.render as R  # noqa: E402

missing = []
for name in R.__all__:
    try:
        getattr(R, name)
    except Exception as exc:
        missing.append(f"{name}: {type(exc).__name__}: {exc}")
line(f"  __all__ 共 {len(R.__all__)} 个名字，取不到的 = {missing or '（无）'}")
assert not missing
line(f"  dir() 有 __getattr__/__dir__ = "
     f"{hasattr(R, '__getattr__')}/{hasattr(R, '__dir__')}")
try:
    R.no_such_thing
except AttributeError as exc:
    line(f"  未知名 -> AttributeError: {exc}")
line(f"  子模块符号转发后已固化：'library' in vars(render) = {'library' in vars(R)}")

# ── C. 两个模块的 __main__ 自检 ─────────────────────────────────────
line("=" * 78)
line("[C] 两个模块的 __main__ 自检")
for mod in ("cardforge.render.assets", "cardforge.render.fonts"):
    p = subprocess.run([sys.executable, "-m", mod], cwd=str(ROOT), capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    tail = [ln for ln in (p.stdout or "").strip().splitlines() if ln.strip()][-3:]
    line(f"  python -m {mod} -> rc={p.returncode}")
    for ln in tail:
        line(f"      {ln[:150]}")
    assert p.returncode == 0, p.stderr

# ── D. 语法/类型卫生 ────────────────────────────────────────────────
line("=" * 78)
line("[D] 编译 + 中文 docstring 覆盖")
import ast  # noqa: E402

files = [ROOT / "cardforge/render/assets.py", ROOT / "cardforge/render/fonts.py",
         ROOT / "cardforge/render/__init__.py"]
rows = []
for f in files:
    src = f.read_text(encoding="utf-8")
    tree = ast.parse(src)
    compile(src, str(f), "exec")
    total = documented = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            total += 1
            doc = ast.get_docstring(node) or ""
            documented += 1 if any("\u4e00" <= c <= "\u9fff" for c in doc) else 0
    rows.append({"file": f.name, "lines": src.count("\n") + 1, "defs": total,
                 "cn_docstring": documented})
    line(f"  {f.name:12s} 行数={src.count(chr(10)) + 1:4d}  "
         f"def/class/module={total:3d}  含中文 docstring={documented:3d}")
assert all(r["defs"] == r["cn_docstring"] for r in rows), "有定义缺中文 docstring"

# ── E. 视觉产物核对：版权标 vs 素材自带预光栅化版 ────────────────────
line("=" * 78)
line("[E] 光栅化结果与素材自带 _cache 版对比（尺寸/墨迹）")
from PIL import Image  # noqa: E402

from cardforge.core import paths  # noqa: E402
from cardforge.render import assets as A  # noqa: E402

A.set_svg_rasterizer(None)
lib = A.AssetLibrary()
for lang in ("sc", "jp", "en"):
    for color in ("black", "white"):
        assert lib.copyright_mark(lang, color) is not None, (lang, color)

for name in ("sc", "jp", "en"):
    for color in ("black", "white"):
        mine = Image.open(paths.CACHE / "svg" / f"copyright_{name}-{color}.svg.png")
        ref_p = paths.ASSETS / "_cache" / f"copyright_{name}-{color}.svg.png"
        ref = Image.open(ref_p) if ref_p.is_file() else None
        mb = mine.split()[3].getbbox()
        rb = ref.split()[3].getbbox() if ref is not None else None
        line(f"  {name}-{color:5s} 本模块 {str(mine.size):13s} 墨迹={str(mb):24s}| "
             f"素材自带 {str(None if ref is None else ref.size):13s} 墨迹={rb}")
line(f"  paths.CACHE/svg 现有 {len(list((paths.CACHE / 'svg').glob('*.png')))} 个缓存文件")

# 同尺寸渲染对比：把我方结果缩到参考尺寸，算平均绝对差
ref_p = paths.ASSETS / "_cache" / "copyright_sc-black.svg.png"
if ref_p.is_file():
    ref = Image.open(ref_p).convert("RGBA")
    mine = Image.open(paths.CACHE / "svg" / "copyright_sc-black.svg.png").convert("RGBA")
    a = mine.resize(ref.size, Image.LANCZOS)
    diff = sum(abs(x - y) for x, y in zip(a.getchannel("A").getdata(),
                                          ref.getchannel("A").getdata()))
    line(f"  sc-black 缩放到 {ref.size} 后与素材自带版平均 alpha 绝对差 = "
         f"{diff / (ref.width * ref.height):.2f} / 255")

line("=" * 78)
line("[F] _probe/render 产物清单")
for p in sorted(OUT.iterdir()):
    line(f"  {p.name:28s} {p.stat().st_size:>9,d} 字节")
line("=" * 78)
line("收尾校验全部通过。")
