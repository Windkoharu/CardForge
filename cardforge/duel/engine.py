"""对局引擎探测与三层降级。

设计立场
--------
**宁可诚实降级，绝不假装跑过对局。**

检测顺序（跨平台）::

    ① 环境变量 CARDFORGE_OCGCORE 指向的库
    ② 工程 vendor/engine/ 下的 ocgcore
    ③ 常见 EDOPro / YGOPro 安装路径
    ④ 系统库搜索路径（PATH / LD_LIBRARY_PATH / DYLD_LIBRARY_PATH）

找不到就返回 ``level="static"``，G3 会降级为静态 Lua 校验，并在报告里写明原因，
同时给出**该平台该放哪个文件**的具体指引。

原生库平台矩阵
--------------
* Windows  ``ocgcore.dll``
* Linux    ``libocgcore.so``
* macOS    ``libocgcore.dylib``
"""
from __future__ import annotations

import ctypes
import os
import platform
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..core import paths

#: 三层降级：真跑 / 静态校验 / 仅导出
LEVELS = ("ocgcore", "static", "export-only")

_LIB_NAMES = {
    "win32": ("ocgcore.dll", "libocgcore.dll"),
    "linux": ("libocgcore.so", "libocgcore.so.1", "ocgcore.so"),
    "darwin": ("libocgcore.dylib", "ocgcore.dylib"),
}


def platform_lib_names() -> tuple[str, ...]:
    if sys.platform.startswith("win"):
        return _LIB_NAMES["win32"]
    if sys.platform == "darwin":
        return _LIB_NAMES["darwin"]
    return _LIB_NAMES["linux"]


#: EDOPro / YGOPro 的常见安装位置（跨平台）
_COMMON_DIRS = (
    # Windows
    r"C:\EDOPro", r"D:\EDOPro", r"C:\Program Files\EDOPro",
    r"C:\Program Files (x86)\EDOPro", r"C:\YGOPro", r"D:\YGOPro",
    os.path.expandvars(r"%LOCALAPPDATA%\EDOPro"),
    os.path.expandvars(r"%APPDATA%\EDOPro"),
    os.path.expandvars(r"%USERPROFILE%\EDOPro"),
    # Linux
    os.path.expanduser("~/.local/share/EDOPro"),
    os.path.expanduser("~/.local/share/edopro"),
    os.path.expanduser("~/.steam/steam/steamapps/common/EDOPro"),
    "/opt/edopro", "/usr/local/edopro", "/usr/share/edopro",
    # macOS
    os.path.expanduser("~/Library/Application Support/EDOPro"),
    "/Applications/EDOPro.app/Contents/MacOS",
    "/Applications/EDOPro.app/Contents/Resources",
)


@dataclass
class EngineStatus:
    """探测结果。``level`` 是三层降级里的哪一层。"""
    level: str = "static"
    lib_path: Optional[str] = None
    loaded: bool = False
    version: str = ""
    reason: str = ""
    hint: str = ""
    checked: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.level == "ocgcore" and self.loaded

    def to_dict(self) -> dict:
        return {"level": self.level, "lib_path": self.lib_path, "loaded": self.loaded,
                "version": self.version, "reason": self.reason, "hint": self.hint,
                "checked": self.checked}


def _platform_hint() -> str:
    names = platform_lib_names()
    sysname = {"win32": "Windows", "linux": "Linux", "darwin": "macOS"}.get(
        "win32" if sys.platform.startswith("win") else
        ("darwin" if sys.platform == "darwin" else "linux"), sys.platform)
    return (f"当前系统是 {sysname}，需要 {names[0]}。把它放进 "
            f"{paths.rel(paths.ENGINE_DIR)}/ 即可；或用环境变量 "
            f"CARDFORGE_OCGCORE 指定完整路径。"
            f"EDOPro 安装目录里自带这个库（Windows 在根目录，Linux 在 "
            f"/usr/lib 或同目录，macOS 在 .app/Contents/MacOS）。")


def _candidates() -> list[tuple[Path, str]]:
    """按优先级列出候选库路径与来源说明。"""
    out: list[tuple[Path, str]] = []
    env = os.environ.get("CARDFORGE_OCGCORE") or os.environ.get("OCGCORE")
    if env:
        out.append((Path(env).expanduser(), "环境变量 CARDFORGE_OCGCORE"))

    for n in platform_lib_names():
        out.append((paths.ENGINE_DIR / n, "工程内置 vendor/engine"))

    for d in _COMMON_DIRS:
        if not d:
            continue
        p = Path(d)
        if not p.exists():
            continue
        for n in platform_lib_names():
            out.append((p / n, f"常见安装位置 {d}"))
        # 再找一层的子目录（有些发行版放在 bin/ 或 lib/）
        for sub in ("bin", "lib", "lib64", "resources"):
            for n in platform_lib_names():
                out.append((p / sub / n, f"常见安装位置 {d}/{sub}"))

    # 系统搜索路径
    for key in ("PATH", "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"):
        for d in (os.environ.get(key) or "").split(os.pathsep):
            if d:
                for n in platform_lib_names():
                    out.append((Path(d) / n, f"系统搜索路径 {key}"))
    return out


