"""卡图提示词**保真**自检 —— 用户写的话，一个字都不许悄悄消失。

用法::

    PYTHONIOENCODING=utf-8 python tools/selfcheck_prompt.py

为什么单独有一套：出图链路里最容易骗人的就是「提示词看起来按我说的做了」。
历史缺陷（本轮修掉的三类，全部有回归锁）：

* **词典吞字**：中文主体过 :func:`zh_to_tags`，没命中的词静默丢弃 ——
  实测「圣痕 / 露米艾尔 / 眼睛 / 光之翼 / 铠甲」整批消失，画面与要求无关；
* **导出走小路**：「导出工作流 JSON」只带卡名，不带界面上填的主体/风格，
  导出的 CLIPTextEncode 与预览对不上；
* **默认装饰词反对用户**：用户写「半身特写、柔和晨光」，系统仍硬塞
  「full body visible」+「dramatic lighting, rim light」+ 卡种强光氛围句，
  等于当面把话拧回去。

八组验收，全部**实际执行**：

1. 语言口径由**文本编码器**决定（Qwen 系双语编码器 = 原文直送；英文词表 CLIP = 翻译）；
2. 原文直送时用户的话**逐字**在提示词里（主体/风格/背景/附加词，含专有名词与生僻词）；
3. 用户指定取景或光照后，与之冲突的默认装饰词**必须撤**；没指定时**必须留**；
4. 翻译档**不许静默吞字**：翻不出来的词进 ``untranslated``，且中文原文绝不漏进 CLIP；
5. 英文片段不被拆碎（``8-bit`` 保持整词），虚词/最长匹配仍正确；
6. 分层出图两个 pass 各自保真，背景 pass 不带主体导向词；
7. 导出工作流 JSON 里的节点文本 == 编译结果，且**带得上界面填的字段**；
   ``character_sheet`` 的版式指令是**追加**不是覆盖；
8. 台账字段齐全（``prompt_mode``/``untranslated``/``user_input``）——
   图能不能事后复查，全靠这三行。

报告落盘：``workspace/.cache/selfcheck-prompt.txt``（UTF-8，控制台只打 ASCII 摘要）。
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cardforge.art import prompt as PR                                       # noqa: E402
from cardforge.art import profiles as PF                                     # noqa: E402
from cardforge.core.models import ArtRequest, CardSpec                       # noqa: E402

OUT = ROOT / "workspace" / ".cache" / "selfcheck-prompt.txt"
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


CJK = re.compile(r"[\u4e00-\u9fff]{2,}")

SUBJECT = "圣痕龙骑士 露米艾尔，银白长发，红色眼睛，手持骑枪，背后展开光之翼，身穿白银铠甲"
STYLE = "柔和的晨光，半身特写"
BG = "废弃神殿，石柱间漏下晨光，地面积水倒影"

KREA = PF.by_key("krea2")
QWEN = PF.by_key("qwen_image")
ANIM = PF.by_key("animagine")
PONY = PF.by_key("pony")


def spec(frame: str = "fusion") -> CardSpec:
    return CardSpec(id=210000021, name="圣痕的龙骑士 露米艾尔", frame=frame,
                    race="战士族", attribute="炎", level=8, atk=3000, dfd=2500,
                    archetype="圣痕")


def req(**over) -> ArtRequest:
    base = dict(subject=SUBJECT, style=STYLE, background=BG, seed=777,
                profile="auto", card_id=210000021, archetype="圣痕")
    base.update(over)
    return ArtRequest(**base)


# ══════════════════════════════════════════════════════════════════════
#  1. 语言口径由编码器决定
# ══════════════════════════════════════════════════════════════════════
head("1. 语言口径：跟着文本编码器走，不跟偏好走")
chk("krea2 是双语编码器", KREA.bilingual_text_encoder is True,
    "Krea 2 用 qwen3vl_* —— Qwen3-VL 本身就是多语言 LLM")
chk("qwen_image 是双语编码器", QWEN.bilingual_text_encoder is True)
chk("animagine 不是双语编码器", ANIM.bilingual_text_encoder is False)
chk("pony 不是双语编码器", PONY.bilingual_text_encoder is False)
chk("SDXL 系一律不双语", all(not p.bilingual_text_encoder for p in PF.PROFILES
                             if p.is_sdxl_family))
chk("krea2 语言口径写明原文直送", "中文原话直送" in KREA.language_line,
    KREA.language_line)
chk("animagine 语言口径写明必须翻译", "必须先翻成英文标签" in ANIM.language_line)
chk("describe_all 带 bilingual 字段",
    all("bilingual_text_encoder" in d for d in PF.describe_all()))

# ══════════════════════════════════════════════════════════════════════
#  2. 原文直送：用户的话逐字进提示词
# ══════════════════════════════════════════════════════════════════════
head("2. 原文直送：一个词都不丢")
out = PR.build(req(), spec(), KREA)
pos = out["positive"]
chk("模式标为原文直送", out["prompt_mode"] == "原文直送", out["prompt_mode"])
chk("未上报任何丢词", out["untranslated"] == [], str(out["untranslated"]))
chk("主体整句逐字在提示词里", SUBJECT in pos)
chk("风格整句逐字在提示词里", STYLE in pos)
chk("专有名词「露米艾尔」没被当成乱码丢掉", "露米艾尔" in pos)
chk("「圣痕」进了提示词", "圣痕" in pos)
chk("「眼睛」进了提示词", "眼睛" in pos)
chk("「光之翼」进了提示词", "光之翼" in pos)
chk("「铠甲」进了提示词", "铠甲" in pos)
chk("英文画质前缀仍在（模型口径没丢）",
    "highly atmospheric anime illustration" in pos)
chk("种族标签仍从卡面规格推导", "warrior" in pos, "战士族 → warrior 是规格推导，不是用户原话")
chk("user_input 原样回显主体", out["user_input"]["subject"] == SUBJECT)
chk("structure.subject_sent 就是用户原话",
    out["structure"]["subject_sent"] == SUBJECT)
chk("附加正向也逐字进", "品红色雾气" in
    PR.build(req(extra_positive="品红色雾气"), spec(), KREA)["positive"])
chk("双语档不拿词典碎片替换用户措辞", "silvery metal" not in pos,
    "词典会把「银白」翻成 silvery metal —— 原文直送时不该出现")
chk("负向里用户补充原样保留", "多余的装饰" in
    PR.build(req(extra_negative="多余的装饰"), spec(), KREA)["negative"])
chk("单张工作流也认「背景」字段（历史缺陷：只有分层出图才生效）",
    BG in PR.build(ArtRequest(subject="白色长发少女", background=BG, seed=1),
                   None, KREA)["positive"], BG)
chk("背景没填时不会硬塞场景句",
    "The scene behind the subject" not in PR.build(
        ArtRequest(subject="白色长发少女", background="", seed=1), None, KREA)["positive"])

# ══════════════════════════════════════════════════════════════════════
#  3. 用户说过的取景/光照，默认装饰词必须让路
# ══════════════════════════════════════════════════════════════════════
head("3. 冲突检查：用户的话优先于默认装饰")
chk("写了半身特写 → 全身可见句撤掉", "full body visible" not in pos)
chk("写了半身特写 → 换成随描述取景句", "framing follows the description" in pos)
chk("写了晨光 → 默认戏剧强光句撤掉", "dramatic and cinematic, with a strong rim light"
    not in pos)
chk("光照让位说明写进了 notes", "光照句" in out["notes"])
chk("卡种强光氛围句也跟着撤（不然又拉回强发光）",
    "spell-driven light" not in pos and "violet aura" not in pos)
chk("cfg<=1 排除句改用精简版（不再声明单主体居中留白）",
    "single subject is shown, centred" not in pos)
chk("精简版仍保留「不要文字/水印/边框」", "no watermark and no logo" in pos)
plain = PR.build(req(subject="白色长发少女", style="", background=""), None, KREA)
chk("用户没指定取景 → 默认全身构图句保留",
    "full body visible" in plain["positive"] or "whole figure inside the frame"
    in plain["positive"], "卡图需要这条约束，不能因为保真就把它删了")
chk("用户没指定光照 → 默认光照句保留", "Lighting is dramatic and cinematic"
    in plain["positive"])
chk("用户没指定光照 → 卡种氛围句保留", plain["structure"]["frame_atmosphere"]
    in plain["positive"])
chk("英文取景词同样触发让路",
    "full body visible" not in PR.build(req(style="upper body close-up"),
                                        spec(), KREA)["positive"])

# ══════════════════════════════════════════════════════════════════════
#  4. 翻译档：不许静默吞字
# ══════════════════════════════════════════════════════════════════════
head("4. 英文词表 CLIP：翻不出来的必须点名")
tr = PR.build(req(), spec(), ANIM)
chk("模式标为词典翻译", tr["prompt_mode"] == "词典翻译", tr["prompt_mode"])
chk("翻不出来的词进了 untranslated", len(tr["untranslated"]) >= 3,
    "、".join(tr["untranslated"]))
chk("专有名词被点名（露米艾尔）", "露米艾尔" in tr["untranslated"])
chk("「圣痕」被点名", any("圣痕" in x for x in tr["untranslated"]),
    str(tr["untranslated"]))
chk("中文原文绝不漏进 CLIP 提示词", not CJK.search(tr["positive"]),
    tr["positive"][:120])
chk("notes 给出两条出路（换档案 / 写英文）",
    "Krea 2 / Qwen-Image" in tr["notes"] and "英文标签" in tr["notes"])
chk("附加正向里的中文也被点名", "虹彩鳞粉" in
    PR.build(req(extra_positive="虹彩鳞粉", style="", background=""),
             spec(), ANIM)["untranslated"])
chk("附加正向里的中文原文没进提示词",
    "虹彩鳞粉" not in PR.build(req(extra_positive="虹彩鳞粉", style="",
                                   background=""), spec(), ANIM)["positive"])
chk("翻得出的一部分照常进（龙骑士）", "dragon" in tr["positive"])
chk("翻档时中文负向同样不外泄",
    not CJK.search(PR.build(req(extra_negative="多余的手指"), spec(), ANIM)["negative"]))

# ══════════════════════════════════════════════════════════════════════
#  5. 词典本身：不拆碎英文、虚词与最长匹配仍正确
# ══════════════════════════════════════════════════════════════════════
head("5. 词典：用户的英文短语不许被锯成碎片")
chk("8-bit 不被拆成 8, bit", PR.zh_to_tags("8-bit") == ["8-bit"],
    str(PR.zh_to_tags("8-bit")))
chk("line-art 保持整词", PR.zh_to_tags("line-art") == ["line-art"])
chk("semi-realistic 保持整词", PR.zh_to_tags("semi-realistic") == ["semi-realistic"])
chk("空格仍是标签分隔（frost dragon → 两词）",
    PR.zh_to_tags("frost dragon") == ["frost", "dragon"])
chk("中文逗号仍分隔", PR.zh_to_tags("赛璐璐，逆光")[:1] == ["cel shading"])
chk("「俯视视角」不会因「角」多长出 horns", "horns" not in PR.zh_to_tags("俯视视角"),
    str(PR.zh_to_tags("俯视视角")))
chk("虚词不进提示词", PR.zh_to_tags("的一条") == [], str(PR.zh_to_tags("的一条")))
chk("最长匹配优先（黑曜石鳞片不拆）",
    PR.zh_to_tags("黑曜石鳞片") == PR.ZH_TAGS["黑曜石鳞片"],
    str(PR.zh_to_tags("黑曜石鳞片")))

# ══════════════════════════════════════════════════════════════════════
#  6. 分层出图：两个 pass 各自保真
# ══════════════════════════════════════════════════════════════════════
head("6. 分层出图的保真")
lay = PR.build_layers(req(), spec(), KREA)
chk("背景 pass 含背景原话", lay["background"]["positive"].count(BG) == 1)
chk("分层的主体 pass **不带**背景描述（纯色底才抠得干净）",
    BG not in lay["subject"]["positive"], lay["subject"]["positive"][:80])
chk("主体 pass 含主体原话", SUBJECT in lay["subject"]["positive"])
chk("背景 pass 不带种族/单主体标签", "1monster" not in lay["background"]["positive"])
chk("背景 pass 开头就钉死「没有人的空场景」",
    lay["background"]["positive"].startswith("This is an empty background plate"))
chk("背景 pass 不声明全身构图", "full body visible" not in lay["background"]["positive"])
chk("主体 pass 保留全身+纯色底（抠底必需，即使用户写了取景）",
    "full body" in lay["subject"]["positive"] and "solid grey background"
    in lay["subject"]["positive"], lay["subject"]["positive"][:200])
chk("分层顶层也带 prompt_mode", lay["prompt_mode"] == "原文直送")
chk("分层 untranslated 合并两 pass", lay["untranslated"] == [])
lay_tr = PR.build_layers(req(), spec(), ANIM)
chk("翻译档分层同样点名丢词", len(lay_tr["untranslated"]) >= 3)
chk("翻译档分层没有中文漏进提示词",
    not CJK.search(lay_tr["background"]["positive"] + lay_tr["subject"]["positive"]))
chk("背景留空时回落不报错", "positive" in PR.build_layers(
    req(background=""), spec(), KREA))

# ══════════════════════════════════════════════════════════════════════
#  7. 导出工作流 JSON：节点文本 == 编译结果
# ══════════════════════════════════════════════════════════════════════
head("7. 导出工作流 JSON 与编译结果一致")
from cardforge.art import run as RUN                                          # noqa: E402

tmp = ROOT / "workspace" / ".cache" / "art-workflow-check"
tmp.mkdir(parents=True, exist_ok=True)


def exported_prompts(preset: str, request: ArtRequest) -> tuple[list[str], dict, dict]:
    info: dict = {}
    path = RUN.export_workflow(preset, str(tmp / f"{preset}.json"),
                               profile="auto", spec=spec(), request=request,
                               host="http://127.0.0.1:8188", info=info)
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    texts: list[str] = []

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k == "widgets_values" and isinstance(v, list):
                    texts.extend(s for s in v if isinstance(s, str) and len(s) > 24)
                else:
                    walk(v)
        elif isinstance(x, list):
            for i in x:
                walk(i)

    walk(d)
    return texts, info, d


t0 = time.time()
texts, info, doc = exported_prompts("t2i_single", req())
joined = "\n".join(texts)
chk("导出的节点文本里有用户原话", SUBJECT in joined,
    f"耗时 {time.time() - t0:.1f}s")
chk("导出 info 带回 prompt_mode", info.get("prompt_mode") == "原文直送")
chk("导出 info 的 positive 与节点文本一致",
    info.get("positive", "") in joined)
cf = ((doc.get("extra") or {}).get("cardforge") or {})
chk("导出 JSON 自带 cardforge 元数据块（含提示词口径）",
    bool(cf) and cf.get("prompt_mode") == "原文直送",
    f"keys={sorted(cf.keys())[:8]}")
chk("元数据里的 user_input 与台账同源",
    (cf.get("user_input") or {}).get("subject") == SUBJECT)
cs_texts, cs_info, _ = exported_prompts("character_sheet", req())
cs_joined = "\n".join(cs_texts)
chk("character_sheet 不再把用户主体整段覆盖", SUBJECT in cs_joined,
    cs_joined[:160].replace("\n", " ⏎ "))
chk("character_sheet 的版式指令仍然追加在里面",
    "three views of the same character" in cs_joined)

# ══════════════════════════════════════════════════════════════════════
#  8. 台账：事后能不能复查
# ══════════════════════════════════════════════════════════════════════
head("8. 台账字段（每张图都要能复查提示词怎么来的）")
for k in ("prompt_mode", "untranslated", "user_input", "structure"):
    chk(f"build() 返回 {k}", k in out)
dry = RUN.generate(req(), spec(), host="http://127.0.0.1:8188", dry_run=True)
chk("dry_run 结果 ok", dry.ok, dry.error)
chk("dry_run meta 记 prompt_mode", dry.meta.get("prompt_mode") == "原文直送")
chk("dry_run meta 记 user_input",
    dry.meta.get("user_input", {}).get("subject") == SUBJECT)
chk("dry_run meta 记完整 request（可复现）",
    dry.meta.get("request", {}).get("subject") == SUBJECT)
chk("dry_run meta 的 positive 含原话", SUBJECT in dry.meta.get("positive", ""))
dry_tr = RUN.generate(req(profile="animagine"), spec(),
                      host="http://127.0.0.1:8188", dry_run=True)
chk("翻译档 dry_run 也把丢词记进 meta",
    dry_tr.meta.get("prompt_mode") == "词典翻译"
    and len(dry_tr.meta.get("untranslated") or []) >= 3,
    str(dry_tr.meta.get("untranslated"))[:80])

# ══════════════════════════════════════════════════════════════════════
#  9. 提示词模板：正统母题 + 按档案口径给中/英文版 + 可自存
# ══════════════════════════════════════════════════════════════════════
head("9. 提示词模板")
from cardforge.art import templates as TP                                     # noqa: E402

chk("内置 12 套母题", len(TP.TEMPLATES) == 12, str(len(TP.TEMPLATES)))
chk("每套都有中文版（本机默认档案原话直送）",
    all(t.subject_zh and t.style_zh for t in TP.TEMPLATES))
chk("每套都有英文版（英文词表 CLIP 用）",
    all(t.subject_en and t.style_en for t in TP.TEMPLATES))
chk("中英文语义对应（同一套的主体不跑题）",
    all(len(t.subject_zh) > 10 and len(t.subject_en) > 10 for t in TP.TEMPLATES))
chk("覆盖怪兽与魔陷两组", {"怪兽", "魔陷"} == {t.group for t in TP.TEMPLATES},
    str({t.group for t in TP.TEMPLATES}))
chk("魔法卡与陷阱卡各有一套无人场景",
    {"spell_scene", "trap_scene"} <= set(TP.BY_KEY))
chk("模板只讲一个视点：不出现坐标轴/多面板式措辞",
    not any(("图表" in t.subject_zh or "面板" in t.subject_zh or "对比图" in t.subject_zh)
            for t in TP.TEMPLATES))
_LIGHT_WORDS = ("最亮", "亮处", "光源", "唯一光", "光柱", "高光", "逆光",
                "火光", "电光", "发光", "照亮", "落日", "晨光")
chk("每套都点明唯一光源或最亮处（一张画只留一处最亮）",
    all(any(w in (t.subject_zh + t.style_zh + t.background_zh) for w in _LIGHT_WORDS)
        for t in TP.TEMPLATES),
    str([t.key for t in TP.TEMPLATES
         if not any(w in (t.subject_zh + t.style_zh + t.background_zh)
                    for w in _LIGHT_WORDS)]))
sp = CardSpec(id=210000021, name="圣痕的龙骑士 露米艾尔", frame="fusion",
              race="战士族", attribute="炎", level=8)
ranked = TP.recommend(sp)
chk("推荐按规格排序：战士族·炎·融合 首推持械骑士", ranked[0][0] == "knight", str(ranked[:3]))
chk("魔法卡首推魔法场景", TP.recommend(CardSpec(id=1, name="x", frame="spell"))[0][0]
    == "spell_scene")
chk("分数为 0 的模板也仍在表里（推荐是排序不是删选项）",
    len(ranked) == len(TP.TEMPLATES) + len(TP.load_user()))
zh_form = TP.as_form(TP.BY_KEY["dragon"], bilingual=True)
en_form = TP.as_form(TP.BY_KEY["dragon"], bilingual=False)
chk("bilingual=True 取中文版", zh_form["subject"] == TP.BY_KEY["dragon"].subject_zh)
chk("bilingual=False 取英文版", en_form["subject"] == TP.BY_KEY["dragon"].subject_en)
chk("t2i_layers 模板会带上分层开关", zh_form["layers"] is True
    and TP.as_form(TP.BY_KEY["knight"], bilingual=True)["layers"] is False)
chk("带卡名时拼进主体", "圣痕的龙骑士 露米艾尔" in
    TP.as_form(TP.BY_KEY["knight"], bilingual=True, name="圣痕的龙骑士 露米艾尔")["subject"])
tmp_root = ROOT / "workspace" / ".cache" / "tpl-check"
tmp_root.mkdir(parents=True, exist_ok=True)
a = TP.save_user({"subject": "甲版主体", "style": "甲版风格"}, root=tmp_root,
                 name="圣痕·龙骑士登场")
b = TP.save_user({"subject": "乙版主体"}, root=tmp_root, name="星奏·前哨")
chk("中文名不再被压成同一个 key（历史缺陷：都变成 template 互相覆盖）",
    a["key"] != b["key"], f'{a["key"]} / {b["key"]}')
c = TP.save_user({"subject": "甲版主体改"}, root=tmp_root, name="圣痕·龙骑士登场")
chk("同名同标题是更新而不是新增", c["count"] == 2, str(c["count"]))
chk("自存模板进得了 list_all",
    {a["key"], b["key"]} <= {t.key for t in TP.list_all(tmp_root)})
chk("自存模板 group 是「我的模板」",
    next(t for t in TP.load_user(tmp_root) if t.key == b["key"]).group == "我的模板")
chk("内置模板不能删（delete 只认自存）",
    TP.delete_user("knight", root=tmp_root).get("ok") is False)
chk("自存模板能删", TP.delete_user(b["key"], root=tmp_root).get("ok") is True)
chk("坏文件不炸（返回空表）",
    TP.load_user(ROOT / "workspace" / ".cache" / "definitely-missing-dir") == [])
try:
    import urllib.request, json as _json
    r = _json.loads(urllib.request.urlopen(
        "http://127.0.0.1:8790/api/art/templates?card=210000021", timeout=30).read().decode())
    chk("端点返回 12+ 套", r.get("count", 0) >= 12, str(r.get("count")))
    chk("端点带 bilingual 与语言说明", "bilingual" in r and "language_note" in r)
    chk("端点带推荐顺序", bool(r.get("recommended")))
except Exception as e:                                          # noqa: BLE001
    chk("模板端点可访问", False, f"{type(e).__name__}: {e}")

# ══════════════════════════════════════════════════════════════════════
#  收尾
# ══════════════════════════════════════════════════════════════════════
summary = f"\n{'=' * 72}\nPASS={PASS} FAIL={FAIL}\n{'=' * 72}"
print(summary)
LOG.append(summary)
try:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(LOG), encoding="utf-8")
    print(f"REPORT={OUT}")
except Exception as e:                                            # noqa: BLE001
    print(f"REPORT_WRITE_FAILED={e}")
sys.exit(1 if FAIL else 0)
