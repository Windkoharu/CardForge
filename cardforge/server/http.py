"""HTTP 层工具 —— 零依赖（只用标准库）的请求/响应封装。

本项目**不引入任何 Web 框架**：``http.server`` 足够，且能保证
「只有 Python 3.10+ 就能跑」这条 L0 底线不被破坏。
"""
from __future__ import annotations

import json
import mimetypes
import re
import traceback
import urllib.parse
from typing import Any, Callable, Optional
from pathlib import Path

from ..core import console, errors, paths

__all__ = ["Response", "Request", "json_response", "error_response",
           "read_body", "safe_join", "MIME", "status_to_reason"]

mimetypes.init()

MIME: dict[str, str] = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".txt": "text/plain; charset=utf-8",
    ".lua": "text/plain; charset=utf-8",
    ".map": "application/json; charset=utf-8",
}

_STATUS_REASONS = {
    200: "OK", 201: "Created", 202: "Accepted", 204: "No Content",
    301: "Moved Permanently", 302: "Found", 304: "Not Modified",
    400: "Bad Request", 401: "Unauthorized", 403: "Forbidden",
    404: "Not Found", 405: "Method Not Allowed", 409: "Conflict",
    413: "Payload Too Large", 415: "Unsupported Media Type",
    422: "Unprocessable Entity", 429: "Too Many Requests",
    500: "Internal Server Error", 501: "Not Implemented",
    503: "Service Unavailable", 504: "Gateway Timeout",
}


def status_to_reason(code: int) -> str:
    return _STATUS_REASONS.get(int(code), "OK" if 200 <= int(code) < 300 else "Error")


# ══════════════════════════════════════════════════════════════════════
#  响应
# ══════════════════════════════════════════════════════════════════════
class Response:
    """一个待发送的 HTTP 响应。

    路由函数可以直接返回 ``dict`` / ``list``（当 JSON）、``str``（当纯文本）、
    ``bytes``（当二进制）、或本类实例（需要精确控制状态码/头）。
    """

    __slots__ = ("status", "headers", "body", "content_type", "stream")

    def __init__(self, body: Any = b"", *, status: int = 200,
                 content_type: str = "application/json; charset=utf-8",
                 headers: Optional[dict] = None,
                 stream: Optional[Callable[[Any], Any]] = None):
        self.status = int(status)
        self.content_type = content_type
        self.headers = dict(headers or {})
        self.stream = stream
        if isinstance(body, (bytes, bytearray)):
            self.body = bytes(body)
        elif body is None:
            self.body = b""
        elif isinstance(body, str):
            self.body = body.encode("utf-8")
        else:
            self.body = json.dumps(body, ensure_ascii=False, indent=2,
                                   default=str).encode("utf-8")
            self.content_type = "application/json; charset=utf-8"

    # ── 快捷构造 ────────────────────────────────────────────────
    @classmethod
    def json(cls, data: Any, status: int = 200, **headers) -> "Response":
        return cls(data, status=status, headers=headers)

    @classmethod
    def html(cls, text: str, status: int = 200) -> "Response":
        return cls(text, status=status, content_type="text/html; charset=utf-8")

    @classmethod
    def text(cls, text: str, status: int = 200) -> "Response":
        return cls(text, status=status, content_type="text/plain; charset=utf-8")

    @classmethod
    def sse(cls, generator: Any, **headers) -> "Response":
        """流式响应（Server-Sent Events）。``generator`` 产出 dict 或 str。"""
        h = {"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no",
             "Connection": "keep-alive"}
        h.update(headers)
        return cls(b"", status=200, content_type="text/event-stream; charset=utf-8",
                   headers=h, stream=generator)

    def with_headers(self, extra: dict) -> "Response":
        self.headers.update(extra or {})
        return self


def json_response(data: Any, status: int = 200, **headers) -> Response:
    return Response.json(data, status=status, **headers)


def error_response(exc: Exception, *, debug: bool = False) -> Response:
    """把异常映射成**结构化、可执行**的中文错误。

    GUI 靠 ``kind`` 决定展示方式，靠 ``hint`` 给用户下一步 —— 绝不只丢一个
    traceback 上去。
    """
    if isinstance(exc, errors.CardForgeError):
        payload = {"ok": False, "error": exc.message, "kind": type(exc).__name__,
                   "hint": exc.hint, "detail": exc.detail}
        if isinstance(exc, errors.AssetMissing):
            status = 404
        elif isinstance(exc, (errors.SpecError, errors.ValidationError, errors.LintError)):
            status = 422
        elif isinstance(exc, (errors.EnvError, errors.EngineUnavailable,
                              errors.LLMUnavailable)):
            status = 503
        elif isinstance(exc, errors.ComfyError):
            status = 503
            payload["comfy_kind"] = exc.kind
        else:
            status = 400
        return Response.json(payload, status=status)

    kind = type(exc).__name__
    if isinstance(exc, PermissionError):
        payload = {"ok": False, "error": f"越权访问：{exc}", "kind": "forbidden",
                   "hint": "文件接口只允许读取工作区与内置数据目录内的路径"}
        status = 403
    elif isinstance(exc, FileNotFoundError):
        payload = {"ok": False, "error": f"文件不存在：{exc}", "kind": "not_found",
                   "hint": "刷新一下看看，或检查路径是否拼错"}
        status = 404
    elif isinstance(exc, (json.JSONDecodeError, ValueError)):
        payload = {"ok": False, "error": f"请求体解析失败：{exc}", "kind": "bad_request",
                   "hint": "检查 JSON 格式与字段类型"}
        status = 400
    else:
        payload = {"ok": False, "error": f"{kind}: {exc}", "kind": "internal",
                   "hint": "这是程序缺陷。把这张卡的 spec.json 与下面的 traceback 一起反馈"}
        if debug:
            payload["traceback"] = traceback.format_exc()
        status = 500
    return Response.json(payload, status=status)


