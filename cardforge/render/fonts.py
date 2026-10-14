"""字体解析 —— ``data/assets/*.woff2`` / 系统字体的跨平台解析、转换与覆盖率检测。

职责
----
1. **role 语义化**：渲染器只认 ``FONT_ROLES``
   （``sc/en/en_name/en_race/atk_def/link``），具体用哪个文件由本模块决定。
2. **woff2 → ttf**：Pillow 读不了 woff2。用 ``fontTools.ttLib.TTFont`` 读入后把
   ``flavor`` 置 ``None`` 再 ``save()`` 到 ``paths.CACHE/'fonts'``；
   若素材目录里已有同名 ``.ttf`` 则直接复用（本仓库就是这种情况，省掉 25MB 级转换）。
   woff2 内部是 **brotli 大窗口模式**（实测 WBITS=25，超标准解码器上限），
   转换必须要有 ``brotli`` 扩展 —— 这是唯一一个「可选、但 woff2 冷启动必需」的依赖；
   缺了不会崩，只是写明「python -m pip install brotli」的修复建议后走系统字体回退。
3. **跨平台回退**：素材不可用时按 :func:`system_font_candidates` 依次尝试
   Windows（msyh/simhei/msjh/simsun/Deng/Noto）、macOS（PingFang/Hiragino/
   Songti/Apple Symbols）、Linux（Noto CJK 多路径 + microsoft 兼容路径），
   每一条都**真的**用 ``os.path.isfile`` 验过；Linux 上再可选地试 ``fc-match``。
4. **覆盖率检测**：:func:`coverage` 用 fontTools 读 cmap 算字形覆盖率，
   :func:`stack` / :func:`load_for` 据此挑「真能显示中文」的字体，
   避免「中文变方框」。
5. **附带的 SVG 光栅化**：:func:`rasterize_svg`（svglib → PDF → PyMuPDF）符合
   :data:`cardforge.render.assets.SvgRasterizer` 钩子签名，由 assets 模块自动挂钩，
   版权标与 Astral 美术字都靠它落地。

兼容性决策
----------
* **绝不抛异常**：解析类函数失败一律返回 ``None`` / ``0.0`` / 空列表，
  错误信息进 :func:`diagnose`，让 doctor 报告而不是让渲染崩掉。本模块不用
  :class:`cardforge.core.errors.AssetMissing` 中断流程 —— 它是给「显式要求素材
  且不允许降级」的调用方预备的，需要时自行 ``if resolve(...) is None: raise``。
* **不缓存 ImageFont 对象**：``FreeTypeFont`` 不能跨 size 复用，只缓存
  「role → 路径」的解析结果；路径解析带 mtime 校验，素材更新后自动失效。
* **字号 3 倍预载**：``load()`` 内部向 Pillow 多要 3 倍字号再 ``set_variation_by_axes``
  之类的高阶 API 一律不用，保持与 Pillow ≥ 9 兼容；``ImageFont.truetype`` 只传
  ``index``（字体集合用），不传其它关键字。
* **PPEM 与缓存口径**：SVG 按「svg 声明的 px 尺寸 / PDF 页面尺寸」推算缩放，
  保证输出分辨率与 ``data/assets/copyright/*.svg`` 里写的 ``width="651px"`` 一致
  （svglib 会按 96→72 dpi 折成 pt，直接渲染会缩水到 75%）。
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Iterator, Sequence

try:  # Pillow 是唯一的硬依赖，缺失时本模块整体降级（不抛异常）
    from PIL import Image, ImageFont
except Exception:  # pragma: no cover - 环境缺 Pillow
    Image = None  # type: ignore[assignment]
    ImageFont = None  # type: ignore[assignment]

if TYPE_CHECKING:  # pragma: no cover - 仅供类型检查
    from PIL.ImageFont import FreeTypeFont

from ..core import paths

__all__ = [
    "FONT_ROLES", "FONT_FILES", "FONT_ROLE_ALIASES", "FONT_SCALE_FAMILY",
    "LANG_STACKS", "resolve", "load", "load_for", "stack", "coverage",
    "coverage_candidates", "system_font_candidates", "diagnose",
    "rasterize_svg", "font_cache_dir", "clear_cache", "truetype_index",
]

# ══════════════════════════════════════════════════════════════════════
#  常量
# ══════════════════════════════════════════════════════════════════════

#: 渲染器可用的字体角色
FONT_ROLES: tuple[str, ...] = ("sc", "en", "en_name", "en_race", "atk_def", "link")

#: role → ``data/assets/`` 下的文件名（不含扩展名）。与素材实际情况一一对应。
FONT_FILES: dict[str, str] = {
    "sc": "ygo-sc",
    "en": "ygo-en",
    "en_name": "ygo-en-name",
    "en_race": "ygo-en-race",
    "atk_def": "ygo-atk-def",
    "link": "ygo-link",
}

#: role 别名（渲染器/调用方可能用别的叫法）
FONT_ROLE_ALIASES: dict[str, str] = {
    "sc": "sc", "zh": "sc", "cn": "sc", "chs": "sc", "zh_cn": "sc", "zh-cn": "sc",
    "zh_tw": "sc", "zh-tw": "sc", "cht": "sc", "ja": "sc", "jp": "sc",
    "chinese": "sc", "cjk": "sc", "text": "sc", "description": "sc", "body": "sc",
    "en": "en", "english": "en", "latin": "en",
    "en_name": "en_name", "name": "en_name", "title": "en_name", "card_name": "en_name",
    "en_race": "en_race", "race": "en_race", "type": "en_race", "type_line": "en_race",
    "atk_def": "atk_def", "atk-def": "atk_def", "stats": "atk_def", "stat": "atk_def",
    "number": "atk_def", "numeric": "atk_def",
    "link": "link", "link_arrow": "link", "arrow": "link",
}

#: 「数值/美术字」角色 —— 这些字体的设计字形只为 ATK/DEF/LINK 数字准备，
#: 虽然 cmap 里也收了 ASCII 字母，但拿它渲染整句英文会很难看。挑系统回退时跳过。
FONT_SCALE_FAMILY: frozenset[str] = frozenset({"atk_def", "link"})

#: 语言 → role 优先栈（每一层都会用覆盖率验证，命中第一个「够用」的）
LANG_STACKS: dict[str, tuple[str, ...]] = {
    "zh_cn": ("sc", "en_name", "en", "en_race", "atk_def", "link"),
    "zh_tw": ("sc", "en_name", "en", "en_race", "atk_def", "link"),
    "zh": ("sc", "en_name", "en", "en_race", "atk_def", "link"),
    "ja": ("sc", "en_name", "en", "en_race", "atk_def", "link"),
    "jp": ("sc", "en_name", "en", "en_race", "atk_def", "link"),
    "ko": ("sc", "en_name", "en", "en_race", "atk_def", "link"),
    "en": ("en_name", "en", "en_race", "sc", "atk_def", "link"),
    "de": ("en_name", "en", "en_race", "sc"),
    "fr": ("en_name", "en", "en_race", "sc"),
    "it": ("en_name", "en", "en_race", "sc"),
    "pt": ("en_name", "en", "en_race", "sc"),
    "es": ("en_name", "en", "en_race", "sc"),
}

#: 语言 → 系统字体目录的额外优先项（追加在跨平台候选之前）
_LANG_SYSTEM_HINTS: dict[str, tuple[str, ...]] = {
    "zh_cn": ("msyh", "msyhbd", "simhei", "simsun", "deng", "notosanssc", "notoserifsc"),
    "zh_tw": ("msjh", "msjhbd", "mingliu", "notosanstc"),
    "ja": ("yugoth", "meiryo", "msgothic", "notosansjp", "hiragino", "pingfang"),
    "ko": ("malgun", "notosanskr", "applegothic"),
    "en": ("arial", "dejavusans", "liberationsans", "times", "georgia"),
}

#: 万用兜底：能在各种语言下都出字的字体名碎片（按优先级）
_ANY_LANG_HINTS: tuple[str, ...] = (
    "notosanssc", "notosanscjk", "notosanstc", "notosansjp", "sourcehansans",
    "sourcehanserif", "msyh", "msjh", "simhei", "simsun", "deng",
    "pingfang", "hiragino", "arialuni", "dejavusans", "liberationsans", "segoeui",
)

#: 系统字体目录（真的存在才用）
_SYSTEM_FONT_DIRS: dict[str, tuple[str, ...]] = {
    "nt": (r"C:\Windows\Fonts", r"C:\WINNT\Fonts"),
    "posix": (
        "/usr/share/fonts", "/usr/local/share/fonts", "/usr/share/fonts/truetype",
        "/usr/share/fonts/opentype", "/usr/share/fonts/truetype/noto",
        "/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/truetype/liberation",
        "/System/Library/Fonts", "/System/Library/Fonts/Supplemental",
        "/Library/Fonts", str(Path.home() / "Library/Fonts"),
        str(Path.home() / ".local/share/fonts"), "/snap/...", "/usr/share/fonts/noto-cjk",
    ),
}

#: 已知的绝对路径候选（按平台分组，逐条验存在性）
_SYSTEM_FONTS_ABS: dict[str, tuple[str, ...]] = {
    "zh_cn": (
        r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\msyh.ttf",
        r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\simsun.ttc", r"C:\Windows\Fonts\Deng.ttf",
        r"C:\Windows\Fonts\NotoSansSC-VF.ttf", r"C:\Windows\Fonts\NotoSerifSC-VF.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/arphic/uming.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
    ),
    "zh_tw": (
        r"C:\Windows\Fonts\msjh.ttc", r"C:\Windows\Fonts\msjhbd.ttc",
        r"C:\Windows\Fonts\mingliub.ttc", r"C:\Windows\Fonts\msyh.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/arphic/uming.ttc",
    ),
    "ja": (
        r"C:\Windows\Fonts\YuGothM.ttc", r"C:\Windows\Fonts\YuGothR.ttc",
        r"C:\Windows\Fonts\meiryo.ttc", r"C:\Windows\Fonts\msgothic.ttc",
        r"C:\Windows\Fonts\msyh.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
    ),
    "ko": (
        r"C:\Windows\Fonts\malgun.ttf", r"C:\Windows\Fonts\gulim.ttc",
        "/System/Library/Fonts/AppleGothic.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ),
    "en": (
        r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\georgia.ttf",
        r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\times.ttf",
        r"C:\Windows\Fonts\calibri.ttf",
        "/System/Library/Fonts/Helvetica.ttc", "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ),
}

#: role → 该角色必须覆盖的代表字符（用于优先级排序，不影响是否可用）
_ROLE_NEED: dict[str, str] = {
    "atk_def": "ATK/DEF0123456789",
    "link": "LINK0123456789",
    "en_name": "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "en_race": "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "en": "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "sc": "通常怪兽效果魔法陷阱攻击力守备力",
}

#: 版权/Astral SVG 的目标高度（像素），用于推算光栅化缩放
_SVG_DEFAULT_TARGET_H = 35
#: SVG 光栅化默认像素密度倍数。素材自带的预光栅化结果就是 3×（如 sc-black.svg
#: 声明 651×35px → 1953×105px），渲染器在不同画布上下采样都能拿到清晰边缘。
_SVG_PIXEL_RATIO = 3.0
_RE_SVG_SIZE = re.compile(r"<svg[^>]*?\b(width|height)\s*=\s*[\"']([\d.]+)(px|pt)?[\"']",
                          re.IGNORECASE | re.DOTALL)
_RE_SVG_VIEWBOX = re.compile(r"viewBox\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE)
_RE_FONT_INDEX = re.compile(r"#(\d+)$")

# ══════════════════════════════════════════════════════════════════════
#  内部缓存
# ══════════════════════════════════════════════════════════════════════

_lock = threading.RLock()
_resolve_cache: dict[tuple[str, str, str | None], dict] = {}   # role+lang+text → 解析结果
_coverage_cache: dict[tuple[str, int, int], tuple] = {}        # path+index+mtime → (cmap_keys,)
_font_index_cache: dict[tuple[str, int], int] = {}             # path+mtime → ttc 索引
_system_cache: dict[str, list[str]] = {}                       # lang → 系统候选（验存在后）
_notes: list[str] = []                                         # 降级说明（doctor 用）


def _note(msg: str) -> None:
    """记一条降级说明（同一个 role/lang 可重复调用，去重）。"""
    with _lock:
        if msg not in _notes:
            _notes.append(msg)


def font_cache_dir() -> Path:
    """字体转换 / SVG 光栅化的缓存目录（``paths.CACHE/'fonts'``）。"""
    return paths.CACHE / "fonts"


def svg_cache_dir() -> Path:
    """SVG 光栅化缓存目录（``paths.CACHE/'svg'``）。"""
    return paths.CACHE / "svg"


def _safe_mkdir(p: Path) -> bool:
    """建目录，成功/已存在返回 ``True``，权限等失败返回 ``False``（不抛异常）。"""
    try:
        p.mkdir(parents=True, exist_ok=True)
        return True
    except Exception:
        return False


def clear_cache() -> None:
    """清空本模块的解析缓存与降级说明（不删磁盘文件）。"""
    with _lock:
        _resolve_cache.clear()
        _coverage_cache.clear()
        _font_index_cache.clear()
        _system_cache.clear()
        _notes.clear()


# ══════════════════════════════════════════════════════════════════════
#  role / 路径解析
# ══════════════════════════════════════════════════════════════════════

def _norm_lang(lang: str | None) -> str:
    """归一化语言代码：小写、``-`` → ``_``，空值按 ``zh_cn`` 处理。"""
    return (lang or "zh_cn").strip().lower().replace("-", "_") or "zh_cn"


def _norm_role(role: str | None) -> str | None:
    """把 role 别名折算成 :data:`FONT_ROLES` 里的正式名；不认识返回 ``None``。"""
    r = (role or "").strip().lower()
    return FONT_ROLE_ALIASES.get(r)


def _iter_system_dirs() -> Iterator[Path]:
    """产出真实存在的系统字体目录（去重，保持优先级）。"""
    seen: set[str] = set()
    keys = ("nt", "posix") if os.name == "nt" else ("posix", "nt")
    for key in keys:
        for raw in _SYSTEM_FONT_DIRS.get(key, ()):
            p = Path(raw)
            try:
                if p.is_dir():
                    s = str(p.resolve()).lower()
                    if s not in seen:
                        seen.add(s)
                        yield p
            except Exception:
                continue


def _scan_system_fonts(hints: Sequence[str], limit: int = 64) -> list[str]:
    """在系统字体目录里按名碎片找字体文件，**逐条验证存在**，返回绝对路径列表。

    先扫浅层（字体目录本身），再扫一层子目录，避免整棵树递归拖慢首次渲染。
    """
    found: list[str] = []
    seen: set[str] = set()
    for d in _iter_system_dirs():
        candidates: list[Path] = []
        try:
            candidates.extend(sorted(d.iterdir()))
        except Exception:
            continue
        try:
            for sub in sorted(d.iterdir()):
                if sub.is_dir():
                    candidates.extend(sorted(sub.iterdir()))
        except Exception:
            pass
        for p in candidates:
            try:
                if not p.is_file():
                    continue
            except Exception:
                continue
            ext = p.suffix.lower()
            if ext not in (".ttf", ".otf", ".ttc", ".otc"):
                continue
            low = p.name.lower().replace(" ", "").replace("-", "").replace("_", "")
            for h in hints:
                if h in low:
                    full = str(p.resolve())
                    if full.lower() not in seen:
                        seen.add(full.lower())
                        found.append(full)
                    break
            if len(found) >= limit:
                return found
    return found


def _fc_match() -> list[str]:
    """Linux/macOS 上可选的 ``fc-match`` 兜底（取不到就返回空列表）。"""
    exe = shutil.which("fc-match")
    if not exe:
        return []
    out: list[str] = []
    try:
        for query in ("sans-serif:lang=zh", "sans-serif", "Noto Sans CJK SC", "serif:lang=ja"):
            try:
                proc = subprocess.run([exe, "-f", "%{file}\n", query], capture_output=True,
                                      timeout=4, text=True,
                                      encoding="utf-8", errors="replace")
            except Exception:
                continue
            for line in (proc.stdout or "").splitlines():
                cand = line.strip()
                if cand and os.path.isfile(cand) and cand not in out:
                    out.append(cand)
    except Exception:
        return out
    return out


def system_font_candidates(lang: str = "zh_cn") -> list[str]:
    """跨平台系统字体路径候选（Windows / macOS / Linux 各若干）。

    返回的每一条都**已用 ``os.path.isfile`` 验证存在**并按语言优先级排序：
    语言专属碎片（如简中的 ``msyh``/``simhei``）→ 已知绝对路径 → 通用兜底（Noto 等）
    → Windows 兼容目录 → ``fc-match``。
    """
    key = _norm_lang(lang)
    with _lock:
        if key in _system_cache:
            return list(_system_cache[key])
    hints = list(_LANG_SYSTEM_HINTS.get(key, ())) + list(_ANY_LANG_HINTS)
    found: list[str] = []

    def _push(p: str | Path) -> None:
        """收一条候选：验过存在且未重复才追加（大小写不敏感去重）。"""
        try:
            s = str(Path(p))
            if os.path.isfile(s) and s.lower() not in {x.lower() for x in found}:
                found.append(s)
        except Exception:
            pass

    for raw in _SYSTEM_FONTS_ABS.get(key, ()) + _SYSTEM_FONTS_ABS.get("en", ()) \
            + _SYSTEM_FONTS_ABS.get("zh_cn", ()):
        _push(raw)
    for p in _scan_system_fonts(hints):
        _push(p)
    for p in _fc_match():
        _push(p)
    with _lock:
        _system_cache[key] = list(found)
    return list(found)


def _split_font_index(path: str | Path) -> tuple[str, int]:
    """把 ``xxx.ttc#2`` 拆成 ``(xxx.ttc, 2)``；无 ``#n`` 时索引为 0。"""
    s = str(path)
    m = _RE_FONT_INDEX.search(s)
    if m:
        return s[: m.start()], int(m.group(1))
    return s, 0


