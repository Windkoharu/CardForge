"""全量集成冒烟测试 —— 一条命令确认"当前交付物是自洽可跑的"。

用法: python tools/smoke.py
退出码 0 = 全部通过；非 0 = 有失败项（会逐条打印）。
"""
from __future__ import annotations

import io
import json
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PASS, FAIL, WARN = [], [], []


def check(name: str, fn, *, allow_skip: bool = False):
    t0 = time.perf_counter()
    try:
        r = fn()
        ms = (time.perf_counter() - t0) * 1000
        if r is False:
            FAIL.append((name, "返回 False", ms))
            print(f"  [FAIL] {name}  ({ms:.0f}ms)")
        elif isinstance(r, str) and r.startswith("SKIP:"):
            WARN.append((name, r[5:], ms))
            print(f"  [SKIP] {name}  — {r[5:]}  ({ms:.0f}ms)")
        else:
            PASS.append((name, r, ms))
            note = f" — {r}" if isinstance(r, str) and r else ""
            print(f"  [ OK ] {name}{note}  ({ms:.0f}ms)")
    except Exception as e:
        ms = (time.perf_counter() - t0) * 1000
        FAIL.append((name, f"{type(e).__name__}: {e}", ms))
        print(f"  [FAIL] {name}  ({ms:.0f}ms)")
        traceback.print_exc(limit=3)


print("=" * 72)
print("CardForge 集成冒烟测试")
print("=" * 72)

# ── 1. 内核 ──────────────────────────────────────────────────────────
print("\n[1] 领域内核")

def _core():
    from cardforge.core import CardSpec, EffectSpec, RenderOptions
    s = CardSpec(id=210000011, name="星奏的见习指挥", frame="effect",
                 attribute="光", race="魔法师族", level=4, atk=1600, dfd=1200)
    assert s.type_bits == 0x21, hex(s.type_bits)
    assert s.race_bits == 2 and s.attr_bits == 16
    s2 = CardSpec.from_dict(s.to_dict())
    assert s2.type_bits == s.type_bits
    lk = CardSpec(frame="link", link_markers=["左下", "下", "右"])
    # 左下(0x001) | 下(0x002) | 右(0x020) = 0x023
    assert lk.effective_level == 3 and lk.def_value == 0x23, hex(lk.def_value)
    legacy = {"name": "旧卡", "frame": "effect", "level": 4, "attribute": "炎",
              "race": "战士族", "atk": 1800, "def": 1000, "text": "①：测试。",
              "id": 1, "type_flags": ["tuner"], "_lua": "-- x", "race_bits": 2}
    m = CardSpec.from_dict(legacy)
    assert m.dfd == 1000 and m.tags == ["tuner"] and m.lua == "-- x"
    return "位掩码/往返/连接/旧版迁移 全部正确"

check("core 领域模型", _core)


def _geometry():
    from cardforge.render import geometry as G
    r = G.verify_frame_consistency()
    # 实测最大相对误差 0.27%（卡框素材 1394x2031 折算回 813x1185 时高度差 0.8px）。
    # 这是同一套坐标的强证据；阈值放到 0.5% 以免把浮点舍入当成回归。
    assert r["max_rel"] < 0.005, r
    # 697px 对应 300.1 dpi（59mm 在 300dpi 下是 696.85px，取整到 697）—— 允许 ±0.5 舍入
    assert abs(G.dpi_of("print300") - 300.0) <= 0.5, G.dpi_of("print300")
    assert abs(G.dpi_of("share") - 350.0) <= 0.5, G.dpi_of("share")
    assert abs(G.dpi_of("print") - 600.0) <= 0.5, G.dpi_of("print")
    return f"卡框一致性 max_rel={r['max_rel']:.5f}，dpi 互校通过"

check("render 几何", _geometry)


def _frameprobe():
    from cardforge.render import frameprobe as FP
    rows = FP.diagnose_all()
    std = [d for d in rows if not d["pendulum"] and d["measured"]]
    assert len(std) >= 8, f"实测成功的标准框只有 {len(std)} 个"
    ys = {round(d["type_line"][1]) for d in std}
    assert all(840 <= y <= 843 for y in ys), ys
    pend = [d for d in rows if d["blank_window"]]
    assert len(pend) >= 5, f"识别出的灵摆框只有 {len(pend)} 个"
    return f"{len(rows)} 种卡框实测，标准框 type_line y∈{sorted(ys)}，灵摆框 {len(pend)} 个"

check("卡框版面实测", _frameprobe)

# ── 2. 渲染 ──────────────────────────────────────────────────────────
print("\n[2] 卡面渲染")


def _render_all_frames():
    from PIL import Image
    from cardforge.core.models import CardSpec, RenderOptions, FullArtOptions
    from cardforge.render import compositor as C
    art = Image.new("RGB", (832, 1216), (60, 80, 160))
    frames = ["normal", "effect", "ritual", "fusion", "synchro", "xyz", "link",
              "pendulum", "spell", "trap", "token"]
    bad = []
    for fr in frames:
        s = CardSpec(id=1, name="测试卡", frame=fr, attribute="光", race="魔法师族",
                     level=4, atk=1600, dfd=1200)
        s.text_i18n = {"zh_cn": "①：这是一段测试卡文，用于验证渲染管线。"}
        s.render = RenderOptions(rarity="common")
        try:
            im = C.render_card(s, art, size=(210, 307))
            assert im.size == (210, 307)
        except Exception as e:
            bad.append(f"{fr}:{type(e).__name__}:{e}")
    assert not bad, bad
    return f"{len(frames)} 种卡框全部渲染成功"

