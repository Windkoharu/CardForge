# -*- coding: utf-8 -*-
"""真跑一次分层出图：背景 pass + 主体 pass（抠底）→ 检查 alpha → 用主体出框档合成卡面。"""
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
BASE = "http://127.0.0.1:8790"
CID = 210000011
OUT = Path("D:/游戏王DIY设计/_probe/layers")


def post(path, **kw):
    url = BASE + path + "?" + urllib.parse.urlencode(kw)
    req = urllib.request.Request(url, data=b"{}", headers={"content-type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=300).read().decode("utf-8"))


def get(path):
    return json.loads(urllib.request.urlopen(BASE + path, timeout=300).read().decode("utf-8"))


subj = "身穿白金色法袍、手持发光法杖的少年指挥者"
back = "大教堂内部的彩窗与光柱"
r = post("/api/art/generate", card=CID, layers="true", steps=12, count=1,
         subject=urllib.parse.quote(subj), background=urllib.parse.quote(back))
print("提交：", json.dumps(r, ensure_ascii=False)[:160])
jid = r.get("job")
t0 = time.time()
while time.time() - t0 < 600:
    j = get(f"/api/jobs/{jid}").get("job", {})
    st = j.get("status")
    if st in ("done", "error", "cancelled", "failed"):
        break
    time.sleep(3)
res = (j.get("result") or {})
print(f"状态：{st}  用时 {time.time()-t0:.0f}s")
meta = res.get("meta") or {}
print("mode           :", meta.get("mode"))
print("seed 背景/主体  :", meta.get("seed_background"), "/", meta.get("seed_subject"))
print("耗时 背景/主体  :", meta.get("took_background_ms"), "/", meta.get("took_subject_ms"), "ms")
print("alpha 不透明/半透:", meta.get("alpha_opaque"), "/", meta.get("alpha_semi"))
lay = meta.get("layers") or {}
for k, v in lay.items():
    p = Path(str(v))
    print(f"  层 {k:<10} {p.name:<28} {p.stat().st_size if p.exists() else '缺失'}B")
print("saved          :", json.dumps(meta.get("saved") or [], ensure_ascii=False)[:220])
print("\n提示词·背景：", (meta.get("prompt_background") or "")[:200])
print("提示词·主体：", (meta.get("prompt_subject") or "")[:200])
print("\nnotes：")
print((meta.get("notes") or "")[:900])
sys.exit(0 if st == "done" else 1)
