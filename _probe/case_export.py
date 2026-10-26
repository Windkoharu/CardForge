# -*- coding: utf-8 -*-
import json, urllib.request
from pathlib import Path
ROOT = Path(r"D:\游戏王DIY设计"); BASE = "http://127.0.0.1:8790"

def post(path, payload):
    r = urllib.request.Request(BASE+path, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST", headers={"Content-Type": "application/json; charset=utf-8",
                                "Origin": BASE, "Referer": BASE+"/"})
    with urllib.request.urlopen(r, timeout=900) as resp:
        return json.loads(resp.read().decode("utf-8"))

print("[1/3] MDPro3 .ypk 打包 …")
res = post("/api/export/mdpro3/build", {"archetype": "圣痕", "name": "圣痕",
                                        "render_pics": True, "langs": "zh_cn"})
print("ok:", res.get("ok"), "path:", res.get("rel"), "size:", res.get("bytes") or res.get("size"))
print("cards:", [c.get("id") if isinstance(c, dict) else c for c in (res.get("cards") or [])][:8])
for i in (res.get("verify") or [])[:8]:
    print(f"  [{i.get('level')}] {i.get('code')}: {i.get('message')}")

print("[2/3] EDOPro 扩展包 …")
eds = post("/api/export/build", {"archetype": "圣痕", "name": "圣痕", "verify": True, "gate5": True})
print("ok:", eds.get("ok"), "pack:", eds.get("pack_dir") or eds.get("rel"))
for i in (eds.get("verify") or [])[:7]:
    print(f"  [{i.get('level')}] {i.get('code')}: {i.get('message')}")
g5 = eds.get("gate5") or eds.get("G5") or {}
if isinstance(g5, dict):
    print("G5:", g5.get("status"), g5.get("summary"))

Path(ROOT/"workspace/out/_case_export.json").write_text(
    json.dumps({"mdpro3": res, "edopro": eds}, ensure_ascii=False, indent=2), encoding="utf-8")
print("[3/3] → workspace/out/_case_export.json")
