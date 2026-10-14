"""服务层与内核之间的胶水。

这里只做三件事，且**不含任何业务判断**（判断全在内核模块里）：

1. **软导入**：``assistant`` / ``duel.bot`` / ``content.lua.emit`` 这些模块可能
   还没实现或依赖缺失。缺了要给出**明确的 501 + 中文下一步**，不能让界面 500。
2. **载荷 → CardSpec**：前端提交的是 JSON，需要安全地变成领域对象。
3. **聚合视图**：界面一次请求要拿到「规格 + 卡文 + 脚本 + 质量门 + 预览地址」，
   在内核侧拼好，避免前端发五个请求。
"""
from __future__ import annotations

import importlib
import json
import re
import threading
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from ..core import errors, paths
from ..core.enums import DEFAULT_LANG, FRAMES, LANGS, RARITIES
from ..core.models import CardSpec, EffectSpec
from ..pool import repo

__all__ = ["try_import", "require", "official", "spec_from_payload", "load_spec",
           "save_spec", "card_view", "cards_index", "soft_call", "ART_TYPES"]

#: 前端可以请求的产物类型（文件接口的白名单根）
ART_TYPES: dict[str, Path] = {}

_LOCK = threading.RLock()
_OFFICIAL: Any = None
_OFFICIAL_FAILED: str = ""


# ══════════════════════════════════════════════════════════════════════
#  软导入
# ══════════════════════════════════════════════════════════════════════
def try_import(dotted: str):
    """导入模块；失败返回 ``None``（不抛）。

    ``dotted`` 可以是 ``cardforge.content.lua.emit`` 或 ``.content.lua.emit``。
    """
    name = dotted if not dotted.startswith(".") else "cardforge" + dotted
    try:
        return importlib.import_module(name)
    except Exception:
        return None


def require(dotted: str, label: str, hint: str = ""):
    """导入失败就抛 ``EnvError``，带**中文**的可执行建议。"""
    mod = try_import(dotted)
    if mod is None:
        raise errors.EnvError(
            f"{label}尚不可用",
            hint or f"确认 {dotted.lstrip('.')} 模块存在；"
                    f"或先用命令行完成这一步，界面会跟进")
    return mod


def soft_call(dotted: str, func: str, *args, label: str = "",
              hint: str = "", **kw) -> dict:
    """调用一个可能不存在的内核函数，统一包装成 ``{"ok":..., "value"/"error"}``。

    界面拿到 ``ok=False`` 时显示降级说明，而不是白屏或转圈。
    """
    label = label or f"{dotted}.{func}"
    try:
        mod = require(dotted, label, hint)
        fn: Optional[Callable] = getattr(mod, func, None)
        if not callable(fn):
            raise errors.EnvError(f"{label} 里没有 {func}() 这个入口",
                                  hint or "检查模块是否实现完整")
        return {"ok": True, "value": fn(*args, **kw)}
    except errors.CardForgeError as e:
        return {"ok": False, "error": e.message, "kind": type(e).__name__,
                "hint": e.hint}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "kind": "internal",
                "hint": "这是内核缺陷，不是你的卡的问题。把本 JSON 反馈出来"}


# ══════════════════════════════════════════════════════════════════════
#  官方卡池（懒加载 + 失败留痕）
# ══════════════════════════════════════════════════════════════════════
def official(*, reload: bool = False):
    """返回 ``OfficialPool``；不可用时返回 ``None``（调用方负责降级说明）。"""
    global _OFFICIAL, _OFFICIAL_FAILED
    with _LOCK:
        if _OFFICIAL is not None and not reload:
            return _OFFICIAL
        if _OFFICIAL_FAILED and not reload:
            return None
        try:
            from ..pool import official as off
            _OFFICIAL = off.load()
        except Exception as e:
            _OFFICIAL_FAILED = f"{type(e).__name__}: {e}"
            _OFFICIAL = None
        return _OFFICIAL


def official_status() -> dict:
    pool = official()
    if pool is None:
        return {"available": False,
                "reason": _OFFICIAL_FAILED or "未找到 vendor/data/*.cdb",
                "hint": "把官方卡池 .cdb 放进 vendor/data/ 即可启用查重与字段核对"}
    try:
        n = pool.count() if callable(getattr(pool, "count", None)) else None
    except Exception:
        n = None
    return {"available": True, "count": n,
            "path": str(getattr(pool, "path", getattr(pool, "cdb", "")) or ""),
            "hint": ""}