def truetype_index(path: str | Path) -> int:
    """给出字体集合（``.ttc``）的可用子字体索引；``.ttf/.otf`` 恒为 0。

    Pillow 打开 ``.ttc`` 默认取第 0 个；这里额外检查「第 0 个是否真的能开」，
    失败则用 fontTools 找第一个可用索引（常见于 msyh.ttc 之类的集合）。
    """
    real, explicit = _split_font_index(path)
    if explicit:
        return explicit
    if not real.lower().endswith((".ttc", ".otc")):
        return 0
    try:
        st = os.stat(real)
        key = (real, st.st_mtime_ns)
    except Exception:
        key = (real, 0)
    with _lock:
        if key in _font_index_cache:
            return _font_index_cache[key]
    idx = 0
    if ImageFont is not None:
        for i in range(4):
            try:
                ImageFont.truetype(real, 16, index=i)
                idx = i
                break
            except Exception:
                continue
        else:
            idx = 0
    with _lock:
        _font_index_cache[key] = idx
    return idx


# ══════════════════════════════════════════════════════════════════════
#  woff2 → ttf 转换
# ══════════════════════════════════════════════════════════════════════

def _ttf_loadable(path: Path) -> bool:
    """确认 Pillow 真的能打开这个 ttf/otf（避免半截文件被当成可用字体）。"""
    if ImageFont is None:
        return path.is_file() and path.stat().st_size > 0
    try:
        ImageFont.truetype(str(path), 16, index=truetype_index(path))
        return True
    except Exception:
        return False


