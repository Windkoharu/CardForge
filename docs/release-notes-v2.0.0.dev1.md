# CardForge 2.0.0.dev1

**把「一句话设想」锻成「能上牌桌的卡」。**
Turn a one-sentence idea into a playable Yu-Gi-Oh! DIY card — fully local.

## Highlights

- **四步流水线**：规格 → PSCT 卡文 + Lua 脚本 → 卡图 + 卡面 → 导出上桌（EDOPro / MDPro3 / .ydk）
- **17 种卡种 · 25 种罕贵 · 6 档出框 · 10 种语言**，严格照官方实测规格（卡图窗斜切框、文本框半透明、版权行截断）
- **质量门 G1–G5 全部确定性代码**：平衡审计、脚本静态检查（844 API 白名单）、**真开一局对战的实跑验证**（ocgcore）、系列一致性、导出自检——降级永远如实标注，绝不谎报通过
- **PSCT 校验器 38 条规则**，覆盖官方规范全部硬性错误
- **助手「星奏·艾莉娅」**：三档人格，把质量门结论翻译成人话；**LLM 只提议、内核裁决**，无 LLM 时功能不缺失
- **本机 ComfyUI 出图**：单张 / 分层（背景+主体抠底）/ 系列一致性 / 风格参考 / 工作流 JSON 导出
- **打包独立程序**：`tools/build_exe.py` 一键 onefolder，目标 Windows 机器零依赖

## Downloads

| 文件 | 说明 |
|---|---|
| `CardForge-2.0.0.dev1-win-x64-engine.zip`（154.8 MB） | Windows x64，**含对局引擎**（L3 真跑对局开箱即用） |

解压到任意可写目录 → 双击 `CardForge\CardForge.exe`。
首次运行 SmartScreen 提示选「更多信息 → 仍要运行」（未签名工具的常规提示）。

## Requirements

- 打包版：Windows x64，无需安装任何东西
- 源码版：Python 3.10+（核心零 pip 依赖；渲染需 Pillow）
- 可选：本机 ComfyUI（出图）、ocgcore（对局验证，EDOPro 自带）、任意 OpenAI 兼容 LLM 端点（AI 起草）

## Verified

- 自测四件套：smoke 16/16 · Lua 生成器 175 断言 · 助手 81 断言 · 端到端 26 项
- 演示卡 `210000011`：G1/G2/G3 三门全绿（G3 真开 38 回合对局）
- MDPro3 `.ypk` 真机导入闭环：导入成功 → 卡可见 → 对局效果生效

## License

代码与文档：MIT（见 LICENSE）。随包第三方素材受各自条款约束（见 NOTICE）。
本项目为非官方个人学习/研究工具，与 Konami 无关联。
