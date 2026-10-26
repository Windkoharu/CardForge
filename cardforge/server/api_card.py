"""卡片 / 卡文 / Lua / 质量门 / 系列 / 卡组。

界面上每个动作都对应内核里一个已有函数 —— **这里只做参数拆装，不写业务规则**。
"""
from __future__ import annotations

from typing import Any

from ..core import errors, paths
from ..core.enums import DEFAULT_LANG, LANGS
from ..core.models import Archetype, CardSpec, DeckSpec
from ..pool import repo
from . import kernel as K
from .http import Request, Response

__all__ = ["register"]


def register(app) -> None:

    # ══════════════════════════════════════════════════════════
    #  卡片
    # ══════════════════════════════════════════════════════════
    @app.get("/api/cards")
    def cards_list(req: Request) -> dict:
        arch = req.str_arg("archetype")
        items = K.cards_index(arch)
        return {"ok": True, "count": len(items), "cards": items,
                "archetype": arch}

    @app.get("/api/cards/<cid>")
    def card_get(req: Request) -> dict:
        spec = K.load_spec(req.int_arg("id", int(req.params["cid"])))
        gates = tuple(g.upper() for g in req.str_arg("gates", "G1,G2").split(",") if g)
        return {"ok": True, **K.card_view(spec, with_gates=gates,
                                          preview_width=req.int_arg("width", 0))}

    @app.post("/api/cards")
    def card_save(req: Request) -> dict:
        """新建或覆盖保存。``?new_id=1`` 时自动分配卡号。"""
        payload = req.json or {}
        if req.bool_arg("new_id") and not payload.get("id"):
            payload["id"] = _next_id()
        spec = K.spec_from_payload(payload)
        if not spec.name and not spec.name_i18n:
            raise errors.SpecError("卡名不能为空", "先给卡名，其他都能默认")
        if not spec.id:
            spec.id = _next_id()
        if not spec.created:
            spec.created = _now()
        spec.updated = _now()
        saved = K.save_spec(spec, note=req.str_arg("note"))
        return {"ok": True, **saved, **K.card_view(spec)}

    @app.put("/api/cards/<cid>")
    def card_update(req: Request) -> dict:
        cid = int(req.params["cid"])
        payload = dict(req.json or {})
        payload["id"] = cid
        spec = K.spec_from_payload(payload, card_id=cid)
        spec.updated = _now()
        saved = K.save_spec(spec, note=req.str_arg("note"))
        return {"ok": True, **saved, **K.card_view(spec)}

    @app.post("/api/cards/<cid>/delete")
    def card_delete(req: Request) -> dict:
        cid = int(req.params["cid"])
        arch = req.str_arg("archetype")
        ok = repo.delete_card(cid, arch)
        if not ok:
            raise errors.CardForgeError(f"工作区里没有卡号 {cid}", "确认卡号与所属系列")
        return {"ok": True, "deleted": cid}

    @app.post("/api/cards/<cid>/new-effect")
    def card_add_effect(req: Request) -> dict:
        """加一条空效果 —— 界面「+添加效果」按钮。"""
        cid = int(req.params["cid"])
        spec = K.load_spec(cid)
        from ..core.models import EffectSpec
        eff = EffectSpec(kind=req.str_arg("kind"), trigger=req.str_arg("trigger", "IGNITION"),
                         limit=req.str_arg("limit", "once_per_turn"))
        spec.effects = list(spec.effects or []) + [eff]
        eff.params = dict(eff.params or {})
        eff.params["_index"] = len(spec.effects) - 1
        spec.updated = _now()
        K.save_spec(spec, note="加效果")
        return {"ok": True, "n_effects": len(spec.effects), **K.card_view(spec)}

    @app.get("/api/cards/<cid>/snapshots")
    def card_snapshots(req: Request) -> dict:
        cid = int(req.params["cid"])
        return {"ok": True, "snapshots": repo.snapshots("cards", repo.card_key(cid))}

    @app.post("/api/cards/<cid>/rollback")
    def card_rollback(req: Request) -> dict:
        cid = int(req.params["cid"])
        v = req.int_arg("version")
        if not v:
            raise errors.SpecError("要回滚到哪个版本？", "带上 version=版本号")
        return K.soft_call("cardforge.pool.repo", "rollback", "cards",
                           repo.card_key(cid), v, label="版本回滚")

    # ══════════════════════════════════════════════════════════
    #  PSCT 卡文
    # ══════════════════════════════════════════════════════════
    @app.post("/api/psct/compose")
    def psct_compose(req: Request) -> dict:
        spec = _spec_of(req)
        langs = _langs_of(req)
        gen = K.require("cardforge.content.psct.gen", "PSCT 卡文生成器")
        out: dict[str, Any] = {"ok": True, "langs": {}, "spec_id": spec.id}
        for lang in langs:
            try:
                m = gen.compose_with_meta(spec, lang)
                out["langs"][lang] = m
            except Exception as e:
                out["langs"][lang] = {"text": "", "error": f"{type(e).__name__}: {e}",
                                      "hint": "这条语言的句式模板可能没有原生覆盖，"
                                             "界面上会退回英文"}
        if spec.is_pendulum:
            for lang in langs:
                try:
                    out["langs"][lang]["pendulum_text"] = gen.compose_pendulum(spec, lang)
                except Exception:
                    pass
        if req.bool_arg("write"):
            try:
                gen.fill_spec(spec, langs)
                spec.updated = _now()
                K.save_spec(spec, note="生成卡文")
                out["written"] = True
            except Exception as e:
                out["written"] = False
                out["write_error"] = f"{type(e).__name__}: {e}"
        return out

    @app.post("/api/psct/summon")
    def psct_summon(req: Request) -> dict:
        """召唤条件预览（素材行 + 召唤限制），与 psct.compose 的同一份投影。"""
        spec = _spec_of(req, allow_missing_text=True)
        langs = _langs_of(req)
        mod = K.require("cardforge.content.summon", "召唤条件投影")
        out: dict[str, Any] = {"ok": True, "langs": {}}
        for lang in langs:
            try:
                out["langs"][lang] = mod.compose_meta(spec, lang)
            except Exception as e:
                out["langs"][lang] = {
                    "text": "", "error": f"{type(e).__name__}: {e}",
                    "notes": ["召唤条件生成失败；检查素材字段"],
                }
        return out

    @app.post("/api/psct/infer")
    def psct_infer(req: Request) -> dict:
        """卡文 → 结构化效果（纯规则推断，**不依赖大模型**）。

        这是「手写文本的旧卡也能进 IR 体系」的入口。推断只认关键词与句式，
        认不出「取对象／不取对象」这类细节，所以结果一定要人过一遍。
        """
        spec = _spec_of(req)
        effects = K.require("cardforge.content.effects", "效果种类注册表",
                            "content/effects.py 尚未实现，此刻无法从卡文反推效果；"
                            "可以先在规格页逐条手工填写")
        fn = getattr(effects, "infer_from_text", None)
        if not callable(fn):
            raise errors.EnvError("effects.infer_from_text 不可用",
                                  "确认 content/effects.py 实现完整")
        lang = req.str_arg("lang", "")
        text = req.str_arg("text") or spec.text_in(lang or DEFAULT_LANG) or ""
        if not text.strip():
            raise errors.SpecError("没有可推断的卡文",
                                   "先在规格页填效果文本，或带上 text=<卡文>")
        try:
            inferred = fn(text) or []
        except Exception as e:
            raise errors.LintError(f"推断失败：{e}",
                                   "这段文本可能不是标准 PSCT 句式") from e
        out = []
        for i, eff in enumerate(inferred):
            d = eff.to_dict() if hasattr(eff, "to_dict") else dict(eff)
            d.setdefault("params", {})["_index"] = i
            out.append(d)
        return {"ok": True, "effects": out, "count": len(out),
                "lang": lang or "(自动)",
                "hint": "推断结果只到「种类/时点/对象/代价」这一层，"
                        "数值与特殊条件请核对后再保存"}

    @app.post("/api/psct/tidy")
    def psct_tidy(req: Request) -> dict:
        """把手写卡文**整理**成标准描述 —— 纯规则，零大模型，且**不动 IR**。

        与 ``/api/psct/infer`` 的分工：infer 是「文本 → 效果列表」（会改你的卡），
        tidy 是「文本 → 更规范的文本」（只碰这个文本框）。
        界面拿 ``paragraphs`` 渲染逐段对照，``safe_to_apply`` 决定
        能不能一键整段替换 —— 判据是「每段都被识别 + 数值与卡名逐字保真 +
        整理后校验的 ERROR 不增加」。
        """
        spec = _spec_of(req, allow_missing_text=True)
        lang = req.str_arg("lang", "") or DEFAULT_LANG
        text = req.str_arg("text") or spec.text_in(lang) or ""
        if not text.strip():
            raise errors.SpecError("没有可整理的文本",
                                   "先在卡文框里贴一段效果文本，或带上 text=<文本>")
        mod = K.require("cardforge.content.psct.tidy", "卡文整理器")
        try:
            out = mod.tidy(text, spec, lang,
                           name=req.str_arg("name") or "",
                           rewrite=req.bool_arg("rewrite", True))
        except Exception as e:
            raise errors.LintError(f"整理失败：{e}",
                                   "这段文本可能不是效果文本（例如只有一句风味文）"
                                   "；可以只勾「只做表层整理」。") from e
        out["hint"] = ("逐段对照后采纳。认不出的句子已原样保留 —— "
                       "要让它也变标准，去规格页把那条效果补全（种类/时点/代价/对象）。")
        return out

    @app.post("/api/psct/lint")
    def psct_lint(req: Request) -> dict:
        spec = _spec_of(req, allow_missing_text=True)
        langs = _langs_of(req)
        mod = K.require("cardforge.content.psct.lint", "PSCT 校验器")
        issues: list[dict] = []
        for lang in langs:
            try:
                for i in (mod.lint(spec, lang) or []):
                    d = i.to_dict() if hasattr(i, "to_dict") else dict(i)
                    d.setdefault("lang", lang)
                    issues.append(d)
            except Exception as e:
                issues.append({"gate": "PSCT", "code": "LINT_INTERNAL", "level": "ERROR",
                               "message": f"{lang} 校验执行失败：{e}", "lang": lang})
        return {"ok": True, "count": len(issues),
                "errors": sum(1 for i in issues if i.get("level") == "ERROR"),
                "issues": issues, "langs": list(langs)}

    @app.get("/api/psct/rules")
    def psct_rules(req: Request) -> dict:
        """把校验规则清单交给界面（用户要知道「为什么被拦」）。"""
        try:
            from ..content.psct import lint as pl
            return {"ok": True, "rules": list(getattr(pl, "RULES", []) or [])}
        except Exception as e:
            return {"ok": False, "rules": [], "error": str(e)}

    # ══════════════════════════════════════════════════════════
    #  Lua
    # ══════════════════════════════════════════════════════════
    @app.post("/api/lua/emit")
    def lua_emit(req: Request) -> dict:
        spec = _spec_of(req)
        emit = K.require("cardforge.content.lua.emit", "Lua 脚本生成器",
                         "content/lua/emit.py 尚未实现。此刻可以先用「卡文」"
                         "与「平衡审计」，脚本一栏留空；实现后这里自动可用")
        tier = req.int_arg("tier", 1)
        try:
            lua = emit.emit_script(spec, tier=tier)
        except Exception as e:
            raise errors.LintError(f"脚本生成失败：{e}",
                                   "把这张卡的 effects 贴出来反馈") from e
        out = {"ok": True, "lua": lua, "chars": len(lua), "spec_id": spec.id}
        if req.bool_arg("write"):
            spec.lua = lua
            try:
                spec.strings = list(emit.emit_strings(spec) or [])
            except Exception as e:
                out["strings_hint"] = f"文本槽位生成失败：{type(e).__name__}"
            spec.updated = _now()
            K.save_spec(spec, note="生成脚本")
            try:
                out["script_path"] = paths.rel(emit.write_script(spec))
            except Exception as e:
                out["script_error"] = str(e)
        return out

    @app.post("/api/lua/lint")
    def lua_lint(req: Request) -> dict:
        lua = req.str_arg("lua")
        spec = None
        if req.arg("card") is not None or req.arg("spec") is not None:
            try:
                spec = _spec_of(req)
            except Exception:
                spec = None
        mod = K.require("cardforge.content.lua.lint", "Lua 校验器")
        try:
            ok, why = mod.syntax_ok(lua)
            issues = [i.to_dict() if hasattr(i, "to_dict") else dict(i)
                      for i in (mod.lint_lua(lua, spec) or [])]
        except Exception as e:
            raise errors.LintError(f"Lua 校验执行失败：{e}", "反馈此问题") from e
        unknown = {}
        cat = K.try_import("cardforge.content.lua.apicatalog")
        if cat is not None:
            try:
                unknown = cat.unknown(lua) or {}
            except Exception:
                pass
        return {"ok": True, "syntax": {"ok": bool(ok), "reason": why},
                "issues": issues, "unknown": unknown,
                "errors": sum(1 for i in issues if i.get("level") == "ERROR")}

    @app.get("/api/lua/api")
    def lua_api(req: Request) -> dict:
        """Lua API 白名单规模 —— 让用户知道生成器的能力边界是真的核对过的。"""
        cat = K.try_import("cardforge.content.lua.apicatalog")
        if cat is None:
            return {"ok": False, "hint": "apicatalog 不可用"}
        try:
            return {"ok": True, "info": cat.info(),
                    "counts": {k: len(v) if hasattr(v, "__len__") else 0
                               for k, v in (cat.info() or {}).items()}}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ══════════════════════════════════════════════════════════
    #  质量门
    # ══════════════════════════════════════════════════════════
    @app.get("/api/gates/<gate>")
    def gate_get(req: Request) -> dict:
        return _run_gate(req, req.params["gate"])

    @app.post("/api/gates/<gate>")
    def gate_post(req: Request) -> dict:
        return _run_gate(req, req.params["gate"])

    @app.post("/api/gates/waive")
    def gate_waive(req: Request) -> dict:
        """强制放行一条问题 —— **必须留痕**，谁、什么时候、为什么。"""
        gate = req.str_arg("gate", "G1").upper()
        code = req.str_arg("code")
        reason = req.str_arg("reason")
        if not code:
            raise errors.SpecError("要放行哪条问题？", "带上 code，如 ATK_L4_OVER")
        if not reason:
            raise errors.SpecError("放行必须写理由",
                                   "豁免是留痕的，不写理由等于没放行")
        spec = _spec_of(req)
        rep = _run_gate_obj(req, gate, spec)
        from ..pipeline import gates
        waived = gates.waive(rep, code, reason, who=req.str_arg("who", "user"))
        path = ""
        try:
            path = paths.rel(gates.write_audit(waived, {"card": spec.id,
                                                        "name": spec.display_name,
                                                        "waived_by": "gui"}))
        except Exception:
            pass
        return {"ok": True, "report": waived.to_dict(), "audit": path}

    # ══════════════════════════════════════════════════════════
    #  系列
    # ══════════════════════════════════════════════════════════
    @app.get("/api/archetypes")
    def arch_list(req: Request) -> dict:
        try:
            items = repo.list_archetypes()
        except Exception as e:
            return {"ok": False, "archetypes": [], "error": str(e)}
        return {"ok": True, "count": len(items), "archetypes": items}

    @app.get("/api/archetypes/<name>")
    def arch_get(req: Request) -> dict:
        name = req.params["name"]
        arch = repo.load_archetype(name)
        if arch is None:
            raise errors.CardForgeError(f"没有系列「{name}」", "先看 /api/archetypes 列表")
        cards = [c for c in (repo.load_card(i["id"], name)
                             for i in repo.list_cards(name)) if c is not None]
        out = {"ok": True, "archetype": arch.to_dict(),
               "cards": [c.summary() for c in cards],
               "roster_total": arch.roster_total()}
        if req.bool_arg("plan"):
            out["plan"] = K.soft_call("cardforge.content.design", "plan_series", arch,
                                      label="卡表蓝图")
        return out

    @app.post("/api/archetypes")
    def arch_save(req: Request) -> dict:
        payload = req.json or {}
        if not payload.get("name"):
            raise errors.SpecError("系列名不能为空", "系列名就是本家字段，如「星奏」")
        arch = Archetype.from_dict(payload)
        arch.updated = _now()
        path = repo.save_archetype(arch, snapshot=True, note=req.str_arg("note"))
        return {"ok": True, "path": paths.rel(path) if path else "",
                "archetype": arch.to_dict()}

    @app.post("/api/archetypes/<name>/audit")
    def arch_audit(req: Request) -> dict:
        name = req.params["name"]
        arch = repo.load_archetype(name)
        if arch is None:
            raise errors.CardForgeError(f"没有系列「{name}」", "先创建系列")
        cards = [c for c in (repo.load_card(i["id"], name)
                             for i in repo.list_cards(name)) if c is not None]
        from ..pipeline import gates
        rep = gates.g4_series(arch, cards, K.official())
        return {"ok": True, "report": rep.to_dict(), "n_cards": len(cards)}

    @app.post("/api/archetypes/<name>/roster")
    def arch_roster(req: Request) -> dict:
        name = req.params["name"]
        arch = repo.load_archetype(name)
        if arch is None:
            raise errors.CardForgeError(f"没有系列「{name}」", "先创建系列")
        out = K.soft_call("cardforge.content.design", "build_roster", arch,
                          label="卡表生成")
        if out.get("ok"):
            out["value"] = [s.to_dict() if hasattr(s, "to_dict") else s
                            for s in (out["value"] or [])]
        return out

    @app.post("/api/archetypes/<name>/series-build")
    def arch_series_build(req: Request) -> dict:
        """整系列出图/出卡 —— 长任务，走 job。"""
        name = req.params["name"]
        from ..pipeline import job
        jm = job.manager()
        jid = jm.submit("series", _series_build, name,
                        render=req.bool_arg("render"),
                        art=req.bool_arg("art"))
        return {"ok": True, "queued": True, "job": jid,
                "note": "系列构建在后台跑，进度走 /api/events"}

    register_decks(app)