def _brotli_available() -> bool:
    """fontTools 能否解 woff2 —— 取决于有没有 ``brotli`` / ``brotlicffi`` 扩展。"""
    try:
        from fontTools.ttLib.woff2 import haveBrotli
        return bool(haveBrotli)
    except Exception:
        return False


def _woff2_to_ttf(src: Path, dst: Path) -> Path | None:
    """把 woff2 转换成 Pillow 可读的 ttf/otf，落到 ``dst``；失败返回 ``None``。

    先写临时文件再 ``os.replace``，避免并发下留下半个文件被 Pillow 读到。

    .. note::
       woff2 内部是 **brotli 大窗口模式**（实测 WBITS=25，超出标准 brotli 解码器
       的 24 上限，且末尾缺 ISLAST 标记），所以只能由 fontTools 的流式解码器处理，
       必须装上 ``brotli``（或 ``brotlicffi``）扩展 —— 这是唯一一个「可选但
       woff2 转换必需」的依赖，装了才能从 woff2 冷启动。
    """
    try:
        from fontTools.ttLib import TTFont
    except Exception as exc:  # pragma: no cover - 环境缺 fontTools
        _note(f"fontTools 不可用，无法转换 woff2：{exc!r}")
        return None
    if not _brotli_available():
        _note(f"缺少 brotli 扩展，无法解码 woff2（{src.name}）。"
              f"修复：python -m pip install brotli  "
              f"（或改成直接放置同名 .ttf 到 {paths.rel(src.parent)}）")
        return None
    if not _safe_mkdir(dst.parent):
        return None
    tmp = dst.with_suffix(dst.suffix + ".part")
    font = None
    try:
        font = TTFont(str(src), flavor="woff2", fontNumber=0, lazy=False)
        font.flavor = None
        font.save(str(tmp))
        font.close()
        font = None
        os.replace(str(tmp), str(dst))
    except Exception as exc:
        _note(f"woff2→ttf 转换失败（{src.name}）：{type(exc).__name__}: {exc}"
              + ("（提示：python -m pip install brotli）"
                 if "brotli" in str(exc).lower() else ""))
        try:
            if font is not None:
                font.close()
        except Exception:
            pass
        for p in (tmp, dst):
            try:
                if p.is_file() and p.stat().st_size == 0:
                    p.unlink()
            except Exception:
                pass
        return None
    return dst if _ttf_loadable(dst) else None


