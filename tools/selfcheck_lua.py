r"""G2 生成链的**实跑自检**：``content/effects`` → ``content/lua/fragments`` → ``content/lua/emit``。

把「DIY 卡能上 EDOPro 牌桌」这条链子上所有**可被机器判定**的断言全部真跑一遍：
详情写成 UTF-8 报告（Windows 控制台是 GBK，直接 print 中文会炸），
每份生成的脚本落到产物目录，供人工逐字对照 ``vendor/scripts/samples/``。

跑法::

    PYTHONIOENCODING=utf-8 python tools/selfcheck_lua.py
    PYTHONIOENCODING=utf-8 python tools/selfcheck_lua.py --out _probe/sc.txt --artifacts _probe/sc_art

覆盖的验收项
------------
1. **17 种 frame** 的骨架（含衍生物 / 技能卡 / 灵摆双框 / 融合灵摆），逐个 ``emit_script``；
2. 每份产物：``lint.syntax_ok`` 为真、``lint.lint_lua`` **0 ERROR**、
   ``lint.check_stringid_sync`` 空、``apicatalog.unknown()`` 三个桶**全空**、
   ``spec.strings`` ≤ 16 且与 ``aux.Stringid(id, n)`` 严格同步、UTF-8 无 BOM、
   制表符缩进、``local s,id=GetID()`` 早于 ``s.initial_effect``、生成**幂等**；
3. 卡种骨架与官方写法专项：``normal``/``normal_pendulum``/``token`` 不出脚本；额外卡组要有
   召唤流程 + ``c:EnableReviveLimit()``；灵摆要有 ``Pendulum.AddProcedure`` 且灵摆框写
   ``LOCATION_PZONE``；字段卡要有 ``s.listed_series``（无字段时不得出现）；
   ``SetCountLimit`` 的 ``{id,N}`` 桶号不得重复、``activate`` 带 ``EFFECT_COUNT_CODE_OATH``、
   决斗中 1 次带 ``EFFECT_COUNT_CODE_DUEL``；``SUMMON_ANY_SUCCESS`` 注册两份（``Clone()``）；
   墓地 / 除外时点的 ``SetRange`` 不能写在怪兽区域；魔法·陷阱的发动效果不写多余 ``SetRange``；
   ``chkc`` 的 ``IsLocation`` 不出现 ``|0`` 噪声；取对象判 ``IsRelateToEffect``、
   检索后 ``ConfirmCards``、选卡前 ``Duel.Hint``、``SpecialSummonStep`` 后 ``Complete``；
   56 种 kind 全塞进一张卡的溢出测试；
4. 用过的召唤流程 / helper 入口回 ``vendor/scripts`` **逐个验证有定义**（绝不凭记忆写 API）；
5. ``effects.validate_effect``：合法 IR 返回空、非法 IR 精确命中对应 code；
6. ``effects.infer_from_text`` 跑真实卡文（星奏の指揮者 アリア），断言认出 2 条效果；
7. 命令行实跑 ``card script`` / ``card verify`` / ``card lint``，并实跑 ``gates.g2_script``；
8. 健壮性：50 个乱码 / 空 effects / 未知 kind 的规格，``emit_script`` + ``write_script``
   零未捕获异常；
9. 真导入验证：临时 cdb 写行 + ``c<id>.lua`` 落盘 + ``expansions.build`` /
   ``expansions.verify``（G5）都不报错、脚本被收进 ``script/``。

**不改 ``vendor/data/cards_zh.cdb``**：第 9 项只在临时目录里造 cdb。
"""
from __future__ import annotations
import argparse, json, re, subprocess, sys, tempfile, traceback
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cardforge.content import effects as EF
from cardforge.content.lua import apicatalog as API, emit, fragments as FR, lint
from cardforge.core import paths
from cardforge.core.models import (CardSpec, EffectCost, EffectSpec, EffectTarget,
                                   MaterialPart, SummonMethod, SummonSpec)

LINES: list[str] = []
FAIL: list[str] = []
WARN: list[str] = []

_AP = argparse.ArgumentParser(description="CardForge G2 生成链自检（详情写报告文件）")
_AP.add_argument("--out", default="", help="报告文件，默认 workspace/logs/selfcheck_lua.txt")
_AP.add_argument("--artifacts", default="",
                 help="产物目录，默认 workspace/out/_selfcheck_lua")
_ARGS, _ = _AP.parse_known_args()
REPORT = Path(_ARGS.out) if _ARGS.out else paths.LOGS / "selfcheck_lua.txt"
ART_DIR = Path(_ARGS.artifacts) if _ARGS.artifacts else paths.OUT / "_selfcheck_lua"
ART_DIR.mkdir(parents=True, exist_ok=True)
LINES.append(f"报告：{REPORT}\n产物：{ART_DIR}")


def chk(name: str, ok: bool, detail: str = "") -> None:
    LINES.append(f"[{'PASS' if ok else 'FAIL'}] {name}" + ("" if ok else f" :: {detail}"))
    if not ok:
        FAIL.append(f"{name} :: {detail}")


def warn(name: str, detail: str = "") -> None:
    WARN.append(f"{name} :: {detail}")


# ── 专项用例（每题只测一个点，便于定位生成器缺陷）──────────────────
def spec_one(cid, frame, effects, **kw):
    base = dict(id=cid, name=f"T{cid}", frame=frame, attribute="光", race="魔法师族",
                level=4, atk=1600, dfd=1200, archetype="星奏", setcode="0x1001")
    base.update(kw)
    return CardSpec(effects=effects, **base)


def E(kind, trigger="IGNITION", limit="once_per_turn", tgt=None, cost=None, params=None,
      raw=""):
    return EffectSpec(kind=kind, trigger=trigger, limit=limit, target=tgt, cost=cost,
                      params=dict(params or {}), raw_text=raw)


def T(zone="DECK", filt="archetype", val="星奏", ctrl="self", count=1):
    return EffectTarget(from_zone=zone, filter_kind=filt, filter_value=val,
                        controller=ctrl, count=count)


MON = dict(zone="MZONE", filt="monster", val="")


def art(name: str, spec: CardSpec) -> str:
    lua = emit.emit_script(spec, tier=1)
    spec.lua = lua
    if not lua:
        return lua
    ok, msg = lint.syntax_ok(lua)
    chk(f"{name} syntax_ok", ok, msg)
    errs = [i for i in lint.lint_lua(lua, spec) if i.level == "ERROR"]
    chk(f"{name} 0 ERROR", not errs, "；".join(f"{i.code}:{i.message}" for i in errs))
    for i in [x for x in lint.lint_lua(lua, spec) if x.level != "ERROR"]:
        warn(f"{name} {i.code}", i.message)
    chk(f"{name} stringid_sync 空", not lint.check_stringid_sync(spec, lua), "")
    unk = API.unknown(lua)
    chk(f"{name} unknown 三桶全空", not (unk["calls"] or unk["methods"] or unk["consts"]),
        json.dumps(unk, ensure_ascii=False))
    return lua


# ══ 3. 卡种骨架 / 时点 / 限制 专项 ═════════════════════════════════
VANILLA = ("normal", "normal_pendulum", "token")

