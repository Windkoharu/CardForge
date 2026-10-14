"""本地 Web 服务（界面是壳，内核是 ``cardforge/`` 里的确定性代码）。

    app.py         路由框架 + 静态服务 + 安全边界（只监听本机、同源校验）
    http.py        请求/响应/错误映射
    kernel.py      软导入、载荷→规格、聚合视图
    api_core.py    doctor / state / meta / files / jobs / SSE / pool
    api_card.py    卡片 CRUD / PSCT 卡文 / Lua / 质量门 / 系列 / 卡组
    api_render.py  卡面预览 / 导出 / 能力分层
    api_art.py     ComfyUI 出图 / 模型 / 工作流 / 卡图库
    api_assistant.py  艾莉娅
    api_export.py  导出包 / 校验 / 一键安装

入口：``python -m cardforge serve`` → :func:`app.run`。
"""
from __future__ import annotations

from .app import App, Route, create_app, run  # noqa: F401

__all__ = ["App", "Route", "create_app", "run"]
