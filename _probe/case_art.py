# -*- coding: utf-8 -*-
"""实战案例的卡图：按卡面规格推荐模板 → 换成自己的话 → 真出图。

与界面「阶段 3 · 卡图」同一条链（``cardforge.art.run.generate``）：
模板只给结构，主体描述里的每一句都是这里写下的原话；出完自动入库并设为当前。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cardforge.core.models import ArtRequest          # noqa: E402
from cardforge.pool import repo                       # noqa: E402
from cardforge.art import run, templates              # noqa: E402

CARD = 210000031
HOST = "http://127.0.0.1:8188"
OUT = ROOT / "workspace" / "out" / "_case_art.json"

# 作者自己写的两句话 —— 视频要证明它们一字不少地进了提示词
MY_SUBJECT = ("右臂与剑身透出细密的发光刻痕（圣痕），光沿着刻痕向外渗，"
              "左肩披风边缘有烧灼般的金色裂纹")
MY_STYLE = "厚涂质感，金属高光只落在剑身与刻痕上"


def main() -> int:
    spec = repo.load_card(CARD, "圣痕")
    recs = templates.recommend(spec)[:6]
    print("模板推荐（分数由卡种/属性/种族确定，不看心情）：")
    for k, s in recs:
        t = templates.get(k)
        print(f"  {s:>2}  {k:<11} {getattr(t, 'zh', '')}")
    top = templates.get(recs[0][0])
    print(f"\n选第 1 名：{top.key} · {top.zh}\n  {top.note}")

    form = templates.as_form(top, bilingual=True, name=spec.name)
    subject = f"{form['subject']}；{MY_SUBJECT}"
    style = f"{form['style']}；{MY_STYLE}"
    ar = ArtRequest(card_id=spec.id, archetype=spec.archetype,
                    subject=subject, style=style, background=form["background"],
                    extra_positive=form["extra_positive"],
                    extra_negative=form["extra_negative"],
                    preset=form["preset"], cutout_bg=form["cutout_bg"],
                    profile="auto", seed=20261027, count=1)

    t0 = time.time()
    last = {"stage": ""}

    def on_progress(info: dict) -> None:
        st = str(info.get("stage") or "")
        if st != last["stage"]:
            last["stage"] = st
            extra = ""
            if st == "wait":
                extra = (f" 队列 {info.get('queue_running')}/{info.get('queue_pending')}"
                         f" 已等 {info.get('elapsed')}s")
            print(f"  [{st}]{extra}")

    print("\n开始出图（本机 ComfyUI）…")
    res = run.generate(ar, spec, on_progress=on_progress, host=HOST)
    took = round(time.time() - t0, 1)
    meta = dict(res.meta or {})
    print(f"ok={res.ok} 用时={took}s error={res.error or '-'}")
    if res.hint:
        print(f"hint={res.hint}")
    for key in ("prompt_mode", "profile", "untranslated", "user_input",
                "prompt_structure", "workflow_nodes", "saved"):
        if key in meta:
            v = meta[key]
            print(f"  {key}: {json.dumps(v, ensure_ascii=False)[:400]}")
    print("images:")
    for p in res.images:
        print("  " + str(p))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "card": CARD, "template": top.key, "template_zh": top.zh,
        "my_subject": MY_SUBJECT, "my_style": MY_STYLE,
        "subject": subject, "style": style,
        "ok": res.ok, "images": [str(p) for p in res.images],
        "meta": meta, "took_s": took, "error": res.error, "hint": res.hint,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n→ {OUT}")
    return 0 if res.ok else 1


if __name__ == "__main__":
    sys.exit(main())