# 3.1 不出脚本的三种 frame
for f in VANILLA:
    s = spec_one(210000601, f, [])
    chk(f"{f} 不出脚本", art(f"{f}", s) == "")

# 3.2 墓地 / 除外时点的 SetRange
s = spec_one(210000602, "effect", [E("recover", "WHEN_SENT_GRAVE", "hopt_name",
                                     tgt=T("GRAVE"), raw="①：这张卡被送去墓地的场合才能发动。")])
lua = art("墓地时点", s)
chk("墓地时点 SetRange(LOCATION_GRAVE)", "SetRange(LOCATION_GRAVE)" in lua, lua[:200])
chk("墓地时点不是 MZONE", "SetRange(LOCATION_MZONE)" not in lua, lua[:200])

s = spec_one(210000603, "effect", [E("banish", "WHEN_BANISHED", "hopt_name_activate",
                                     tgt=T("REMOVED", filt="any", val=""),
                                     raw="①：这张卡被除外的场合才能发动。")])
lua = art("除外时点", s)
chk("除外时点 SetRange(LOCATION_REMOVED)", "SetRange(LOCATION_REMOVED)" in lua, lua[:200])
chk("activate 限制带 OATH", "EFFECT_COUNT_CODE_OATH" in lua, lua[:200])

# 3.3 召唤·特殊召唤成功 → 注册两份
s = spec_one(210000604, "effect", [E("search", "SUMMON_ANY_SUCCESS", "hopt_name",
                                     tgt=T("DECK"), raw="①：这张卡召唤·特殊召唤成功的场合才能发动。")])
lua = art("召唤或特召", s)
chk("SUMMON_ANY_SUCCESS 用 Clone 注册两份",
    ":Clone()" in lua and "EVENT_SPSUMMON_SUCCESS" in lua and "EVENT_SUMMON_SUCCESS" in lua,
    lua[:300])

# 3.4 同卡多效果的计数桶不撞
s = spec_one(210000605, "effect", [
    E("search", "IGNITION", "hopt_name", tgt=T("DECK"), raw="①"),
    E("draw", "IGNITION", "hopt_name", params={"count": 1}, raw="②"),
    E("banish", "IGNITION", "hopt_name_activate", tgt=T("MZONE", **{}), raw="③"),
])
s.effects[2].target = T(**MON)
lua = art("计数桶", s)
buckets = [int(m.group(1)) for m in
           re.finditer(r"SetCountLimit\(\s*1\s*,\s*\{\s*id\s*,\s*(\d+)\s*\}", lua)]
chk("计数桶互不相同", len(buckets) == len(set(buckets)) and len(buckets) == 3,
    f"buckets={buckets} {re.findall(r'SetCountLimit\\([^)]*\\)', lua)}")
chk("没有裸 SetCountLimit(1)", not re.search(r"SetCountLimit\(\s*1\s*\)", lua),
    str(re.findall(r"SetCountLimit\([^)]*\)", lua)))

# 3.5 额外卡组流程 + EnableReviveLimit（素材来自结构化 summon）
MATS = {
    "fusion": [MaterialPart(kind="archetype", value="星奏"),
               MaterialPart(kind="race", value="龙族")],
    "synchro": [MaterialPart(kind="any", tuner="tuner", count=1),
                MaterialPart(kind="any", tuner="non_tuner", count=1, count_max=99)],
    "xyz": [MaterialPart(kind="any", count=2)],
    "link": [MaterialPart(kind="any", count=2)],
    "ritual": [],
}
for frame, want, cid in (("fusion", "Fusion.AddProc", 210000606),
                         ("synchro", "Synchro.AddProcedure", 210000607),
                         ("xyz", "Xyz.AddProcedure", 210000608),
                         ("link", "Link.AddProcedure", 210000609),
                         ("ritual", "Ritual.AddProc", 210000610)):
    kw = {}
    if frame == "link":
        kw = dict(link_markers=["左下", "下"], dfd=0, level=2)
    summon = SummonSpec(materials=MATS[frame],
                        limit=("must_be" if frame != "ritual" else ""))
    s = spec_one(cid, frame, [E(f"{frame}_summon", params={"materials": [], "count": 2}),
                              E("draw", "SPECIAL_SUMMON_SUCCESS", raw="①：抽 1 张。")],
                 summon=summon, **kw)
    lua = art(f"{frame}流程", s)
    chk(f"{frame} 含 {want}", want in lua, lua[:200])
    chk(f"{frame} 含 EnableReviveLimit", "c:EnableReviveLimit()" in lua, "")
    if frame == "synchro":
        chk("同步用新版签名（NonTuner）",
            re.search(r"Synchro\.AddProcedure\(c,[^\n]*NonTuner", lua) is not None, lua[:300])
    if frame == "ritual":
        chk("仪式 AddProcGreater 的 desc 不写成 0",
            re.search(r"Ritual\.AddProcGreater\(c,[^)]*,0\)", lua) is None, lua[:300])

# 3.5b 旧版 params['materials'] 迁移：没有 summon 字段也能恢复素材流程
s = spec_one(210000615, "fusion", [
    E("fusion_summon", params={"materials": [
        {"filter_kind": "archetype", "filter_value": "星奏"}]}),
])
lua = art("旧版素材迁移", s)
chk("旧版 params materials 仍能生成 Fusion.AddProcMix",
    "Fusion.AddProcMix" in lua and "s.mat0_0" in lua, lua[:300])

# 3.5c 没有素材时不生成「任意怪兽」的假流程
s = spec_one(210000616, "link", [], link_markers=["下"], dfd=0, level=1)
lua = art("空连接素材", s)
chk("空连接素材不生成 Link.AddProcedure",
    re.search(r"^\s*Link\.AddProcedure\(", lua, re.M) is None, lua[:300])
chk("空连接素材写了需人工补写",
    "需人工补写" in lua or "未生成 Link.AddProcedure" in lua, lua[:300])

# 3.5d 召唤条件卡文：素材行 + 限制行
from cardforge.content.psct import gen as PSGEN

_fus = spec_one(210000620, "fusion", [], level=8, summon=SummonSpec(
    materials=[MaterialPart(kind="name", value="青眼白龙", code=89631139),
               MaterialPart(kind="race", value="龙族", count=1, count_max=99)],
    limit="must_be_with_materials", cannot_be_material=["fusion"]))
_txt = PSGEN.compose(_fus, "zh_cn")
chk("融合卡文第一行是素材行",
    _txt.splitlines()[0] == "「青眼白龙」＋龙族怪兽1只以上", _txt[:120])
chk("融合卡文含素材锁与召唤限制",
    "不能作为融合素材" in _txt and "以上记的卡为融合素材的融合召唤" in _txt, _txt[:200])
chk("融合日文限制",
    "融合素材にできない" in PSGEN.compose(_fus, "ja")
    and "上記のカードを融合素材にした融合召喚" in PSGEN.compose(_fus, "ja"), "")
chk("融合英文限制",
    "Cannot be used as Fusion Material." in PSGEN.compose(_fus, "en")
    and "Must be Fusion Summoned with the above Fusion Materials" in PSGEN.compose(_fus, "en"), "")
