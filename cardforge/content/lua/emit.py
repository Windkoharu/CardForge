"""脚本组装器 —— 效果 IR → 可直接放进 EDOPro 的 ``c<id>.lua``。

职责
----
1. 按 ``CardSpec.frame`` 选出**卡种骨架**（15 种卡面都有自己的写法）；
2. 用 :mod:`fragments` 把每条效果投成注册块 + 辅助函数；
3. 统一推进 **槽位**：``e1/e2/…`` 变量名、``aux.Stringid(id, n)`` 的 ``n``、
   ``spec.strings``（= cdb 的 ``str1..str16``）与卡文框的 ①②③ 编号同源，
   三处任何一处错位都会让卡文显示 ``???``（历史缺陷 #9）；
4. 没有对应片段的效果种类**降级成注释**，绝不产出会崩的假代码。

契约（§3.5）::

    emit_script(spec, *, tier=1) -> str
    emit_strings(spec, lang="zh_cn") -> list[str]
    write_script(spec, path=None) -> str
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional

from ...core import constants as C
from ...core import paths
from ...core.models import CardSpec, EffectSpec
from ..effects import EFFECT_KINDS, kind as effect_kind
from . import apicatalog as API
from .fragments import (LuaCtx, NO_DESCRIPTION_FRAGMENTS, degrade, equip_filter_fn,
                        fragment, link_marker_lines, setcode_literals,
                        skill_skeleton_lines, summon_procedure_lines, TAB)

__all__ = ["emit_script", "emit_strings", "write_script", "plan", "LuaCtx"]

#: 一个「槽位」= 一次 ``Effect`` 注册（或一段规则文本注释）
SLOT_KIND_EFFECT = "effect"
SLOT_KIND_RULE = "rule_text"


class _Slot(dict):
    """槽位记录（kind / eff / 是否需要 Stringid / 属于哪个文本框）。"""


def _ordered_effects(spec: CardSpec) -> list:
    """按「灵摆效果框 → 怪兽效果框」的顺序返回效果（与卡文编号一致）。

    灵摆卡的两个文本框在版式上是**灵摆刻度条在上、怪兽效果在下**，
    卡文侧 :func:`cardforge.content.psct.gen.compose_pendulum` 先出灵摆框，
    脚本槽位也必须按同一顺序推进，否则 ``aux.Stringid`` 会指向另一框的描述。
    """
    effects = spec.effect_specs()
    pend = {int(i) for i in (spec.pendulum_effect_indices or [])}
    pend_box = [e for i, e in enumerate(effects) if i in pend]
    mon_box = [e for i, e in enumerate(effects) if i not in pend]
    return pend_box, mon_box


def plan(spec: CardSpec, *, tier: int = 1, lang: str = "zh_cn") -> list:
    """列出所有槽位（**``emit_script`` 与 ``emit_strings`` 共用同一份计划**）。

    槽位编号就一条规则：**跟官方 cdb 的 ``str`` 顺序走，跟卡文里的 ①②③ 无关**。
    官方脚本的 ``aux.Stringid(id, n)`` 是按**注册顺序**递增分配的，于是：

    1. 灵摆卡的两个文本框在脚本里也是「灵摆效果先注册、怪兽效果后注册」
       —— 参照真实卡 ``vendor/scripts/samples/c18716735.lua``：
       e1 是 P 区域的灵摆效果 → ``Stringid(id,0)``，e2 是怪兽效果 → ``Stringid(id,1)``。
       所以这里按 ``pendulum → monster`` 的顺序推进，与
       :func:`cardforge.content.psct.gen.compose_pendulum` /
       :func:`cardforge.content.psct.gen.compose` 的分框顺序一致。
    2. **不入连锁的效果不占描述槽**（永续 / 抗性 / 规则文本没有「发动」描述，
       官方也不给它们 str），由 ``params['continuous']`` 或 kind 的
       ``CONTINUOUS_KINDS`` / ``RULE_TEXT_KINDS`` 归属决定；
    3. 没有 Lua 片段、降级成 ``-- [CardForge]`` 注释的效果同样不占槽
       （脚本里不会出现引用了空槽的 ``SetDescription``）；
    4. 超过 16 个描述时截断（``str1..str16`` 是硬上限，G2 报 ``G2_STR_OVERFLOW``），
       并把截断写进 ``ctx.notes``。

    返回 ``[{'kind','eff','box','fragment','needs_string','string_index',
    'string_text','rule_text'}]``：``string_index`` 即脚本里的 ``n``，
    ``string_text`` 即 cdb ``str{n+1}`` 的正文 ——
    两个投影函数都只从这份计划取值，所以不可能出现「卡文改了、脚本没改」的
    错位（历史缺陷 #9）。
    """
    pend_box, mon_box = _ordered_effects(spec)
    slots: list[_Slot] = []
    str_index = 0
    for box, items in (("pendulum", pend_box), ("monster", mon_box)):
        for eff in items:
            k = effect_kind(eff.kind)
            frag_name = k.lua_fragment if k else ""
            has_frag = bool(frag_name and frag_name in _FRAGMENT_NAMES)
            continuous = bool((eff.params or {}).get("continuous")) or \
                (k is not None and (k.is_continuous or k.is_rule_text))
            wants_string = bool(k) and not continuous and has_frag
            text = _description_for(spec, eff, lang) if wants_string else ""
            needs_string = wants_string and bool(str(text).strip())
            # 描述正文为空（例如 raw_text 只有段首编号「①」）时**不分配槽位**：
            # 引用一个空 str 槽会让卡文提示显示 ???，比不写 Description 更糟。
            # cdb 的 texts 只有 str1..str16 —— 超过 16 条需要描述的效果也不再分配
            # Stringid，否则 check_stringid_sync 会抓到「引用了空槽位」。
            # 降级只影响发动菜单里的提示文字，效果照样注册与结算。
            if wants_string and not needs_string:
                text = ""
            if needs_string and str_index >= 16:
                needs_string = False
            slot = _Slot(kind=str(eff.kind), eff=eff, box=box,
                         fragment=frag_name if has_frag else "",
                         needs_string=needs_string, wants_string=wants_string,
                         string_index=str_index if needs_string else -1,
                         string_text=text,
                         rule_text=bool(k and k.is_rule_text))
            if needs_string:
                str_index += 1
            slots.append(slot)
    return slots


_FRAGMENT_NAMES: set = set()


def _sync_fragment_names() -> None:
    from . import fragments as F
    _FRAGMENT_NAMES.clear()
    _FRAGMENT_NAMES.update(F.FRAGMENTS.keys())


# ══════════════════════════════════════════════════════════════════════
#  卡种骨架
# ══════════════════════════════════════════════════════════════════════
#: 不需要脚本的卡种 —— 与 ``cardforge/export/expansions.py`` 的 ``_VANILLA_FRAMES``
#: 保持同一份口径（导出层按这个集合决定「缺脚本」是否算问题）。
#: 按 **frame 键**判，不用 ``frame_def.base``：实测 ``FRAMES["normal"].base`` 是
#: ``"effect"``，照 base 判会把通常怪兽误判成需要脚本。
VANILLA_FRAMES: tuple[str, ...] = ("normal", "normal_pendulum", "token")


def _is_vanilla(spec: CardSpec) -> bool:
    """通常怪兽 / 通常灵摆 / 衍生物：官方不给这类卡脚本（引擎连文件都不找）。

    衍生物即使 IR 里带了效果也不出脚本 —— 衍生物的行为由**召唤它的那张卡**的
    脚本负责（``Duel.CreateToken`` + 那边的 ``ssummon_token`` 片段），
    给衍生物本身出脚本会和导出层的 ``needs_script`` 判断打架。
    """
    return spec.frame in VANILLA_FRAMES


def _header(spec: CardSpec, tier: int, notes: list) -> str:
    """长注释头：卡名 + 生成信息 + 降级清单（``--[==[ … ]==]`` 不会被词法器误读）。"""
    name = spec.display_name or spec.name or f"c{spec.id}"
    lines = [f"--[==[ {name}",
             f"     CardForge 2.0 生成 · 卡种={spec.frame_def.zh_cn}"
             f"（frame={spec.frame}） · tier={tier}",
             f"     由效果 IR 投影而来；效果种类缺失的部分以 -- [CardForge] 注释标出。"]
    for n in notes:
        lines.append(f"     ⚑ {n}")
    lines.append("]==]")
    return "\n".join(lines)


def _monster_activation_skeleton(ctx: LuaCtx, spec: CardSpec) -> list:
    """怪兽卡骨架不需要额外前置行（召唤流程由 :func:`summon_procedure_lines` 给）。"""
    return []


def _spelltrap_opening(ctx: LuaCtx, spec: CardSpec) -> list:
    """魔法/陷阱：先注册「可以从手卡发动」这一件事。

    官方永续魔法/永续陷阱/场地魔法需要一条 ``EFFECT_TYPE_ACTIVATE + EVENT_FREE_CHAIN``
    的激活效果，否则表侧表示在场上的持续效果不会生效；
    装备魔法由 ``aux.AddEquipProcedure`` 负责，速攻/反击由卡种本身获得 2 速。
    """
    kind = spec.spell_kind if spec.frame == "spell" else spec.trap_kind
    if spec.frame == "spell" and kind == "equip":
        return []          # AddEquipProcedure 已经带了激活效果
    if spec.frame == "trap" and kind == "counter":
        return []          # 反击陷阱的效果自己就是 EVENT_TYPE_QUICK_F
    if kind in ("continuous", "field"):
        v = f"e{ctx.slot}"
        lines = [f"{TAB}--可以从手卡放置/发动（永续类必须有这条激活效果）",
                 f"local {v}=Effect.CreateEffect(c)",
                 f"{v}:SetType(EFFECT_TYPE_ACTIVATE)",
                 f"{v}:SetCode(EVENT_FREE_CHAIN)",
                 f"c:RegisterEffect({v})"]
        ctx.slot += 1
        return lines
    return []


def _skill_opening(ctx: LuaCtx, spec: CardSpec) -> list:
    return skill_skeleton_lines(ctx, spec)


# ══════════════════════════════════════════════════════════════════════
#  单条效果 → 注册块
# ══════════════════════════════════════════════════════════════════════
def _emit_effect(ctx: LuaCtx, eff: EffectSpec, spec: CardSpec, *,
                 tier: int = 1) -> str:
    """调用对应片段；没有片段 / 片段报错 → 降级成注释。"""
    k = effect_kind(eff.kind)
    if k is None or not k.lua_fragment:
        return degrade(eff, ctx, "暂无脚本片段（kind 未登记 lua_fragment）"
                         if k else "kind 不在效果注册表里")
    fn = fragment(eff.kind)
    if fn is None:
        return degrade(eff, ctx, f"片段 {k.lua_fragment} 未在 FRAGMENTS 里实现")
    ctx.slot += 1
    ctx.box = "pendulum" if _in_pendulum_box(spec, eff) else "monster"
    try:
        return fn(eff, spec, ctx)
    except Exception as e:                      # 片段内部出错也不能让整次生成崩掉
        ctx.note(f"片段 {k.lua_fragment} 生成失败：{type(e).__name__}: {e}")
        return degrade(eff, ctx, f"片段生成异常（{type(e).__name__}），已降级为注释")


def _in_pendulum_box(spec: CardSpec, eff: EffectSpec) -> bool:
    pend = {int(i) for i in (spec.pendulum_effect_indices or [])}
    try:
        return int(eff.index) in pend
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════════
#  对外主接口
# ══════════════════════════════════════════════════════════════════════
def emit_script(spec: CardSpec, *, tier: int = 1) -> str:
    """生成整份 Lua 脚本（**UTF-8 无 BOM**、行尾 ``\\n``、制表符缩进）。

    ``tier`` 语义：

    * ``tier=1`` —— 只生成能确定性映射的内容：卡种骨架 + 召唤流程 +
      已有片段的效果；没有片段的效果写成 ``-- [CardForge] 效果 kind=xxx
      暂无脚本片段，需人工补写``，不产生任何猜测代码。
    * ``tier=2`` —— 同 tier=1，另外把 ``params`` 里额外给出的
      自定义条件（``params['condition']`` 之类）也拼进去（当前实现里
      两者等价，占位保留，便于以后扩展）。
    """
    _sync_fragment_names()
    if spec is None:
        return ""
    if _is_vanilla(spec):
        # 通常怪兽 / 无效果衍生物：官方没有脚本文件
        return ""

    ctx = LuaCtx(spec=spec, setcodes=setcode_literals(spec))
    slots = plan(spec, tier=tier)
    dropped = sum(1 for s in slots if s.get("wants_string") and not s["needs_string"])
    if dropped:
        ctx.note(f"有 {dropped} 条效果没能分到 aux.Stringid 槽位："
                 f"cdb 的 texts 只有 str1–str16。这些效果仍会正常注册与结算，"
                 f"只是发动菜单里没有提示文字 —— 官方卡不会这么设计，"
                 f"建议把卡拆开或精简卡文")
    body: list[str] = []
    tail_notes: list[str] = []

    # ① 召唤流程（灵摆 / 融合 / 同步 / 超量 / 连接 / 仪式 / 装备）
    proc_effect = _summon_source_effect(spec)
    proc_lines = summon_procedure_lines(ctx, spec, proc_effect)
    if proc_lines:
        body.extend(proc_lines)
        ctx.slot += 1
    body.extend(link_marker_lines(spec))
    if spec.frame == "skill":
        body.extend(_skill_opening(ctx, spec))
        ctx.slot += 1
    else:
        body.extend(_spelltrap_opening(ctx, spec))

    # ② 效果注册块（按槽位顺序；ctx.slot 已在上面推进过）
    for slot in slots:
        eff = slot["eff"]
        ctx.box = slot["box"]
        # 描述槽位由 plan 统一分配 → 片段里的 aux.Stringid(id, n) 直接取这个 n
        ctx.current_string = int(slot["string_index"])
        block = _emit_effect(ctx, eff, spec, tier=tier)
        if block:
            body.append(block)
    # ③ 装备魔法的装备目标过滤函数（依赖 slot 号，放在效果之后）
    ctx.slot += 1
    equip_filter_fn(ctx, spec, _equip_source_effect(spec))

    notes = list(ctx.notes)
    header = _header(spec, tier, notes)
    funcs = "\n".join(f"{src}\n" for _n, src in ctx.funcs)
    out = (f"{header}\n"
           f"local s,id=GetID()\n"
           f"function s.initial_effect(c)\n"
           + "\n".join(x for x in body if x) + "\n"
           + "end\n"
           + (f"s.listed_series={{{', '.join(ctx.setcodes)}}}\n"
              if ctx.setcodes else "")
           + ("\n" + funcs if funcs else ""))
    out = _normalize(out)
    # 描述槽写回 spec.strings（G2 的 check_stringid_sync 查的就是这个）
    _sync_strings(spec, [s["string_text"] for s in slots if s["needs_string"]])
    return out


def _summon_source_effect(spec: CardSpec) -> Optional[EffectSpec]:
    """找描述「本卡怎么被召唤」的那条效果（``*_summon`` + ``params['materials']``）。"""
    for eff in spec.effect_specs():
        k = str(eff.kind or "")
        if k.endswith("_summon") and (eff.params or {}).get("materials"):
            return eff
    for eff in spec.effect_specs():
        if str(eff.kind or "").endswith("_summon"):
            return eff
    return None


def _equip_source_effect(spec: CardSpec) -> Optional[EffectSpec]:
    for eff in spec.effect_specs():
        if str(eff.kind or "") in ("gain_atk", "take_control", "equip"):
            return eff
    return spec.effect_specs()[0] if spec.effects else None


def _sync_strings(spec: CardSpec, strings: list) -> None:
    """把生成的描述写回 ``spec.strings``（str1..str16，绝不越界）。"""
    try:
        spec.strings = [str(s) for s in (strings or [])][:16]
    except Exception:
        pass


def _normalize(lua: str) -> str:
    """行尾统一 ``\\n``、去掉行尾空白、制表符缩进、确保末尾单个换行、无 BOM。"""
    text = (lua or "").lstrip("\ufeff")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln.rstrip() for ln in text.split("\n")]
    # 折叠连续空行（最多留一行），方便人读
    out: list[str] = []
    for ln in lines:
        if not ln and out and not out[-1]:
            continue
        out.append(ln)
    return "\n".join(out).strip("\n") + "\n"


def emit_strings(spec: CardSpec, lang: str = "zh_cn") -> list:
    """生成 cdb ``texts.str1..str16`` 用的效果描述列表。

    **直接取 :func:`plan` 算好的 ``string_text``**（plan 的编号规则见其 docstring：
    灵摆效果框先、怪兽效果框后，只给不入连锁以外的激活效果编号，超过 16 槽截断），
    因此第 ``n`` 项必然对应脚本里的 ``aux.Stringid(id, n)``，
    与 :func:`emit_script` 不可能各走各的顺序。
    """
    _sync_fragment_names()
    if spec is None or _is_vanilla(spec):
        return []
    out = [slot["string_text"] for slot in plan(spec, lang=lang) if slot["needs_string"]]
    return out[:16]


def _description_for(spec: CardSpec, eff: EffectSpec, lang: str) -> str:
    """一条描述文本：作者原文 → 卡文模板（剥掉段首编号）。"""
    p = eff.params or {}
    if p.get("desc"):
        return str(p["desc"])
    if eff.raw_text:
        from .fragments import _strip_number
        return _strip_number(str(eff.raw_text))
    try:
        from ..psct import gen
        from .fragments import _strip_number
        idx = int(eff.index) + 1
        return _strip_number(gen.effect_to_text(eff, spec, lang, index=idx))
    except Exception:
        return str(eff.kind or "")


def write_script(spec: CardSpec, path: Optional[str] = None) -> str:
    """把脚本落盘（**UTF-8 无 BOM**），返回实际写入的路径。

    ``path`` 缺省用 ``core.paths.script_path(spec.id)``
    （即 ``workspace/script/c<id>.lua``）。同时把产物写进 ``spec.lua``，
    让 G2/导出直接读规格对象就能拿到脚本。
    """
    if spec is None:
        return ""
    lua = getattr(spec, "lua", "") or emit_script(spec)
    spec.lua = lua
    if not lua.strip():
        # 通常怪兽 / 通常灵摆 / 衍生物：官方卡包里没有这个文件，落一个 0 字节
        # 空脚本会让 EDOPro 报「脚本加载失败」，所以直接不写。
        return ""
    target = Path(path) if path else paths.script_path(int(spec.id or 0))
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    try:
        target.write_bytes(lua.encode("utf-8"))      # 不写 BOM
    except OSError as e:
        from ...core.errors import EnvError
        raise EnvError(f"脚本写入失败：{e}", hint="检查 workspace/script 目录权限") from e
    return str(target)