def _series_build(name: str, *, render: bool = False, art: bool = False,
                  on_progress=None) -> dict:
    cards = repo.list_cards(name)
    total = max(1, len(cards))
    done: list[dict] = []
    for i, row in enumerate(cards):
        spec = repo.load_card(row["id"], name)
        if spec is None:
            continue
        item: dict[str, Any] = {"id": spec.id, "name": spec.display_name}
        if render:
            try:
                from ..render import compositor
                files = compositor.export_card(spec, None, paths.OUT,
                                               sizes=("edopro", "share"))
                item["rendered"] = [paths.rel(f) for f in files]
            except Exception as e:
                item["render_error"] = f"{type(e).__name__}: {e}"
        done.append(item)
        if on_progress:
            on_progress((i + 1) / total, f"已完成 {i + 1}/{total}")
    return {"ok": True, "cards": done, "count": len(done)}


# ══════════════════════════════════════════════════════════════════════
#  卡组
# ══════════════════════════════════════════════════════════════════════
def register_decks(app) -> None:
    @app.get("/api/decks")
    def deck_list(req: Request) -> dict:
        try:
            items = repo.list_decks()
        except Exception as e:
            return {"ok": False, "decks": [], "error": str(e)}
        return {"ok": True, "count": len(items), "decks": items}

    @app.get("/api/decks/<name>")
    def deck_get(req: Request) -> dict:
        name = req.params["name"]
        deck = repo.load_deck(name)
        if deck is None:
            raise errors.CardForgeError(f"没有卡组「{name}」", "先看 /api/decks")
        from ..export import ydk
        return {"ok": True, "deck": deck.to_dict(), "sizes": ydk.sizes(deck),
                "ydk": ydk.to_text(deck)}

    @app.post("/api/decks")
    def deck_save(req: Request) -> dict:
        payload = req.json or {}
        if not payload.get("name"):
            raise errors.SpecError("卡组名不能为空", "给个能认出来的名字")
        deck = DeckSpec.from_dict(payload)
        spec_note = req.str_arg("note")
        path = repo.save_deck(deck, snapshot=True, note=spec_note)
        return {"ok": True, "path": paths.rel(path) if path else "",
                "deck": deck.to_dict()}

    @app.post("/api/decks/<name>/analyze")
    def deck_analyze(req: Request) -> dict:
        name = req.params["name"]
        deck = repo.load_deck(name)
        if deck is None:
            raise errors.CardForgeError(f"没有卡组「{name}」", "先创建卡组")
        cards: dict[int, CardSpec] = {}
        for row in repo.list_cards(deck.archetype or ""):
            sp = repo.load_card(row["id"], deck.archetype or "")
            if sp is not None:
                cards[row["id"]] = sp
        out = K.soft_call("cardforge.content.design", "analyze_deck", deck, cards,
                          label="卡组分析")
        if out.get("ok"):
            from ..export import ydk
            out["value"]["ydk_issues"] = [i.to_dict() for i in ydk.validate(deck)]
        return out

    @app.post("/api/decks/<name>/export")
    def deck_export(req: Request) -> dict:
        name = req.params["name"]
        deck = repo.load_deck(name)
        if deck is None:
            raise errors.CardForgeError(f"没有卡组「{name}」", "先创建卡组")
        from ..export import ydk
        out = req.str_arg("path") or str(paths.OUT / f"{name}.ydk")
        try:
            written = ydk.write(deck, out)
        except Exception as e:
            raise errors.CardForgeError(f"YDK 导出失败：{e}",
                                        "确认 OUT 目录可写") from e
        return {"ok": True, "path": paths.rel(written)}


