#!/usr/bin/env python3
"""CardForge 卡锻 2.0 —— PyInstaller onefolder 一键构建。

用法（项目根目录）::

    py -3 tools/build_exe.py                  # 默认 onefolder，不含对决引擎
    py -3 tools/build_exe.py --with-engine    # 带上 vendor/engine（+195M ocgcore.dll）
    py -3 tools/build_exe.py --clean          # 先清 build/ dist/ 再构建
    py -3 tools/build_exe.py --py <python>    # 用别的解释器（默认 .packaging/venv）
    py -3 tools/build_exe.py --no-ensure      # 跳过「venv 里有没有 PyInstaller」检查

设计要点（改前必读）：

1. **入口脚本是构建时一次性生成的**（``.packaging/entry.py``，绝对导入）。
   ``cardforge/__main__.py`` 用的是相对导入（``from .cli import main``），
   只能 ``python -m cardforge`` 跑，不能当 PyInstaller 的脚本入口。

2. **只读资源进 ``_internal/``**：``web/ data/ vendor/{scripts,decks,data}``。
   ``core/paths.py`` 的 ``_frozen_root()`` 已经认识 PyInstaller 6 的两种布局
   （onefile 的 ``sys._MEIPASS`` 临时目录 / onefolder 的 ``dist/<App>/_internal``）。

3. **可写工作区不进 _internal/**：frozen 时 ``paths._default_workspace()`` 落在
   exe 同级，由 ``ensure_dirs()`` 惰性创建。只往那儿放一个**最小骨架**
   （演示卡 + 系列圣经 + script，构建后由 :func:`copy_workspace_skeleton` 拷贝），
   不含 ``pics/ out/ logs/ .cache/`` 等用户产物 —— 那些是跑出来的，不是发出去的。
   注意 add-data 只能落 ``_internal/``，所以骨架不能走 datas，必须构建后拷。
   **用户文档同理**（``docs/`` ``research/`` + 根级 README 与调研报告）：交付后
   要直接可读，由 :func:`copy_docs` 拷到 exe 同级，不进 ``_internal/``。

4. **对决引擎默认排除**：``vendor/engine/ocgcore.dll`` 195M。
   ``duel/ocgcore.py`` 找不到 DLL 时抛 ``EngineUnavailable``，doctor 如实报
   「引擎不可用」，其余功能不受影响。``--with-engine`` 才把它打进去。

5. **卡面立绘有两份镜像**（``data/assets/aria`` 与 ``web/assets/aria``，md5 相同）：
   渲染层读前者、Web 服务读后者，运行时都真实需要，故两份都进包（约 17M）。
   去重需要改运行时路径解析，不值得为打包单开特例。

6. **dist/ 的更新走「暂存 → 重命名备份 → 上位」，自动路径零删除**：
   PyInstaller 的 COLLECT 阶段会先删输出目录再重建 —— 复用同一 dist 路径意味着
   每次重新打包都是 700+ 文件的批量删除（危险，且会被安全策略拦截）。
   所以 PyInstaller 只往``.packaging/out/CardForge-<时间戳>/``（永不预存在）写；
   旧的 ``dist/CardForge`` 用**重命名**挪到 ``.packaging/out/prev-<时间戳>/`` 备份；
   暂存目录再重命名上位。交付后不做任何清理——备份随 ``--clean``（显式 opt-in）
   删除，且 ``--clean`` 排在构建**之前**：被删除护栏拦下时就诚实失败，
   不存在「构建成功了脚本最后却非零退出」的骗局。
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACK_DIR = ROOT / ".packaging"
# venv 解释器路径随平台：Windows 在 Scripts\，POSIX 在 bin/。
# （项目本身跨平台，start.sh 就是给 macOS/Linux 的；打包脚本不能只认 Windows。）
VENV_PY = PACK_DIR / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
ENTRY = PACK_DIR / "entry.py"
DIST = ROOT / "dist"
WORK = PACK_DIR / "build"
SPEC = PACK_DIR
#: PyInstaller 的暂存输出。**必须是每次构建都全新的路径**：PyInstaller 的 COLLECT
#: 阶段会先删掉输出目录再重建，若复用同一路径，每次重新打包都变成一次 700+ 文件的
#: 批量删除（既危险又会被安全策略拦截）。时间戳目录永不预存在，从根上免掉删除。
STAGE_BASE = PACK_DIR / "out"

APP_NAME = "CardForge"

# 随包分发的只读资源（src 相对项目根 → bundle 内目标目录）
READONLY_DATAS = [
    ("web", "web"),
    ("data", "data"),
    ("vendor/scripts", "vendor/scripts"),
    ("vendor/decks", "vendor/decks"),
    ("vendor/data", "vendor/data"),
]

# 工作区**不**进 _internal/（add-data 只能落在 _internal 里，而 frozen 时
# paths._default_workspace() 解析的是 exe 同级目录，放错地方演示卡就看不见）。
# 改为构建后 copy_workspace_skeleton() 拷到 dist/<App>/workspace/。
# 只发最小骨架（cards + archetypes + script），不含 pics/out/logs/.cache 等用户产物。
WORKSPACE_SKELETON = [
    ("workspace/cards", "workspace/cards"),
    ("workspace/archetypes", "workspace/archetypes"),
    ("workspace/script", "workspace/script"),
]

# 用户文档（同工作区骨架，构建后拷到 **exe 同级**——_internal 不是给人看的，
# 文档要交付后可直接打开）。docs/05 是完整使用教学；README 与调研报告的
# 相对链接（../research/…）在这个布局下原样可用。
DOC_BUNDLE_DIRS = [
    ("docs", "docs"),
    ("research", "research"),
]
DOC_BUNDLE_FILES = [
    "README.md",
    "ComfyUI-游戏王卡图-技术调研.md",
]

# 对决引擎（默认排除，--with-engine 才带）
ENGINE_DATA = ("vendor/engine", "vendor/engine")

# 可选增强层：在 cardforge 里都是函数内懒 import，PyInstaller 静态追踪不到，
# 显式声明（装了的才声明，没装就老实降级——doctor 会报）。
OPTIONAL_HIDDEN = {
    "PIL": ["PIL"],
    "numpy": ["numpy"],
    "fontTools": ["fontTools"],
    "brotli": ["brotli"],
    "svglib": ["svglib", "reportlab"],
    "pymupdf": ["pymupdf"],
}

ENTRY_SRC = '''# -*- coding: utf-8 -*-
"""PyInstaller 入口 —— 由 tools/build_exe.py 自动生成，勿手改。

