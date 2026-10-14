"""质量门 G1–G5 —— 全流程的强制关卡。

设计原则（不可动摇）
--------------------
**五道门全部是确定性代码，不依赖任何模型。** 这是刻意设计：质量门必须可复现、
可验证，不能交给概率模型。AI 只在"表达层"参与（艾莉娅把结论翻译成人话）。

| 门 | 位置 | 检查 | 失败处理 |
|---|---|---|---|
| G1 | 规格生成后 | 平衡审计 / ATK 惯例 / HOPT / 素材条件 / 字段查重 / 号段冲突 | 告警或拦截，可强制放行但留痕 |
| G2 | 脚本生成后 | Lua 语法 / UTF-8 无 BOM / API 存在性 / Stringid↔texts 同步 | 回脚本层，或降级重试 |
| G3 | 落盘后 | 场景单测 + 整局对战 0 报错 | 无引擎时**降级为静态校验并明确标注** |
| G4 | 系列批量后 | 方言数 / 属性种族交集 / 启动路径 / 泛用素材 / 角色覆盖率 | 告警，回蓝图 |
| G5 | 导出打包后 | 文件完整性 / 编码 / 卡号冲突 / cdb 表结构 | **拦截导出** |

依赖缺失时：门返回 ``status="skipped"`` 并把原因写进 ``degraded`` —— **绝不假装通过**。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from ..core import paths
from ..core.models import Archetype, CardSpec, GateReport, Issue

GATE_ORDER = ("G1", "G2", "G3", "G4", "G5")
GATE_NAMES = {
    "G1": "平衡审计", "G2": "脚本静态检查", "G3": "实跑验证",
    "G4": "系列一致性", "G5": "导出自检",
}
#: 状态优先级（用于汇总底栏指示灯）
STATUS_RANK = {"pass": 0, "waived": 1, "skipped": 2, "warn": 3, "fail": 4, "pending": -1}


# ══════════════════════════════════════════════════════════════════════
#  工具
# ══════════════════════════════════════════════════════════════════════
def _report(gate: str, issues: list, *, t0: float = 0.0,
            degraded: str = "", skipped: bool = False) -> GateReport:
    """把 issue 列表汇总成门报告。

    ``degraded`` 与 ``skipped`` 语义**必须分清**：
      * ``degraded``：门的**部分子检查**没跑成（如官方池缺失导致跳过字段查重），
        门本身跑了，结论仍有效 —— 状态照常是 pass/warn/fail，只在 summary 里注明。
      * ``skipped``：门**整体没跑**（如无对局引擎），此时结论不可用，
        状态必须是 skipped，**绝不能显示成通过**。
    """
    issues = [i if isinstance(i, Issue) else Issue(**i) for i in (issues or [])]
    errors = [i for i in issues if i.level == "ERROR" and not i.waived]
    warns = [i for i in issues if i.level == "WARN" and not i.waived]
    waived = [i for i in issues if i.waived]

    if skipped:
        return GateReport(gate=gate, status="skipped", issues=issues,
                          summary=degraded or "已跳过",
                          took_ms=int((time.perf_counter() - t0) * 1000) if t0 else 0,
                          degraded=degraded)
    if errors:
        status, summary = "fail", f"{len(errors)} 项拦截、{len(warns)} 项告警"
    elif warns:
        status, summary = "warn", f"{len(warns)} 项告警"
    elif waived:
        status, summary = "waived", f"{len(waived)} 项已强制放行（留痕）"
    else:
        status, summary = "pass", "全部通过"
    if degraded:
        summary += f"；注意：{degraded}"
    return GateReport(
        gate=gate, status=status, issues=issues, summary=summary,
        took_ms=int((time.perf_counter() - t0) * 1000) if t0 else 0,
        degraded=degraded,
    )


def _try_import(modpath: str, attr: str = ""):
    """惰性导入可选模块，缺失时返回 None（用于跨模块尚未就绪时的降级）。"""
    try:
        import importlib
        m = importlib.import_module(modpath, package="cardforge")
        return getattr(m, attr) if attr else m
    except Exception:
        return None


def _official():
    """拿官方卡池（可能不可用）。"""
    cls = _try_import(".pool.official", "OfficialPool")
    if cls is None:
        cls = _try_import("cardforge.pool.official", "OfficialPool")
    if cls is None:
        return None
    try:
        for p in (paths.OFFICIAL_CDB / "cards_zh.cdb", paths.OFFICIAL_CDB / "cards.cdb"):
            if p.exists():
                return cls(str(p))
    except Exception:
        return None
    return None


# ══════════════════════════════════════════════════════════════════════
#  G1 · 平衡审计
# ══════════════════════════════════════════════════════════════════════
def g1_balance(spec: CardSpec, official=None, *, lang: str = "zh_cn",
               check_pool: bool = True) -> GateReport:
    t0 = time.perf_counter()
    design = _try_import(".content.design") or _try_import("cardforge.content.design")
    if design is None:
        return _report("G1", [], t0=t0, degraded="设计审计模块不可用", skipped=True)
    pool = official if official is not None else (_official() if check_pool else None)
    degraded = "" if pool is not None else "官方卡池不可用，已跳过字段查重与号段冲突检查"
    try:
        issues = design.audit_card(spec, pool, lang=lang, check_pool=check_pool)
    except Exception as e:      # 审计器自身出问题要暴露，不能静默放过
        return _report("G1", [Issue(gate="G1", code="G1_INTERNAL", level="ERROR",
                                    message=f"平衡审计执行失败：{e}",
                                    hint="这是程序缺陷，请把这张卡的 spec.json 附上反馈")],
                       t0=t0)
    return _report("G1", issues, t0=t0, degraded=degraded)


# ══════════════════════════════════════════════════════════════════════
#  G2 · 脚本静态检查
# ══════════════════════════════════════════════════════════════════════
def g2_script(spec: CardSpec, lua: str = "") -> GateReport:
    t0 = time.perf_counter()
    body = lua or getattr(spec, "lua", "") or ""
    issues: list[Issue] = []

    if not body.strip():
        if spec.is_monster and spec.frame not in ("normal", "token"):
            return _report("G2", [Issue(
                gate="G2", code="G2_NO_SCRIPT", level="WARN",
                message="效果怪兽没有脚本", hint="用 card script 生成，或把卡种改为通常怪兽")],
                t0=t0)
        return _report("G2", [], t0=t0)

    # UTF-8 无 BOM —— 带 BOM 的 Lua 会直接失效，且事后不可补救
    if body.startswith("\ufeff"):
        issues.append(Issue(gate="G2", code="G2_BOM", level="ERROR",
                            message="脚本以 BOM 开头，ocgcore 会加载失败",
                            hint="以 UTF-8 **无 BOM** 重新保存"))

    lint = _try_import(".content.lua.lint") or _try_import("cardforge.content.lua.lint")
    if lint is None:
        issues.append(Issue(gate="G2", code="G2_NO_LINTER", level="INFO",
                            message="Lua 校验模块不可用，仅做了编码检查",
                            hint=""))
        return _report("G2", issues, t0=t0, degraded="Lua 校验模块不可用")

    try:
        issues.extend(lint.lint_lua(body, spec))
        for extra in ("check_stringid_sync",):
            fn = getattr(lint, extra, None)
            if callable(fn):
                issues.extend(fn(spec, body) or [])
    except Exception as e:
        issues.append(Issue(gate="G2", code="G2_INTERNAL", level="ERROR",
                            message=f"Lua 校验执行失败：{e}", hint="请反馈此问题"))
    return _report("G2", issues, t0=t0)


# ══════════════════════════════════════════════════════════════════════
#  G3 · 实跑验证（三层降级）
# ══════════════════════════════════════════════════════════════════════
def g3_duel(spec: CardSpec, *, scenario: bool = True, duels: int = 10,
            deck: Optional[list] = None) -> GateReport:
    t0 = time.perf_counter()
    engine = _try_import(".duel.engine") or _try_import("cardforge.duel.engine")
    if engine is None:
        # 没有对局模块 → 降级为 G2 的静态结论，并**明确标注**
        rep = g2_script(spec)
        rep.gate = "G3"
        rep.status = "skipped"
        rep.degraded = "对局引擎模块不可用，已降级为静态校验"
        rep.summary = rep.degraded
        rep.took_ms = int((time.perf_counter() - t0) * 1000)
        return rep

    try:
        st = engine.detect()
    except Exception as e:
        st = None
        err = str(e)
    else:
        err = ""

    level = getattr(st, "level", "static") if st else "static"
    if level != "ocgcore":
        rep = g2_script(spec)
        rep.gate = "G3"
        rep.status = "skipped"
        reason = (getattr(st, "reason", "") or err or "未检测到 ocgcore 原生库")
        hint = getattr(st, "hint", "") or ""
        rep.degraded = f"未检测到对局引擎（{reason}），已降级为静态校验"
        rep.summary = rep.degraded
        if hint:
            rep.issues.append(Issue(gate="G3", code="G3_ENGINE_HINT", level="INFO",
                                    message=hint, hint=""))
        rep.took_ms = int((time.perf_counter() - t0) * 1000)
        return rep

    issues: list[Issue] = []
    detail: dict = {}
    ran_anything = False          # 真的跑过至少一项验证吗？
    try:
        if scenario:
            sc_mod = _try_import(".duel.scenario") or _try_import("cardforge.duel.scenario")
            if sc_mod is not None:
                builtin = getattr(sc_mod, "SCENARIOS", []) or []
                if builtin:
                    res = sc_mod.run_batch(list(builtin)[:4], [spec]) or []
                    ran_anything = True
                    for r in res:
                        if not r.get("ok"):
                            issues.append(Issue(
                                gate="G3", code="G3_SCENARIO", level="ERROR",
                                message=f"场景「{r.get('name', '?')}」结算不符预期："
                                        f"{r.get('detail', '')}",
                                hint="回到脚本层修正", field="lua"))
                    detail["scenarios"] = len(res)
        if duels > 0:
            bot = _try_import(".duel.bot") or _try_import("cardforge.duel.bot")
            run = getattr(bot, "run_duel", None) if bot else None
            if callable(run):
                dk = deck or ([spec.id] * 3 + [0] * 37)
                res = run(dk, dk, seed=1, max_steps=3000, cards={spec.id: spec})
                ran_anything = True
                detail["duels"] = 1
                detail["turns"] = res.get("turns")
                detail["blocking"] = res.get("blocking", "")
                # 卡住的归因很关键：引擎没报脚本错、只是简易 bot 走投无路时，
                # 报 ERROR 会把人引去改本来没问题的脚本（"bot 局限" ≠ "卡有问题"）。
                bot_limited = res.get("blocking") == "bot"
                for e in (res.get("errors") or []):
                    issues.append(Issue(gate="G3", code="G3_DUEL_ERROR",
                                        level="WARN" if bot_limited else "ERROR",
                                        message=f"实跑报错：{e}",
                                        hint="回到脚本层修正" if not bot_limited
                                             else "这是内置简易 bot 的决策局限，"
                                                  "不是这张卡的问题：可以换卡组再跑一次"))
                if not res.get("ok"):
                    if bot_limited:
                        issues.append(Issue(
                            gate="G3", code="G3_BOT_STUCK", level="WARN",
                            message=f"整局没能由简易 bot 打完（跑到回合 {res.get('turns')} "
                                    f"步数 {res.get('steps')}），引擎未报任何脚本错误",
                            hint="脚本加载与结算本身没报错。想拿到完整胜负：换一副更主动的"
                                 "卡组（多带攻击手），或把这张卡并进系列后用真实卡组跑"))
                    else:
                        issues.append(Issue(
                            gate="G3", code="G3_DUEL_FAIL", level="ERROR",
                            message="整局对战未能正常完成",
                            hint="检查脚本是否有死循环或非法结算"))
                if res.get("degraded"):
                    issues.append(Issue(gate="G3", code="G3_DEGRADED", level="INFO",
                                        message=res["degraded"], hint=""))
    except Exception as e:
        issues.append(Issue(gate="G3", code="G3_INTERNAL", level="ERROR",
                            message=f"实跑验证执行失败：{e}", hint="请反馈此问题"))
        ran_anything = True

    # ⚠ 引擎在、但驱动模块还没就绪时，**绝不能报 pass** —— 那等于假装跑过对局。
    #   必须显式降级为 skipped 并写清缺什么。
    if not ran_anything:
        return GateReport(
            gate="G3", status="skipped", issues=issues,
            summary="对局引擎可用，但对局驱动模块尚未就绪，未实际运行任何验证",
            took_ms=int((time.perf_counter() - t0) * 1000),
            degraded="驱动模块缺失（duel/scenario.py 与 duel/bot.py）；"
                     "在此之前 G3 无法给出实跑结论",
        )

    rep = _report("G3", issues, t0=t0)
    if detail:
        rep.summary += f"（{json.dumps(detail, ensure_ascii=False)}）"
    return rep


# ══════════════════════════════════════════════════════════════════════
#  G4 · 系列一致性
# ══════════════════════════════════════════════════════════════════════
def g4_series(arch: Archetype, cards: Iterable[CardSpec],
              official=None) -> GateReport:
    t0 = time.perf_counter()
    design = _try_import(".content.design") or _try_import("cardforge.content.design")
    if design is None:
        return _report("G4", [], t0=t0, degraded="设计审计模块不可用", skipped=True)
    try:
        issues = design.audit_archetype(arch, list(cards or []), official)
    except Exception as e:
        return _report("G4", [Issue(gate="G4", code="G4_INTERNAL", level="ERROR",
                                    message=f"系列一致性检查失败：{e}", hint="请反馈")],
                       t0=t0)
    return _report("G4", issues, t0=t0)


# ══════════════════════════════════════════════════════════════════════
#  G5 · 导出自检
# ══════════════════════════════════════════════════════════════════════
def g5_export(pack_dir) -> GateReport:
    t0 = time.perf_counter()
    exp = _try_import(".export.expansions") or _try_import("cardforge.export.expansions")
    if exp is None or not hasattr(exp, "verify"):
        return _report("G5", [], t0=t0, degraded="导出模块不可用，未做导出自检", skipped=True)
    try:
        issues = exp.verify(str(pack_dir)) or []
    except Exception as e:
        return _report("G5", [Issue(gate="G5", code="G5_INTERNAL", level="ERROR",
                                    message=f"导出自检失败：{e}", hint="请反馈")], t0=t0)
    return _report("G5", issues, t0=t0)


# ══════════════════════════════════════════════════════════════════════
#  统一入口 / 豁免 / 留痕
# ══════════════════════════════════════════════════════════════════════
GATES = {
    "G1": g1_balance, "G2": g2_script, "G3": g3_duel,
    "G4": g4_series, "G5": g5_export,
}


def run(gate: str, **kw) -> GateReport:
    """按门名执行。未知门名返回 fail（而不是静默通过）。"""
    fn = GATES.get(str(gate).upper())
    if fn is None:
        return _report(gate, [Issue(gate=gate, code="GATE_UNKNOWN", level="ERROR",
                                    message=f"未知的质量门「{gate}」",
                                    hint=f"可用：{'、'.join(GATE_ORDER)}")])
    return fn(**kw)


def run_all(spec: Optional[CardSpec] = None, *, arch=None, cards=None,
            pack_dir=None, gates: Iterable[str] = GATE_ORDER,
            duels: int = 10) -> dict:
    """按需跑多道门，返回 ``{gate: GateReport.to_dict()}``。缺参数的跳过并标注。"""
    out: dict[str, dict] = {}
    for g in gates:
        g = str(g).upper()
        try:
            if g == "G1" and spec is not None:
                out[g] = g1_balance(spec).to_dict()
            elif g == "G2" and spec is not None:
                out[g] = g2_script(spec).to_dict()
            elif g == "G3" and spec is not None:
                out[g] = g3_duel(spec, duels=duels).to_dict()
            elif g == "G4" and arch is not None:
                out[g] = g4_series(arch, cards or []).to_dict()
            elif g == "G5" and pack_dir is not None:
                out[g] = g5_export(pack_dir).to_dict()
            else:
                out[g] = GateReport(gate=g, status="pending",
                                    summary="缺少执行所需参数").to_dict()
        except Exception as e:
            out[g] = GateReport(gate=g, status="fail",
                                summary=f"执行异常：{e}").to_dict()
    return out


def waive(report: GateReport, code: str, reason: str, who: str = "user") -> GateReport:
    """强制放行某条 issue —— **必须填理由**，理由会写进审计报告。"""
    if not str(reason or "").strip():
        raise ValueError("强制放行必须填写理由（会写入审计留痕）")
    hit = False
    for i in report.issues:
        if isinstance(i, Issue) and i.code == code:
            i.waived = True
            i.waiver_reason = f"{reason}（by {who}）"
            hit = True
    if not hit:
        return report
    errors = [i for i in report.issues if i.level == "ERROR" and not i.waived]
    warns = [i for i in report.issues if i.level == "WARN" and not i.waived]
    waived = [i for i in report.issues if i.waived]
    if errors:
        report.status, report.summary = "fail", f"{len(errors)} 项仍被拦截"
    elif warns:
        report.status = "warn"
        report.summary = f"{len(warns)} 项告警、{len(waived)} 项带豁免通过"
    else:
        report.status = "waived"
        report.summary = f"{len(waived)} 项带豁免通过"
    return report


def write_audit(report: GateReport, ctx: Optional[dict] = None) -> str:
    """把一份门报告写成 Markdown 审计报告，落到 ``workspace/logs/audit/``。"""
    ctx = ctx or {}
    paths.ensure_dirs()
    d = paths.LOGS / "audit"
    d.mkdir(parents=True, exist_ok=True)
    ts = datetime.now()
    name = ctx.get("card_id") or ctx.get("archetype") or "run"
    p = d / f"{ts:%Y%m%d-%H%M%S}-{report.gate}-{name}.md"

    badge = {"pass": "✅ 通过", "warn": "⚠️ 告警", "fail": "⛔ 拦截",
             "waived": "🟡 带豁免通过", "skipped": "⏭️ 已降级跳过",
             "pending": "… 待检"}.get(report.status, report.status)
    lines = [
        f"# {report.gate} · {GATE_NAMES.get(report.gate, '')} — {badge}",
        "",
        f"- 时间：{ts:%Y-%m-%d %H:%M:%S}",
        f"- 结论：{report.summary}",
        f"- 耗时：{report.took_ms} ms",
    ]
    if report.degraded:
        lines.append(f"- **降级说明**：{report.degraded}")
    for k, v in ctx.items():
        lines.append(f"- {k}：{v}")
    lines += ["", "## 检查项", ""]
    if not report.issues:
        lines.append("（无问题）")
    else:
        lines += ["| 级别 | 规则号 | 说明 | 建议 | 豁免 |", "|---|---|---|---|---|"]
        for i in report.issues:
            if not isinstance(i, Issue):
                continue
            mark = "🟡 已放行" if i.waived else ""
            reason = f"<br>理由：{i.waiver_reason}" if i.waiver_reason else ""
            lines.append(f"| {i.level} | `{i.code}` | {i.message}{reason} | "
                         f"{i.hint} | {mark} |")
    lines += ["", "---", "",
              "> 本报告由 CardForge 质量门自动生成。强制放行记录永久保留，可追溯。"]
    p.write_text("\n".join(lines), encoding="utf-8")
    return str(p)


def summarize(reports: dict) -> dict:
    """把多门结果汇总成底栏指示灯用的一行数据。"""
    out = {}
    worst = -1
    for g in GATE_ORDER:
        r = reports.get(g)
        st = (r.get("status") if isinstance(r, dict) else getattr(r, "status", None)) or "pending"
        out[g] = {"status": st, "name": GATE_NAMES.get(g, "")}
        worst = max(worst, STATUS_RANK.get(st, -1))
    inv = {v: k for k, v in STATUS_RANK.items()}
    out["overall"] = inv.get(worst, "pending")
    return out


def capabilities() -> dict:
    """各门的依赖可用性（doctor 用）。"""
    return {
        "G1": _try_import(".content.design") is not None,
        "G2": _try_import(".content.lua.lint") is not None,
        "G3_engine": _try_import(".duel.engine") is not None,
        "G4": _try_import(".content.design") is not None,
        "G5": _try_import(".export.expansions") is not None,
        "official_pool": _official() is not None,
        "gate_names": dict(GATE_NAMES),
    }
