"""MDPro3 旧方言：翻译（EDOPro → 客户端）与对账（符号白名单）。

背景（缺陷 #48）
----------------
B 站用户 SA人类 报告：卡锻生成的额外卡组卡导入 MDPro3 后**不能正规召唤、
效果全部失灵**，只能被别的卡效果特召；改导 MDPro4 则**整包不识别**。

根因不在 cdb、也不在包结构：``initial_effect`` 第一行就是
``Fusion.AddProcMix(...)`` —— 这是 ProjectIgnis（EDOPro）新方言；
MDPro3 客户端 ``Data/script.zip``（constant/utility/procedure 三个库 +
13572 张官方卡）只认 **旧命名空间** ``Auxiliary.*`` / ``aux.*``，
官方脚本里 ``Fusion.|Synchro.|Xyz.|Link.|Ritual.|Pendulum.X(`` 新方言调用
**一次都没有**。Lua 在 ``initial_effect`` 里对 nil 调用的那一刻中止：
召唤流程没注册、效果也没登记 —— 症状与反馈逐条吻合。

本模块做两件事（用户拍板：改 bug 满足 MDPro3/4 用户）：
1. ``translate()``：把生成器产出的 EDOPro 脚本**逐行翻译**成经客户端实测的
   旧方言等价写法（语义映射见 ``_TRANSLATION_TABLE``，每条都有客户端
   库源码或官方卡脚本作依据）。翻译失败的项目**注释掉并降级报错**，
   绝不留下会中止 ``initial_effect`` 的死调用。
2. ``lint()``：把译文里出现的全部「全局函数 / 常量 / 方法名」与
   ``data/mdpro3_api.json``（``tools/extract_mdpro3_api.py`` 从客户端
   脚本包实测抽取）对账；认不出来的符号 = 客户端运行时 ``nil`` = 又一张
   「空壳卡」，打包时判 ERROR。

边界（刻意保守）
----------------
* **只影响 MDPro3/4 打包**：工作区里的 ``spec.lua`` 与 EDOPro 导出
  一个字都不改（EDOPro 是设计基准）。
* 翻译是**文本级**的：只改写「本生成器确定会产出的行」；改写不了就整行
  注释降级，不做字符串级猜测。
* MDPro4：本机没有客户端、公开资料无定论，包暂按 MDPro3 同规格产出，
  调用方负责标注「MDPro4 未实测」。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from ...core.paths import DATA
from .readiness import strip_comments

__all__ = ["Note", "API_JSON", "load_api", "translate", "lint"]

#: 客户端符号白名单快照（tools/extract_mdpro3_api.py 的产物）
API_JSON = DATA / "mdpro3_api.json"
_API_SCHEMA = "mdpro3-api-v1"


@dataclass(frozen=True)
class Note:
    """一条对账/翻译结论。level 用与 Issue 相同口径：ERROR/WARN/INFO。"""
    level: str
    code: str
    msg: str
    hint: str = ""


# ══════════════════════════════════════════════════════════════════════
#  白名单加载
# ══════════════════════════════════════════════════════════════════════
@lru_cache(maxsize=1)
def load_api(path: Optional[str] = None) -> dict:
    """读符号白名单；缺文件/换 schema 直接抛错（打包侧转成响亮的 ERROR）。"""
    p = path or str(API_JSON)
    with open(p, encoding="utf-8") as f:
        api = json.load(f)
    if api.get("schema") != _API_SCHEMA:
        raise ValueError(f"{p} 的 schema 是 {api.get('schema')!r}，"
                         f"需要 {_API_SCHEMA!r}：重跑 tools/extract_mdpro3_api.py")
    return api


class _Api:
    """把白名单收进集合，一次构建反复用。"""

    def __init__(self, api: dict):
        self.defined = frozenset(api["defined_functions"])
        self.tokens = frozenset(api["official_tokens"])
        self.constants = frozenset(api["constants"])
        self.bare = frozenset(api.get("defined_bare_functions", ()))
        self.aliases = {"aux": "Auxiliary"}

    def has_member(self, dotted: str, member: str) -> bool:
        """``aux.EnablePendulumAttribute`` 这类全局表的成员在不在。"""
        full = f"{self.aliases.get(dotted, dotted)}.{member}"
        return full in self.defined or member in self.tokens


# ══════════════════════════════════════════════════════════════════════
#  翻译表（每条都经客户端实测；行号/样本可在 _probe/mdpro3_*.py 复现）
# ══════════════════════════════════════════════════════════════════════
#
#  新方言（生成器现有输出）                    MDPro3 旧方言（实测依据）
#  ──────────────────────────────────────────────────────────────────
#  Fusion.AddProcMix(c,true,true,…)            aux.AddFusionProcMix(c,false,true,…)
#      客户端签名 (fcard,sub,insf,…)；官方主流布尔参 false,true；
#      EDOPro 的 (notg,nodbg) 与 (sub,insf) 语义不同，必须换值不能只改名。
#  Fusion.AddProcMixRep(c,true,true,F,lo,hi,…) aux.AddFusionProcMixRep(c,false,true,F,lo,hi,…)
#      客户端签名 (fcard,sub,insf,fun1,minc,maxc,…) —— 尾部与 EDOPro 对齐。
#  Fusion.AddProcMixRepUnfix(…)                （无等价：降级）
#  Synchro.AddProcedure(c,F1,1,m1,
#      Synchro.NonTuner(F2),lo2,hi2)           aux.AddSynchroProcedure(c,F1,aux.NonTuner(F2),lo2,hi2)
#      客户端签名 (c,f1,f2,minc,maxc)，协调兽固定 1 只；lo1>1 无等价 → 降级。
#  Xyz.AddProcedure(c,F,lv,ct[,nil,nil,mc])    aux.AddXyzProcedure(c,F,lv,ct[,nil,nil,mc])
#      位置前缀完全兼容（官方样本 maxct 可为 99）；Xyz.InfiniteMats → 99。
#  Link.AddProcedure(c,F,lo,hi[,gf])           aux.AddLinkProcedure(c,F,lo,hi[,gf])
#  Ritual.AddProcGreater(c,F,lv)               （客户端仪式流程在**仪式魔法**侧；
#                                               怪兽侧无等价 → 降级并说明）
#  Fusion.AddContactProc(c,G,OP,nil,nil,SUMMON_TYPE_FUSION)
#        G = function(tp) return Duel.GetMatchingGroup(F,tp,L1,L2,nil) end
#                                  ↓ 取 F/L1/L2（旧接口是「卡片级过滤+区域对」）
#      aux.AddContactFusionProcedure(c,F,L1,L2,OP)   （官方范本 c11502550）
#  Pendulum.AddProcedure(c)                    aux.EnablePendulumAttribute(c)
#  aux.AddEquipProcedure(c,0,F)                aux.AddEquipSpellEffect(c,true,true,F)
#      旧装备魔法四合一（发动+目标+EQUIP_LIMIT）；eqlimit 取默认 1。
#  SetCountLimit(1,{id,N})                     SetCountLimit(1,id+N)
#      旧核的计数字段是整数（官方 1398 张用 id+N）；带
#      EFFECT_COUNT_CODE_OATH/DUEL 的第三参没有 → 去掉并 WARN（语义降级：
#      新核的「同盟计数」在旧核没有对应物）。
#  aux.lnklimit                                aux.linklimit（客户端就叫这个）
#  Card.AddCannotBeNormalSummoned(c)           EFFECT_CANNOT_SUMMON + EFFECT_CANNOT_MSET
#  Card.AddCannotBeSpecialSummoned(c)          EFFECT_CANNOT_SPECIAL_SUMMON      两枚
#  Card.AddMustFirstBeXSummoned(c)             EFFECT_SPSUMMON_CONDITION + aux.{fus,syn,xyz,link,rit}limit
#  Card.AddSetcodesRule(c,0,CODE)              EFFECT_ADD_SETCODE 效果块（官方 12 张用法）
#  常量核对：EFFECT_COUNT_CODE_OATH/DUEL、REASON_MATERIAL、SEQ_DECKSHUFFLE、
#  EFFECT_TYPE_GRANT、EFFECT_SPSUMMON_CONDITION 等客户端**都有**，无需动。

_RE_MIX = re.compile(r"^(\t*)Fusion\.AddProcMix\(c,true,true,(.+)\)\s*$")
_RE_MIX_REP = re.compile(r"^(\t*)Fusion\.AddProcMixRep\(c,true,true,(.+)\)\s*$")
_RE_UNFIX = re.compile(r"^(\t*)Fusion\.AddProcMixRepUnfix\(")
_RE_SYNC = re.compile(
    r"^(\t*)Synchro\.AddProcedure\(c,([^,]+),(\d+),(\d+),"
    r"Synchro\.NonTuner\((.+)\),(\d+),(\d+)\)\s*$")
_RE_XYZ = re.compile(r"^(\t*)Xyz\.AddProcedure\((.+)\)\s*$")
_RE_LINK = re.compile(r"^(\t*)Link\.AddProcedure\((.+)\)\s*$")
_RE_PEND = re.compile(r"^(\t*)Pendulum\.AddProcedure\(c\)\s*$")
_RE_EQUIP = re.compile(r"^(\t*)aux\.AddEquipProcedure\(c,(\d+),(.+)\)\s*$")
_RE_CONTACT = re.compile(
    r"^(\t*)Fusion\.AddContactProc\(c,(s\.cgrp[\w.]+),(s\.ctop[\w.]+),"
    r"nil,nil,SUMMON_TYPE_FUSION\)\s*$")
_RE_GRP = re.compile(
    r"function (s\.cgrp[\w.]+)\(tp\)\s*\n\s*return Duel\.GetMatchingGroup\("
    r"([^,]+),tp,([^,]+),([^,]+),nil\)\s*\nend")
_RE_RITUAL = re.compile(r"^(\t*)Ritual\.AddProcGreater\(c,([^,]+),(\d+)\)\s*$")
_RE_LIMIT = re.compile(r"SetCountLimit\((\d+),\{id,(\d+)\}(,EFFECT_COUNT_CODE_\w+)?\)")
_RE_LNKLIMIT = re.compile(r"\baux\.lnklimit\b")

_MUSTLIM = {"Fusion": "fuslimit", "Synchro": "synlimit", "Xyz": "xyzlimit",
            "Link": "linklimit", "Ritual": "ritlimit"}


def _degrade(indent: str, why: str, line: str, notes: list,
             code: str = "MD_DIALECT_DEGRADED", level: str = "ERROR") -> str:
    """把翻译不了的行注释掉，并留一条响亮的记录。"""
    notes.append(Note(level, code,
                      f"「{line.strip()}」在 MDPro3 旧方言里没有等价写法：{why}",
                      "这行已注释掉（保住脚本其余部分能加载）。要么改卡文绕开，"
                      "要么在脚本里按旧方言手工补写；见 docs/03 缺陷 #48。"))
    return f"{indent}-- [CardForge#48] {why}，原 EDOPro 写法注释保留：{line.strip()}"


def _effect_block(indent: str, var: str, codes: list, value: Optional[str] = None,
                  prop: str = "EFFECT_FLAG_CANNOT_DISABLE+EFFECT_FLAG_UNCOPYABLE",
                  etype: str = "EFFECT_TYPE_SINGLE") -> str:
    """旧方言里「给卡打规则状态」的标准效果块（RegisterEffect 是普通核心 API）。"""
    lines = [f"{indent}local {var}=Effect.CreateEffect(c)",
             f"{indent}{var}:SetType({etype})"]
    if prop:
        lines.append(f"{indent}{var}:SetProperty({prop})")
    lines.append(f"{indent}{var}:SetCode({codes[0]})")
    if value:
        lines.append(f"{indent}{var}:SetValue({value})")
    lines.append(f"{indent}c:RegisterEffect({var})")
    for extra_code in codes[1:]:
        lines.append(f"{indent}local {var}b={var}:Clone()")
        lines.append(f"{indent}{var}b:SetCode({extra_code})")
        lines.append(f"{indent}c:RegisterEffect({var}b)")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════
#  translate
# ══════════════════════════════════════════════════════════════════════
def translate(lua: str) -> tuple[str, list[Note]]:
    """EDOPro 脚本 → MDPro3 旧方言。翻不动的行注释降级，绝不产出死调用。"""
    text = str(lua or "")
    if not text.strip():
        return text, []
    notes: list[Note] = []

    # 接触召唤：先扫出组函数体，把「组函数名」还原成旧接口要的「卡片过滤+区域」
    groups: dict[str, tuple[str, str, str]] = {}
    for m in _RE_GRP.finditer(text):
        groups[m.group(1)] = (m.group(2), m.group(3), m.group(4))

    ev_n = 0                     # 注入块里的临时效果变量名 e100、e101…

    out_lines: list[str] = []
    for line in text.splitlines():
        s = line.rstrip("\r")

        m = _RE_MIX.match(s)
        if m:
            out_lines.append(f"{m.group(1)}aux.AddFusionProcMix(c,false,true,{m.group(2)})")
            continue
        m = _RE_MIX_REP.match(s)
        if m:
            out_lines.append(f"{m.group(1)}aux.AddFusionProcMixRep(c,false,true,{m.group(2)})")
            continue
        m = _RE_UNFIX.match(s)
        if m:
            out_lines.append(_degrade(m.group(1), "旧核没有多段可变数量的融合素材接口"
                                  "（AddFusionProcMixRep 只支持一段可变）", s, notes))
            continue
        m = _RE_SYNC.match(s)
        if m:
            t, f1, lo1, hi1, f2, lo2, hi2 = m.groups()
            if lo1 != "1":
                out_lines.append(_degrade(t, f"旧核同步固定 1 只协调（本卡 {lo1} 只）", s, notes))
            else:
                out_lines.append(f"{t}aux.AddSynchroProcedure(c,{f1},"
                                 f"aux.NonTuner({f2}),{lo2},{hi2})")
            continue
        m = _RE_XYZ.match(s)
        if m:
            args = m.group(2).replace("Xyz.InfiniteMats", "99")
            out_lines.append(f"{m.group(1)}aux.AddXyzProcedure({args})")
            continue
        m = _RE_LINK.match(s)
        if m:
            out_lines.append(f"{m.group(1)}aux.AddLinkProcedure({m.group(2)})")
            continue
        m = _RE_PEND.match(s)
        if m:
            out_lines.append(f"{m.group(1)}aux.EnablePendulumAttribute(c)")
            continue
        m = _RE_EQUIP.match(s)
        if m:
            out_lines.append(f"{m.group(1)}aux.AddEquipSpellEffect(c,true,true,{m.group(3)})"
                             f"  -- [CardForge#48] 装备限制数按旧接口默认 1")
            continue
        m = _RE_CONTACT.match(s)
        if m:
            t, gname, opname = m.groups()
            g = groups.get(gname)
            if g:
                out_lines.append(f"{t}aux.AddContactFusionProcedure(c,{g[0]},{g[1]},{g[2]},{opname})")
            else:
                out_lines.append(_degrade(t, "读不出组函数里的素材过滤/区域，无法还原成"
                                          "旧接口（卡片级过滤+区域对）", s, notes))
            continue
        m = _RE_RITUAL.match(s)
        if m:
            out_lines.append(_degrade(m.group(1), "旧客户端的仪式流程写在**仪式魔法**脚本里"
                                      "（Auxiliary.AddRitualProc*），怪兽侧没有等价入口", s, notes))
            continue
        if "SetCountLimit" in s and "{id," in s:
            def _cl(mm: re.Match) -> str:
                if mm.group(3):
                    notes.append(Note("WARN", "MD_DIALECT_COUNT_LABEL",
                                      f"「{s.strip()}」：旧核的计数字段没有"
                                      " OATH/DUEL 标签（跨回合/跨决斗计数语义不同），"
                                      "已按旧写法 id+N 保留「每回合限 N 次」",
                                      "「一回合 1 次、一决斗 1 次」这类卡语义会不同，"
                                      "MDPro3 上请自行核对；见 docs/03 缺陷 #48。"))
                return f"SetCountLimit({mm.group(1)},id+{mm.group(2)})"
            s = _RE_LIMIT.sub(_cl, s)
        if "aux.lnklimit" in s:
            s = _RE_LNKLIMIT.sub("aux.linklimit", s)
        if "IsMonsterEffect" in s and not s.lstrip().startswith("--"):
            # 旧核没有 Card.IsMonsterEffect（ocgcore 符号与官方 13572 张双重确认）；
            # 「以怪兽卡身份发动的效果」在旧方言用 IsHasType（二进制里有该绑定）。
            s = s.replace(":IsMonsterEffect()", ":IsHasType(TYPE_MONSTER)")

        if (m := re.match(r"^(\t*)Card\.AddCannotBeNormalSummoned\(c\)\s*$", s)):
            ev_n += 1
            out_lines.append(_effect_block(m.group(1), f"e{100 + ev_n}",
                                           ["EFFECT_CANNOT_SUMMON", "EFFECT_CANNOT_MSET"]))
            continue
        if (m := re.match(r"^(\t*)Card\.AddCannotBeSpecialSummoned\(c\)\s*$", s)):
            ev_n += 1
            out_lines.append(_effect_block(m.group(1), f"e{100 + ev_n}",
                                           ["EFFECT_CANNOT_SPECIAL_SUMMON"]))
            continue
        if (m := re.match(r"^(\t*)Card\.AddMustFirstBe(Fusion|Synchro|Xyz|Link|Ritual)Summoned\(c\)\s*$", s)):
            ev_n += 1
            out_lines.append(_effect_block(m.group(1), f"e{100 + ev_n}",
                                           ["EFFECT_SPSUMMON_CONDITION"],
                                           value=f"aux.{_MUSTLIM[m.group(2)]}"))
            continue
        if (m := re.match(r"^(\t*)Card\.AddSetcodesRule\(c,0,([^)]+)\)\s*$", s)):
            ev_n += 1
            out_lines.append(_effect_block(m.group(1), f"e{100 + ev_n}",
                                           ["EFFECT_ADD_SETCODE"], value=m.group(2),
                                           prop=""))
            continue
        out_lines.append(s)

    return "\n".join(out_lines) + ("\n" if text.endswith("\n") else ""), notes


# ══════════════════════════════════════════════════════════════════════
#  lint —— 与客户端库对账
# ══════════════════════════════════════════════════════════════════════
_KNOWN_TABLES = frozenset({"Duel", "Card", "Effect", "Group", "Deck", "Auxiliary",
                           "aux", "Core", "Table", "Event", "Log", "BitFlag", "Sync"})
#: 出现即「翻译没跑/没兜住」的新方言表
_PROC_TABLES = frozenset({"Fusion", "Synchro", "Xyz", "Link", "Ritual", "Pendulum",
                          "Counter", "Skill"})
_LUA_BUILTINS = frozenset({
    "pcall", "xpcall", "ipairs", "pairs", "type", "tonumber", "tostring", "select",
    "error", "assert", "next", "rawget", "rawset", "setmetatable", "getmetatable",
    "unpack", "print", "require", "loadstring", "collectgarbage", "tostring",
})
_LUA_KEYWORDS = frozenset({"function", "if", "while", "for", "return", "then", "do",
                           "elseif", "repeat", "until", "and", "or", "not", "end"})
_RE_DOTTED = re.compile(r"\b([A-Za-z_]\w*)\.([A-Za-z_]\w*)\s*\(")
_RE_MEMBER = re.compile(r"\b(aux|Auxiliary)\.([A-Za-z_]\w*)(?![\w.]|\()")
_RE_METHOD = re.compile(r":([A-Za-z_]\w*)\s*\(")  # 只查冒号方法；点式的归 _RE_DOTTED
_RE_BARE = re.compile(r"(?<![\w.:])([a-z_][\w]*)\s*\(")
_RE_CONST = re.compile(r"\b[A-Z][A-Z0-9_]{3,}\b")

#: 官方脚本没用过、但客户端 ocgcore.dll 里确有绑定的方法（二进制符号实测
#: 2026-11-06，见 _probe/mdpro3_probe7.py）——lint 不再对这些报警。
_CORE_METHOD_OK = frozenset({
    "IsHasType", "IsReason", "GetReasonEffect", "GetTurnCount", "IsSummonType",
    "IsDestructable", "IsCanBeEffectTarget", "IsPreviousLocation",
    "IsPreviousSetCard", "IsOriginalSetCard", "GetOwner",
})


def _clean(lua: str) -> str:
    """剥注释与字符串 —— 注释里提到 ``Fusion.AddProcMix`` 不算用了它。"""
    text = strip_comments(lua)
    text = re.sub(r"\[\[[\s\S]*?\]\]", " ", text)
    text = re.sub(r'"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'', " ", text)
    return text


def lint(lua: str, api: Optional[dict] = None) -> list[Note]:
    """把脚本里所有全局符号与客户端白名单对账；返回问题清单（空 = 干净）。"""
    a = _Api(api or load_api())
    text = _clean(str(lua or ""))
    notes: list[Note] = []
    seen: set[str] = set()

    def add(level: str, code: str, msg: str, hint: str = "") -> None:
        if (code, msg) not in seen:
            seen.add((code, msg))
            notes.append(Note(level, code, msg, hint))

    # 本卡自己定义的函数名（s.mat0_0 之类；成员名也要收，方法调用只看末段）
    defs = set(re.findall(r"function ([\w.:]+)\s*\(", text))
    def_names = {n.rsplit(".", 1)[-1].lstrip(":") for n in defs}

    for m in _RE_DOTTED.finditer(text):
        recv, mem = m.group(1), m.group(2)
        full = f"{recv}.{mem}"
        if full in defs:
            continue
        if recv in _PROC_TABLES:
            add("ERROR", "MD_LUA_DIALECT",
                f"用了新方言 {full}()：MDPro3 客户端没有 {recv} 这套表，"
                f"脚本会在这一行中止",
                "MDPro3 只认 aux./Auxiliary. 旧写法；跑 mdpro3dialect.translate "
                "或按 docs/03 缺陷 #48 的表手工改")
        elif recv in _KNOWN_TABLES:
            if not a.has_member(recv, mem):
                add("ERROR", "MD_LUA_DIALECT",
                    f"{full}() 在客户端脚本库里不存在", "换用白名单内的写法")
        elif recv[:1].isupper():
            add("WARN", "MD_LUA_DIALECT",
                f"{full}()：既不认识全局表 {recv}，也没在本卡里定义", "确认是否笔误")

    for m in _RE_MEMBER.finditer(text):
        recv, mem = m.group(1), m.group(2)
        if not a.has_member(recv, mem):
            add("ERROR", "MD_LUA_DIALECT",
                f"引用了不存在的成员 {recv}.{mem}")

    for m in _RE_METHOD.finditer(text):
        mem = m.group(1)
        if mem not in a.tokens and mem not in a.bare and mem not in def_names \
                and mem not in _CORE_METHOD_OK:
            add("WARN", "MD_LUA_METHOD",
                f"方法 :{mem}() 在官方 13572 张卡脚本里没出现过",
                "可能是客户端没有的核心方法，进游戏验证一下")

    for m in _RE_BARE.finditer(text):
        name = m.group(1)
        if name in _LUA_BUILTINS or name in _LUA_KEYWORDS or name in a.bare:
            continue
        if name in def_names or f"local {name}" in text or f"function {name}" in text:
            continue
        add("WARN", "MD_LUA_BARE", f"裸函数调用 {name}() 来源不明", "确认客户端存在")

    for m in _RE_CONST.finditer(text):
        c = m.group(0)
        if c not in a.constants and c not in a.tokens:
            add("ERROR", "MD_LUA_DIALECT",
                f"常量 {c} 在客户端 constant.lua 里不存在（运行值是 nil）",
                "对照客户端脚本改用旧常量；docs/03 缺陷 #48 有对照表")

    if "{id," in text and "SetCountLimit" in text:
        add("ERROR", "MD_LUA_DIALECT",
            "SetCountLimit 用了 {id,N} 表格式标签：旧核只认整数计数",
            "改成 SetCountLimit(1,id+N)")
    return notes