def _materialize(role: str) -> tuple[str, str] | None:
    """把某 role 解析成可用字体文件，返回 ``(真实路径, 来源)``。

    来源取值：``asset-ttf``（素材目录已有 ttf/otf）/ ``cache-ttf``（缓存命中）/
    ``converted``（本次由 woff2 转换）。
    """
    stem = FONT_FILES.get(role)
    if stem is None:
        return None
    assets = paths.ASSETS
    # 1) 素材目录里已有的 ttf/otf/ttc（本仓库优先命中这一条）
    for ext in (".ttf", ".otf", ".ttc"):
        p = assets / f"{stem}{ext}"
        if p.is_file() and p.stat().st_size > 0 and _ttf_loadable(p):
            return str(p), "asset-ttf"
    # 2) woff2 → 缓存
    woff = assets / f"{stem}.woff2"
    if not woff.is_file() or woff.stat().st_size <= 0:
        return None
    dst = font_cache_dir() / f"{stem}.ttf"
    if dst.is_file() and dst.stat().st_size > 0 and _ttf_loadable(dst):
        return str(dst), "cache-ttf"
    out = _woff2_to_ttf(woff, dst)
    return (str(out), "converted") if out is not None else None


# ══════════════════════════════════════════════════════════════════════
#  覆盖率
# ══════════════════════════════════════════════════════════════════════