cardforge/__main__.py 用相对导入只能 -m 跑；打包需要绝对导入的脚本入口。
默认无参即 launch（与 启动.bat 的语义一致）。
"""
import sys

from cardforge.cli import main

if __name__ == "__main__":
    sys.exit(main())
'''


def _say(msg: str = "") -> None:
    print(msg, flush=True)


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    _say("+ " + " ".join(str(c) for c in cmd[:6]) + (" ..." if len(cmd) > 6 else ""))
    t0 = time.time()
    r = subprocess.run(cmd, **kw)
    _say(f"  -> exit={r.returncode} ({time.time() - t0:.1f}s)")
    return r


def _human(n: int) -> str:
    for unit in ("B", "KiB", "MiB", "GiB"):
        if n < 1024 or unit == "GiB":
            return f"{n:.1f}{unit}" if unit != "B" else f"{n}B"
        n /= 1024
    return f"{n:.1f}GiB"


def _dir_size(p: Path) -> int:
    total = 0
    for f in p.rglob("*"):
        try:
            if f.is_file():
                total += f.stat().st_size
        except OSError:
            pass
    return total


#: 上次构建可能残留、本次不会重新生成的路径（切换 --with-engine 时最重要的漂移源）。
#: 只删这些**具体的**目录，不做整体 rmtree(dist)——那是用户的产物目录，
#: 批量删除既危险又会把「我就想重新打个包」变成一次心惊胆战的确认。
STALE_PATHS = ["_internal/vendor/engine", "_internal/workspace"]


def prune_stale(app_dir: Path, with_engine: bool) -> list[str]:
    """删掉本次构建不会覆盖的已知残留（小目录，逐个点名，不扫盘）。"""
    removed = []
    for rel in STALE_PATHS:
        if rel == "_internal/vendor/engine" and with_engine:
            continue                      # 这次要带引擎，不删
        p = app_dir / rel
        if p.is_dir():
            shutil.rmtree(p)
            removed.append(rel)
    return removed


def resolve_python(arg: str | None) -> str:
    if arg:
        return arg
    if VENV_PY.is_file():
        return str(VENV_PY)
    # 没有 venv 时退回当前解释器（可能在系统 Python 上跑构建）
    _say(f"[!] 未找到 {VENV_PY}，退回当前解释器 {sys.executable}")
    return sys.executable


def ensure_pyinstaller(py: str, skip: bool) -> None:
    if skip:
        return
    r = subprocess.run([py, "-c", "import PyInstaller; print(PyInstaller.__version__)"],
                       capture_output=True, text=True)
    if r.returncode == 0:
        _say(f"[i] PyInstaller {r.stdout.strip()} 就绪")
        return
    _say("[i] venv 里没有 PyInstaller，安装中…")
    r2 = subprocess.run([py, "-m", "pip", "install", "pyinstaller"])
    if r2.returncode != 0:
        raise SystemExit("PyInstaller 安装失败；请手动装好后重试，或加 --no-ensure")


def write_entry() -> Path:
    PACK_DIR.mkdir(parents=True, exist_ok=True)
    ENTRY.write_text(ENTRY_SRC, encoding="utf-8")
    return ENTRY


def collect_datas(with_engine: bool) -> tuple[list[str], list[str]]:
    """返回 (add_data 参数列表, 实际纳入的说明行)。"""
    args: list[str] = []
    notes: list[str] = []
    for src, dst in READONLY_DATAS:          # 注意：不含 WORKSPACE_SKELETON
        p = ROOT / src
        if not p.is_dir():
            raise SystemExit(f"缺少随包资源：{src}（应为目录）")
        args.append(f"{p}{os.pathsep}{dst}")
        notes.append(f"{src:<22} {_human(_dir_size(p)):>10}  → _internal/{dst}")
    if with_engine:
        p = ROOT / ENGINE_DATA[0]
        if not p.is_dir():
            raise SystemExit("缺少 vendor/engine（--with-engine 需要它）")
        args.append(f"{p}{os.pathsep}{ENGINE_DATA[1]}")
        notes.append(f"{ENGINE_DATA[0]:<22} {_human(_dir_size(p)):>10}  → _internal/{ENGINE_DATA[1]}（--with-engine）")
    else:
        notes.append(f"{'vendor/engine':<22} {'—':>10}    （默认排除，见 docstring 第 4 条）")
    return args, notes


def copy_workspace_skeleton(app_dir: Path) -> list[str]:
    """把最小工作区骨架拷到 **exe 同级** 的 workspace/（frozen 时的可写工作区）。

    add-data 只能落 _internal/，而 paths.WORKSPACE（frozen）= exe 同级 workspace/，
    所以这一步必须构建后手工做。重复构建用 dirs_exist_ok 覆盖，不报错。
    """
    copied: list[str] = []
    for src, dst in WORKSPACE_SKELETON:
        s = ROOT / src
        d = app_dir / dst
        if not s.is_dir():
            continue
        shutil.copytree(s, d, dirs_exist_ok=True)
        n = sum(1 for f in d.rglob("*") if f.is_file())
        copied.append(f"{dst:<24} {n:>4} 个文件")
    return copied


def copy_docs(app_dir: Path) -> list[str]:
    """把用户文档拷到 **exe 同级**（docs/ research/ + 根级说明文件）。

    与 workspace 骨架同理：add-data 只能进只读的 _internal/，而文档是交付后
    要直接打开的东西（使用教学、调研报告、README），所以放 exe 同级。
    docs 内部的相对链接（../research/…）在这个布局下原样可用。
    """
    copied: list[str] = []
    for src, dst in DOC_BUNDLE_DIRS:
        s = ROOT / src
        d = app_dir / dst
        if not s.is_dir():
            continue
        shutil.copytree(s, d, dirs_exist_ok=True)
        n = sum(1 for f in d.rglob("*") if f.is_file())
        copied.append(f"{dst:<24} {n:>4} 个文件")
    for rel in DOC_BUNDLE_FILES:
        s = ROOT / rel
        if s.is_file():
            shutil.copy2(s, app_dir / rel)
            copied.append(f"{rel:<24} {1:>4} 个文件")
    return copied


def collect_hidden(py: str) -> list[str]:
    hidden = ["cardforge"]  # 包本体（双保险）
    for mod, imps in OPTIONAL_HIDDEN.items():
        r = subprocess.run([py, "-c", f"import {mod}"], capture_output=True)
        if r.returncode == 0:
            hidden.extend(imps)
        else:
            _say(f"[i] 可选依赖 {mod} 未安装 → 不声明 hidden import（运行时如实降级）")
    return hidden


def park_old_build(app_dir: Path, ts: str) -> Path | None:
    """把 dist/ 下的旧构建**挪**到 .packaging/out/prev-<ts>/（重命名，不删文件）。

    PyInstaller 的 COLLECT 会先删输出目录，所以不能让旧构建挡在那儿；
    但直接删 700+ 文件既危险又会被安全策略拦。重命名是零删除的等价操作。
    """
    if not app_dir.exists():
        return None
    parked = STAGE_BASE / f"prev-{ts}"
    shutil.move(str(app_dir), str(parked))
    return parked


def best_effort_clean_backups(all_of_them: bool = False) -> str:
    """删除旧构建备份。**只在 --clean 时调用，且不做异常兜底。**

    为什么不 try/except：删除护栏触发时抛的不是 ``Exception`` 而是
    ``BaseException`` 一族（直接终止进程）——那是安全机制在说话，
    脚本不该吞掉它继续跑，更不能事后谎称「清理失败但构建成功」。
    被拦时就该失败：构建还没开始，用户手动删 ``.packaging/out/prev-*``
    或者干脆不加 ``--clean`` 再跑。

    ``all_of_them=True`` 连暂存目录一起清（上次失败留下的半成品）。
    """
    olds = sorted(STAGE_BASE.glob("prev-*"), key=lambda p: p.name)
    doomed = olds if all_of_them else olds[:-1]
    stages = sorted(STAGE_BASE.glob("CardForge-*")) if all_of_them else []
    if not doomed and not stages:
        return "没有旧备份需要清理"
    for p in doomed + stages:
        shutil.rmtree(p)
    parts = []
    if doomed:
        parts.append(f"{len(doomed)} 份旧构建备份")
    if stages:
        parts.append(f"{len(stages)} 个残留暂存目录")
    return "已清理 " + "、".join(parts)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="CardForge PyInstaller onefolder 构建",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    ap.add_argument("--with-engine", action="store_true",
                    help="把 vendor/engine（含 195M ocgcore.dll）打进包")
    ap.add_argument("--clean", action="store_true",
                    help="构建前删除旧构建备份（.packaging/out/prev-*）与残留暂存目录；"
                         "在带删除护栏的环境里这一步可能被拦截而导致构建不开始——"
                         "那就手动删 .packaging/out/ 下的旧目录，或不加 --clean 再跑")
    ap.add_argument("--py", default=None, help="构建用解释器（默认 .packaging/venv）")
    ap.add_argument("--no-ensure", action="store_true", help="跳过 PyInstaller 存在性检查")
    args = ap.parse_args(argv)

    py = resolve_python(args.py)
    _say(f"[i] 构建解释器：{py}")
    ensure_pyinstaller(py, args.no_ensure)

    if args.clean:
        # 放在构建**之前**：真被护栏拦下，用户loss的只是一次还没开始的构建，
        # 而不是「构建成功了但脚本最后莫名其妙非零退出」。
        note = best_effort_clean_backups(all_of_them=True)
        _say(f"[i] --clean：{note}")

    entry = write_entry()
    datas, notes = collect_datas(args.with_engine)
    hidden = collect_hidden(py)

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    stage = STAGE_BASE / f"CardForge-{ts}"
    STAGE_BASE.mkdir(parents=True, exist_ok=True)

    _say("")
    _say("== 随包资源 ==")
    for n in notes:
        _say("  " + n)

    # 注意不给 PyInstaller 传 --clean：它会 rmtree 自己的缓存目录
    # （C:\Users\<user>\AppData\Local\pyinstaller），那是批量删除，
    # 不该由构建脚本代劳。--noconfirm 已保证输出被覆盖，缓存留着无害。
    # 暂存目录用时间戳（每次全新），PyInstaller 的 COLLECT 因此无需删除任何东西。
    cmd = [py, "-m", "PyInstaller",
           "--noconfirm",
           "--onedir", "--console",
           f"--name={APP_NAME}",
           f"--distpath={stage}",
           f"--workpath={WORK}",
           f"--specpath={SPEC}",
           "--collect-submodules", "cardforge",
           entry]
    for h in hidden:
        cmd += ["--hidden-import", h]
    for d in datas:
        cmd += ["--add-data", d]

    _say("")
    _say("== 开始构建 ==")
    r = _run(cmd, cwd=str(ROOT))
    if r.returncode != 0:
        _say("[X] PyInstaller 失败（上面应有具体报错；常见漏模块看 warn 文件）")
        return r.returncode

    staged_app = stage / APP_NAME
    exe = staged_app / f"{APP_NAME}.exe"
    if not exe.is_file():
        _say(f"[X] 构建结束但没找到 {exe}")
        return 1

    skel = copy_workspace_skeleton(staged_app)
    docs = copy_docs(staged_app)

    # 构建后再兜一次漂移：不带引擎时 _internal/vendor/engine 不该存在
    # （上次带 --with-engine 打的包会留下 195M 的 ocgcore.dll）。
    leftover = prune_stale(staged_app, args.with_engine)
    if leftover:
        _say(f"[i] 已清构建后残留：{', '.join(leftover)}")

    size = _dir_size(staged_app)
    _say("")
    _say("== 冒烟验证（暂存目录）：--version ==")
    r2 = subprocess.run([str(exe), "--version"], capture_output=True, text=True)
    _say("  " + (r2.stdout.strip() or r2.stderr.strip() or "(无输出)"))
    if r2.returncode != 0:
        _say("[X] --version 都跑不通，这个包有问题；保留 dist/ 里的旧构建不动")
        return 1

    # ── 交付：旧构建重命名备份 → 暂存目录上位（全程零删除） ──────────────
    # 注意：交付后**不做**任何清理。旧备份以 prev-<ts> 累积，由用户显式
    # --clean 处理——自动路径里一次删除都不做，也就不存在「被护栏拦下」
    # 还能假装成功的路径。
    parked = park_old_build(DIST / APP_NAME, ts)
    shutil.move(str(staged_app), str(DIST / APP_NAME))

    # 交付后再冒烟一次：这次跑的是**用户真正拿到的**那个 exe
    final_exe = DIST / APP_NAME / f"{APP_NAME}.exe"
    r3 = subprocess.run([str(final_exe), "--version"], capture_output=True, text=True)
    _say("")
    _say("== 冒烟验证（最终交付）：--version ==")
    _say("  " + (r3.stdout.strip() or r3.stderr.strip() or "(无输出)"))
    if r3.returncode != 0:
        _say("[X] 交付的 exe 跑不通，dist/ 里的这份不可用")
        return 1

    _say("")
    _say("== 构建完成 ==")
    _say(f"  程序目录：{DIST / APP_NAME}")
    _say(f"  入口 exe：{final_exe}")
    _say(f"  总体积：  {_human(size)}")
    _say("  工作区骨架（exe 同级，首次启动在此读写作户卡）：")
    for n in skel:
        _say("    " + n)
    _say("  用户文档（exe 同级，可直接打开阅读）：")
    for n in docs:
        _say("    " + n)
    if parked:
        _say(f"  旧构建备份：{parked}（重命名保留，未删除；--clean 可清）")
    backups = sorted(STAGE_BASE.glob("prev-*"))
    if backups:
        total = sum(_dir_size(p) for p in backups)
        _say(f"  备份堆积：{len(backups)} 份共 {_human(total)}（在 {STAGE_BASE}；"
             f"不加 --clean 会逐次累积，手动删或加 --clean）")
    _say("")
    _say("[OK] 可用。真机验收建议：双击 exe（无参 = launch）→ 看进度条 → 浏览器开页 →")
    _say("     再跑一次  CardForge.exe doctor  确认各层能力如实上报。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
