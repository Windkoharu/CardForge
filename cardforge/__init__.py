"""CardForge 卡锻 2.0 —— 跨平台 AI 游戏王 DIY 工坊。

模块分工（依赖严格单向：core ← 各内核 ← pipeline ← server/cli）::

    core/       领域模型与常量（零依赖）
    render/     卡面渲染：三段式管线 / 罕贵注册表 / 出框 / 多语言排版
    content/    PSCT 卡文生成与校验 / 效果 DSL / Lua 生成 / 平衡审计
    art/        ComfyUI 客户端 / 工作流构造与导出 / 提示词 / 卡图资产库
    assistant/  星奏·艾莉娅：人格、LLM 适配、工具调用、知识库检索
    pool/       .cdb 读写 / 官方卡池查询 / 项目仓库
    duel/       对局验证（三层降级：真跑 / 静态校验 / 仅导出）
    export/     expansions / strings.conf / .ydk / 一键安装
    pipeline/   质量门 G1–G5 与单卡·系列·卡组三条流水线
    server/     本地 Web 服务（标准库 http.server + SSE）
    cli.py      命令行内核
"""

__version__ = "2.0.0.dev1"
__all__ = ["__version__"]