def detect(*, try_load: bool = True, deep: bool = False) -> EngineStatus:
    """探测 ocgcore 是否可用。

    ``deep=True`` 时会在常见盘符下做**有限的**浅层搜索（较慢，只给 doctor 用）。
    """
    st = EngineStatus()
    cands = _candidates()

    if deep:
        cands.extend(_shallow_search())

    seen: set[str] = set()
    for p, src in cands:
        key = str(p).lower()
        if key in seen:
            continue
        seen.add(key)
        st.checked.append(f"{src}: {p}")
        if not p.exists():
            continue
        st.lib_path = str(p)
        if not try_load:
            st.level, st.loaded = "ocgcore", True
            st.reason = f"找到库文件（{src}），未尝试加载"
            return st
        global _LAST_LIB
        _LAST_LIB = p
        try:
            lib = ctypes.CDLL(str(p))
        except OSError as e:
            st.reason = f"找到 {p.name} 但加载失败：{e}"
            st.hint = ("常见原因：缺少同目录的 libstdc++-6.dll / libgcc_s_seh-1.dll "
                       "/ libwinpthread-1.dll；把 EDOPro 目录下的这几个 DLL 一起复制过来。")
            continue
        # 探一下标准入口是否存在（只探符号，不跑对局）
        missing = [fn for fn in ("OCG_CreateDuel", "OCG_StartDuel", "OCG_DuelProcess")
                   if not hasattr(lib, fn)]
        if missing:
            st.reason = (f"{p.name} 已加载，但缺少 ocgcore 标准入口："
                         f"{'、'.join(missing)}")
            st.hint = ("这个库可能不是 ocgcore，而是别的东西。"
                       "请用 EDOPro 自带的 ocgcore 原生库。")
            continue
        st.level, st.loaded, st.version = "ocgcore", True, _probe_version(lib)
        st.reason = f"已加载 {p.name}（{src}）"
        st.hint = ""
        return st

    # 没找到
    st.level = "static"
    st.reason = "未检测到 ocgcore 原生库" if not st.checked else \
        f"检查了 {len(st.checked)} 个候选位置，均未找到可用的 ocgcore"
    st.hint = _platform_hint()
    return st


def _probe_version(lib) -> str:
    """尽力取版本号；取不到就留空（不猜）。

    ⚠ 不要调用 ``OCG_GetVersion``：实测这个符号存在但**不是**版本 getter，
    按 ``c_char_p`` / ``c_uint`` 调用都会触发 access violation（0xC0000005）。
    这里改用官方导出表中语义明确的两个 getter，并且结果必须是可打印 ASCII 才采用。
    """
    for fn in ("OCG_GetVersionMajor", "OCG_GetVersionMinor"):
        f = getattr(lib, fn, None)
        if f is None:
            continue
        try:
            f.restype = ctypes.c_int
            f.argtypes = []
            v = int(f())
            if 0 <= v < 10000:
                return str(v)
        except Exception:
            continue
    # 退一步：查文件版本信息（Windows）
    try:
        if sys.platform.startswith("win") and _LAST_LIB:
            import win32api  # type: ignore  # 可选依赖
            info = win32api.GetFileVersionInfo(str(_LAST_LIB), "\\")
            ms, ls = info["FileVersionMS"], info["FileVersionLS"]
            return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
    except Exception:
        pass
    return ""


_LAST_LIB: Optional[Path] = None


def _shallow_search(max_depth: int = 2) -> list[tuple[Path, str]]:
    """在常见盘符/家目录下做有限的浅层搜索（只给 doctor 的 --deep 用）。"""
    roots: list[Path] = [Path.home()]
    if sys.platform.startswith("win"):
        for letter in "CDEFGH":
            p = Path(f"{letter}:\\")
            if p.exists():
                roots.append(p)
    else:
        roots += [Path("/opt"), Path("/usr/local"), Path("/usr/share")]

    names = {n.lower() for n in platform_lib_names()}
    out: list[tuple[Path, str]] = []
    for root in roots:
        try:
            for depth in range(max_depth):
                pattern = "/".join(["*"] * (depth + 1))
                for p in root.glob(f"{pattern}/ocgcore*"):
                    if p.is_file() and p.name.lower() in names:
                        out.append((p, f"浅层搜索 {root}"))
                if len(out) > 20:
                    break
        except Exception:
            continue
        if len(out) > 20:
            break
    return out


def available() -> bool:
    return detect(try_load=False).level == "ocgcore"


def find_edopro_install() -> list[str]:
    """列出看起来像 EDOPro 安装目录的路径（找 expansions/ 或 ocgcore）。"""
    names = {n.lower() for n in platform_lib_names()}
    hits: list[str] = []
    for d in _COMMON_DIRS:
        if not d:
            continue
        p = Path(d)
        if not p.is_dir():
            continue
        try:
            has_lib = any((p / n).exists() for n in names) or \
                any((p / s / n).exists() for n in names
                    for s in ("", "bin", "lib", "resources"))
            if has_lib or (p / "expansions").is_dir():
                hits.append(str(p))
        except Exception:
            continue
    return hits


def which(name: str) -> Optional[str]:
    """薄封装，方便测试打桩。"""
    return shutil.which(name)


def capabilities() -> dict:
    st = detect(try_load=False)
    return {
        "levels": list(LEVELS),
        "platform": platform.platform(),
        "lib_names": list(platform_lib_names()),
        "level": st.level,
        "lib_path": st.lib_path,
        "edopro_dirs": find_edopro_install(),
        "hint": st.hint,
    }


if __name__ == "__main__":  # pragma: no cover
    import json
    print(json.dumps(detect(deep=True).to_dict(), ensure_ascii=False, indent=2))
