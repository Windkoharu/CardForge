"""``/api/update/*`` —— 检查 GitHub 上的新版本。

走 **api.github.com**（本机直连 github.com 会被重置）；公开仓库不需要 token。
检查失败**永远返回 200** + ``ok=False``，让界面把它当「暂时查不了」而不是报错。
"""
from __future__ import annotations

from .http import Request

__all__ = ["register"]


def register(app) -> None:

    @app.get("/api/update/check")
    def update_check(req: Request) -> dict:
        del req  # 无参数；timeout 固定 4s，界面点击不值得久等
        from ..core.update import check_update
        try:
            return check_update(timeout=4.0)
        except Exception as e:                             # noqa: BLE001
            return {"ok": False, "error": f"{type(e).__name__}: {e}",
                    "hint": "检查更新需要能访问 api.github.com；稍后再试"}
