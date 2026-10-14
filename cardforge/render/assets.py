"""素材库 —— 官方卡框 / 属性圆标 / 魔陷徽记 / 星级 / 连接箭头 等位图的统一入口。

职责
----
* 把 ``data/assets/`` 下**杂乱的真实文件名**收敛成渲染器需要的稳定语义 API
  （``frame('xyz', pendulum=True)``、``arrow('右上', on=True)`` ……）。
* 惰性加载 + 进程内缓存：同一张素材只从磁盘读一次，返回同一个 PIL 图像对象。
* **优雅降级**：素材缺失一律返回 ``None`` 并记入 :meth:`AssetLibrary.missing`，
  由渲染器自行回退到程序化绘制，本模块**不抛异常**。
* 两种格式不由本模块解析，但必须给出入口：

  - ``*.woff2`` → 交给 :mod:`cardforge.render.fonts`（``TTFont`` + ``flavor=None``）。
  - ``*.svg``   → 交给可插拔钩子 :func:`set_svg_rasterizer`，默认指向
    :func:`cardforge.render.fonts.rasterize_svg`；未注入钩子时返回 ``None`` 并记 missing。

兼容性决策（结果见文件末尾的 ``if __name__`` 自检）
--------------------------------------------------
1. **大小写不敏感 + 容错路径**：初始化时把整棵素材树扫成 ``小写相对路径 → 真实路径``
   索引，Windows / Linux 行为一致；``frame('XYZ')``、``rarity_layer('UR')``、
   ``spell_trap_badge('spell','quick-play')`` 都能命中。
2. **镜像/代码页差异**：文件名与用户输入可能来自不同代码页（CP936 ↔ UTF-8），
   索引同时登记 NFC / NFD 两种归一化形式；命中失败时再做一次二次遍历兜底。
3. **命名别名**：素材实际名与需求名并不一致，模块内用 ``_ALIASES`` / ``_MAP``
   显式列出全部落差点（``20th → stamp/twentieth.png``、``quick → icon/quick-play.png``、
   ``zh_tw → copyright/sc-*.svg`` ……），避免把别名逻辑散落到渲染器里。
4. **指纹口径**：``digest()`` 只统计真实素材文件（排除 ``_cache/``、``__pycache__/``
   与根目录下 ``_`` 开头的排版预览图）。若 woff2 曾被转换成同名 ``.ttf``，
   该 ``.ttf`` 会参与指纹、导致指纹变化一次 —— 这是可接受的（转换本身是幂等的，
   第二次运行指纹即稳定）。
"""
from __future__ import annotations

import hashlib
import threading
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Sequence

from PIL import Image

from ..core import paths
from .geometry import FRAME_NATIVE

__all__ = [
    "AssetLibrary", "library", "set_svg_rasterizer", "svg_rasterizer",
    "CATEGORIES", "FRAME_BASES", "ATTRIBUTES", "SPELL_TRAP_KINDS",
    "ARROW_DIRECTIONS", "RARITY_KEYS", "DEFAULT_EXPECTED",
]

# ══════════════════════════════════════════════════════════════════════
#  常量：语义键 → 素材相对路径
# ══════════════════════════════════════════════════════════════════════

#: 卡框基座（与 ``data/assets/frame/`` 实际文件一一对应）
FRAME_BASES: tuple[str, ...] = (
    "normal", "effect", "ritual", "fusion", "synchro", "xyz", "link",
    "spell", "trap", "token",
)
#: 有灵摆变体的基座（link / spell / trap / token 官方没有灵摆版）
PENDULUM_BASES: tuple[str, ...] = (
    "normal", "effect", "ritual", "fusion", "synchro", "xyz",
)

#: 属性圆标：英文键 → 素材文件；别名表含中文名
ATTRIBUTE_KEYS: tuple[str, ...] = (
    "dark", "light", "earth", "water", "fire", "wind", "divine", "spell", "trap",
)
_ATTRIBUTE_ALIASES: dict[str, str] = {
    # 中文属性名（官方简中译名 + 常见俗称）
    "暗": "dark", "暗属性": "dark", "闇": "dark", "dark": "dark",
    "光": "light", "光属性": "light", "light": "light",
    "地": "earth", "地属性": "earth", "earth": "earth",
    "水": "water", "水属性": "water", "water": "water",
    "炎": "fire", "炎属性": "fire", "火": "fire", "fire": "fire",
    "风": "wind", "风属性": "wind", "wind": "wind",
    "神": "divine", "神属性": "divine", "幻神": "divine", "divine": "divine",
    "魔": "spell", "魔法": "spell", "魔法卡": "spell", "spell": "spell", "magic": "spell",
    "罠": "trap", "陷阱": "trap", "陷阱卡": "trap", "trap": "trap",
}

