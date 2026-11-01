# -*- coding: utf-8 -*-
"""界面路径实测：四个 bug 在真实 HTTP 接口上的修复效果（用完即删临时卡）。"""
import json
import sys
import io
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BASE = "http://127.0.0.1:8790"
TMP_ID = 219999901


def call(method, path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json"},
                                 method=method)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        raw = getattr(e, "read", lambda: b"")()
        return {"ok": False, "error": f"{type(e).__name__}: {e}",
                "body": raw.decode("utf-8", "replace")[:400]}


def spec_with(target, name="青眼白龙测试体"):
    return {"id": TMP_ID, "name": name, "frame": "effect", "attribute": "光",
            "race": "魔法师族", "level": 1, "atk": 0, "dfd": 0,
            "archetype": "星奏", "setcode": "0x1000",
            "effects": [{"kind": "search", "trigger": "NORMAL_SUMMON_SUCCESS",
                         "limit": "hopt_name", "target": target,
                         "cost": {"kind": "none"}, "params": {}}],
            "text_i18n": {"zh_cn": ""}}


print("── ①反解：卡名 vs 字段（界面「从卡文推断」）──")
r = call("POST", "/api/psct/infer", {
    "spec": spec_with({"filter_kind": "any", "count": 1, "controller": "self"}),
    "text": "①：这张卡召唤成功时才能发动。从卡组把1张「星奏的和音」加入手卡。"})
if r.get("ok"):
    t = (r["effects"][0].get("target") or {})
    print("  反解筛选:", t.get("filter_kind"), "=", t.get("filter_value"))
else:
    print("  ✗", r.get("error"), r.get("body"))

print("\n── ②具名检索：保存时自动解析卡号 + 脚本 ──")
r = call("POST", f"/api/cards?new_id=0", spec_with(
    {"filter_kind": "name", "filter_value": "青眼白龙", "count": 1,
     "from_zone": "DECK", "to_zone": "HAND", "controller": "self"}))
if r.get("ok"):
    t = (r["spec"]["effects"][0].get("target") or {})
    print("  解析到的卡号:", t.get("code"), "| 字段码:", t.get("setcode"))
    print("  卡文:", (r.get("texts") or {}).get("zh_cn", "")[:80].replace("\n", " / "))
    print("  脚本过滤:", [l.strip() for l in (r.get("lua") or "").splitlines()
                        if "IsCode" in l or "IsSetCard" in l])
    print("  G1:", [f"{i['level']}:{i['code']}" for i in
                   (call("GET", f"/api/cards/{TMP_ID}?gates=G1").get("gates", {}) or {})
                   .get("G1", {}).get("issues", [])])
else:
    print("  ✗", r.get("error"), r.get("body"))

print("\n── ③「以外的」：卡文语序 + 脚本排除 ──")
r = call("POST", "/api/psct/compose", {"spec": spec_with({
    "filter_kind": "archetype", "filter_value": "星奏", "count": 1,
    "from_zone": "DECK", "to_zone": "HAND", "controller": "self",
    "exclude_self": True}), "langs": "zh_cn"})
txt = ((r.get("langs") or {}).get("zh_cn") or {}).get("text", "")
print("  卡文:", txt.replace("\n", " / "))
r2 = call("POST", "/api/lua/emit", {"spec": spec_with({
    "filter_kind": "archetype", "filter_value": "星奏", "count": 1,
    "from_zone": "DECK", "to_zone": "HAND", "controller": "self",
    "exclude_self": True})})
print("  脚本:", [l.strip() for l in (r2.get("lua") or "").splitlines()
               if "SelectMatchingCard" in l or "IsExistingMatchingCard" in l])

print("\n── ④字段留空：保存后自动补本家字段名与字段码 ──")
r = call("PUT", f"/api/cards/{TMP_ID}", spec_with({
    "filter_kind": "archetype", "filter_value": "", "count": 1,
    "from_zone": "DECK", "to_zone": "HAND", "controller": "self"}))
if r.get("ok"):
    t = (r["spec"]["effects"][0].get("target") or {})
    print("  补齐后:", repr(t.get("filter_value")), "字段码", t.get("setcode"))
    print("  G1:", [f"{i['level']}:{i['code']}" for i in
                   (call("GET", f"/api/cards/{TMP_ID}?gates=G1").get("gates", {}) or {})
                   .get("G1", {}).get("issues", [])])
else:
    print("  ✗", r.get("error"), r.get("body"))

print("\n── 清理临时卡 ──")
print(" ", call("POST", f"/api/cards/{TMP_ID}/delete", {}))
