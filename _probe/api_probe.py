# -*- coding: utf-8 -*-
"""对运行中的 8790 服务做只读探活：每个 GET 路由 + 静态资源，逐条记录状态码与 error 字段。"""
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8790"
CARD = "210000011"

GETS = [
    "/", "/index.html", "/css/theme.css", "/css/app.css", "/js/app.js", "/js/api.js",
    "/js/state.js", "/js/ui.js", "/js/spec.js", "/js/text.js", "/js/gates.js",
    "/js/art.js", "/js/pack.js", "/js/assistant.js",
    "/api/doctor", "/api/state", "/api/cards", "/api/cards/" + CARD,
    "/api/cards/" + CARD + "/snapshots", "/api/archetypes", "/api/decks",
    "/api/meta", "/api/jobs",
    "/api/gates/G1?card=" + CARD, "/api/gates/G2?card=" + CARD,
    "/api/gates/G3?card=" + CARD + "&duels=1", "/api/gates/G4?card=" + CARD,
    "/api/gates/G5?card=" + CARD, "/api/gates/GX?card=" + CARD,
    "/api/psct/rules", "/api/lua/api",
    "/api/render/capabilities", "/api/render/stages?card=" + CARD,
    "/api/render/preview?card=" + CARD + "&width=480",
    "/api/render/svg?card=" + CARD + "&width=813",
    "/api/art/capabilities", "/api/art/models", "/api/art/workflows",
    "/api/art/library", "/api/art/library/" + CARD, "/api/art/queue",
    "/api/assistant/status", "/api/assistant/personas", "/api/assistant/history",
    "/api/assistant/guide/spec", "/api/knowledge/search?q=HOPT",
    "/api/pool/search?q=" + urllib.parse.quote("黑魔导"),
    "/api/pool/card?id=46986706",
    "/api/pool/dupcheck?name=" + urllib.parse.quote("星奏"),
    "/api/pool/setcode",
    "/api/export/targets", "/api/export/packages", "/api/export/strings",
    "/api/export/verify", "/api/export/mdpro3/detect",
    "/api/files/" + CARD,                       # 不存在的路径，应 404 而非 500
    "/api/nope/does-not-exist",                 # 未注册路由，应 404
]

fails = []
notes = []
for path in GETS:
    url = BASE + path
    try:
        with urllib.request.urlopen(url, timeout=180) as r:
            code, body, ctype = r.status, r.read(), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        code, body, ctype = e.code, e.read(), "error"
    except Exception as e:                                   # noqa: BLE001
        print(f"[ERR ] {path}  {type(e).__name__}: {e}")
        fails.append(path)
        continue

    err = ""
    if "json" in ctype:
        try:
            d = json.loads(body.decode("utf-8", "replace"))
            if isinstance(d, dict) and d.get("error"):
                err = f"{d['error']}: {d.get('message', '')}"
        except Exception as e:                               # noqa: BLE001
            err = f"JSON 解析失败 {e}"
    ok = code in (200, 204, 304)
    tag = "OK  " if ok and not err else ("WARN" if code == 200 else "BAD ")
    size = len(body)
    print(f"[{tag}] {code:>3} {size:>8}B {path}" + (f"   ← {err}" if err else ""))
    if not ok or err:
        # 404/400 是故意测的负例，单独归类
        if path in ("/api/files/" + CARD, "/api/nope/does-not-exist",
                    "/api/gates/GX?card=" + CARD):
            notes.append(f"负例 {path} → {code} {err}")
        else:
            fails.append(f"{path} [{code}] {err}")

print("\n" + "=" * 70)
print(f"探活：{len(GETS)} 条 · 异常 {len(fails)} · 预期负例 {len(notes)}")
for n in notes:
    print("  " + n)
sys.exit(1 if fails else 0)
