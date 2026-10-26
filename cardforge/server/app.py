"""本地 Web 服务 —— 标准库 ``http.server``，零依赖、零构建。

设计要点
--------
1. **只监听 127.0.0.1。** 这个进程能读写本地文件、能提交 ComfyUI 任务，
   暴露到局域网是不负责任的。``--host 0.0.0.0`` 会被明确警告。
2. **同源校验（含 Host 校验）。** 防 DNS rebinding：浏览器里任何页面都能
   向 ``http://localhost:8790`` 发请求，若不校验 Origin/Host，恶意网页就能
   驱动本工具往磁盘写文件。非白名单来源一律 403。
3. **路由函数返回 Python 对象即可**：``dict``/``list`` → JSON，``str`` → 文本，
   ``bytes`` → 二进制，``Response`` → 精确控制，生成器 → SSE。
4. **内核能力缺失绝不 500。** 所有可选模块（assistant / duel / lua emit）都
   软导入，缺了就返回带中文说明与下一步建议的 ``501`` + ``hint``，界面照样能用。
   这条是项目 L0/L1/L2/L3 分层降级原则在 HTTP 层的镜像。
5. **静态资源从 ``web/`` 读，每次请求都重新 stat**，改前端刷新即生效（开发体验）。
"""
from __future__ import annotations

import json
import os
import re
import socket
import socketserver
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from .. import __version__
from ..core import console, errors, paths
from .http import (Request, Response, content_type_of, error_response, log_line,
                   parse_query, read_body)

__all__ = ["App", "Route", "create_app", "run", "CFG", "DEFAULT_CFG"]

#: 允许访问的来源。本地开发常用三种写法都要认。
_ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}
_ALLOWED_ORIGINS_RE = re.compile(r"^https?://(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$", re.I)

DEFAULT_CFG: dict[str, Any] = {
    "host": "127.0.0.1",
    "port": 8790,
    "open_browser": True,
    "debug": False,
    "web_dir": None,
    "max_body": 64 * 1024 * 1024,
}

#: 运行期配置（create_app 填充；api 模块可回读端口）
CFG: dict[str, Any] = dict(DEFAULT_CFG)


def _methods(spec: str) -> list[str]:
    out: list[str] = []
    for part in str(spec).replace("+", ",").split(","):
        p = part.strip().upper()
        if p and p not in out:
            out.append(p)
    return out or ["GET"]


_PARAM_RE = re.compile(r"<([A-Za-z_]\w*)(?::([^>]*))?>")


def compile_pattern(path: str) -> re.Pattern:
    """``/api/cards/<id>`` → 正则。

    * ``<name>``           —— 匹配一段
    * ``<name:正则>``       —— 自定义匹配
    * ``<rel:path>``       —— 贪婪匹配剩余全部（文件接口用）
    * 结尾 ``?``            —— 最后一段可省略（``/api/cards/<id>?``）
    """
    p = str(path).rstrip("/")
    optional = p.endswith("?")
    if optional:
        p = p[:-1]
    parts: list[str] = []
    for seg in [s for s in p.split("/") if s]:
        m = _PARAM_RE.fullmatch(seg)
        if not m:
            parts.append(re.escape(seg))
            continue
        name, pat = m.group(1), (m.group(2) or "").strip()
        if pat in ("path", ".*") or name == "rel":
            parts.append(f"(?P<{name}>.+)" if name.isidentifier() else f"(?P<rel>.+)")
        else:
            if not name.isidentifier():
                name = f"p{len(parts)}"
            parts.append(f"(?P<{name}>{pat or '[^/]+'})")
    body = "/".join(parts)
    rx = f"^/(?:{body})?$" if optional else f"^/{body}/?$"
    return re.compile(rx)


def match_route(pattern: re.Pattern, path: str) -> Optional[dict]:
    """路径 → 参数字典；不匹配返回 None。"""
    m = pattern.match(path or "/")
    if not m:
        return None
    return {k: urllib.parse.unquote(v) for k, v in m.groupdict().items() if v is not None}


