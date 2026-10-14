# -*- coding: utf-8 -*-
"""真跑一次 L2 出图：POST /api/art/generate → 轮询 job → 确认卡图落到资产库。"""
import json
import sys
import time
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
BASE = "http://127.0.0.1:8790"
CID = 210000011


def post(path, **kw):
    url = BASE + path + "?" + urllib.parse.urlencode(kw)
    req = urllib.request.Request(url, data=b"{}", headers={"content-type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=180).read().decode("utf-8"))


def get(path):
    return json.loads(urllib.request.urlopen(BASE + path, timeout=180).read().decode("utf-8"))


r = post("/api/art/generate", card=CID,
         subject=urllib.parse.unquote("%E6%98%9F%E5%A5%8F%E7%9A%84%E8%A7%81%E4%B9%A0%E6%8C%87%E6%8C%A5"),
         steps=12, count=1, width=832, height=1216)
print("提交：", json.dumps(r, ensure_ascii=False)[:200])
jid = r.get("job")
if not jid:
    print("没有 job id，直接返回结果"); print(json.dumps(r, ensure_ascii=False)[:2000]); sys.exit(1)

t0 = time.time()
last = ""
while time.time() - t0 < 420:
    j = get(f"/api/jobs/{jid}").get("job", {})
    st = j.get("status", "?")
    line = f"{st:<10} {str(j.get('progress', ''))[:70]:<70}"
    if line != last:
        print(f"[{time.time()-t0:6.1f}s] {line}")
        last = line
    if st in ("done", "error", "cancelled", "failed"):
        break
    time.sleep(2)

j = get(f"/api/jobs/{jid}").get("job", {})
print("\n最终：", json.dumps(j, ensure_ascii=False)[:600])
lib = get(f"/api/art/library/{CID}")
print("\n资产库：", json.dumps(lib, ensure_ascii=False)[:800])
sys.exit(0 if j.get("status") == "done" else 1)
