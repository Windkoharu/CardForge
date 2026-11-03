"""可运行度判定 —— 「这份脚本在对局里真的能干活吗」。

背景（缺陷 #37）
----------------
生成器有一条正确的设计：**没有结构化数据就不产出猜测代码**，只写
``-- [CardForge]`` 注释。问题出在门禁侧：这条路产出的「空壳脚本」
（``initial_effect`` 里除注释外一行代码都没有）在 G2 判 pass、在 G5 只被
当成「脚本文件存在」。用户把这些卡导进 EDOPro / MDPro3 后看到的是：

* 额外卡组怪兽**不能正规召唤**（没有 ``Fusion.AddProcMix`` 之类的流程）；
* 上场后**效果一条都不能发动**（没有 ``RegisterEffect``）；
* **却能被别的卡效果特召**（引擎按 ``datas.type`` 认它是融合/同步怪，
  特召不看这张卡自己的脚本）。

三种现象一个原因，所以本模块把「声明了多少 / 落地了多少」做成**确定性**
判定，供 G2（有 spec，能区分设计意图 → ERROR）与 G5（只有 cdb+lua →
空壳判 ERROR、缺流程判 WARN，避免误伤）共用。

判定口径（刻意保守：宁可漏报，不可误杀好卡）
--------------------------------------------
1. **注释不算代码**：所有判定都在「去掉注释后的正文」上做。生成器的
   ``-- [CardForge] … 未生成 Fusion.AddProcMix`` 这类注释里就含调用名，
   不剥注释会把空壳判成有流程（这正是缺陷 #37 最容易被漏掉的地方）。
2. ``empty_body`` 只在「剥完注释后什么都不剩」时为真 —— 少剥或多剥都只会
   让判定偏向"通过"，不会把好卡拦下来。
3. 召唤流程按 **frame** 期望（有 spec 时），并按 ``summon.limit``
   （``cannot_spsummon`` 是**故意不生成**流程）豁免。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

__all__ = [
    "PROC_CALLS", "PROC_BY_BASE", "PROC_LABELS", "Readiness", "readiness",
    "analyze_lua", "find_proc_calls", "expected_procs", "issues_for",
    "needs_proc_card", "proc_label",
]

# ══════════════════════════════════════════════════════════════════════
#  召唤流程调用表（片段里的唯一出口，改片段时这张表要跟着改）
# ══════════════════════════════════════════════════════════════════════
PROC_CALLS: dict[str, tuple[str, ...]] = {
    "fusion": ("Fusion.AddProcMix", "Fusion.AddProcMixRep",
               "Fusion.AddProcMixRepUnfix", "Fusion.AddContactProc"),
    "synchro": ("Synchro.AddProcedure", "aux.AddSynchroProcedure"),
    "xyz": ("Xyz.AddProcedure",),
    "link": ("Link.AddProcedure",),
    "ritual": ("Ritual.AddProcGreater", "Ritual.AddProcEqual", "Ritual.AddProc"),
    "pendulum": ("Pendulum.AddProcedure",),
}

#: frame 的 ``base`` → 该卡种必须出现的流程种类
PROC_BY_BASE: dict[str, tuple[str, ...]] = {
    "fusion": ("fusion",),
    "synchro": ("synchro",),
    "xyz": ("xyz",),
    "link": ("link",),
    "ritual": ("ritual",),
}

#: cdb ``type`` 位 → 该卡种必须出现的流程种类（G5 无 spec 时用）
_TYPE_PROC: tuple[tuple[int, tuple[str, ...]], ...] = (
    (0x40, ("fusion",)),          # TYPE_FUSION
    (0x2000, ("synchro",)),       # TYPE_SYNCHRO
    (0x800000, ("xyz",)),         # TYPE_XYZ
    (0x4000000, ("link",)),       # TYPE_LINK
    (0x80, ("ritual",)),          # TYPE_RITUAL
)

#: 卡种 → 官方写法的示例调用（给提示文案用）
_PROC_EXAMPLE: dict[str, str] = {
    "fusion": "融合素材 ×N",
    "synchro": "协调 + 协调以外",
    "xyz": "阶级与素材数",
    "link": "连接值与素材",
    "ritual": "仪式怪兽的等级",
    "pendulum": "刻度",
}

#: 卡种 → 中文名（报错文案用；不要把 "fusion" 直接甩给用户）
PROC_LABELS: dict[str, str] = {
    "fusion": "融合", "synchro": "同步", "xyz": "超量",
    "link": "连接", "ritual": "仪式", "pendulum": "灵摆",
}


def proc_label(kinds) -> str:
    """把流程种类列表翻成「融合/连接」这样的中文。"""
    return "/".join(PROC_LABELS.get(k, k) for k in (kinds or []))

_LONG_COMMENT = re.compile(r"--\[(=*)\[.*?\]\1\]", re.S)
_LINE_COMMENT = re.compile(r"--[^\n]*")
_REGISTER = re.compile(r":RegisterEffect\s*\(")


# ══════════════════════════════════════════════════════════════════════
#  Lua 文本分析
# ══════════════════════════════════════════════════════════════════════
def strip_comments(lua: str) -> str:
    """去掉注释（长注释 ``--[[ ]]`` / ``--[==[ ]==]`` 与行注释）。"""
    text = str(lua or "").replace("\r\n", "\n").replace("\r", "\n")
    text = _LONG_COMMENT.sub("", text)
    return _LINE_COMMENT.sub("", text)


def _initial_body(code: str) -> str:
    """取 ``function s.initial_effect(c)`` 到其后第一个顶格 ``end`` 之间的正文。

    生成器的骨架是固定的（``function …`` 顶格起、``end`` 顶格收），所以按行扫
    即可；用户手改的脚本取不到就退化成整份代码，判定偏"通过"。
    """
    lines = code.split("\n")
    start = -1
    for i, ln in enumerate(lines):
        if "initial_effect" in ln and "function" in ln:
            start = i + 1
            break
    if start < 0:
        return code
    depth = 1
    for i in range(start, len(lines)):
        ln = lines[i].strip()
        if ln.startswith("function ") or ln.endswith("function"):
            depth += 1
        if ln == "end" and len(lines[i]) and not lines[i][0].isspace():
            depth -= 1
            if depth == 0:
                return "\n".join(lines[start:i])
    return "\n".join(lines[start:])


def find_proc_calls(lua: str) -> list[str]:
    """正文里出现的召唤流程调用名（已剥注释，空壳不会误命中）。"""
    code = strip_comments(lua)
    out: list[str] = []
    for names in PROC_CALLS.values():
        for name in names:
            if name in code and name not in out:
                out.append(name)
    return out


def expected_procs(*, base: str = "", type_bits: int = 0) -> list[str]:
    """该卡种应该有的流程种类（``base`` 优先，否则按 type 位）。"""
    if base:
        return list(PROC_BY_BASE.get(str(base), ())) or \
            (["pendulum"] if "pendulum" in str(base) else [])
    t = int(type_bits or 0)
    out: list[str] = []
    for bit, kinds in _TYPE_PROC:
        if t & bit:
            out.extend(kinds)
    return out


def analyze_lua(lua: str) -> dict:
    """只看脚本文本的事实：有没有代码 / 有多少次注册 / 有哪些流程。"""
    raw = str(lua or "")
    has_lua = bool(raw.strip())
    code = strip_comments(raw)
    body = _initial_body(code).strip()
    return {
        "has_lua": has_lua,
        "empty_body": not body,
        "n_register": len(_REGISTER.findall(code)),
        "procs": find_proc_calls(raw),
        #: 剥注释后正文里还剩多少字符（诊断用，别拿来当判据）
        "body_chars": len(body),
    }


# ══════════════════════════════════════════════════════════════════════
#  spec + lua 的可运行度
# ══════════════════════════════════════════════════════════════════════
@dataclass
class Readiness:
    """一张卡的「能不能在真机上跑」结论（全部字段都是确定性推导）。"""
    needs_script: bool = False
    has_lua: bool = False
    empty_body: bool = False
    n_register: int = 0
    procs_found: list = field(default_factory=list)
    procs_expected: list = field(default_factory=list)
    effects_declared: int = 0
    effects_planned: int = 0
    dead_effects: list = field(default_factory=list)     # [{index, kind}]
    exempt: str = ""                                     # 豁免原因
    notes: list = field(default_factory=list)

    # ── 派生结论 ────────────────────────────────────────────────
    @property
    def missing_procs(self) -> list:
        return [k for k in self.procs_expected
                if not any(n in PROC_CALLS.get(k, ()) for n in self.procs_found)]

    @property
    def playable(self) -> bool:
        """对局里这张卡有没有任何自己的行为（流程或效果）。"""
        if not self.needs_script:
            return True
        if not self.has_lua or self.empty_body:
            return False
        if self.n_register == 0 and not self.procs_found:
            return False
        return True

    def to_dict(self) -> dict:
        return {
            "needs_script": self.needs_script,
            "playable": self.playable,
            "has_lua": self.has_lua,
            "empty_body": self.empty_body,
            "n_register": self.n_register,
            "procs_found": list(self.procs_found),
            "procs_expected": list(self.procs_expected),
            "missing_procs": self.missing_procs,
            "effects_declared": self.effects_declared,
            "effects_planned": self.effects_planned,
            "dead_effects": list(self.dead_effects),
            "exempt": self.exempt,
            "notes": list(self.notes),
        }


def _needs_script(spec) -> bool:
    """与 ``export.expansions.needs_script`` 同口径（按 frame 键判白板）。"""
    return str(getattr(spec, "frame", "")) not in ("normal", "normal_pendulum", "token")


#: 靠「召唤流程」上场的卡种 —— 这些卡没有脚本就连出场的入口都没有
PROC_BASES: tuple[str, ...] = ("fusion", "synchro", "xyz", "link", "ritual")


def needs_proc_card(spec) -> bool:
    """额外卡组 / 仪式卡（缺脚本、缺流程时必须报 ERROR 而不是 WARN）。"""
    try:
        return str(spec.frame_def.base) in PROC_BASES
    except Exception:
        return False


def _declared_effects(spec) -> list:
    try:
        return list(spec.effect_specs() or [])
    except Exception:
        return []


def _planned_effects(spec) -> tuple[int, list, list]:
    """``(有片段的条数, 无片段的效果 [{index, kind}], notes)``。"""
    try:
        from . import emit as E
        E._sync_fragment_names()
        slots = E.plan(spec)
    except Exception as e:                      # 计划都算不出来：如实标注，不猜
        return 0, [], [f"效果计划计算失败：{type(e).__name__}: {e}"]
    planned = 0
    dead: list = []
    for slot in slots:
        if slot.get("fragment"):
            planned += 1
        else:
            eff = slot.get("eff")
            try:
                idx = int(getattr(eff, "index", -1))
            except Exception:
                idx = -1
            dead.append({"index": idx, "kind": str(slot.get("kind") or "")})
    return planned, dead, []


def readiness(spec, lua: str = "") -> Readiness:
    """算一张卡的可运行度。``lua`` 缺省取 ``spec.lua``。"""
    body = lua if str(lua or "").strip() else str(getattr(spec, "lua", "") or "")
    info = analyze_lua(body)
    r = Readiness(
        needs_script=_needs_script(spec),
        has_lua=info["has_lua"],
        empty_body=info["empty_body"],
        n_register=info["n_register"],
        procs_found=list(info["procs"]),
        effects_declared=len(_declared_effects(spec)),
    )

    # 期望哪些流程：frame 是权威，灵摆与 base 叠着来
    base = ""
    try:
        base = str(spec.frame_def.base or "")
    except Exception:
        base = ""
    want: list = []
    if str(getattr(spec, "frame", "")) in PROC_BY_BASE:
        want.extend(PROC_BY_BASE[str(spec.frame)])
    else:
        want.extend(PROC_BY_BASE.get(base, ()))
    try:
        if spec.is_pendulum:
            want.append("pendulum")
    except Exception:
        pass
    r.procs_expected = [k for k in want if k]

    # 召唤限制豁免：「不能特殊召唤」是**故意**不生成流程（见 fragments 注释）
    try:
        from .. import summon as S
        if S.normalize(spec).limit == "cannot_spsummon":
            r.exempt = "召唤条件声明「不能特殊召唤」，按设计不生成流程"
            r.procs_expected = []
    except Exception:
        pass

    planned, dead, notes = _planned_effects(spec)
    r.effects_planned = planned
    r.dead_effects = dead
    r.notes.extend(notes)
    return r


# ══════════════════════════════════════════════════════════════════════
#  结论 → Issue（G2 用；G5 走同名规则但级别不同，见 expansions.verify）
# ══════════════════════════════════════════════════════════════════════
def _issue(code: str, level: str, message: str, hint: str = "",
           field: str = "", gate: str = "G2"):
    from ...core.models import Issue       # 延迟导入：本模块被门与导出双侧引用
    return Issue(gate=gate, code=code, level=level, message=message,
                 hint=hint, field=field)


def issues_for(spec, lua: str = "", *, gate: str = "G2", proc_level: str = "") -> list:
    """把可运行度翻成 Issue 列表（G2 与 G5 共用，``gate`` 只影响编号与措辞）。

    级别取舍（**这是本轮的核心决定**）：

    * 「一条代码都没有」= **ERROR**。它决定了这张卡在真机上是个空壳，
      不是风格问题；G2 判 pass 正是缺陷 #37 的成因。
    * 「有代码但缺某个流程」= **ERROR**。额外卡组卡没有流程 = 不能正规召唤，
      与设计意图无关（``cannot_spsummon`` 已在 :func:`readiness` 里豁免）。
      ``proc_level="WARN"`` 供**没有 spec** 的场合降级使用（G5 verify 只有
      cdb 的 type 位，判不出「这张卡本来就声明不能特殊召唤」）。
    * 「个别效果没有片段」= **WARN**。这是片段库的覆盖缺口，卡本身还能用。
    """
    r = readiness(spec, lua)
    if not r.needs_script:
        return []
    cid = getattr(spec, "id", 0) or 0
    name = getattr(spec, "name", "") or f"c{cid}"
    head = f"卡 {cid}「{name}」"
    mk = lambda code, level, msg, hint="": _issue(  # noqa: E731
        code, level, msg, hint, field=str(cid), gate=gate)

    if r.empty_body:
        if r.effects_declared or r.procs_expected:
            parts = []
            if r.effects_declared:
                parts.append(f"{r.effects_declared} 条效果")
            if r.procs_expected:
                parts.append("召唤流程")
            return [mk(
                "G2_NOT_PLAYABLE", "ERROR",
                f"{head}的脚本只有注释：{'+'.join(parts)}一条都没生成",
                "到「召唤条件」面板填素材行、到「效果」面板给每条效果选「效果种类」。"
                "只写卡文不会产生任何可执行代码 —— 导进游戏后既不能正规召唤、"
                "效果也不能发动，只能被别的卡效果特召。")]
        return [mk(
            "G2_EMPTY_INITIAL", "WARN",
            f"{head}的 initial_effect 是空的（没有效果，也没有召唤流程）",
            "对局里这张卡会是白板。若是有意做的白板，改成「通常」卡种更合适。")]

    out = []
    missing = r.missing_procs
    if missing:
        calls = "、".join(PROC_CALLS.get(k, ("",))[0] for k in missing)
        out.append(mk(
            "G2_EXTRA_NO_PROC", proc_level or "ERROR",
            f"{head}没有召唤流程（缺 {calls}），对局里无法正规召唤",
            "在「召唤条件」里填素材（" +
            "、".join(_PROC_EXAMPLE.get(k, k) for k in missing) +
            "）。缺这一步，这张卡只能被别的卡效果特召。"))

    if r.effects_declared and r.effects_planned == 0:
        kinds = "、".join(sorted({d["kind"] for d in r.dead_effects if d["kind"]})) or "（未填种类）"
        out.append(mk(
            "G2_EFFECT_NOT_EMITTED", "ERROR",
            f"{head}的 {r.effects_declared} 条效果一条都没生成：{kinds}",
            "这些效果只有卡文、没有登记「效果种类」，脚本里只会留注释。"
            "到「效果」面板逐条选种类；也可以用「从卡文推断」再核对。"))
    elif r.effects_declared > r.effects_planned:
        dead = list(r.dead_effects)
        idxs = "".join("①②③④⑤⑥⑦⑧⑨"[d["index"]] if 0 <= d["index"] < 9 else "?"
                       for d in dead) or "若干"
        out.append(mk(
            "G2_EFFECT_DEGRADED", "WARN",
            f"{head}有 {len(dead)} 条效果没有脚本片段（{idxs}），只会写成注释",
            "这些效果在对局里不会生效。换成已有片段的效果种类，"
            "或把卡文改成只描述能生成的部分。"))
    return out
