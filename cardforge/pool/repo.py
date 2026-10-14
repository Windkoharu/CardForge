"""项目仓库 —— ``workspace/cards`` / ``archetypes`` / ``decks`` 的 CRUD + 版本快照与回滚。

三条硬规则
----------
1. **落盘 JSON 一律 UTF-8 无 BOM**，``json.dumps(..., ensure_ascii=False, indent=2)``，
   换行固定 ``\\n``。中文直接原样写，不转 ``\\uXXXX``。
2. **增量保存**：只有「规范化 JSON」真的变了才写新快照。比较时剔除 ``updated``
   时间戳字段，否则每次保存都会因为时间戳不同而误判为「变了」。
   幂等保存不会推进 ``updated``，也不会产生新快照。
3. **读旧版自动迁移**：v0.x 的 ``def`` / ``text`` / ``_lua`` / ``_strings`` / ``type_flags``
   由 ``CardSpec.from_dict`` 迁移（已实测支持），迁移后**立即写回新版**。

快照布局::

    workspace/.history/<kind>/<key>/v1.json     ← 第一版
    workspace/.history/<kind>/<key>/v2.json     ← 第二次内容变化
    ...

``kind`` ∈ ``{"cards","archetypes","decks"}``；``key`` 为卡号 / 系列名 / 卡组名。
每个快照是一个**信封**，而不是裸 payload::

    {"kind":"cards","key":"210000000","version":1,"ts":"2026-07-09T12:00:00",
     "note":"","digest":"3fa9c1…","path":"workspace/cards/210000000/spec.json",
     "payload":{…CardSpec.to_dict()…}}

``path`` 记的是**写入时的真实落盘位置**，所以 ``rollback()`` 能精确还原（哪怕卡后来
换了系列子目录）。回滚**不覆盖历史**：它把旧内容写回现场，并追加一条新快照
（``note="rollback ← vN"``），所以任何一步都能再退回去。
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from ..core import paths
from ..core.errors import SpecError
from ..core.models import SCHEMA_VERSION, Archetype, CardSpec, DeckSpec
from ..core.paths import _safe_name as _safe  # noqa: PLC2701 —— 复用 core 的唯一一份名字消毒

__all__ = [
    "KINDS", "card_key", "save_card", "load_card", "list_cards", "delete_card",
    "save_archetype", "load_archetype", "list_archetypes", "delete_archetype",
    "save_deck", "load_deck", "list_decks", "delete_deck",
    "snapshots", "latest_snapshot", "rollback", "history_path",
    "card_spec_path", "archetype_spec_path", "deck_spec_path",
]

KINDS: tuple[str, ...] = ("cards", "archetypes", "decks")

#: 快照比较时忽略的字段（时间戳会自己变，不代表内容变了）。
_VOLATILE = frozenset({"updated"})

_CARD_FILE = "spec.json"
_ARCH_FILE = "archetype.json"


# ══════════════════════════════════════════════════════════════════════
#  基础设施
# ══════════════════════════════════════════════════════════════════════
def _now() -> str:
    """本地 ISO 时间戳（**微秒**精度）。

    用微秒而不是秒：同一秒内先改一次再存一次时，秒精度会让 ``updated`` 看起来没推进
    （实测踩到过）。微秒精度下「内容变了 → 时间戳必然前进」这句断言才成立，
    同时仍是字典序可排序的 ISO 串。
    """
    return datetime.now().isoformat(timespec="microseconds")


def _canon(data: Any) -> str:
    """规范化 JSON —— 快照比较的唯一依据（键排序、无空白）。"""
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(data: Any) -> str:
    return hashlib.sha256(_canon(data).encode("utf-8")).hexdigest()[:16]


def _write_json(path: Path, data: Any) -> None:
    """UTF-8 无 BOM + ``ensure_ascii=False`` + ``indent=2`` + ``\\n``。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2)
    path.write_text(text + "\n", encoding="utf-8", newline="\n")


