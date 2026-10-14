"""``/api/doctor`` ``/api/state`` ``/api/meta`` ``/api/pool/*`` ``/api/jobs``
``/api/events`` ``/api/files`` —— 环境、元数据、卡池查询与任务流。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ..core import errors, paths
from ..core import enums as E
from ..core import constants as C
from ..core.models import TRIGGERS, EFFECT_LIMITS, ROLES
from . import kernel as K
from .http import Request, Response, safe_join

__all__ = ["register"]


def register(app) -> None:
    # ══════════════════════════════════════════════════════════════
    #  环境与能力
    # ══════════════════════════════════════════════════════════════
    @app.get("/api/doctor")
    def api_doctor(req: Request) -> dict:
        """环境自检（与 ``cardforge doctor`` 同一份判定）。"""
        from ..cli import doctor_report
        return doctor_report()

    @app.get("/api/state")
    def api_state(req: Request) -> dict:
        """界面首屏要的一次性快照 —— 别让人家发六个请求。"""
        from ..cli import __version__
        idx = K.cards_index()
        archs = _list_archetypes()
        decks = _list_decks()
        return {
            "ok": True,
            "version": __version__,
            "started_at": app.started_at,
            "uptime_s": round(time.time() - app.started_at, 1),
            "requests": app.requests,
            "server_errors": app.errors_seen,
            "paths": paths.describe(),
            "levels": _levels(),
            "counts": {"cards": len(idx), "archetypes": len(archs),
                       "decks": len(decks)},
            "pool": K.official_status(),
            "assistant": _assistant_status(),
            "recent_cards": idx[:12],
            "archetypes": archs[:40],
            "decks": decks[:40],
        }

    @app.get("/api/meta")
    def api_meta(req: Request) -> dict:
        """所有下拉框的数据源。一次取全，前端缓存。"""
        return {
            "ok": True,
            "frames": {k: _drop(v) for k, v in E.FRAMES.items()},
            "rarities": {k: _drop(v) for k, v in E.RARITIES.items()},
            "langs": {k: _drop(v) for k, v in E.LANGS.items()},
            "spell_kinds": E.SPELL_KINDS,
            "trap_kinds": E.TRAP_KINDS,
            "monster_tags": E.MONSTER_TAGS,
            "fullart_modes": {k: _drop(v) for k, v in E.FULL_ART_MODES.items()},
            "attributes": list(C.ATTRIBUTE_MAP),
            "races": list(C.RACE_MAP),
            "link_markers": list(C.LINK_MARKER_MAP),
            "triggers": TRIGGERS,
            "effect_limits": EFFECT_LIMITS,
            "roles": ROLES,
            "default_lang": E.DEFAULT_LANG,
            "effect_kinds": _effect_kinds(),
            "gates": _gate_labels(),
        }

    # ══════════════════════════════════════════════════════════════
    #  官方卡池
    # ══════════════════════════════════════════════════════════════
    @app.get("/api/pool/search")
    def api_pool_search(req: Request) -> dict:
        q = req.str_arg("q")
        if not q:
            raise errors.SpecError("搜索词不能为空", "输入卡名、字段名或效果关键词")
        pool = K.official()
        if pool is None:
            return {"ok": False, "results": [], **K.official_status(),
                    "hint": "把官方 .cdb 放进 vendor/data/ 就能查官方卡池"}
        limit = max(1, min(int(req.int_arg("limit", 20) or 20), 100))
        try:
            return {"ok": True, "q": q, "results": pool.search(q, limit=limit)}
        except Exception as e:
            return {"ok": False, "results": [],
                    "error": f"查询失败：{type(e).__name__}: {e}"}

    @app.get("/api/pool/card")
    def api_pool_card(req: Request) -> dict:
        cid = req.int_arg("id")
        pool = K.official()
        if pool is None:
            raise errors.EnvError("官方卡池不可用",
                                  "把官方 .cdb 放进 vendor/data/")
        return {"ok": True, "id": cid, "text": pool.text_of(cid)}

    @app.get("/api/pool/dupcheck")
    def api_pool_dupcheck(req: Request) -> dict:
        name = req.str_arg("name")
        if not name:
            raise errors.SpecError("要查重的字段名不能为空", "填本家字段，如「星奏」")
        return K.soft_call("cardforge.content.design", "dupcheck_archetype",
                           name, official=K.official(), label="字段名查重")

    @app.get("/api/pool/setcode")
    def api_pool_setcode(req: Request) -> dict:
        out = K.soft_call("cardforge.content.design", "suggest_setcode",
                          official=K.official(), label="setcode 建议")
        if out.get("ok"):
            out["value"] = {"suggested": out["value"]}
        return out

    # ══════════════════════════════════════════════════════════════
    #  任务与 SSE
    # ══════════════════════════════════════════════════════════════
    @app.get("/api/jobs")
    def api_jobs(req: Request) -> dict:
        from ..pipeline import job
        return {"ok": True, "jobs": job.manager().list(
            kind=req.str_arg("kind"), status=req.str_arg("status"),
            limit=req.int_arg("limit", 50))}

    @app.get("/api/jobs/<jid>")
    def api_job(req: Request) -> dict:
        from ..pipeline import job
        j = job.manager().get(req.params["jid"])
        if j is None:
            raise errors.CardForgeError(f"没有任务 {req.params['jid']}",
                                        "任务可能已被回收；产物仍在磁盘上")
        return {"ok": True, "job": j.to_dict()}

    @app.post("/api/jobs/<jid>/cancel")
    def api_job_cancel(req: Request) -> dict:
        from ..pipeline import job
        ok = job.manager().cancel(req.params["jid"])
        return {"ok": ok,
                "note": "" if ok else "任务已结束或不存在，无需取消",
                "hint": "" if ok else "出图这类长任务只能等它跑完；"
                                      "要立刻停下来可以点界面上的「打断 ComfyUI」"}

    @app.get("/api/events")
    def api_events(req: Request):
        """SSE 事件流。``?job=j0001&since=12``。"""
        from ..pipeline import job
        jid = req.str_arg("job")
        if not jid:
            return Response.json({"ok": False, "error": "缺少 job 参数",
                                  "hint": "/api/events?job=j0001"}, status=400)
        since = req.int_arg("since", 0)
        return Response.sse(job.manager().events(jid, since=since))

    # ══════════════════════════════════════════════════════════════
    #  文件（预览图 / 产物下载）
    # ══════════════════════════════════════════════════════════════
    @app.get("/api/files/<rel:path>")
    def api_files(req: Request) -> Response:
        """白名单根目录下的文件读取。

        只允许 ``workspace/`` 与 ``data/`` —— 这个端口绑在本机，但浏览器里任何
        页面都可能有脚本想读 ``~/.ssh``，所以必须锁死。

        ⚠ 路径基准要统一：``paths.rel()`` 给的是**相对项目根**的路径
        （``workspace/out/x.ypk``），而文件接口原来按 **WORKSPACE** 解析，
        于是所有下载链接都 404。这里两种写法都认。
        """
        rel = req.params.get("rel", "")
        roots = [paths.WORKSPACE, paths.DATA, paths.OUT]
        p = safe_join(roots[0], rel, extra_roots=roots[1:])
        if not p.exists():
            alt = safe_join(paths.ROOT, rel, extra_roots=[paths.WORKSPACE])
            inside = False
            for allow in (paths.WORKSPACE, paths.DATA):
                try:
                    alt.resolve().relative_to(allow.resolve())
                    inside = True
                except Exception:
                    continue
            if inside and alt.exists():
                p = alt
        if not p.exists():
            raise FileNotFoundError(paths.rel(p))
        from .http import content_type_of
        data = p.read_bytes()
        inline = req.bool_arg("inline", True)
        disp = "inline" if inline else f"attachment; filename*=UTF-8''{Path(p.name).name}"
        return Response(data, content_type=content_type_of(p), headers={
            "Content-Disposition": disp,
            "Cache-Control": "max-age=20",
        })


# ══════════════════════════════════════════════════════════════════════
#  内部小助手
# ══════════════════════════════════════════════════════════════════════
_GATE_LABELS = {
    "G1": ("平衡审计", "这张卡超不超模、能不能进构筑"),
    "G2": ("脚本静态检查", "Lua 语法/API/编码/编号同步"),
    "G3": ("实跑验证", "真开一局引擎跑，跑不通就是没跑"),
    "G4": ("系列一致性", "整系列的字段、方言、强度曲线"),
    "G5": ("导出自检", "包结构、cdb、卡图尺寸、脚本齐不齐"),
}


def _gate_labels() -> dict:
    return {k: {"zh": v[0], "brief": v[1]} for k, v in _GATE_LABELS.items()}


def _drop(obj: Any) -> dict:
    """把 dataclass 定义压成下拉框需要的 ``{key, zh, en, ...}``。"""
    d = getattr(obj, "__dict__", None)
    if d is None and isinstance(obj, dict):
        d = obj
    d = dict(d or {})
    out = {}
    for k, v in d.items():
        if k.startswith("_"):
            continue
        if isinstance(v, (str, int, float, bool)) or v is None:
            out[k] = v
        elif isinstance(v, dict) and all(isinstance(x, (str, int, float)) for x in v.values()):
            out[k] = v
        elif isinstance(v, (list, tuple)) and all(isinstance(x, (str, int, float)) for x in v):
            out[k] = list(v)
    out.setdefault("key", d.get("key") or d.get("slug") or "")
    out.setdefault("zh", d.get("zh_cn") or d.get("label") or out["key"])
    return out


def _effect_kinds() -> list[dict]:
    """效果种类表。``content/effects.py`` 还没实现时，退回 PSCT 的句式模板键。"""
    effects = K.try_import("cardforge.content.effects")
    fn = getattr(effects, "describe_all", None) if effects else None
    if callable(fn):
        try:
            items = fn()
            if items:
                return list(items)
        except Exception:
            pass
    # 降级：至少让界面能把 kind 选出来，卡文侧仍能工作
    try:
        from ..content.psct import rules
        return [{"key": k, "zh": (v.get("zh_cn") or k).split("{")[0].strip(),
                 "en": (v.get("en") or k).split("{")[0].strip(),
                 "triggers": ["IGNITION"], "params": {},
                 "target_required": False, "cost_allowed": True,
                 "available": False}
                for k, v in rules.EFFECT_TEMPLATES.items()]
    except Exception:
        return []


def _levels() -> dict:
    out: dict[str, Any] = {"L0-data": True}
    art = K.try_import("cardforge.art.client")
    if art is not None:
        try:
            out["L2-art"] = bool(art.ComfyClient().alive())
        except Exception:
            out["L2-art"] = False
    comp = K.try_import("cardforge.render.compositor")
    if comp:
        try:
            caps = comp.capabilities()
            out["L1-render"] = bool(caps.get("L1_render"))
            out["L1_detail"] = caps
        except Exception:
            out["L1-render"] = False
    eng = K.try_import("cardforge.duel.engine")
    if eng:
        try:
            st = eng.detect(try_load=True)
            out["L3-duel"] = getattr(st, "level", "static")
            out["L3_reason"] = getattr(st, "reason", "")
            out["L3_hint"] = getattr(st, "hint", "")
        except Exception:
            out["L3-duel"] = "static"
    try:
        from ..pipeline import gates
        out["gates"] = gates.capabilities()
    except Exception:
        pass
    return out


def _assistant_status() -> dict:
    a = K.try_import("cardforge.assistant")
    if a is None:
        return {"available": False, "name": "星奏·艾莉娅",
                "reason": "assistant 模块未安装",
                "hint": "命令行 ask 子命令同样不可用；不影响造卡主流程"}
    try:
        from ..assistant import providers
        p = providers.detect_provider()
        return {"available": True, "name": getattr(a, "ASSISTANT_NAME", "艾莉娅"),
                "provider": getattr(p, "name", "none")}
    except Exception as e:
        return {"available": True, "provider": "unknown",
                "reason": f"provider 探测失败：{type(e).__name__}: {e}"}


def _list_archetypes() -> list[dict]:
    try:
        from ..pool import repo
        return repo.list_archetypes()
    except Exception:
        return []


def _list_decks() -> list[dict]:
    try:
        from ..pool import repo
        return repo.list_decks()
    except Exception:
        return []
