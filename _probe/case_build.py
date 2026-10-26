# -*- coding: utf-8 -*-
"""实战案例的造卡脚本：建卡 → 卡文 → 脚本 → G1/G2/G3，一步一打印。

案例：圣痕的追迹者 赛拉（210000031）· 4 星 光 战士族 1600/1200
  ① 召唤·特殊召唤成功时：从卡组把 1 只「圣痕」怪兽加入手卡
  ② 这张卡被送去墓地的场合：从自己墓地选 1 只「赛拉」以外的「圣痕」怪兽加入手卡

全程走本地服务的 HTTP 接口，和界面点按钮是同一条路 —— 视频里出现的每个字
都能被这份脚本复现。产物落在 workspace/out/_case_build.json。
"""
from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8790"
CARD = 210000031
OUT = ROOT / "workspace" / "out" / "_case_build.json"

SPEC = {
    "id": CARD,
    "name": "圣痕的追迹者 赛拉",
    "frame": "effect",
    "attribute": "光",
    "race": "战士族",
    "level": 4,
    "atk": 1600,
    "dfd": 1200,
    "archetype": "圣痕",
    "setcode": "0x1000",
    "rarity": "common",
    "effects": [
        {
            "kind": "search",
            "trigger": "SUMMON_ANY_SUCCESS",
            "target": {
                "from_zone": "DECK", "to_zone": "HAND", "filter_kind": "archetype",
                "filter_value": "圣痕", "count": 1, "count_max": 0,
                "controller": "self", "exclude_self": False, "face_up": False,
            },
            "cost": {"kind": "none", "count": 1, "filter_kind": "any", "lp": 0},
            "limit": "hopt_name",
            "params": {"n": 1, "card_type": "monster"},
            "source": "manual",
        },
        {
            "kind": "search_grave",
            "trigger": "WHEN_SENT_GRAVE",
            "target": {
                "from_zone": "GRAVE", "to_zone": "HAND", "filter_kind": "archetype",
                "filter_value": "圣痕", "count": 1, "count_max": 0,
                "controller": "self", "exclude_self": True, "face_up": False,
            },
            "cost": {"kind": "none", "count": 1, "filter_kind": "any", "lp": 0},
            "limit": "hopt_name",
            "params": {"n": 1, "card_type": "monster", "select": True},
            "source": "manual",
        },
    ],
}


def call(path: str, payload: dict, *, method: str = "POST", timeout: int = 900) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json; charset=utf-8",
                 "Origin": BASE, "Referer": BASE + "/"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def get(path: str, timeout: int = 300) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> int:
    bundle: dict = {"card": CARD}

    print(f"[1/6] 建卡 {CARD} …")
    saved = call("/api/cards", SPEC)
    bundle["save"] = {"path": saved.get("path"), "id": saved.get("id")}
    print(f"  → {saved.get('path')}")

    print("[2/6] 生成卡文（zh_cn）…")
    comp = call("/api/psct/compose", {"card": CARD, "langs": "zh_cn", "write": 1})
    text = ((comp.get("langs") or {}).get("zh_cn") or {}).get("text", "")
    bundle["text_zh"] = text
    print("  " + text.replace("\n", "\n  "))

    print("[3/6] 生成 Lua 脚本 …")
    em = call("/api/lua/emit", {"card": CARD})
    lua = em.get("lua", "")
    bundle["lua"] = lua
    print(f"  → {len(lua)} 字符")

    print("[4/6] PSCT lint（39 条规则）…")
    lint = call("/api/psct/lint", {"card": CARD, "lang": "zh_cn"})
    issues = lint.get("issues") or []
    bundle["lint"] = {"errors": lint.get("errors", 0), "issues": issues}
    print(f"  → 问题 {len(issues)} 条（ERROR {lint.get('errors', 0)}）")
    for i in issues[:6]:
        print(f"    [{i.get('level')}] {i.get('code')}: {i.get('message')}")

    print("[5/6] 质量门 G1 / G2 / G3 …")
    gates: dict = {}
    for g in ("G1", "G2", "G3"):
        r = call(f"/api/gates/{g}", {"card": CARD, "duels": 1})
        rep = r.get("report") or {}
        gates[g] = rep
        print(f"  {g}: {rep.get('status')} | {rep.get('summary')} "
              f"({rep.get('took_ms')} ms)")
        for i in (rep.get("issues") or [])[:4]:
            print(f"     [{i.get('level')}] {i.get('code')}: {i.get('message')}")
    bundle["gates"] = gates

    print("[6/6] 落盘 bundle …")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  → {OUT}")

    bad = [g for g, r in gates.items() if r.get("status") not in ("pass", "warn", "waived")]
    print("\n结论：" + ("G1–G3 全绿" if not bad else f"未通过：{bad}"))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
