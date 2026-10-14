"""跨平台路径解析 —— 取代旧工程里写死的 ``D:\\workbuddy workspace\\...``。

优先级：环境变量 > 配置文件 > 默认值。
所有目录都是**惰性创建**，导入本模块不产生任何副作用。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

_ENV_PREFIX = "CARDFORGE_"


def _env_path(key: str) -> Path | None:
    raw = os.environ.get(_ENV_PREFIX + key) or os.environ.get(key)
    return Path(raw).expanduser().resolve() if raw else None


def _frozen_root() -> Optional[Path]:
    """PyInstaller 打包后的**只读资源根**（data/ web/ vendor/ 都打在它里面）。

    onefile 时 ``sys._MEIPASS`` 是临时解包目录（只读、退出即焚）；
    onefolder（PyInstaller 6）时它是 ``dist/<App>/_internal``。两者对只读资源等价。
    """
    if not getattr(sys, "frozen", False):
        return None
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(str(base))
    return Path(sys.executable).resolve().parent


def _find_root() -> Path:
    """项目根 = 本文件的爷爷的爷爷（cardforge/core/paths.py -> 根）。

    打包后（``sys.frozen``）改为 bundle 内的资源根 —— 见 :func:`_frozen_root`。
    """
    if getattr(sys, "frozen", False):
        return _frozen_root() or Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


ROOT: Path = _env_path("ROOT") or _find_root()


def _sub(env_key: str, default: Path) -> Path:
    p = _env_path(env_key) or default
    return p


# ── 只读资源 ──────────────────────────────────────────────────────────
DATA: Path = _sub("DATA", ROOT / "data")
ASSETS: Path = DATA / "assets"                 # 卡框/图标/字体（MIT 素材）
FONTS: Path = ASSETS                           # 兼容旧布局
LEXICONS: Path = DATA / "lexicons"             # 多语言术语表 / PSCT 句式
KNOWLEDGE: Path = DATA / "knowledge"           # 设计方法论知识库
TEMPLATES: Path = DATA / "templates"           # 工作流模板、卡组模板
WEB: Path = _sub("WEB", ROOT / "web")

VENDOR: Path = _sub("VENDOR", ROOT / "vendor")
ENGINE_DIR: Path = VENDOR / "engine"           # ocgcore 原生库（可选层 L3）
OFFICIAL_SCRIPTS: Path = VENDOR / "scripts"    # 官方 Lua 运行库与抽样
OFFICIAL_CDB: Path = VENDOR / "data"           # 官方卡池 .cdb
AI_DECKS: Path = VENDOR / "decks"              # 测试用 AI 卡组

DOCS: Path = ROOT / "docs"
RESEARCH: Path = ROOT / "research"
TESTS: Path = ROOT / "tests"

# ── 可写工作区 ────────────────────────────────────────────────────────
def _default_workspace() -> Path:
    """工作区是**可写**的：打包后放 exe 同级（onefile 的临时解包目录退出即焚，
    把用户的卡扔那儿等于每次退出都格式化）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "workspace"
    return ROOT / "workspace"


WORKSPACE: Path = _sub("WORKSPACE", _default_workspace())
CONFIG_DIR: Path = WORKSPACE / "config"           # LLM 接入等用户配置（含密钥）
CARDS: Path = WORKSPACE / "cards"              # 单卡工程
ARCHETYPES: Path = WORKSPACE / "archetypes"    # 系列圣经
DECKS: Path = WORKSPACE / "decks"
PICS: Path = WORKSPACE / "pics"                # 卡图（art/<id>/vN.png）
OUT: Path = WORKSPACE / "out"                  # 最终产物
LOGS: Path = WORKSPACE / "logs"
CACHE: Path = WORKSPACE / ".cache"             # 字体转换、素材光栅化等缓存
HISTORY: Path = WORKSPACE / ".history"         # 版本快照

EXPORT_DIR: Path = OUT / "expansions"
CONFIG_FILE: Path = WORKSPACE / "cardforge.json"
LLM_CONFIG_FILE: Path = CONFIG_DIR / "llm.json"   # LLM 接入配置（多 provider + active）

_ALL_DIRS = (
    WORKSPACE, CONFIG_DIR, CARDS, ARCHETYPES, DECKS, PICS, OUT, LOGS, CACHE, HISTORY,
    EXPORT_DIR, EXPORT_DIR / "pics", EXPORT_DIR / "script", CACHE / "fonts",
    CACHE / "svg",
)


def ensure_dirs() -> list[Path]:
    """创建所有工作区目录，返回实际创建的（供 doctor 报告）。"""
    created = []
    for d in _ALL_DIRS:
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
            created.append(d)
    return created


# ── 单卡/系列的工程目录约定 ──────────────────────────────────────────
def card_dir(card_id: int, archetype: str | None = None) -> Path:
    """单卡工程目录。有系列时归入系列子目录，便于整系列导出。"""
    if archetype:
        return CARDS / _safe_name(archetype) / str(int(card_id))
    return CARDS / str(int(card_id))


def card_spec_path(card_id: int, archetype: str | None = None) -> Path:
    return card_dir(card_id, archetype) / "spec.json"


def archetype_dir(name: str) -> Path:
    return ARCHETYPES / _safe_name(name)


def art_dir(card_id: int, archetype: str | None = None) -> Path:
    if archetype:
        return PICS / "art" / _safe_name(archetype) / str(int(card_id))
    return PICS / "art" / str(int(card_id))


def pic_path(card_id: int, ext: str = "jpg") -> Path:
    """EDOPro 用的成品卡图路径（<id>.jpg）。"""
    return PICS / f"{int(card_id)}.{ext}"


def field_pic_path(card_id: int, ext: str = "jpg") -> Path:
    """场地魔法背景图（field/<id>.jpg）。"""
    return PICS / "field" / f"{int(card_id)}.{ext}"


def script_path(card_id: int) -> Path:
    return WORKSPACE / "script" / f"c{int(card_id)}.lua"


def history_dir(kind: str, key: str) -> Path:
    return HISTORY / kind / _safe_name(key)


# ── 工具 ─────────────────────────────────────────────────────────────
_UNSAFE = '<>:"/\\|?*'


def _safe_name(name: str) -> str:
    """把系列名等转成安全的目录名（保留中日文，去掉路径分隔与保留字符）。"""
    s = "".join("_" if c in _UNSAFE else c for c in str(name)).strip(" .")
    return s or "_unnamed"


def rel(p: Path) -> str:
    """转成相对项目根的显示路径，失败则返回绝对路径。"""
    try:
        return str(Path(p).resolve().relative_to(ROOT))
    except Exception:
        return str(p)


def describe() -> dict:
    """doctor 用：列出关键路径与存在性。"""
    items = {
        "root": ROOT, "data": DATA, "assets": ASSETS, "lexicons": LEXICONS,
        "knowledge": KNOWLEDGE, "web": WEB, "vendor": VENDOR,
        "engine": ENGINE_DIR, "official_scripts": OFFICIAL_SCRIPTS,
        "workspace": WORKSPACE, "cache": CACHE,
    }
    return {k: {"path": rel(v), "exists": Path(v).exists()} for k, v in items.items()}
