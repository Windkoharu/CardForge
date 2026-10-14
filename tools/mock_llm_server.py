"""一次性模拟 OpenAI 兼容端点（LM Studio 行为）：GET /v1/models → 200，GET /v1 → 404。

``--draft`` 模式：chat/completions 返回一份**故意漏了 HOPT** 的 PSCT 草稿 ——
给「AI 起草」链路做端到端验收用（内核校验器应当抓出 PSCT_HOPT_MISSING）。
默认模式不变：任何请求都回「模拟模型应答」（api_llm 的试连断言依赖它）。
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 1234
MODEL = sys.argv[2] if len(sys.argv) > 2 else "mock-qwen-7b"
DRAFT_MODE = "--draft" in sys.argv[2:]
# 故意漏「1回合1次」—— 检索类效果没有回合限制，内核必须报 PSCT_HOPT_MISSING
DRAFT_TEXT = ("①：这张卡召唤成功的场合才能发动。从卡组把1只怪兽加入手卡。")
REPLY = DRAFT_TEXT if DRAFT_MODE else "模拟模型应答"


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.endswith("/models"):
            self._json(200, {"object": "list",
                             "data": [{"id": MODEL, "object": "model"}]})
        else:
            self._json(404, {"error": "Not Found"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(n)
        if self.path.endswith("/chat/completions"):
            self._json(200, {"id": "chatcmpl-mock", "object": "chat.completion",
                             "choices": [{"index": 0, "message": {
                                 "role": "assistant",
                                 "content": REPLY}, "finish_reason": "stop"}],
                             "usage": {"total_tokens": 3}})
        else:
            self._json(404, {"error": "Not Found"})


HTTPServer(("127.0.0.1", PORT), H).serve_forever()
