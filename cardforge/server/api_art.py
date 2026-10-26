"""``/api/art/*`` —— 本地 ComfyUI 出图。

出图是本工具里**唯一会长时间占用机器**的能力（单张几秒到几分钟），所以：

* 一律走后台任务 + SSE 进度，不阻塞界面；
* 提交前先 ``dry_run`` 把将要执行的工作流摊给人看（含模型名、尺寸、seed）；
* ComfyUI 没开/模型缺失 → 明确报 ``comfy_kind`` 与中文回落建议，
  同时**保留「上传自己的图」通路**（见 ``/api/render/upload-art``）。
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from ..core import errors, paths
from ..core.models import ArtRequest
from . import kernel as K
from .http import Request, Response

__all__ = ["register"]


def register(app) -> None:

    @app.get("/api/art/capabilities")
    def art_capabilities(req: Request) -> dict:
        run = K.try_import("cardforge.art.run")
        if run is None:
            return {"ok": False, "available": False, "reason": "art 模块不可用"}
        try:
            caps = run.capabilities(host=_host(req))
        except Exception as e:
            return {"ok": False, "available": False, "error": f"{type(e).__name__}: {e}",
                    "hint": "ComfyUI 没开也不影响造卡：改用「上传自己的卡图」"}
        caps.setdefault("ok", True)
        return caps

    @app.get("/api/art/models")
    def art_models(req: Request) -> dict:
        """本机可用模型 + 档案表 + 自动选中的档案（含**为什么**选它）。"""
        run = K.require("cardforge.art.run", "出图模块")
        prof = K.require("cardforge.art.profiles", "模型档案")
        out: dict[str, Any] = {"ok": True, "host": _host(req)}
        try:
            p = run.probe(host=_host(req), timeout=6)
        except Exception as e:
            return {"ok": False, "alive": False, "error": str(e),
                    "hint": "启动 ComfyUI（默认 127.0.0.1:8188）后刷新", **out}
        models = p.get("models") or {}
        out["alive"] = True
        out["counts"] = {k: len(v) for k, v in models.items() if isinstance(v, list)}
        out["models"] = {k: list(v)[:60] for k, v in models.items() if isinstance(v, list)}
        out["profiles"] = [_profile_row(m) for m in getattr(prof, "PROFILES", [])]
        try:
            chosen = prof.detect(models)
            out["detected"] = _profile_row(chosen)
            ex = getattr(prof, "detect_explain", None)
            out["detected_why"] = ex(models) if callable(ex) else {}
        except Exception as e:
            out["detected"] = None
            out["detected_error"] = f"档案自动选择失败：{type(e).__name__}: {e}"
        out["warnings"] = p.get("warnings") or []
        return out

    @app.get("/api/art/workflows")
    def art_workflows(req: Request) -> dict:
        """ presets 表 —— 界面告诉用户每种工作流要什么模型、会怎么降级。"""
        pre = K.require("cardforge.art.presets", "工作流预设")
        return {"ok": True, "presets": list(getattr(pre, "PRESETS", {}).values())}

    @app.post("/api/art/workflow")
    def art_workflow(req: Request) -> dict:
        """导出**可直接导入 ComfyUI** 的工作流 JSON。

        提示词一律按界面上填的「主体/风格/背景/附加词」编译 —— 以前这里只带卡名，
        于是「导出工作流 JSON」里的 CLIPTextEncode 和用户刚写的话对不上，
        看起来就像程序自作主张改了提示词。
        """
        run = K.require("cardforge.art.run", "工作流导出")
        preset = req.str_arg("preset", "t2i_single")
        spec = None
        if req.arg("card") is not None:
            try:
                spec = K.load_spec(req.int_arg("card"))
            except Exception:
                spec = None
        ar = _request_from(req, spec)
        ar.preset = preset
        out_dir = Path(req.str_arg("out_dir") or (paths.OUT / "workflows"))
        out_dir.mkdir(parents=True, exist_ok=True)
        name = req.str_arg("name") or f"{preset}_{int(Path(str(out_dir)).stat().st_mtime)}"
        path = str(out_dir / f"{_ascii_name(name)}.json")
        try:
            info: dict[str, Any] = {}
            written = run.export_workflow(preset, path, profile=req.str_arg("profile", "auto"),
                                          spec=spec, host=_host(req),
                                          request=ar, submit=req.bool_arg("submit"),
                                          info=info)
        except Exception as e:
            raise _comfy_error(e) from e
        data: dict[str, Any] = {"ok": True, "path": paths.rel(Path(written)),
                                "preset": preset}
        data.update({k: info.get(k) for k in
                     ("positive", "negative", "prompt_mode", "untranslated",
                      "user_input", "profile") if info.get(k) is not None})
        try:
            import json
            data["workflow"] = json.loads(Path(written).read_text(encoding="utf-8"))
            data["import_hint"] = ("ComfyUI 界面 → 菜单 Load（或直接把文件拖进画布）"
                                   "→ 顶部会出现节点；把文件里的说明块看完再点 Run")
        except Exception as e:
            data["read_error"] = str(e)
        return data

    @app.get("/api/art/templates")
    def art_templates(req: Request) -> dict:
        """提示词模板表（12 套正统母题 + 用户自存），按当前卡的规格排好序。

        ``bilingual`` 决定界面拿中文版还是英文版 —— 口径跟着档案的文本编码器走，
        不是跟着偏好走（Krea 2 / Qwen-Image 的中文原话直送，CLIP 只能吃英文标签）。
        """
        tpl = K.require("cardforge.art.templates", "提示词模板")
        spec = None
        if req.arg("card") is not None:
            try:
                spec = K.load_spec(req.int_arg("card"))
            except Exception:
                spec = None
        bi = _bilingual(req)
        rows = [t.to_dict() for t in tpl.list_all()]
        ranked = tpl.recommend(spec) if spec is not None else []
        return {"ok": True, "count": len(rows), "templates": rows,
                "bilingual": bi,
                "language_note": ("当前档案中文原话直送 → 模板取中文版" if bi
                                  else "当前档案只认英文 → 模板取英文版标签"),
                "recommended": [{"key": k, "score": sc} for k, sc in ranked],
                "groups": sorted({str(r.get("group") or "") for r in rows})}

    @app.post("/api/art/templates/save")
    def art_templates_save(req: Request) -> dict:
        """把界面上填好的一版提示词存成「我的模板」（落 workspace，不进代码库）。"""
        tpl = K.require("cardforge.art.templates", "提示词模板")
        fields = {k: req.arg(k) for k in
                  ("subject", "style", "background", "extra_positive",
                   "extra_negative", "preset", "cutout_bg", "use", "note")}
        fields = {k: v for k, v in fields.items() if v is not None}
        if not str(fields.get("subject") or "").strip():
            raise errors.SpecError("主体是空的，存成模板没有意义",
                                   "先在「主体（画什么）」里写点东西")
        try:
            return tpl.save_user(fields, name=req.str_arg("name"))
        except ValueError as e:
            raise errors.SpecError(str(e), "给这一版起个名字，例如「圣痕·龙骑士登场」") from e

    @app.post("/api/art/templates/delete")
    def art_templates_delete(req: Request) -> dict:
        tpl = K.require("cardforge.art.templates", "提示词模板")
        out = tpl.delete_user(req.str_arg("key"))
        if not out.get("ok"):
            raise errors.SpecError(out.get("error") or "删除失败",
                                   out.get("hint") or "看 /api/art/templates 的「我的模板」组")
        return out

    @app.post("/api/art/generate")
    def art_generate(req: Request) -> dict:
        cid = req.int_arg("card")
        if not cid:
            raise errors.SpecError("要指定 card=<卡号>", "先选中一张卡再出图")
        spec = K.load_spec(cid)
        ar = _request_from(req, spec)
        dry = req.bool_arg("dry_run")
        run = K.require("cardforge.art.run", "出图")
        if dry:
            layered = (bool(getattr(ar, "layers", False))
                       or str(getattr(ar, "preset", "")) == "t2i_layers")
            if layered:
                res = run.generate_layers(ar, spec, host=_host(req), dry_run=True)
            else:
                res = run.generate(ar, spec, host=_host(req), dry_run=True)
            return {"ok": True, "dry_run": True, "result": _result_dict(res)}
        from ..pipeline import job
        jid = job.manager().submit("art", _gen_job, cid, ar, _host(req))
        return {"ok": True, "queued": True, "job": jid, "card": cid,
                "note": "出图在后台跑，进度走 /api/events?job=" + jid}

    @app.post("/api/art/generate-series")
    def art_generate_series(req: Request) -> dict:
        name = req.str_arg("archetype")
        if not name:
            raise errors.SpecError("要指定 archetype=<系列名>", "整系列出图按系列来")
        arch = _load_arch(name)
        if arch is None:
            raise errors.CardForgeError(f"没有系列「{name}」", "先看 /api/archetypes")
        cards = [c for c in (_load_card(i["id"], name) for i in _rows(name))
                 if c is not None]
        if not cards:
            raise errors.CardForgeError(f"系列「{name}」里还没有卡", "先造卡再批量出图")
        base = _request_from(req, cards[0])
        from ..pipeline import job
        jid = job.manager().submit("art_series", _series_job, name, base, _host(req))
        return {"ok": True, "queued": True, "job": jid, "n_cards": len(cards)}

    @app.get("/api/art/library")
    def art_library(req: Request) -> dict:
        lib = K.require("cardforge.art.library", "卡图资产库")
        name = req.str_arg("archetype")
        try:
            rows = lib.list_all(name)
        except Exception as e:
            return {"ok": False, "items": [], "error": str(e)}
        for r in rows:
            if r.get("image"):
                r["url"] = "/api/files/" + _rel_of(r["image"])
        return {"ok": True, "count": len(rows), "items": rows}

    @app.get("/api/art/library/<cid>")
    def art_library_card(req: Request) -> dict:
        lib = K.require("cardforge.art.library", "卡图资产库")
        cid = int(req.params["cid"])
        spec = K.load_spec(cid)
        vs = lib.versions(cid, spec.archetype or "")
        for v in vs:
            if v.get("image"):
                v["url"] = "/api/files/" + _rel_of(v["image"])
        return {"ok": True, "card": cid, "versions": vs,
                "current": lib.current(cid, spec.archetype or "")}

    @app.post("/api/art/library/<cid>/use")
    def art_library_use(req: Request) -> dict:
        lib = K.require("cardforge.art.library", "卡图资产库")
        cid = int(req.params["cid"])
        v = req.int_arg("version")
        if not v:
            raise errors.SpecError("要指定 version=<版本号>", "从版本列表里选一个")
        spec = K.load_spec(cid)
        return K.soft_call("cardforge.art.library", "set_current", cid, v,
                           archetype=spec.archetype or "", label="切换卡图版本")

    @app.post("/api/art/library/<cid>/compare")
    def art_library_compare(req: Request) -> dict:
        lib = K.require("cardforge.art.library", "卡图资产库")
        cid = int(req.params["cid"])
        spec = K.load_spec(cid)
        return K.soft_call("cardforge.art.library", "compare", cid,
                           req.int_arg("a"), req.int_arg("b"),
                           archetype=spec.archetype or "", label="版本对比")

    @app.post("/api/art/interrupt")
    def art_interrupt(req: Request) -> dict:
        """打断当前出图 —— 排队中的任务会停，但**已经跑完的不回收**。"""
        cli = K.try_import("cardforge.art.client")
        if cli is None:
            raise errors.EnvError("ComfyUI 客户端不可用", "确认 art/client.py 存在")
        try:
            c = cli.ComfyClient(host=_host(req))
            if not c.alive():
                raise errors.ComfyError("ComfyUI 没有响应", "确认 127.0.0.1:8188 还开着",
                                        kind="offline")
            c.interrupt()
            return {"ok": True, "note": "已发送打断请求。显存释放要点一下「卸载模型」"}
        except errors.CardForgeError:
            raise
        except Exception as e:
            raise errors.ComfyError(f"打断失败：{e}", "在 ComfyUI 界面里点 Queue Prompt "
                                             "→ Interrupt 也可以", kind="offline") from e

    @app.post("/api/art/free")
    def art_free(req: Request) -> dict:
        cli = K.try_import("cardforge.art.client")
        if cli is None:
            raise errors.EnvError("ComfyUI 客户端不可用", "确认 art/client.py 存在")
        try:
            c = cli.ComfyClient(host=_host(req))
            c.free(unload_models=req.bool_arg("unload_models", True))
            return {"ok": True, "note": "已请求释放显存"}
        except Exception as e:
            raise errors.ComfyError(f"释放显存失败：{e}", "可以在 ComfyUI 里手动 Unload",
                                    kind="offline") from e

    @app.get("/api/art/queue")
    def art_queue(req: Request) -> dict:
        cli = K.try_import("cardforge.art.client")
        if cli is None:
            return {"ok": False, "hint": "art.client 不可用"}
        try:
            c = cli.ComfyClient(host=_host(req))
            fn = getattr(c, "queue_depth", None)
            return {"ok": True, "queue": fn() if callable(fn) else None}
        except Exception as e:
            return {"ok": False, "error": str(e),
                    "hint": "你的 ComfyUI 可能正在排队出别的图 —— "
                            "CardForge 不会抢占队列，会等它排空"}


# ══════════════════════════════════════════════════════════════════════
#  任务体
# ══════════════════════════════════════════════════════════════════════
def _gen_job(cid: int, ar: ArtRequest, host: str, on_progress=None) -> dict:
    spec = K.load_spec(cid)
    run = K.require("cardforge.art.run", "出图")
    layered = bool(getattr(ar, "layers", False)) or str(getattr(ar, "preset", "")) == "t2i_layers"
    if layered:
        # 背景 + 主体分两次生成，主体抠底成 alpha 层（出框时只让主体出窗）
        res = run.generate_layers(ar, spec, on_progress=on_progress, host=host)
    else:
        res = run.generate(ar, spec, on_progress=on_progress, host=host)
    out = _result_dict(res)
    if res.ok:
        # 出图成功后自动入资产库并设为当前，界面刷新就能看到。
        # ``run.generate`` 带 card_id 时**已经**入库并把 current 指好（meta["saved"]），
        # 这里只补它没入库的情况 —— 否则每出一张会留下两个重复版本。
        lib = K.try_import("cardforge.art.library")
        if lib is not None and res.images:
            try:
                first = res.images[0]
                recs = (res.meta or {}).get("saved") or []
                rec = recs[0] if recs else lib.save(
                    cid, first, dict(res.meta or {}), archetype=spec.archetype or "")
                lib.set_current(cid, rec.get("version", 0), spec.archetype or "")
                out["saved"] = rec
            except Exception as e:
                out["save_error"] = f"图已生成但入库失败：{type(e).__name__}: {e}"
    return out


def _series_job(name: str, base: ArtRequest, host: str, on_progress=None) -> dict:
    from ..pool import repo
    arch = _load_arch(name)
    cards = [c for c in (_load_card(i["id"], name) for i in repo.list_cards(name))
             if c is not None]
    run = K.require("cardforge.art.run", "系列出图")
    results = run.generate_series(arch, cards, base, on_progress=on_progress, host=host)
    out = []
    lib = K.try_import("cardforge.art.library")
    for spec, res in zip(cards, results):
        row = _result_dict(res)
        row["card"] = spec.id
        row["name"] = spec.display_name
        if res.ok and lib is not None and res.images:
            try:
                recs = (res.meta or {}).get("saved") or []
                rec = recs[0] if recs else lib.save(
                    spec.id, res.images[0], dict(res.meta or {}),
                    archetype=spec.archetype or "")
                lib.set_current(spec.id, rec.get("version", 0), spec.archetype or "")
                row["saved"] = rec
            except Exception as e:
                row["save_error"] = str(e)
        out.append(row)
    ok = sum(1 for r in out if r.get("ok"))
    return {"ok": ok == len(out), "done": ok, "total": len(out), "results": out}


# ══════════════════════════════════════════════════════════════════════
#  小工具
# ══════════════════════════════════════════════════════════════════════
def _host(req: Request) -> str:
    return req.str_arg("host", "") or "http://127.0.0.1:8188"


def _bilingual(req: Request) -> bool:
    """当前档案的文本编码器认不认识中文（决定模板取中文版还是英文版）。

    优先按**指定档案**判；``auto`` 时探一次本机模型再判；
    ComfyUI 不在（探不到）就按 ``krea2`` 的口径给 True —— 本机默认档案就是它，
    且界面「预览工作流」仍然会如实显示最终提示词，不会骗人。
    """
    prof = K.try_import("cardforge.art.profiles")
    if prof is None:
        return True
    key = str(req.str_arg("profile", "") or "").strip()
    if key and key != "auto":
        p = prof.by_key(key)
        return bool(getattr(p, "bilingual_text_encoder", False)) if p else True
    run = K.try_import("cardforge.art.run")
    if run is not None:
        try:
            models = (run.probe(host=_host(req), timeout=4) or {}).get("models") or {}
            chosen = prof.detect(models)
            if chosen is not None:
                return bool(getattr(chosen, "bilingual_text_encoder", False))
        except Exception:                               # noqa: BLE001
            pass
    return True


def _request_from(req: Request, spec) -> ArtRequest:
    payload = req.arg("request")
    if isinstance(payload, dict):
        ar = ArtRequest(**{k: v for k, v in payload.items()
                          if k in ArtRequest.__dataclass_fields__})
    else:
        ar = ArtRequest()
    ar.card_id = int(getattr(spec, "id", 0) or 0)
    ar.archetype = str(getattr(spec, "archetype", "") or "")
    for k in ("subject", "background", "style", "extra_positive", "extra_negative",
              "preset", "profile", "seed", "count", "steps", "cfg",
              "sampler", "scheduler", "cutout_bg"):
        v = req.arg(k)
        if v is not None and str(v) != "":
            cur = getattr(ar, k)
            try:
                setattr(ar, k, type(cur)(v) if not isinstance(cur, bool) else cur)
            except Exception:
                setattr(ar, k, v)
    for k in ("upscale", "remove_bg", "layers", "cutout_invert"):
        v = req.arg(k)
        if v is not None:
            setattr(ar, k, v if isinstance(v, bool)
                    else str(v).lower() in ("1", "true", "yes", "on"))
    for k in ("loras", "style_refs"):
        v = req.arg(k)
        if isinstance(v, list):
            setattr(ar, k, [str(x) for x in v])
    if not ar.subject:
        ar.subject = str(getattr(spec, "display_name", "") or "") or "角色"
    # 不覆盖用户在界面上已经排好的系列上下文
    if req.arg("series_style") and isinstance(ar.series_context, dict):
        ar.series_context["series_style"] = str(req.arg("series_style"))
    return ar


def _result_dict(res) -> dict:
    out: dict[str, Any] = {"ok": bool(getattr(res, "ok", False)),
                           "images": list(getattr(res, "images", []) or []),
                           "meta": dict(getattr(res, "meta", {}) or {}),
                           "error": getattr(res, "error", "") or "",
                           "hint": getattr(res, "hint", "") or "",
                           "took_ms": getattr(res, "took_ms", 0)}
    # 图片给浏览器要经文件接口，别直接暴露绝对路径
    out["urls"] = ["/api/files/" + _rel_of(p) for p in out["images"]]
    if getattr(res, "workflow", None):
        out["workflow_nodes"] = len(res.workflow) if isinstance(res.workflow, dict) else 0
    return out


def _rel_of(p: Any) -> str:
    try:
        return paths.rel(Path(p)).replace("\\", "/")
    except Exception:
        return str(p).replace("\\", "/")


def _profile_row(p) -> dict:
    if p is None:
        return {}
    return {"key": getattr(p, "key", ""), "zh": getattr(p, "zh", ""),
            "chain": getattr(p, "chain", ""), "prompt_style": getattr(p, "prompt_style", ""),
            "bilingual_text_encoder": bool(getattr(p, "bilingual_text_encoder", False)),
            "language_line": getattr(p, "language_line", ""),
            "steps": getattr(p, "steps", 0), "cfg": getattr(p, "cfg", 0.0),
            "sampler": getattr(p, "sampler", ""), "scheduler": getattr(p, "scheduler", ""),
            "width": getattr(p, "width", 0), "height": getattr(p, "height", 0),
            "clip_skip": getattr(p, "clip_skip", None),
            "negative": getattr(p, "negative", ""), "notes": getattr(p, "notes", "")}


def _comfy_error(e: Exception) -> errors.CardForgeError:
    if isinstance(e, errors.CardForgeError):
        return e
    return errors.ComfyError(f"ComfyUI 调用失败：{e}",
                             "先跑 python -m cardforge doctor 看 ComfyUI 是否在线",
                             kind="offline")


def _ascii_name(s: str) -> str:
    keep = [ch for ch in str(s) if ch.isalnum() or ch in "-_."]
    return "".join(keep)[:64] or "workflow"


def _load_arch(name: str):
    from ..pool import repo
    try:
        return repo.load_archetype(name)
    except Exception:
        return None


def _load_card(cid: int, name: str = ""):
    from ..pool import repo
    try:
        return repo.load_card(int(cid), name)
    except Exception:
        return None


def _rows(name: str) -> list[dict]:
    from ..pool import repo
    try:
        return repo.list_cards(name)
    except Exception:
        return []
