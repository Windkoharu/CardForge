# -*- coding: utf-8 -*-
"""实战案例的卡面：选罕贵 → 渲染导出 PNG，并留一张预览图给视频用。"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8790"
CARD = 210000031
RARITY = "ultra"
OUT_PNG = ROOT / "workspace" / "out" / "实战案例_赛拉.png"
OUT_PREVIEW = ROOT / "workspace" / "out" / "_case_face.png"


def req(path: str, payload: dict | None = None, method: str = "GET",
        timeout: int = 600) -> dict:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    r = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json; charset=utf-8",
                 "Origin": BASE, "Referer": BASE + "/"})
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        body = resp.read()
        ctype = resp.headers.get("Content-Type", "")
        if "image" in ctype:
            return {"_bytes": body, "_ctype": ctype}
        return json.loads(body.decode("utf-8"))


def main() -> int:
    view = req(f"/api/cards/{CARD}")
    spec = view["spec"]
    spec.setdefault("render", {})
    spec["render"]["rarity"] = RARITY
    spec["render"]["fullart"] = {**(spec["render"].get("fullart") or {}), "mode": "none"}
    saved = req(f"/api/cards/{CARD}", spec, method="PUT")
    print(f"罕贵设置为 {RARITY} → {saved.get('path')}")

    exp = req("/api/render/export", {"card": CARD, "fmt": "png",
                                     "out_dir": "workspace/out",
                                     "name": "实战案例_赛拉", "use_art": True,
                                     "quality": 95})
    path = (exp.get("files") or {}).get("share") or exp.get("file") or ""
    print("导出结果：", json.dumps({k: v for k, v in exp.items() if k != "files"},
                                   ensure_ascii=False)[:300])
    print("files：", json.dumps(exp.get("files"), ensure_ascii=False))

    p = Path(path)
    if p.suffix.lower() != ".png":
        p = next((ROOT / v for v in (exp.get("files") or {}).values()
                  if str(v).lower().endswith(".png")), p)
    if p.exists() and p.resolve() != OUT_PNG.resolve():
        OUT_PNG.write_bytes(p.read_bytes())
        print(f"→ {OUT_PNG} ({OUT_PNG.stat().st_size // 1024} KB)")
    else:
        print(f"→ 原文件 {p}")

    img = req(f"/api/render/preview?card={CARD}&width=813&use_art=1")
    OUT_PREVIEW.write_bytes(img["_bytes"])
    print(f"→ 预览 {OUT_PREVIEW} ({len(img['_bytes']) // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
