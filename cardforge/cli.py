"""CardForge 命令行内核。

**GUI 是壳，CLI 是芯。** 网页界面上每个按钮背后调用的就是这里的子命令；
同时它也是自动化接口（批量造卡、CI 校验、被 AI agent 直接调用）。

用法::

    python -m cardforge doctor                  # 环境自检
    python -m cardforge serve                   # 启动图形界面
    python -m cardforge render --card 210000011 --rarity prismatic_secret --fullart art_over
    python -m cardforge render --demo            # 不需要任何数据，直接渲一张演示卡
    python -m cardforge card lint --card 210000011
    python -m cardforge export --install
    python -m cardforge ask "帮我看看这张卡的打点合不合理"

所有子命令都支持 ``--json`` 输出机器可读结果。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable, Optional

# 允许 `python cardforge/cli.py` 直接运行
if __package__ in (None, ""):  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "cardforge"

from . import __version__                      # noqa: E402
from .core import console, errors, paths       # noqa: E402
from .core.enums import FULL_ART_MODES, FRAMES, LANGS, RARITIES  # noqa: E402
from .core.models import CardSpec, RenderOptions, FullArtOptions  # noqa: E402
from .core.progress import Progress, enabled_by_default  # noqa: E402

BANNER = r"""
   ______            __ ______
  / ____/___ ______/ // ____/___  _________ ____
 / /   / __ `/ ___/ // /_  / __ \/ ___/ __ `/ _ \
/ /___/ /_/ / /  / // __/ / /_/ / /  / /_/ /  __/
\____/\__,_/_/  /_//_/    \____/_/   \__, /\___/
                                    /____/
  卡锻 2.0 · 跨平台 AI 游戏王 DIY 工坊
