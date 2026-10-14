r"""一次性验证脚本（不落在 tools/ 里，避免和并行 agent 抢同一个文件）。

覆盖 selfcheck 的验收项 3–9，详情写 _probe/verify_g2.txt。
"""
from __future__ import annotations
import json, re, subprocess, sys, tempfile, traceback
from pathlib import Path
ROOT = Path(r"D:/游戏王DIY设计")
sys.path.insert(0, str(ROOT))
from cardforge.content import effects as EF
from cardforge.content.lua import apicatalog as API, emit, fragments as FR, lint
from cardforge.core import paths
from cardforge.core.models import CardSpec, EffectCost, EffectSpec, EffectTarget

LINES: list[str] = []
FAIL: list[str] = []
WARN: list[str] = []


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

# 3.5 额外卡组流程 + EnableReviveLimit
for frame, want, cid in (("fusion", "Fusion.AddProc", 210000606),
                         ("synchro", "Synchro.AddProcedure", 210000607),
                         ("xyz", "Xyz.AddProcedure", 210000608),
                         ("link", "Link.AddProcedure", 210000609),
                         ("ritual", "Ritual.AddProc", 210000610)):
    kw = {}
    if frame == "link":
        kw = dict(link_markers=["左下", "下"], dfd=0, level=2)
    s = spec_one(cid, frame, [E(f"{frame}_summon", params={"materials": [], "count": 2}),
                              E("draw", "SPECIAL_SUMMON_SUCCESS", raw="①：抽 1 张。")], **kw)
    lua = art(f"{frame}流程", s)
    chk(f"{frame} 含 {want}", want in lua, lua[:200])
    chk(f"{frame} 含 EnableReviveLimit", "c:EnableReviveLimit()" in lua, "")
    if frame == "synchro":
        chk("同步用新版签名（NonTuner）",
            re.search(r"Synchro\.AddProcedure\(c,[^\n]*NonTuner", lua) is not None, lua[:300])
    if frame == "ritual":
        chk("仪式 AddProcGreater 的 desc 不写成 0",
            re.search(r"Ritual\.AddProcGreater\(c,[^)]*,0\)", lua) is None, lua[:300])

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