#: 魔陷徽记：种类键 → 素材文件（注意速攻实际文件名为 ``quick-play.png``）
SPELL_TRAP_KINDS: tuple[str, ...] = (
    "normal", "ritual", "quick", "continuous", "equip", "field", "counter",
)
_KIND_ALIASES: dict[str, str] = {
    "normal": "normal", "通常": "normal", "普通": "normal", "": "normal",
    "ritual": "ritual", "仪式": "ritual", "儀式": "ritual",
    "quick": "quick-play", "quick-play": "quick-play", "quickplay": "quick-play",
    "速攻": "quick-play", "速攻魔法": "quick-play",
    "continuous": "continuous", "永续": "continuous", "永續": "continuous",
    "equip": "equip", "装备": "equip", "裝備": "equip",
    "field": "field", "场地": "field", "場地": "field",
    "counter": "counter", "反击": "counter", "反擊": "counter",
}

#: 连接箭头：中文方位 → 素材文件名前缀（8 方向，与素材一一对应）
ARROW_DIRECTIONS: dict[str, str] = {
    "上": "up", "下": "down", "左": "left", "右": "right",
    "左上": "left-up", "右上": "right-up",
    "左下": "left-down", "右下": "right-down",
}
_ARROW_ALIASES: dict[str, str] = {
    "up": "up", "top": "up", "n": "up", "↑": "up",
    "down": "down", "bottom": "down", "s": "down", "↓": "down",
    "left": "left", "w": "left", "←": "left",
    "right": "right", "e": "right", "→": "right",
    "left-up": "left-up", "up-left": "left-up", "nw": "left-up", "↖": "left-up",
    "right-up": "right-up", "up-right": "right-up", "ne": "right-up", "↗": "right-up",
    "left-down": "left-down", "down-left": "left-down", "sw": "left-down", "↙": "left-down",
    "right-down": "right-down", "down-right": "right-down", "se": "right-down", "↘": "right-down",
}

#: 稀有度覆膜（文件名取自 ``data/assets/rare/``）
RARITY_KEYS: tuple[str, ...] = (
    "ur", "ser", "gser", "hr", "pser", "pser-print", "gr", "dt", "attribute-rare",
)
_RARITY_ALIASES: dict[str, str] = {
    "ur": "ur", "ultra": "ur", "银字": "ur", "銀字": "ur",
    "ser": "ser", "secret": "ser", "银碎": "ser", "銀碎": "ser",
    "gser": "gser", "gold-secret": "gser", "金碎": "gser",
    "hr": "hr", "holographic": "hr", "全息": "hr",
    "pser": "pser", "prismatic": "pser", "棱镜碎": "pser", "棱鏡碎": "pser",
    "pser-print": "pser-print", "print": "pser-print", "印刷层": "pser-print",
    "gr": "gr", "gold-rare": "gr", "金字": "gr",
    "dt": "dt", "diamond": "dt", "碎钻": "dt",
    "attribute-rare": "attribute-rare", "attr-rare": "attribute-rare", "属性位": "attribute-rare",
}

#: 激光防伪标（1–3 为全息标；4 是 505 字节的占位/异常文件，仍按素材登记）
LASER_VARIANTS: tuple[int, ...] = (1, 2, 3, 4)
#: 纪念标：需求里的 ``20th`` 与素材实际名 ``twentieth`` 都接受
_STAMP_ALIASES: dict[str, str] = {
    "20th": "twentieth", "twentieth": "twentieth", "20周年": "twentieth",
    "二十周年": "twentieth", "anniversary": "twentieth",
}
#: 版权标语言 → 素材前缀（简中 = sc；zh_tw 无独立素材，回落 sc）
_COPYRIGHT_LANGS: dict[str, str] = {
    "sc": "sc", "zh_cn": "sc", "zh-cn": "sc", "zh": "sc", "cn": "sc",
    "chs": "sc", "simplified": "sc", "zh_tw": "sc", "zh-tw": "sc", "cht": "sc",
    "traditional": "sc", "tw": "sc",
    "jp": "jp", "ja": "jp", "jpn": "jp", "japanese": "jp",
    "en": "en", "eng": "en", "english": "en",
}
#: 版权标颜色别名
_COPYRIGHT_COLORS: dict[str, str] = {
    "black": "black", "k": "black", "黑": "black", "黑色": "black",
    "white": "white", "w": "white", "白": "white", "白色": "white",
}
#: 杂项图标（``icon/`` 里除速攻外的其余文件同时也可当 icon 取）
_ICON_ALIASES: dict[str, str] = {
    "bleed": "bleed/card-bleed", "card-bleed": "bleed/card-bleed", "出血": "bleed/card-bleed",
    "back": "back/card-back-bleed", "card-back": "back/card-back-bleed",
    "cardback": "back/card-back-bleed", "卡背": "back/card-back-bleed",
    "mask": "mask/card-mask", "card-mask": "mask/card-mask",
    "mask-pendulum": "mask/card-mask-pendulum", "card-mask-pendulum": "mask/card-mask-pendulum",
    "level": "star/level", "rank": "star/rank",
    "copyright": "copyright/sc-black",
    "atk-def-astral": "stat/atk-def-astral", "atk-link-astral": "stat/atk-link-astral",
}