check("全卡种渲染", _render_all_frames)


def _render_rarities():
    from PIL import Image
    from cardforge.core.models import CardSpec, RenderOptions
    from cardforge.render import compositor as C, rarities as R
    art = Image.new("RGB", (832, 1216), (200, 120, 60))
    bad = []
    for rk in R.RARITY_DEFS:
        s = CardSpec(id=1, name="测试", frame="effect", attribute="暗", race="龙族",
                     level=8, atk=3000, dfd=2500)
        s.text_i18n = {"zh_cn": "①：测试。"}
        s.render = RenderOptions(rarity=rk)
        try:
            C.render_card(s, art, size=(210, 307))
        except Exception as e:
            bad.append(f"{rk}:{type(e).__name__}:{e}")
    assert not bad, bad
    return f"{len(R.RARITY_DEFS)} 种罕贵全部渲染成功"

check("全罕贵渲染", _render_rarities)


def _render_fullart():
    from PIL import Image
    from cardforge.core.models import CardSpec, RenderOptions, FullArtOptions
    from cardforge.render import compositor as C, fullart as FA
    art = Image.new("RGB", (832, 1216), (60, 160, 90))
    for m in FA.MODES:
        s = CardSpec(id=1, name="出框测试", frame="effect", attribute="光",
                     race="魔法师族", level=4, atk=1800, dfd=1000)
        s.text_i18n = {"zh_cn": "①：出框档位测试卡文。"}
        s.render = RenderOptions(rarity="ultra", fullart=FullArtOptions(mode=m))
        im = C.render_card(s, art, size=(210, 307))
        assert im.size == (210, 307)
    return f"{len(FA.MODES)} 个出框档位全部渲染成功"

check("全出框档位", _render_fullart)


def _render_langs():
    from PIL import Image
    from cardforge.core.models import CardSpec, RenderOptions
    from cardforge.render import compositor as C
    from cardforge.core.enums import LANGS
    art = Image.new("RGB", (832, 1216), (120, 60, 160))
    texts = {
        "zh_cn": "①：这张卡召唤成功时才能发动。", "zh_tw": "①：這張卡召喚成功時才能發動。",
        "ja": "①：このカードが召喚に成功した時に発動できる。",
        "en": "①: When this card is Normal Summoned: You can draw 1 card.",
        "ko": "①: 이 카드가 일반 소환에 성공했을 때 발동할 수 있다.",
        "de": "①: Wenn diese Karte als Normalbeschwörung beschworen wird: Ziehe 1 Karte.",
        "fr": "①: Lorsque cette carte est Invoquée Normalement: Piochez 1 carte.",
        "it": "①: Quando questa carta viene Evocata Normalmente: Pesca 1 carta.",
        "pt": "①: Quando este card for Invocado por Invocação-Normal: Compre 1 card.",
        "es": "①: Cuando esta carta es Invocada de Modo Normal: Roba 1 carta.",
    }
    missing = []
    for lg in LANGS:
        s = CardSpec(id=1, name="Test", frame="effect", attribute="光",
                     race="魔法师族", level=4, atk=1000, dfd=1000)
        s.text_i18n = {lg: texts.get(lg, "①: test.")}
        s.render = RenderOptions(lang_text=lg, lang_name=lg, rarity="common")
        im, rep = C.render_card(s, art, size=(210, 307), return_report=True)
        if rep.missing_fonts:
            missing.append(lg)
    assert not missing, f"缺字体的语言：{missing}"
    return f"{len(LANGS)} 种语言全部渲染且无缺字体"

check("全语言渲染", _render_langs)

# ── 3. 文本与脚本 ────────────────────────────────────────────────────
print("\n[3] 文本与脚本")


def _lua_syntax():
    from cardforge.content.lua import lint
    cases = {
        "正确": ("local s,id=GetID()\nfunction s.initial_effect(c)\n"
                 "\tlocal e=Effect.CreateEffect(c)\n\tc:RegisterEffect(e)\nend\n", True),
        "缺end": ("local s,id=GetID()\nfunction s.initial_effect(c)\n", False),
        "多end": ("function f()\nend\nend\n", False),
        "括号": ("local a = (1\n", False),
        "字符串": ('local a = "abc\n', False),
        "repeat": ("repeat\nlocal a=1\n", False),
        "长注释": ("--[[ abc\nlocal a=1\n", False),
        "带注释正确": ("--[[ 说明 ]]\nlocal t=\"end\"\nfunction f()\nend\n", True),
    }
    bad = []
    for n, (code, want) in cases.items():
        ok, _ = lint.syntax_ok(code)
        if ok != want:
            bad.append(f"{n}(期望{want}得到{ok})")
    assert not bad, bad
    return f"{len(cases)}/{len(cases)} 个语法用例判定正确"

check("Lua 语法校验", _lua_syntax)