def _cmap_keys(path: str | Path) -> frozenset[int] | None:
    """读取字体 cmap 的码点集合（带 mtime 缓存）；失败返回 ``None``。"""
    real, index = _split_font_index(path)[0], truetype_index(path)
    try:
        st = os.stat(real)
        key = (real, index, st.st_mtime_ns)
    except Exception:
        key = (real, index, 0)
    with _lock:
        hit = _coverage_cache.get(key)
    if hit is not None:
        return hit[0]
    try:
        from fontTools.ttLib import TTFont
        font = TTFont(real, fontNumber=index, lazy=True)
        cmap = font.getBestCmap() or {}
        keys = frozenset(cmap.keys())
        font.close()
    except Exception:
        try:  # woff2 未被 fontTools 直接支持时，先转 ttf 再读
            if real.lower().endswith(".woff2"):
                dst = font_cache_dir() / (Path(real).stem + ".ttf")
                conv = _woff2_to_ttf(Path(real), dst)
                if conv is not None:
                    return _cmap_keys(conv)
        except Exception:
            pass
        with _lock:
            _coverage_cache[key] = (None,)
        return None
    with _lock:
        _coverage_cache[key] = (keys,)
    return keys


def coverage(path: str, text: str) -> float:
    """字体对给定文本的字形覆盖率 0–1（fontTools 读 cmap）。

    按**不同字符**计数（重复字符不重复计权），忽略空白字符。字体打不开返回 ``0.0``；
    文本为空/全是空白返回 ``1.0``。用于挑「真的能显示中文」的字体，避免方框。
    """
    if not text:
        return 1.0
    chars = {c for c in text if not c.isspace()}
    if not chars:
        return 1.0
    keys = _cmap_keys(path)
    if keys is None:
        return 0.0
    hit = sum(1 for c in chars if ord(c) in keys)
    return hit / len(chars)


