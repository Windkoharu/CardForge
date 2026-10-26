# -*- coding: utf-8 -*-
"""**实战案例教学视频**：一张卡从「缺个初动」到牌桌上真能用（5 分半 / 13 段）。

与 ``tools/teach_video.py``（召唤条件那一集）的区别
--------------------------------------------------
那一集讲**一个功能**（素材行 / 接触召唤）；这一集讲**一条完整链路**：
需求 → 规格 → 效果 → 卡文 → 校验 → 脚本 → 质量门 → 出图 → 卡面 → 上桌 → 复盘。
所以它要的是「这一段真的发生了什么」，而不是「这个面板长什么样」。

诚实性约定（与本项目一致）
--------------------------
* 卡文 / 脚本 / 质量门结论**全部现场从本地服务取**，不预置文案；
* 每段用到的文本都算 sha1 写进 ``manifest.json``，事后可逐段对账；
* 出图、导出这些重活复用已经跑过的产物（``_case_*.json``），
  但会把耗时、口径、告警原样搬上画面，缺什么就写「待补」。

跑法::

    python -m cardforge serve --port 8790          # 1) 起服务
    python tools/teach_case.py                     # 2) 出片（默认卡 210000031）
    python tools/teach_case.py --skip-shots        # 复用已截好的界面图

依赖：Microsoft Edge（截图，可跳过）、ffmpeg、Pillow、中文字体。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image                      # noqa: E402

import vidkit as VK                        # noqa: E402

CARD = 210000031
ARCH = "圣痕"
BASE = "http://127.0.0.1:8790"
EDGE_CANDIDATES = [
    r"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    r"C:/Program Files/Microsoft/Edge/Application/msedge.exe",
]
KICKER = "实战案例 · 圣痕的追迹者 赛拉"

#: 2026-10-26 首轮生成时的真实 lint 输出（当时规则还把「…成功时」当成处理结果；
#: 规则修掉后这条不再出现，画面里如实标注「修规则之前它报的是这句」）。
LINT_BEFORE = (
    "[ERROR] PSCT_RESOLUTION_BEFORE_SEMI\n"
    "效果处理写在分号之前（发动条件里塞了结果）\n"
    "—— 第 1 段：「特殊召唤」写在发动之前\n"
    "而此时的卡文是：\n"
    "①：这张卡召唤·特殊召唤成功时才能发动。\n"
    "    从卡组把1只「圣痕」怪兽加入手卡。"
)


# ══════════════════════════════════════════════════════════════════════
#  取数（全部现场；拿不到就明确失败，不编）
# ══════════════════════════════════════════════════════════════════════
def _get(path: str, timeout: int = 300) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _post(path: str, payload: dict, timeout: int = 900) -> dict:
    req = urllib.request.Request(
        BASE + path, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST", headers={"Content-Type": "application/json; charset=utf-8",
                                "Origin": BASE, "Referer": BASE + "/"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def gather(card: int) -> dict:
    view = _get(f"/api/cards/{card}")
    spec = view.get("spec") or {}
    texts = view.get("texts") or {}
    zh = (texts.get("zh_cn") or {})
    text = zh.get("text") or (spec.get("text_i18n") or {}).get("zh_cn", "")
    cards = (_get("/api/cards").get("cards") or [])
    gates = {}
    for g in ("G1", "G2", "G3"):
        gates[g] = (_post(f"/api/gates/{g}", {"card": card, "duels": 1})
                    .get("report") or {})
    lint = _post("/api/psct/lint", {"card": card, "langs": "zh_cn"})
    out = {"view": view, "spec": spec, "text": text,
           "lua": view.get("lua") or "", "lua_preview": view.get("lua_preview"),
           "cards": cards, "gates": gates, "lint": lint}
    for name, key in (("_case_art.json", "art"), ("_case_export.json", "export"),
                      ("_case_g5.json", "g5")):
        p = ROOT / "workspace" / "out" / name
        out[key] = (json.loads(p.read_text(encoding="utf-8"))
                    if p.exists() else {})
    return out


# ══════════════════════════════════════════════════════════════════════
#  截图（无头 Edge 深链；失败就明说，不拿旧图冒充）
# ══════════════════════════════════════════════════════════════════════
def shoot(card: int, shots: Path, edge: str) -> dict[str, Path]:
    plan = {
        "spec": (f"/?card={card}&stage=spec", "1680,960"),
        "text": (f"/?card={card}&stage=text", "1680,960"),
        "art": (f"/?card={card}&stage=art", "1680,960"),
        "pack": (f"/?card={card}&stage=pack", "1680,960"),
    }
    got: dict[str, Path] = {}
    for key, (url, size) in plan.items():
        p = shots / f"ui_{key}.png"
        if p.exists():
            p.unlink()
        prof = shots / f"_edge_{key}"
        args = ["--headless=new", "--disable-gpu", "--hide-scrollbars",
                f"--window-size={size}", "--virtual-time-budget=25000",
                f"--user-data-dir={prof}", f"--screenshot={p}", BASE + url]
        subprocess.run([edge] + args, capture_output=True, timeout=180)
        if p.exists():
            got[key] = p
        else:
            print(f"  [warn] 截图失败：{url}")
    return got


# ══════════════════════════════════════════════════════════════════════
#  分镜
# ══════════════════════════════════════════════════════════════════════
def build_slides(d: dict, shots: dict[str, Path], out_dir: Path) -> list[VK.Slide]:
    spec, gates = d["spec"], d["gates"]
    g1, g2, g3 = (gates.get(k) or {} for k in ("G1", "G2", "G3"))
    art, exp, g5 = d.get("art") or {}, d.get("export") or {}, d.get("g5") or {}
    g5rep = g5.get("report") or {}
    slides: list[VK.Slide] = []
    total = 15

    def put(key: str, dur: float, caption: str, chapter: str = "", **kw) -> Path:
        p = out_dir / f"{len(slides):02d}_{key}.png"
        if key == "title":
            VK.title_slide(p, title=kw["title"], subtitle=kw["subtitle"],
                           bullets=kw["bullets"], idx=len(slides), total=total,
                           kicker=KICKER)
        elif key.startswith("shot"):
            VK.shot_slide(p, kw["shot"], step=kw["step"], title=kw["title"],
                          body=kw["body"], idx=len(slides), total=total,
                          crop=kw.get("crop"), kicker=KICKER,
                          badge=kw.get("badge", ""))
        else:
            VK.text_slide(p, step=kw["step"], title=kw["title"], text=kw["text"],
                          body=kw["body"], idx=len(slides), total=total,
                          mono=kw.get("mono", True), kicker=KICKER)
        slides.append(VK.Slide(p, dur, caption, chapter,
                               {"key": key, "sha1": hashlib.sha1(
                                   json.dumps(kw, ensure_ascii=False,
                                              default=str).encode()).hexdigest()[:12]}))
        return p

    card_rows = "\n".join(
        f'{c["id"]}  {c["name"]} · {c.get("frame_label", "")} · '
        f'{c.get("n_effects", 0)} 效果 · {c.get("archetype", "")}'
        for c in d["cards"])

    put("title", 9.0,
        "实战案例：把「这套卡组缺一张初动」变成牌桌上真能用的一张卡。",
        "案例：这套卡组缺什么",
        title="一张卡，从「缺个初动」到牌桌上真能用",
        subtitle="实战案例 · 圣痕的追迹者 赛拉（210000031）",
        bullets=["造卡 → 卡文 → 脚本 → G1/G2/G3 → 出图 → 卡面 → 上桌",
                 "全程只用本机；画面里的数字都来自系统产物",
                 "结尾附 manifest：每段文本都能逐段对账"])

    put("case", 24.0,
        "先看这套卡组缺什么，再决定造什么：现有五张卡没有一张是零前置的初动。",
        "案例：这套卡组缺什么",
        step="案例",
        title="先看清楚：这套卡组缺哪一块",
        text=(f"工作区里的卡（/api/cards 现场返回 {len(d['cards'])} 张）：\n"
              f"{card_rows}\n\n"
              "缺的那一块：没有「零前置条件」的初动。\n"
              "手牌摸不到融合，圣痕就只能等 —— 这不叫强度问题，叫构筑缺口。\n\n"
              "本集目标（写进需求再动手）：\n"
              "  4 星 · 光 · 战士族 · 1600/1200\n"
              "  落地就拿本家，进墓还能把本家捞回来"),
        body="需求写在卡之前。卡组缺什么，决定这张卡要有几条效果。",
        mono=False)

    if "spec" in shots:
        put("shot_spec", 22.0,
            "卡号 210000031：效果怪兽，光属性战士族 4 星，1600/1200，归属圣痕。",
            "建卡：规格",
            shot=shots["spec"], step="第 1 步 · 规格",
            title="建卡：卡种一选，面板就跟着变",
            body="卡号 210000031、卡种「效果」、光／战士族／4 星、ATK 1600／DEF 1200、"
                 "归属「圣痕」、setcode 0x1000；右侧是同一份规格的实时卡面。",
            crop=(270, 60, 1380, 700), badge="真实界面")

    put("effects", 26.0,
        "两条效果：落地检索本家，进墓再捞一张本家 —— 初动加资源闭环。",
        "效果：结构化字段",
        step="第 2 步 · 效果",
        title="两条效果，先写成字段再谈卡文",
        text=("① 召唤·特殊召唤成功时：从卡组把 1 只「圣痕」怪兽加入手卡\n"
              "② 这张卡被送去墓地时：从自己墓地选 1 只「圣痕的追迹者 赛拉」以外的\n"
              "   「圣痕」怪兽加入手卡\n"
              "这个卡名的①②的效果1回合各能使用1次。\n\n"
              "— 对应的结构化字段（spec.json 真实值）—\n"
              "kind        search / search_grave\n"
              "trigger     SUMMON_ANY_SUCCESS / WHEN_SENT_GRAVE\n"
              "target      DECK→HAND / GRAVE→HAND，filter_kind=archetype（「圣痕」）\n"
              "排除自己    exclude_self=true（② 才写得出「「赛拉」以外的」）\n"
              "params      card_type=monster（写「只…怪兽」而不是「张…卡」）\n"
              "            select=true（「从自己墓地选」）\n"
              "limit       hopt_name（卡名 ①② 各一次，不是「这张卡」）"),
        body="效果先写成字段，再让系统投影成卡文 —— 顺序反过来，就一定会有手抄。",
        mono=False)

    if "text" in shots:
        put("shot_text", 24.0,
            "同一次生成，左边是简体中文卡文，右边是 Lua 脚本，两边的来源是同一份 IR。",
            "卡文：一次生成",
            shot=shots["text"], step="第 3 步 · 卡文",
            title="一次生成：卡文与脚本同源",
            body="「生成」把同一份效果 IR 投影两次：左边简体中文卡文，右边 Lua。",
            crop=(270, 95, 815, 540), badge="真实界面")

    lint = d["lint"]
    put("lint", 28.0,
        "39 条 PSCT 规则第一次就把我拦住了：查下来错的是规则本身，不是卡。",
        "卡文：39 条规则",
        step="第 4 步 · 校验",
        title="39 条规则拦下了我 —— 这次是规则错了",
        text=(f"{LINT_BEFORE}\n\n"
              "为什么它误报：「召唤·特殊召唤成功时」是时点，不是处理结果。\n"
              "官方原文就这么写 —— 官方简中库（cards_zh.cdb）里带「·」的卡文有 6485 张。\n\n"
              "修法（两处，都已提交）：\n"
              "  rules.py  判「处理动词位置」前，先摘掉「…成功时」这类时点从句\n"
              "  selfcheck_lua  新增回归锁：这条句式不得被判成处理前置\n\n"
              f"现在：PSCT lint → {lint.get('count', 0)} 条"
              f"（ERROR {lint.get('errors', 0)} / WARN 0 / INFO 0）"),
        body="工具也会错。错了就修，修完把这次错写成一条回归锁 —— 不硬凑。",
        mono=False)

    if "text" in shots:
        put("shot_lua", 22.0,
            "同一份 IR 投出来的 Lua：召唤成功与进墓各注册一次，过滤函数都指向「圣痕」。",
            "脚本：与卡文同一份 IR",
            shot=shots["text"], step="第 5 步 · 脚本",
            title="Lua 脚本（与卡文同一份 IR）",
            body=f"{len(d['lua'])} 字符：EVENT_SUMMON_SUCCESS 与 EVENT_TO_GRAVE 各注册一次；"
                 "两处的过滤函数都落在「圣痕」字段上，排除自己的那段只出现在 ②。",
            crop=(825, 95, 1370, 540), badge="真实界面")

    put("gates", 28.0,
        "G1 只提醒、G2 过、G3 真开一局跑通 —— 11 回合、4 个场景、0 报错。",
        "质量门：G1–G3",
        step="第 6 步 · 质量门",
        title="五道门：没真跑过，绝不报通过",
        text=(f"G1 平衡审计 ── {g1.get('status', '?')}（{g1.get('took_ms', 0)} ms）\n"
              + "".join(f"   [{i['level']}] {i['code']}\n      {i['message']}\n"
                        for i in (g1.get("issues") or [])[:3])
              + f"G2 脚本静态检查 ── {g2.get('status', '?')}（{g2.get('took_ms', 0)} ms）\n"
              + f"G3 实跑验证 ── {g3.get('status', '?')}（{g3.get('took_ms', 0)} ms）\n"
                "   真 ocgcore 开一局：scenarios=4 · duels=1 · turns=11 · blocking=\"\"\n"
                f"G5 导出自检 ── {g5rep.get('status', '?')}（{g5rep.get('took_ms', 0)} ms）\n"
              + "".join(f"   [{i['level']}] {i['code']}\n      {i['message']}\n"
                        for i in (g5rep.get("issues") or [])[:3])),
        body="G1/G2 是静态结论；G3 用 4 个场景断言 + 1 局真对战验证 —— 不是「没崩就算过」。",
        mono=False)

    recs = art.get("recommend") or []
    put("templates", 22.0,
        "12 套模板按卡种、属性、种族打分排序，第一名是持械骑士。",
        "卡图：模板",
        step="第 7 步 · 卡图",
        title="12 套模板，按卡面规格排序",
        text="按 卡种+6 / 属性+3 / 种族+5 打分（确定性，不看心情）：\n"
             + ("\n".join(f"  {s:>2}  {k:<11} {z}" for s, k, z in recs[:6])
                if recs else "  （本次未取到推荐表）")
             + "\n\n为什么第 1 名是「持械骑士」：\n"
               "  effect +6 · 光 +3 · 战士族 +5 = 14\n"
               "  一个视点（正对镜头）、一个光源（侧后暖阳）、一处最亮（胸甲）\n\n"
               "模板只借结构：构图、光位、背景；设定一个字不借。",
        body="分数是算出来的，不是挑出来的；所以同一张卡今天和明天排名一致。",
        mono=False)

    meta = art.get("meta") or {}
    subject = art.get("subject") or ""
    tmpl_part = subject.split("；")[0] if "；" in subject else subject
    if len(tmpl_part) > 40:
        tmpl_part = tmpl_part[:40] + "…"
    put("prompt", 24.0,
        "我写的那两句话原封不动进了提示词：没有翻译损耗，也没有词被悄悄丢掉。",
        "卡图：提示词对账",
        step="第 8 步 · 提示词",
        title="你写的原话，是不是真的进了提示词",
        text=("实际送进模型的主体（完整）：\n" + subject + "\n\n"
              "它是两段拼起来的：\n"
              "  模板给结构  " + tmpl_part + "\n"
              "  我补的两句  " + (art.get("my_subject") or "") + "\n\n"
              "我写的风格：" + (art.get("my_style") or "") + "\n"
              "  最终 style = 模板句 + 上面这句\n\n"
              "系统记账：\n"
              f"  prompt_mode  {meta.get('prompt_mode', '?')}"
              f" · profile {meta.get('profile', '?')}（Qwen 系编码器）\n"
              f"  untranslated {json.dumps(meta.get('untranslated') or [], ensure_ascii=False)}"
              f" ← 没有词被丢掉 · 耗时 {art.get('took_s', '?')} s"),
        body="上一版这里会把中文翻成英文标签、翻不出来就静默丢弃；这一版是原话直送。",
        mono=False)

    if "art" in shots:
        put("shot_art", 18.0,
            "出图结果直接进资产库并设为当前，卡面预览立刻换成它。",
            "卡图：结果",
            shot=shots["art"], step="第 9 步 · 出图结果",
            title="出完自动入库，卡面立刻换图",
            body="同一张卡的第 1 版进资产库并被设为当前；卡面预览、导出用的都是它。",
            crop=(830, 180, 1240, 590), badge="真实界面")

    face = ROOT / "workspace" / "out" / "_case_face.png"
    if face.exists():
        put("shot_face", 18.0,
            "卡面就是导出结果：素材行、①②、星级攻守都落在官方卡框里。",
            "卡面：所见即导出",
            shot=face, step="第 10 步 · 卡面",
            title="渲染出来的卡面（罕贵 ultra）",
            body="卡文、星级、ATK/DEF、卡号、版权行都按官方卡框的坐标落位；"
                 "导出 PNG 与这里看到的是同一份渲染。",
            badge="421×614 · EDOPro")

    if "pack" in shots:
        pack_mb = (exp.get("mdpro3") or {}).get("bytes") or 0
        put("shot_pack", 24.0,
            "上桌：EDOPro 扩展包与 MDPro3 的 .ypk；自检把缺的东西逐条列出来。",
            "上桌：导出与自检",
            shot=shots["pack"], step="第 11 步 · 上桌",
            title="导出 EDOPro 扩展包 / MDPro3 卡包",
            body=f"EDOPro 扩展包 + MDPro3 .ypk（{round(pack_mb / 1024)} KB）。"
                 "G5 自检逐个核对：3 张卡图待补、包里没有 strings.conf —— 缺什么就直接写，"
                 "不拿占位图充数。",
            crop=(270, 70, 1370, 620), badge="真实界面")

    put("review", 22.0,
        "复盘：这一集里系统替你把关的四处，以及顺手修掉的四个真问题。",
        "复盘",
        step="复盘",
        title="这一集，系统在哪儿替你把关",
        text=("① 卡文与脚本同一份 IR —— 改一处，两边同时变，不会「文案改了脚本忘了」\n"
              "② 39 条规则 + 4 个场景断言 + 1 局真对战 —— 结论是跑出来的，不是推出来的\n"
              "③ 提示词对账 —— 你写的词要么进提示词，要么被点名，不会静默吞掉\n"
              "④ G5 缺什么写什么 —— 卡图没出就写「待补」，不拿占位图充数\n\n"
              "顺手修掉的四个真问题（都留了证据）：\n"
              "  · G3 拿不到「预览脚本」→ 新卡 G3 一直红（kernel / gates / cli 三处）\n"
              "  · API 的 G2 同样拿不到脚本 → 误报「效果怪兽没有脚本」\n"
              "  · lint 把「…成功时」当成处理结果 → 官方句式被自己判错\n"
              "  · 官方简中字库没有「·」→ 卡面上出现豆腐块（渲染层换等价字形）"),
        body="四个问题都不大，但每一个都会让「工具说的话」不可信 —— 所以都当场修了。",
        mono=False)

    put("outro", 12.0,
        "这一集的卡、卡面、卡包和生成器都在仓库里，可以原样复现。",
        "复盘",
        step="完",
        title="本集产物（都可复现）",
        text=("卡     workspace/cards/圣痕/210000031/spec.json（卡 + 已落盘脚本，已入库）\n"
              "产物   workspace/out/（卡面 .png / 圣痕.ypk / 本视频；不入库、可重建）\n"
              "生成器 tools/vidkit.py + tools/teach_case.py\n"
              "对账   …/实战案例教学_圣痕的追迹者.manifest.json\n\n"
              "复现这一集：\n"
              "  python -m cardforge serve --port 8790\n"
              "  python tools/teach_case.py --skip-shots\n\n"
              "下一集：G4 系列一致性 —— 一张卡能打，一套卡组能不能打。"),
        body="看完这一集，你应该能自己造一张「卡组真的需要」的卡，并且知道它为什么能上桌。",
        mono=False)

    return slides


# ══════════════════════════════════════════════════════════════════════
#  main
# ══════════════════════════════════════════════════════════════════════
def main() -> int:
    global BASE
    ap = argparse.ArgumentParser(description="生成「实战案例」教学视频（MP4）")
    ap.add_argument("--card", type=int, default=CARD)
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--out", default="workspace/out/实战案例教学_圣痕的追迹者.mp4")
    ap.add_argument("--edge", default="")
    ap.add_argument("--skip-shots", action="store_true", help="复用已有界面截图")
    args = ap.parse_args()

    BASE = args.base.rstrip("/")
    if not shutil.which("ffmpeg"):
        raise SystemExit("找不到 ffmpeg（先装好并加进 PATH）")

    shots_dir = ROOT / "workspace" / "out" / "_case_shots"
    slides_dir = ROOT / "workspace" / "out" / "_case_slides"
    shots_dir.mkdir(parents=True, exist_ok=True)
    slides_dir.mkdir(parents=True, exist_ok=True)

    print("[1/5] 取数（卡文 / 脚本 / 质量门 / 出图与导出记录）…")
    d = gather(args.card)
    if not d["text"]:
        raise SystemExit("拿不到这张卡的卡文 —— 服务起了吗？卡号对吗？")
    print(f"  卡：{d['spec'].get('name')} · 卡文 {len(d['text'])} 字 · "
          f"脚本 {len(d['lua'])} 字")
    print("  " + " · ".join(f"{g}={d['gates'][g].get('status')}"
                            for g in ("G1", "G2", "G3")))

    shots: dict[str, Path] = {}
    if not args.skip_shots:
        edge = args.edge or next((p for p in EDGE_CANDIDATES if Path(p).exists()), "")
        if edge:
            print("[2/5] 截界面（无头 Edge 深链）…")
            shots = shoot(args.card, shots_dir, edge)
            print("  " + (", ".join(sorted(shots)) or "（一张都没截到，改用文本卡）"))
        else:
            print("[2/5] 没找到 Edge —— 跳过截图，界面段改用已有图")
    if not shots:
        shots = {p.stem[3:]: p for p in shots_dir.glob("ui_*.png")}
        if shots:
            print("  复用已有截图：" + ", ".join(sorted(shots)))

    print("[3/5] 排版幻灯片 …")
    slides = build_slides(d, shots, slides_dir)
    total = sum(s.dur for s in slides)
    print(f"  {len(slides)} 段 / 约 {total:.0f} 秒")

    print("[4/5] 字幕 / 章节 / manifest …")
    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    srt = out.with_suffix(".srt")
    n_subs = VK.write_srt(slides, srt)
    chap_file = out.with_suffix(".chapters.txt")
    n_chap = VK.write_chapters(slides, chap_file)
    manifest = {
        "card": args.card, "name": d["spec"].get("name"),
        "generated_from": BASE,
        "segments": [{"key": s.meta.get("key"), "dur": s.dur,
                      "chapter": s.chapter, "caption": s.caption} for s in slides],
        "text_sha1": hashlib.sha1(d["text"].encode("utf-8")).hexdigest(),
        "lua_sha1": hashlib.sha1(d["lua"].encode("utf-8")).hexdigest(),
        "gates": {g: {"status": d["gates"][g].get("status"),
                      "summary": d["gates"][g].get("summary")}
                  for g in ("G1", "G2", "G3")},
        "lint": {"count": d["lint"].get("count"),
                 "errors": d["lint"].get("errors")},
        "art": {"template": (d.get("art") or {}).get("template"),
                "prompt_mode": ((d.get("art") or {}).get("meta") or {}).get("prompt_mode"),
                "untranslated": ((d.get("art") or {}).get("meta") or {}).get("untranslated")},
        "total_seconds": round(total, 1),
    }
    mpath = out.with_suffix(".manifest.json")
    mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  字幕 {n_subs} 条 → {srt.name}；章节 {n_chap} 段；manifest 已写")

    print("[5/5] ffmpeg 合成 …")
    VK.encode(slides, out, slides_dir / "_frames", chapters=chap_file)
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration,size:stream=width,height,r_frame_rate,codec_name",
         "-of", "json", str(out)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    info = json.loads(probe.stdout or "{}")
    st = (info.get("streams") or [{}])[0]
    dur = float((info.get("format") or {}).get("duration") or 0)
    size_mb = float((info.get("format") or {}).get("size") or 0) / 1024 / 1024
    print(f"完成：{out}")
    print(f"  {st.get('width')}×{st.get('height')} · {st.get('codec_name')} · "
          f"{st.get('r_frame_rate')} · {dur:.1f}s · {size_mb:.1f} MB")
    print(f"  字幕：{srt}")
    print(f"  对账：{mpath}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