# ══════════════════════════════════════════════════════════════════════
#  助手函数
# ══════════════════════════════════════════════════════════════════════
def _spec_of(req: Request, *, allow_missing_text: bool = False) -> CardSpec:
    """从 ``card=<id>`` 或 ``spec`` 载荷取出 CardSpec。"""
    if req.arg("spec") is not None:
        return K.spec_from_payload(req.arg("spec"))
    cid = req.arg("card")
    if cid is None:
        cid = req.params.get("cid")
    if cid is None:
        raise errors.SpecError("要指定 ``card=<卡号>`` 或提交 ``spec`` 对象",
                               "界面里选中一张卡再操作即可")
    return K.load_spec(int(cid))


def _langs_of(req: Request) -> tuple[str, ...]:
    raw = req.arg("langs")
    if isinstance(raw, list):
        langs = [str(x) for x in raw]
    else:
        langs = [x.strip() for x in str(raw or "").split(",") if x.strip()]
    if not langs:
        langs = [DEFAULT_LANG]
    bad = [x for x in langs if x not in LANGS]
    if bad:
        raise errors.SpecError(f"不支持的语言：{'、'.join(bad)}",
                               f"可用：{'、'.join(LANGS)}")
    return tuple(langs)


def _run_gate(req: Request, gate: str) -> dict:
    gate = str(gate).upper()
    spec = _spec_of(req)
    rep, audit = _run_gate_obj(req, gate, spec)
    out = {"ok": True, "gate": gate, "report": rep.to_dict(),
           "card": spec.id, "name": spec.display_name}
    if audit:
        out["audit"] = audit
    return out