def coverage_candidates(text: str, lang: str = "zh_cn",
                        paths_in: Iterable[str] | None = None) -> list[tuple[str, float]]:
    """给一组候选字体算覆盖率，返回按覆盖率降序（同分保持输入顺序）的 ``(路径, 覆盖率)``。"""
    cands = list(paths_in) if paths_in is not None else \
        [p for r in stack(lang) if (p := resolve(r, lang))]
    scored = [(p, coverage(p, text)) for p in dict.fromkeys(cands)]
    return sorted(scored, key=lambda kv: -kv[1])


# ══════════════════════════════════════════════════════════════════════
#  解析 / 加载
# ══════════════════════════════════════════════════════════════════════

def _pick(role: str, lang: str, text: str) -> dict:
    """核心解析：素材 → 系统回退，返回结构化结果（不抛异常）。"""
    result: dict = {
        "role": role, "lang": lang, "path": None, "source": "none", "fallback": False,
        "coverage": 0.0, "index": 0, "reason": "",
    }
    got = _materialize(role)
    if got is not None:
        result.update(path=got[0], source=got[1])
    else:
        need = text or _ROLE_NEED.get(role, "")
        pool = system_font_candidates(lang)
        if role not in FONT_SCALE_FAMILY:
            best, best_cov = None, -1.0
            for cand in pool:
                c = coverage(cand, need) if need else 1.0
                if c > best_cov:
                    best, best_cov = cand, c
                if c >= 1.0:
                    break
            if best is not None:
                result.update(path=best, source="system", fallback=True,
                              coverage=max(best_cov, 0.0))
        if result["path"] is None:
            for cand in pool:
                if role in FONT_SCALE_FAMILY and not Path(cand).name.lower().startswith(
                        ("arial", "georgia", "segoeui", "times", "calibri", "dejavu",
                         "liberation", "helvetica", "noto")):
                    continue
                result.update(path=cand, source="system-scale", fallback=True)
                break
        if result["path"] is None:
            result["reason"] = ("素材与系统字体都不可用："
                                f"assets={paths.rel(paths.ASSETS)}，"
                                f"系统候选={len(pool)} 条")
            _note(f"{role}/{lang} 无可用字体（{result['reason']}）")
            return result
    idx = truetype_index(result["path"])
    result["index"] = idx
    result["coverage"] = coverage(result["path"], text) if text else 0.0
    if result["fallback"] and not result["reason"]:
        result["reason"] = "素材缺失或不可读，已回退系统字体"
        _note(f"{role}/{lang} 回退系统字体：{result['path']}")
    if text and result["coverage"] < 1.0:
        _note(f"{role}/{lang} 对给定文本覆盖率 {result['coverage']:.0%}（{result['path']}）")
    return result


def resolve(role: str, lang: str = "zh_cn", text: str | None = None) -> str | None:
    """返回可用于 Pillow 的 ttf/otf 绝对路径；解析失败返回 ``None``。

    * 优先用 ``data/assets`` 里的字体（已有 ``.ttf`` 直接用；只有 ``.woff2`` 时
      自动转换并缓存到 ``paths.CACHE/'fonts'``）。
    * 素材不可用时按 :func:`system_font_candidates` 回退（已验存在）。
    * ``text`` 给定时额外算一次覆盖率（进 :func:`diagnose`），便于 doctor 判断
      「这个字体到底能不能显示中文」。
    * 一律不抛异常；``role`` 非法返回 ``None``。
    """
    r = _norm_role(role)
    if r is None:
        return None
    lg = _norm_lang(lang)
    key = (r, lg, text)
    with _lock:
        hit = _resolve_cache.get(key)
    if hit is None:
        hit = _pick(r, lg, text or "")
        with _lock:
            _resolve_cache[key] = hit
    return hit["path"]


def stack(lang: str) -> list[str]:
    """该语言的字体优先栈（role 列表）。中文 ``sc`` 优先；英文 ``en`` 优先；日文 ``sc`` 兜底。"""
    return list(LANG_STACKS.get(_norm_lang(lang), LANG_STACKS["zh_cn"]))


def resolve_for(text: str, lang: str = "zh_cn", roles: Sequence[str] | None = None
                ) -> tuple[str | None, str | None]:
    """按 :func:`stack` 挑「通过覆盖率验证」的字体，返回 ``(path, role)``。

    ``roles`` 覆盖优先栈（默认取 ``stack(lang)``）。全部候选都覆盖不全时，
    退而返回覆盖率最高的那个（并在 :func:`diagnose` 里留说明），
    全部不可用返回 ``(None, None)``。
    """
    lg = _norm_lang(lang)
    order = list(roles) if roles else stack(lg)
    scored: list[tuple[str, str, float]] = []
    for role in order:
        p = resolve(role, lg, text)
        if p is None:
            continue
        c = coverage(p, text)
        scored.append((role, p, c))
        if c >= 1.0:
            return p, role
    if not scored:
        return None, None
    role, p, c = max(scored, key=lambda t: t[2])
    if c < 1.0:
        _note(f"{lg} 无字体能完全覆盖目标文本（最佳 {role}={c:.0%}）")
    return p, role


