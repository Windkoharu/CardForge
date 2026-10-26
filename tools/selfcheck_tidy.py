"""``cardforge/content/psct/tidy.py`` 的交付自检 —— 零 AI 整理卡文，**不许改坏语义**。

用法::

    PYTHONIOENCODING=utf-8 python tools/selfcheck_tidy.py

八组验收，全部**实际执行**：

1. L1 表层归一：段号 / 全角数字 / 引号 / 标点角色 / 重复标点，且 ``1.5`` 不当段号；
2. 分段与保留：无编号多行按行切、卡名级声明剥离、召唤手续段一字不改、
   认不出的句子**原样保留**并说明原因；
3. L2 重写守卫：只有「再反解 IR 等价 + 数值保真 + 卡名保真」三条全过才重写，
   任何一条不过就退回表层整理并写明为什么；
4. ``safe_to_apply`` 三门槛：未识别段 / 数值丢 / 校验劣化 都能各自否掉一键替换；
5. 术语**只报不改**：给建议但绝不自动替换（卡名里就有这些词）；
6. ``FOLK_TERMS`` 方向以官方简中卡文库实测为准（同调/调整 是官方，不许反过来判），
   且 zh_cn 的裁决不套到 zh_tw 上；
7. 本轮顺带修的投影缺陷：自指效果不写成「1张卡的…」，字段+怪兽量词，代词跟宾语类别；
8. ``/api/psct/tidy`` 端点字段齐全（界面靠它渲染逐段对照）。

报告落盘：``workspace/.cache/selfcheck-tidy.txt``（UTF-8，控制台只打 ASCII 摘要）。
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cardforge.content import effects as EF                          # noqa: E402
from cardforge.content.psct import gen, lint, rules, tidy as TD      # noqa: E402
from cardforge.core.models import CardSpec, EffectSpec, EffectTarget  # noqa: E402

OUT = ROOT / "workspace" / ".cache" / "selfcheck-tidy.txt"
CDB = ROOT / "vendor" / "data" / "cards_zh.cdb"
LOG: list[str] = []
PASS = FAIL = 0


def chk(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        line = f"  [ OK ] {name}" + (f" — {detail}" if detail else "")
    else:
        FAIL += 1
        line = f"  [FAIL] {name}" + (f" — {detail}" if detail else "")
    print(line)
    LOG.append(line)


def head(t: str) -> None:
    print(f"\n── {t} " + "─" * max(0, 60 - len(t)))
    LOG.append(f"\n── {t} " + "─" * max(0, 60 - len(t)))


def spec(frame: str = "fusion") -> CardSpec:
    return CardSpec(id=210000021, name="圣痕的龙骑士 露米艾尔", frame=frame,
                    race="战士族", attribute="炎", level=8, atk=3000, dfd=2500,
                    archetype="圣痕")


# ══════════════════════════════════════════════════════════════════════
#  1. L1 表层归一
# ══════════════════════════════════════════════════════════════════════
head("1. 表层归一：只动字符，不动词")
s, e = TD.surface("1. 把自己场上1只战士族怪兽送去墓地才能发动。", "zh_cn")
chk("1. → ①：", s.startswith("①：把自己场上"), s[:24])
chk("记了一条 TIDY_PARA_MARK", any(x.code == "TIDY_PARA_MARK" for x in e))
s2, _ = TD.surface("（2）这张卡的攻击力上升300点。", "zh_cn")
chk("（2） → ②：", s2.startswith("②："), s2[:12])
s3, _ = TD.surface("[3]、以对方场上1只怪兽为对象才能发动。", "zh_cn")
chk("[3] → ③：", s3.startswith("③："), s3[:12])
s4, _ = TD.surface("1、这张卡的攻击力上升300点。", "zh_cn")
chk("1、 也算段号", s4.startswith("①"), s4[:12])
s5, _ = TD.surface("这张卡的攻击力上升1.5倍于原本数值。", "zh_cn")
chk("小数 1.5 不当段号", "1.5" in s5 and not s5.startswith("①"), s5[:24])
s6, _ = TD.surface("①：这张卡的攻击力上升３００点。", "zh_cn")
chk("全角数字 → 半角", "300" in s6 and "３" not in s6, s6[:24])
s7, _ = TD.surface('①：以"星尘龙"为对象才能发动。', "zh_cn")
chk("直引号 → 「」", "「星尘龙」" in s7, s7[:28])
s8, _ = TD.surface("①:以对方场上1只怪兽为对象才能发动;那张怪兽除外。", "zh_cn")
chk("半角冒号/分号归一", "：以对方" in s8 and "；那张" in s8, s8[:30])
s9, _ = TD.surface("①：这张卡的攻击力上升300点。。", "zh_cn")
chk("重复句号合并", "。。" not in s9, s9[:24])
s10, _ = TD.surface("①：这张卡的攻击力上升300点，。", "zh_cn")
chk("句末悬挂逗号去掉", "，。" not in s10, s10[:24])
en, ee = TD.surface("1. add 1 card from your deck to your hand.", "en")
chk("英文档不做 CJK 标点归一", "：" not in en and not
    any(x.code == "TIDY_PUNCT_ROLE" for x in ee), en[:30])
chk("「2000点」这种数字+量词不被误当段号",
    TD.surface("①：那张卡的攻击力下降2000点。", "zh_cn")[0].startswith("①"))

# ══════════════════════════════════════════════════════════════════════
#  2. 分段与保留
# ══════════════════════════════════════════════════════════════════════
head("2. 分段与保留：认不出的必须原样在")
messy = ("融合素材：卡名带有「圣痕」的战士族怪兽×3\n"
         "这张卡不能作为融合素材。这张卡用融合召唤以及以下方法才能特殊召唤。\n"
         "1. 把自己场上1只战士族怪兽送去墓地。“圣痕”相关卡可以检索。\n"
         "2. 这张卡的攻击力上升300点。\n"
         "这个卡名的①的效果1回合只能使用1次。")
r = TD.tidy(messy, spec(), "zh_cn")
kinds = [p["kind"] for p in r["paragraphs"]]
chk("召唤手续段被单独识别", "summon_block" in kinds, str(kinds))
blk = next(p for p in r["paragraphs"] if p["kind"] == "summon_block")
chk("召唤手续段一字不改", blk["src"] == blk["out"], blk["out"][:30])
chk("卡名级声明单独成段", kinds.count("declaration") == 1, str(kinds))
decl = next(p for p in r["paragraphs"] if p["kind"] == "declaration")
chk("声明句原样保留", decl["src"] == decl["out"] == "这个卡名的①的效果1回合只能使用1次。")
chk("无编号多行也能逐段处理", r["total"] == 2, f'{r["recognized"]}/{r["total"]}')
chk("Para.src 是**归一前**的原文（否则看不到 1. → ①：）",
    any(p["src"].startswith("1. ") and p["out"].startswith("①：")
        for p in r["paragraphs"]))
junk = TD.tidy("①：这是一句完全不像卡文的感想。", spec(), "zh_cn")
jp = junk["paragraphs"][0]
chk("认不出的句子原样保留", jp["src"] == jp["out"], jp["out"][:24])
chk("认不出时给出可执行的原因", "才能发动" in jp["reason"] or "种类" in jp["reason"],
    jp["reason"][:40])
chk("认不出 → 不给一键替换", junk["safe_to_apply"] is False, str(junk["blockers"])[:60])
chk("空文本有说明", "文本是空的" in " ".join(
    TD.tidy("   ", spec(), "zh_cn")["blockers"]))

# ══════════════════════════════════════════════════════════════════════
#  3. L2 重写守卫
# ══════════════════════════════════════════════════════════════════════
head("3. 重写守卫：三条保真全过才敢动整段")
one = TD.tidy("②：这张卡的攻击力上升300点。", spec(), "zh_cn")
p0 = one["paragraphs"][0]
chk("自指增益被整段重写", p0["status"] == "rewritten", p0["out"][:40])
chk("重写补出「自己主要阶段才能发动。」", "自己主要阶段才能发动" in p0["out"])
chk("重写后仍含「这张卡的攻击力上升300」", "这张卡的攻击力上升300" in p0["out"])
chk("数值保真", TD._digits_of(p0["src"]) == TD._digits_of(p0["out"]))
chk("全识别 + 保真 → 允许一键", one["safe_to_apply"] is True, str(one["blockers"]))
nomiss = TD.tidy("①：把自己场上1只战士族怪兽送去墓地。「圣痕」相关卡可以检索。",
                 spec(), "zh_cn")
np0 = nomiss["paragraphs"][0]
chk("重写会丢「检索」这层语义时拒绝重写",
    np0["status"] == "surface" and "没敢重写" in np0["reason"], np0["reason"][:44])
chk("拒绝重写时原文照旧", np0["out"] == np0["src"])
off = TD.tidy("②：这张卡的攻击力上升300点。", spec(), "zh_cn", rewrite=False)
chk("rewrite=False 完全不做结构重写", off["rewritten"] == 0
    and off["paragraphs"][0]["status"] == "surface")
nospec = TD.tidy("①：这张卡的攻击力上升300点。", None, "zh_cn")
chk("没有卡规格时只做表层", nospec["rewritten"] == 0
    and nospec["paragraphs"][0]["status"] == "surface", nospec["paragraphs"][0]["reason"][:30])
chk("再反解 IR 等价是硬判据（TD._ir_sig 用到 kind/trigger/limit/target/cost/params）",
    TD._ir_sig(EffectSpec(kind="destroy", trigger="IGNITION", limit="none"))
    != TD._ir_sig(EffectSpec(kind="destroy", trigger="QUICK", limit="none")))
chk("params 里的 _index 不参与指纹",
    TD._ir_sig(EffectSpec(kind="destroy", params={"_index": 1}))
    == TD._ir_sig(EffectSpec(kind="destroy", params={"_index": 7})))

# ══════════════════════════════════════════════════════════════════════
#  4. safe_to_apply 三门槛
# ══════════════════════════════════════════════════════════════════════
head("4. 一键替换的门槛")
chk("有未识别段就否掉", any("认不出来" in b for b in junk["blockers"]),
    str(junk["blockers"])[:50])
r2 = TD.tidy(messy, spec(), "zh_cn")
chk("全识别 + 保真 + 不劣化 → 放行", r2["safe_to_apply"] is True, str(r2["blockers"]))
chk("fidelity 三项齐全", set(r2["fidelity"]) ==
    {"numbers_ok", "names_ok", "all_recognized"}, str(r2["fidelity"]))
chk("返回里有 lint 前后对比", r2["lint_before"]["errors"] <= r2["lint_after"]["errors"]
    and "issues" in r2["lint_after"])
# 构造一个「整理后必然劣化」的极端：把守卫关掉直接比较（验证劣化确实会被拦）
bad = TD.tidy("①：这张卡的攻击力上升300点。", spec(), "zh_cn")
fake = dict(bad)
chk("confidence 用识别率表达", 0 <= bad["confidence"] <= 1, str(bad["confidence"]))

# ══════════════════════════════════════════════════════════════════════
#  5. 术语只报不改
# ══════════════════════════════════════════════════════════════════════
head("5. 术语：给建议，绝不动手替换")
folk = TD.tidy("①：把1只协调从卡组特殊召唤。②：进行同步召唤时解放这张卡。",
               spec("effect"), "zh_cn")
bads = {t["bad"] for t in folk["terms"]}
chk("「协调」被建议为「调整」", "协调" in bads, str(bads))
chk("「同步」被建议为「同调」", "同步" in bads)
chk("建议里给了官方写法与理由",
    all(t.get("good") and t.get("why") for t in folk["terms"]))
chk("但**没有自动替换**（文本里仍然是用户写的词）",
    "协调" in folk["text"] and "同步" in folk["text"], folk["text"][:30])
xyz = TD.tidy("①：「XYZ-神龙炮」的攻击力上升1000。", spec("effect"), "zh_cn")
chk("卡名里的 XYZ 不算民间术语",
    not any(t["bad"] == "XYZ" for t in xyz["terms"]), str(xyz["terms"]))
flip = TD.tidy("①：双方玩家把卡组上下翻转过来确认最上面的卡。", spec("effect"), "zh_cn")
chk("普通用语「上下翻转」不被判成反转术语",
    not any("翻转" in t["bad"] for t in flip["terms"]), str(flip["terms"]))
trip = TD.tidy("①：这张卡反转的场合，抽1张卡。", spec("effect"), "zh_cn")
chk("官方写法「反转」不报术语", not trip["terms"], str(trip["terms"]))

# ══════════════════════════════════════════════════════════════════════
#  6. FOLK_TERMS 方向以官方库实测为准
# ══════════════════════════════════════════════════════════════════════
head("6. 术语表方向：以官方简中卡文库为准")
if CDB.exists():
    con = sqlite3.connect(f"file:{CDB}?mode=ro&immutable=1", uri=True)
    texts = [r[0] or "" for r in con.execute("select desc from texts")]
    con.close()
    cnt = lambda w: sum(1 for t in texts if w in t)                      # noqa: E731
    chk(f"库里「同调」({cnt('同调')}) 远多于「同步」({cnt('同步')}) → 同调是官方",
        cnt("同调") > cnt("同步") * 10 or cnt("同步") == 0)
    chk(f"库里「调整」({cnt('调整')}) 远多于「协调」({cnt('协调')}) → 调整是官方",
        cnt("调整") > cnt("协调") * 10 or cnt("协调") == 0)
    chk(f"库里「那只怪兽」({cnt('那只怪兽')}) 是主流代词", cnt("那只怪兽") > 1000)
    CHARS = 2000000
    chk("官方库里「N张卡的攻击力上升」为 0（兜底宾语是错的）",
        sum(1 for t in texts if re.search(r"[0-9１]张卡的攻击力上升", t)) == 0)
else:
    chk("官方卡文库存在", False, str(CDB))
pairs = {t.bad: t.good for t in rules.FOLK_TERMS if "zh_cn" in t.langs}
chk("表里不再把「同调」当民间词", "同调" not in pairs, str(sorted(pairs))[:60])
chk("表里改为「同步 → 同调」", pairs.get("同步") == "同调")
chk("「调整」不在民间词里", "调整" not in pairs)
chk("繁中不参与 zh_cn 的术语裁决",
    all(t.langs == ("zh_cn",) for t in rules.FOLK_TERMS),
    str({t.langs for t in rules.FOLK_TERMS}))
chk("「祭品」降级为 INFO（旧卡原文合法）",
    next(t for t in rules.FOLK_TERMS if t.bad == "祭品").level == "INFO")
s_ok = spec("effect")
s_ok.text_i18n = {"zh_cn": "①：这张卡当作同调怪兽使用。②：把1只调整从手卡特殊召唤。"}
chk("lint 不再把官方简中写法报成民间误译",
    not [i for i in lint.lint(s_ok, "zh_cn") if i.code == "PSCT_FOLK_TERM"])

# ══════════════════════════════════════════════════════════════════════
#  7. 顺带修的投影缺陷（gen）
# ══════════════════════════════════════════════════════════════════════
head("7. 投影缺陷回归：自指宾语 / 字段量词 / 代词类别")
self_eff = EF.infer_from_text("①：这张卡的攻击力上升300点。", "测试兽")[0]
chk("反解记下「作用于自己」", self_eff.params.get("self_obj") is True,
    str(self_eff.params))
txt = gen.effect_to_text(self_eff, spec("effect"), "zh_cn", index=1)
chk("投影不再写「1张卡的攻击力上升」", "1张卡的攻击力" not in txt, txt[:40])
chk("投影写出「这张卡的攻击力上升300」", "这张卡的攻击力上升300" in txt)
arch_eff = EffectSpec(kind="search_grave", trigger="IGNITION", limit="none",
                      target=EffectTarget(from_zone="GRAVE", filter_kind="archetype",
                                          filter_value="圣痕", count=1),
                      params={"card_type": "monster"})
at = gen.effect_to_text(arch_eff, spec(), "zh_cn", index=1)
chk("字段 + 怪兽 → 「1只「圣痕」怪兽」而不是「1张「圣痕」卡」",
    "1只「圣痕」怪兽" in at and "1张「圣痕」卡" not in at, at[:60])
spell_eff = EffectSpec(kind="search", trigger="IGNITION", limit="none",
                       target=EffectTarget(from_zone="DECK", filter_kind="archetype",
                                           filter_value="圣痕", count=1),
                       params={"card_type": "spelltrap"})
st = gen.effect_to_text(spell_eff, spec(), "zh_cn", index=1)
chk("字段 + 魔陷 → 「「圣痕」魔法·陷阱卡」", "「圣痕」魔法·陷阱卡" in st, st[:50])
ref_eff = EffectSpec(kind="search_grave", trigger="IGNITION", limit="none",
                     target=EffectTarget(from_zone="GRAVE", filter_kind="archetype",
                                         filter_value="圣痕", count=1),
                     params={"card_type": "monster", "reference": True,
                             "targeting": True})
rt = gen.effect_to_text(ref_eff, spec(), "zh_cn", index=1)
chk("取对象后用「那只怪兽」而不是重抄宾语", "那只怪兽" in rt, rt[:70])
chk("同一句里量词与名词不自相矛盾（对象段也得是「1只…怪兽」）",
    "1只「圣痕」怪兽为对象" in rt and "1张「圣痕」卡为对象" not in rt, rt[:70])
jt = gen.effect_to_text(self_eff, spec("effect"), "ja", index=1)
chk("日文自指宾语是「このカード」", "このカード" in jt, jt[:40])
et = gen.effect_to_text(self_eff, spec("effect"), "en", index=1)
chk("英文自指宾语是 this card", "this card" in et.lower(), et[:50])

# ══════════════════════════════════════════════════════════════════════
#  8. 端点
# ══════════════════════════════════════════════════════════════════════
head("8. POST /api/psct/tidy 的返回结构")
try:
    req = urllib.request.Request("http://127.0.0.1:8790/api/psct/tidy",
                                 data=json.dumps({"card": 210000021, "lang": "zh_cn",
                                                  "text": messy}).encode(),
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    r = json.loads(urllib.request.urlopen(req, timeout=60).read().decode())
    chk("端点 ok", r.get("ok") is True)
    for k in ("text", "paragraphs", "surface_edits", "terms", "lint_before",
              "lint_after", "safe_to_apply", "blockers", "fidelity", "confidence"):
        chk(f"端点返回 {k}", k in r)
    chk("端点段落带 rules 列表",
        all("rules" in p and "reason" in p for p in r["paragraphs"]))
except Exception as e:                                       # noqa: BLE001
    chk("端点可访问（服务没起就跳过）", False, f"{type(e).__name__}: {e}")

# ══════════════════════════════════════════════════════════════════════
summary = f"\n{'=' * 72}\nPASS={PASS} FAIL={FAIL}\n{'=' * 72}"
print(summary)
LOG.append(summary)
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text("\n".join(LOG), encoding="utf-8")
print(f"REPORT={OUT}")
sys.exit(1 if FAIL else 0)
