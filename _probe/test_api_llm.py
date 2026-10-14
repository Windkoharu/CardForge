"""api_llm 的真实 handler 驱动测试（不起服务，直接 handle Request）。"""
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cardforge.server.app import App          # noqa: E402
from cardforge.server import api_llm          # noqa: E402
from cardforge.server.http import Request, error_response   # noqa: E402

app = App()
api_llm.register(app)

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [ok]   {name}" + (f" —— {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {name} —— {detail}")


def call(method, path, **kw):
    body = b""
    headers = {}
    if "json" in kw:
        body = json.dumps(kw.pop("json")).encode()
        headers = {"content-type": "application/json"}
    req = Request(method, path, query=kw.pop("query", {}), body=body, headers=headers)
    try:
        r = app.handle(req)
    except Exception as e:
        # 异常→响应那层在 socket 循环里；直驱 handler 时自己补上
        r = error_response(e)
    try:
        data = json.loads(r.body.decode("utf-8"))
        if not isinstance(data, dict):
            data = {"value": data}
    except Exception:
        data = {}
    return r.status, data


# 清场：确保从空配置开始
cfg_file = ROOT / "workspace" / "config" / "llm.json"
if cfg_file.exists():
    cfg_file.unlink()

print("── 1. GET /api/llm（空配置）")
r = call("GET", "/api/llm")
d = r[1]
check("GET 200", r[0] == 200, str(r[0]))
check("空配置 active 为空", d.get("active") == "", str(d.get("active")))
check("预设 8 个", len(d.get("presets") or []) == 8, str(len(d.get("presets") or [])))
check("detected 给出 auto 结论", "detected" in d, json.dumps(d.get("detected"), ensure_ascii=False))

print("── 2. POST preset lmstudio（本地，免 Key）")
r = call("POST", "/api/llm", json={"action": "preset", "preset": "lmstudio"})
d = r[1]
check("保存并激活", d.get("active") == "lmstudio", str(d.get("active")))
row = next((p for p in d.get("providers") or [] if p["name"] == "lmstudio"), {})
check("列表出现且打码字段在", row.get("name") == "lmstudio" and "masked_key" in row,
      json.dumps(row, ensure_ascii=False))
check("本地端点 online 判定存在", row.get("online") in (True, False), str(row.get("online")))

print("── 3. POST set 自定义（云端，空 Key 应警告）")
r = call("POST", "/api/llm", json={"action": "upsert", "name": "ds",
                                   "base_url": "https://api.deepseek.com/v1",
                                   "model": "deepseek-chat", "set_active": False})
d = r[1]
check("云端空 Key 有警告", bool(d.get("warn")), d.get("warn", "")[:40])
check("active 未被抢走（set_active=false）", d.get("active") == "lmstudio", str(d.get("active")))

print("── 4. POST set 补 Key（空串不清旧 —— 先设再改模型）")
call("POST", "/api/llm", json={"action": "upsert", "name": "ds",
                               "base_url": "https://api.deepseek.com/v1",
                               "api_key": "sk-test1234567890abcd"})
r = call("POST", "/api/llm", json={"action": "upsert", "name": "ds",
                                   "model": "deepseek-reasoner"})
d = r[1]
row = next((p for p in d.get("providers") or [] if p["name"] == "ds"), {})
check("空 api_key 保持旧 Key", row.get("has_key") is True, json.dumps(row, ensure_ascii=False))
check("模型已更新", row.get("model") == "deepseek-reasoner", str(row.get("model")))
check("Key 是打码的", "sk-…" in (row.get("masked_key") or ""), row.get("masked_key", ""))

print("── 5. POST use / off / rm")
r = call("POST", "/api/llm", json={"action": "use", "name": "ds"})
check("use 切到 ds", (r[1] or {}).get("active") == "ds")
r = call("POST", "/api/llm", json={"action": "off"})
check("off 清空 active", (r[1] or {}).get("active") == "")
r = call("POST", "/api/llm", json={"action": "use", "name": "不存在"})
check("use 不存在 → 4xx 且不炸", r[0] >= 400, str(r[0]))
r = call("POST", "/api/llm", json={"action": "rm", "name": "ds"})
check("rm 删除", all(p["name"] != "ds" for p in (r[1] or {}).get("providers") or []))

print("── 6. POST /api/llm/test（保存前试连，不起服务 → 诚实报不在线）")
r = call("POST", "/api/llm/test", json={"base_url": "http://127.0.0.1:1234/v1"})
d = r[1]
check("死端点 ok=False", d.get("ok") is False, json.dumps(d, ensure_ascii=False)[:120])
check("死端点说人话（不在线）", "不在线" in str(d.get("error", "")), str(d.get("error"))[:80])

print("── 7. 跨进程失效：CLI 改配置 → 服务器 detect 立刻跟上")
from cardforge.assistant import providers  # noqa: E402
# 观测点选 prefer="config"：它的降级 reason 会说出「尚未配置」还是
# 「已配置的死端点」—— auto 链死配置时最终 reason 恒为「未探测到」，
# 分不出缓存到底刷没刷。config 通路的 reason 能分。
providers.reset_probe_cache()
p1 = providers.detect_provider("config")
info1 = providers.provider_info()
env = dict(__import__("os").environ, PYTHONIOENCODING="utf-8")
subprocess.run([sys.executable, "-m", "cardforge", "llm", "use", "lmstudio"],
               cwd=str(ROOT), env=env, capture_output=True, timeout=60)
p2 = providers.detect_provider("config")
info2 = providers.provider_info()
check("CLI use 前：config 通路报「尚未配置/不在线」之一",
      "尚未配置" in str(info1.get("detail", {})) or "不在线" in str(info1.get("detail", {})),
      str(info1.get("detail"))[:80])
check("CLI use 后：同进程 detect 立刻看到新 active（lmstudio 死 → 不在线）",
      "lmstudio" in str(info2.get("detail", {})) and "不在线" in str(info2.get("detail", {})),
      str(info2.get("detail"))[:100])

# 收场：清空配置，恢复首启干净状态
if cfg_file.exists():
    cfg_file.unlink()
print(f"\nPASS={PASS} FAIL={FAIL}")
sys.exit(1 if FAIL else 0)
