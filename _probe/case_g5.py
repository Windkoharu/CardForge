import json, urllib.request
from pathlib import Path
BASE="http://127.0.0.1:8790"
def post(p, d):
    r=urllib.request.Request(BASE+p, data=json.dumps(d,ensure_ascii=False).encode("utf-8"), method="POST",
        headers={"Content-Type":"application/json; charset=utf-8","Origin":BASE,"Referer":BASE+"/"})
    with urllib.request.urlopen(r, timeout=600) as x: return json.loads(x.read().decode("utf-8"))
g5 = post("/api/gates/G5", {"card": 210000031, "pack_dir": "workspace/out/expansions/圣痕"})
rep = g5.get("report") or {}
print("G5:", rep.get("status"), "|", rep.get("summary"), "|", rep.get("took_ms"), "ms")
for i in (rep.get("issues") or [])[:8]:
    print(f"  [{i.get('level')}] {i.get('code')}: {i.get('message')}")
Path(r"D:\游戏王DIY设计\workspace\out\_case_g5.json").write_text(json.dumps(g5, ensure_ascii=False, indent=2), encoding="utf-8")
