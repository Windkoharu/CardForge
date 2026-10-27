"""更新检测 —— 本地版本 vs GitHub ``main`` 上的版本。

为什么走 **api.github.com**：本机直连 ``github.com:443`` 会被重置
（实测多次），而 API 通道一直可用；公开仓库不需要 token。

* 远端版本号取 ``main`` 分支的 ``cardforge/__init__.py`` —— 单一事实来源，
  不会出现「release 忘了发」导致的假最新；
* 顺带给远端 ``main`` 的 commit sha，本地是 git 检出时还能对出「落后/领先」；
* 网络失败**友好降级**：返回 ``ok=False`` 与可读 hint，绝不影响本地使用。
"""
from __future__ import annotations

import base64
import json
import re
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

__all__ = ["GITHUB_REPO", "check_update", "local_version"]

GITHUB_REPO = "Windkoharu/CardForge"
_API = "https://api.github.com"
_DEFAULT_TIMEOUT = 5.0
_UA = "CardForge-update-check"

_V_RE = re.compile(
    r"^\s*v?(\d+(?:\.\d+)*)\s*(?:[.-](dev|alpha|beta|rc)\.?(\d+)?)?\s*$", re.I)


def local_version() -> str:
    """本地包版本（``cardforge.__version__``，调用时取避免循环导入）。"""
    from cardforge import __version__
    return __version__


def _vkey(v: str):
    """``"2.1.0.dev1"`` → 可比较元组 ``((2,1,0), ("dev",1))``；解析失败 ``None``。"""
    m = _V_RE.match(v or "")
    if not m:
        return None
    nums = tuple(int(x) for x in m.group(1).split("."))
    if m.group(2):
        pre = (m.group(2).lower(), int(m.group(3) or 0))
    else:
        pre = ("final", 0)
    return (nums, pre)


def _local_git_sha() -> "str | None":
    """本地是 git 检出时给 HEAD sha；打包版/无 git 时给 None。"""
    try:
        root = Path(__file__).resolve().parents[2]
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(root),
            capture_output=True, text=True, encoding="utf-8", check=True)
        return out.stdout.strip() or None
    except Exception:
        return None


def _get(url: str, timeout: float):
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": _UA,
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def check_update(timeout: float = _DEFAULT_TIMEOUT) -> dict:
    """检查远端是否有新版本。**永远不抛异常** —— 网络问题走 ``ok=False``。"""
    out: dict = {
        "ok": False,
        "local_version": local_version(),
        "local_sha": _local_git_sha(),
        "repo": GITHUB_REPO,
    }
    try:
        meta = _get(f"{_API}/repos/{GITHUB_REPO}/contents/cardforge/__init__.py?ref=main",
                    timeout)
        src = base64.b64decode(meta.get("content", "")).decode("utf-8", "replace")
        m = re.search(r'__version__\s*=\s*"([^"]+)"', src)
        remote = m.group(1) if m else None
        head = _get(f"{_API}/repos/{GITHUB_REPO}/commits/main", timeout)
        remote_sha = (head or {}).get("sha")
        out.update({"ok": True, "remote_version": remote, "remote_sha": remote_sha})

        lk, rk = _vkey(out["local_version"]), _vkey(remote or "")
        if lk is None or rk is None:
            out.update({"update_available": False, "comparison": "unknown",
                        "hint": "版本号解析不了，请手工比对 " + f"github.com/{GITHUB_REPO}"})
        else:
            newer = rk > lk
            behind_git = bool(out["local_sha"] and remote_sha
                              and out["local_sha"] != remote_sha)
            out.update({"update_available": bool(newer),
                        "comparison": "ok",
                        "local_is_head": (out["local_sha"] == remote_sha)
                        if out["local_sha"] else None})
            if newer:
                if out["local_sha"] and remote_sha:
                    out["url"] = (f"https://github.com/{GITHUB_REPO}/compare/"
                                  f"{out['local_sha'][:10]}...{remote_sha[:10]}")
                else:
                    out["url"] = f"https://github.com/{GITHUB_REPO}/commits/main"
                out["hint"] = (f"远端 main 已是 {remote}，本地 {out['local_version']}"
                               " → 拉取新版覆盖，或本地 git pull 后重启")
            elif lk > rk:
                out["update_available"] = False
                out["hint"] = (f"本地 {out['local_version']} 比远端 main 的 {remote} 新"
                               " —— 开发机还没推送属正常，用户端不会看到这条")
            elif behind_git:
                out["hint"] = ("版本号相同，但本地 commit 与远端 main 不一致"
                               "（本地领先或落后）——以 git 为准")
            else:
                out["hint"] = "已是最新版本"
    except Exception as e:                                # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {e}"
        out["hint"] = "检查更新需要能访问 api.github.com；稍后再试，不影响本地使用"
    out["checked_at"] = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    return out
