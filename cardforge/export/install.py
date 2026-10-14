"""把导出的 expansions 装进 EDOPro —— 探测安装目录、备份式复制、打包分发。

三条设计原则
------------
1. **探测要真的验证，不是猜路径。** 候选目录必须真的含 ``expansions/`` 目录
   或 ``ocgcore`` 库（``ocgcore.dll`` / ``libocgcore.so`` / ``libocgcore.dylib``），
   否则不算命中 —— 否则会在用户的 ``C:\\EDOPro`` 之类空目录里乱建东西。
2. **覆盖前一定备份。** 每次 install 新建一个带时间戳的备份目录
   ``<target>/expansions/.cardforge_backup/<ts>/``，同名的旧文件先原样搬进去。
   内容**逐字节相同**的文件直接跳过，不产生备份垃圾。
3. **失败返回结构化结果，不抛异常。** 找不到 EDOPro 时返回
   ``{"ok": False, "error": …, "hint": …}``，让 CLI/UI 直接展示。

关于 ``user_configs.json``
--------------------------
EDOPro 的「仓库」是**用 git 克隆**的（``repositories/<name>/``），所以给朋友的 zip
包不能直接当远程仓库用。:func:`make_repo_pack` 因此同时做两件事：把包打成 zip，
并附一份 ``config/user_configs.json`` 片段（:func:`repo_config_block`），
里面填的 ``url`` 建议是可 ``git clone`` 的地址；纯本地分发时留 ``file://`` 或空串，
走 :func:`install` 手动安装更靠谱。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from .expansions import pack_layout

__all__ = [
    "APP_NAMES", "find_edopro", "find_candidates", "install", "make_repo_pack",
    "repo_config_block", "is_edopro_dir", "backup_dir_name",
]

#: 常见的 EDOPro 目录名（大小写各异，Windows 上不区分大小写但 Linux 区分）。
APP_NAMES: tuple[str, ...] = ("EDOPro", "edopro", "EDOPro-beta", "YGOPro", "ygopro")

#: ``ocgcore`` 原生库的文件名模式（三平台）。
_OCGCORE_GLOBS: tuple[str, ...] = ("ocgcore*", "libocgcore*")

BACKUP_DIRNAME = ".cardforge_backup"

_STRING_MARK_BEGIN = "# >>> CardForge"
_STRING_MARK_END = "# <<< CardForge"


# ══════════════════════════════════════════════════════════════════════
#  探测
# ══════════════════════════════════════════════════════════════════════
def is_edopro_dir(p: str | os.PathLike[str]) -> bool:
    """这个目录**真的是** EDOPro 安装目录吗？

    判定依据（真的去查文件系统）：含 ``expansions/`` 目录，或含 ``ocgcore`` 原生库。
    """
    q = Path(p)
    if not q.is_dir():
        return False
    if (q / "expansions").is_dir():
        return True
    for pat in _OCGCORE_GLOBS:
        try:
            if any(q.glob(pat)):
                return True
        except OSError:
            continue
    return False


def _win_candidates() -> list[Path]:
    """Windows 候选：LOCALAPPDATA / Program Files / 各盘符 / Steam 库。"""
    out: list[Path] = []
    env = os.environ
    for var in ("LOCALAPPDATA", "APPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)",
                "PROGRAMDATA", "USERPROFILE"):
        base = env.get(var)
        if not base:
            continue
        for name in APP_NAMES:
            out.append(Path(base) / name)
    for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        drive = f"{letter}:\\"
        if not Path(drive).exists():
            continue
        for name in ("EDOPro", "edopro"):
            out.append(Path(drive) / name)
            out.append(Path(drive) / "Games" / name)
            out.append(Path(drive) / "Program Files" / name)
            out.append(Path(drive) / "Program Files (x86)" / name)
        for steam in (Path(drive) / "Steam", Path(drive) / "SteamLibrary",
                      Path(drive) / "Program Files (x86)" / "Steam",
                      Path(drive) / "Program Files" / "Steam"):
            out.append(steam / "steamapps" / "common" / "EDOPro")
    return out


def _mac_candidates() -> list[Path]:
    home = Path.home()
    out = [
        home / "Library" / "Application Support" / "EDOPro",
        home / "Library" / "Application Support" / "edopro",
        Path("/Applications/EDOPro.app"),
        Path("/Applications/EDOPro.app/Contents/Resources"),
        Path("/Applications/EDOPro.app/Contents/Resources/EDOPro"),
        home / "Applications" / "EDOPro.app",
        home / "Library" / "Application Support" / "Steam" / "steamapps"
        / "common" / "EDOPro",
    ]
    return out


def _linux_candidates() -> list[Path]:
    home = Path.home()
    out = [
        home / ".local" / "share" / "EDOPro",
        home / ".local" / "share" / "edopro",
        Path("/opt/EDOPro"),
        Path("/opt/edopro"),
        Path("/usr/local/share/EDOPro"),
        home / ".steam" / "steam" / "steamapps" / "common" / "EDOPro",
        home / ".local" / "share" / "Steam" / "steamapps" / "common" / "EDOPro",
        home / ".var" / "app" / "com.valvesoftware.Steam" / "data" / "Steam"
        / "steamapps" / "common" / "EDOPro",
    ]
    if os.environ.get("XDG_DATA_HOME"):
        out.insert(0, Path(os.environ["XDG_DATA_HOME"]) / "EDOPro")
    return out


def find_candidates() -> list[str]:
    """**未经校验**的候选目录字符串列表（含大量不存在的路径，供 doctor 排查）。"""
    if sys.platform.startswith("win"):
        cands = _win_candidates()
    elif sys.platform == "darwin":
        cands = _mac_candidates()
    else:
        cands = _linux_candidates()
    seen: set[str] = set()
    out: list[str] = []
    for c in cands:
        s = str(c)
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def find_edopro() -> list[str]:
    """探测本机的 EDOPro 安装目录，返回**通过校验**的候选列表（可能为空）。

    校验方式：:func:`is_edopro_dir` —— 目录里必须有 ``expansions/`` 或 ``ocgcore`` 库。
    找不到就是找不到，不返回未经证实的猜测路径。
    """
    out: list[str] = []
    for s in find_candidates():
        try:
            if is_edopro_dir(s):
                rp = str(Path(s).resolve())
                if rp not in out:
                    out.append(rp)
        except OSError:
            continue
    return out


# ══════════════════════════════════════════════════════════════════════
#  安装
# ══════════════════════════════════════════════════════════════════════
def backup_dir_name() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _same_bytes(a: Path, b: Path) -> bool:
    try:
        if a.stat().st_size != b.stat().st_size:
            return False
        return a.read_bytes() == b.read_bytes()
    except OSError:
        return False


def _result(ok: bool, *, target: str = "", expansions: str = "", pack: str = "",
            backup_dir: str = "", copied: list[str] | None = None,
            backed_up: list[str] | None = None, unchanged: list[str] | None = None,
            failed: list[dict] | None = None, strings_merged: str = "",
            dry_run: bool = False, error: str = "", hint: str = "",
            extra: dict | None = None) -> dict:
    """统一的返回结构 —— **每条返回路径的键都一样**。

    这样调用方（``cli.py`` 无条件地读 ``r["target"]``）不用为失败分支写特例。
    """
    copied = copied or []
    backed_up = backed_up or []
    unchanged = unchanged or []
    failed = failed or []
    out = {
        "ok": bool(ok),
        "target": target,
        "expansions": expansions,
        "pack": pack,
        "backup_dir": backup_dir,
        "copied": copied,                # 复制清单（列表）
        "backed_up": backed_up,
        "unchanged": unchanged,
        "failed": failed,
        "strings_merged": strings_merged,
        "dry_run": bool(dry_run),
        "count": len(copied),            # 数量别名
        "copied_count": len(copied),
        "backed_up_count": len(backed_up),
        "unchanged_count": len(unchanged),
        "error": error,
        "hint": hint,
    }
    if extra:
        out.update(extra)
    return out


def install(
    pack_dir: str | os.PathLike[str],
    target: str | os.PathLike[str] | None = None,
    *,
    dry_run: bool = False,
    merge_strings: bool = True,
    backup: bool = True,
) -> dict:
    """把 ``<pack>/expansions/*`` 复制进目标的 ``expansions/``。

    * ``target=None`` → 用 :func:`find_edopro` 的第一个命中项；一个都没有则返回
      ``ok=False`` 与中文提示（不抛异常）。
    * 覆盖同名文件前，先把旧文件备份到
      ``<target>/expansions/.cardforge_backup/<时间戳>/<相对路径>``。
    * 内容逐字节相同的文件会被跳过（``unchanged``），不产生备份垃圾。
    * ``merge_strings=True`` 且包里带 ``strings.conf``、目标有 ``config/`` 时，
      会把 ``!setname``/``!counter`` 合并进 ``config/strings.conf`` 的受管区块
      （已存在则替换该区块，不动用户其它内容）。

    :returns: ``{"ok","target","expansions","pack","backup_dir","copied","backed_up",
        "unchanged","failed","strings_merged","dry_run","count","copied_count",
        "backed_up_count","unchanged_count","error","hint"}``。
        ``copied``/``backed_up``/``unchanged`` 是**清单**（列表），
        想要数量用 ``count`` / ``copied_count`` / ``backed_up_count`` / ``unchanged_count``。
        失败时 ``error``/``hint`` 有值，其余键仍在（**所有返回路径键集合一致**）。
    """
    root = Path(pack_dir)
    exp = root / "expansions" if (root / "expansions").is_dir() else root
    if not exp.is_dir():
        return _result(False, pack=str(root), dry_run=dry_run,
                       error=f"包里没有 expansions/ 目录：{root}",
                       hint="先跑 cardforge.export.expansions.build() 生成包。")

    tgt_root: Path | None = None
    if target:
        tgt_root = Path(target)
        if not tgt_root.is_dir():
            return _result(False, pack=str(root), target=str(tgt_root),
                           dry_run=dry_run,
                           error=f"目标目录不存在：{tgt_root}",
                           hint="确认 EDOPro 安装路径；或先手动创建该目录。")
    else:
        found = find_edopro()
        if not found:
            return _result(False, pack=str(root),
                           error="没找到 EDOPro 安装目录",
                           hint="手动指定：install(pack_dir, target=r'…\\EDOPro')。"
                                "EDOPro 目录里应当有 expansions/ 或 ocgcore 库。",
                           extra={"candidates": find_candidates()[:12]})
        tgt_root = Path(found[0])

    tgt_exp = tgt_root / "expansions"
    stamp = backup_dir_name()
    bdir = tgt_exp / BACKUP_DIRNAME / stamp

    copied: list[str] = []
    backed_up: list[str] = []
    unchanged: list[str] = []
    failed: list[dict] = []

    if not dry_run:
        try:
            tgt_exp.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return _result(False, pack=str(root), target=str(tgt_root),
                           error=f"无法创建 {tgt_exp}：{e}",
                           hint="检查写权限，或用管理员权限重试。")

    for src in sorted(exp.rglob("*")):
        if not src.is_file():
            continue
        rel = src.relative_to(exp)
        if BACKUP_DIRNAME in rel.parts:      # 别把备份自己再复制一遍
            continue
        dst = tgt_exp / rel
        rel_s = str(rel).replace("\\", "/")
        if dst.is_file() and _same_bytes(src, dst):
            unchanged.append(rel_s)
            continue
        if dry_run:
            copied.append(rel_s)
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.is_file() and backup:
                bdst = bdir / rel
                bdst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dst, bdst)
                backed_up.append(rel_s)
            shutil.copy2(src, dst)
            copied.append(rel_s)
        except OSError as e:
            failed.append({"file": rel_s, "error": str(e)})

    strings_merged = ""
    src_conf = exp / "strings.conf"
    if merge_strings and src_conf.is_file() and tgt_root is not None:
        strings_merged = _merge_target_strings(src_conf, tgt_root, bdir, dry_run=dry_run)

    # 没备份任何东西就别留空目录
    backup_path = str(bdir) if (backup and backed_up) else ""
    if backup and not backed_up:
        try:
            if bdir.is_dir() and not any(bdir.rglob("*")):
                shutil.rmtree(bdir, ignore_errors=True)
        except OSError:
            pass

    ok = not failed
    return _result(
        ok,
        target=str(tgt_root) if tgt_root else "",
        expansions=str(tgt_exp),
        pack=str(root),
        backup_dir=backup_path,
        copied=copied, backed_up=backed_up, unchanged=unchanged, failed=failed,
        strings_merged=strings_merged, dry_run=dry_run,
        error="" if ok else f"{len(failed)} 个文件复制失败",
        hint="" if ok else "检查目标目录写权限，或文件是否被 EDOPro 占用。",
    )


def _merge_target_strings(src_conf: Path, tgt_root: Path, bdir: Path,
                          *, dry_run: bool) -> str:
    """把包里的 strings.conf 合并进 ``<target>/config/strings.conf``（受管区块替换）。"""
    conf_dir = tgt_root / "config"
    if not conf_dir.is_dir():
        return ""
    dst = conf_dir / "strings.conf"
    try:
        from . import strings as stringsmod
        incoming = stringsmod.read(src_conf)
        block = stringsmod.render(incoming.get("setnames"), incoming.get("counters"),
                                  incoming.get("counters_alias"), header="",
                                  unknown=incoming.get("unknown"))
        if not block.strip():
            return ""
        existing = dst.read_text(encoding="utf-8-sig") if dst.is_file() else ""
        merged = stringsmod.merge(existing, tag="expansions",
                                  setnames=incoming.get("setnames"),
                                  counters=incoming.get("counters"),
                                  counters_alias=incoming.get("counters_alias"),
                                  unknown=incoming.get("unknown"))
        if dry_run:
            return str(dst)
        if dst.is_file():
            try:
                bdst = bdir / "config" / "strings.conf"
                bdst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dst, bdst)
            except OSError:
                pass
        dst.write_text(merged, encoding="utf-8", newline="\n")
        return str(dst)
    except (OSError, UnicodeDecodeError, ValueError, ImportError):
        return ""


# ══════════════════════════════════════════════════════════════════════
#  分发
# ══════════════════════════════════════════════════════════════════════
def repo_config_block(pack_name: str, url: str, *, mode: str = "") -> dict:
    """``config/user_configs.json`` 的 repos 片段：``{"name","url","mode"}``。

    ``mode`` 不给时按 url 猜：``git``/``http(s)``/``.git`` 结尾 → ``"git"``，
    ``file://`` → ``"local"``，空串 → ``"manual"``（让用户手动装）。
    """
    name = str(pack_name or "").strip() or "CardForge"
    u = str(url or "").strip()
    if not mode:
        low = u.lower()
        if not u:
            mode = "manual"
        elif low.startswith("file:"):
            mode = "local"
        else:
            mode = "git"
    return {"name": name, "url": u, "mode": mode}


def make_repo_pack(
    pack_dir: str | os.PathLike[str],
    out_zip: str | os.PathLike[str] | None = None,
    *,
    name: str = "",
    url: str = "",
    mode: str = "",
    root_folder: str = "",
) -> str:
    """把包打成 zip（含 ``config/user_configs.json`` 的 repos 片段），便于分发给朋友。

    zip 结构::

        <root_folder>/
        ├── expansions/…
        ├── README.txt
        ├── cardforge_manifest.json
        └── config/user_configs.json     ← {"repos": [repo_config_block(...)]}

    :param out_zip: 默认 ``<pack_dir 同级>/<pack_dir 名>.zip``。
    :param root_folder: zip 内的顶层目录名；默认取 ``pack_dir`` 的名字。
    :returns: 生成的 zip 路径字符串。
    """
    root, exp, exists = pack_layout(pack_dir)
    if not exists:
        raise FileNotFoundError(f"包里没有 expansions/ 目录：{root}")
    zip_path = Path(out_zip) if out_zip else root.parent / f"{root.name}.zip"
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    top = (root_folder or name or root.name).strip() or root.name
    block = repo_config_block(name or root.name, url, mode=mode)
    user_cfg = json.dumps({"repos": [block]}, ensure_ascii=False, indent=2) + "\n"

    added = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for src in sorted(root.rglob("*")):
            if not src.is_file() or src == zip_path:
                continue
            rel = src.relative_to(root).as_posix()
            if BACKUP_DIRNAME in Path(rel).parts or src.suffix.lower() == ".zip":
                continue
            zf.write(src, f"{top}/{rel}")
            added += 1
        zf.writestr(f"{top}/config/user_configs.json", user_cfg)
    return str(zip_path)