def _api_catalog():
    from cardforge.content.lua import apicatalog as API
    info = API.info()
    assert info["n_functions"] > 500, info
    assert info["n_constants"] > 500, info
    assert API.is_known("Duel.SelectMatchingCard")
    assert API.is_known("aux.Stringid")
    assert not API.is_known("Duel.ThisDoesNotExist")
    return (f"{info['n_functions']} 函数 / {info['n_constants']} 常量 / "
            f"{info['n_methods']} 方法（来源 {info['source']}）")

check("Lua API 白名单", _api_catalog)


def _g2_clean():
    from cardforge.core.models import CardSpec
    from cardforge.content.lua import lint
    spec = CardSpec(id=1, name="x", frame="effect", attribute="光", race="魔法师族")
    spec.strings = ["①：从卡组把1张「星奏」卡加入手卡。"]
    good = ('local s,id=GetID()\nfunction s.initial_effect(c)\n'
            '\tlocal e1=Effect.CreateEffect(c)\n'
            '\te1:SetDescription(aux.Stringid(id,0))\n'
            '\te1:SetCategory(CATEGORY_TOHAND)\n'
            '\te1:SetType(EFFECT_TYPE_SINGLE+EFFECT_TYPE_TRIGGER_O)\n'
            '\te1:SetCode(EVENT_SUMMON_SUCCESS)\n'
            '\te1:SetTarget(function(e,tp,eg,ep,ev,re,r,rp,chk)\n'
            '\t\tif chk==0 then return Duel.IsExistingMatchingCard(aux.TRUE,tp,LOCATION_DECK,0,1,nil) end\n'
            '\t\tDuel.SetOperationInfo(0,CATEGORY_TOHAND,nil,1,tp,LOCATION_DECK)\n\tend)\n'
            '\te1:SetOperation(function(e,tp)\n'
            '\t\tDuel.Hint(HINT_SELECTMSG,tp,HINTMSG_ATOHAND)\n'
            '\t\tlocal g=Duel.SelectMatchingCard(tp,aux.TRUE,tp,LOCATION_DECK,0,1,1,nil)\n'
            '\t\tif #g>0 then Duel.SendtoHand(g,nil,REASON_EFFECT) end\n\tend)\n'
            '\tc:RegisterEffect(e1)\nend\n')
    iss = lint.lint_lua(good, spec)
    errs = [i for i in iss if i.level == "ERROR"]
    assert not errs, [(i.code, i.message) for i in errs]
    return "合规脚本零 ERROR（无误报）"

check("G2 零误报", _g2_clean)


def _design_audit():
    from cardforge.core.models import CardSpec, EffectSpec
    from cardforge.content import design as D
    ok = CardSpec(id=210000011, name="合规卡", frame="effect", attribute="光",
                  race="魔法师族", level=4, atk=1600, dfd=1200,
                  archetype="星奏", setcode="0x1001")
    ok.effects = [EffectSpec(kind="search", trigger="NORMAL_SUMMON_SUCCESS",
                             limit="hopt_name")]
    ok.text_i18n = {"zh_cn": "①：这张卡召唤成功时才能发动。从卡组把1张「星奏」卡加入手卡。"}
    e1 = [i for i in D.audit_card(ok, None) if i.level == "ERROR"]
    assert not e1, [(i.code, i.message) for i in e1]

    bad = CardSpec(id=200000001, name="超模卡", frame="effect", attribute="暗",
                   race="龙族", level=4, atk=2600, dfd=2600)
    bad.effects = [EffectSpec(kind="search", trigger="NORMAL_SUMMON_SUCCESS", limit="none")]
    bad.text_i18n = {"zh_cn": "①：从卡组把1只怪兽加入手卡。"}
    e2 = [i for i in D.audit_card(bad, None) if i.level == "ERROR"]
    assert e2, "超模卡应当被拦截"
    codes = {i.code for i in e2}
    assert "G1_L4_EFFECT_ATK" in codes, codes

    # 起手概率与调研数值一致
    p = D.opening_probability(12)
    assert abs(p - 0.850) < 0.005, p
    return f"合规卡 0 ERROR，超模卡命中 {len(e2)} 条（含 ATK 惯例）；起手概率 12 张 = {p:.1%}"

check("G1 平衡审计", _design_audit)


def _summon_conditions():
    from cardforge.core import CardSpec, MaterialPart, SummonSpec
    from cardforge.content.psct import gen
    from cardforge.content.lua import emit, lint
    from cardforge.content.design import audit_card
    s = CardSpec(id=210000050, name="召唤条件测试", frame="fusion",
                 attribute="光", race="龙族", level=8, atk=3000, dfd=2500,
                 archetype="星奏", setcode="0x1001")
    s.summon = SummonSpec(
        materials=[MaterialPart(kind="name", value="青眼白龙", code=89631139),
                   MaterialPart(kind="race", value="龙族", count=1, count_max=99)],
        limit="must_be_with_materials", cannot_be_material=["fusion"])
    zh = gen.compose(s, "zh_cn")
    assert zh.splitlines()[0] == "「青眼白龙」＋龙族怪兽1只以上", zh
    assert "不能作为融合素材" in zh and "以上记的卡为融合素材" in zh, zh
    lua = emit.emit_script(s)
    assert "Fusion.AddProcMixRep(c,true,true,s.mat0_1,1,99,s.mat0_0)" in lua, lua
    assert "aux.fuslimit" in lua and "EFFECT_CANNOT_BE_FUSION_MATERIAL" in lua, lua
    ok, msg = lint.syntax_ok(lua)
    assert ok, msg
    # 序列化往返（空 SummonSpec 不落盘）
    d = s.to_dict()
    assert d["summon"]["materials"][0]["code"] == 89631139, d.get("summon")
    s2 = CardSpec.from_dict(d)
    assert s2.summon.limit == "must_be_with_materials", s2.summon
    assert "summon" not in CardSpec(id=1, name="x").to_dict()
    # 缺失素材必须被 G1 拦住
    bad = CardSpec(id=210000051, name="坏融合", frame="fusion", attribute="光",
                   race="龙族", level=8, atk=3000, dfd=2500, archetype="星奏",
                   setcode="0x1001")
    codes = {i.code for i in audit_card(bad, check_pool=False)}
    assert "G1_SUMMON_MATERIAL_MISSING" in codes, codes
    return "素材行/Lua 流程/限制/序列化/G1 缺失拦截 全部正确"