#: ``availability()`` 的分类口径（每类给出「必须存在」的期望路径，用于算总数）
DEFAULT_EXPECTED: dict[str, tuple[str, ...]] = {
    "frame": tuple(f"frame/{b}.png" for b in FRAME_BASES)
             + tuple(f"frame/{b}-pendulum.png" for b in PENDULUM_BASES),
    "attribute": tuple(f"attribute/{k}.png" for k in ATTRIBUTE_KEYS),
    "icon": tuple(f"icon/{k}.png" for k in
                  ("ritual", "quick-play", "continuous", "equip", "field", "counter")),
    "star": ("star/level.png", "star/rank.png"),
    "arrow": tuple(f"arrow/{d}-{s}.png"
                   for d in sorted(set(ARROW_DIRECTIONS.values())) for s in ("on", "off")),
    "rare": tuple(f"rare/{k}.png" for k in RARITY_KEYS),
    "laser": tuple(f"laser/{v}.png" for v in LASER_VARIANTS),
    "stamp": ("stamp/twentieth.png",),
    "copyright": tuple(f"copyright/{l}-{c}.svg" for l in ("sc", "jp", "en")
                       for c in ("black", "white")),
    "stat": ("stat/atk-def-astral.svg", "stat/atk-link-astral.svg"),
    "mask": ("mask/card-mask.png", "mask/card-mask-pendulum.png"),
    "bleed": ("bleed/card-bleed.png",),
    "back": ("back/card-back-bleed.png",),
    # 字体：每支都有 woff2 原件；本仓库同时带了已转换好的 ttf（woff2 转换的产物），
    # 两者都算「素材已就位」，避免 availability() 把生成物报成 unexpected。
    "font": tuple(
        f"{stem}{ext}" for stem in
        ("ygo-sc", "ygo-en", "ygo-en-name", "ygo-en-race", "ygo-atk-def", "ygo-link")
        for ext in (".woff2", ".ttf")
    ),
}
#: ``availability()`` 里分类名的展示顺序
CATEGORIES: tuple[str, ...] = tuple(DEFAULT_EXPECTED)

#: 扫描时跳过的目录名（``_cache`` 是生成物，NOTICE 明确说不计入素材指纹）
_SKIP_DIRS = frozenset({"_cache", "__pycache__", ".git", ".svn", "_probe"})
#: 预光栅化缓存的相对位置（只读回退；正式缓存目录是 ``paths.CACHE/'svg'``）
_LEGACY_SVG_CACHE = ("_cache",)

_SVG_EXTS = frozenset({".svg"})
_RASTER_EXTS = frozenset({".png"})

# ══════════════════════════════════════════════════════════════════════
#  可插拔的 SVG 光栅化钩子
# ══════════════════════════════════════════════════════════════════════

SvgRasterizer = Callable[[Path, Path], Any]
"""``(src_svg, dst_png) -> 任意真值表示成功``。约定实现见 fonts.rasterize_svg。"""

_svg_rasterizer: SvgRasterizer | None = None
_svg_rasterizer_resolved = False
_hook_lock = threading.Lock()


def set_svg_rasterizer(fn: SvgRasterizer | None) -> None:
    """注入 SVG 光栅化实现（``fonts.py`` 或调用方负责）。

    ``fn=None`` 会清除注入并解除「已解析」标记，下次调用重新尝试默认实现
    （:func:`cardforge.render.fonts.rasterize_svg`，内部用 svglib → PDF → PyMuPDF）。
    """
    global _svg_rasterizer, _svg_rasterizer_resolved
    with _hook_lock:
        _svg_rasterizer = fn or None
        _svg_rasterizer_resolved = fn is not None


