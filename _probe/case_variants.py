# -*- coding: utf-8 -*-
"""卡文变体对照：只为选定「圣痕的追迹者 赛拉」的最终写法。

每轮都走 /api/psct/compose → /api/psct/lint（与界面同一条路），
不落盘，只打印文本与 ERROR 数，方便挑一版既像官方、又过校验的。
"""
from __future__ import annotations

import copy
import json
import urllib.request
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8790"
CARD = 210000031


def post(path: str, payload: dict) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        BASE + path, data=data, method="POST",
        headers={"Content-Type": "application/json; charset=utf-8",
                 "Origin": BASE, "Referer": BASE + "/"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read().decode("utf-8"))


def base_spec() -> dict:
    p = ROOT / "workspace" / "cards" / "圣痕" / str(CARD) / "spec.json"
    return json.loads(p.read_text(encoding="utf-8"))


def variant(name: str, mutate) -> None:
    spec = copy.deepcopy(base_spec())
    spec.pop("text_i18n", None)
    mutate(spec)
    comp = post("/api/psct/compose", {"spec": spec, "langs": "zh_cn"})
    text = ((comp.get("langs") or {}).get("zh_cn") or {}).get("text", "")
    spec["text_i18n"] = {"zh_cn": text}
    lint = post("/api/psct/lint", {"spec": spec, "langs": "zh_cn"})
    print(f"\n=== {name} ===")
    print(text)
    print(f"--- ERROR {lint.get('errors')} / 共 {lint.get('count')} ---")
    for i in lint.get("issues") or []:
        print(f"  [{i.get('level')}] {i.get('code')}: {i.get('message')}")


def v_monster(spec: dict) -> None:
    for e in spec["effects"]:
        e.setdefault("params", {})["card_type"] = "monster"


def v_monster_select(spec: dict) -> None:
    v_monster(spec)
    spec["effects"][1]["params"]["select"] = True


def v_normal_summon(spec: dict) -> None:
    v_monster(spec)
    spec["effects"][0]["trigger"] = "NORMAL_SUMMON_SUCCESS"


def v_no_exclude(spec: dict) -> None:
    v_monster(spec)
    spec["effects"][1]["target"]["exclude_self"] = False


if __name__ == "__main__":
    variant("A 现状（无 card_type）", lambda s: None)
    variant("B +card_type=monster", v_monster)
    variant("C +card_type +select（② 带「以外」）", v_monster_select)
    variant("D ① 改「召唤成功时」", v_normal_summon)
    variant("E ② 去掉 exclude_self", v_no_exclude)