def _read_json(path: Path) -> dict | None:
    """读 JSON；不存在/损坏返回 None（可降级，不抛异常）。"""
    try:
        raw = path.read_text(encoding="utf-8-sig")   # 容忍历史文件带 BOM
    except (OSError, UnicodeDecodeError):
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _content_digest(d: dict | None) -> str:
    """剔除易变字段后的内容指纹。"""
    if not d:
        return ""
    return _digest({k: v for k, v in d.items() if k not in _VOLATILE})


def card_key(card_id: int) -> str:
    """卡号 → 快照目录键。"""
    return str(int(card_id))


def history_path(kind: str, key: str, version: int) -> Path:
    """``v{n}.json`` 的完整路径。"""
    return paths.history_dir(kind, key) / f"v{int(version)}.json"


# 现场路径（集中一处，便于 rollback 复用）
def card_spec_path(card_id: int, archetype: str = "") -> Path:
    return paths.card_spec_path(int(card_id), archetype or None)


def archetype_spec_path(name: str) -> Path:
    return paths.archetype_dir(name) / _ARCH_FILE


def deck_spec_path(name: str) -> Path:
    return paths.DECKS / f"{_safe(name)}.json"


# ══════════════════════════════════════════════════════════════════════
#  快照
# ══════════════════════════════════════════════════════════════════════
def _snapshot_versions(kind: str, key: str) -> list[int]:
    d = paths.history_dir(kind, key)
    if not d.is_dir():
        return []
    out = []
    for p in d.glob("v*.json"):
        stem = p.stem[1:]
        if stem.isdigit():
            out.append(int(stem))
    return sorted(out)


def latest_snapshot(kind: str, key: str) -> dict | None:
    """最新一条快照（含 payload）；没有则 None。"""
    versions = _snapshot_versions(kind, key)
    if not versions:
        return None
    return _read_json(history_path(kind, key, versions[-1]))


def _make_snapshot(kind: str, key: str, payload: dict, live_path: Path,
                   note: str = "", *, force: bool = False) -> dict | None:
    """写一条新快照。内容与最新快照一致且 ``force=False`` 时**不写**（增量保存）。"""
    if kind not in KINDS:
        raise SpecError(f"未知仓库类型：{kind}", hint=f"可用：{', '.join(KINDS)}")
    digest = _content_digest(payload)
    prev = latest_snapshot(kind, key)
    if prev is not None and not force and prev.get("digest") == digest:
        return prev
    versions = _snapshot_versions(kind, key)
    version = (versions[-1] + 1) if versions else 1
    envelope = {
        "kind": kind,
        "key": str(key),
        "version": version,
        "ts": _now(),
        "note": note,
        "digest": digest,
        "path": str(live_path),
        "payload": payload,
    }
    _write_json(history_path(kind, key, version), envelope)
    return envelope


def snapshots(kind: str, key: str) -> list[dict]:
    """列出某对象的全部快照（**不含 payload**，只给元信息，便于 UI 列表）。"""
    out: list[dict] = []
    for v in _snapshot_versions(kind, key):
        p = history_path(kind, key, v)
        env = _read_json(p) or {}
        try:
            size = p.stat().st_size
        except OSError:
            size = 0
        out.append({
            "version": v, "ts": env.get("ts", ""), "note": env.get("note", ""),
            "digest": env.get("digest", ""), "path": env.get("path", ""),
            "bytes": size, "file": str(p),
        })
    return out