check("召唤条件同源", _summon_conditions)


def _contact_fusion_duel():
    """真 ocgcore 里跑一遍接触召唤：引擎是否提供、是否真执行。

    官方卡池没有字段码 0x1001 的战士族怪兽，素材也用 DIY 卡，
    否则「包含「星奏」怪兽的战士族怪兽×3」永远凑不齐，测不到 AddContactProc。
    """
    from cardforge.duel import bot, engine, ocgcore as oc
    from cardforge.content import summon as CS
    from cardforge.content.lua import emit
    from cardforge.core.models import (CardSpec, MaterialPart, SummonMethod,
                                       SummonSpec)
    try:
        st = engine.detect()
    except Exception as e:
        return f"SKIP: 引擎探测失败（{e}）"
    if getattr(st, "level", "") != "ocgcore":
        return f"SKIP: 未检测到 ocgcore（{getattr(st, 'reason', '') or '引擎不可用'}）"

    mat_id = 210000041
    mat = CardSpec(id=mat_id, name="圣痕的战士", frame="effect", attribute="光",
                   race="战士族", level=4, atk=1600, dfd=1200,
                   archetype="星奏", setcode="0x1001", effects=[],
                   lua="local s,id=GetID()\nfunction s.initial_effect(c)\nend\n")
    lum = CardSpec(id=210000042, name="星痕龙骑士", frame="fusion", attribute="光",
                   race="战士族", level=8, atk=3000, dfd=2500,
                   archetype="星奏", setcode="0x1001")
    lum.summon = SummonSpec(
        materials=[MaterialPart(kind="archetype", value="星奏",
                                also=[MaterialPart(kind="race", value="战士族")],
                                count=3)],
        methods=[SummonMethod(action="banish", zone="mz")],
        limit="must_be", cannot_be_material=["fusion"])
    lum.lua = emit.emit_script(lum, tier=1)
    assert CS.material_line(lum, "zh_cn") == "包含「星奏」怪兽的战士族怪兽×3", \
        CS.material_line(lum, "zh_cn")
    assert "Fusion.AddContactProc" in lum.lua, lum.lua[:400]

    offered = {"n": 0}
    orig = bot.SimpleBot._idlecmd

    def spy(self, msg, state):
        res = orig(self, msg, state)
        if lum.id in [int(x.get("code") or 0) for x in (msg.get("spsummon") or [])]:
            offered["n"] += 1
        return res

    bot.SimpleBot._idlecmd = spy
    try:
        fillers = [89631139, 45467446, 73176492, 77098843, 85861495, 385172]
        info = {"field": [{"code": mat_id, "team": 0, "seq": i, "pos": 1}
                          for i in range(3)],
                "action": {"summon_code": lum.id}}
        res = bot.run_duel([lum.id] * 3 + [mat_id] * 3 + fillers,
                           fillers[:4] * 6, seed=7, max_steps=2500,
                           cards={lum.id: lum, mat_id: mat}, scenario=info)
    finally:
        bot.SimpleBot._idlecmd = orig
    errs = [str(e) for e in (res.get("errors") or [])]
    moves = [e for e in (res.get("log") or []) if int(e.get("id") or 0) == 50]
    up = {int(e.get("turn") or 0) for e in moves
          if int(e.get("code") or 0) == lum.id
          and int(e.get("to_location") or 0) & oc.LOCATION_MZONE}
    ban = {int(e.get("turn") or 0) for e in moves
           if int(e.get("code") or 0) == mat_id
           and int(e.get("to_location") or 0) & oc.LOCATION_REMOVED}
    n_ban = len([e for e in moves if int(e.get("code") or 0) == mat_id
                 and int(e.get("to_location") or 0) & oc.LOCATION_REMOVED])
    assert not errs, f"引擎报错：{errs[:2]}"
    assert offered["n"] > 0, "引擎没把接触召唤列为合法动作（AddContactProc 未生效）"
    assert up & ban and n_ban >= 3, (
        f"接触召唤未实际执行：上场回合={sorted(up)} 除外素材回合={sorted(ban)} "
        f"除外次数={n_ban}")
    return (f"引擎提供接触召唤 {offered['n']} 次，第 {sorted(up & ban)[:2]} 回合"
            f"除外 {n_ban} 只素材后额外卡组上场")

check("接触召唤上桌（真 ocgcore）", _contact_fusion_duel)