# ══════════════════════════════════════════════════════════════════════
#  规格进出
# ══════════════════════════════════════════════════════════════════════
_INT_FIELDS = {"id", "level", "pendulum_scale"}
_STR_FIELDS = {"name", "frame", "attribute", "race", "archetype", "setcode",
               "spell_kind", "trap_kind", "flavor"}


def _coerce(d: dict) -> dict:
    """把前端传来的松类型值修成 dataclass 需要的类型。

    浏览器 ``<input>`` 出来的全是字符串 —— 不在这里收口，后面每个 ``int()``
    调用点都要各写一遍，而漏一个就是 500。
    """
    out = dict(d or {})
    for k in _INT_FIELDS:
        if k in out and out[k] not in (None, "", "?"):
            try:
                out[k] = int(float(str(out[k]).strip()))
            except Exception:
                pass
        elif k == "pendulum_scale" and str(out.get(k, "")).strip() in ("", "0", "None"):
            out[k] = None
    for k in ("atk", "dfd"):
        if k in out:
            v = str(out[k]).strip() if out[k] is not None else ""
            if v in ("", "?", "？"):
                out[k] = "?"
            else:
                try:
                    out[k] = int(float(v))
                except Exception:
                    out[k] = v
    for k in _STR_FIELDS:
        if k in out and out[k] is not None and not isinstance(out[k], str):
            out[k] = str(out[k])
    if "effects" in out and isinstance(out["effects"], list):
        out["effects"] = [e if isinstance(e, dict) else str(e) for e in out["effects"]]
    return out


def spec_from_payload(payload: Any, *, card_id: Optional[int] = None) -> CardSpec:
    """JSON → CardSpec。未知字段忽略（``from_dict`` 已经做了），坏字段给中文错误。"""
    if isinstance(payload, CardSpec):
        return payload
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception as e:
            raise errors.SpecError(f"spec 不是合法 JSON：{e}", "前端请直接提交对象") from e
    if not isinstance(payload, dict):
        raise errors.SpecError(f"spec 结构不对（收到 {type(payload).__name__}）",
                               "应提交 CardSpec 的 JSON 对象")
    d = _coerce(payload)
    if card_id is not None:
        d["id"] = int(card_id)
    if "id" in d:
        try:
            d["id"] = int(d["id"])
        except Exception:
            d.pop("id")
    if d.get("frame") and d["frame"] not in FRAMES:
        raise errors.SpecError(f"未知的卡种：{d['frame']}",
                               f"可用卡种：{'、'.join(FRAMES)}")
    try:
        spec = CardSpec.from_dict(d)
    except errors.CardForgeError:
        raise
    except Exception as e:
        raise errors.SpecError(f"规格解析失败：{e}",
                               "字段类型不对。卡号/等级/刻度必须是整数，"
                               "攻击力可以是整数或 '?'") from e
    if spec.render.rarity not in RARITIES:
        spec.render.rarity = "common"
    if spec.render.lang_text not in LANGS:
        spec.render.lang_text = DEFAULT_LANG
    return spec


def load_spec(card_id: int, archetype: str = "") -> CardSpec:
    spec = repo.load_card(int(card_id), archetype)
    if spec is None:
        raise errors.CardForgeError(f"工作区里没有卡号 {card_id} 的卡",
                                    "先在「新建」里建一张，或用 card new 命令")
    return spec


def save_spec(spec: CardSpec, *, note: str = "") -> dict:
    path = repo.save_card(spec, snapshot=True, note=note) if note else \
        repo.save_card(spec, snapshot=True)
    return {"path": paths.rel(Path(path)) if path else "", "id": spec.id}


# ══════════════════════════════════════════════════════════════════════
#  聚合视图
# ══════════════════════════════════════════════════════════════════════
def _lua_of(spec: CardSpec) -> str:
    if getattr(spec, "lua", ""):
        return spec.lua
    emit = try_import("cardforge.content.lua.emit")
    fn = getattr(emit, "emit_script", None) if emit else None
    if not callable(fn):
        return ""
    try:
        return str(fn(spec) or "")
    except Exception as e:
        return f"-- [CardForge] 脚本生成失败：{type(e).__name__}: {e}\n"