def svg_rasterizer() -> SvgRasterizer | None:
    """取当前 SVG 光栅化钩子；未显式注入时惰性尝试默认实现，取不到返回 ``None``。

    「取不到」= svglib / PyMuPDF 未安装，或 fonts 模块不可导入。此时调用方
    （渲染器）应回退到程序化绘制，而不是崩溃。
    """
    global _svg_rasterizer, _svg_rasterizer_resolved
    if _svg_rasterizer_resolved:
        return _svg_rasterizer
    with _hook_lock:
        if not _svg_rasterizer_resolved:
            try:  # 局部导入：规避 assets ↔ fonts 的模块级循环依赖
                from .fonts import rasterize_svg as _default
                _svg_rasterizer = _default
            except Exception:
                _svg_rasterizer = None
            _svg_rasterizer_resolved = True
    return _svg_rasterizer


# ══════════════════════════════════════════════════════════════════════
#  路径归一化工具
# ══════════════════════════════════════════════════════════════════════

def _normalize(name: str | Path) -> str:
    """把任意输入折成索引键：``\\`` → ``/``、去首尾空白与斜杠、大小写不敏感。

    同时尝试 NFC 归一化（macOS 上的文件名可能是 NFD）。
    """
    s = str(name).replace("\\", "/").strip().strip("/")
    while "//" in s:
        s = s.replace("//", "/")
    return s.lower()


def _norm_variants(name: str | Path) -> Iterator[str]:
    """产出索引键的所有候选写法（原名 / NFC 折叠）。"""
    key = _normalize(name)
    yield key
    nfc = unicodedata.normalize("NFC", key)
    if nfc != key:
        yield nfc


def _asset_rel_path(p: Path, root: Path) -> str:
    """取素材相对项目根的 ``/`` 分隔路径；越界时退回绝对路径。"""
    try:
        return p.resolve().relative_to(root).as_posix()
    except Exception:
        return p.as_posix()


# ══════════════════════════════════════════════════════════════════════
#  素材库
# ══════════════════════════════════════════════════════════════════════