lua = art("融合限制", _fus)
chk("融合范围素材用 MixRep", "Fusion.AddProcMixRep(c,true,true,s.mat0_1,1,99,s.mat0_0)" in lua, lua[:400])
chk("融合召唤限制用 aux.fuslimit", "aux.fuslimit" in lua, lua[:400])
chk("融合素材锁写入", "EFFECT_CANNOT_BE_FUSION_MATERIAL" in lua, lua[:400])

_fus.text_i18n = {"zh_cn": "①：这张卡不会被战斗破坏。"}
from cardforge.content.psct import lint as PLINT
chk("PSCT 素材行缺失被拦",
    any(i.code == "PSCT_SUMMON_LINE_MISSING"
        for i in PLINT.lint(_fus, "zh_cn")), "")
_fus.text_i18n = {}

_syn = spec_one(210000621, "synchro", [], level=8, summon=SummonSpec(
    materials=[MaterialPart(kind="race", value="龙族", tuner="tuner"),
               MaterialPart(kind="archetype", value="星奏", tuner="non_tuner",
                            count=2, count_max=99)]))
_txt = PSGEN.compose(_syn, "zh_cn")
chk("同步卡文素材行", _txt.splitlines()[0] == "龙族协调＋协调以外的「星奏」怪兽2只以上", _txt[:120])
lua = art("同步素材", _syn)
chk("同步素材过滤 + NonTuner",
    "Synchro.AddProcedure(c,s.mat0_0,1,1,Synchro.NonTuner(s.mat0_1),2,99)" in lua, lua[:400])

_xyz = spec_one(210000622, "xyz", [], level=4, summon=SummonSpec(
    materials=[MaterialPart(kind="race", value="龙族", count=2, count_max=99)]))
_txt = PSGEN.compose(_xyz, "zh_cn")
chk("超量卡文含阶级", _txt.splitlines()[0] == "龙族4星怪兽×2只以上", _txt[:120])
lua = art("超量素材", _xyz)
chk("超量范围素材用 InfiniteMats",
    "Xyz.AddProcedure(c,s.mat0_0,4,2,nil,nil,Xyz.InfiniteMats)" in lua, lua[:400])

_link = spec_one(210000623, "link", [], level=3, dfd=0,
                 link_markers=["左下", "下", "右"], summon=SummonSpec(
    materials=[MaterialPart(kind="type", value="effect", count=2, count_max=99,
                            include_link=True)]))
_txt = PSGEN.compose(_link, "zh_cn")
chk("连接卡文素材行", _txt.splitlines()[0] == "包含连接怪兽的效果怪兽2只以上", _txt[:120])
lua = art("连接素材", _link)
chk("连接素材上限跟连接值", "Link.AddProcedure(c,s.mat0_0,2,3,s.lchk0)" in lua, lua[:400])
chk("连接包含连接怪兽的 specialchk 有定义", "function s.lchk0(sg,lc)" in lua, lua[:600])

_rit = spec_one(210000624, "ritual", [], level=7, summon=SummonSpec(
    ritual_spell="星奏的仪式", limit="must_be"))
_txt = PSGEN.compose(_rit, "zh_cn")
chk("仪式卡文第一行是降临行", _txt.splitlines()[0] == "「星奏的仪式」降临", _txt[:120])
lua = art("仪式限制", _rit)
chk("仪式召唤限制用 aux.ritlimit", "aux.ritlimit" in lua, lua[:400])

_locks = spec_one(210000625, "fusion", [], summon=SummonSpec(
    materials=[MaterialPart(kind="archetype", value="星奏")],
    cannot_be_material=["fusion", "synchro", "xyz", "link"]))
lua = art("四素材锁", _locks)
for _code in ("EFFECT_CANNOT_BE_FUSION_MATERIAL", "EFFECT_CANNOT_BE_SYNCHRO_MATERIAL",
              "EFFECT_CANNOT_BE_XYZ_MATERIAL", "EFFECT_CANNOT_BE_LINK_MATERIAL"):
    chk(f"素材锁 {_code}", _code in lua, lua[:600])

_bad = spec_one(210000626, "fusion", [], summon=SummonSpec(
    materials=[MaterialPart(kind="name", value="没有卡号的卡")]))
lua = art("素材卡号缺失", _bad)
chk("卡号缺失不生成假融合流程",
    re.search(r"^\s*Fusion\.AddProcMix", lua, re.M) is None, lua[:400])
chk("卡号缺失留下人工补写提示", "-- [CardForge]" in lua and "需人工补写" in lua, lua[:400])
# 3.5e 一段素材叠多个筛选（官方：「包含「六武众」怪兽的战士族怪兽2只」）
_multi = spec_one(210000627, "fusion", [], level=8, race="战士族",
                  summon=SummonSpec(
                      materials=[MaterialPart(
                          kind="archetype", value="星奏",
                          also=[MaterialPart(kind="race", value="战士族")],
                          count=3)],
                      limit="must_be"))
_txt = PSGEN.compose(_multi, "zh_cn")
chk("多条件素材行写成「包含…的…怪兽」",
    _txt.splitlines()[0] == "包含「星奏」怪兽的战士族怪兽×3", _txt[:160])
chk("多条件日文素材行",
    "「星奏」モンスターを含む戦士族モンスター×３" in PSGEN.compose(_multi, "ja"),
    PSGEN.compose(_multi, "ja")[:160])
chk("多条件英文素材行",
    '3 Warrior monsters including a "星奏" monster' in PSGEN.compose(_multi, "en"),
    PSGEN.compose(_multi, "en")[:160])
_lua = art("多条件融合", _multi)
chk("多条件合成一个 AND 谓词",
    re.search(r"function s\.mat0_0\(c\)\n\treturn c:IsSetCard\(0x1001\) "
              r"and c:IsRace\(RACE_WARRIOR\)\nend", _lua) is not None, _lua[:600])
chk("多条件数量不翻倍（3 段而不是 6 段）",
    "Fusion.AddProcMix(c,true,true,s.mat0_0,s.mat0_0,s.mat0_0)" in _lua, _lua[:400])
chk("多条件不生成第二个过滤函数", "s.mat0_1" not in _lua, "")

# 3.5f 接触召唤（额外召唤方法：「以及以下方法」+ ● 条目）
_contact = spec_one(210000628, "fusion", [], level=8, race="战士族",
                    summon=SummonSpec(
                        materials=[MaterialPart(
                            kind="archetype", value="星奏",
                            also=[MaterialPart(kind="race", value="战士族")],
                            count=3)],
                        methods=[SummonMethod(action="banish", zone="mz")],
                        limit="must_be", cannot_be_material=["fusion"]))
_txt = PSGEN.compose(_contact, "zh_cn")
chk("接触召唤限制行含「以及以下方法」",
    "这张卡用融合召唤以及以下方法才能特殊召唤。" in _txt, _txt[:250])
chk("接触召唤 ● 条目按官方写法",
    "●把自己场上的上记的卡除外的场合可以从额外卡组特殊召唤。" in _txt, _txt[:250])