class Route:
    __slots__ = ("method", "path", "fn", "pattern", "meta")

    def __init__(self, method: str, path: str, fn: Callable,
                 pattern: re.Pattern, meta: dict):
        self.method, self.path, self.fn = method, path, fn
        self.pattern, self.meta = pattern, meta


class App:
    """极小路由框架（不是 Web 框架 —— 没有任何业务逻辑住在这里）。"""

    def __init__(self, cfg: Optional[dict] = None):
        self.cfg = dict(DEFAULT_CFG)
        self.cfg.update(cfg or {})
        CFG.update(self.cfg)
        self.routes: list[Route] = []
        self.middlewares: list[Callable] = []
        self.state: dict[str, Any] = {}
        self.started_at = time.time()
        self.web_dir = Path(self.cfg.get("web_dir") or paths.WEB)
        self.requests = 0
        self.errors_seen = 0
        self._server = None

    # ── 注册 ────────────────────────────────────────────────────
    def route(self, method: str = "GET", path: str = "/", *,
              meta: Optional[dict] = None) -> Callable:
        def deco(fn: Callable) -> Callable:
            self.add(method, path, fn, meta=meta)
            return fn
        return deco

    def add(self, method: str, path: str, fn: Callable, *,
            meta: Optional[dict] = None) -> None:
        for m in _methods(method):
            self.routes.append(Route(m, path, fn, compile_pattern(path), meta or {}))

    def get(self, path: str, **kw):
        return self.route("GET", path, **kw)

    def post(self, path: str, **kw):
        return self.route("POST", path, **kw)

    def put(self, path: str, **kw):
        return self.route("PUT", path, **kw)

    def patch(self, path: str, **kw):
        return self.route("PATCH", path, **kw)

    def delete(self, path: str, **kw):
        return self.route("DELETE", path, **kw)

    def use(self, fn: Callable) -> Callable:
        self.middlewares.append(fn)
        return fn

    # ── 分发 ────────────────────────────────────────────────────
    def handle(self, req: Request) -> Response:
        allowed = {r.method for r in self.routes if match_route(r.pattern, req.path)}
        for r in self.routes:
            if r.method != req.method:
                continue
            params = match_route(r.pattern, req.path)
            if params is None:
                continue
            req.params = params
            for mw in self.middlewares:
                early = mw(req)
                if early is not None:
                    return _to_response(early)
            return _to_response(r.fn(req))
        if allowed:
            return error_response(errors.CardForgeError(
                f"{req.path} 不支持 {req.method}", f"支持的方法：{'、'.join(sorted(allowed))}"))
        return Response.json({"ok": False, "error": f"没有这个接口：{req.path}",
                              "kind": "not_found",
                              "hint": "见 docs/02 §10 的路由清单，或刷新页面重来"},
                             status=404)

    # ── 静态资源 ────────────────────────────────────────────────
    def serve_static(self, url_path: str) -> Response:
        rel = url_path.strip("/") or "index.html"
        try:
            p = _static_lookup(self.web_dir, rel)
        except PermissionError as e:
            return error_response(e)
        if p is None:
            # 前端是单页应用：未知路径回落 index.html
            idx = self.web_dir / "index.html"
            if idx.exists():
                p = idx
            else:
                return Response.html(_no_web_hint(), status=503)
        if p.is_dir():
            idx = p / "index.html"
            if not idx.exists():
                return Response.html(_no_web_hint(), status=503)
            p = idx
        try:
            data = p.read_bytes()
        except OSError as e:
            return error_response(e)
        html = p.suffix.lower() in (".html", ".htm")
        # 前端代码一律不缓存：实测浏览器对 ``no-cache`` 的 ES 模块经常不回源校验，
        # 升级后界面还是老样子（召唤条件面板就是被这个坑过一次）。
        # 本机静态文件总共两百来 KB，不缓存比"用户看到旧界面"便宜得多。
        fresh = html or p.suffix.lower() in (".js", ".mjs", ".css")
        headers = {"Cache-Control": "no-store" if (fresh or self.cfg.get("debug"))
                   else "no-cache", "X-Content-Type-Options": "nosniff",
                   "X-Frame-Options": "DENY"}
        if html:
            data = _stamp_assets(data, self.web_dir)
            # 无框架、无 CDN、无内联脚本；图片要允许本机 ComfyUI 的 /view 端口
            headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: blob: http://127.0.0.1:* http://localhost:*; "
                "connect-src 'self' http://127.0.0.1:* http://localhost:*; "
                "font-src 'self' data:; frame-ancestors 'none'; base-uri 'self'"
            )
        return Response(data, content_type=content_type_of(p), headers=headers)

    # ── 运行 ────────────────────────────────────────────────────
    def run(self, host: Optional[str] = None, port: Optional[int] = None,
            open_browser: Optional[bool] = None, progress: Any = None) -> int:
        """启动服务。

        ``progress`` 可选传入 :class:`cardforge.core.progress.Progress` ——
        启动进度条会挂在**真实步骤**上（探测端口 / 绑定 / 就绪 / 打开浏览器）。
        不传就还是原来的纯文本输出（脚本、测试走这条）。
        """
        host = host or self.cfg["host"]
        port = int(port or self.cfg["port"])
        if open_browser is None:
            open_browser = bool(self.cfg.get("open_browser", True))

        def padv(frac: float, label: str = "") -> None:
            if progress is not None:
                try:
                    progress.advance(frac, label)
                except Exception:
                    pass

        def pnote(text: str) -> None:
            if progress is not None:
                try:
                    progress.note(text)
                except Exception:
                    pass

        def pdone(text: str) -> None:
            if progress is not None:
                try:
                    progress.done(text)
                except Exception:
                    pass

        if not self.web_dir.exists():
            console.eprint(f"\n  [X] 前端目录不存在：{self.web_dir}", file=sys.stderr)
            console.eprint("      → 确认 web/ 与 cardforge/ 同级；"
                           "或用 CARDFORGE_WEB 环境变量指定", file=sys.stderr)
            if progress is not None:
                progress.fail(f"前端目录不存在：{self.web_dir}")
            return 1

        paths.ensure_dirs()
        handler = _make_handler(self)

        # ── 找端口 ──────────────────────────────────────────────────
        # 优化动机（也是实测教训）：Windows 的 SO_REUSEADDR 允许**双绑定**——
        # 两台服务器能同时监听 8790，请求随机落到谁手里。所以「靠 bind 抛错
        # 发现端口占用」在 Windows 上根本不成立，必须先主动探测：
        #   ① 主端口已有 CardForge → 直接复用并打开（这正是「双击即用」）；
        #   ② 主端口被别的程序占用 → 自动顺延；
        #   ③ 一路找得到空位 → 正常起服务。
        def _listening(h: str, p_: int) -> bool:
            try:
                with socket.create_connection((h, p_), timeout=0.6):
                    return True
            except OSError:
                return False

        if _listening(host, port) and _probe_cardforge(host, port):
            url = f"http://{host}:{port}"
            padv(0.95, f"复用已在运行的实例 {url}")
            console.eprint("", file=sys.stdout)
            console.eprint(f"  已有 CardForge 在跑（{url}），本进程直接复用它。",
                           file=sys.stdout)
            console.eprint("  → 想换新工作区/新端口：先关掉那个窗口，再启动一次。",
                           file=sys.stdout)
            if open_browser:
                # 同步等（对方已在线，毫秒级返回）——
                # 这里不能用守护线程：本函数马上 return，进程一退线程就被掐死。
                _open_when_ready(url, timeout=5.0)
            pdone(f"已就绪 → {url}（浏览器已打开）" if open_browser
                  else f"已就绪 → {url}")
            pnote("停止：关掉那个已存在的窗口 / Ctrl-C")
            # 双击启动时本进程会立刻退出、控制台窗口随之关闭 ——
            # 用户只会看到「闪一下」，以为没反应。真终端里停 2 秒把话说完；
            # 脚本/管道调用不受影响（非 TTY 不停）。
            try:
                if sys.stdout.isatty():
                    time.sleep(2.0)
            except Exception:
                pass
            return 0

        padv(0.42, f"探测端口 {host}:{port}…")
        server: Optional[_Server] = None
        last_err: Optional[OSError] = None
        p = port
        while p < port + 10 and server is None:
            if _listening(host, p):        # 有人（或别的程序）蹲着 → 下一个
                last_err = None
                p += 1
                continue
            try:
                server = _Server((host, p), handler)
            except OSError as e:
                last_err = e
                p += 1
        if server is None:
            console.eprint(f"\n  [X] 端口 {port}–{port + 9} 都起不来：{last_err or '全被占用'}",
                           file=sys.stderr)
            console.eprint(f"      → 换个显式端口：python -m cardforge serve --port {port + 20}",
                           file=sys.stderr)
            if progress is not None:
                progress.fail(f"端口 {port}–{port + 9} 都起不来（{last_err or '全被占用'}）")
            return 1
        if p != port:
            console.eprint(f"  [!]  端口 {port} 被占用（不是 CardForge），已自动改用 {p}。",
                           file=sys.stdout)
            pnote(f"端口 {port} 被占用（不是 CardForge），已自动改用 {p}。")

        self._server = server
        self.cfg["host"], self.cfg["port"] = host, p
        CFG["host"], CFG["port"] = host, p
        url = f"http://{host}:{p}"
        padv(0.62, f"已绑定 {host}:{p}")

        _ws = paths.rel(paths.WORKSPACE)
        _web = (paths.rel(self.web_dir) if _inside(self.web_dir, paths.ROOT)
                else str(self.web_dir))
        _warn = ("" if str(host) in _ALLOWED_HOSTS else
                 "  [!]  监听地址不是 127.0.0.1 —— 这台机器上的任何人都能用这个界面读写你的文件。")

        if progress is not None:
            # 有进度条时不再打印整块就绪文本：\r 重绘与多行输出混在一起会花屏。
            padv(0.9, "服务已就绪")
            pdone(f"已就绪 → {url}（浏览器已打开）" if open_browser else f"已就绪 → {url}")
            pnote(f"工作区 {_ws}   ｜   前端 {_web}")
            pnote("停止：关闭本窗口 / Ctrl-C" + (_warn and ("　" + _warn.strip()) or ""))
            if _warn:
                console.eprint(_warn, file=sys.stderr)
        else:
            console.eprint("", file=sys.stdout)
            console.eprint(f"  CardForge {__version__} 已就绪 → {url}", file=sys.stdout)
            console.eprint(f"  工作区 {_ws}   "
                           f"前端 {_web}", file=sys.stdout)
            if _warn:
                console.eprint(_warn, file=sys.stderr)
            console.eprint("  停止：关闭本窗口 / Ctrl-C", file=sys.stdout)
            console.eprint("", file=sys.stdout)

        if open_browser:
            # 不再固定 0.4s 盲开：等 /api/state 真能应答再开，
            # 避免浏览器先弹一个「无法访问此网站」再刷新。
            threading.Thread(target=_open_when_ready, args=(url,), daemon=True).start()
        try:
            server.serve_forever(poll_interval=0.3)
        except KeyboardInterrupt:
            console.eprint("\n  已停止图形界面", file=sys.stdout)
        finally:
            server.shutdown()
            server.server_close()
        return 0