def load(role: str, size: int, lang: str = "zh_cn",
         text: str | None = None) -> "FreeTypeFont | None":
    """按 role 加载指定字号的字体；失败返回 ``None``（调用方应回退程序化绘制）。

    ``ImageFont`` 对象**不跨 size 缓存**（Pillow 的 ``FreeTypeFont`` 不能复用），
    但 role → 路径的解析结果会被缓存，重复调用的开销只是一次 FreeType 打开。
    """
    if ImageFont is None:
        _note("Pillow 不可用，无法加载字体")
        return None
    path = resolve(role, lang, text)
    if path is None:
        return None
    try:
        return ImageFont.truetype(path, max(1, int(size)), index=truetype_index(path))
    except Exception as exc:
        _note(f"加载字体失败（{path} @ {size}px）：{type(exc).__name__}: {exc}")
        return None


def load_for(text: str, size: int, lang: str = "zh_cn",
             roles: Sequence[str] | None = None) -> "FreeTypeFont | None":
    """按文本覆盖率挑字体并加载，专治「中文变方框」。失败返回 ``None``。"""
    if ImageFont is None:
        return None
    path, _role = resolve_for(text, lang, roles)
    if path is None:
        return None
    try:
        return ImageFont.truetype(path, max(1, int(size)), index=truetype_index(path))
    except Exception as exc:
        _note(f"加载字体失败（{path} @ {size}px）：{type(exc).__name__}: {exc}")
        return None


# ══════════════════════════════════════════════════════════════════════
#  SVG 光栅化（assets.set_svg_rasterizer 的默认实现）
# ══════════════════════════════════════════════════════════════════════

def _svg_declared_px(src: Path) -> tuple[float | None, float | None]:
    """读 SVG 根元素声明的 ``width``/``height``（折算成 px）。"""
    try:
        head = src.read_text(encoding="utf-8", errors="replace")[:4096]
    except Exception:
        return None, None
    w = h = None
    for name, value, unit in _RE_SVG_SIZE.findall(head):
        try:
            v = float(value)
        except Exception:
            continue
        if (unit or "").lower() == "pt":
            v *= 96.0 / 72.0
        if name.lower() == "width":
            w = v
        else:
            h = v
    return w, h


def rasterize_svg(src: str | Path, dst: str | Path, *,
                  target_h: int | None = None, scale: float | None = None,
                  pixel_ratio: float = _SVG_PIXEL_RATIO,
                  trim: bool = True) -> Path | None:
    """把 SVG 光栅化成 RGBA PNG 并返回输出路径；失败返回 ``None``。

    依赖链：``svglib.svg2rlg`` → reportlab ``renderPDF`` → ``pymupdf`` 渲染。
    （``reportlab`` 的 ``renderPM`` 后端需要未随附的 rlPyCairo，故不走它。）

    缩放推算：svglib 把 SVG 的 px 按 96→72 dpi 折成 pt，直接按 1x 渲染会缩水到 75%，
    因此用「SVG 声明的 px / PDF 页面 pt」推出 ``px_per_pt``，再乘 ``pixel_ratio``
    （默认 3×，与素材自带 ``_cache`` 的 1953×105 同一密度）。``scale`` 给定时直接
    覆盖整个缩放值。``trim=True`` 会按实际墨迹包围盒裁掉空白边，返回的图像更贴近
    真卡排版。``target_h`` 只影响 1× 基准高度（缺省用 SVG 自己声明的高度）。
    """
    src_p, dst_p = Path(src), Path(dst)
    if not src_p.is_file():
        return None
    try:
        from svglib.svglib import svg2rlg
        from reportlab.graphics import renderPDF
        import pymupdf
    except Exception as exc:
        _note(f"SVG 光栅化依赖缺失（svglib/reportlab/PyMuPDF）：{exc!r}")
        return None
    if not _safe_mkdir(dst_p.parent):
        return None
    pdf = dst_p.with_suffix(".pdf")
    doc = None
    try:
        drawing = svg2rlg(str(src_p))
        if drawing is None or float(getattr(drawing, "width", 0) or 0) <= 0 \
                or float(getattr(drawing, "height", 0) or 0) <= 0:
            return None
        renderPDF.drawToFile(drawing, str(pdf))
        doc = pymupdf.open(str(pdf))
        page = doc[0]
        pw, ph = float(page.rect.width), float(page.rect.height)
        if pw <= 0 or ph <= 0:
            return None
        decl_w, decl_h = _svg_declared_px(src_p)
        if scale is None:
            px_per_pt = (decl_w / pw) if decl_w else (96.0 / 72.0)
            base_h = float(target_h if target_h else (decl_h or _SVG_DEFAULT_TARGET_H))
            zoom = max(1.0, base_h / max(ph * px_per_pt, 1e-6)) * px_per_pt \
                * max(0.25, float(pixel_ratio))
        else:
            zoom = max(0.1, float(scale))
        pm = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=True)
        img = Image.frombytes("RGBA", (pm.width, pm.height), pm.samples)
        if trim:
            box = img.split()[3].getbbox()
            if box:
                img = img.crop(box)
        img.save(dst_p, format="PNG")
        return dst_p
    except Exception as exc:
        _note(f"SVG 光栅化失败（{src_p.name}）：{type(exc).__name__}: {exc}")
        return None
    finally:
        if doc is not None:
            try:
                doc.close()
            except Exception:
                pass
        try:
            if pdf.is_file():
                pdf.unlink()
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════
#  诊断
# ══════════════════════════════════════════════════════════════════════