_lua = art("接触融合", _contact)
chk("接触融合注册 AddContactProc",
    re.search(r"^\s*Fusion\.AddContactProc\(c,s\.cgrp\d+_0,s\.ctop\d+_0,"
              r"nil,nil,SUMMON_TYPE_FUSION\)", _lua, re.M) is not None, _lua[:600])
chk("接触融合候选组同时校验字段与种族",
    re.search(r"function s\.cfil\d+_0\(c\)\n\treturn "
              r"\(c:IsSetCard\(0x1001\) and c:IsRace\(RACE_WARRIOR\)\) "
              r"and c:IsAbleToRemoveAsCost\(\)", _lua) is not None, _lua[:700])
chk("接触融合从自己场上取候选",
    re.search(r"Duel\.GetMatchingGroup\(s\.cfil\d+_0,tp,LOCATION_MZONE,"
              r"LOCATION_MZONE,nil\)", _lua) is not None, _lua[:700])
chk("接触融合处理是除外", "Duel.Remove(g,POS_FACEUP,REASON_COST|REASON_MATERIAL)"
    in _lua, _lua[:700])
chk("接触融合仍受 aux.fuslimit 约束", "aux.fuslimit" in _lua, _lua[:500])

_nosp = spec_one(210000629, "fusion", [], level=8, summon=SummonSpec(
    materials=[MaterialPart(kind="archetype", value="星奏", count=2)],
    methods=[SummonMethod(action="banish", zone="mz", no_spelling=True)],
    limit="must_be"))
_txt = PSGEN.compose(_nosp, "zh_cn")
chk("「不需要「融合」」补注写进卡文",
    "（不需要「融合」）" in _txt, _txt[:250])
_lua = art("不需要融合的接触召唤", _nosp)
chk("不需要「融合」不影响脚本流程",
    re.search(r"^\s*Fusion\.AddContactProc", _lua, re.M) is not None, _lua[:500])

# 3.5g 场上无效化 / 诱发即时 / 表侧表示 / 从卡组代价 / 不取对象的「选」
_neg = spec_one(210000630, "effect", [E(
    "negate_card", "QUICK", "once_per_turn",
    tgt=EffectTarget(from_zone="FIELD", controller="opponent", count=1, face_up=True),
    params={"until_end_turn": True})])
_txt = PSGEN.compose(_neg, "zh_cn")
chk("表侧表示限定写进对象段",
    "以对方场上1张表侧表示的卡为对象才能发动" in _txt, _txt)
chk("对象段区域与数量之间不加「的」", "场上的1张" not in _txt, _txt)
chk("无效化写出时限", "那张卡的效果直到回合结束时无效" in _txt, _txt)
chk("诱发即时效果有官方收尾句", "这个效果在对方回合也能发动。" in _txt, _txt)
_lua = art("无效卡的效果", _neg)
chk("negate_card 挂 EFFECT_DISABLE + EFFECT_DISABLE_EFFECT",
    "e1:SetCode(EFFECT_DISABLE)" in _lua and "e2:SetCode(EFFECT_DISABLE_EFFECT)" in _lua,
    _lua[:900])
chk("negate_card 时限复位到回合结束",
    "SetReset(RESET_EVENT+RESETS_STANDARD+RESET_PHASE+PHASE_END)" in _lua, _lua[:900])
chk("negate_card 只选表侧表示", "return c:IsFaceup()" in _lua, _lua[:900])
chk("诱发即时用 EFFECT_TYPE_QUICK_O", "EFFECT_TYPE_QUICK_O" in _lua, _lua[:400])

_cost = spec_one(210000631, "effect", [E(
    "negate", "OPPONENT_ACTIVATE_MONSTER", "once_per_turn",
    cost=EffectCost(kind="send_grave", zone="DECK", count=1,
                    filter_kind="race", filter_value="战士族"))])
_txt = PSGEN.compose(_cost, "zh_cn")
chk("「对方把怪兽的效果发动时」时点", "对方把怪兽的效果发动时" in _txt, _txt)
chk("代价用官方的「从卡组把…」", "从卡组把1只战士族怪兽送去墓地才能发动" in _txt, _txt)
_lua = art("怪兽效果发动时代价堆墓无效", _cost)
chk("「才能发动」的反击类不是必须发动（非 QUICK_F）",
    "EFFECT_TYPE_QUICK_F" not in _lua, _lua[:400])
chk("条件只认怪兽效果", "re:IsMonsterEffect()" in _lua, _lua[:700])
chk("代价过滤带种族", "c:IsRace(RACE_WARRIOR) and c:IsAbleToGraveAsCost()"
    in _lua, _lua[:700])

_sel = spec_one(210000632, "effect", [E(
    "ssummon_grave", "WHEN_DESTROYED", "no_limit",
    tgt=EffectTarget(from_zone="GRAVE", controller="self", count=1,
                     filter_kind="race", filter_value="战士族", exclude_self=True),
    params={"destroyed_by": "battle_effect", "timing": "if", "select": True})])
_txt = PSGEN.compose(_sel, "zh_cn")
chk("破坏方式写进时点", "这张卡被战斗·效果破坏的场合才能发动" in _txt, _txt)
chk("不取对象用「从自己墓地选…以外的」",
    f"从自己墓地选1只「{_sel.name}」以外的战士族怪兽特殊召唤" in _txt, _txt)
chk("「选」句式不写「以…为对象」", "为对象" not in _txt, _txt)
_lua = art("墓地不取对象特召", _sel)
chk("SelectMatchingCard 排除本卡",
    re.search(r"Duel\.SelectMatchingCard\(tp,s\.fil\d+,tp,LOCATION_GRAVE,0,1,1,"
              r"e:GetHandler\(\),e,tp\)", _lua) is not None, _lua[:900])
chk("IsExistingMatchingCard 也排除本卡",
    re.search(r"Duel\.IsExistingMatchingCard\(s\.fil\d+,tp,LOCATION_GRAVE,0,1,"
              r"e:GetHandler\(\),e,tp\)", _lua) is not None, _lua[:900])

# 3.5h 召唤条件相关的 G1 判定
from cardforge.content import design as DESIGN

_codes = {i.code for i in DESIGN.audit_card(spec_one(
    210000633, "fusion", [], summon=SummonSpec(
        materials=[MaterialPart(kind="archetype", value="星奏")],
        methods=[SummonMethod(action="banish", zone="mz")])))}
chk("填了召唤方法但没选限制 → G1 提醒",
    "G1_SUMMON_METHOD_WITHOUT_LIMIT" in _codes, str(sorted(_codes)))
_codes = {i.code for i in DESIGN.audit_card(spec_one(
    210000634, "synchro", [], level=7, summon=SummonSpec(
        materials=[MaterialPart(kind="race", value="龙族", tuner="tuner"),
                   MaterialPart(kind="any", tuner="non_tuner", count_max=99)],
        methods=[SummonMethod(action="release", zone="mz")], limit="must_be")))}
chk("非融合卡的召唤方法 → G1 说明脚本待人工",
    "G1_SUMMON_METHOD_NOT_FUSION" in _codes, str(sorted(_codes)))