def _inside(p: Path, root: Path) -> bool:
    try:
        Path(p).resolve().relative_to(Path(root).resolve())
        return True
    except Exception:
        return False


def _asset_stamp(web_dir: Path) -> str:
    """web/ 下最新前端文件的指纹（mtime+大小）。

    浏览器对 ``Cache-Control: no-cache`` 的 ES 模块**未必**回源校验（实测会拿
    旧副本），升级后就会出现「界面还是老样子」。所以 index.html 里的 css/js
    都带 ``?v=``，前端一改版本号就变，用户刷新即拿到新代码。
    """
    best = 0
    size = 0
    try:
        for f in web_dir.rglob("*"):
            if f.suffix.lower() not in (".js", ".css", ".html") or not f.is_file():
                continue
            st = f.stat()
            if st.st_mtime_ns > best:
                best, size = st.st_mtime_ns, st.st_size
    except OSError:
        return "0"
    return format(best, "x")[-8:] + format(size, "x")[-5:]


def _stamp_assets(data: bytes, web_dir: Path) -> bytes:
    """把 index.html 里的 ``{{ASSET_V}}`` 换成实时版本号。"""
    if b"{{ASSET_V}}" not in data:
        return data
    try:
        return data.replace(b"{{ASSET_V}}", _asset_stamp(web_dir).encode("ascii"))
    except Exception:
        return data