class AssetLibrary:
    """``data/assets/`` 的只读句柄：语义化取值 + 惰性缓存 + 缺失登记。

    线程安全（内部一把可重入锁）。**不修改**任何素材文件；唯一会写入的位置是
    SVG 光栅化缓存 ``paths.CACHE/'svg'``（由钩子实现负责）。

    >>> lib = AssetLibrary()
    >>> lib.frame("effect").size
    (1394, 2031)
    """

    #: 期望存在的素材（用于 ``availability()`` 的分母；子类/测试可改）
    expected: dict[str, tuple[str, ...]] = dict(DEFAULT_EXPECTED)

    def __init__(self, root: Path | None = None) -> None:
        """``root`` 缺省为 :data:`cardforge.core.paths.ASSETS`。"""
        self.root: Path = Path(root) if root is not None else paths.ASSETS
        self._lock = threading.RLock()
        self._index: dict[str, Path] | None = None      # 小写相对路径 → 真实路径
        self._files: list[Path] = []                    # 参与指纹的真实素材文件
        self._skipped: list[str] = []                   # 被排除的相对路径（诊断用）
        self._missing: set[str] = set()
        self._images: dict[str, Image.Image | None] = {}
        self._digest: str | None = None
        self._legacy_index: dict[str, Path] | None = None

    # ── 索引与扫描 ──────────────────────────────────────────────────
    def _ensure_index(self) -> None:
        """惰性建立大小写不敏感的文件名索引。"""
        if self._index is not None:
            return
        with self._lock:
            if self._index is not None:
                return
            index: dict[str, Path] = {}
            files: list[Path] = []
            skipped: list[str] = []
            root = self.root
            if root.is_dir():
                for p in sorted(root.rglob("*")):
                    if not p.is_file():
                        continue
                    try:
                        rel = p.relative_to(root)
                    except ValueError:  # pragma: no cover - 防御
                        continue
                    parts = rel.parts
                    top = parts[0] if parts else ""
                    if top in _SKIP_DIRS or any(x in _SKIP_DIRS for x in parts[:-1]):
                        skipped.append(rel.as_posix())
                        continue
                    if len(parts) == 1 and parts[0].startswith("_"):
                        # 根目录下的 _contact_sheet.png 等排版预览图，不是卡面素材
                        skipped.append(rel.as_posix())
                        continue
                    if parts[0] == "NOTICE.txt":
                        skipped.append(rel.as_posix())
                        continue
                    files.append(p)
                    key = unicodedata.normalize("NFC", rel.as_posix().lower())
                    index.setdefault(key, p)
            self._index = index
            self._files = files
            self._skipped = skipped

    @property
    def index(self) -> dict[str, Path]:
        """``小写相对路径 → 真实路径`` 的只读快照（诊断/调试用）。"""
        self._ensure_index()
        return dict(self._index or {})

    @property
    def files(self) -> list[Path]:
        """参与指纹的全部真实素材文件（已排序）。"""
        self._ensure_index()
        return list(self._files)

    # ── 路径解析 ────────────────────────────────────────────────────
    def path(self, rel: str | Path) -> Path | None:
        """按相对路径取素材真实路径；大小写不敏感，找不到返回 ``None``（不登记 missing）。

        查找顺序：精确（小写/NFC）→ 去扩展名补 ``.png`` → 补分类前缀（``icon/`` 等）
        → 全表二次遍历（兜底，处理极端代码页差异）。
        """
        self._ensure_index()
        index = self._index or {}
        candidates: list[str] = []
        for key in _norm_variants(rel):
            candidates.append(key)
            if not key.endswith(tuple(_RASTER_EXTS | _SVG_EXTS)):
                candidates.append(key + ".png")
            for prefix in ("icon/", "star/", "laser/", "stamp/", "attribute/",
                           "arrow/", "rare/", "frame/", "mask/", "bleed/", "back/",
                           "copyright/", "stat/"):
                if not key.startswith(prefix):
                    candidates.append(prefix + key)
                    if not key.endswith(tuple(_RASTER_EXTS | _SVG_EXTS)):
                        candidates.append(prefix + key + ".png")
        for key in candidates:
            hit = index.get(key)
            if hit is not None:
                return hit
        # 二次遍历兜底：处理未归一化的罕见文件名
        target = _normalize(rel)
        for key, p in index.items():
            if _normalize(key) == target or key.endswith("/" + target):
                return p
        return None

    def _mark_missing(self, rel: str) -> None:
        """把一次取值失败记进 :meth:`missing`（统一小写键，便于 doctor 去重）。"""
        with self._lock:
            self._missing.add(_normalize(rel))

    def _load(self, rel: str) -> Image.Image | None:
        """读一张位图（只读一次，进程内缓存）。失败返回 ``None`` 并登记。"""
        key = _normalize(rel)
        with self._lock:
            if key in self._images:
                return self._images[key]
        img: Image.Image | None = None
        p = self.path(rel)
        if p is None:
            self._mark_missing(rel)
        else:
            try:
                with Image.open(p) as im:
                    im.load()
                    img = im.copy() if im.mode == "RGBA" else im.convert("RGBA")
            except Exception:
                img = None
                self._mark_missing(rel)
        with self._lock:
            self._images[key] = img
        return img

    def _load_svg(self, rel: str) -> Image.Image | None:
        """光栅化一张 SVG。

        优先级：``paths.CACHE/'svg'`` 缓存 → 注入的光栅化钩子 → 素材自带的
        ``data/assets/_cache/<name>.svg.png``（只读兜底，仅当钩子不可用时才用）。
        钩子返回假值视为「光栅化失败」，返回 ``None`` 并记入 :meth:`missing`
        —— 这样 ``set_svg_rasterizer`` 注入失败时，渲染器能明确知道要回退。
        """
        key = "svg::" + _normalize(rel)
        with self._lock:
            if key in self._images:
                return self._images[key]
        img: Image.Image | None = None
        src = self.path(rel)
        if src is None:
            self._mark_missing(rel)
        else:
            stem = _normalize(rel).replace("/", "_")
            cache_png = paths.CACHE / "svg" / (stem + ".png")
            img = self._read_png(cache_png)          # 1) 正式缓存
            if img is None:
                fn = svg_rasterizer()
                if fn is not None:                   # 2) 注入的钩子
                    try:
                        paths.CACHE.mkdir(parents=True, exist_ok=True)
                        cache_png.parent.mkdir(parents=True, exist_ok=True)
                    except Exception:
                        pass
                    try:
                        ok = fn(src, cache_png)
                    except Exception:
                        ok = None
                    img = self._read_png(cache_png) if ok else None
                else:                                # 3) 素材自带的预光栅化结果
                    legacy = self.root.joinpath(*_LEGACY_SVG_CACHE,
                                                Path(rel).name + ".png")
                    img = self._read_png(legacy)
                if img is None:
                    self._mark_missing(rel)
        with self._lock:
            self._images[key] = img
        return img

    @staticmethod
    def _read_png(p: Path) -> Image.Image | None:
        """读一张 PNG 成 RGBA；文件不存在/为空/损坏一律返回 ``None``（不抛异常）。"""
        try:
            if not p.is_file() or p.stat().st_size <= 0:
                return None
            with Image.open(p) as im:
                im.load()
                return im.copy() if im.mode == "RGBA" else im.convert("RGBA")
        except Exception:
            return None

    # ── 卡框 ────────────────────────────────────────────────────────
    def frame(self, base: str, pendulum: bool = False) -> Image.Image | None:
        """官方卡框整图（原生 1394×2031，RGBA，全不透明）。

        ``base`` 取 ``normal/effect/ritual/fusion/synchro/xyz/link/spell/trap/token``；
        ``pendulum=True`` 取灵摆变体（只有前 6 种基座存在）。
        """
        base_key = _normalize(base).replace("frame/", "")
        if base_key not in FRAME_BASES:
            base_key = {
                "普通": "normal", "通常": "normal", "效果": "effect", "儀式": "ritual",
                "仪式": "ritual", "融合": "fusion", "同调": "synchro", "同步": "synchro",
                "超量": "xyz", "多维": "xyz", "连接": "link", "鏈接": "link",
                "链接": "link", "魔法": "spell", "陷阱": "trap", "罠": "trap",
                "衍生物": "token", "token": "token",
            }.get(base_key, base_key)
        suffix = "-pendulum" if pendulum else ""
        return self._load(f"frame/{base_key}{suffix}.png")

    # ── 属性圆标 / 魔陷徽记 / 星级 / 箭头 ────────────────────────────
    def attribute(self, key: str) -> Image.Image | None:
        """属性圆标（128×128 RGBA）。中文属性名与英文键都接受。"""
        k = _normalize(key).replace("attribute/", "")
        k = _ATTRIBUTE_ALIASES.get(k, k)
        if k not in ATTRIBUTE_KEYS:
            return None
        return self._load(f"attribute/{k}.png")

    def spell_trap_badge(self, frame: str, kind: str) -> Image.Image | None:
        """魔陷种类徽记（72×72 RGBA）。``kind=normal`` 时官方无独立徽记，返回 ``None``。"""
        f = _normalize(frame)
        if f not in ("spell", "trap", "magic", "罠", "魔法", "陷阱"):
            return None
        k = _normalize(kind).replace("icon/", "")
        k = _KIND_ALIASES.get(k, k)
        if k == "normal":          # 通常魔法/通常陷阱：真卡不画种类徽记
            return None
        if k not in ("ritual", "quick-play", "continuous", "equip", "field", "counter"):
            return None
        return self._load(f"icon/{k}.png")

    def star(self, kind: str = "level") -> Image.Image | None:
        """星级符号（88×88 RGBA）。``level`` 红金星 / ``rank`` 黑阶星。"""
        k = _normalize(kind)
        k = {"level": "level", "等级": "level", "星": "level", "lv": "level", "red": "level",
             "rank": "rank", "阶级": "rank", "階級": "rank", "黑": "rank",
             "black": "rank", "xyz": "rank"}.get(k, k)
        if k not in ("level", "rank"):
            return None
        return self._load(f"star/{k}.png")

    def arrow(self, direction: str, on: bool = True) -> Image.Image | None:
        """连接箭头（8 方向 × on/off 两态）。``direction`` 用中文方位或英文。"""
        d = _normalize(direction).replace("arrow/", "")
        d = ARROW_DIRECTIONS.get(d, d)
        d = _ARROW_ALIASES.get(d, d)
        if d not in set(ARROW_DIRECTIONS.values()):
            return None
        return self._load(f"arrow/{d}-{'on' if on else 'off'}.png")

    # ── 覆膜 / 防伪 / 纪念标 / 版权标 ───────────────────────────────
    def rarity_layer(self, key: str) -> Image.Image | None:
        """稀有度覆膜整卡图（1394×2031 RGBA）。``ur/ser/gser/hr/pser/pser-print/gr/dt/attribute-rare``。"""
        k = _normalize(key).replace("rare/", "")
        k = _RARITY_ALIASES.get(k, k)
        if k not in RARITY_KEYS:
            return None
        return self._load(f"rare/{k}.png")

    def laser(self, variant: int = 1) -> Image.Image | None:
        """激光防伪标（72×72 RGBA）。``variant`` 1–4（4 为素材里的异常小文件）。"""
        try:
            v = int(variant)
        except Exception:
            return None
        if v not in LASER_VARIANTS:
            return None
        return self._load(f"laser/{v}.png")

    def stamp(self, key: str = "20th") -> Image.Image | None:
        """纪念标（445×358 RGBA）。``20th`` 与素材实际名 ``twentieth`` 都接受。"""
        k = _normalize(key).replace("stamp/", "")
        k = _STAMP_ALIASES.get(k, k)
        if k != "twentieth":
            return None
        return self._load("stamp/twentieth.png")

    def copyright_mark(self, lang: str, color: str = "black") -> Image.Image | None:
        """版权标（SVG，需光栅化）。

        ``lang`` 取 ``'sc'|'jp'|'en'|'zh_cn'|'zh_tw'|'ja'|'en'``；``color`` 取
        ``black`` / ``white`` 及中文「黑/白」。``zh_tw`` 无独立素材，回落 ``sc``。
        未注入光栅化钩子时返回 ``None`` 并记入 :meth:`missing`。
        """
        lg = _COPYRIGHT_LANGS.get(_normalize(lang))
        if lg is None:
            return None
        cl = _COPYRIGHT_COLORS.get(_normalize(color), "black")
        return self._load_svg(f"copyright/{lg}-{cl}.svg")

    # ── 杂项 ────────────────────────────────────────────────────────
    def icon(self, name: str) -> Image.Image | None:
        """通用图标入口：魔陷徽记、掩码、出血、卡背、Astral 美术字等。"""
        k = _normalize(name).replace("icon/", "")
        if k in _ICON_ALIASES:
            target = _ICON_ALIASES[k]
            return self._load_svg(target + ".svg") if target.endswith("astral") else self._load(target + ".png")
        for kind in SPELL_TRAP_KINDS:
            if _KIND_ALIASES.get(k) == _KIND_ALIASES.get(kind) and _KIND_ALIASES.get(kind) != "normal":
                return self._load(f"icon/{_KIND_ALIASES[kind]}.png")
        return None

    def card_back(self) -> Image.Image | None:
        """出血版卡背（1488×2126 RGBA）。"""
        return self._load("back/card-back-bleed.png")

    def bleeds(self) -> Image.Image | None:
        """出血版卡面（1488×2126 RGBA）。"""
        return self._load("bleed/card-bleed.png")

    def mask(self, pendulum: bool = False) -> Image.Image | None:
        """插画窗遮罩（额外便利方法；亮度通道才是有效遮罩，见 NOTICE）。"""
        return self._load("mask/card-mask-pendulum.png" if pendulum else "mask/card-mask.png")

    def stat_art(self, kind: str = "atk-def") -> Image.Image | None:
        """Astral 版数值行美术字（SVG）。``kind=atk-def|atk-link``。"""
        k = _normalize(kind)
        k = {"atk-def": "atk-def-astral", "atk_def": "atk-def-astral", "atkdef": "atk-def-astral",
             "atk-link": "atk-link-astral", "atk_link": "atk-link-astral",
             "atklink": "atk-link-astral", "link": "atk-link-astral"}.get(k)
        if k is None:
            return None
        return self._load_svg(f"stat/{k}.svg")

    # ── 度量缓存（给渲染器做版面计算，避免重复 getbbox）────────────────
    @lru_cache(maxsize=4096)
    def _measure_cached(self, key: str, text: str, size: int) -> tuple[int, int, int, int]:
        """度量内核（按 role+文本+字号缓存）：返回 ``(宽, 高, x0, y0)``。"""
        from . import fonts as _fonts          # 局部导入，规避循环依赖
        font = _fonts.load(key, size)
        if font is None:
            return (0, 0, 0, 0)
        try:
            box = font.getbbox(text or " ")
        except Exception:
            return (0, 0, 0, 0)
        x0, y0, x1, y1 = box
        return (int(x1 - x0), int(y1 - y0), int(x0), int(y0))

    def measure(self, role: str, text: str, size: int, lang: str = "zh_cn") -> tuple[int, int]:
        """用某 role 的字体量一行文本，返回 ``(宽, 高)``；字体不可用时返回 ``(0, 0)``。

        结果按 ``(role, text, size)`` 缓存 —— ``ImageFont`` 对象本身不跨 size 复用，
        但「文本 → 像素尺寸」是纯函数，可以安全缓存。
        """
        w, h, _x0, _y0 = self._measure_cached(role, text, int(size))
        return (w, h)

    # ── 诊断 ────────────────────────────────────────────────────────
    def missing(self) -> set[str]:
        """已请求但不存在的素材相对路径（小写、``/`` 分隔）集合。"""
        with self._lock:
            return set(self._missing)

    def clear_missing(self) -> None:
        """清空缺失登记（doctor 重跑 / 素材补齐后调用）。"""
        with self._lock:
            self._missing.clear()

    def reset(self) -> None:
        """丢掉全部缓存与登记，下次访问重新扫描磁盘（测试用）。"""
        with self._lock:
            self._index = None
            self._files = []
            self._skipped = []
            self._missing.clear()
            self._images.clear()
            self._digest = None
            self._legacy_index = None

    def digest(self) -> str:
        """素材指纹：``sha1(相对路径 + 大小 + mtime_ns)`` 取前 16 位十六进制。

        用于缓存失效（``_cache/``、``__pycache__/``、根目录 ``_`` 预览图不计入）。
        同一份素材内容不变时结果稳定；新增/删除/改动任一文件都会变。
        """
        with self._lock:
            if self._digest is not None:
                return self._digest
        self._ensure_index()
        h = hashlib.sha1()
        for p in self._files:
            rel = _asset_rel_path(p, self.root)
            try:
                st = p.stat()
                size, mtime = st.st_size, st.st_mtime_ns
            except Exception:
                size, mtime = -1, -1
            h.update(f"{rel}\0{size}\0{mtime}\n".encode("utf-8", "replace"))
        value = h.hexdigest()[:16]
        with self._lock:
            self._digest = value
        return value

    def _iter_category(self, category: str) -> Iterator[tuple[str, str, bool]]:
        """产出 ``(相对路径, 索引键, 是否存在)``。"""
        for rel in self.expected.get(category, ()):
            yield rel, _normalize(rel), self.path(rel) is not None

    def availability(self) -> dict:
        """doctor 用：按分类统计「存在 / 总数」，附缺失清单与指纹。

        返回形如::

            {"root": "data/assets", "exists": True, "digest": "…", "files": 78,
             "categories": {"frame": {"present": 16, "total": 16, "missing": []}, …},
             "missing": [], "skipped": ["_cache/…"], "unexpected": []}
        """
        self._ensure_index()
        categories: dict[str, dict] = {}
        all_missing: list[str] = []
        known = set()
        for cat in CATEGORIES:
            present, miss = 0, []
            for rel, _key, ok in self._iter_category(cat):
                known.add(_normalize(rel))
                if ok:
                    present += 1
                else:
                    miss.append(rel)
            categories[cat] = {"present": present, "total": present + len(miss), "missing": miss}
            all_missing.extend(miss)
        unexpected = sorted(
            _asset_rel_path(p, self.root) for p in self._files
            if _normalize(_asset_rel_path(p, self.root)) not in known
        )
        return {
            "root": paths.rel(self.root),
            "exists": self.root.is_dir(),
            "files": len(self._files),
            "digest": self.digest(),
            "categories": categories,
            "missing": all_missing,
            "requested_missing": sorted(self.missing()),
            "unexpected": unexpected,
            "skipped": sorted(self._skipped),
            "image_cache": len(self._images),
        }

    def describe(self) -> dict:
        """:meth:`availability` 的别名（与 ``paths.describe()`` 风格一致）。"""
        return self.availability()

    def __repr__(self) -> str:  # pragma: no cover - 展示用
        """调试用一行摘要：根目录与已扫描到的素材文件数。"""
        n = len(self._files) if self._index is not None else "?"
        return f"<AssetLibrary root={self.root} files={n}>"