# ── 3.6 四类「正规召唤」（缺陷 #37 的验收：空壳卡不许通过）─────────────
#: 探针魔法：与真实「融合 / 同调 / 升阶 / 连接」魔法用同一条判定链。
#: IDLE 的 spsummon 列表在本驱动下测不出正规召唤（实测四类全 0，手写官方
#: 风格脚本同样 0 —— 那是观测盲区），所以改成「谓词 + 执行」两层判据：
#: 探针只在引擎认为「这张卡可以这样召唤」时才可发动，然后真的把卡召唤上场。
_SUMMON_PROBE = """local s,id=GetID()
function s.initial_effect(c)
	local e1=Effect.CreateEffect(c)
	e1:SetCategory(CATEGORY_SPECIAL_SUMMON)
	e1:SetType(EFFECT_TYPE_ACTIVATE)
	e1:SetCode(EVENT_FREE_CHAIN)
	e1:SetTarget(s.tg)
	e1:SetOperation(s.op)
	c:RegisterEffect(e1)
end
function s.filter(c,e,tp)
	return c:IsCode(%(target)d) and %(pred)s
end
function s.tg(e,tp,eg,ep,ev,re,r,rp,chk)
	if chk==0 then return Duel.IsExistingMatchingCard(s.filter,tp,LOCATION_EXTRA,0,1,nil,e,tp) end
	Duel.SetOperationInfo(0,CATEGORY_SPECIAL_SUMMON,nil,1,tp,LOCATION_EXTRA)
end
function s.op(e,tp,eg,ep,ev,re,r,rp)
	local g=Duel.SelectMatchingCard(tp,s.filter,tp,LOCATION_EXTRA,0,1,1,nil,e,tp)
	if #g==0 then return end
	local tc=g:GetFirst()
	local mg=Duel.GetMatchingGroup(nil,tp,LOCATION_MZONE,0,nil)
	%(exec)s
end
"""

_SUMMON_KINDS = {
    "融合": dict(
        id=210000051, frame="fusion", level=8,
        parts=[("archetype", "星奏", 3)],
        mat_levels=(4, 4, 4), n_mat=3,
        pred="c:IsCanBeSpecialSummoned(e,SUMMON_TYPE_FUSION,tp,false,false) "
             "and c:CheckFusionMaterial(Duel.GetFusionMaterial(tp),nil,tp)",
        exec="local fmg=Duel.SelectFusionMaterial(tp,tc,Duel.GetFusionMaterial(tp),nil,tp)\n"
             "\tif not fmg or #fmg==0 then return end\n"
             "\ttc:SetMaterial(fmg)\n"
             "\tDuel.SendtoGrave(fmg,REASON_EFFECT+REASON_MATERIAL+REASON_FUSION)\n"
             "\tDuel.BreakEffect()\n"
             "\tDuel.SpecialSummon(tc,SUMMON_TYPE_FUSION,tp,tp,false,false,POS_FACEUP)\n"
             "\ttc:CompleteProcedure()"),
    "同步": dict(
        id=210000052, frame="synchro", level=8,
        parts=[("tuner", "", 1), ("non_tuner", "", 2)],
        # ⚠ 等级必须对得上：协调 2 + 协调以外 3+3 = 8（先前给 4+4+4 时
        #   IsSynchroSummonable 返回 false 是**正确**行为，不是缺陷）
        mat_levels=(2, 3, 3), n_mat=3, tuner_first=True,
        pred="c:IsCanBeSpecialSummoned(e,SUMMON_TYPE_SYNCHRO,tp,false,false) "
             "and c:IsSynchroSummonable(nil)",
        exec="if #mg==0 then return end\n"
             "\ttc:SetMaterial(mg)\n"
             "\tDuel.SynchroSummon(tp,tc,mg)\n"
             "\ttc:CompleteProcedure()"),
    "超量": dict(
        id=210000053, frame="xyz", level=4,
        parts=[("level", "", 2)],
        mat_levels=(4, 4), n_mat=2,
        pred="c:IsCanBeSpecialSummoned(e,SUMMON_TYPE_XYZ,tp,false,false)",
        exec="if #mg<2 then return end\n"
             "\ttc:SetMaterial(mg)\n"
             "\tDuel.SpecialSummon(tc,SUMMON_TYPE_XYZ,tp,tp,false,false,POS_FACEUP)\n"
             "\ttc:CompleteProcedure()"),
    "连接": dict(
        id=210000054, frame="link", level=2,
        parts=[("any", "", 2)],
        mat_levels=(4, 4), n_mat=2,
        pred="c:IsCanBeSpecialSummoned(e,SUMMON_TYPE_LINK,tp,false,false) "
             "and c:IsLinkSummonable(nil)",
        exec="if #mg<2 then return end\n"
             "\ttc:SetMaterial(mg)\n"
             "\tDuel.LinkSummon(tp,tc,mg)\n"
             "\ttc:CompleteProcedure()"),
}