def _static_lookup(root: Path, rel: str) -> Optional[Path]:
    """在 ``web/`` 下安全找文件；越界抛 ``PermissionError``。"""
    rel = urllib.parse.unquote(rel).replace("\\", "/").lstrip("/")
    if ".." in rel.split("/") or "\x00" in rel:
        raise PermissionError(rel)
    target = (root / rel).resolve()
    try:
        target.relative_to(root.resolve())
    except Exception:
        raise PermissionError(rel)
    return target if target.exists() else None


def _to_response(out: Any) -> Response:
    if isinstance(out, Response):
        return out
    if isinstance(out, bytes):
        return Response(out, content_type="application/octet-stream")
    if isinstance(out, str):
        return Response.text(out)
    if hasattr(out, "__next__") or hasattr(out, "send"):
        return Response.sse(out)
    if isinstance(out, tuple) and len(out) == 2 and isinstance(out[0], int):
        return Response.json(out[1], status=out[0])
    return Response.json(out if out is not None else {"ok": True})


def _no_web_hint() -> str:
    return ("<html><meta charset='utf-8'><body style='font-family:system-ui;"
            "padding:40px;line-height:1.9'><h2>找不到前端文件</h2>"
            "<p>服务已经起来了，但 <code>web/</code> 目录不在预期位置。"
            "它应该与 <code>cardforge/</code> 同级。</p>"
            "<p>可以用环境变量指路：<code>CARDFORGE_WEB=/绝对路径/web</code></p>"
            "</body></html>")