"""


# ══════════════════════════════════════════════════════════════════════
#  输出助手
# ══════════════════════════════════════════════════════════════════════
class Out:
    """统一输出：``--json`` 时只输出 JSON，否则输出人读文本。

    所有写操作走 :func:`cardforge.core.console.eprint` 同款的**安全写入**，
    因此被 GUI / 测试直接实例化时也不会因为控制台是 GBK 而崩。
    """

    def __init__(self, as_json: bool = False, quiet: bool = False):
        self.json = as_json
        self.quiet = quiet
        console.setup()

    @staticmethod
    def _write(text: str) -> None:
        console.eprint(text, file=sys.stdout, end="\n")

    def say(self, *a) -> None:
        if not self.json and not self.quiet:
            self._write(" ".join(str(x) for x in a))

    def emit(self, data) -> None:
        if self.json:
            self._write(json.dumps(data, ensure_ascii=False, indent=2, default=str))

    def ok(self, msg: str) -> None:
        if not self.json and not self.quiet:
            self._write(f"  [OK] {msg}")

    def warn(self, msg: str) -> None:
        if not self.json and not self.quiet:
            self._write(f"  [!]  {msg}")

    def bad(self, msg: str) -> None:
        if not self.json and not self.quiet:
            self._write(f"  [X]  {msg}")


def _die(e: Exception, as_json: bool = False) -> int:
    if as_json and isinstance(e, errors.CardForgeError):
        Out._write(json.dumps(e.to_dict(), ensure_ascii=False, indent=2))
    else:
        console.eprint(f"\n  [X] {e}\n", file=sys.stderr)
        if not isinstance(e, errors.CardForgeError):
            # 非本工程异常：把类型带上，方便定位真正的缺陷
            console.eprint(f"      （{type(e).__name__}）\n", file=sys.stderr)
    return 1


# ══════════════════════════════════════════════════════════════════════
#  doctor
# ══════════════════════════════════════════════════════════════════════
def doctor_report(*, on_step: Optional[Callable[[str], None]] = None) -> dict:
    """环境自检的**唯一实现**。

    CLI 的 ``doctor`` 与 GUI 的 ``/api/doctor`` 都读它 —— 判定逻辑只有一份，
    打印是调用方的事。否则两个入口会各自漂移（界面上说引擎可用、命令行说不可用
    是最难查的那类 bug）。

    ``on_step(name)`` 会在**每一个检查项开始前**被调用 —— 启动进度条靠它做到
    「进度跟着真实步骤走」（``launch`` 命令用它，纯 doctor 不用）。
    """
    report: dict = {"version": __version__, "python": sys.version.split()[0],
                    "platform": sys.platform, "paths": paths.describe(),
                    "levels": {"L0-data": True}, "checks": []}

    def check(name: str, ok: bool, detail: str, hint: str = "", level: str = "") -> None:
        if on_step is not None:
            try:
                on_step(name)
            except Exception:      # 进度回调坏了不能影响自检
                pass
        report["checks"].append({"name": name, "ok": bool(ok), "detail": detail,
                                 "hint": hint, "level": level})

    # L0 数据层
    created = paths.ensure_dirs()
    report["created_dirs"] = len(created)
    check("工作区", True, f"{paths.rel(paths.WORKSPACE)}"
                         f"{'（已创建 ' + str(len(created)) + ' 个目录）' if created else ''}")
    check("内置数据", paths.DATA.exists(), paths.rel(paths.DATA))
    check("卡框素材", (paths.ASSETS / "frame").exists(),
          f"{paths.rel(paths.ASSETS / 'frame')}", "素材缺失时渲染器会回退到程序化框体",
          level="warn")
    check("知识库", paths.KNOWLEDGE.exists(), paths.rel(paths.KNOWLEDGE), level="warn")

    # L1 渲染层
    try:
        from .render import compositor
        caps = compositor.capabilities()
        report["levels"]["L1-render"] = bool(caps.get("L1_render"))
        check("Pillow", bool(caps.get("pillow")), "已安装" if caps.get("pillow") else "未安装",
              "pip install Pillow（缺失时只能用浏览器端矢量预览）")
        check("排版引擎", bool(caps.get("text_engine")),
              "可用" if caps.get("text_engine") else "不可用", "")
        fd = caps.get("font_diagnose") or {}
        roles = fd.get("roles") or {}
        # fonts.diagnose().roles[role] = {path, absolute, source, fallback, ...}
        # 判"可用"的标准：解析到了路径且文件真的在（不看 ok 字段，它不存在）
        def _role_ok(v) -> bool:
            if not isinstance(v, dict):
                return bool(v)
            src = str(v.get("source") or "")
            p = v.get("absolute") or v.get("path") or ""
            return bool(p) and src not in ("", "missing", "none") and (
                v.get("asset_exists", True) or "fallback" in src or src.startswith("system"))

        ok_roles = [k for k, v in roles.items() if _role_ok(v)]
        n_ok = len(ok_roles)
        check("字体", n_ok > 0, f"{n_ok}/{len(roles) or '?'} 个角色解析成功"
                                + (f"（{fd.get('assets', '')}）" if n_ok else ""),
              "缺字体时中文会显示成方框", level="warn")
        report["font_source"] = {k: (v.get("source") if isinstance(v, dict) else str(v))
                                 for k, v in list(roles.items())[:8]}
    except Exception as e:
        report["levels"]["L1-render"] = False
        check("渲染层", False, f"导入失败：{e}", "检查 cardforge/render/ 是否完整")

    # L2 出图层
    try:
        from .art import client as ac
        c = ac.ComfyClient()
        alive = c.alive()
        report["levels"]["L2-art"] = bool(alive)
        detail = "已连接 127.0.0.1:8188" if alive else "未检测到 ComfyUI"
        check("ComfyUI", alive, detail,
              "启动 ComfyUI 后即可用本地模型出图（不影响其他功能）", level="warn")
        if alive:
            m = c.models()
            report["comfy_models"] = {k: len(v) for k, v in m.items()}
            report["comfy_model_names"] = {k: list(v)[:40] for k, v in m.items()}
            check("本地模型", True,
                  "，".join(f"{k} {len(v)}" for k, v in m.items()))
    except Exception as e:
        report["levels"]["L2-art"] = False
        check("ComfyUI", False, f"模块或服务不可用：{e}", "此为可选能力", level="warn")

    # LLM 接入（可选层 —— 没配照样能造卡，艾莉娅走规则通路）
    try:
        from .assistant import llm_config as LC
        desc = LC.describe_active()
        report["llm"] = desc
        if desc.get("active"):
            pr = LC.probe()
            report["llm_probe"] = {k: pr.get(k) for k in ("ok", "ms", "error", "hint")}
            report["levels"]["LLM"] = bool(pr.get("ok"))
            check("LLM 接入", bool(pr.get("ok")),
                  f"{desc['active']} · {desc.get('base_url', '')}"
                  + (f" · {pr.get('ms')}ms" if pr.get("ok") else ""),
                  "" if pr.get("ok") else (pr.get("hint") or str(pr.get("error") or "不可达")),
                  level="warn")
        else:
            report["levels"]["LLM"] = False
            check("LLM 接入", False, "未配置（艾莉娅走规则通路，功能不缺失）",
                  "cardforge llm preset lmstudio 一键接本机；云端 Key 见 llm set", level="warn")
    except Exception as e:
        report["levels"]["LLM"] = False
        check("LLM 接入", False, f"配置模块异常：{e}", level="warn")

    # L3 对局层
    try:
        from .duel import engine as de
        st = de.detect()
        lv = getattr(st, "level", "static")
        report["levels"]["L3-duel"] = lv
        check("对局引擎", lv == "ocgcore",
              getattr(st, "reason", "") or lv,
              getattr(st, "hint", "把 ocgcore 放到 vendor/engine/ 即可启用实跑验证"),
              level="warn")
    except Exception as e:
        report["levels"]["L3-duel"] = "static"
        check("对局引擎", False, f"模块不可用：{e}", "缺引擎时 G3 会降级为静态校验",
              level="warn")

    # 卡池与门
    try:
        from .pipeline import gates as G
        caps = G.capabilities()
        report["gates"] = caps
        check("官方卡池", bool(caps.get("official_pool")),
              "已加载" if caps.get("official_pool") else "未找到 vendor/data/cards_zh.cdb",
              "缺失时字段查重与卡号冲突检查会跳过", level="warn")
        check("质量门", all(caps.get(g) for g in ("G1", "G2", "G4", "G5")),
              "，".join(f"{g}{'✓' if caps.get(g) else '×'}"
                        for g in ("G1", "G2", "G4", "G5")),
              "缺哪个门就修哪个门；G3 依赖对局引擎，缺了会诚实降级", level="warn")
    except Exception as e:
        check("质量门", False, f"导入失败：{e}", "")

    lv = report["levels"]
    report["levels_summary"] = (
        f"L0 数据 ✓ · L1 渲染 {'✓' if lv.get('L1-render') else '×'}"
        f" · L2 出图 {'✓' if lv.get('L2-art') else '×'}"
        f" · L3 对局 {'✓' if lv.get('L3-duel') == 'ocgcore' else '×（降级为静态校验）'}"
        f" · LLM {'✓ ' + report.get('llm', {}).get('active', '') if lv.get('LLM') else '×（规则通路）'}")
    report["next_step"] = ("python -m cardforge serve   →  打开 "
                           f"http://127.0.0.1:{8790}")
    return report


def cmd_doctor(args) -> int:
    """把 :func:`doctor_report` 打印成人读文本（或原样吐 JSON）。"""
    o = Out(args.json)
    report = doctor_report()
    o.say(BANNER)
    o.say(f"CardForge {report['version']}  ·  Python {report['python']}"
          f"  ·  {report['platform']}")
    o.say("─" * 68)
    for c in report["checks"]:
        (o.ok if c["ok"] else (o.warn if c["level"] == "warn" else o.bad))(
            f"{c['name']}：{c['detail']}")
        if not c["ok"] and c["hint"] and not o.json:
            o.say(f"        → {c['hint']}")
    o.say("─" * 68)
    o.say("能力层级：" + report.get("levels_summary", ""))
    o.say("下一步：" + report.get("next_step", ""))
    o.emit(report)
    return 0


# ══════════════════════════════════════════════════════════════════════
#  serve
# ══════════════════════════════════════════════════════════════════════
def cmd_serve(args) -> int:
    o = Out(args.json, args.quiet)
    try:
        from .server import app as srv
    except Exception as e:
        return _die(errors.EnvError(
            f"Web 服务模块不可用：{e}",
            "确认 cardforge/server/ 完整；或先用 CLI 子命令"), args.json)
    o.say(BANNER)
    # 注意：返回码要透传 —— 老版本吞掉 run() 的结果，端口起不来时
    # 启动.bat 拿到 errorlevel 0、不 pause，窗口一闪而过（谁都看不见错误）。
    return srv.run(host=args.host, port=args.port, open_browser=not args.no_browser)


# ══════════════════════════════════════════════════════════════════════
#  launch —— 「自检 + 起服务」合成一条进度流（双击启动走这条）
# ══════════════════════════════════════════════════════════════════════
def cmd_launch(args) -> int:
    """一键启动：带**真实进度条**地走完 自检 → 绑定端口 → 就绪 → 打开浏览器。

    与 ``doctor`` + ``serve`` 的区别只有一个：那是两段输出、中间没有任何进度感；
    这里把两边都挂在同一条进度条上 —— 进度条跟着真实步骤走（自检的每个检查项、
    端口绑定、服务就绪），不演戏。

    ``--skip-check`` 跳过自检（已知环境没问题时更快）；``--quiet/--json`` 时
    自动退回普通日志（进度条只在真终端里出现）。
    """
    o = Out(args.json, args.quiet)
    quiet = bool(args.json or args.quiet)
    p = Progress("CardForge 卡锻 2.0 · 启动中",
                 enabled=False if quiet else enabled_by_default())
    o.say(BANNER)

    if not args.skip_check:
        p.sub("环境自检…")
        report = doctor_report(on_step=lambda name: p.sub(f"环境自检：{name}"))
        hard = [c for c in report["checks"] if not c["ok"] and c["level"] != "warn"]
        soft = [c for c in report["checks"] if not c["ok"] and c["level"] == "warn"]
        if hard:
            p.note("自检有硬性问题（不影响先把界面开起来，但功能会降级）：")
            for c in hard:
                p.note(f"  ✗ {c['name']}：{c['detail']}"
                       + (f"  → {c['hint']}" if c.get("hint") else ""))
        elif soft:
            p.note("自检通过（有 " + str(len(soft)) + " 项提示，不影响使用）。")
        else:
            p.note("自检通过：" + str(len(report["checks"])) + " 项全绿。")
        p.advance(0.30, "环境自检完成 · " + report.get("levels_summary", ""))
    else:
        p.advance(0.30, "已跳过环境自检（--skip-check）")

    try:
        from .server import app as srv
    except Exception as e:
        p.fail(f"Web 服务模块不可用：{e}")
        return _die(errors.EnvError(
            f"Web 服务模块不可用：{e}",
            "确认 cardforge/server/ 完整；或先用 CLI 子命令"), args.json)

    rc = srv.run(host=args.host, port=args.port,
                 open_browser=not args.no_browser, progress=p)
    if rc != 0:
        p.fail("启动失败 —— 上面有原因；窗口保持打开方便你看清楚。")
    return rc


# ══════════════════════════════════════════════════════════════════════
#  render
# ══════════════════════════════════════════════════════════════════════
def _demo_spec() -> CardSpec:
    s = CardSpec(id=210000011, name="星奏的见习指挥", frame="effect", attribute="光",
                 race="魔法师族", level=4, atk=1600, dfd=1200,
                 archetype="星奏", setcode="0x1001")
    s.effects = []
    s.text_i18n = {"zh_cn": "①：这张卡召唤成功时才能发动。从卡组把1张「星奏」卡加入手卡。"
                            "②：1回合1次，自己主要阶段才能发动。从手卡把1只「星奏」怪兽"
                            "特殊召唤。"}
    s.render = RenderOptions(rarity="prismatic_secret", set_number="CF01-JP011")
    return s


def cmd_render(args) -> int:
    o = Out(args.json, args.quiet)
    try:
        from .render import compositor
    except Exception as e:
        return _die(errors.EnvError(f"渲染器不可用：{e}", "pip install Pillow"), args.json)

    # 取卡
    spec = None
    if args.demo:
        spec = _demo_spec()
    elif args.card:
        try:
            from .pool import repo
            spec = repo.load_card(int(args.card), args.archetype or "")
        except Exception:
            spec = None
        if spec is None:
            # 退一步：直接读 workspace/cards/<id>.json
            p = paths.CARDS / f"{args.card}.json"
            if p.exists():
                spec = CardSpec.from_dict(json.loads(p.read_text(encoding="utf-8")))
        if spec is None:
            return _die(errors.SpecError(f"找不到卡片 {args.card}",
                                         "用 --demo 渲一张演示卡，或先 card new 建卡"),
                        args.json)
    else:
        spec = _demo_spec()
        o.warn("未指定 --card，已渲染演示卡（用 --demo 可显式指定）")

    # 覆盖渲染选项
    if args.rarity:
        spec.render.rarity = args.rarity
    if args.lang:
        spec.render.lang_text = spec.render.lang_name = args.lang
    if args.fullart:
        spec.render.fullart = FullArtOptions(mode=args.fullart)
    if getattr(args, "bezel", None) is not None:
        spec.render.bezel = float(args.bezel)
    if args.set_number:
        spec.render.set_number = args.set_number

    # 插画
    art = None
    if args.art:
        try:
            from PIL import Image
            art = Image.open(args.art)
        except Exception as e:
            o.warn(f"插画读取失败，改用无图渲染：{e}")

    # 主体出框档需要分层卡图（背景 + 带 alpha 的主体），从资产库当前版取
    layers = {}
    if spec.render.fullart.mode == "subject_bleed":
        try:
            from .art import library as AL
            got = AL.load_for_render(spec.id, spec.archetype or "") or {}
            for role in ("background", "subject"):
                if got.get(role) is not None:
                    layers[role] = got[role].convert("RGBA")
            if "background" not in layers:
                o.warn("主体出框档要分层卡图，但这张卡没有分层版本"
                       "（用「分层出图」重新生成）→ 回落到普通卡图")
        except Exception as e:
            o.warn(f"读取分层卡图失败：{e}")

    sizes = args.size or ["share"]
    out_dir = Path(args.out) if args.out else paths.OUT
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        written = compositor.export_card(spec, art, out_dir, sizes=sizes,
                                         fmt=args.format, quality=args.quality,
                                         layers=layers)
    except Exception as e:
        return _die(errors.EnvError(f"渲染失败：{e}", "检查素材与字体"), args.json)

    for p in written:
        o.ok(f"{paths.rel(Path(p))}")
    img = compositor.render_card(spec, art, size=sizes[0], layers=layers)
    o.say(f"  卡种 {FRAMES[spec.frame].zh_cn} · 罕贵 "
          f"{RARITIES.get(spec.render.rarity, RARITIES['common']).zh_cn} · "
          f"出框 {FULL_ART_MODES[spec.render.fullart.mode].zh_cn} · "
          f"语言 {LANGS.get(spec.render.lang_text, LANGS['zh_cn']).zh_cn}")
    o.emit({"written": written, "size": list(img.size), "spec": spec.to_dict()})
    return 0


# ══════════════════════════════════════════════════════════════════════
#  card / archetype / series / deck
# ══════════════════════════════════════════════════════════════════════
def cmd_card(args) -> int:
    o = Out(args.json, args.quiet)
    action = args.action

    if action == "new":
        try:
            from .pool import repo, official as off
        except Exception as e:
            return _die(errors.EnvError(f"卡池模块不可用：{e}", ""), args.json)
        pool = None
        try:
            cls = off.OfficialPool
            for p in (paths.OFFICIAL_CDB / "cards_zh.cdb",):
                if p.exists():
                    pool = cls(str(p))
                    break
        except Exception:
            pool = None
        cid = int(args.id) if args.id else (
            pool.next_free_id(210000000) if pool is not None else 210000000)
        spec = CardSpec(id=cid, name=args.name or "未命名卡", frame=args.frame or "effect")
        spec.render = RenderOptions(set_number=args.set_number or "")
        try:
            p = repo.save_card(spec)
        except Exception as e:
            return _die(errors.CardForgeError(f"保存失败：{e}", ""), args.json)
        o.ok(f"已建立卡片 {cid}：{paths.rel(Path(p))}")
        o.emit({"id": cid, "path": str(p), "spec": spec.to_dict()})
        return 0

    if action in ("lint", "text", "script", "verify", "seal"):
        try:
            from .pool import repo
            spec = repo.load_card(int(args.card), args.archetype or "")
        except Exception:
            p = paths.CARDS / f"{args.card}.json"
            spec = (CardSpec.from_dict(json.loads(p.read_text(encoding="utf-8")))
                    if p.exists() else None)
        if spec is None:
            return _die(errors.SpecError(f"找不到卡片 {args.card}", ""), args.json)

        from .pipeline import gates
        if action == "lint":
            rep = gates.g1_balance(spec)
            o.say(f"G1 平衡审计 — {rep.summary}")
            for i in rep.issues:
                o.say(f"  [{i.level:<5}] {i.code:<26} {i.message}")
                if i.hint:
                    o.say(f"          → {i.hint}")
            o.emit(rep.to_dict())
            return 0 if rep.status in ("pass", "warn", "waived") else 1

        if action == "text":
            from .content import psct
            res = {lg: psct.compose(spec, lg) for lg in (args.lang or ["zh_cn"])}
            for lg, t in res.items():
                o.say(f"── {lg} ──\n{t}")
            o.emit(res)
            return 0

        if action == "script":
            from .content.lua import emit
            lua = emit.emit_script(spec)
            spec.lua = lua
            o.say(lua)
            o.emit({"lua": lua})
            return 0

        if action == "verify":
            rep = gates.g3_duel(spec)
            o.say(f"G3 实跑验证 — {rep.status}：{rep.summary}")
            if rep.degraded:
                o.warn(rep.degraded)
            o.emit(rep.to_dict())
            return 0 if rep.status in ("pass", "warn", "waived", "skipped") else 1

        if action == "seal":
            from .content.lua import emit as lemit
            spec.lua = spec.lua or lemit.emit_script(spec)
            spec.strings = spec.strings or lemit.emit_strings(spec)
            p = repo.save_card(spec) if "repo" in dir() else None
            o.ok(f"已入库：{spec.id}")
            o.emit({"id": spec.id, "path": str(p)})
            return 0

    o.say("可用动作：new / lint / text / script / verify / seal")
    return 0


def cmd_archetype(args) -> int:
    o = Out(args.json, args.quiet)
    from .content import design
    if args.action == "new":
        try:
            from .pool import repo
            arch = repo.load_archetype(args.name)
        except Exception:
            arch = None
        if arch is None:
            from .core.models import Archetype
            pool = None
            try:
                from .pool import official as off
                for p in (paths.OFFICIAL_CDB / "cards_zh.cdb",):
                    if p.exists():
                        pool = off.OfficialPool(str(p))
                        break
            except Exception:
                pool = None
            arch = Archetype(name=args.name,
                             setcode=args.setcode or design.suggest_setcode(pool),
                             concept=args.concept or "",
                             win_method=args.win or "BATTLE",
                             trumps=[args.trump] if args.trump else ["MAIN"],
                             target_power=args.power or "casual")
            arch.roster = design.build_roster(arch)
            try:
                from .pool import repo as r2
                p = r2.save_archetype(arch)
                o.ok(f"已建立系列「{arch.name}」setcode={arch.setcode}")
                o.emit({"archetype": arch.to_dict(), "path": str(p)})
            except Exception as e:
                o.emit(arch.to_dict())
                o.warn(f"未能落盘（{e}），以下为草案")
                o.say(json.dumps(arch.to_dict(), ensure_ascii=False, indent=2))
        else:
            o.say(json.dumps(arch.to_dict(), ensure_ascii=False, indent=2))
        return 0
    if args.action == "list":
        try:
            from .pool import repo
            items = repo.list_archetypes()
        except Exception:
            items = []
        for it in items:
            o.say(f"  {it.get('name')}  setcode={it.get('setcode')}  "
                  f"卡数={it.get('n_cards', '?')}")
        o.emit(items)
        return 0
    o.say("可用动作：new / list / show / check")
    return 0


# ══════════════════════════════════════════════════════════════════════
#  llm —— 大模型接入管理（云端 / 本地）
# ══════════════════════════════════════════════════════════════════════
def cmd_llm(args) -> int:
    """``cardforge llm …`` —— 配模型、切模型、测连通。

    设计取舍：**密钥打码后才出终端**（``list`` 不见明文）；写入动作一律
    走 :mod:`cardforge.assistant.llm_config` 的校验，坏配置当场报错、
    不落半截文件。没配过 LLM 不是错误 —— 艾莉娅走规则通路，功能不缺失。
    """
    from .assistant import llm_config as LC

    o = Out(args.json, args.quiet)
    act = getattr(args, "action", "") or "list"
    # 名字有两个入口：位置参数与 --name。后者赢（显式选项优先于隐含位置）。
    name = (getattr(args, "opt_name", "") or getattr(args, "pos_name", "") or "").strip()

    if act == "presets":
        o.say("可用预设（llm preset <名> 一键落账）：")
        for key, p in LC.PRESETS.items():
            o.say(f"  {key:<10} {p['label']:<22} {p['base_url']}")
        o.emit(LC.PRESETS)
        return 0

    if act == "list":
        items = LC.list_providers()
        if not items:
            o.say("还没有配置任何模型。")
            o.say("  本机：  cardforge llm preset lmstudio")
            o.say("  云端：  cardforge llm preset deepseek --key sk-…")
            o.say("  自定：  cardforge llm set --name my --base-url https://…/v1 --key sk-…")
        else:
            o.say(f"{'':2}{'名称':<14}{'状态':<6}{'类型':<16}{'模型':<22}端点")
            for it in items:
                mark = "●" if it["active"] else " "
                o.say(f"  {mark} {it['name']:<14}{'启用' if it['active'] else '':<6}"
                       f"{it['kind']:<16}{it['model'] or '(自动)':<22}{it['base_url']}")
                if it["masked_key"]:
                    o.say(f"    key：{it['masked_key']}   {it['note']}")
        desc = LC.describe_active()
        o.say(f"当前：{desc['detail']}")
        o.emit({"providers": items, "active": LC.active_name()})
        return 0

    if act == "preset":
        key = (args.preset or name).strip().lower()
        if key not in LC.PRESETS:
            o.bad(f"没有预设「{key}」。可用：{', '.join(LC.PRESETS)}")
            return 1
        p = LC.PRESETS[key]
        name = name or key
        try:
            LC.upsert(name, kind=p["kind"], base_url=args.base_url or p["base_url"],
                      api_key=args.key or "", model=args.model or p["model"],
                      note=p["note"], set_active=True)
        except ValueError as e:
            o.bad(str(e))
            return 1
        o.ok(f"已接入「{name}」（{p['label']}）并设为当前模型")
        # 只有**云端**预设才索要 Key —— 本机端点（127.0.0.1/localhost）大多免鉴权，
        # 以前一刀切地提示「需要 API Key」，用户会给 LM Studio 硬编一把空钥匙。
        _local = "127.0.0.1" in p["base_url"] or "localhost" in p["base_url"]
        if not (args.key or _local):
            o.warn("这个预设需要 API Key：llm set --name "
                   f"{name} --key sk-…（或先用 llm test 看通不通）")
        o.emit({"upsert": name, "active": LC.active_name()})
        return 0

    if act == "set":
        if not name:
            o.bad("--name 不能空")
            return 1
        existing_entry = next((p for p in LC.list_providers() if p["name"] == name), None)
        existing = existing_entry is not None
        # 只改想改的：没给 --base-url / --kind / --key 时沿用旧值
        # （argparse 的默认值分不清「没给」和「给了默认值」，所以默认 None）
        base = args.base_url or (existing_entry or {}).get("base_url", "")
        kind = args.kind or (existing_entry or {}).get("kind") or "openai_compat"
        try:
            LC.upsert(name, kind=kind, base_url=base,
                      api_key=args.key or "", model=args.model or "",
                      note=args.note or "", set_active=bool(args.use) or not existing)
        except ValueError as e:
            o.bad(str(e))
            return 1
        verb = "更新" if existing else "新建"
        not_switched = existing and not args.use and LC.active_name() != name
        o.ok(f"已{verb}「{name}」" + ("（未切换当前模型，加 --use 切换）"
                                    if not_switched else ""))
        o.emit({"upsert": name, "active": LC.active_name()})
        return 0

    if act == "use":
        if LC.set_active(name):
            o.ok(f"当前模型 → {name}")
            o.emit({"active": LC.active_name()})
            return 0
        o.bad(f"配置里没有「{name}」")
        return 1

    if act == "off":
        LC.use_off()
        o.ok("已关闭 LLM —— 艾莉娅回到规则通路（功能不缺失）")
        o.emit({"active": ""})
        return 0

    if act == "rm":
        if LC.remove(name):
            o.ok(f"已删除「{name}」")
            o.emit({"providers": LC.list_providers(), "active": LC.active_name()})
            return 0
        o.bad(f"配置里没有「{name}」")
        return 1

    if act == "models":
        try:
            pr = LC.probe(name or None)
        except Exception as e:
            o.bad(LC.friendly_error(e))
            return 1
        if not pr.get("ok"):
            o.bad(f"探不到模型：{pr.get('error')}")
            if pr.get("hint"):
                o.say(f"      → {pr['hint']}")
            o.emit(pr)
            return 1
        o.say(f"{pr.get('base_url')} 上的模型（{pr.get('ms')}ms）：")
        for m in pr.get("models") or []:
            o.say(f"  · {m}")
        if not pr.get("models"):
            o.warn("端点没报告模型列表；llm set --model <名> 手填")
        o.emit(pr)
        return 0

    if act == "test":
        name = name or LC.active_name()
        if not name:
            o.bad("还没有配置任何模型（先 llm preset …）")
            return 1
        o.say(f"正在测「{name}」…")
        try:
            pr = LC.probe(name)
        except Exception as e:
            o.bad(LC.friendly_error(e))
            return 1
        if pr.get("ok"):
            o.ok(f"连通 · {pr.get('ms')}ms · 模型 {pr.get('model') or '(自动)'}")
            o.say(f"  它说：{pr.get('greet', '')}")
            o.emit(pr)
            return 0
        o.bad(f"不通：{pr.get('error')}")
        if pr.get("hint"):
            o.say(f"      → {pr['hint']}")
        o.emit(pr)
        return 1

    o.say("可用动作：list / presets / preset / set / use / off / rm / models / test")
    return 0


def cmd_export(args) -> int:
    o = Out(args.json, args.quiet)
    try:
        from .export import expansions
    except Exception as e:
        return _die(errors.EnvError(f"导出模块不可用：{e}", ""), args.json)
    try:
        from .pool import repo
        cards = []
        for it in repo.list_cards(args.archetype or ""):
            c = repo.load_card(int(it["id"]), args.archetype or "")
            if c is not None:
                cards.append(c)
    except Exception as e:
        return _die(errors.EnvError(f"读取卡片失败：{e}", ""), args.json)

    if not cards:
        o.warn("没有找到任何卡片；先用 card new 建卡")
        o.emit({"cards": 0})
        return 1

    try:
        res = expansions.build(cards, args.out or None,
                               name=args.name or "CardForge",
                               langs=tuple(args.lang or ["zh_cn"]))
    except Exception as e:
        return _die(errors.CardForgeError(f"打包失败：{e}", ""), args.json)
    o.ok(f"已打包 {res.get('cards', 0)} 张卡 → {paths.rel(Path(res.get('dir', '')))}")
    for k, v in (res.get("stats") or {}).items():
        o.say(f"    {k}: {v}")

    from .pipeline import gates
    rep = gates.g5_export(res.get("dir"))
    o.say(f"G5 导出自检 — {rep.status}：{rep.summary}")
    for i in rep.issues:
        o.say(f"  [{i.level:<5}] {i.code:<24} {i.message}")
    o.emit({"build": res, "g5": rep.to_dict()})
    if rep.status == "fail":
        return 1
    if args.install:
        from .export import install as inst
        try:
            r = inst.install(res["dir"])
            o.ok("已安装到 %s，复制 %d 个文件（备份 %d，未变 %d）" % (
                r.get("target"),
                r.get("copied_count", len(r.get("copied") or [])),
                r.get("backed_up_count", 0),
                r.get("unchanged_count", 0)))
        except Exception as e:
            o.bad(f"安装失败：{e}")
            return 1
    return 0


def cmd_ask(args) -> int:
    o = Out(args.json, args.quiet)
    try:
        from .assistant import chat
    except Exception as e:
        return _die(errors.EnvError(f"助手模块不可用：{e}", ""), args.json)
    sess = chat.new_session(persona=args.persona or "professional")
    res = chat.send(sess, " ".join(args.text))
    o.say(res.get("reply", ""))
    o.emit(res)
    return 0


# ══════════════════════════════════════════════════════════════════════
#  mdpro3 —— 导出 MDPro3 / MDPro4 扩展卡包（.ypk）
# ══════════════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════════════
#  draft —— AI 起草卡文草稿（LLM 提议，内核裁决）
# ══════════════════════════════════════════════════════════════════════
def cmd_draft(args) -> int:
    """``cardforge draft "概念描述"`` —— 让配置好的大模型起草一份卡文。

    与 ``card text``（确定性模板生成）的分工：那个永远可用、只投影结构化效果；
    这个从自然语言概念自由起草，**需要先配模型**（``cardforge llm preset …``）。
    草稿只是提议：问题清单与 G1 结论全部由内核校验器产出，模型的自评不采信。
    """
    o = Out(args.json, args.quiet)
    from .assistant import draft as D

    spec = None
    if args.card:
        try:
            from .pool import repo
            spec = repo.load_card(int(args.card), args.archetype or "")
        except Exception:
            spec = None
        if spec is None:
            p = paths.CARDS / f"{args.card}.json"
            if p.exists():
                try:
                    spec = CardSpec.from_dict(json.loads(p.read_text(encoding="utf-8-sig")))
                except Exception:
                    spec = None
        if spec is None:
            return _die(errors.SpecError(
                f"找不到卡片 {args.card}",
                "换一个 --card 卡号，或不带卡号做纯概念起草"), args.json)

    concept = " ".join(args.text).strip()
    if not concept and spec is None:
        return _die(errors.SpecError(
            "概念描述是空的",
            "例如：cardforge draft \"翻转时把墓地 1 只怪兽特殊召唤的通常陷阱\""),
            args.json)

    res = D.draft(concept, spec=spec, lang=args.lang or "zh_cn",
                  with_g1=not args.no_g1)
    if not res.get("ok"):
        if res.get("degraded"):
            o.bad(res["degraded"])
            if res.get("hint"):
                o.say(f"      → {res['hint']}")
            o.emit(res)
            return 1
        return _die(errors.LLMUnavailable(res.get("error") or "起草失败",
                                          res.get("hint") or ""), args.json)

    o.say(res.get("draft") or "")
    c = res.get("counts") or {}
    model = f"{res.get('provider')}{'/' + res['model'] if res.get('model') else ''}"
    o.say(f"\n内核结论：{c.get('error', 0)} ERROR · {c.get('warn', 0)} WARN · "
          f"{c.get('info', 0)} INFO"
          f"（{model or '模型'} 只提议；以上全部由内核校验器产出）")
    for i in res.get("issues") or []:
        lvl = str(i.get("level") or "INFO").upper()
        fn = o.bad if lvl == "ERROR" else (o.warn if lvl == "WARN" else o.say)
        fn(f"{i.get('code') or '（无规则号）'} {i.get('message') or ''}")
        if i.get("hint"):
            o.say(f"      → {i['hint']}")
    if res.get("gate"):
        g = res["gate"]
        o.say(f"G1（对象是规格本身，不是草稿文字）：{g.get('status')} —— "
              f"{g.get('summary') or ''}")
    elif res.get("gate_degraded"):
        o.say(f"G1：{res['gate_degraded']}")

    if args.write:
        if spec is None:
            return _die(errors.SpecError("--write 需要 --card",
                                         "没有指定卡就不知道写回哪里"), args.json)
        lang = args.lang or "zh_cn"
        spec.text_i18n = dict(spec.text_i18n or {})
        spec.text_i18n[lang] = res.get("draft") or ""
        spec.dirty = sorted(set(list(spec.dirty or []) + ["text"]))
        spec.updated = _now_stamp()
        try:
            from .pool import repo
            p = repo.save_card(spec)
        except Exception as e:
            return _die(errors.CardForgeError(f"写回失败：{e}", ""), args.json)
        o.ok(f"已写回 {paths.rel(Path(p))}（{lang}）")

    o.emit({"draft": res.get("draft"), "issues": res.get("issues"),
            "counts": c, "gate": res.get("gate"), "provider": res.get("provider"),
            "model": res.get("model"), "written": bool(args.write)})
    return 1 if c.get("error") else 0


def _now_stamp() -> str:
    import datetime as _dt
    return _dt.datetime.now().replace(microsecond=0).isoformat()


def cmd_mdpro3(args) -> int:
    o = Out(args.json, args.quiet)
    try:
        from .export import mdpro3
    except Exception as e:
        return _die(errors.EnvError(f"MDPro3 导出模块不可用：{e}", ""), args.json)

    # 只探测客户端
    if args.detect:
        found = mdpro3.detect(deep=args.deep)
        if not found:
            o.bad("没找到 MDPro3/MDPro4 安装目录")
            o.say("      → 用 --mdpro <目录> 手动指定；或设环境变量 CARDFORGE_MDPRO")
            o.emit({"clients": []})
            return 1
        for c in found:
            o.ok(f"{c['path']}")
            o.say(f"        官方卡 {c['n_official']} · 脚本 {c['n_scripts']} · "
                  f"卡图 {c['n_pics']} · 语言包 {len(c['langs'])} · "
                  f"SavedCardSize {tuple(c['saved_size']) or '未知'}")
            for w in c["warnings"]:
                o.warn(w)
        o.emit({"clients": found})
        return 0

    # 只校验已有包
    if args.verify:
        issues = mdpro3.verify(args.verify, deep=bool(getattr(args, "deep_check", False)))
        for i in issues:
            (o.ok if False else (o.bad if i.level == "ERROR" else o.warn))(
                f"{i.code} {i.message}")
        if not issues:
            o.ok("包结构干净")
        o.emit({"issues": [i.to_dict() for i in issues]})
        return 1 if any(i.level == "ERROR" for i in issues) else 0

    try:
        from .pool import repo
        cards = []
        if args.card:
            c = repo.load_card(int(args.card))
            if c is None:
                return _die(errors.CardForgeError(f"没有卡号 {args.card}",
                                                  "先 card new 建卡"), args.json)
            cards.append(c)
        else:
            for it in repo.list_cards(args.archetype or ""):
                c = repo.load_card(int(it["id"]), args.archetype or "")
                if c is not None:
                    cards.append(c)
    except Exception as e:
        return _die(errors.EnvError(f"读取卡片失败：{e}", ""), args.json)
    if not cards:
        o.bad("没有可打包的卡")
        o.say("      → --card <卡号> 指定单张，或 --archetype <系列名> 打整个系列")
        o.emit({"cards": 0})
        return 1

    deck = None
    if args.deck:
        try:
            deck = repo.load_deck(args.deck)
        except Exception as e:
            o.warn(f"读不到卡组「{args.deck}」：{e}（继续打包，只是不带演示卡组）")

    out = args.out or str(paths.OUT / f"{args.name}.ypk")
    try:
        res = mdpro3.build(cards, out, name=args.name, author=args.author or "",
                           langs=tuple(args.lang or ["zh_cn"]), deck=deck,
                           render_pics=not args.no_pics)
    except Exception as e:
        return _die(errors.CardForgeError(f"打包失败：{e}",
                                          "确认输出目录可写"), args.json)
    o.ok(f"{res['n_cards']} 张卡 → {res['rel']}（{res['bytes']:,} 字节）")
    o.say(f"        脚本 {res['n_scripts']} · 卡图 {res['n_pics']}"
          f"（现场渲 {res['n_rendered']}）· 演示卡组 {res['n_deck']}")
    if res["cards_without_script"]:
        o.warn(f"这些卡没有脚本，进游戏只能看不能用：{res['cards_without_script']}")
    bad = [i for i in res["issues"] if i["level"] == "ERROR"]
    for i in res["issues"]:
        (o.bad if i.level == "ERROR" else o.warn)(f"{i.code} {i.message}")
    rep = mdpro3.verify(res["path"], deep=bool(getattr(args, "deep_check", False)))
    o.say(f"包自检 — {'通过' if not any(i.level=='ERROR' for i in rep) else '有错误'}"
          f"（{len(rep)} 条）")
    for i in rep:
        (o.bad if i.level == "ERROR" else o.warn)(f"{i.code} {i.message}")
    o.say("")
    o.say("  " + res["hint"])
    o.emit({"build": res, "verify": [i.to_dict() for i in rep]})
    return 1 if bad or any(i.level == "ERROR" for i in rep) else 0


# ══════════════════════════════════════════════════════════════════════
#  参数表
# ══════════════════════════════════════════════════════════════════════
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cardforge", description="CardForge 卡锻 · 跨平台 AI 游戏王 DIY 工坊",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="所有子命令都支持 --json；完整文档见 docs/ 目录。")
    p.add_argument("--version", action="version", version=f"CardForge {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--json", action="store_true", help="输出机器可读 JSON")
        sp.add_argument("--quiet", action="store_true", help="安静模式")
        return sp

    common(sub.add_parser("doctor", help="环境自检")).set_defaults(func=cmd_doctor)

    sp = common(sub.add_parser("launch", help="一键启动：自检 + 起服务（带启动进度条）"))
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8790)
    sp.add_argument("--no-browser", action="store_true", help="不要自动打开浏览器")
    sp.add_argument("--skip-check", action="store_true", help="跳过环境自检（更快）")
    sp.set_defaults(func=cmd_launch)

    sp = common(sub.add_parser("serve", help="启动图形界面"))
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8790)
    sp.add_argument("--no-browser", action="store_true", help="不要自动打开浏览器")
    sp.set_defaults(func=cmd_serve)

    sp = common(sub.add_parser("render", help="渲染卡面"))
    sp.add_argument("--card", help="卡片 id")
    sp.add_argument("--archetype", help="所属系列")
    sp.add_argument("--demo", action="store_true", help="渲染内置演示卡（无需任何数据）")
    sp.add_argument("--rarity", choices=sorted(RARITIES), help="罕贵度")
    sp.add_argument("--lang", choices=sorted(LANGS), help="卡名与卡文语言")
    sp.add_argument("--fullart", choices=sorted(FULL_ART_MODES), help="出框档位")
    sp.add_argument("--bezel", type=float, default=None,
                    help="卡图窗斜切框强度：1=官方实测（默认），0=关掉")
    sp.add_argument("--set-number", help="卡号，如 CF01-JP011")
    sp.add_argument("--art", help="插画文件路径")
    sp.add_argument("--size", action="append",
                    choices=["edopro", "compat", "share", "print300", "print", "native"],
                    help="输出尺寸（可重复）")
    sp.add_argument("--out", help="输出目录")
    sp.add_argument("--format", default="png", choices=["png", "jpg", "webp"])
    sp.add_argument("--quality", type=int, default=92)
    sp.set_defaults(func=cmd_render)

    sp = common(sub.add_parser("card", help="单卡操作"))
    sp.add_argument("action", choices=["new", "lint", "text", "script", "verify", "seal"])
    sp.add_argument("--id", type=int, help="指定卡号（默认自动分配）")
    sp.add_argument("--card", help="卡片 id")
    sp.add_argument("--name", help="卡名")
    sp.add_argument("--frame", choices=sorted(FRAMES))
    sp.add_argument("--archetype")
    sp.add_argument("--set-number")
    sp.add_argument("--lang", action="append")
    sp.set_defaults(func=cmd_card)

    sp = common(sub.add_parser("archetype", help="系列圣经"))
    sp.add_argument("action", choices=["new", "list", "show", "check"])
    sp.add_argument("--name")
    sp.add_argument("--setcode")
    sp.add_argument("--concept")
    sp.add_argument("--win", choices=["BATTLE", "EFFECT", "BURN", "MIX"])
    sp.add_argument("--trump", choices=["MAIN", "FUSION", "SYNCHRO", "XYZ", "LINK", "RITUAL"])
    sp.add_argument("--power", choices=["casual", "rogue", "competitive"])
    sp.set_defaults(func=cmd_archetype)

    sp = common(sub.add_parser("export", help="打包导出到 EDOPro"))
    sp.add_argument("--archetype")
    sp.add_argument("--name", default="CardForge")
    sp.add_argument("--lang", action="append")
    sp.add_argument("--out")
    sp.add_argument("--install", action="store_true", help="同时安装到 EDOPro")
    sp.set_defaults(func=cmd_export)

    sp = common(sub.add_parser("mdpro3", help="导出 MDPro3/MDPro4 扩展卡包 (.ypk)"))
    sp.add_argument("--card", type=int, help="只打这一张卡")
    sp.add_argument("--archetype", help="打整个系列")
    sp.add_argument("--name", default="CardForge", help="卡包名（决定文件名）")
    sp.add_argument("--author", default="", help="作者，写进包内 README")
    sp.add_argument("--lang", action="append", help="语言，可重复")
    sp.add_argument("--deck", help="附带一个已保存的卡组作为演示卡组")
    sp.add_argument("--out", help="输出 .ypk 路径")
    sp.add_argument("--no-pics", action="store_true", help="不渲染卡图（快，但游戏里没图）")
    sp.add_argument("--detect", action="store_true", help="只探测本机 MDPro 客户端")
    sp.add_argument("--deep", action="store_true", help="探测时多扫一层目录（慢）")
    sp.add_argument("--verify", help="校验一个已有的 .ypk")
    sp.add_argument("--deep-check", action="store_true",
                    help="自检时与本机客户端逐项对账（schema/卡图尺寸/撞号/编码，更慢更全）")
    sp.set_defaults(func=cmd_mdpro3)

    sp = common(sub.add_parser("ask", help="问艾莉娅"))
    sp.add_argument("text", nargs="+")
    sp.add_argument("--persona", choices=["professional", "lightnovel", "tsundere"])
    sp.set_defaults(func=cmd_ask)

    sp = common(sub.add_parser("draft", help="AI 起草卡文草稿（需先 cardforge llm 配模型）"))
    sp.add_argument("text", nargs="*", help="概念描述，如「翻转后堆墓的通常陷阱」")
    sp.add_argument("--card", help="附带一张卡：字段与效果清单喂给模型当事实底座")
    sp.add_argument("--archetype", help="--card 所属系列（可选）")
    sp.add_argument("--lang", default="zh_cn", choices=sorted(LANGS), help="目标语言")
    sp.add_argument("--write", action="store_true",
                    help="把草稿写回 --card 的卡文（需要 --card）")
    sp.add_argument("--no-g1", action="store_true", help="不跑 G1 平衡审计")
    sp.set_defaults(func=cmd_draft)

    sp = common(sub.add_parser("llm", help="大模型接入（云端/本地）：配模型、切模型、测连通"))
    sp.add_argument("action", nargs="?", default="list",
                    choices=["list", "presets", "preset", "set", "use", "off",
                             "rm", "models", "test"])
    sp.add_argument("pos_name", nargs="?", help="配置名/预设名（位置写法）")
    sp.add_argument("--name", dest="opt_name", help="配置名（选项写法，与位置等价）")
    sp.add_argument("--preset", help="预设名：lmstudio/ollama/vllm/deepseek/kimi/zhipu/qwen/openai")
    sp.add_argument("--kind", choices=["openai_compat", "ollama", "lmstudio"],
                    help="端点类型（不填=沿用旧值/openai_compat）")
    sp.add_argument("--base-url", help="端点，如 https://api.deepseek.com/v1")
    sp.add_argument("--key", help="API Key（不明文回显）")
    sp.add_argument("--model", help="模型名，留空=自动取端点第一个")
    sp.add_argument("--note", help="备注")
    sp.add_argument("--use", action="store_true", help="set 后立即切为当前模型")
    sp.set_defaults(func=cmd_llm)

    return p


def main(argv: list[str] | None = None) -> int:
    # 第一件事必须是控制台编码：中文 Windows 默认 GBK，任何一处 ✓/日文/西语
    # 都会抛 UnicodeEncodeError，表现为「软件打不开」。见 core/console.py。
    console.setup()
    if argv is None:
        argv = sys.argv[1:]
        # 无参运行（双击 CardForge.exe / 裸跑 python -m cardforge）→ 默认 launch。
        # 否则 add_subparsers(required=True) 会甩一句 usage 就退出 —— 双击场景下
        # 就是「窗口一闪、什么都没发生」（启动.bat 缺陷 #31 的同类失败模式）。
        # 只兜「完全无参」：显式给了参数却不给子命令，仍走 argparse 的明确报错。
        if not argv:
            argv = ["launch"]
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        console.eprint("\n已中断", file=sys.stderr)
        return 130
    except Exception as e:
        return _die(e, getattr(args, "json", False))


if __name__ == "__main__":
    raise SystemExit(main())