def _run_gate_obj(req: Request, gate: str, spec: CardSpec):
    """跑一道门。质量门**全部是确定性代码**，界面不允许在这里做任何判断。"""
    from ..pipeline import gates
    gate = str(gate).upper()
    if gate not in gates.GATES:
        raise errors.SpecError(f"没有质量门 {gate}", f"可用：{'、'.join(gates.GATES)}")
    audit = ""
    if gate == "G1":
        lang = req.str_arg("lang")
        rep = (gates.g1_balance(spec, K.official(), lang=lang) if lang
               else gates.g1_balance(spec, K.official()))
    elif gate == "G2":
        rep = gates.g2_script(spec, req.str_arg("lua"))
    elif gate == "G3":
        rep = gates.g3_duel(spec, scenario=req.bool_arg("scenario", True),
                            duels=req.int_arg("duels", 10))
    elif gate == "G4":
        arch = repo.load_archetype(spec.archetype or req.str_arg("archetype"))
        if arch is None:
            raise errors.CardForgeError(
                f"这张卡没有可审计的系列「{spec.archetype}」",
                "先创建系列并把它归入系列，G4 才有对象")
        cards = [c for c in (repo.load_card(i["id"], arch.name)
                             for i in repo.list_cards(arch.name)) if c is not None]
        rep = gates.g4_series(arch, cards, K.official())
    else:
        pack = req.str_arg("pack_dir") or str(paths.EXPORT_DIR)
        rep = gates.g5_export(pack)
    if req.bool_arg("audit"):
        try:
            audit = paths.rel(gates.write_audit(
                rep, {"card": spec.id, "name": spec.display_name, "by": "gui"}))
        except Exception:
            audit = ""
    return rep, audit


def _next_id() -> int:
    """分配一个**同时避开官方池与工作区**的卡号。

    历史缺陷：这里原本只问官方池 ``next_free_id(210000000)``，工作区里已经
    存在的 DIY 卡不会被告知，于是「+ 新卡」会拿到 210000000 并覆盖同号旧卡。
    分配必须把两边合并起来查。
    """
    used = {int(c["id"]) for c in K.cards_index()
            if isinstance(c, dict) and c.get("id") is not None}
    pool = K.official()
    fn = getattr(pool, "next_free_id", None) if pool else None
    n = 210000000
    if callable(fn):
        try:
            n = int(fn(n))
        except Exception:
            n = 210000000
    while n in used:
        n += 1
        if callable(fn):
            try:
                # 官方池占用的号也跳过；next_free_id 从候选号继续找
                n = int(fn(n))
            except Exception:
                pass
    return n


def _now() -> str:
    import datetime as _dt
    return _dt.datetime.now().isoformat(timespec="seconds")