# ══════════════════════════════════════════════════════════════════════
#  请求处理
# ══════════════════════════════════════════════════════════════════════
def _make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = f"CardForge/{__version__}"
        sys_version = f"Python/{sys.version.split()[0]}"
        protocol_version = "HTTP/1.1"

        # 关掉 BaseHTTPRequestHandler 自己的 print（它在 GBK 控制台上会炸）
        def log_message(self, fmt: str, *a) -> None:  # noqa: A003
            pass

        # ── 头与安全 ────────────────────────────────────────────
        def _headers(self) -> dict:
            return {k.lower(): v for k, v in self.headers.items()}

        def _origin_allowed(self, headers: dict) -> tuple[bool, str]:
            host = (headers.get("host") or "").split(":")[0].strip("[]")
            if host not in _ALLOWED_HOSTS and not self.server.allow_external:  # type: ignore[attr-defined]
                return False, f"Host 头是 {host}，只允许本机地址"
            origin = headers.get("origin") or ""
            if origin and not _ALLOWED_ORIGINS_RE.match(origin):
                return False, f"来源是 {origin}，只允许本机页面"
            referer = headers.get("referer") or ""
            if referer:
                m = re.match(r"^https?://([^/]+)", referer)
                if m and m.group(1).split(":")[0].strip("[]") not in _ALLOWED_HOSTS:
                    return False, f"页面来源 {m.group(1)} 不是本机"
            return True, ""

        # ── 发送 ────────────────────────────────────────────────
        def _send(self, resp: Response, *, head_only: bool = False) -> None:
            self.close_connection = True
            if resp.stream is not None:
                self.send_response(resp.status)
                self.send_header("Content-Type", resp.content_type)
                self.send_header("Cache-Control", "no-cache")
                for k, v in resp.headers.items():
                    self.send_header(k, v)
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                try:
                    for chunk in _sse_bytes(resp.stream):
                        self.wfile.write(b"%x\r\n" % len(chunk))
                        self.wfile.write(chunk + b"\r\n")
                        self.wfile.flush()
                    self.wfile.write(b"0\r\n\r\n")
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass      # 用户关页面是正常事件，不是错误
                return

            body = resp.body or b""
            self.send_response(resp.status)
            self.send_header("Content-Type", resp.content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in resp.headers.items():
                self.send_header(k, v)
            self.end_headers()
            if not head_only:
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass

        def _dispatch(self, method: str, *, head_only: bool = False) -> None:
            app.requests += 1
            parsed = urllib.parse.urlsplit(self.path)
            path = parsed.path or "/"
            headers = self._headers()
            ok, why = self._origin_allowed(headers)
            if not ok:
                self._send(Response.json(
                    {"ok": False, "error": f"拒绝跨站请求：{why}", "kind": "forbidden",
                     "hint": "CardForge 只服务本机浏览器打开的界面"}, status=403))
                return
            try:
                if path.startswith("/api/"):
                    body = b"" if method in ("GET", "HEAD", "DELETE") else read_body(
                        self.rfile, headers, limit=int(app.cfg.get("max_body", 0) or 0))
                    req = Request(method, path, query=parse_query(parsed.query),
                                  body=body, headers=headers, app=app)
                    resp = app.handle(req)
                elif method in ("GET", "HEAD"):
                    resp = app.serve_static(path)
                else:
                    resp = Response.json({"ok": False, "error": f"不支持 {method} {path}",
                                          "kind": "bad_method"}, status=405)
            except Exception as e:                      # 任何缺陷都不许让连接挂死
                resp = error_response(e, debug=bool(app.cfg.get("debug")))
                if isinstance(e, errors.CardForgeError):
                    # 可降级的能力缺失是**设计内**的状态，不该刷满屏红字
                    log_line(f"{method} {path} → {resp.status} {type(e).__name__}")
                else:
                    app.errors_seen += 1
                    console.eprint(f"接口出错 {method} {path}: "
                                   f"{type(e).__name__}: {e}", file=sys.stderr)
            self._send(resp, head_only=head_only)

        def do_GET(self) -> None:      # noqa: N802
            self._dispatch("GET")

        def do_HEAD(self) -> None:     # noqa: N802
            self._dispatch("HEAD", head_only=True)

        def do_POST(self) -> None:     # noqa: N802
            self._dispatch("POST")

        def do_PUT(self) -> None:      # noqa: N802
            self._dispatch("PUT")

        def do_PATCH(self) -> None:    # noqa: N802
            self._dispatch("PATCH")

        def do_DELETE(self) -> None:   # noqa: N802
            self._dispatch("DELETE")

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(204)
            self.send_header("Allow", "GET, HEAD, POST, PUT, PATCH, DELETE, OPTIONS")
            self.end_headers()

    return Handler


def _sse_bytes(gen) -> Iterable[bytes]:
    """把 dict 生成器编码成 SSE 帧。"""
    for item in gen:
        if isinstance(item, (bytes, bytearray)):
            yield bytes(item)
            continue
        if isinstance(item, str):
            payload = item
        else:
            payload = json.dumps(item, ensure_ascii=False, default=str)
        yield f"event: message\ndata: {payload}\n\n".encode("utf-8")


# ══════════════════════════════════════════════════════════════════════
#  服务器
# ══════════════════════════════════════════════════════════════════════
class _Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """线程化 + 端口复用。

    ``daemon_threads`` 是关键：SSE 长连接会占住一条线程直到客户端断开，
    非守护线程会让 Ctrl-C 永远退不出去。
    """
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 64

    def __init__(self, addr, handler):
        super().__init__(addr, handler)
        self.allow_external = str(addr[0]) not in _ALLOWED_HOSTS
        self.cardforge_app = None


def _open_browser(url: str) -> None:
    """尽力打开系统浏览器；一级失败换二级，全失败就打印 URL 让人手动点。"""
    ok = False
    try:
        if sys.platform.startswith("win"):
            os.startfile(url)  # type: ignore[attr-defined]
            ok = True
        elif sys.platform == "darwin":
            import subprocess
            ok = subprocess.run(["open", url], check=False).returncode == 0
        else:
            ok = bool(webbrowser.open_new(url))
    except Exception:
        ok = False
    if not ok:
        try:
            ok = bool(webbrowser.open_new(url))
        except Exception:
            ok = False
    if not ok:
        console.eprint(f"  → 自动打开浏览器失败，请手动访问 {url}", file=sys.stderr)


def _open_when_ready(url: str, timeout: float = 25.0) -> None:
    """等 ``/api/state`` 真能应答再开浏览器（超时也开，尽力而为）。

    固定延时盲开在慢机器上会先弹一个「无法访问此网站」，用户还得手动刷新 ——
    这一步只是把「刷新」替用户做了。
    """
    import urllib.request
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(url + "/api/state", timeout=0.8) as r:
                r.read(64)
            break
        except Exception:
            time.sleep(0.25)
    _open_browser(url)


def _probe_cardforge(host: str, port: int, *, tries: int = 3,
                     timeout: float = 2.5) -> bool:
    """那个端口上蹲着的，是不是一个 CardForge？（用来决定「复用」还是「顺延」）

    重试是必要的：刚启动、正在跑自检、或客户端偶发卡顿时，一次 1 秒的探测
    会误判成「别的程序占着」，于是白白顺延一个端口、多起一个实例。
    宁可多花两秒，也不要生出一个没人要的第二个实例。
    """
    import urllib.request
    for i in range(max(1, tries)):
        try:
            with urllib.request.urlopen(f"http://{host}:{port}/api/state",
                                        timeout=timeout) as r:
                head = r.read(512).decode("utf-8", "replace")
            if '"version"' in head and '"ok"' in head:
                return True
        except Exception:
            pass
        if i + 1 < tries:
            time.sleep(0.6)
    return False


# ══════════════════════════════════════════════════════════════════════
#  装配
# ══════════════════════════════════════════════════════════════════════
def create_app(cfg: Optional[dict] = None) -> App:
    app = App(cfg)
    from . import api_core, api_card, api_render, api_art, api_assistant, api_llm, api_export  # noqa: E402
    for mod in (api_core, api_card, api_render, api_art, api_assistant, api_llm, api_export):
        mod.register(app)
    app.state.setdefault("routes", [(r.method, r.path) for r in app.routes])
    return app


def run(host: Optional[str] = None, port: Optional[int] = None,
        *, open_browser: bool = True, cfg: Optional[dict] = None,
        progress: Any = None) -> int:
    """``cardforge serve`` / ``launch`` 的实现入口。

    ``progress`` 透传给 :meth:`App.run` —— 启动进度条挂真实步骤用（见 core/progress.py）。
    """
    app = create_app(cfg)
    return app.run(host=host, port=port, open_browser=open_browser,
                   progress=progress)


def serve_once(app: App, host: str = "127.0.0.1", port: int = 0) -> tuple:
    """测试用：起一个一次性服务，返回 ``(server, url, stop)``。"""
    handler = _make_handler(app)
    server = _Server((host, port), handler)
    url = f"http://{host}:{server.server_address[1]}"
    th = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                          daemon=True)
    th.start()

    def stop():
        server.shutdown()
        server.server_close()
    return server, url, stop
