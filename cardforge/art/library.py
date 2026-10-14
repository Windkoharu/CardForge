"""卡图资产库 —— 卡图的版本控制。

目录约定
--------
::

    workspace/pics/art/<archetype>/<card_id>/          # 有系列时
    workspace/pics/art/<card_id>/                      # 无系列时
        v1.png        # 第一版
        v1.meta.json  # 这一版的提示词 / 模型 / seed / 参数 / 工作流指纹 / 耗时
        v2.png
        v2.meta.json
        current.json  # {"version": 2, "file": "...", "updated": "..."}

* **只增不改**：``save`` 永远写新版本号，不覆盖历史。
* ``rollback`` 是**写指针**（改 ``current.json``），不删文件、不改历史。
* ``compare`` 用 Pillow 做像素差（``ImageChops.difference``）并生成并排图。

路径一律走 :mod:`cardforge.core.paths`，禁止硬编码绝对路径。
"""
from __future__ import annotations

import json
import math
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from ..core.errors import AssetMissing, EnvError
from ..core import paths as P

__all__ = [
    "save", "versions", "current", "rollback", "compare", "list_all",
    "dir_for", "meta_path", "image_path", "set_current", "prune",
    "layers_of", "load_for_render",
    "VERSION_RE", "library_root",
]

VERSION_RE = re.compile(r"^v(\d+)\.(png|jpg|jpeg|webp)$", re.IGNORECASE)
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")
CURRENT_FILE = "current.json"


# ══════════════════════════════════════════════════════════════════════
#  路径
# ══════════════════════════════════════════════════════════════════════
def library_root() -> Path:
    """资产库根目录 ``workspace/pics/art``。"""
    return Path(P.PICS) / "art"


def dir_for(card_id: int, archetype: str = "") -> Path:
    """某个 card_id 的资产目录（有系列时落在系列子目录下）。

    复用 :func:`cardforge.core.paths.art_dir` —— 保证与渲染模块看到的路径一致。
    """
    if archetype:
        return Path(P.art_dir(int(card_id), archetype))
    return Path(P.art_dir(int(card_id)))


def image_path(card_id: int, version: int, archetype: str = "",
               ext: str = ".png") -> Path:
    """``v{n}.png`` 的完整路径。"""
    return dir_for(card_id, archetype) / f"v{int(version)}{ext}"


def meta_path(card_id: int, version: int, archetype: str = "") -> Path:
    """``v{n}.meta.json`` 的完整路径。"""
    return dir_for(card_id, archetype) / f"v{int(version)}.meta.json"


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _write_json(path: Path, obj: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path.resolve())