def rollback(kind: str, key: str, version: int) -> dict:
    """把某对象的现场文件恢复成 ``v{version}`` 的内容。

    历史**只追加不重写**：回滚后现场内容等于 ``v{version}``，同时多出一条
    ``note="rollback ← vN"`` 的新快照，所以还能再退回去。

    :returns: ``{"ok","kind","key","version","path","new_version","payload"}``；
        失败时 ``{"ok": False, "error","hint"}``（不抛异常，方便 UI 直接展示）。
    """
    if kind not in KINDS:
        return {"ok": False, "error": f"未知仓库类型：{kind}",
                "hint": f"可用：{', '.join(KINDS)}"}
    env = _read_json(history_path(kind, key, version))
    if not env:
        avail = _snapshot_versions(kind, key)
        return {"ok": False, "error": f"没有 v{version} 快照（{kind}/{key}）",
                "hint": f"可用版本：{avail or '无'}"}
    payload = env.get("payload")
    if not isinstance(payload, dict):
        return {"ok": False, "error": f"v{version} 快照内容损坏", "hint": "换一个版本再试。"}

    live = _live_path_for(kind, key, env, payload)
    if live is None:
        return {"ok": False, "error": "无法确定该对象的落盘位置",
                "hint": "快照里缺 path 与 id/name，请手动恢复。"}
    _write_json(live, payload)
    new_env = _make_snapshot(kind, key, payload, live,
                             note=f"rollback ← v{int(version)}", force=True)
    return {
        "ok": True, "kind": kind, "key": str(key), "version": int(version),
        "path": str(live), "new_version": (new_env or {}).get("version", 0),
        "ts": _now(), "payload": payload,
    }


def _live_path_for(kind: str, key: str, env: dict, payload: dict) -> Path | None:
    """还原目标路径：优先用快照记的 ``path``，否则按 kind 重新推导。"""
    recorded = env.get("path")
    if recorded:
        return Path(recorded)
    if kind == "cards":
        cid = payload.get("id")
        if cid:
            return card_spec_path(int(cid), str(payload.get("archetype") or ""))
    elif kind == "archetypes":
        nm = payload.get("name") or key
        return archetype_spec_path(str(nm))
    elif kind == "decks":
        nm = payload.get("name") or key
        return deck_spec_path(str(nm))
    return None


# ══════════════════════════════════════════════════════════════════════
#  卡片
# ══════════════════════════════════════════════════════════════════════
def _find_card_path(card_id: int, archetype: str = "") -> tuple[Path, str]:
    """定位某卡号的 spec.json，返回 ``(路径, 实际所属系列)``。

    给了系列就只找那一个；没给就先找平铺目录，再扫一层系列子目录。
    """
    cid = int(card_id)
    if archetype:
        return card_spec_path(cid, archetype), str(archetype)
    flat = card_spec_path(cid, "")
    if flat.is_file():
        return flat, ""
    base = paths.CARDS
    if base.is_dir():
        for sub in sorted(p for p in base.iterdir() if p.is_dir()):
            cand = sub / str(cid) / _CARD_FILE
            if cand.is_file():
                return cand, sub.name
    return flat, ""


def save_card(spec: CardSpec, *, snapshot: bool = True, note: str = "") -> str:
    """保存一张卡到 ``workspace/cards[/<系列>]/<id>/spec.json``。

    * ``spec.created`` 为空时补当前时间；**内容真变了**才推进 ``spec.updated``。
    * 内容没变 → 不写新快照、不推进时间戳，但仍然保证 ``schema_version`` 是最新版
      （旧版文件需要迁移写回时会真的写一次盘）。
    * 卡号在同一工作区里唯一：保存后若在**别的**目录还留着同名 spec.json，
      旧文件会被清掉（并把空目录删掉），避免 ``list_cards`` 出现重复卡。

    :returns: 写入的 spec.json 路径字符串。
    """
    if not int(spec.id or 0):
        raise SpecError("卡号为 0，无法保存", hint="先分配卡号（pool.official.next_free_id）。")

    key = card_key(spec.id)
    target = card_spec_path(spec.id, str(spec.archetype or ""))
    old_path = target if target.is_file() else None
    if old_path is None:
        # 可能躺在别的系列目录里（或平铺目录里）
        found, _found_arch = _find_card_path(spec.id, "")
        if found.is_file():
            old_path = found
    old = _read_json(old_path) if old_path is not None else None

    if not spec.created:
        spec.created = str((old or {}).get("created") or _now())

    changed = (old is None) or (_content_digest(old) != _content_digest(spec.to_dict()))
    moved = old_path is not None and Path(old_path) != Path(target)
    schema_stale = bool(old) and old.get("schema_version") != SCHEMA_VERSION

    if changed or not spec.updated:
        spec.updated = _now()
    elif old and old.get("updated"):
        spec.updated = str(old["updated"])     # 幂等：保持原时间戳

    content = spec.to_dict()
    if changed or moved or schema_stale:
        _write_json(target, content)

    # 清掉同一卡号的游离副本（换了系列目录时旧文件让位）
    for p in _stale_card_paths(spec.id, target):
        _remove_card_file(p)

    if snapshot and (changed or old is None):
        _make_snapshot("cards", key, content, target, note=note)
    return str(target)