def _texts_of(spec: CardSpec) -> dict:
    """卡文：优先用已写回的 text_i18n，缺失的语言现场生成。"""
    out: dict[str, Any] = {}
    gen = try_import("cardforge.content.psct.gen")
    for lang in LANGS:
        txt = spec.text_i18n.get(lang) or ""
        meta: dict[str, Any] = {"text": txt, "source": "stored" if txt else "empty"}
        if not txt and gen is not None:
            try:
                m = gen.compose_with_meta(spec, lang)
                meta = {"text": m.get("text", ""), "source": "generated",
                        "used_lang": m.get("used_lang", lang),
                        "degraded": m.get("degraded", False),
                        "reason": m.get("reason", "")}
            except Exception as e:
                meta["reason"] = f"生成失败：{type(e).__name__}: {e}"
        pend = spec.pendulum_text_i18n.get(lang) or ""
        if spec.is_pendulum:
            meta["pendulum_text"] = pend
            if not pend and gen is not None and hasattr(gen, "compose_pendulum"):
                try:
                    meta["pendulum_text"] = gen.compose_pendulum(spec, lang)
                except Exception:
                    pass
        out[lang] = meta
    return out


def cards_index(archetype: str = "") -> list[dict]:
    try:
        return repo.list_cards(archetype)
    except Exception:
        return []


def card_view(spec: CardSpec, *, with_gates: Iterable[str] = (),
              preview_width: int = 0) -> dict:
    """一次请求给齐界面需要的东西。"""
    view: dict[str, Any] = {
        "spec": spec.to_dict(),
        "summary": spec.summary(),
        "labels": spec.labels(),
        "lua": _lua_of(spec),
        "texts": _texts_of(spec),
        "type_bits_hex": f"0x{spec.type_bits:X}",
        "files": _files_of(spec),
    }
    if preview_width:
        view["preview_url"] = f"/api/render/preview?card={spec.id}&width={preview_width}"
    reports = {}
    for g in with_gates:
        rep = _gate_cached(spec, str(g).upper())
        if rep is not None:
            reports[str(g).upper()] = rep
    if reports:
        view["gates"] = reports
    return view


_GATE_CACHE: dict[str, dict] = {}


def _gate_cached(spec: CardSpec, gate: str) -> Optional[dict]:
    """按「卡号 + 规格指纹」缓存质量门结果 —— 改了规格自动失效。"""
    try:
        digest = json.dumps(spec.to_dict(), ensure_ascii=False, sort_keys=True,
                            default=str)
        key = f"{spec.id}:{gate}:{hash(digest) & 0xFFFFFFFF:08x}"
    except Exception:
        return None
    if key in _GATE_CACHE:
        return _GATE_CACHE[key]
    from ..pipeline import gates
    try:
        if gate == "G1":
            rep = gates.g1_balance(spec, official())
        elif gate == "G2":
            rep = gates.g2_script(spec, _lua_of(spec))
        elif gate == "G3":
            rep = gates.g3_duel(spec)
        else:
            return None
    except Exception as e:
        rep = None
        out = {"gate": gate, "status": "error",
               "summary": f"质量门执行失败：{type(e).__name__}: {e}", "issues": []}
        _GATE_CACHE[key] = out
        return out
    out = rep.to_dict()
    _GATE_CACHE[key] = out
    if len(_GATE_CACHE) > 400:
        _GATE_CACHE.clear()
    return out


def _files_of(spec: CardSpec) -> dict:
    """已存在的产物 → 可供界面直接引用的相对路径。"""
    out: dict[str, Any] = {}
    sp = paths.card_spec_path(spec.id, spec.archetype or "")
    if Path(sp).exists():
        out["spec"] = paths.rel(Path(sp))
    for cand in (paths.script_path(spec.id), Path(sp).parent / "card.lua"):
        if Path(cand).exists():
            out["script"] = paths.rel(Path(cand))
            break
    adir = paths.art_dir(spec.id, spec.archetype or "")
    if Path(adir).is_dir():
        vs = sorted(Path(adir).glob("v*.png"),
                    key=lambda x: int(re.sub(r"\D", "", x.stem) or 0))
        if vs:
            out["art"] = paths.rel(vs[-1])
    for cand in (paths.pic_path(spec.id), paths.field_pic_path(spec.id)):
        if Path(cand).exists():
            out.setdefault("pic", paths.rel(Path(cand)))
            break
    return out