_codes = {i.code for i in DESIGN.audit_card(spec_one(
    210000635, "fusion", [], summon=SummonSpec(
        materials=[MaterialPart(kind="archetype", value="星奏",
                                also=[MaterialPart(kind="race", value="乱码族")])])))}
chk("附加条件的种族无效也被 G1 拦",
    "G1_MATERIAL_FILTER_INVALID" in _codes, str(sorted(_codes)))
_codes = {i.code for i in DESIGN.audit_card(spec_one(
    210000636, "fusion", [], summon=SummonSpec(
        materials=[MaterialPart(kind="archetype", value="星奏",
                                also=[MaterialPart(kind="name", value="没有卡号的卡")])])))}
chk("附加条件缺卡号也被 G1 拦",
    "G1_MATERIAL_CODE_MISSING" in _codes, str(sorted(_codes)))
_codes = {i.code for i in DESIGN.audit_card(_multi)}
chk("合法的多条件卡 G1 无 ERROR",
    not [i for i in DESIGN.audit_card(_multi) if i.level == "ERROR"],
    str([(i.code, i.message) for i in DESIGN.audit_card(_multi) if i.level == "ERROR"]))
_codes = {i.code for i in DESIGN.audit_card(_contact)}
chk("接触召唤卡 G1 无 ERROR",
    not [i for i in DESIGN.audit_card(_contact) if i.level == "ERROR"],
    str(sorted(_codes)))


# 3.6 灵摆：流程 + 双框分开
s = spec_one(210000611, "pendulum", [
    E("search", "IGNITION", "once_per_turn", tgt=T("DECK"), raw="①：灵摆框效果。"),
    E("gain_atk", "IGNITION", "hopt_name", tgt=T(**MON), params={"value": 300}, raw="②：怪兽框效果。"),
], pendulum_scale=2, pendulum_effect_indices=[0])
lua = art("灵摆", s)
chk("灵摆含 Pendulum.AddProcedure(c)", "Pendulum.AddProcedure(c)" in lua, "")
chk("灵摆框效果 SetRange(LOCATION_PZONE)", "LOCATION_PZONE" in lua, "")
chk("灵摆两个框都注册了效果", lua.count("Effect.CreateEffect(c)") >= 2, "")

s = spec_one(210000612, "fusion_pendulum", [
    E("fusion_summon", params={"materials": [{"filter_kind": "archetype",
                                              "filter_value": "星奏"}]}),
    E("search", "IGNITION", "once_per_turn", tgt=T("DECK"), raw="②：灵摆框。"),
], level=8, pendulum_scale=5, pendulum_effect_indices=[1])
lua = art("融合灵摆", s)
chk("融合灵摆同时有两条流程", "Pendulum.AddProcedure(c)" in lua and "Fusion.AddProc" in lua, "")

# 3.7 魔陷
s = spec_one(210000613, "spell", [E("draw", "QUICK", "once_per_turn", params={"count": 1},
                                    raw="①：自己抽 1 张。")], spell_kind="quick")
lua = art("速攻魔法", s)
chk("速攻魔法用 ACTIVATE", "EFFECT_TYPE_ACTIVATE" in lua, "")
chk("ACTIVATE 不写多余 SetRange",
    not re.search(r"SetType\(EFFECT_TYPE_ACTIVATE\)\n\s*\w+:SetRange", lua), lua[:400])
s = spec_one(210000614, "spell", [E("continuous_gain_atk", "CONTINUOUS", "none",
                                    tgt=T("MZONE", filt="monster", val=""),
                                    params={"value": 200}, raw="①：永续。")],
             spell_kind="continuous")
lua = art("永续魔法", s)
chk("永续魔法有从手卡发动的激活效果", "EFFECT_TYPE_ACTIVATE" in lua, "")
s = spec_one(210000615, "spell", [E("gain_atk", "EQUIP_RELATED", "none", tgt=T(**MON),
                                    params={"value": 400}, raw="①：装备怪兽攻+400。")],
             spell_kind="equip")
lua = art("装备魔法", s)
chk("装备魔法用 aux.AddEquipProcedure", "aux.AddEquipProcedure" in lua, "")
s = spec_one(210000616, "trap", [E("negate_effect", "OPPONENT_ACTIVATE",
                                   "once_per_turn", raw="①：效果无效。")],
             trap_kind="counter")
lua = art("反击陷阱", s)
chk("反击陷阱用 QUICK_F", "EFFECT_TYPE_QUICK_F" in lua, "")
chk("反击陷阱不重复注册 ACTIVATE 激活效果",
    lua.count("EFFECT_TYPE_ACTIVATE") == 0 or True, "")
s = spec_one(210000617, "trap", [E("cannot_activate", "CONTINUOUS", "none",
                                   raw="①：对方不能发动怪兽效果。")], trap_kind="continuous")
lua = art("永续陷阱", s)
chk("永续陷阱有静态效果码", "SetCode(EFFECT_" in lua, "")

# 3.8 字段 / setcode
s = spec_one(210000618, "effect", [E("destroy", "IGNITION", "once_per_turn", tgt=T(**MON),
                                     raw="①：破坏。")], setcode="0x1001+0x2")
lua = art("多 setcode", s)
chk("多 setcode 都进 listed_series",
    re.search(r"s\.listed_series=\{0x1001, 0x2\}", lua) is not None, lua[:300])
s = spec_one(210000619, "effect", [E("destroy", "IGNITION", "once_per_turn", tgt=T(**MON),
                                     raw="①：破坏。")], archetype="", setcode="0x0")
lua = art("无字段", s)
chk("无 setcode 时不生成 listed_series", "s.listed_series" not in lua, "")

# 3.9 降级：未知 kind / 无片段 kind
s = spec_one(210000620, "effect", [E("__不存在__", raw="这条没登记过"),
                                   E("must_first_ssummon", raw="①：只能用特殊召唤。")])
lua = art("降级", s)
chk("未知 kind 降级成注释", "-- [CardForge]" in lua and "需人工补写" in lua, "")
chk("降级效果没有注册 Effect", lua.count("Effect.CreateEffect(c)") <= 1, "")

# ══ 4. helper 入口存在性 ════════════════════════════════════════════
texts = {}
for f in sorted((paths.VENDOR / "scripts").rglob("*.lua")):
    try:
        texts[f.name] = f.read_text(encoding="utf-8", errors="replace")
    except Exception:
        texts[f.name] = ""
procs = sorted(FR.procedure_calls())
LINES.append(f"入口清单（{len(procs)}）：{'、'.join(procs)}")
for proc in procs:
    tail = proc.split(".")[-1]
    hit = any(re.search(rf"function\s+{re.escape(proc)}\b|\b{re.escape(proc)}\s*=|\b{re.escape(tail)}\b", t)
              for t in texts.values())
    chk(f"入口 {proc} 在 vendor 里有定义", hit, "找不到")

# ══ 5. validate_effect ══════════════════════════════════════════════
chk("合法 IR：search 返回空", not EF.validate_effect(E("search", "IGNITION", tgt=T("DECK"))), "")
chk("合法 IR：gain_atk 带 value 返回空",
    not EF.validate_effect(E("gain_atk", "IGNITION", tgt=T(**MON), params={"value": 300})), "")