def _stale_card_paths(card_id: int, keep: Path) -> list[Path]:
    """同一卡号在别处残留的 spec.json。"""
    cid = int(card_id)
    out: list[Path] = []
    keep_r = Path(keep)
    base = paths.CARDS
    if not base.is_dir():
        return out
    cands = [base / str(cid) / _CARD_FILE]
    for sub in base.iterdir():
        if sub.is_dir():
            cands.append(sub / str(cid) / _CARD_FILE)
    for cand in cands:
        try:
            if cand.is_file() and cand.resolve() != keep_r.resolve():
                out.append(cand)
        except OSError:
            continue
    return out


def _remove_card_file(path: Path) -> None:
    """删文件，父目录空了就一起删（只删到 cards/ 这层为止）。"""
    try:
        path.unlink()
    except OSError:
        return
    d = path.parent
    for _ in range(2):     # <id>/ 与可能的 <系列>/
        try:
            if d.is_dir() and not any(d.iterdir()) and d != Path(paths.CARDS):
                parent = d.parent
                d.rmdir()
                d = parent
            else:
                break
        except OSError:
            break


def load_card(card_id: int, archetype: str = "") -> CardSpec | None:
    """读一张卡。旧版 JSON 会**自动迁移并写回新版**；不存在返回 None。"""
    path, found_arch = _find_card_path(card_id, archetype)
    raw = _read_json(path)
    if raw is None:
        return None
    spec = CardSpec.from_dict(raw)
    if not spec.id:
        spec.id = int(card_id)
    if not spec.archetype and found_arch:
        spec.archetype = found_arch
    # 迁移写回：schema 版本落后，或文件里还有 v0.x 的键
    legacy = raw.get("schema_version") != SCHEMA_VERSION or any(
        k in raw for k in ("def", "text", "_lua", "_strings", "type_flags"))
    if legacy:
        content = spec.to_dict()
        if not spec.created:
            spec.created = str(raw.get("created") or _now())
        spec.updated = _now()
        content = spec.to_dict()
        _write_json(path, content)
        _make_snapshot("cards", card_key(spec.id), content, path,
                       note=f"migrate schema v{raw.get('schema_version', 0)} → v{SCHEMA_VERSION}")
    return spec


def list_cards(archetype: str = "") -> list[dict]:
    """列出卡片摘要（``CardSpec.summary()`` + 元信息）。同一卡号只出现一次。

    ``archetype=""`` 列出全部（平铺目录 + 一层系列子目录）。
    """
    specs: dict[int, dict] = {}
    for path, arch in _iter_card_files(archetype):
        raw = _read_json(path)
        if raw is None:
            continue
        try:
            spec = CardSpec.from_dict(raw)
        except Exception:
            continue
        if not spec.id:
            stem = path.parent.name
            if not stem.isdigit():
                continue
            spec.id = int(stem)
        item = spec.summary()
        item["archetype"] = spec.archetype or arch
        item["updated"] = raw.get("updated", "")
        item["schema_version"] = raw.get("schema_version", 0)
        item["path"] = str(path)
        prev = specs.get(spec.id)
        if prev is None or str(item["updated"]) >= str(prev.get("updated", "")):
            specs[spec.id] = item
    return sorted(specs.values(), key=lambda d: int(d["id"]))


