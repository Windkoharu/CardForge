"""CardForge 异常层次 —— 让调用方能区分「用户输入问题」与「环境问题」。"""
from __future__ import annotations


class CardForgeError(Exception):
    """所有本工程异常的基类。带中文提示与可选的修复建议。"""

    def __init__(self, message: str, hint: str = "", *, detail: dict | None = None):
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.detail = detail or {}

    def to_dict(self) -> dict:
        return {"error": type(self).__name__, "message": self.message,
                "hint": self.hint, "detail": self.detail}

    def __str__(self) -> str:  # pragma: no cover - 展示用
        return f"{self.message}（建议：{self.hint}）" if self.hint else self.message


# ── 输入/规格类 ──────────────────────────────────────────────────────
class SpecError(CardForgeError):
    """spec.json 缺字段、类型不对、取值非法。"""


class ValidationError(CardForgeError):
    """质量门拦截。detail 里带 issues 列表。"""


class LintError(CardForgeError):
    """PSCT 文本或 Lua 脚本的确定性校验失败。"""


# ── 环境/依赖类 ──────────────────────────────────────────────────────
class EnvError(CardForgeError):
    """环境缺失（Python 版本、Pillow、字体、素材）。"""


class AssetMissing(EnvError):
    """素材/字体缺失，且无法优雅降级。"""


class ComfyError(CardForgeError):
    """ComfyUI 调用失败。"""

    def __init__(self, message: str, hint: str = "", *, kind: str = "unknown",
                 detail: dict | None = None):
        super().__init__(message, hint, detail=detail)
        self.kind = kind  # offline | node_missing | model_missing | oom | timeout | bad_prompt


class EngineUnavailable(CardForgeError):
    """ocgcore 原生库不可用 —— 触发 L3 降级，不是错误。"""


class LLMUnavailable(CardForgeError):
    """LLM 端点不可用 —— 触发『无 LLM 降级』，不是错误。"""