def _proper_summons_duel():
    """四类正规召唤：引擎认不认 + 真的上不上场（真 ocgcore）。"""
    from cardforge.duel import bot, engine, ocgcore as oc
    from cardforge.content.lua import emit
    from cardforge.core.models import CardSpec, MaterialPart, SummonSpec
    try:
        st = engine.detect()
    except Exception as e:
        return f"SKIP: 引擎探测失败（{e}）"
    if getattr(st, "level", "") != "ocgcore":
        return f"SKIP: 未检测到 ocgcore（{getattr(st, 'reason', '') or '引擎不可用'}）"

    vanilla = "local s,id=GetID()\nfunction s.initial_effect(c)\nend\n"
    spell_id = 210000055
    results: list[str] = []
    fails: list[str] = []

    for name, spec_d in _SUMMON_KINDS.items():
        tid = spec_d["id"]
        target = CardSpec(id=tid, name=f"测试{name}", frame=spec_d["frame"],
                          attribute="光", race="战士族", level=spec_d["level"],
                          atk=3000, dfd=(0 if spec_d["frame"] == "link" else 2500),
                          archetype="星奏", setcode="0x1001",
                          link_markers=(["左下", "下"] if spec_d["frame"] == "link" else []))
        parts = []
        for kind, value, count in spec_d["parts"]:
            if kind in ("tuner", "non_tuner", "any"):
                parts.append(MaterialPart(kind="any", value="", tuner=kind,
                                          count=count) if kind != "any"
                             else MaterialPart(kind="any", value="", count=count))
            else:
                parts.append(MaterialPart(kind=kind, value=value, count=count))
        target.summon = SummonSpec(materials=parts)
        target.lua = emit.emit_script(target, tier=1)

        mats = []
        for i, lv in enumerate(spec_d["mat_levels"]):
            mid = 210000041 + i
            mats.append(CardSpec(
                id=mid, name=f"素材{mid}", frame="effect", attribute="光",
                race="战士族", level=lv, atk=1600, dfd=1200,
                archetype="星奏", setcode="0x1001",
                tags=(["tuner"] if (spec_d.get("tuner_first") and i == 0) else []),
                effects=[], lua=vanilla))

        spell = CardSpec(id=spell_id, name="探针", frame="spell", spell_kind="normal",
                         attribute="光", race="战士族", level=0, atk=0, dfd=0)
        spell.lua = _SUMMON_PROBE % {"target": tid, "pred": spec_d["pred"],
                                     "exec": spec_d["exec"]}

        offered = {"n": 0}
        orig = bot.SimpleBot._idlecmd

        def spy(self, msg, state, _o=orig, _n=offered):
            res = _o(self, msg, state)
            if spell_id in [int(x.get("code") or 0) for x in (msg.get("activate") or [])]:
                _n["n"] += 1
            return res

        bot.SimpleBot._idlecmd = spy
        try:
            cards = {tid: target, spell_id: spell}
            for m in mats:
                cards[m.id] = m
            info = {"hand": [{"code": spell_id, "team": 0,
                              "loc": oc.LOCATION_HAND, "pos": oc.POS_FACEUP_ATTACK}],
                    "field": [{"code": m.id, "team": 0, "seq": i, "pos": 1}
                              for i, m in enumerate(mats)]}
            res = bot.run_duel([tid] * 3 + [m.id for m in mats] + [spell_id] * 3,
                               [89631139, 45467446, 73176492, 77098843],
                               seed=7, max_steps=500, cards=cards, scenario=info)
        finally:
            bot.SimpleBot._idlecmd = orig

        moves = [e for e in (res.get("log") or [])
                 if int(e.get("id") or 0) == 50 and int(e.get("code") or 0) == tid]
        landed = [e for e in moves if int(e.get("to_location") or 0) & oc.LOCATION_MZONE]
        errs = [str(e) for e in (res.get("errors") or [])]
        if errs:
            fails.append(f"{name}：引擎报错 {errs[0][:60]}")
        elif offered["n"] <= 0:
            fails.append(f"{name}：引擎不认为这张卡可以{name}召唤（谓词从未成立）")
        elif not landed:
            fails.append(f"{name}：判定成立但没真的上场")
        else:
            results.append(f"{name}谓词{offered['n']}次/上场{len(landed)}次")

    assert not fails, "；".join(fails)
    return "四类正规召唤均成立：" + "、".join(results)


check("融合/同步/超量/连接 正规召唤（真 ocgcore）", _proper_summons_duel)