def _iter_card_files(archetype: str = ""):
    """产出 ``(spec.json 路径, 所属系列)``。"""
    base = paths.CARDS
    if not base.is_dir():
        return
    if archetype:
        root = base / _safe(archetype)
        if not root.is_dir():
            return
        for sub in sorted(p for p in root.iterdir() if p.is_dir()):
            f = sub / _CARD_FILE
            if f.is_file():
                yield f, archetype
        return
    for sub in sorted(p for p in base.iterdir() if p.is_dir()):
        if sub.name.isdigit():
            f = sub / _CARD_FILE
            if f.is_file():
                yield f, ""
        else:
            for leaf in sorted(p for p in sub.iterdir() if p.is_dir()):
                f = leaf / _CARD_FILE
                if f.is_file():
                    yield f, sub.name


def delete_card(card_id: int, archetype: str = "") -> bool:
    """删除一张卡。删之前先留一条 ``delete`` 快照，所以 ``rollback`` 能救回来。"""
    path, _arch = _find_card_path(card_id, archetype)
    raw = _read_json(path)
    if raw is None:
        return False
    _make_snapshot("cards", card_key(card_id), raw, path,
                   note="delete（删除前留档）", force=True)
    _remove_card_file(path)
    return True


# ══════════════════════════════════════════════════════════════════════
#  系列圣经
# ══════════════════════════════════════════════════════════════════════
def save_archetype(a: Archetype, *, snapshot: bool = True, note: str = "") -> str:
    """保存系列圣经到 ``workspace/archetypes/<名字>/archetype.json``。"""
    if not str(a.name or "").strip():
        raise SpecError("系列名为空，无法保存", hint="先给 Archetype.name 赋值。")
    key = str(a.name)
    target = archetype_spec_path(key)
    old = _read_json(target)
    if not a.created:
        a.created = str((old or {}).get("created") or _now())
    changed = (old is None) or (_content_digest(old) != _content_digest(a.to_dict()))
    if changed or not a.updated:
        a.updated = _now()
    elif old and old.get("updated"):
        a.updated = str(old["updated"])
    content = a.to_dict()
    if changed or old is None:
        _write_json(target, content)
    if snapshot and (changed or old is None):
        _make_snapshot("archetypes", key, content, target, note=note)
    return str(target)


def load_archetype(name: str) -> Archetype | None:
    """读系列圣经；不存在返回 None。旧版自动迁移并写回。"""
    path = archetype_spec_path(name)
    raw = _read_json(path)
    if raw is None:
        return None
    arch = Archetype.from_dict(raw)
    if not arch.name:
        arch.name = str(name)
    legacy = raw.get("schema_version") != SCHEMA_VERSION
    if legacy:
        if not arch.created:
            arch.created = str(raw.get("created") or _now())
        arch.updated = _now()
        content = arch.to_dict()
        _write_json(path, content)
        _make_snapshot("archetypes", str(arch.name), content, path,
                       note=f"migrate schema v{raw.get('schema_version', 0)} → v{SCHEMA_VERSION}")
    return arch


def list_archetypes() -> list[dict]:
    """列出全部系列圣经摘要。"""
    out: list[dict] = []
    base = paths.ARCHETYPES
    if not base.is_dir():
        return out
    for sub in sorted(p for p in base.iterdir() if p.is_dir()):
        raw = _read_json(sub / _ARCH_FILE)
        if raw is None:
            continue
        try:
            arch = Archetype.from_dict(raw)
        except Exception:
            continue
        out.append({
            "name": arch.name or sub.name,
            "setcode": arch.setcode,
            "concept": arch.concept,
            "target_power": arch.target_power,
            "n_roster": len(arch.roster or []),
            "roster_total": arch.roster_total(),
            "n_cards": _count_cards_of(arch.name or sub.name),
            "updated": raw.get("updated", ""),
            "path": str(sub / _ARCH_FILE),
        })
    return out


