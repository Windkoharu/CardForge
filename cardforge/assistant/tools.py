"""艾莉娅的工具表 —— 每个工具都只是**确定性内核的转调**。

第一原则
--------
**这里没有任何"判定"逻辑。** 平衡不合格、脚本有问题、字段撞名 —— 这些结论全部由
``pipeline.gates`` / ``content.*`` / ``pool.*`` / ``render.*`` / ``duel.*`` / ``export.*``
给出；本文件只做三件事：参数归一 → 调用 → 把结果整包装成 dict。

依赖策略
--------
* 与 :func:`cardforge.pipeline.gates._try_import` 同款的**软导入**：
  ``content.effects`` / ``content.lua.emit`` / ``duel.bot`` / ``duel.scenario``
  由其它并行开发的小组实现，模块不在时返回带中文说明的**降级 dict**，
  绝不抛异常、绝不因为一个子模块缺失让整个 ``assistant`` 不可用。
* 每个 handler 外面都套 ``try/except Exception``，异常一律折成
  ``{"ok": False, "error": "..."}`` —— 契约未定的东西按 ``docs/02`` 的签名调用，
  调用结果不认识就原样塞进 ``raw``。

约定：``call(name, args, ctx)`` 永远返回 dict，键固定包含
``{"tool", "ok", ...数据或 "degraded"/"error"}``。
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any, Callable, Optional

from ..core import paths
from ..core.models import ArtRequest, CardSpec
from . import knowledge

__all__ = ["TOOLS", "call", "tool_schemas", "tool_names", "tool_doc"]


# ══════════════════════════════════════════════════════════════════════
#  通用工具（与 gates 同款）
# ══════════════════════════════════════════════════════════════════════
def _try_import(modpath: str, attr: str = "") -> Any:
    """惰性导入可选模块；缺失返回 ``None``（**降级信号，不是错误**）。"""
    try:
        m = importlib.import_module(modpath, package="cardforge")
        return getattr(m, attr) if attr else m
    except Exception:
        return None


def _kernel(modpath: str, name: str) -> Optional[Callable]:
    """取内核函数；模块或函数不存在返回 None。"""
    mod = _try_import(modpath)
    fn = getattr(mod, name, None) if mod is not None else None
    return fn if callable(fn) else None


def _official_pool() -> Any:
    """官方卡池（只读）。不可用时返回 None，由调用方给出降级说明。"""
    cls = _kernel(".pool.official", "OfficialPool")
    if cls is None:
        return None
    base = Path(paths.OFFICIAL_CDB)
    for name in ("cards_zh.cdb", "cards.cdb"):
        p = base / name
        try:
            if p.is_file():
                return cls(str(p))
        except Exception:
            continue
    return None


_MISSING_POOL = {"ok": False, "degraded": "官方卡池不可用（vendor/data/*.cdb 缺失），"
                                          "这项检查没法给出确定性结论。"}


def _as_spec(obj: Any) -> Optional[CardSpec]:
    """把 ctx / args 里的东西尽量变成 CardSpec。"""
    if isinstance(obj, CardSpec):
        return obj
    if isinstance(obj, dict):
        try:
            return CardSpec.from_dict(obj)
        except Exception:
            return None
    return None


def _resolve_spec(args: dict, ctx: dict) -> tuple[Optional[CardSpec], str]:
    """定位「哪张卡」：ctx.spec → ctx.card_id → args.card_id → args.name 模糊查表。"""
    spec = _as_spec(ctx.get("spec")) or _as_spec(args.get("spec"))
    if spec is not None:
        return spec, ""

    repo = _try_import(".pool.repo")
    cid = args.get("card_id") or args.get("id") or ctx.get("card_id") or 0
    try:
        cid = int(cid or 0)
    except (TypeError, ValueError):
        cid = 0
    arch = str(args.get("archetype") or ctx.get("archetype") or "")

    if cid:
        if repo is not None and callable(getattr(repo, "load_card", None)):
            try:
                got = repo.load_card(cid, arch)
            except Exception:
                got = None
            s = _as_spec(got)
            if s is not None:
                return s, ""
        p = paths.CARDS / str(cid) / "spec.json"
        alt = paths.CARDS / f"{cid}.json"
        for cand in (p, alt):
            try:
                if cand.is_file():
                    s = CardSpec.from_dict(json.loads(cand.read_text(encoding="utf-8-sig")))
                    return s, ""
            except Exception:
                continue
        return None, f"找不到卡号 {cid} 的工程文件（workspace/cards 下没有它的 spec.json）。"

    name = str(args.get("name") or ctx.get("card_name") or "").strip()
    if not name:
        return None, "没有指定卡片：请给我卡号（card_id）或卡名（name），或先在 UI 里选中一张卡。"
    if repo is None:
        return None, "卡库模块（pool/repo.py）不可用，无法按卡名查卡。"
    try:
        for item in (repo.list_cards() or []):
            if not isinstance(item, dict):
                continue
            if name in {str(item.get("name") or ""), str(item.get("display_name") or "")}:
                got = repo.load_card(int(item.get("id") or 0), str(item.get("archetype") or ""))
                s = _as_spec(got)
                if s is not None:
                    return s, ""
        for item in (repo.list_cards() or []):
            if isinstance(item, dict) and name and name in str(item.get("name") or ""):
                got = repo.load_card(int(item.get("id") or 0), str(item.get("archetype") or ""))
                s = _as_spec(got)
                if s is not None:
                    return s, ""
    except Exception as e:
        return None, f"按卡名查卡失败：{e}"
    return None, f"工作区里没有名为「{name}」的卡。"


def _issues(issues: Any) -> list[dict]:
    """把 Issue 列表整成纯 dict（工具输出要能直接进 JSON/提示词）。"""
    out: list[dict] = []
    for i in issues or []:
        if hasattr(i, "to_dict"):
            try:
                out.append(i.to_dict())
                continue
            except Exception:
                pass
        if isinstance(i, dict):
            out.append(dict(i))
        else:
            out.append({"message": str(i)})
    return out


def _report_dict(rep: Any) -> dict:
    """GateReport → dict（含 status / degraded 原始字段，不做任何美化）。"""
    if rep is None:
        return {"ok": False, "error": "内核没有返回报告。"}
    if hasattr(rep, "to_dict"):
        try:
            d = rep.to_dict()
            d["ok"] = True
            d["status"] = getattr(rep, "status", d.get("status", ""))
            d["has_error"] = bool(getattr(rep, "has_error", False))
            return d
        except Exception:
            pass
    if isinstance(rep, dict):
        d = dict(rep)
        d.setdefault("ok", True)
        return d
    return {"ok": True, "raw": str(rep)}


# ══════════════════════════════════════════════════════════════════════
#  handler 实现（全部转调内核）
# ══════════════════════════════════════════════════════════════════════
def _t_card_get(args: dict, ctx: dict) -> dict:
    spec, err = _resolve_spec(args, ctx)
    if spec is None:
        return {"tool": "card_get", "ok": False, "error": err}
    return {"tool": "card_get", "ok": True, "spec": spec.to_dict(),
            "summary": spec.summary(), "labels": spec.labels()}


def _t_card_list(args: dict, ctx: dict) -> dict:
    repo = _try_import(".pool.repo")
    if repo is None or not callable(getattr(repo, "list_cards", None)):
        return {"tool": "card_list", "ok": False, "degraded": "卡库模块（pool/repo.py）不可用。"}
    try:
        items = repo.list_cards(str(args.get("archetype") or "")) or []
    except Exception as e:
        return {"tool": "card_list", "ok": False, "error": f"列卡失败：{e}"}
    return {"tool": "card_list", "ok": True, "count": len(items), "cards": items[:200]}


_PATCHABLE = ("name", "frame", "attribute", "race", "level", "atk", "dfd",
              "pendulum_scale", "spell_kind", "trap_kind", "archetype", "setcode",
              "flavor", "source_note")


def _t_card_patch(args: dict, ctx: dict) -> dict:
    spec, err = _resolve_spec(args, ctx)
    if spec is None:
        return {"tool": "card_patch", "ok": False, "error": err}
    patch = args.get("patch") if isinstance(args.get("patch"), dict) else {
        k: v for k, v in args.items() if k in _PATCHABLE}
    if not patch:
        return {"tool": "card_patch", "ok": False,
                "degraded": "没有要改的字段。可改：" + "、".join(_PATCHABLE)}
    applied: dict[str, Any] = {}
    rejected: dict[str, str] = {}
    for k, v in patch.items():
        if k not in _PATCHABLE:
            rejected[k] = "不在可改字段白名单里"
            continue
        try:
            setattr(spec, k, v)
            applied[k] = v
        except Exception as e:
            rejected[k] = str(e)
    if not applied:
        return {"tool": "card_patch", "ok": False, "rejected": rejected,
                "error": "没有任何字段被修改。"}
    spec.dirty = sorted(set(list(spec.dirty or []) + ["text", "lua", "pic"]))
    repo = _try_import(".pool.repo")
    saved = ""
    if repo is not None and callable(getattr(repo, "save_card", None)):
        try:
            saved = str(repo.save_card(spec, note="assistant.card_patch"))
        except Exception as e:
            return {"tool": "card_patch", "ok": False, "applied": applied,
                    "rejected": rejected, "error": f"落盘失败：{e}"}
    else:
        return {"tool": "card_patch", "ok": False, "applied": applied,
                "rejected": rejected, "degraded": "卡库模块不可用，只改了内存对象，没有落盘。"}
    return {"tool": "card_patch", "ok": True, "applied": applied, "rejected": rejected,
            "path": saved, "summary": spec.summary()}


def _t_card_audit(args: dict, ctx: dict) -> dict:
    spec, err = _resolve_spec(args, ctx)
    if spec is None:
        return {"tool": "card_audit", "ok": False, "error": err}
    gates = _try_import(".pipeline.gates")
    fn = getattr(gates, "g1_balance", None) if gates else None
    if not callable(fn):
        return {"tool": "card_audit", "ok": False,
                "degraded": "质量门模块（pipeline/gates.py）不可用，无法审计。"}
    try:
        rep = fn(spec, check_pool=bool(args.get("check_pool", True)))
    except Exception as e:
        return {"tool": "card_audit", "ok": False, "error": f"G1 执行异常：{e}"}
    d = _report_dict(rep)
    d["tool"] = "card_audit"
    d["card"] = {"id": spec.id, "name": spec.display_name}
    return d


def _t_gate_run(args: dict, ctx: dict) -> dict:
    gates = _try_import(".pipeline.gates")
    if gates is None:
        return {"tool": "gate_run", "ok": False, "degraded": "质量门模块不可用。"}
    gate = str(args.get("gate") or "G1").upper()
    spec, _ = _resolve_spec(args, ctx)
    try:
        if gate in ("ALL", "*"):
            reps = gates.run_all(spec, arch=ctx.get("archetype_obj"),
                                 pack_dir=args.get("pack_dir") or ctx.get("pack_dir"))
            return {"tool": "gate_run", "ok": True, "reports": reps,
                    "summary": gates.summarize(reps)}
        if gate == "G1":
            rep = gates.g1_balance(spec) if spec else None
        elif gate == "G2":
            rep = gates.g2_script(spec) if spec else None
        elif gate == "G3":
            rep = gates.g3_duel(spec, duels=int(args.get("duels") or 10)) if spec else None
        elif gate == "G4":
            arch = ctx.get("archetype_obj")
            cards = [c for c in (ctx.get("cards") or []) if isinstance(c, CardSpec)]
            rep = gates.g4_series(arch, cards) if arch is not None else None
        elif gate == "G5":
            pack = args.get("pack_dir") or ctx.get("pack_dir")
            rep = gates.g5_export(pack) if pack else None
        else:
            rep = gates.run(gate)          # 未知门名由内核返回 fail + GATE_UNKNOWN
        if rep is None:
            return {"tool": "gate_run", "ok": False,
                    "degraded": f"{gate} 缺少执行所需的参数（卡 / 系列 / 包目录）。"}
        d = _report_dict(rep)
        d["tool"] = "gate_run"
        return d
    except Exception as e:
        return {"tool": "gate_run", "ok": False, "error": f"{gate} 执行异常：{e}"}


def _t_psct_lint(args: dict, ctx: dict) -> dict:
    spec, err = _resolve_spec(args, ctx)
    text = str(args.get("text") or "")
    lang = str(args.get("lang") or "zh_cn")
    lint = _try_import(".content.psct.lint")
    fn = getattr(lint, "lint", None) if lint else None
    if not callable(fn):
        return {"tool": "psct_lint", "ok": False, "degraded": "PSCT 校验模块不可用。"}
    try:
        if text:
            issues = lint.lint_text(text, lang, spec)
        elif spec is not None:
            issues = fn(spec, lang)
        elif err:
            # 用户明明指了卡却找不到 —— 把内核的查卡结论原样报出去，别打马虎眼
            return {"tool": "psct_lint", "ok": False, "error": err}
        else:
            return {"tool": "psct_lint", "ok": False,
                    "error": "既要校验卡文，就得给 text 或指定一张卡。"}
    except Exception as e:
        return {"tool": "psct_lint", "ok": False, "error": f"PSCT 校验执行异常：{e}"}
    return {"tool": "psct_lint", "ok": True, "count": len(issues or []),
            "issues": _issues(issues),
            "note": "规则来自 content/psct/lint.py（G-text 门），本工具不做判断。"}


def _t_psct_gen(args: dict, ctx: dict) -> dict:
    spec, err = _resolve_spec(args, ctx)
    if spec is None:
        return {"tool": "psct_gen", "ok": False, "error": err}
    gen = _try_import(".content.psct.gen")
    fn = getattr(gen, "compose", None) if gen else None
    if not callable(fn):
        return {"tool": "psct_gen", "ok": False, "degraded": "PSCT 生成模块不可用。"}
    lang = str(args.get("lang") or "zh_cn")
    try:
        text = fn(spec, lang)
        pend = (gen.compose_pendulum(spec, lang)
                if callable(getattr(gen, "compose_pendulum", None)) and spec.is_pendulum else "")
        typeline = (gen.type_line(spec, lang)
                    if callable(getattr(gen, "type_line", None)) else "")
    except Exception as e:
        return {"tool": "psct_gen", "ok": False, "error": f"卡文生成异常：{e}"}
    return {"tool": "psct_gen", "ok": True, "lang": lang, "text": text,
            "pendulum_text": pend, "type_line": typeline}


def _t_draft_card(args: dict, ctx: dict) -> dict:
    """AI 起草卡文草稿：LLM 提议，**内核校验器裁决**（lint_text + G1）。

    与 ``psct_gen`` 的分工：那个是从结构化效果确定性投影（永远可用）；
    这个是从自然语言概念自由起草（**需要配置大模型**，没有就诚实降级）。
    返回里的 ``issues`` / ``counts`` / ``gate`` 全部来自内核，LLM 的自评不采信。
    """
    d = _try_import(".assistant.draft")
    if d is None or not callable(getattr(d, "draft", None)):
        return {"tool": "draft_card", "ok": False,
                "degraded": "起草模块（assistant/draft.py）不可用。"}
    spec, _err = _resolve_spec(args, ctx)     #  spec 可选：没选中卡也能从概念起草
    lang = str(args.get("lang") or "zh_cn")
    prefer = str(args.get("provider") or ctx.get("provider") or "auto")
    try:
        out = d.draft(str(args.get("concept") or args.get("text") or ""),
                      spec=spec, lang=lang, prefer=prefer,
                      with_g1=bool(args.get("with_g1", True)))
    except Exception as e:
        return {"tool": "draft_card", "ok": False, "error": f"起草执行异常：{e}"}
    out["tool"] = "draft_card"
    out.setdefault("ok", True)
    return out


def _t_lua_lint(args: dict, ctx: dict) -> dict:
    spec, _ = _resolve_spec(args, ctx)
    body = str(args.get("lua") or (getattr(spec, "lua", "") if spec else ""))
    lint = _try_import(".content.lua.lint")
    fn = getattr(lint, "lint_lua", None) if lint else None
    if fn is None:
        return {"tool": "lua_lint", "ok": False, "degraded": "Lua 校验模块不可用。"}
    try:
        issues = fn(body, spec)
        sync = getattr(lint, "check_stringid_sync", None)
        if spec is not None and callable(sync):
            issues = list(issues or []) + list(sync(spec, body) or [])
    except Exception as e:
        return {"tool": "lua_lint", "ok": False, "error": f"Lua 校验执行异常：{e}"}
    return {"tool": "lua_lint", "ok": True, "count": len(issues or []),
            "issues": _issues(issues)}


def _t_lua_gen(args: dict, ctx: dict) -> dict:
    spec, err = _resolve_spec(args, ctx)
    if spec is None:
        return {"tool": "lua_gen", "ok": False, "error": err}
    emit = _try_import(".content.lua.emit")
    fn = getattr(emit, "emit_script", None) if emit else None
    if not callable(fn):
        return {"tool": "lua_gen", "ok": False,
                "degraded": "Lua 生成模块（content/lua/emit.py）尚未就绪，"
                            "所以这一项现在只能走静态检查（lua_lint）。"}
    try:
        body = fn(spec, tier=int(args.get("tier") or 1))
    except Exception as e:
        return {"tool": "lua_gen", "ok": False, "error": f"Lua 生成异常：{e}"}
    out = {"tool": "lua_gen", "ok": True, "lua": body, "chars": len(body or "")}
    lint = _try_import(".content.lua.lint")
    if lint is not None and callable(getattr(lint, "lint_lua", None)):
        try:
            out["issues"] = _issues(lint.lint_lua(body, spec))
        except Exception:
            out["degraded"] = "生成成功，但校验模块调用失败，未附静态检查结果。"
    return out


def _t_effects_lookup(args: dict, ctx: dict) -> dict:
    """效果 DSL 注册表查询（纯查表，不判定）。"""
    mod = _try_import(".content.effects")
    if mod is None:
        return {"tool": "effects_lookup", "ok": False,
                "degraded": "效果 DSL 注册表（content/effects.py）尚未就绪，"
                            "现在只能按知识库里的设计规律说话。"}
    key = str(args.get("key") or "")
    text = str(args.get("text") or "")
    try:
        if key and callable(getattr(mod, "kind", None)):
            k = mod.kind(key)
            return {"tool": "effects_lookup", "ok": bool(k),
                    "kind": (k.to_dict() if hasattr(k, "to_dict")
                             else (dict(vars(k)) if k else None)),
                    "error": "" if k else f"效果种类「{key}」不在注册表里。"}
        if text and callable(getattr(mod, "infer_from_text", None)):
            effs = mod.infer_from_text(text) or []
            return {"tool": "effects_lookup", "ok": True, "text": text,
                    "effects": [e.to_dict() if hasattr(e, "to_dict") else e for e in effs],
                    "note": "这是规则/关键词推断的候选，不是裁决；写入规格前请人工确认。"}
        if callable(getattr(mod, "describe_all", None)):
            items = mod.describe_all() or []
            return {"tool": "effects_lookup", "ok": True, "count": len(items),
                    "kinds": [i.get("key") for i in items if isinstance(i, dict)][:80]}
    except Exception as e:
        return {"tool": "effects_lookup", "ok": False, "error": f"注册表查询异常：{e}"}
    return {"tool": "effects_lookup", "ok": False,
            "error": "要查效果种类，请给 key，或给一段 text 让规则引擎推断。"}


def _t_pool_search(args: dict, ctx: dict) -> dict:
    q = str(args.get("query") or args.get("q") or "").strip()
    if not q:
        return {"tool": "pool_search", "ok": False, "error": "没有给查询词。"}
    pool = _official_pool()
    if pool is None:
        return {"tool": "pool_search", "ok": False, **_MISSING_POOL}
    try:
        hits = pool.search(q, limit=int(args.get("limit") or 12)) or []
        return {"tool": "pool_search", "ok": True, "query": q, "count": len(hits),
                "cards": hits, "warnings": list(getattr(pool, "warnings", []) or [])}
    except Exception as e:
        return {"tool": "pool_search", "ok": False, "error": f"官方池查询异常：{e}"}


def _t_pool_dupcheck(args: dict, ctx: dict) -> dict:
    spec, _ = _resolve_spec(args, ctx)
    name = str(args.get("name") or args.get("field")
               or (spec.archetype if spec is not None else "") or "").strip()
    if not name and spec is not None:
        name = spec.name
    if not name:
        return {"tool": "pool_dupcheck", "ok": False, "error": "没给要查重的字段名/卡名。"}
    fn = _kernel(".content.design", "dupcheck_archetype")
    if fn is None:
        return {"tool": "pool_dupcheck", "ok": False, "degraded": "设计辅助模块不可用。"}
    pool = _official_pool()
    try:
        res = fn(name, pool)
    except Exception as e:
        return {"tool": "pool_dupcheck", "ok": False, "error": f"查重执行异常：{e}"}
    out = dict(res or {})
    out["tool"] = "pool_dupcheck"
    out["ok"] = bool(out.get("checked"))
    if pool is None:
        out.setdefault("degraded", "官方卡池不可用，查重没有真正执行（checked=False）。")
    return out


def _t_setcode_suggest(args: dict, ctx: dict) -> dict:
    fn = _kernel(".content.design", "suggest_setcode")
    if fn is None:
        return {"tool": "setcode_suggest", "ok": False, "degraded": "设计辅助模块不可用。"}
    pool = _official_pool()
    try:
        code = fn(pool)
    except Exception as e:
        return {"tool": "setcode_suggest", "ok": False, "error": f"setcode 分配异常：{e}"}
    return {"tool": "setcode_suggest", "ok": True, "setcode": code,
            "pool_available": pool is not None,
            "note": "" if pool is not None else
                    "官方池不可用，返回的是安全区起点，没有做占用校验。"}


def _t_archetype_get(args: dict, ctx: dict) -> dict:
    repo = _try_import(".pool.repo")
    if repo is None:
        return {"tool": "archetype_get", "ok": False, "degraded": "卡库模块（pool/repo.py）不可用。"}
    name = str(args.get("name") or ctx.get("archetype") or "").strip()
    try:
        if not name:
            return {"tool": "archetype_get", "ok": True, "archetypes": repo.list_archetypes()}
        arch = repo.load_archetype(name)
        if arch is None:
            return {"tool": "archetype_get", "ok": False,
                    "error": f"没有名为「{name}」的系列圣经（workspace/archetypes 下找不到）。"}
        d = arch.to_dict() if hasattr(arch, "to_dict") else dict(arch)
        cards = repo.list_cards(name) or []
        return {"tool": "archetype_get", "ok": True, "archetype": d,
                "card_count": len(cards), "cards": cards[:100]}
    except Exception as e:
        return {"tool": "archetype_get", "ok": False, "error": f"读取系列异常：{e}"}


def _t_series_plan(args: dict, ctx: dict) -> dict:
    repo = _try_import(".pool.repo")
    name = str(args.get("name") or ctx.get("archetype") or "").strip()
    arch = ctx.get("archetype_obj")
    if arch is None and name and repo is not None:
        try:
            arch = repo.load_archetype(name)
        except Exception:
            arch = None
    if arch is None:
        return {"tool": "series_plan", "ok": False,
                "error": "没有系列可规划。先建系列圣经（archetype），或把 name 填对。"}
    design = _try_import(".content.design")
    out: dict[str, Any] = {"tool": "series_plan", "ok": True, "archetype": name or arch.name}
    try:
        if design is not None and callable(getattr(design, "plan_series", None)):
            out["plan"] = design.plan_series(arch)
        elif design is not None and callable(getattr(design, "build_roster", None)):
            out["roster"] = [r.to_dict() if hasattr(r, "to_dict") else r
                             for r in (design.build_roster(arch) or [])]
        else:
            return {"tool": "series_plan", "ok": False,
                    "degraded": "设计辅助模块（content/design.py）不可用，无法出蓝图。"}
        if design is not None and callable(getattr(design, "opening_probability", None)):
            starters = sum(int(getattr(s, "count", 0) or 0)
                           for s in (getattr(arch, "roster", []) or [])
                           if getattr(s, "role", "") == "starter")
            out["starter_count"] = starters
            out["opening_rate"] = round(design.opening_probability(starters) * 100, 1)
    except Exception as e:
        return {"tool": "series_plan", "ok": False, "error": f"系列蓝图生成异常：{e}"}
    return out


def _t_deck_analyze(args: dict, ctx: dict) -> dict:
    repo = _try_import(".pool.repo")
    design = _try_import(".content.design")
    if design is None or not callable(getattr(design, "analyze_deck", None)):
        return {"tool": "deck_analyze", "ok": False, "degraded": "设计辅助模块不可用，无法分析卡组。"}
    name = str(args.get("name") or ctx.get("deck") or "").strip()
    deck = ctx.get("deck_obj")
    if deck is None and name and repo is not None:
        try:
            deck = repo.load_deck(name)
        except Exception:
            deck = None
    if deck is None:
        return {"tool": "deck_analyze", "ok": False,
                "error": "没有指定卡组（name），或该卡组不在 workspace/decks 下。"}
    cards: dict[int, CardSpec] = {}
    try:
        if repo is not None:
            for item in (repo.list_cards() or []):
                cid = int(item.get("id") or 0)
                if not cid:
                    continue
                s = repo.load_card(cid, str(item.get("archetype") or ""))
                if s is not None:
                    cards[cid] = s
        res = design.analyze_deck(deck, cards)
        return {"tool": "deck_analyze", "ok": True, "deck": name, "result": res}
    except Exception as e:
        return {"tool": "deck_analyze", "ok": False, "error": f"卡组分析异常：{e}"}


def _t_opening_probability(args: dict, ctx: dict) -> dict:
    fn = _kernel(".content.design", "opening_probability")
    if fn is None:
        return {"tool": "opening_probability", "ok": False,
                "degraded": "设计辅助模块不可用。"}
    try:
        n = int(args.get("n_starters") or args.get("starters") or 0)
        d = int(args.get("deck_size") or 40)
        h = int(args.get("hand") or 5)
        p = fn(n, d, h)
    except Exception as e:
        return {"tool": "opening_probability", "ok": False, "error": f"初动率计算异常：{e}"}
    return {"tool": "opening_probability", "ok": True, "n_starters": n,
            "deck_size": d, "hand": h, "probability": round(float(p), 4),
            "percent": round(float(p) * 100, 1)}


def _t_red_flags(args: dict, ctx: dict) -> dict:
    """红旗清单查询（读 RED_FLAGS 常量表，不产生判断）。"""
    design = _try_import(".content.design")
    flags = getattr(design, "RED_FLAGS", None) if design is not None else None
    if not flags:
        return {"tool": "red_flags", "ok": False, "degraded": "红旗清单（content/design.py）不可用。"}
    out = []
    for f in flags:
        d = f.to_dict() if hasattr(f, "to_dict") else (dict(vars(f)) if hasattr(f, "__dict__") else f)
        if isinstance(d, dict):
            out.append({k: d.get(k) for k in ("code", "level", "zh", "hint") if k in d})
    return {"tool": "red_flags", "ok": True, "count": len(out), "flags": out}


def _t_knowledge_search(args: dict, ctx: dict) -> dict:
    q = str(args.get("query") or args.get("q") or "").strip()
    if not q:
        return {"tool": "knowledge_search", "ok": False, "error": "没有检索词。"}
    try:
        hits = knowledge.search(q, k=int(args.get("k") or 3))
    except Exception as e:
        return {"tool": "knowledge_search", "ok": False, "error": f"检索异常：{e}"}
    return {"tool": "knowledge_search", "ok": True, "query": q,
            "hits": [{"section": h["section"], "score": h["score"],
                      "text": h["text"], "source": h["source"],
                      "doc_id": h["doc_id"], "low_confidence": h.get("low_confidence", False)}
                     for h in hits]}


def _t_render_capabilities(args: dict, ctx: dict) -> dict:
    fn = _kernel(".render.compositor", "capabilities")
    if fn is None:
        return {"tool": "render_capabilities", "ok": False,
                "degraded": "渲染模块（render/compositor.py）不可用。"}
    try:
        return {"tool": "render_capabilities", "ok": True, "capabilities": fn()}
    except Exception as e:
        return {"tool": "render_capabilities", "ok": False, "error": f"渲染能力探测异常：{e}"}


def _t_engine_detect(args: dict, ctx: dict) -> dict:
    fn = _kernel(".duel.engine", "detect")
    if fn is None:
        return {"tool": "engine_detect", "ok": False,
                "degraded": "对局模块（duel/engine.py）不可用。"}
    try:
        st = fn()
    except Exception as e:
        return {"tool": "engine_detect", "ok": False, "error": f"引擎探测异常：{e}"}
    d = st.to_dict() if hasattr(st, "to_dict") else dict(getattr(st, "__dict__", {}) or {})
    level = str(d.get("level") or "static")
    d["tool"] = "engine_detect"
    d["ok"] = True
    d["level_zh"] = {"ocgcore": "真引擎可实跑（L3）", "static": "仅静态校验（L2）",
                     "export-only": "只能导出（L1）"}.get(level, level)
    return d


def _t_duel_probe(args: dict, ctx: dict) -> dict:
    """实跑能力探针：只报告引擎与驱动模块在不在，**不谎称跑过对局**。"""
    engine = _kernel(".duel.engine", "detect")
    bot = _try_import(".duel.bot")
    scenario = _try_import(".duel.scenario")
    st = {}
    try:
        if callable(engine):
            r = engine()
            st = (r.to_dict() if hasattr(r, "to_dict")
                  else dict(getattr(r, "__dict__", {}) or {}))
    except Exception:
        st = {}
    return {"tool": "duel_probe", "ok": True,
            "engine_level": str(st.get("level") or "static"),
            "engine_reason": str(st.get("reason") or ""),
            "bot_ready": bot is not None and callable(getattr(bot, "run_duel", None)),
            "scenario_ready": scenario is not None,
            "note": "G3 只有在 bot/scenario 都就绪且引擎可用时才会给出实跑结论；"
                    "否则返回 skipped（没跑过），不会假称通过。"}


def _t_export_pack(args: dict, ctx: dict) -> dict:
    """导出建包。**必须显式 confirm**：这是有副作用的落盘动作，助手不擅自触发。"""
    if not args.get("confirm"):
        return {"tool": "export_pack", "ok": False,
                "degraded": "导出会写盘并生成 .cdb，需要显式 confirm=true 才执行。"
                            "先把卡号/包名告诉我，我再确认一次。"}
    exp = _try_import(".export.expansions")
    fn = getattr(exp, "build", None) if exp else None
    if not callable(fn):
        return {"tool": "export_pack", "ok": False, "degraded": "导出模块（export/expansions.py）不可用。"}
    repo = _try_import(".pool.repo")
    specs: list[CardSpec] = []
    ids = args.get("card_ids") or args.get("cards") or []
    try:
        for cid in ids:
            s = repo.load_card(int(cid)) if repo is not None else None
            s = _as_spec(s)
            if s is not None:
                specs.append(s)
    except Exception as e:
        return {"tool": "export_pack", "ok": False, "error": f"读卡失败：{e}"}
    if not specs:
        return {"tool": "export_pack", "ok": False,
                "error": "card_ids 为空或都读不到，没有可导出的卡。"}
    try:
        res = fn(specs, str(args.get("out_dir") or "") or None,
                 name=str(args.get("name") or "CardForge"))
    except Exception as e:
        return {"tool": "export_pack", "ok": False, "error": f"导出异常：{e}"}
    return {"tool": "export_pack", "ok": True, "result": res if isinstance(res, dict)
            else {"raw": str(res)}}


def _t_art_status(args: dict, ctx: dict) -> dict:
    """ComfyUI 在线状态（短超时；离线是常态，不算错误）。"""
    client_cls = _kernel(".art.client", "ComfyClient")
    if client_cls is None:
        return {"tool": "art_status", "ok": False, "degraded": "出图模块（art/client.py）不可用。"}
    host = str(args.get("host") or "http://127.0.0.1:8188")
    try:
        cli = client_cls(host, timeout=2)
        alive = bool(cli.alive())
    except Exception as e:
        return {"tool": "art_status", "ok": True, "online": False,
                "host": host, "reason": str(e),
                "hint": "ComfyUI 没在本机运行。卡图这一步可以先跳过，用现成插画渲染卡面。"}
    out = {"tool": "art_status", "ok": True, "online": alive, "host": host}
    if alive:
        try:
            out["models"] = cli.models()
        except Exception as e:
            out["degraded"] = f"在线但模型清单读取失败：{e}"
    return out


def _t_art_generate(args: dict, ctx: dict) -> dict:
    """出图：同样**必须 confirm**（一次生成动辄几十秒且占显存）。"""
    if not args.get("confirm"):
        return {"tool": "art_generate", "ok": False,
                "degraded": "生成卡图会占用 ComfyUI 与显存，需要显式 confirm=true。"
                            "先确认 ComfyUI 在线（art_status），再让我提交。"}
    spec, _ = _resolve_spec(args, ctx)
    run = _try_import(".art.run")
    gen = getattr(run, "generate", None) if run else None
    if not callable(gen):
        return {"tool": "art_generate", "ok": False, "degraded": "出图流水线（art/run.py）不可用。"}
    req = ArtRequest(subject=str(args.get("subject") or ""), style=str(args.get("style") or ""),
                     preset=str(args.get("preset") or "t2i_single"),
                     card_id=int(getattr(spec, "id", 0) or 0),
                     archetype=str(getattr(spec, "archetype", "") or ""))
    try:
        res = gen(req, spec)
    except Exception as e:
        return {"tool": "art_generate", "ok": False, "error": f"出图失败：{e}",
                "hint": "常见原因：ComfyUI 未运行、缺节点、缺权重、显存不足。"}
    d = res.to_dict() if hasattr(res, "to_dict") else dict(res or {})
    d["tool"] = "art_generate"
    d["ok"] = bool(d.get("ok", True))
    return d


def _t_help_step(args: dict, ctx: dict) -> dict:
    """流程向导：转调 ``chat.guide_step``（惰性导入，避免循环依赖）。"""
    step = str(args.get("step") or args.get("name") or "")
    chat = _try_import(".assistant.chat")
    fn = getattr(chat, "guide_step", None) if chat else None
    if not callable(fn):
        return {"tool": "help_step", "ok": False, "degraded": "向导模块（assistant/chat.py）不可用。"}
    try:
        sess = ctx.get("session")
        text = fn(step, sess) if sess is not None else fn(step, None)
    except Exception as e:
        return {"tool": "help_step", "ok": False, "error": f"向导查询异常：{e}"}
    return {"tool": "help_step", "ok": True, "step": step, "text": text,
            "steps": STEPS_INDEX}


STEPS_INDEX: list[str] = ["new_card", "anchor", "audit", "text", "script",
                          "render", "art", "series", "deck", "export"]


# ══════════════════════════════════════════════════════════════════════
#  注册表
# ══════════════════════════════════════════════════════════════════════
def _fn(name: str, desc: str, props: dict, required: Optional[list[str]] = None,
        handler: Optional[Callable] = None) -> dict:
    """注册一个工具：只装 schema 与 handler 引用，**不含任何判断**。"""
    schema: dict[str, Any] = {"type": "object", "properties": dict(props or {}),
                              "additionalProperties": True}
    if required:
        schema["required"] = list(required)
    return {"zh": desc, "handler": handler, "needs_card": bool(props.get("card_id")),
            "schema": {"name": name, "description": desc, "parameters": schema}}


_P_CARD = {
    "card_id": {"type": "integer", "description": "卡号（workspace/cards 下的工程）"},
    "name": {"type": "string", "description": "卡名（工作区内模糊匹配）"},
    "archetype": {"type": "string", "description": "所属系列名（可选）"},
}

TOOLS: dict[str, dict] = {
    "card_get": _fn("card_get", "读取一张卡的结构化规格（CardSpec）与摘要。",
                    {**_P_CARD}, handler=_t_card_get),
    "card_list": _fn("card_list", "列出工作区里的全部卡片摘要。",
                     {"archetype": {"type": "string", "description": "只看某个系列（可选）"}},
                     handler=_t_card_list),
    "card_patch": _fn("card_patch", "修改卡片的确定性字段并落盘（不判断平衡性）。",
                      {**_P_CARD, "patch": {"type": "object",
                                            "description": "要改的字段，如 {\"atk\": 1800}"}},
                      handler=_t_card_patch),
    "card_audit": _fn("card_audit", "跑 G1 平衡审计，返回逐条 issue（规则号/级别/建议）。",
                      {**_P_CARD, "check_pool": {"type": "boolean",
                                                 "description": "是否做官方池查重（默认 true）"}},
                      handler=_t_card_audit),
    "gate_run": _fn("gate_run", "执行指定质量门（G1/G2/G3/G4/G5 或 ALL）。",
                    {**_P_CARD,
                     "gate": {"type": "string", "enum": ["G1", "G2", "G3", "G4", "G5", "ALL"]},
                     "duels": {"type": "integer", "description": "G3 实跑局数"},
                     "pack_dir": {"type": "string", "description": "G5 的包目录"}},
                    ["gate"], handler=_t_gate_run),
    "psct_lint": _fn("psct_lint", "对卡文跑 PSCT 确定性校验（G-text 门）。",
                     {**_P_CARD, "text": {"type": "string"}, "lang": {"type": "string"}},
                     handler=_t_psct_lint),
    "psct_gen": _fn("psct_gen", "由 CardSpec 生成 PSCT 卡文（多语言）。",
                    {**_P_CARD, "lang": {"type": "string",
                                         "description": "zh_cn / ja / en …（默认 zh_cn）"}},
                    handler=_t_psct_gen),
    "draft_card": _fn("draft_card",
                      "按概念描述起草一份 PSCT 卡文草稿：大模型只提议，"
                      "内核校验器（PSCT 规则 + G1）出确定性问题清单。"
                      "没配置大模型时本工具不可用（会如实说明）。",
                      {**_P_CARD,
                       "concept": {"type": "string",
                                   "description": "概念描述，如「翻转后堆墓的通常陷阱」"},
                       "text": {"type": "string", "description": "concept 的别名"},
                       "lang": {"type": "string",
                                "description": "目标语言（默认 zh_cn）"},
                       "provider": {"type": "string",
                                    "description": "用哪个模型（默认 auto）"},
                       "with_g1": {"type": "boolean",
                                   "description": "附带卡时是否顺带跑 G1（默认 true）"}},
                      ["concept"], handler=_t_draft_card),
    "lua_gen": _fn("lua_gen", "由 CardSpec 生成 Lua 脚本（并顺带静态检查）。",
                   {**_P_CARD, "tier": {"type": "integer", "description": "脚本档位 1/2/3"}},
                   handler=_t_lua_gen),
    "lua_lint": _fn("lua_lint", "静态校验 Lua 脚本（语法、API 存在性、Stringid 同步）。",
                    {**_P_CARD, "lua": {"type": "string", "description": "脚本正文"}},
                    handler=_t_lua_lint),
    "effects_lookup": _fn("effects_lookup", "查询效果 DSL 注册表；给 text 时做规则推断。",
                          {"key": {"type": "string", "description": "效果种类键"},
                           "text": {"type": "string", "description": "从这段文字反推效果"}},
                          handler=_t_effects_lookup),
    "pool_search": _fn("pool_search", "在官方卡池（只读 .cdb）里查卡。",
                       {"query": {"type": "string"}, "limit": {"type": "integer"}},
                       ["query"], handler=_t_pool_search),
    "pool_dupcheck": _fn("pool_dupcheck", "字段名/卡名查重（精确同名 + 官方名子串）。",
                         {"name": {"type": "string"}, **_P_CARD}, handler=_t_pool_dupcheck),
    "setcode_suggest": _fn("setcode_suggest", "挑一个未被官方占用的 setcode。",
                           {}, handler=_t_setcode_suggest),
    "archetype_get": _fn("archetype_get", "读取系列圣经（三锚点/方言/卡表蓝图）。",
                         {"name": {"type": "string"}}, handler=_t_archetype_get),
    "series_plan": _fn("series_plan", "展开卡表蓝图并给出初动数量与初动率。",
                       {"name": {"type": "string", "description": "系列名"}},
                       handler=_t_series_plan),
    "deck_analyze": _fn("deck_analyze", "卡组分析：卡位覆盖 / 冗余判据 / 初动率。",
                        {"name": {"type": "string", "description": "卡组名"}},
                        handler=_t_deck_analyze),
    "opening_probability": _fn("opening_probability",
                               "计算起手至少 1 张初动点的概率（超几何分布）。",
                               {"n_starters": {"type": "integer"},
                                "deck_size": {"type": "integer"},
                                "hand": {"type": "integer"}},
                               ["n_starters"], handler=_t_opening_probability),
    "red_flags": _fn("red_flags", "列出 22 条红旗规则原文（code/级别/建议）。",
                     {}, handler=_t_red_flags),
    "knowledge_search": _fn("knowledge_search", "检索设计方法论知识库（纯关键词 + bigram 打分）。",
                            {"query": {"type": "string"}, "k": {"type": "integer"}},
                            ["query"], handler=_t_knowledge_search),
    "render_capabilities": _fn("render_capabilities", "报告渲染管线可用性（字体/素材/Pillow）。",
                               {}, handler=_t_render_capabilities),
    "engine_detect": _fn("engine_detect", "探测对局引擎层级（ocgcore / static / export-only）。",
                         {}, handler=_t_engine_detect),
    "duel_probe": _fn("duel_probe", "报告 G3 实跑所需的模块是否就绪（不谎称跑过）。",
                      {}, handler=_t_duel_probe),
    "art_status": _fn("art_status", "探测 ComfyUI 是否在线并列可用模型。",
                      {"host": {"type": "string"}}, handler=_t_art_status),
    "art_generate": _fn("art_generate", "提交卡图生成请求（需要 confirm=true）。",
                        {**_P_CARD, "subject": {"type": "string"},
                         "style": {"type": "string"},
                         "preset": {"type": "string"},
                         "confirm": {"type": "boolean"}}, handler=_t_art_generate),
    "export_pack": _fn("export_pack", "导出 EDOPro 扩展包（需要 confirm=true）。",
                       {"card_ids": {"type": "array", "items": {"type": "integer"}},
                        "name": {"type": "string"}, "out_dir": {"type": "string"},
                        "confirm": {"type": "boolean"}}, handler=_t_export_pack),
    "help_step": _fn("help_step", "询问某个制卡步骤做什么、为什么存在、下一步是什么。",
                     {"step": {"type": "string", "enum": STEPS_INDEX}},
                     handler=_t_help_step),
}


def tool_schemas() -> list[dict]:
    """OpenAI function-calling 用的 schema 列表。"""
    out: list[dict] = []
    for name, spec in TOOLS.items():
        fn = dict(spec.get("schema") or {})
        fn.setdefault("name", name)
        out.append({"type": "function", "function": fn})
    return out


def tool_names() -> list[str]:
    return list(TOOLS.keys())


def tool_doc(name: str) -> str:
    """一句话说明这个工具转调了哪个内核。"""
    spec = TOOLS.get(name) or {}
    return str(spec.get("zh") or "")


def call(name: str, args: dict, ctx: dict) -> dict:
    """执行工具。**永远返回 dict，绝不抛异常**：未知工具、参数缺失、内核未就绪
    都折成 ``ok=False`` + 中文 ``error``/``degraded``。"""
    key = str(name or "").strip()
    spec = TOOLS.get(key)
    if spec is None:
        return {"tool": key, "ok": False,
                "error": f"没有名为「{key}」的工具。可用：" + "、".join(tool_names())}
    handler = spec.get("handler")
    if not callable(handler):
        return {"tool": key, "ok": False, "degraded": "该工具没有绑定实现。"}
    a = dict(args or {}) if isinstance(args, dict) else {"raw": args}
    c = dict(ctx or {}) if isinstance(ctx, dict) else {}
    try:
        out = handler(a, c)
    except Exception as e:                       # 兜住一切：助手不能因为一个工具挂掉而闭嘴
        return {"tool": key, "ok": False, "error": f"工具执行异常：{type(e).__name__}: {e}"}
    if not isinstance(out, dict):
        return {"tool": key, "ok": True, "result": out}
    out.setdefault("tool", key)
    out.setdefault("ok", True)
    # 参数完全没给时的提示语也算有效结论，标记出来方便自检统计
    return out