def _shell_fusion_not_summonable():
    """反向验收（缺陷 #37）：**只填卡文**的融合卡，引擎不许能融合召唤它。

    这是用户报障的原始现象：卡在额外卡组、能被别的卡效果特召，但正规融合
    召唤的入口不存在。判据与正例完全对称 —— 谓词从未成立即算通过。
    """
    from cardforge.duel import bot, engine, ocgcore as oc
    from cardforge.content.lua import emit
    from cardforge.core.models import CardSpec, SummonSpec
    try:
        st = engine.detect()
    except Exception as e:
        return f"SKIP: 引擎探测失败（{e}）"
    if getattr(st, "level", "") != "ocgcore":
        return f"SKIP: 未检测到 ocgcore（{getattr(st, 'reason', '') or '引擎不可用'}）"

    vanilla = "local s,id=GetID()\nfunction s.initial_effect(c)\nend\n"
    tid, spell_id = 210000061, 210000065
    shell = CardSpec(id=tid, name="空壳融合", frame="fusion", attribute="光",
                     race="战士族", level=8, atk=3000, dfd=2500,
                     archetype="星奏", setcode="0x1001",
                     effects=[{"kind": "", "raw_text": "①：抽 1 张卡。"}])
    shell.summon = SummonSpec(text_i18n={"zh_cn": "包含「星奏」怪兽的战士族怪兽×3"})
    shell.lua = emit.emit_script(shell, tier=1)
    # 注意：脚本的**注释**里就写着「未生成 Fusion.AddProcMix」，所以判据必须走
    # readiness 的剥注释逻辑，不能直接 `in lua`（这正是缺陷 #37 的盲点）。
    from cardforge.content.lua import readiness as RDY
    assert not RDY.analyze_lua(shell.lua)["procs"], "空壳样本不该含可执行的召唤流程"

    mats = [CardSpec(id=210000041 + i, name=f"素材{210000041 + i}", frame="effect",
                     attribute="光", race="战士族", level=4, atk=1600, dfd=1200,
                     archetype="星奏", setcode="0x1001", effects=[], lua=vanilla)
            for i in range(3)]
    spell = CardSpec(id=spell_id, name="探针", frame="spell", spell_kind="normal",
                     attribute="光", race="战士族", level=0, atk=0, dfd=0)
    spell.lua = _SUMMON_PROBE % {
        "target": tid,
        "pred": _SUMMON_KINDS["融合"]["pred"],
        "exec": _SUMMON_KINDS["融合"]["exec"]}

    offered = {"n": 0}
    orig = bot.SimpleBot._idlecmd

    def spy(self, msg, state):
        res = orig(self, msg, state)
        if spell_id in [int(x.get("code") or 0) for x in (msg.get("activate") or [])]:
            offered["n"] += 1
        return res

    bot.SimpleBot._idlecmd = spy
    try:
        cards = {tid: shell, spell_id: spell}
        for m in mats:
            cards[m.id] = m
        info = {"hand": [{"code": spell_id, "team": 0,
                          "loc": oc.LOCATION_HAND, "pos": oc.POS_FACEUP_ATTACK}],
                "field": [{"code": m.id, "team": 0, "seq": i, "pos": 1}
                          for i, m in enumerate(mats)]}
        res = bot.run_duel([tid] * 3 + [m.id for m in mats] + [spell_id] * 3,
                           [89631139, 45467446, 73176492, 77098843],
                           seed=7, max_steps=400, cards=cards, scenario=info)
    finally:
        bot.SimpleBot._idlecmd = orig

    moves = [e for e in (res.get("log") or [])
             if int(e.get("id") or 0) == 50 and int(e.get("code") or 0) == tid
             and int(e.get("to_location") or 0) & oc.LOCATION_MZONE]
    errs = [str(e) for e in (res.get("errors") or [])]
    assert not errs, f"引擎报错：{errs[:1]}"
    assert offered["n"] == 0 and not moves, (
        f"空壳融合卡竟然能被融合召唤（谓词 {offered['n']} 次、上场 {len(moves)} 次）"
        " —— 说明召唤流程在没有素材条件时被错误地放行了")
    return "只填卡文的空壳融合卡：引擎全程不提供融合召唤（谓词 0 次、上场 0 次）"


check("空壳卡不许被正规召唤（反向，真 ocgcore）", _shell_fusion_not_summonable)


# ── 4. 质量门 ────────────────────────────────────────────────────────
print("\n[4] 质量门")


def _gates():
    from cardforge.core.models import CardSpec, Archetype
    from cardforge.pipeline import gates as G
    s = CardSpec(id=210000011, name="x", frame="effect", attribute="光",
                 race="魔法师族", level=4, atk=1600, dfd=1200)
    s.text_i18n = {"zh_cn": "①：测试。"}
    r1 = G.g1_balance(s)
    assert r1.status in ("pass", "warn"), r1.status
    r3 = G.g3_duel(s)
    # 这条断言守的是本项目第一原则：**没真跑过就绝不能报 pass**。
    # 驱动写完之前它必须 skipped；驱动写完之后它必须真跑出场景/对局计数。
    # 两种时代都成立的写法是断"不变式"，而不是断某个固定状态值。
    assert r3.status in ("pass", "warn", "fail", "skipped"), r3.status
    _ran = ("scenarios" in (r3.summary or "")) or ("duels" in (r3.summary or ""))
    if r3.status == "pass":
        assert _ran, f"G3 报 pass 但没记录任何真跑过的证据：{r3.summary}"
    if r3.status == "skipped":
        assert r3.degraded, "G3 降级必须写明缺什么"
    r5 = G.g5_export(str(ROOT / "_nope"))
    assert r5.status in ("skipped", "fail"), r5.status
    assert G.run("G9").status == "fail"
    a = Archetype(name="星奏")
    r4 = G.g4_series(a, [])
    assert r4.status == "fail"
    rep = G.g1_balance(s)
    errs = [i.code for i in rep.issues if i.level == "ERROR"]
    if errs:
        G.waive(rep, errs[0], "单元测试用", who="smoke")
        assert any(i.waived for i in rep.issues)
    p = G.write_audit(rep, {"card_id": "smoke"})
    assert Path(p).exists()
    return f"G1={r1.status} G3={r3.status}(降级) G4={r4.status} G5={r5.status}；豁免留痕与审计报告 OK"

check("G1–G5 与留痕", _gates)

# ── 5. 可选能力 ──────────────────────────────────────────────────────
print("\n[5] 可选能力（缺失不影响主流程）")