def _count_cards_of(archetype: str) -> int:
    """系列名下**落盘**的卡数。

    只数含 ``spec.json`` 的子目录，不解析文件内容 —— 列表接口会被界面频繁
    调用，这里解析每张卡纯属浪费（``n_cards`` 只是给人看的提示，不是审计依据）。
    系列改名后旧目录可能残留，所以按**目录**数而不是按 ``spec.archetype`` 数。
    """
    root = paths.CARDS / _safe(archetype)
    if not root.is_dir():
        return 0
    return sum(1 for p in root.iterdir() if p.is_dir() and (p / _CARD_FILE).is_file())


def delete_archetype(name: str) -> bool:
    """删除系列圣经整目录（删除前留档，可 rollback 回文件，不还原其它文件）。"""
    path = archetype_spec_path(name)
    raw = _read_json(path)
    if raw is None:
        return False
    _make_snapshot("archetypes", str(name), raw, path,
                   note="delete（删除前留档）", force=True)
    try:
        shutil.rmtree(path.parent)
    except OSError:
        try:
            path.unlink()
        except OSError:
            return False
    return True


# ══════════════════════════════════════════════════════════════════════
#  卡组
# ══════════════════════════════════════════════════════════════════════
def save_deck(d: DeckSpec, *, snapshot: bool = True, note: str = "") -> str:
    """保存卡组到 ``workspace/decks/<名字>.json``（``DeckSpec`` 没有时间戳字段）。"""
    if not str(d.name or "").strip():
        raise SpecError("卡组名为空，无法保存", hint="先给 DeckSpec.name 赋值。")
    key = str(d.name)
    target = deck_spec_path(key)
    old = _read_json(target)
    content = d.to_dict()
    changed = (old is None) or (_content_digest(old) != _content_digest(content))
    if changed or old is None:
        _write_json(target, content)
    if snapshot and (changed or old is None):
        _make_snapshot("decks", key, content, target, note=note)
    return str(target)


def load_deck(name: str) -> DeckSpec | None:
    """读卡组；不存在返回 None。旧版自动迁移并写回。"""
    path = deck_spec_path(name)
    raw = _read_json(path)
    if raw is None:
        return None
    deck = DeckSpec.from_dict(raw)
    if not deck.name:
        deck.name = str(name)
    if raw.get("schema_version") != SCHEMA_VERSION:
        content = deck.to_dict()
        _write_json(path, content)
        _make_snapshot("decks", str(deck.name), content, path,
                       note=f"migrate schema v{raw.get('schema_version', 0)} → v{SCHEMA_VERSION}")
    return deck


def list_decks() -> list[dict]:
    """列出全部卡组摘要。"""
    out: list[dict] = []
    base = paths.DECKS
    if not base.is_dir():
        return out
    for f in sorted(base.glob("*.json")):
        raw = _read_json(f)
        if raw is None:
            continue
        try:
            deck = DeckSpec.from_dict(raw)
        except Exception:
            continue
        out.append({
            "name": deck.name or f.stem,
            "archetype": deck.archetype,
            "target": deck.target,
            "main": sum(int(e.count or 0) for e in (deck.main or [])),
            "extra": sum(int(e.count or 0) for e in (deck.extra or [])),
            "side": sum(int(e.count or 0) for e in (deck.side or [])),
            "path": str(f),
        })
    return out


def delete_deck(name: str) -> bool:
    """删除卡组（删除前留档）。"""
    path = deck_spec_path(name)
    raw = _read_json(path)
    if raw is None:
        return False
    _make_snapshot("decks", str(name), raw, path,
                   note="delete（删除前留档）", force=True)
    try:
        path.unlink()
    except OSError:
        return False
    return True