def diagnose(lang: str = "zh_cn", text: str | None = None) -> dict:
    """doctor 用：每个 role 的解析结果、是否走了回退、缓存位置。

    ``text`` 给定时附带 ``coverage_text``（该文本下各 role 的覆盖率）与
    ``best_for_text``（最优 role + 路径），直接回答「中文会不会变方框」。

    结构::

        {"assets": "data/assets", "assets_exists": true,
         "pillow": "12.3.0", "fonttools": "4.66.1",
         "cache": {"fonts": "workspace/.cache/fonts", "svg": "workspace/.cache/svg",
                   "fonts_writable": true, "svg_writable": true},
         "stack": ["sc", …], "roles": {"sc": {"path":…, "source":"asset-ttf", …}},
         "system_candidates": {"zh_cn": 6, "ja": 4, "en": 5},
         "best_for_text": {"role": "sc", "path": "…"},
         "notes": ["…"], "ok": true}
    """
    lg = _norm_lang(lang)
    result: dict = {
        "lang": lg,
        "assets": paths.rel(paths.ASSETS),
        "assets_exists": paths.ASSETS.is_dir(),
        "cache": {
            "fonts": paths.rel(font_cache_dir()),
            "svg": paths.rel(svg_cache_dir()),
            "fonts_writable": _safe_mkdir(font_cache_dir()),
            "svg_writable": _safe_mkdir(svg_cache_dir()),
        },
        "stack": stack(lg),
        "roles": {},
    }
    try:
        import PIL
        result["pillow"] = getattr(PIL, "__version__", "?")
    except Exception:
        result["pillow"] = None
    try:
        import fontTools
        result["fonttools"] = getattr(fontTools, "version", "?")
    except Exception:
        result["fonttools"] = None
    try:
        import svglib  # noqa: F401
        import pymupdf  # noqa: F401
        result["svg_rasterizer"] = "svglib+pymupdf"
    except Exception as exc:
        result["svg_rasterizer"] = f"unavailable: {type(exc).__name__}"

    for role in FONT_ROLES:
        info = _pick(role, lg, text or "")
        result["roles"][role] = {
            "path": paths.rel(Path(info["path"])) if info["path"] else None,
            "absolute": info["path"],
            "source": info["source"],
            "fallback": bool(info["fallback"]),
            "index": info["index"],
            "coverage": round(float(info["coverage"]), 4) if text else None,
            "reason": info["reason"],
            "asset_exists": (paths.ASSETS / f"{FONT_FILES[role]}.ttf").is_file()
                            or (paths.ASSETS / f"{FONT_FILES[role]}.woff2").is_file(),
        }
    cands: dict[str, int] = {}
    for lg2 in ("zh_cn", "zh_tw", "ja", "ko", "en"):
        cands[lg2] = len(system_font_candidates(lg2))
    result["system_candidates"] = cands
    if text:
        role, path, cov = None, None, -1.0
        for r in stack(lg):
            p = result["roles"].get(r, {}).get("absolute")
            if not p:
                continue
            c = coverage(p, text)
            if c > cov:
                role, path, cov = r, p, c
        result["coverage_text"] = round(max(cov, 0.0), 4)
        result["best_for_text"] = {"role": role,
                                   "path": paths.rel(Path(path)) if path else None}
    with _lock:
        result["notes"] = list(_notes)
    result["ok"] = all(v["path"] for v in result["roles"].values())
    return result


# ══════════════════════════════════════════════════════════════════════
#  自检
# ══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":  # pragma: no cover
    import json

    print(json.dumps(diagnose("zh_cn", text="通常怪兽 效果 ATK/3200 测试"),
                     ensure_ascii=False, indent=2))
    for role in FONT_ROLES:
        print(f"{role:8s} ->", resolve(role))
    print("stack(zh_cn) =", stack("zh_cn"))
    print("stack(en)    =", stack("en"))
    for lang in ("zh_cn", "ja", "en"):
        print(f"system_font_candidates({lang})[:4] =", system_font_candidates(lang)[:4])
