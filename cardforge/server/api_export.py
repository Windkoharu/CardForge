"""``/api/export/*`` —— 导出包、自检、一键安装。

这一段是「能上牌桌」的收口，所以界面必须把**装了哪、备份在哪、怎么回退**
说清楚。安装永远先 ``dry_run`` 出清单，用户点头才真写。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core import errors, paths
from ..pool import repo
from . import kernel as K
from .http import Request, Response

__all__ = ["register"]


def register(app) -> None:

    @app.get("/api/export/packages")
    def export_packages(req: Request) -> dict:
        """已有的导出包列表（界面「导入 EDOPro」页的入口）。"""
        root = Path(paths.EXPORT_DIR)
        out: list[dict] = []
        if root.is_dir():
            for d in sorted(root.iterdir()):
                if not d.is_dir() or d.name.startswith("."):
                    continue
                cdb = list(d.glob("*.cdb"))
                scripts = list((d / "script").glob("c*.lua")) if (d / "script").is_dir() else []
                pics = list((d / "pics").glob("*")) if (d / "pics").is_dir() else []
                out.append({"name": d.name, "path": paths.rel(d),
                            "cdb": [p.name for p in cdb], "n_scripts": len(scripts),
                            "n_pics": len(pics),
                            "strings_conf": (d / "strings.conf").exists()})
        return {"ok": True, "dir": paths.rel(root), "packages": out}

    @app.post("/api/export/build")
    def export_build(req: Request) -> dict:
        name = req.str_arg("name", "CardForge")
        cards = _cards_of(req)
        if not cards:
            raise errors.CardForgeError("没有可导出的卡",
                                        "带上 card=<卡号> / archetype=<系列名>，"
                                        "或先在界面上勾选取中范围")
        langs = _langs_of(req)
        ex = K.require("cardforge.export.expansions", "导出模块")
        out_dir = Path(req.str_arg("out_dir") or (paths.EXPORT_DIR / _slug(name)))
        try:
            res = ex.build(cards, out_dir, name=name, langs=langs,
                           copy_pics=req.bool_arg("copy_pics", True),
                           setnames=_dict_arg(req, "setnames"),
                           counters=_dict_arg(req, "counters"),
                           counters_alias=_dict_arg(req, "counters_alias"),
                           use_disk_scripts=req.bool_arg("use_disk_scripts", False))
        except errors.CardForgeError:
            raise
        except Exception as e:
            raise errors.CardForgeError(f"导出失败：{e}",
                                        "先看 /api/export/verify 报什么，"
                                        "再确认卡号是否 >= 210000000") from e
        res = _jsonable(res)
        issues: list[dict] = []
        if req.bool_arg("verify", True):
            issues = _verify(out_dir)
        gates5: dict[str, Any] = {}
        if req.bool_arg("gate5", True):
            g5 = K.soft_call("cardforge.pipeline.gates", "g5_export", str(out_dir),
                             label="G5 导出自检")
            if g5.get("ok"):
                rep = g5["value"]
                gates5 = rep.to_dict() if hasattr(rep, "to_dict") else rep
        return {"ok": True, "pack_dir": paths.rel(out_dir), "stats": res,
                "issues": issues, "g5": gates5,
                "next": "确认无误后 POST /api/export/install?dry_run=1 看会写哪些文件"}

    @app.get("/api/export/verify")
    def export_verify(req: Request) -> dict:
        pack = req.str_arg("pack_dir") or _default_pack(req)
        if not Path(pack).exists():
            raise errors.CardForgeError(f"导出包目录不存在：{pack}",
                                         "先 POST /api/export/build")
        issues = _verify(pack, check_official=req.bool_arg("check_official", True))
        ex = K.try_import("cardforge.export.expansions")
        tree = []
        stats = {}
        if ex is not None:
            try:
                tree = ex.file_tree(pack)
            except Exception:
                pass
            fn = getattr(ex, "pack_stats", None)
            if callable(fn):
                try:
                    stats = _jsonable(fn(pack))
                except Exception:
                    pass
        return {"ok": not any(i.get("level") == "ERROR" for i in issues),
                "pack_dir": pack, "issues": issues, "stats": stats,
                "files": tree[:400],
                "summary": _issue_summary(issues)}

    @app.get("/api/export/targets")
    def export_targets(req: Request) -> dict:
        """探测 EDOPro 安装目录（跨平台）。"""
        inst = K.require("cardforge.export.install", "EDOPro 目录探测")
        try:
            found = inst.find_edopro()
        except Exception as e:
            return {"ok": False, "targets": [], "error": str(e),
                    "hint": "手动指定 target=<EDOPro 安装目录>"}
        out = []
        for t in found:
            p = Path(t)
            out.append({"path": t, "exists": p.exists(),
                        "expansions": (p / "expansions").exists(),
                        "has_strings": (p / "config" / "strings.conf").exists()
                        or (p / "strings.conf").exists()})
        return {"ok": bool(out), "targets": out,
                "hint": "" if out else
                "没找到 EDOPro。装好之后再点安装，或直接把导出包目录手动拷进 "
                "<EDOPro>/expansions/ 也能用"}

    @app.post("/api/export/install")
    def export_install(req: Request) -> dict:
        pack = req.str_arg("pack_dir") or _default_pack(req)
        if not Path(pack).exists():
            raise errors.CardForgeError(f"导出包不存在：{pack}",
                                         "先 POST /api/export/build")
        target = req.str_arg("target") or None
        dry = req.bool_arg("dry_run", True)
        inst = K.require("cardforge.export.install", "安装模块")
        try:
            res = inst.install(pack, target, dry_run=dry,
                               merge_strings=req.bool_arg("merge_strings", True),
                               backup=req.bool_arg("backup", True))
        except errors.CardForgeError:
            raise
        except Exception as e:
            raise errors.CardForgeError(f"安装失败：{e}",
                                        "先跑 dry_run 看清单；权限问题多半是"
                                        "EDOPro 装在 Program Files 需要管理员") from e
        res = _jsonable(res)
        if dry:
            res["hint"] = ("这是预演，**什么都没写**。确认 will_write 的清单没问题，"
                           "再去掉 dry_run 真装。原有 expansions 会被备份到 "
                           ".cardforge_backup/")
        else:
            res["hint"] = ("装好了。重启 EDOPro 后在卡组编辑器里能看到；"
                           "看不到就检查卡号是否 >= 210000000")
        return {"ok": True, "dry_run": dry, "result": res}

    @app.post("/api/export/zip")
    def export_zip(req: Request) -> dict:
        pack = req.str_arg("pack_dir") or _default_pack(req)
        if not Path(pack).exists():
            raise errors.CardForgeError(f"导出包不存在：{pack}", "先构建")
        inst = K.require("cardforge.export.install", "打包模块")
        try:
            z = inst.make_repo_pack(pack, req.str_arg("out_zip") or None,
                                    name=req.str_arg("name"), url=req.str_arg("url"))
        except Exception as e:
            raise errors.CardForgeError(f"打包失败：{e}", "检查磁盘空间与 OUT 目录权限") from e
        return {"ok": True, "zip": paths.rel(Path(z)),
                "config_block": inst.repo_config_block(Path(z).stem,
                                                      req.str_arg("url") or ""),
                "hint": "把这个 zip 传到仓库地址，再把 config_block 填进"
                        " config/user_configs.json，别人就能一键更新"}

    @app.get("/api/export/mdpro3/detect")
    def mdpro3_detect(req: Request) -> dict:
        """探测本机 MDPro3 / MDPro4 客户端。``?deep=1`` 多扫一层目录。"""
        m = K.require("cardforge.export.mdpro3", "MDPro3 导出")
        try:
            found = m.detect(deep=req.bool_arg("deep"))
        except Exception as e:
            return {"ok": False, "clients": [], "error": f"{type(e).__name__}: {e}",
                    "hint": "用 mdpro3_path 手动指定客户端目录"}
        return {"ok": bool(found), "clients": found,
                "hint": "" if found else
                        "没找到 MDPro3。不影响导出 —— .ypk 可以在游戏里"
                        "「导入导出 → 导入」手动选文件，探测只是为了帮你查撞号"}

    @app.post("/api/export/mdpro3/build")
    def mdpro3_build(req: Request) -> dict:
        """产出 MDPro3 的 ``.ypk`` 扩展卡包。

        注意：**只写 workspace/out/，不碰客户端目录**。MDPro3 的
        ``Data/script.zip`` 与官方 cdb 会被「更新先行卡」整体覆盖，
        写进去等于放在会被冲掉的路径上；导入这一步由用户在游戏里点一下，
        而且「清空扩展卡」能整体回退。
        """
        m = K.require("cardforge.export.mdpro3", "MDPro3 导出")
        cards = _cards_of(req)
        if not cards:
            raise errors.CardForgeError("没有可打包的卡",
                                        "带上 card=<卡号> / archetype=<系列名>")
        deck = None
        dn = req.str_arg("deck")
        if dn:
            deck = repo.load_deck(dn)
        out = req.str_arg("out") or str(paths.OUT / f"{_slug(req.str_arg('name', 'CardForge'))}.ypk")
        try:
            res = m.build(cards, out, name=req.str_arg("name", "CardForge"),
                          author=req.str_arg("author"),
                          langs=_langs_of(req), deck=deck,
                          render_pics=req.bool_arg("render_pics", True))
        except errors.CardForgeError:
            raise
        except Exception as e:
            raise errors.CardForgeError(f"打包失败：{e}",
                                        "确认输出目录可写、磁盘空间充足") from e
        rep = [i.to_dict() for i in m.verify(res["path"], deep=req.bool_arg("deep", False))]
        res["verify"] = rep
        res["download"] = "/api/files/" + res["rel"].replace("\\", "/")
        res["filename"] = Path(res["rel"]).name
        res["ok"] = res["ok"] and not any(i["level"] == "ERROR" for i in rep)
        return res

    @app.get("/api/export/mdpro3/verify")
    def mdpro3_verify(req: Request) -> dict:
        m = K.require("cardforge.export.mdpro3", "MDPro3 导出")
        p = req.str_arg("path")
        if not p:
            raise errors.SpecError("要指定 path=<.ypk 路径>", "从构建结果里拿 rel 字段")
        issues = [i.to_dict() for i in m.verify(p, deep=req.bool_arg("deep", False))]
        return {"ok": not any(i["level"] == "ERROR" for i in issues),
                "path": p, "issues": issues, "deep": req.bool_arg("deep", False),
                "hint": m.import_hint(p)}

    @app.get("/api/export/strings")
    def export_strings(req: Request) -> dict:
        """看/预览 strings.conf（系列名与计数器名的官方载体）。"""
        st = K.require("cardforge.export.strings", "strings.conf 模块")
        payload = {"setnames": _dict_arg(req, "setnames"),
                   "counters": _dict_arg(req, "counters"),
                   "counters_alias": _dict_arg(req, "counters_alias")}
        try:
            text = st.render(**{k: v for k, v in payload.items() if v})
        except Exception as e:
            raise errors.CardForgeError(f"strings.conf 渲染失败：{e}",
                                        "setnames 的键要能写成 0x… 形式") from e
        return {"ok": True, "text": text,
                "note": "EDOPro 用它把 setcode 显示成本家字段名；"
                        "缺这一行，游戏里卡名后面的字段会显示成十六进制"}


# ══════════════════════════════════════════════════════════════════════
def _verify(pack: str, *, check_official: bool = True) -> list[dict]:
    ex = K.try_import("cardforge.export.expansions")
    if ex is None:
        return [{"gate": "G5", "code": "G5_NO_MODULE", "level": "ERROR",
                 "message": "导出模块不可用", "hint": "确认 cardforge/export/ 完整"}]
    try:
        issues = ex.verify(pack, official=K.official(), check_official=check_official)
    except Exception as e:
        return [{"gate": "G5", "code": "G5_INTERNAL", "level": "ERROR",
                 "message": f"自检执行失败：{e}", "hint": "反馈此问题"}]
    return [i.to_dict() if hasattr(i, "to_dict") else dict(i) for i in (issues or [])]


def _issue_summary(issues: list[dict]) -> str:
    n = {"ERROR": 0, "WARN": 0, "INFO": 0}
    for i in issues:
        lv = str(i.get("level", "INFO"))
        n[lv] = n.get(lv, 0) + 1
    parts = [f"{k} {v}" for k, v in n.items() if v]
    if not parts:
        return "自检通过，没有问题"
    line = " · ".join(parts)
    if n["ERROR"]:
        line += "（有 ERROR 时**不要**直接进游戏，先修）"
    return line


def _cards_of(req: Request) -> list:
    cid = req.arg("card")
    name = req.str_arg("archetype")
    ids = req.arg("ids")
    specs: list = []
    if cid is not None:
        specs.append(K.load_spec(int(cid), req.str_arg("archetype")))
    if isinstance(ids, list):
        specs.extend(K.load_spec(int(i)) for i in ids)
    if name:
        for row in repo.list_cards(name):
            try:
                s = repo.load_card(row["id"], name)
            except Exception:
                s = None
            if s is not None:
                specs.append(s)
    if not specs:
        specs = [s for s in (repo.load_card(r["id"]) for r in repo.list_cards())
                 if s is not None]
        return specs
    # 去重（同一张卡可能被 card 和 archetype 各带一次）
    seen: dict[int, Any] = {}
    for s in specs:
        seen[int(s.id)] = s
    return list(seen.values())


def _langs_of(req: Request) -> tuple[str, ...]:
    from ..core.enums import LANGS
    raw = req.arg("langs")
    if isinstance(raw, list):
        langs = [str(x) for x in raw]
    else:
        langs = [x.strip() for x in str(raw or "zh_cn").split(",") if x.strip()]
    langs = langs or ["zh_cn"]
    bad = [x for x in langs if x not in LANGS]
    if bad:
        raise errors.SpecError(f"不支持的语言：{'、'.join(bad)}", f"可用：{'、'.join(LANGS)}")
    return tuple(langs)


def _dict_arg(req: Request, key: str):
    v = req.arg(key)
    if v is None or v == "":
        return None
    if isinstance(v, dict):
        return v
    if isinstance(v, str):
        import json
        try:
            parsed = json.loads(v)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None
    return None


def _default_pack(req: Request) -> str:
    name = req.str_arg("name")
    if name:
        return str(paths.EXPORT_DIR / _slug(name))
    d = Path(paths.EXPORT_DIR)
    if d.is_dir():
        subs = [p for p in sorted(d.iterdir()) if p.is_dir() and not p.name.startswith(".")]
        if subs:
            return str(subs[-1])
    return str(d)


def _slug(s: str) -> str:
    keep = [ch for ch in str(s or "CardForge") if ch.isalnum() or ch in "-_"]
    return "".join(keep)[:48] or "CardForge"


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, Path):
        return paths.rel(obj)
    to_dict = getattr(obj, "to_dict", None)
    if callable(to_dict):
        try:
            return _jsonable(to_dict())
        except Exception:
            pass
    return str(obj)