# ══════════════════════════════════════════════════════════════════════
#  请求
# ══════════════════════════════════════════════════════════════════════
class Request:
    """解析后的请求。路由函数拿这一个对象就够。"""

    __slots__ = ("method", "path", "params", "query", "body", "json", "headers", "app")

    def __init__(self, method: str, path: str, *, params: Optional[dict] = None,
                 query: Optional[dict] = None, body: bytes = b"",
                 headers: Optional[dict] = None, app: Any = None):
        self.method = method
        self.path = path
        self.params = params or {}
        self.query = query or {}
        self.body = body
        self.headers = headers or {}
        self.app = app
        self.json: dict = {}
        if body:
            ctype = (self.headers.get("content-type") or "").lower()
            if "application/json" in ctype:
                try:
                    parsed = json.loads(body.decode("utf-8"))
                    self.json = parsed if isinstance(parsed, dict) else {"value": parsed}
                except Exception as e:
                    raise errors.SpecError(
                        f"请求体不是合法 JSON：{e}",
                        "前端把对象直接 JSON.stringify，不要手动拼字符串") from e
            elif "application/x-www-form-urlencoded" in ctype:
                self.json = {k: v[-1] for k, v in
                             urllib.parse.parse_qs(body.decode("utf-8", "replace")).items()}

    # ── 取值助手 ────────────────────────────────────────────────
    def arg(self, name: str, default: Any = None) -> Any:
        """优先级：路径参数 → JSON body → query string。"""
        if name in self.params:
            return self.params[name]
        if isinstance(self.json, dict) and name in self.json:
            return self.json[name]
        if name in self.query:
            return self.query[name]
        return default

    def int_arg(self, name: str, default: int = 0) -> int:
        v = self.arg(name, None)
        try:
            return int(v) if v is not None and v != "" else int(default)
        except Exception:
            return int(default)

    def bool_arg(self, name: str, default: bool = False) -> bool:
        v = self.arg(name, None)
        if v is None:
            return bool(default)
        if isinstance(v, bool):
            return v
        return str(v).strip().lower() in ("1", "true", "yes", "y", "on", "是")

    def str_arg(self, name: str, default: str = "") -> str:
        v = self.arg(name, None)
        return default if v is None else str(v)

    def need(self, *names: str) -> dict:
        missing = [n for n in names if self.arg(n, None) in (None, "")]
        if missing:
            raise errors.SpecError(
                f"缺少必填参数：{'、'.join(missing)}",
                f"请带上 {', '.join(missing)} 再请求")
        return {n: self.arg(n) for n in names}

    @property
    def origin(self) -> str:
        return self.headers.get("origin", "") or ""

    @property
    def host(self) -> str:
        return self.headers.get("host", "") or ""


def read_body(rfile, headers: dict, *, limit: int = 64 * 1024 * 1024) -> bytes:
    """按 Content-Length 读请求体；无 body 时返回空 bytes。"""
    if (headers.get("expect") or "").lower().startswith("100-continue"):
        try:
            rfile.send_response(300)  # type: ignore[attr-defined]
            rfile.end_headers()       # type: ignore[attr-defined]
        except Exception:
            pass
    raw = headers.get("content-length")
    if not raw:
        return b""
    try:
        n = int(raw)
    except Exception:
        return b""
    if n <= 0:
        return b""
    if n > limit:
        raise errors.SpecError(f"请求体过大（{n} 字节，上限 {limit}）",
                               "卡图请走上传接口，不要塞进 JSON body")
    return rfile.read(n)


def parse_query(qs: str) -> dict:
    out: dict[str, str] = {}
    for k, v in urllib.parse.parse_qs(qs, keep_blank_values=True).items():
        out[k] = v[-1] if v else ""
    return out


# ══════════════════════════════════════════════════════════════════════
#  路径安全
# ══════════════════════════════════════════════════════════════════════
_TRAVERSAL = re.compile(r"(\.\.[\\/])|(^\\)|(^/)")


def safe_join(root: Path, rel: str, *, extra_roots: Optional[list[Path]] = None) -> Path:
    """把相对路径安全地拼到白名单根目录下。越界 → ``PermissionError``。

    ``/api/files`` 会把本地图片喂给浏览器，**必须**挡住
    ``../../Windows/win.ini`` 这类穿越，否则一个本地服务就变成任意文件读取。
    """
    rel = urllib.parse.unquote(str(rel or "").lstrip("/"))
    if _TRAVERSAL.search(rel) or "\x00" in rel:
        raise PermissionError(f"路径非法：{rel}")
    roots = [Path(root)] + [Path(p) for p in (extra_roots or [])]
    target = None
    for r in roots:
        candidate = (r / rel).resolve()
        try:
            candidate.relative_to(r.resolve())
        except Exception:
            continue
        if candidate.exists():
            target = candidate
            break
        if target is None:
            target = candidate
    if target is None:
        raise PermissionError(f"路径不在允许范围内：{rel}")
    return target


def content_type_of(path: Path, default: str = "application/octet-stream") -> str:
    return MIME.get(path.suffix.lower()) or mimetypes.guess_type(str(path))[0] or default


def log_line(msg: str) -> None:
    """服务端日志：走安全写入，绝不允许 ``print`` 把请求线程打死。"""
    console.eprint(f"[cardforge] {msg}")


__all__ += ["log_line", "parse_query", "content_type_of"]