# ══════════════════════════════════════════════════════════════════════
#  模块级单例
# ══════════════════════════════════════════════════════════════════════

_default: AssetLibrary | None = None
_default_lock = threading.Lock()


def library() -> AssetLibrary:
    """默认 :class:`AssetLibrary` 单例（根目录 = ``paths.ASSETS``）。"""
    global _default
    if _default is None:
        with _default_lock:
            if _default is None:
                _default = AssetLibrary()
    return _default


# ══════════════════════════════════════════════════════════════════════
#  自检
# ══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":  # pragma: no cover
    import json

    lib = library()
    print(json.dumps(lib.availability(), ensure_ascii=False, indent=2))
    fr = lib.frame("effect")
    print("frame(effect) =", None if fr is None else (fr.size, fr.mode))
    print("frame(xyz, pendulum) =", getattr(lib.frame("xyz", pendulum=True), "size", None))
    print("attribute('暗') =", getattr(lib.attribute("暗"), "size", None))
    print("spell_trap_badge('spell','quick') =",
          getattr(lib.spell_trap_badge("spell", "quick"), "size", None))
    print("star('rank') =", getattr(lib.star("rank"), "size", None))
    print("arrow('右上') =", getattr(lib.arrow("右上"), "size", None))
    print("arrow('右下', on=False) =", getattr(lib.arrow("右下", on=False), "size", None))
    print("rarity_layer('UR') =", getattr(lib.rarity_layer("UR"), "size", None))
    print("laser(1) =", getattr(lib.laser(1), "size", None))
    print("stamp('20th') =", getattr(lib.stamp("20th"), "size", None))
    print("copyright_mark('zh_cn') =", getattr(lib.copyright_mark("zh_cn"), "size", None))
    print("card_back() =", getattr(lib.card_back(), "size", None))
    print("bleeds() =", getattr(lib.bleeds(), "size", None))
    print("FRAME_NATIVE =", FRAME_NATIVE, "digest =", lib.digest())
    print("missing =", sorted(lib.missing()))