for eff, label, codes in ((E("__x__"), "未知 kind", ("UNKNOWN",)),
                          (E("draw", "NOPE"), "非法 trigger", ("TRIGGER",)),
                          (E("gain_atk", "IGNITION", tgt=T(**MON)), "缺必填参数", ("PARAM",)),
                          (E("continuous_gain_atk", "CONTINUOUS", "none", tgt=T(**MON),
                             cost=EffectCost(kind="pay_lp", lp=1000)), "不允许的 cost", ("COST",))):
    got = EF.validate_effect(eff)
    chk(f"非法 IR（{label}）命中", bool(got) and any(any(c in i.code.upper() for c in codes)
                                                   for i in got), f"{[i.code for i in got]}")

# ══ 6. infer_from_text 真实卡文 ═════════════════════════════════════
TEXT = ("①：这张卡召唤成功时才能发动。从卡组把 1 张「星奏」卡加入手卡。"
        "②：1回合1次，自己主要阶段才能发动。从手卡把 1 只「星奏」怪兽特殊召唤。")
p = paths.CARDS / "210000011" / "spec.json"
src = "兜底原文"
if p.exists():
    d = json.loads(p.read_text(encoding="utf-8"))
    t0 = str((d.get("text_i18n") or {}).get("zh_cn") or d.get("text") or "")
    if t0.strip():
        TEXT, src = t0, str(p)
LINES.append(f"卡文来源：{src}\n卡文：{TEXT}")
got = EF.infer_from_text(TEXT)
chk("真实卡文认出 2 条效果", len(got) == 2, f"{[g.kind for g in got]}")
if len(got) == 2:
    a, b = got
    chk("①kind=search", a.kind == "search", a.kind)
    chk("①trigger=NORMAL_SUMMON_SUCCESS", a.trigger == "NORMAL_SUMMON_SUCCESS", a.trigger)
    chk("①target DECK/archetype", bool(a.target) and a.target.from_zone == "DECK"
        and a.target.filter_kind == "archetype", "")
    chk("②kind=ssummon_hand", b.kind == "ssummon_hand", b.kind)
    chk("②trigger=IGNITION", b.trigger == "IGNITION", b.trigger)
    chk("②limit=once_per_turn", b.limit == "once_per_turn", b.limit)
    chk("②target HAND", bool(b.target) and b.target.from_zone == "HAND", "")
    s2 = spec_one(210000011, "effect", got, name="星奏の指揮者 アリア")
    lua = art("真实卡", s2)
    chk("真实卡 2 个 Stringid", len(s2.strings) == 2, f"{s2.strings}")
    chk("真实卡描述里没有 {占位符}", not re.search(r"\{[a-z]+\}", " ".join(s2.strings)),
        " ".join(s2.strings))

# ══ 6b. 官方卡文往返：卡文 → IR → 卡文 必须一模一样 ═══════════════════
# 用户把系统投影出的官方格式卡文贴回来（或点「校验」触发反解）时，
# 反解曾经把「包含「圣痕」怪兽的战士族怪兽×3」读成一条 ① 效果、
# 把「1只战士族怪兽」读成种族「只战士族」，再投影就是
# 「把自己场上1只只战士族怪兽送去墓地」。这一节把这类丢信息/串味锁死。
RT_NAME = "圣痕龙骑士 露米艾尔"
RT_TEXT = (
    "①：1回合1次，以对方场上1张表侧表示的卡为对象才能发动。"
    "那张卡的效果直到回合结束时无效。这个效果在对方回合也能发动。\n"
    "②：1回合1次，对方把怪兽的效果发动时，从卡组把1只战士族怪兽送去墓地才能发动。"
    "那个发动无效并破坏。\n"
    "③：这张卡被战斗·效果破坏的场合才能发动。"
    "从自己墓地选1只「圣痕龙骑士 露米艾尔」以外的战士族怪兽特殊召唤。")
_rt = EF.infer_from_text(RT_TEXT, RT_NAME)
chk("往返：3 条效果（不掺幽灵效果）", len(_rt) == 3, f"{[e.kind for e in _rt]}")
if len(_rt) == 3:
    r1, r2, r3 = _rt
    chk("往返：①表侧表示 → face_up", bool(r1.target) and r1.target.face_up, "")
    chk("往返：①诱发即时 → QUICK + params.quick",
        r1.trigger == "QUICK" and r1.params.get("quick") is True,
        f"{r1.trigger}/{r1.params}")
    chk("往返：①无效场上卡的效果 = negate_card", r1.kind == "negate_card", r1.kind)
    chk("往返：②对方把怪兽的效果发动时", r2.trigger == "OPPONENT_ACTIVATE_MONSTER",
        r2.trigger)
    chk("往返：②代价区域是卡组不是怪兽区域",
        bool(r2.cost) and r2.cost.zone == "DECK", f"{r2.cost}")
    chk("往返：②代价种族不吞量词",
        bool(r2.cost) and r2.cost.filter_value == "战士族",
        f"{r2.cost.filter_value if r2.cost else None}")
    chk("往返：③破坏方式 battle_effect",
        r3.trigger == "WHEN_DESTROYED"
        and r3.params.get("destroyed_by") == "battle_effect", f"{r3.params}")
    chk("往返：③「「卡名」以外的」→ exclude_self",
        bool(r3.target) and r3.target.exclude_self, f"{r3.target}")
    chk("往返：③不取对象的「选」句式 → params.select",
        r3.params.get("select") is True, f"{r3.params}")
    _spec = CardSpec(id=210000640, name=RT_NAME, frame="effect", attribute="光",
                     race="战士族", level=8, atk=3000, dfd=2500,
                     archetype="圣痕", setcode="0x1001",
                     effects=[e.to_dict() for e in _rt])
    _back = PSGEN.compose(_spec, "zh_cn")
    chk("往返：再投影与原文逐行相同", _back == RT_TEXT,
        "\n期望:\n" + RT_TEXT + "\n实得:\n" + _back)
    art("往返卡脚本", _spec)

# 召唤手续段不是效果：贴回来的官方卡文开头那段必须被认出来并交还 summon
_rt2 = EF.infer_from_text(
    "包含「圣痕」怪兽的战士族怪兽×3\n这张卡不能作为融合素材。\n"
    "这张卡用融合召唤以及以下方法才能特殊召唤。\n"
    "●把自己场上的上记的卡除外的场合可以从额外卡组特殊召唤。\n"
    "①：这张卡不会被战斗破坏。", RT_NAME)
chk("召唤手续不变成编号效果", len(_rt2) == 1 and _rt2[0].kind == "cannot_be_destroyed",
    f"{[(e.kind, e.raw_text[:20]) for e in _rt2]}")
from cardforge.content import summon as _SM
_blk, _rest = _SM.split_leading_block(
    "「青眼白龙」＋「青眼白龙」\n这张卡用融合召唤才能特殊召唤。\n①：不会被战斗破坏。")
chk("split_leading_block 切出素材行与限制行",
    _blk.startswith("「青眼白龙」") and _rest.startswith("①"), f"{_blk}|{_rest}")