def _read_json(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except Exception:
        return default


# ══════════════════════════════════════════════════════════════════════
#  写
# ══════════════════════════════════════════════════════════════════════
def _next_version(d: Path) -> int:
    mx = 0
    if d.exists():
        for p in d.iterdir():
            m = VERSION_RE.match(p.name)
            if m:
                mx = max(mx, int(m.group(1)))
    return mx + 1


def save(card_id: int, img_or_bytes, meta: dict, archetype: str = "",
         layers: dict | None = None) -> dict:
    """存一版卡图，写 ``v{n}.png`` + ``v{n}.meta.json``，并把 ``current`` 指向它。

    :param card_id: 卡 id（``CardSpec.id``）。
    :param img_or_bytes: ``PIL.Image``、``bytes``（PNG/JPEG）或已有文件路径。
    :param meta: 提示词 / 模型 / seed / 参数 / 工作流指纹 / 耗时 等元数据。
    :param archetype: 系列名（非空时归入 ``art/<archetype>/<card_id>/``）。
    :param layers: 分层卡图的各层文件 ``{"background": 路径, "subject": 路径}``；
        会一起落成 ``v{n}_bg.png`` / ``v{n}_subject.png`` 并记进 meta。
        ``v{n}.png`` 始终是**压平后的预览**，老链路（导出/卡面）照旧能读。
    :return: ``{"ok","version","image","meta","dir","current","layers"}``
    """
    d = dir_for(card_id, archetype)
    d.mkdir(parents=True, exist_ok=True)
    version = _next_version(d)
    png = d / f"v{version}.png"

    if isinstance(img_or_bytes, (bytes, bytearray)):
        png.write_bytes(bytes(img_or_bytes))
    elif isinstance(img_or_bytes, (str, Path)):
        src = Path(img_or_bytes)
        if not src.exists():
            raise AssetMissing(f"要入库的图片不存在：{src}",
                               "检查上游出图是否成功写盘。")
        if src.suffix.lower() == ".png":
            shutil.copyfile(src, png)
        else:
            _convert_to_png(src, png)
    else:
        try:
            img_or_bytes.save(png, "PNG")          # type: ignore[union-attr]
        except AttributeError as exc:
            raise EnvError("img_or_bytes 既不是 bytes / 路径，也不是 PIL.Image",
                           "传 PIL.Image / bytes / 文件路径三者之一。") from exc

    # 分层：把各层按 v{n}_<role>.png 落到同一目录（VERSION_RE 只认 v{n}.png，
    # 所以这些文件不会被误算成"新版本"）
    layer_files: dict[str, str] = {}
    for role, src in (layers or {}).items():
        if not src:
            continue
        p = Path(str(src))
        if not p.exists():
            continue
        dst = d / f"v{version}_{str(role).strip().lower()}{'.png' if p.suffix.lower() == '.png' else p.suffix.lower()}"
        if p.suffix.lower() == ".png":
            shutil.copyfile(p, dst)
        else:
            _convert_to_png(p, dst)
        layer_files[str(role)] = dst.name

    info = dict(meta or {})
    info.setdefault("card_id", int(card_id))
    if archetype:
        info.setdefault("archetype", str(archetype))
    info["version"] = version
    info["image"] = png.name
    info["bytes"] = png.stat().st_size
    info["sha256"] = _sha256(png)
    if layer_files:
        info["layers"] = layer_files
    info.setdefault("saved", _now())
    mp = d / f"v{version}.meta.json"
    _write_json(mp, info)
    cur = set_current(card_id, version, archetype)
    return {"ok": True, "version": version, "image": str(png.resolve()),
            "meta": str(mp.resolve()), "dir": str(d.resolve()), "current": cur,
            "layers": {k: str((d / v).resolve()) for k, v in layer_files.items()}}


def layers_of(card_id: int, version: int | None = None,
              archetype: str = "") -> dict[str, str]:
    """取某一版（默认当前版）的分层文件绝对路径；没有分层则返回 ``{}``。"""
    if version is None:
        cur = current(card_id, archetype) or {}
        version = cur.get("version")
    if not version:
        return {}
    info = _read_json(meta_path(card_id, int(version), archetype)) or {}
    out = {}
    for role, name in (info.get("layers") or {}).items():
        p = dir_for(card_id, archetype) / str(name)
        if p.exists():
            out[str(role)] = str(p.resolve())
    return out


def load_for_render(card_id: int, archetype: str = "",
                    version: int | None = None) -> dict:
    """给渲染器用：一次取回压平件与分层件（PIL 图像，缺哪个就少哪个键）。

    ``{"flat": Image, "background": Image, "subject": Image}`` —— 主体层保留 alpha。
    读不到的键直接不出现，调用方按「有没有」决定走哪条合成路径。
    """
    from PIL import Image

    out: dict = {}
    d = dir_for(card_id, archetype)
    if version is None:
        cur = current(card_id, archetype) or {}
        version = cur.get("version")
    if not version:
        return out

    def _open(p):
        try:
            im = Image.open(str(p))
            im.load()
            return im
        except Exception:
            return None

    flat = d / f"v{int(version)}.png"
    if flat.exists():
        im = _open(flat)
        if im is not None:
            out["flat"] = im
    for role, name in (layers_of(card_id, version, archetype) or {}).items():
        im = _open(name)
        if im is not None:
            out[role] = im
    return out


def _convert_to_png(src: Path, dst: Path) -> None:
    from PIL import Image
    with Image.open(src) as im:
        im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB").save(dst, "PNG")


def _sha256(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ══════════════════════════════════════════════════════════════════════
#  读
# ══════════════════════════════════════════════════════════════════════
def versions(card_id: int, archetype: str = "") -> list[dict]:
    """列出某个 card_id 的全部版本（按版本号升序）。

    每项：``{"version","image","meta","bytes","mtime","is_current","meta_data"}``
    """
    d = dir_for(card_id, archetype)
    if not d.exists():
        return []
    cur = (current(card_id, archetype) or {}).get("version")
    out: list[dict] = []
    for p in sorted(d.iterdir()):
        m = VERSION_RE.match(p.name)
        if not m:
            continue
        v = int(m.group(1))
        mp = d / f"v{v}.meta.json"
        st = p.stat()
        out.append({
            "version": v,
            "image": str(p.resolve()),
            "meta": str(mp.resolve()) if mp.exists() else "",
            "bytes": st.st_size,
            "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
            "is_current": (v == cur),
            "meta_data": _read_json(mp, {}) or {},
        })
    out.sort(key=lambda x: x["version"])
    return out


def current(card_id: int, archetype: str = "") -> dict | None:
    """当前指针（``current.json`` 的内容）；没有返回 ``None``。

    若 ``current.json`` 缺失但目录里有版本，**自动回落到最大版本号**。
    """
    d = dir_for(card_id, archetype)
    cur = _read_json(d / CURRENT_FILE, None)
    if isinstance(cur, dict) and cur.get("version"):
        return cur
    vs = versions(card_id, archetype)
    if not vs:
        return None
    last = vs[-1]
    return {"version": last["version"], "file": Path(last["image"]).name,
            "updated": last["mtime"], "fallback": True}


def set_current(card_id: int, version: int, archetype: str = "") -> dict:
    """把 ``current`` 指针指向某个版本（不校验文件是否存在，rollback 会校验）。"""
    d = dir_for(card_id, archetype)
    d.mkdir(parents=True, exist_ok=True)
    png = _find_image(d, int(version))
    obj = {"version": int(version), "file": png.name if png else "",
           "updated": _now()}
    _write_json(d / CURRENT_FILE, obj)
    return obj


def _find_image(d: Path, version: int) -> Path | None:
    for ext in IMAGE_EXTS:
        p = d / f"v{version}{ext}"
        if p.exists():
            return p
    return None


def rollback(card_id: int, version: int, archetype: str = "") -> dict:
    """把当前指针退回某个历史版本（**不删文件、不改历史**）。

    :raises AssetMissing: 该版本不存在。
    """
    d = dir_for(card_id, archetype)
    png = _find_image(d, int(version))
    if png is None:
        have = [v["version"] for v in versions(card_id, archetype)]
        raise AssetMissing(
            f"卡 {card_id} 没有 v{version}（现有版本：{have or '无'}）",
            "先 versions(card_id, archetype) 看有哪些版本，再 rollback。")
    cur = set_current(card_id, int(version), archetype)
    return {"ok": True, "card_id": int(card_id), "version": int(version),
            "image": str(png.resolve()), "current": cur}


def list_all(archetype: str = "") -> list[dict]:
    """列出资产库里的全部卡图（``archetype`` 为空时递归全部系列）。

    每项：``{"card_id","archetype","version","versions","image","current","meta"}``
    """
    root = library_root()
    out: list[dict] = []
    if not root.exists():
        return out
    if archetype:
        bases = [(root / _safe(archetype), str(archetype))]
    else:
        bases = [(root, "")]
    for base, arch_name in bases:
        if not base.exists():
            continue
        for card_dir in sorted(base.iterdir()):
            if not card_dir.is_dir():
                continue
            if not card_dir.name.isdigit():
                # 无系列模式下的系列子目录 → 递归进去，带上系列名
                for sub in sorted(card_dir.iterdir()):
                    if sub.is_dir() and sub.name.isdigit():
                        out.append(_card_row(sub, card_dir.name))
                continue
            out.append(_card_row(card_dir, arch_name))
    return out


def _card_row(card_dir: Path, arch: str) -> dict:
    cid = int(card_dir.name)
    vs = versions(cid, arch)
    cur = current(cid, arch) or {}
    return {
        "card_id": cid,
        "archetype": arch,
        "versions": len(vs),
        "version": cur.get("version"),
        "current": cur.get("file") or "",
        "image": vs[-1]["image"] if vs else "",
        "bytes": sum(v["bytes"] for v in vs),
        "dir": str(card_dir.resolve()),
        "meta": (vs[-1]["meta_data"] if vs else {}),
    }


def _safe(name: str) -> str:
    from ..core.paths import _safe_name          # noqa: PLC2701 - 复用同一套清洗规则
    return _safe_name(name)


# ══════════════════════════════════════════════════════════════════════
#  比较
# ══════════════════════════════════════════════════════════════════════
def compare(card_id: int, a: int, b: int, archetype: str = "") -> dict:
    """比较两个版本：像素差统计 + 并排对比图。

    :return: ``{"ok","a","b","stats":{...},"sbs": "<并排图路径>"}``

    ``stats`` 里的关键字段：

    * ``mean_abs`` / ``max_abs`` —— 0–255 尺度的平均 / 最大绝对差；
    * ``pct_changed`` —— 差异超过 8/255 的像素占比（%）；
    * ``identical`` —— ``mean_abs < 0.5`` 时判为「实质上同一张图」。
    """
    from PIL import Image, ImageChops

    d = dir_for(card_id, archetype)
    pa, pb = _find_image(d, int(a)), _find_image(d, int(b))
    if pa is None or pb is None:
        raise AssetMissing(
            f"卡 {card_id} 缺版本（a=v{a}→{pa}，b=v{b}→{pb}）",
            "用 versions() 看现有版本；compare 需要两个都已存在的版本。")
    out_dir = d / "_compare"
    out_dir.mkdir(parents=True, exist_ok=True)
    with Image.open(pa) as ia, Image.open(pb) as ib:
        A = ia.convert("RGBA") if ia.mode in ("RGBA", "LA", "P") else ia.convert("RGB")
        B = ib.convert("RGBA") if ib.mode in ("RGBA", "LA", "P") else ib.convert("RGB")
        same_size = (A.size == B.size)
        if not same_size:
            B = B.resize(A.size, Image.LANCZOS)
        ca = A.convert("RGB")
        cb = B.convert("RGB")
        diff = ImageChops.difference(ca, cb)
        hist = diff.convert("L").histogram()
        total = max(1, sum(hist))
        acc = sum(i * n for i, n in enumerate(hist))
        mean_abs = acc / total
        max_abs = max((i for i, n in enumerate(hist) if n), default=0)
        changed = sum(n for i, n in enumerate(hist) if i > 8)
        pct = 100.0 * changed / total
        # 并排图（左 A 右 B，中间 8px 分隔）
        gap = 8
        sbs = Image.new("RGB", (ca.width * 2 + gap, ca.height), (24, 24, 28))
        sbs.paste(ca, (0, 0))
        sbs.paste(cb, (ca.width + gap, 0))
        sbs_path = out_dir / f"v{a}_vs_v{b}.png"
        sbs.save(sbs_path, "PNG")
        # 差异热力图（放大后更直观）
        heat = diff.convert("L").point(lambda v: min(255, v * 4))
        heat_path = out_dir / f"v{a}_vs_v{b}_diff.png"
        heat.convert("RGB").save(heat_path, "PNG")

    return {
        "ok": True,
        "card_id": int(card_id),
        "a": {"version": int(a), "image": str(pa.resolve())},
        "b": {"version": int(b), "image": str(pb.resolve())},
        "size": list(A.size),
        "same_size": same_size,
        "stats": {
            "mean_abs": round(mean_abs, 4),
            "max_abs": int(max_abs),
            "pct_changed": round(pct, 3),
            "identical": bool(mean_abs < 0.5),
            "rmse": round(math.sqrt(sum((i ** 2) * n for i, n in enumerate(hist)) / total), 4),
        },
        "sbs": str(sbs_path.resolve()),
        "diff": str(heat_path.resolve()),
    }


def prune(card_id: int, keep: int = 3, archetype: str = "") -> dict:
    """只保留最近 ``keep`` 个版本（含当前版本），其余删除。**破坏性操作。**"""
    vs = versions(card_id, archetype)
    keep = max(1, int(keep))
    cur_v = (current(card_id, archetype) or {}).get("version")
    victims = [v for v in vs[:-keep]] if len(vs) > keep else []
    if cur_v and all(v["version"] != cur_v for v in vs[-keep:]):
        # 当前版本不在保留窗口里 → 少删一个，保证 current 还在
        victims = victims[:-1] if victims else victims
    removed: list[int] = []
    for v in victims:
        for p in (Path(v["image"]), Path(v["meta"]) if v["meta"] else None):
            if p and p.exists():
                p.unlink()
        removed.append(v["version"])
    return {"ok": True, "removed": removed, "kept": [v["version"] for v in vs[-keep:]]}