def _comfy():
    try:
        from cardforge.art import client as ac
    except Exception as e:
        return f"SKIP:art 模块未就绪（{type(e).__name__}）"
    c = ac.ComfyClient()
    if not c.alive():
        return "SKIP:ComfyUI 未运行"
    m = c.models()
    return "ComfyUI 在线：" + "，".join(f"{k} {len(v)}" for k, v in m.items())

check("ComfyUI 出图", _comfy)


def _export():
    try:
        from cardforge.pool import repo  # noqa: F401
        from cardforge.export import expansions  # noqa: F401
    except Exception as e:
        return f"SKIP:pool/export 模块未就绪（{type(e).__name__}）"
    return "pool/export 可用"

check("卡池与导出", _export)


def _pool_threads():
    """官方卡池必须能在**工作线程**里查得到 —— Web 服务每请求一个线程。

    曾经这里全局缓存一条 sqlite 连接：主线程打开后，工作线程拿到的是
    ``ProgrammingError: SQLite objects created in a thread can only be used in
    that same thread``，而每个查询方法都把异常吞成 warning，
    界面于是显示成「卡池里没有这张卡」「字段码解析不出来」。
    """
    try:
        from cardforge.pool import official as off
    except Exception as e:
        return f"SKIP:官方卡池模块未就绪（{type(e).__name__}）"
    pool = off.load()
    if not pool.available or not pool.count():
        return "SKIP:官方卡池未挂载（把 cards_zh.cdb 放进 vendor/data/）"
    import threading
    box: dict = {}

    def work():
        try:
            box["count"] = pool.count()
            hit = pool.search("青眼白龙", limit=3)
            box["hit_id"] = int(hit[0]["id"]) if hit else 0
        except Exception as e:                       # noqa: BLE001
            box["err"] = f"{type(e).__name__}: {e}"

    t = threading.Thread(target=work)
    t.start()
    t.join(20)
    if box.get("err"):
        return f"FAIL:工作线程查卡失败 {box['err']}"
    if not box.get("count") or not box.get("hit_id"):
        return f"FAIL:工作线程查不到卡（count={box.get('count')} hit={box.get('hit_id')}）"
    return f"工作线程可查卡：{box['count']} 张，青眼白龙 → {box['hit_id']}"


check("官方卡池跨线程可用", _pool_threads)


def _duel():
    from cardforge.duel import engine as E
    st = E.detect(try_load=True)
    if st.level != "ocgcore":
        return f"SKIP:未检测到引擎（{st.reason}）"
    return f"ocgcore 已加载：{Path(st.lib_path).name}"

check("对局引擎", _duel)

# ── 6. 界面静态守卫 ──────────────────────────────────────────────────
print("\n[6] 界面静态守卫")


def _css_hidden_guard():
    """防「空弹窗常驻盖住整页」这一类 CSS 陷阱。

    浏览器给 ``[hidden]`` 的是 UA 样式 ``display:none``，作者样式里任何一条
    ``.foo { display: grid }`` 都会把它盖掉 —— 于是写了 ``hidden`` 的浮层
    照样显示。历史缺陷：``.modal-backdrop``（空弹窗 + 66% 黑遮罩，页面点不动）
    与 ``.job-progress``（一直露着空进度条）。
    """
    import re as _re
    html = (ROOT / "web/index.html").read_text(encoding="utf-8")
    css = "\n".join(p.read_text(encoding="utf-8")
                    for p in sorted((ROOT / "web/css").glob("*.css")))
    if not _re.search(r"\[hidden\]\s*\{[^}]*display\s*:\s*none\s*!important", css):
        raise AssertionError("css 里缺全局守卫 `[hidden] { display: none !important; }`")
    # 逐个点名 index.html 里用了 hidden 的元素，确认它们真的被全局规则兜住
    tagged = _re.findall(r'<(\w+)([^>]*\shidden\b[^>]*)>', html)
    risky = []
    for tag, attrs in tagged:
        cls = _re.search(r'class="([^"]+)"', attrs)
        for c in (cls.group(1).split() if cls else []):
            if _re.search(rf"\.{_re.escape(c)}\b[^{{]*\{{[^}}]*display\s*:", css):
                risky.append(f".{c}<{tag}>")
    return (f"全局守卫在位；{len(tagged)} 个元素用了 hidden，"
            f"其中 {len(set(risky))} 处的作者样式带 display（靠守卫兜住）")


check("CSS hidden 守卫", _css_hidden_guard)


def _next_id_unique():
    from cardforge.server import api_card as A, kernel as K
    used = {int(c["id"]) for c in K.cards_index() if c.get("id") is not None}
    n = A._next_id()
    assert n >= 210000000, n
    assert n not in used, f"新卡号 {n} 已被工作区占用：{sorted(used)}"
    return f"下一个空号 {n}，避开了工作区 {len(used)} 张卡"

check("新卡号不覆盖工作区", _next_id_unique)

# ── 汇总 ─────────────────────────────────────────────────────────────
print("\n" + "=" * 72)
print(f"通过 {len(PASS)} · 跳过 {len(WARN)} · 失败 {len(FAIL)}")
if FAIL:
    print("\n失败项：")
    for n, why, ms in FAIL:
        print(f"  - {n}: {why}")
print("=" * 72)
sys.exit(1 if FAIL else 0)