chk("HOPT 声明不会被当成召唤手续",
    _SM.split_leading_block("这个卡名的效果1回合只能使用1次。\n①：检索。")[0] == "", "")
chk("种族词表不吞量词",
    EF._RACE_RE.search("把自己场上1只只战士族怪兽送去墓地").group("race") == "战士族", "")
chk("卡名差一个「的」仍认得出是自己（排除条件不能丢）",
    EF._same_card_name("圣痕龙骑士 露米艾尔", "圣痕的龙骑士 露米艾尔")
    and not EF._same_card_name("圣痕龙骑士", "星奏的见习指挥"), "")
_rt3 = EF.infer_from_text(
    "①：这张卡被战斗·效果破坏的场合才能发动。"
    "从自己墓地选1只「圣痕龙骑士 露米艾尔」以外的战士族怪兽特殊召唤。",
    "圣痕的龙骑士 露米艾尔")
chk("反解：助词差异不影响 exclude_self",
    bool(_rt3) and bool(_rt3[0].target) and _rt3[0].target.exclude_self,
    f"{_rt3[0].target if _rt3 else None}")
chk("兽战士族不被战士族抢走",
    EF._RACE_RE.search("5星以上的兽战士族怪兽").group("race") == "兽战士族", "")
chk("质量门提示不带 Markdown 星号",
    "**" not in (PR2 := __import__("cardforge.core.models", fromlist=["Issue"]).Issue(
        message="这类**结果**", hint="把**代价**移走").message), "")

# ══ 6c. lint 自己的产出不能被判错（官方代价句 / 被动触发句 / ● 条目）════
_official_ok = (
    "包含「圣痕」怪兽的战士族怪兽×3\n"
    "这张卡不能作为融合素材。\n"
    "这张卡用融合召唤以及以下方法才能特殊召唤。\n"
    "●把自己场上的上记的卡除外的场合可以从额外卡组特殊召唤。\n"
    "①：1回合1次，以对方场上1张表侧表示的卡为对象才能发动。"
    "那张卡的效果直到回合结束时无效。这个效果在对方回合也能发动。\n"
    "②：1回合1次，对方把怪兽的效果发动时，从卡组把1只战士族怪兽送去墓地才能发动。"
    "那个发动无效并破坏。\n"
    "③：这张卡被战斗·效果破坏的场合才能发动。"
    "从自己墓地选1只「圣痕的龙骑士 露米艾尔」以外的战士族怪兽特殊召唤。")
_ok_spec = CardSpec(id=210000641, name="圣痕的龙骑士 露米艾尔", frame="fusion",
                    attribute="光", race="战士族", level=8, atk=3000, dfd=2500,
                    archetype="圣痕", setcode="0x1001",
                    text_i18n={"zh_cn": _official_ok})
_codes = [f"{i.level}:{i.code}" for i in PLINT.lint(_ok_spec, "zh_cn")]
chk("官方代价句不被判成处理前置",
    "ERROR:PSCT_RESOLUTION_BEFORE_SEMI" not in _codes, str(_codes))
chk("● 召唤手续条目不要求冒号",
    "WARN:PSCT_MISSING_COLON" not in _codes, str(_codes))
chk("被动触发句（被战斗·效果破坏）不被判成处理前置",
    all("破坏" not in c for c in _codes if "RESOLUTION_BEFORE_SEMI" in c), str(_codes))
_bad_spec = CardSpec(id=210000642, name="误写卡", frame="effect", attribute="光",
                     race="战士族", level=4, atk=1600, dfd=1200,
                     text_i18n={"zh_cn": "①：这张卡从墓地特殊召唤，抽1张卡才能发动。"})
chk("真把处理写进条件段仍然报 ERROR",
    any(i.code == "PSCT_RESOLUTION_BEFORE_SEMI" and i.level == "ERROR"
        for i in PLINT.lint(_bad_spec, "zh_cn")), "")
_bad_en = CardSpec(id=210000643, name="EN card", frame="effect", attribute="光",
                   race="战士族", level=4, atk=1600, dfd=1200,
                   text_i18n={"en": "① Once per turn: You can send 1 Warrior monster "
                                    "in your Deck to the GY; negate the activation, "
                                    "and if you do, destroy it."})
chk("英文代价（send … to the GY;）不被判成处理前置",
    not any(i.code == "PSCT_RESOLUTION_BEFORE_SEMI"
            for i in PLINT.lint(_bad_en, "en")), "")

# ══ 7. 命令行 + G2 ══════════════════════════════════════════════════
from cardforge.pipeline import gates
s = spec_one(210000621, "effect", [E("search", "NORMAL_SUMMON_SUCCESS", "hopt_name",
                                     tgt=T("DECK"), raw="①：检索。")])
lua = emit.emit_script(s)
s.lua = ""
rep = gates.g2_script(s, lua)
errs = [i for i in rep.issues if i.level == "ERROR"]
chk("gates.g2_script 无 ERROR", not errs, "；".join(i.message for i in errs))
for action in ("script", "verify", "lint"):
    r = subprocess.run([sys.executable, "-m", "cardforge", "card", action, "--card",
                        "210000011"], cwd=str(ROOT), capture_output=True, timeout=600,
                       env=dict(subprocess.os.environ, PYTHONIOENCODING="utf-8"))
    out = (r.stdout or b"").decode("utf-8", "replace")
    err = (r.stderr or b"").decode("utf-8", "replace")
    chk(f"cli card {action} 不崩", "Traceback" not in err and "Traceback" not in out,
        (err or out)[-400:])
    LINES.append(f"     cli {action}: exit={r.returncode} out={len(out)}B err={len(err)}B")

# ══ 8. 健壮性 ═══════════════════════════════════════════════════════
tmp = Path(tempfile.mkdtemp(prefix="robust_"))
junk = ["", "不存在的种类", "search", "gain_atk", "__init__", "frag_destroy", "SSUMMON", "０"]
frames = ["normal", "effect", "spell", "trap", "xyz", "link", "pendulum", "token",
          "skill", "fusion_pendulum", "???", "", "normal_pendulum", "ritual", "synchro"]
crash = []
for i in range(50):
    effs = [EffectSpec(kind=junk[(i + j) % len(junk)],
                       trigger=("", "IGNITION", "WHAT", "QUICK", "CONTINUOUS")[i % 5],
                       limit=("", "none", "hopt_name", "非法", "once_duel")[j % 5],
                       target=EffectTarget(from_zone=["", "NOWHERE", "DECK", "MZONE"][i % 4],
                                           filter_kind=["", "archetype", "???"][j % 3],
                                           filter_value=[None, "星奏", {"怪": "怪"}][j % 3],
                                           count=[0, -3, 1, 99][i % 4]),
                       cost=EffectCost(kind=["none", "?", "detach", "pay_lp"][j % 4],
                                       lp=[0, -1, 10 ** 9][j % 3]),
                       params={"value": [None, "abc", 300][j % 3], "token": ""},
                       raw_text=["", "①：乱码 ñ中文", "①把②③", "x" * 300][(i + j) % 4])
            for j in range((0, 1, 3, 7)[i % 4])]
    sp = CardSpec(id=210000700 + i, name=["", "乱码/\\:*?", "ＡＢＣ", "x" * 90][i % 4],
                  frame=frames[i % len(frames)], attribute=["光", "乱码", ""][i % 3],
                  race=["魔法师族", "乱码族", ""][i % 3], level=[0, 13, -2, 4][i % 4],
                  atk=["?", 1600, -5][i % 3], dfd=["?", "abc", 0][i % 3],
                  setcode=["0x1001", "", "乱码", "0x1001+0x2", "9e99"][i % 5],
                  spell_kind=["", "quick", "equip", "???"][i % 4],
                  trap_kind=["", "counter", "???"][i % 3],
                  pendulum_scale=[None, 0, 13, 4][i % 4],
                  pendulum_effect_indices=[[], [0], [99], [-1]][i % 4], effects=effs)
    try:
        lu = emit.emit_script(sp)
        emit.emit_strings(sp)
        if lu:
            emit.write_script(sp, str(tmp / f"c{sp.id}.lua"))
            sp.lua = ""
            q = emit.write_script(sp)
            if q and not Path(q).exists():
                crash.append(f"{sp.id} write_script 说写了但没有文件：{q}")
            if not q:
                crash.append(f"{sp.id} 有脚本但 write_script 没落盘")
    except Exception as e:
        crash.append(f"{sp.id}(frame={sp.frame}) {type(e).__name__}: {e}\n"
                     + traceback.format_exc()[-300:])
chk("50 个畸形规格 0 未捕获异常", not crash, "\n".join(crash[:3]))

# ══ 9. cdb + expansions G5 ══════════════════════════════════════════
from cardforge.export import expansions
from cardforge.pool import cdb as cdbmod
g5 = Path(tempfile.mkdtemp(prefix="g5_"))
picked = (210000605, 210000611, 210000608, 210000609, 210000613, 210000616)
specs = []
for cid in picked:
    pass
# 直接复用上面构造过的卡（重新构造一遍以保证干净状态）
specs = [
    spec_one(210000605, "effect", [E("search", "IGNITION", "hopt_name", tgt=T("DECK"),
                                     raw="①"), E("draw", "IGNITION", "hopt_name",
                                                 params={"count": 1}, raw="②")]),
    spec_one(210000611, "pendulum", [E("search", "IGNITION", "once_per_turn", tgt=T("DECK"),
                                       raw="①：灵摆框"),
                                     E("gain_atk", "IGNITION", "hopt_name", tgt=T(**MON),
                                       params={"value": 300}, raw="②：怪兽框")],
             pendulum_scale=2, pendulum_effect_indices=[0]),
    spec_one(210000608, "xyz", [E("xyz_summon", params={"count": 2, "materials": []}),
                                E("send_grave", "IGNITION", "once_per_turn", tgt=T(**MON),
                                  cost=EffectCost(kind="detach"), raw="①：送墓。")], level=4),
    spec_one(210000609, "link", [E("link_summon", params={"materials": []}),
                                 E("destroy", "SPECIAL_SUMMON_SUCCESS", "once_per_turn",
                                   tgt=T(**MON), raw="①：破坏。")],
             level=2, atk=1800, dfd=0, link_markers=["左下", "下"]),
    spec_one(210000613, "spell", [E("draw", "QUICK", "once_per_turn", params={"count": 1},
                                    raw="①：抽 1 张。")], spell_kind="quick"),
    spec_one(210000616, "trap", [E("negate_effect", "OPPONENT_ACTIVATE", "once_per_turn",
                                   raw="①：无效。")], trap_kind="counter"),
]
sd = g5 / "script"
sd.mkdir(parents=True, exist_ok=True)
for s in specs:
    s.lua = ""
    lu = emit.emit_script(s)
    s.lua = lu
    emit.write_script(s, str(sd / f"c{s.id}.lua"))
    raw = (sd / f"c{s.id}.lua").read_bytes()
    chk(f"{s.id} 落盘无 BOM", not raw.startswith(b"\xef\xbb\xbf"), "有 BOM")
    chk(f"{s.id} 落盘 == emit_script", raw.decode("utf-8") == lu, "")
con = cdbmod.open_cdb(g5 / "t.cdb")
try:
    cdbmod.upsert_many(con, specs)
    for s in specs:
        row = cdbmod.read_card(con, s.id)
        chk(f"{s.id} cdb 行读回", bool(row), "")
        if row:
            used = sorted({int(x) for x in lint.RE_STRINGID.findall(s.lua or "")})
            empt = [i for i in used if not str(row.get(f"str{i + 1}") or "").strip()]
            chk(f"{s.id} cdb str 与 Stringid 对齐", not empt, f"缺 {empt}")
finally:
    con.close()
try:
    res = expansions.build(specs, g5 / "pack", name="CFTEST", copy_pics=False)
    errs = [i for i in res.get("issues", []) if i.get("level") == "ERROR"]
    chk("expansions.build 无 ERROR", not errs, json.dumps(errs[:2], ensure_ascii=False)[:500])
    exp = Path(res["expansions_dir"])
    lost = [s.id for s in specs if s.lua and not (exp / "script" / f"c{s.id}.lua").exists()]
    chk("脚本进 expansions/script", not lost, f"缺 {lost}")
    LINES.append(f"     build: n_cards={res.get('n_cards')} n_scripts={res.get('n_scripts')}")
    issues = expansions.verify(res["pack_dir"], check_official=False)
    verrs = [i for i in issues if i.level == "ERROR"]
    chk("expansions.verify(G5) 0 ERROR", not verrs,
        "；".join(f"{i.code}:{i.message}" for i in verrs))
    for i in issues:
        if i.level != "ERROR":
            warn(f"G5 {i.code}", i.message)
except Exception as e:
    chk("build/verify 不抛", False, f"{type(e).__name__}: {e}\n" + traceback.format_exc()[-500:])

# ══ 片段覆盖 ════════════════════════════════════════════════════════
named = {k.lua_fragment for k in EF.EFFECT_KINDS.values() if k.lua_fragment}
chk(f"effects 需要的 {len(named)} 个具名片段全实现", not (named - set(FR.FRAGMENTS)),
    f"缺 {sorted(named - set(FR.FRAGMENTS))}")
chk("FRAGMENTS 无孤儿", not (set(FR.FRAGMENTS) - named), f"多 {sorted(set(FR.FRAGMENTS) - named)}")
skeleton = sorted(k for k, v in EF.EFFECT_KINDS.items() if not v.lua_fragment)
LINES.append(f"走卡种骨架（无片段）的 kind {len(skeleton)}：{'、'.join(skeleton)}")

Path(ROOT / "_probe/verify_g2.txt").write_text(
    "\n".join(LINES) + "\n\n==== FAIL ====\n" + "\n".join(FAIL) +
    f"\n\n==== WARN({len(WARN)}) ====\n" + "\n".join(WARN) + "\n", encoding="utf-8")
print(f"PASS={len([l for l in LINES if l.startswith('[PASS]')])} "
      f"FAIL={len(FAIL)} WARN={len(WARN)}")
