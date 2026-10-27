# CardForge 卡锻 2.0

> **跨平台 AI 游戏王 DIY 工坊** —— 把「一句话设想」变成「能上牌桌的卡」。
>
> **Turn a one-sentence idea into a playable Yu-Gi-Oh! DIY card.**
> Fully local, zero build, zero intrusion: structured spec → PSCT card text + Lua
> script → card art (local ComfyUI) → print-grade card image → export to EDOPro / MDPro3.

[![version](https://img.shields.io/badge/version-2.0.0.dev1-D4A017)]()
[![python](https://img.shields.io/badge/python-3.10%2B-3776AB)](https://www.python.org/)
[![platform](https://img.shields.io/badge/platform-Windows%20·%20macOS%20·%20Linux-555)]()
[![deps](https://img.shields.io/badge/core-deps%20free-brightgreen)]()
[![build](https://img.shields.io/badge/build-not%20needed-brightgreen)]()

---

## English (TL;DR)

CardForge is a **fully-local workshop** for designing Yu-Gi-Oh! proxy/DIY cards that
actually work at the table:

```
structured spec ─→ PSCT card text + Lua script ─→ card art + frame/rarity composite ─→ EDOPro / MDPro3 export
      │                    │                             │                                   │
 balance audit G1    38-rule PSCT linter          local ComfyUI · 25 rarities         expansions pkg · .ypk
                     G2 static check              6 extended-art treatments           .ydk · one-click install
                     G3 real-duel verify          10 languages                        G5 export self-check
```

- **17 card frames · 25 rarities · 6 extended-art treatments · 10 languages**
- **Deterministic quality gates G1–G5** — including *actually playing a duel* (G3)
  against the real `ocgcore` engine, with scenario assertions, not just "it didn't crash".
- **LLM is optional and only ever *proposes*.** Every verdict (lint issues, gate
  results, counts) comes from deterministic code; a model's self-assessment is never trusted.
- **Four capability tiers (L0–L3)**: whatever is missing degrades honestly and loudly —
  nothing ever blocks the main pipeline, and nothing ever fakes a pass.
- Ships as a **self-contained Windows build** (`tools/build_exe.py`) — no Python needed
  on target machines.

Quick start: double-click `启动.bat`, or `python -m cardforge launch`.
Full tutorial (Chinese): [docs/05-使用教学.md](docs/05-使用教学.md)

---

## 30 秒开始

```powershell
# Windows：双击 启动.bat，或
python -m cardforge doctor                    # 环境自检（先跑这个）
python -m cardforge launch                    # 一键启动：自检 → 起服务 → 开浏览器（带进度条）
python -m cardforge serve                     # 只起服务（不带自检与进度条）
python -m cardforge update                    # 检查 GitHub 上的新版本（走 api.github.com）
python -m cardforge render --demo --rarity prismatic_secret --fullart overframe
```

> 启动行为：`启动.bat` / `start.sh` 走 `cardforge launch` —— **终端里有真实进度条**
> （自检 12 项逐项推进 → 端口绑定 → 服务就绪 → 打开浏览器），页面加载时也有一条
> 对应的启动进度面板。就绪后才开浏览器；已在跑的实例会被直接复用；
> 8790 被别的程序占用时自动顺延端口（+1…+9）。
>
> 进度条开关：`CARDFORGE_NO_PROGRESS=1` 关掉（串日志 / CI 用）、
> `CARDFORGE_PROGRESS=1` 强制打开（重定向到文件时也想看条）。
>
> ⚠ **`启动.bat` 请保持「纯 ASCII + CRLF」**，不要往里面加中文、也不要让编辑器
> 改它的换行符：cmd 会用当前代码页（中文版是 GBK）逐行解码批处理文件，
> 里面的 UTF-8 中文会错位并**吞掉下一行命令** —— 典型症状是双击后窗口一闪、
> 什么都不发生（见 `docs/03` 缺陷 #31）。中文提示统一由 `cardforge launch` 打印。
> 仓库已用 `.gitattributes` 把 `*.bat` 钉为 CRLF。

```bash
# macOS / Linux
./start.sh doctor
./start.sh render --demo
./start.sh serve
```

只要机器上有 **Python 3.10+**，就能跑起来。没有 pip 包也能跑核心功能。

### 在另一台电脑上第一次运行

`启动.bat` 会**真的逐个试跑**候选解释器（`py -3.13…3.10`、`.venv`、PATH、常见安装
目录），而不是只看 `where` 找没找到名字。这条规则来自缺陷 #36：有些电脑的
`where python` 能命中 Windows 自带的「应用执行别名」，但那个空壳根本启动不了——
旧版启动器在这里直接退出，屏幕上只剩一句
`The system cannot execute the specified program.`。

| 情况 | 现在的行为 |
|---|---|
| 有可用的 Python 3.10+ | 打印解释器与版本后正常启动：`Using Python 3.13.x [py -3.13]` |
| PATH 命中的是坏别名，但别处装了 Python | 跳过坏的，自动改用装好的那个（venv / py / 常见目录） |
| 完全没装，或只有 3.9 及以下 | 说明具体原因，并调起**双语安装助手**：自动装 Python 3.12（用户级、无需管理员；国内镜像 + 官方 MD5/签名校验），或打开 python.org 下载页 |
| 有 Python 但缺 Pillow | 首次启动问一句要不要自动装（`CARDFORGE_NO_PIP=1` 可关） |

手动兜底：从 [python.org](https://www.python.org/downloads/windows/) 装 3.10+ 并勾选
**Add python.exe to PATH**；便携版 / conda 用 `set CARDFORGE_PYTHON=D:\python\python.exe`
指定解释器，启动器会优先试它。macOS / Linux 的 `start.sh` 遵循同一套规则。

---

## 它能做什么

| 能力 | 说明 | 依赖层级 |
|---|---|---|
| **造卡** | 全部 17 种卡种（通常/效果/仪式/融合/同步/超量/连接/灵摆×6/魔法/陷阱/衍生物/技能卡） | L0 |
| **召唤条件** | 融合/同步/超量/连接/仪式的素材行、召唤限制与素材锁定：结构化填写 → 卡文第一段与 Lua `AddProc*` / `SPSUMMON_CONDITION` 同源生成；**一段素材可叠多个筛选**（官方「包含「六武众」怪兽的战士族怪兽2只」）；**额外召唤方法**＝接触召唤 ● 条目 → `Fusion.AddContactProc`（已在真 ocgcore 里跑通）；卡名一键解析卡号；缺信息时宁可写「需人工补写」也不放行任意素材 | L0 |
| **出框卡** | **6 档：标准 + 官方超框（Overframe / 超框卡）+ 4 个 DIY**（出血出框 / 全画 / 灵摆出框 / **主体出框**；旧「超框」档已并入官方超框，枚举保留为兼容别名）。官方档照 2026 官方商品样张：插画铺满内框、最外框保留；无名条，卡名/星级/属性浮于画上；类型行贴正文上方、随半透明面板（金边/投影）一起包进来，魔陷卡种标签在类型行右侧；正文统一墨色（不做 PSCT 加粗）；卡号在面板外、密码隐藏；版权行上方截断。DIY 档本轮已按同一套排版精修：全画档真正铺满整卡（卡框 55% 叠回）、出血档类型行/卡号/密码自适应对比、怪物不再回贴空的卡种标签条、箔纸闪膜跟随实际插画矩形；标准档仍叠官方实测的**卡图窗斜切框**（框侧暗部渐变 → 窗沿暗线 → 钢色带 → 亮发丝 → 画面内圈过渡，四角 45° 斜接） | L1 |
| **25 种罕贵** | 声明式「五层可叠加」模型 + 19 种闪膜花纹。**不该闪的地方不闪**（文本框与卡图按罕贵分别定义） | L1 |
| **10 种语言** | 简中 / 繁中 / 日 / 英 / 韩 / 德 / 法 / 意 / 葡 / 西。术语与句式来自官方数据库，**不逐词直译** | L0 |
| **PSCT 卡文** | 结构化效果 → 规范卡文；确定性 Linter 按官方规则逐条检查（**39 条规则**，覆盖调研报告 §E2 全部硬性错误，含素材行位置、效果处理位置、内置特召来源括号、HERO 字段大小写）。**零 AI 的「整理为标准文本」**：手写文本逐段整理成官方句式，表层归一永远安全、整段重写要过「再反解 IR 等价 + 数值保真 + 卡名保真」三道守卫，认不出的原样保留，**只报术语不动手替换** | L0 |
| **Lua 脚本** | 模板化生成 + 静态门（语法 / UTF-8 无 BOM / API 存在性 / Stringid↔texts 同步） | L0 |
| **本地出图** | 对接本机 ComfyUI，自动探测可用模型并适配参数；单张 / **分层（背景 + 主体两次生成，主体自动抠底）** / 系列一致性 / 风格参考。**12 套正统卡图模板**（只借结构不借设定），按卡的种族/属性/卡种排序，可自存为「我的模板」。**提示词口径跟着文本编码器走**：Qwen 系编码器中文原话直送，英文词表 CLIP 才翻译且翻不出来的词如实点名 | L2 |
| **ComfyUI 工作流导出** | 一键导出**可直接导入 ComfyUI** 的 workflow JSON，含使用说明 | L0 |
| **助手「星奏·艾莉娅」** | 立绘陪伴栏（六表情 + 呼吸动效）常驻右栏；气泡把质量门结论与任务进度翻译成人话，三档人格语气实时切换。**无 LLM 时功能不缺失**。抽屉聊天：历史按人格持久化（刷新不丢、切换只换册子）、每条回答带复制/重试、忙碌态可停止（Esc）、答不上来给出口建议、选中卡后「这张卡」问的就是那张卡 | L0 |
| **质量门 G1–G5** | 平衡审计 / 脚本静态检查 / 实跑验证 / 系列一致性 / 导出自检 | L0–L3 |
| **系列圣经** | 「⌘ 系列」面板建/管/审：卡表蓝图（初动·展开·终端·支援·回收五类）、G4 一键审计、缺口可视化。规格页的「所属系列」**实时校验**——填了没有圣经的名字当场提示并可一键创建 | L0 |
| **导出上桌** | **EDOPro**（`expansions/`：cdb + script + pics + strings.conf）+ `.ydk` + 备份式一键安装 | L0 |
| **直接导出卡面** | 一键把成品卡图**直接下载**到本地（不经导出包）：6 档尺寸（EDOPro 421×614 / MDPro3 704×1024 / 分享 813×1185 / 印刷 300·600dpi / 存档 2787×4063）× 3 种格式（JPG/PNG/WebP），可放大；多尺寸自动打包 zip | L0 |
| **MDPro3 / MDPro4** | 导出 `.ypk` 扩展卡包（Unity 客户端，布局与 EDOPro 完全不同）、自动探测本机客户端、**卡号撞车检查** | L0 |
| **AI 起草卡文（可选）** | 「AI 起草」按钮：大模型按 PSCT 约束一次性提议草稿，**问题清单与门结论全部由内核校验器产出**（LLM 只提议、不裁决，它在文本里的自评一律不采信）。没配大模型时按钮诚实降级并给配置入口 | 可选 |

---

## 四层能力（"各个电脑都能用"的落地方式）

缺哪层就降级到哪层，**没有任何一层会阻断主流程**：

| 层 | 需要什么 | 提供什么 | 缺失时的降级 |
|---|---|---|---|
| **L0 必需** | Python 3.10+ | 全部数据 / 文本 / Lua / 导出 / UI / PSCT 校验 | — |
| **L1 渲染** | Pillow | 卡面 PNG 合成、罕贵、出框、打印级导出 | 浏览器端矢量卡面预览仍可用 |
| **L2 出图** | 本地 ComfyUI + 模型 | 卡图生成、系列一致性、界面素材 | 保留「上传自己的图」通路 |
| **L3 对局** | ocgcore 原生库 | 场景单测 + 整局实跑验证 | **降级为静态 Lua 校验并明确标注** |

`cardforge doctor` 会明确报告当前处于哪一层。

### 对局引擎（本仓库有意不含）

`vendor/engine/ocgcore.dll` 约 195MB，**超过 GitHub 单文件 100MB 上限，故不入库**。
需要 G3 实跑验证时三选一：

1. 装了 **EDOPro** 就不用管——`doctor` 会扫描候选位置自动找到它自带的库；
2. 从 [ProjectIgnition](https://github.com/ProjectIgnition) 的发行版取 `ocgcore.dll`，
   放进 `vendor/engine/`；
3. 设环境变量 `CARDFORGE_OCGCORE=<完整路径>`。

没有引擎时 L3 如实降级为静态校验，其余功能不受任何影响。

---

## 接入大模型（可选）

内核**不依赖任何大模型**：PSCT 校验、Lua 生成、质量门 G1–G5 全是确定性代码。
大模型只在一处参与——「AI 起草卡文」，而且只处于**提议**位置：

```
概念描述（+ 可选当前卡规格）
   → 约束提示词（11 条，与 content/psct/rules.py 的 LINT_RULES 一一对应）
   → LLM 一次性起草
   → 内核 lint_text（+ G1）出问题清单与门结论
   → { 草稿（提议）, issues / counts / gate（内核裁决） }
```

**红线**：草稿文字里的「已符合 PSCT，没有任何问题」这类自评**不回传、不影响裁决**；
审计 G1 的对象是**卡规格**而不是草稿文字，字段里明说。

配置（三界面通用，任选其一）：

```powershell
cardforge llm preset lmstudio        # 一键接本机 LM Studio（127.0.0.1:1234）
cardforge llm preset ollama          # 一键接本机 Ollama（11434）
cardforge llm set --name mycloud --base-url https://api.example.com/v1 --api-key sk-... --use
cardforge llm off / cardforge llm use <名字> / cardforge llm list
```

界面顶栏「⚙ 模型」面板做同样的事。配置落在 `workspace/config/llm.json`（含密钥，
**已进 .gitignore，不要提交**）。auto 探测只扫固定候选端口（LM Studio 1234 / Ollama 11434 等），
自定义端点必须显式 `llm set --use` 才能被找到。

**没配大模型时**：`detect_provider` 返回 NullProvider，「AI 起草」与 `cardforge draft`
返回 `ok=false + degraded`，明说「规则通路不做自由起草，不拿模板文本冒充 AI 产物」，
并给出跨界面通用的配置入口提示。规则通路（艾莉娅聊天 / 校验 / 生成）不受任何影响。

CLI 用法：`cardforge draft "这张卡翻转时…" [--card 210000011] [--write] [--no-g1]`
（`--write` 把草稿写回规格的 `text_i18n`；内核报 ERROR 时退出码为 1）。

---

## 打包为独立程序

一条命令打出 **onefolder** 独立程序（双击即用，不需要目标机器装 Python）：

```powershell
# Windows：首次建构建虚拟环境并装依赖（PyInstaller + Pillow + 渲染增强链）
py -3 -m venv .packaging\venv
.packaging\venv\Scripts\python.exe -m pip install pyinstaller Pillow numpy fonttools brotli svglib reportlab pymupdf

# 构建（约 40s，产出 dist\CardForge\，约 216MB）
py -3 tools\build_exe.py

# 可选：带上对决引擎（+198MB，L3 从静态校验升级为真开局）
py -3 tools\build_exe.py --with-engine
```

```bash
# macOS / Linux（venv 解释器在 bin/ 下，其余相同）
python3 -m venv .packaging/venv
.packaging/venv/bin/python -m pip install pyinstaller Pillow numpy fonttools brotli svglib reportlab pymupdf
python3 tools/build_exe.py
```

> 引擎库目前只有 Windows 版（MinGW 构建），所以 `--with-engine` 实际只在 Windows
> 打包时有意义；其他平台照默认打，L3 如实降级。

**包里有什么**：Python 3.13 运行时 + `cardforge/` 全部子模块 + 只读资源
（`web/` 8.8M、`data/` 78M、`vendor/{scripts,decks,data}` 13M，落在 `_internal/`）
+ **exe 同级的 `workspace/` 最小骨架**（两张演示卡 + 星奏系列圣经 + 脚本）
+ **exe 同级的用户文档**（`docs/` 全部五份含使用教学、`research/` 调研报告、
`README.md` 与 ComfyUI 技术调研——交付后可直接打开阅读，不进 `_internal/`）。

**打包后的路径语义**（`core/paths.py` 的 frozen 分支，已被验收）：

| 路径 | 解析到 | 说明 |
|---|---|---|
| 只读资源（data/web/vendor） | `_internal/`（PyInstaller 6 onefolder） | `sys._MEIPASS` 指向它，源码树布局原样复用 |
| 可写工作区 | **exe 同级 `workspace/`** | 首次启动惰性创建；用户的卡不会随临时目录焚毁 |
| 对决引擎 | `_internal/vendor/engine/` | 默认**不打进包**（195M）；`--with-engine` 才带。缺失时 doctor 如实报「检查了候选位置均未找到」并降级为静态校验 |

**无参双击 = launch**：`CardForge.exe` 不带参数时自动走「自检 → 起服务 → 开浏览器」
（与 `启动.bat` 同语义）；也可以传任意子命令，如 `CardForge.exe doctor`、
`CardForge.exe render --demo`。

**关于旧构建与备份**：PyInstaller 的 COLLECT 阶段会先删输出目录再重建，所以
`build_exe.py` 不让它复用同一个 dist 路径——每次构建写到带时间戳的暂存目录
（`.packaging/out/CardForge-<时间戳>/`），旧 `dist/CardForge` 用**重命名**挪到
`.packaging/out/prev-<时间戳>/` 备份，暂存目录再上位。自动路径零删除；
加 `--clean` 可在构建前清备份。

打包后的真机验收（CLI doctor / serve /api/doctor / 演示卡渲染 / 无参 launch）见
`docs/03-实现状态.md` §三-h，脚本在 `_probe/accept_pack.sh`。

---

## 目录结构

```
游戏王DIY设计/
├── cardforge/                 Python 包
│   ├── core/                  领域模型与常量（零依赖）
│   ├── render/                卡面渲染（几何 / 素材 / 字体 / 排版 / 罕贵 / 出框 / 编排）
│   ├── content/               PSCT 卡文 · 效果 DSL · Lua 生成 · 平衡审计
│   ├── art/                   ComfyUI 客户端 · 工作流构造与导出 · 卡图资产库
│   ├── assistant/             星奏·艾莉娅
│   ├── pool/                  .cdb 读写 · 官方卡池查询 · 项目仓库
│   ├── duel/                  对局验证（三层降级）
│   ├── export/                expansions / strings.conf / .ydk / 一键安装
│   ├── pipeline/              质量门 G1–G5 · 三条流水线
│   ├── server/                本地 Web 服务
│   └── cli.py                 命令行内核
├── web/                       零构建前端（原生 ES Modules；含艾莉娅立绘镜像 assets/aria/）
├── data/                      内置数据：卡框素材 / 字体 / 术语表 / 知识库 / Lua API 快照 / 艾莉娅立绘
├── vendor/                    可选：ocgcore 引擎(不入库) / 官方脚本库 / 卡池
├── workspace/                 你的项目数据（卡片 / 系列 / 卡组 / 卡图 / 导出）
├── docs/                      设计文档
├── research/                  调研报告
├── tools/                     辅助脚本（build_exe.py 打包入口 · install_python.ps1 换机装 Python）
├── .packaging/                构建现场：venv / 暂存与备份 out/ / 入口脚本（可安全删除，重建即可）
└── dist/                      打包产物（build_exe.py 生成）
```

---

## 设计文档

| 文档 | 内容 |
|---|---|
| [使用教学](docs/05-使用教学.md) | **从零开始的完整教学**：环境准备 · 界面导览 · 单卡全流程 · 系列全流程 · 功能详解 · 质量门参考 · 排障 |
| [总体设计](docs/01-总体设计.md) | 需求对照 · 四条原则 · 九大模块 · 渲染设计 · 质量门 · 界面 · 里程碑 |
| [模块规格与接口契约](docs/02-模块规格与接口契约.md) | 每个模块的精确函数签名与数据结构 |
| [实现状态](docs/03-实现状态.md) | 真实完成度 · 实测证据 · 缺陷史 · 诚实清单 |
| [官方超框规格](docs/06-官方超框规格.md) | 2026 官方样张的版面实测 · 实现值 · 与 DIY 档的边界 · 验收清单 |
| [星奏·艾莉娅 角色设定](docs/04-星奏艾莉娅-角色设定.md) | 外观规格 · 四状态六表情 · 三档人格 · 台词红线 · 立绘复现方式 |
| [PSCT 与制卡方法论调研](research/PSCT与制卡方法论调研报告.md) | 官方 PSCT 规范全文整理 + 可编码的校验规则清单 |
| [多语言术语表说明](data/lexicons/README.md) | 术语来源 · 可信度分级 · 覆盖率与缺口 |

### 教学视频

| 片子 | 讲什么 | 怎么重出 |
|---|---|---|
| 实战案例 · 圣痕的追迹者 赛拉（5 分 35 秒） | **一条完整链路**：卡组缺什么 → 规格 → 效果 → 卡文 → 39 条规则 → 脚本 → G1/G2/G3 → 卡图（模板 + 提示词对账）→ 卡面 → 上桌 → 复盘。画面里的每个数字都来自系统产物，附 `manifest.json` 逐段对账 | `python -m cardforge serve --port 8790` 后 `python tools/teach_case.py` |
| 召唤条件 · 素材行与接触召唤（约 2 分半） | 额外卡组的召唤条件：素材行 / 召唤限制 / 素材锁定 / 接触召唤，卡文与 Lua 同源 | `python tools/teach_video.py --card 210000021` |

两集共用版式件 `tools/vidkit.py`（片头 chrome / 截图卡 / 文本卡 / SRT / 章节 / ffmpeg 合成），
各自的生成器只负责分镜与取数 —— 改一集不会把另一集的成片改坏。

---

## 关键设计决策（都有据可依）

1. **不做「自然语言 → Lua」直译。** 调研确认公开世界**不存在**可用的此类项目，且 ocgcore Lua API
   没有权威公开文档 —— 直译必然幻觉。因此走 **IR 三段式**：`意图 → EffectSpec → PSCT 卡文 → Lua`，
   卡文与脚本都是 IR 的确定性投影。
2. **质量门全部是确定性代码。** AI 只在"表达层"参与（艾莉娅把结论翻译成人话），
   **绝不参与裁决** —— 质量门必须可复现、可验证。
3. **罕贵是「五层可叠加」而不是"整卡叠一张图"。** 官方的罕贵可分别作用于卡名 / 卡图 / 属性符号 /
   等级星 / 文本框边框 / 卡框，所以必须分区实现。
4. **出框是「设计处理」而不是罕贵度**（官方日文 オーバーフレーム / 英文 Extended Art /
   官方中文商品名「超框卡」）。2026 官方首发；它与罕贵正交，可任意叠加（社区缩写 OFPSE）。
   官方形态由 `overframe` 档实现，旧 DIY 档另存，不混用。
5. **版面数值靠实测而非硬编码。** 15 种卡框的类型行与文本框位置各不相同，
   `render/frameprobe.py` 在运行时从卡框素材**反推**可用区域，避免"一套坐标套所有框"造成的错位。
6. **多语言不逐词直译。** 日文「〜が発動した時」/「〜を発動した場合」的差别在中英文里无法表达；
   中文与日文官方卡文都**不使用分号**。因此每种语言独立维护句式模板。

---

## 状态

版本 `2.0.0.dev1` —— **需求清单里的九块已全部落地**，含图形界面。
逐模块完成度与**实测证据**见 `docs/03-实现状态.md`（含"仍未闭环的诚实清单"——目前为空，
全部遗留已闭环）。

四套自测随时可重跑：

```powershell
python tools/smoke.py               # 冒烟 19 项（含召唤条件、接触召唤上桌、界面静态守卫）
python tools/selfcheck_lua.py       # Lua 生成器 335 项断言
python tools/selfcheck_prompt.py    # 卡图提示词保真 106 项断言（含 12 套模板；用户写的词一个字都不许悄悄消失）
python tools/selfcheck_tidy.py      # 卡文整理器 77 项断言（零 AI 整理成标准描述，且不许改坏语义）
python tools/selfcheck_assistant.py # 艾莉娅 81 项断言（含 AI 起草的「LLM 只提议」不变式）
python tools/e2e_check.py           # 端到端 26 项：规格→卡文→脚本→实跑→渲染→导出→安装预演
```

> 艾莉娅的立绘与表情差分是**本地出图**的（krea2 + BiRefNet 抠底），
> 想重出：`python tools/gen_aria.py --preset all`（需 ComfyUI 在线；生成凭据见
> `data/assets/aria/manifest.json`）。

工作区里 `workspace/cards/星奏/210000011` 是一张**三门全绿**的演示卡：
G1 平衡审计 pass、G2 脚本静态检查 pass、**G3 真开了一局 38 回合的对局并 pass**。
打开界面就能看到它。

> 中文 Windows 上如果 `python -m cardforge doctor` 报
> `'gbk' codec can't encode character '✓'`：那是**旧版本**的控制台编码问题，
> 已由 `cardforge/core/console.py` 修掉（自动切 UTF-8 代码页 + 安全写入）。
> 双击 `启动.bat` 即可，不需要额外配置。

---

## 免责声明（Disclaimer）

- 本项目是**非官方个人学习/研究工具**，与 Konami、Studio Dice 无任何关联。
  游戏王 / Yu-Gi-Oh! 及相关卡名、卡面美术、官方字体均为 **Konami 的商标与版权物**。
- 卡框与图标素材来自 [kooriookami/yugioh-card](https://github.com/kooriookami/yugioh-card)（**MIT**），
  署名义务由 `data/assets/NOTICE.txt` 承担；但卡框**设计本身**是 Konami 的美术。
- 内置的官方字体复刻件（`data/assets/ygo-*.ttf/woff2`）仅供本地预览。
  **生成的卡面用于任何商业发行前，请替换为 OFL 字体**：Cinzel、EB Garamond、
  思源宋体、霞鹜文楷（LXGW WenKai）、Noto Serif KR，并自行评估卡框美术的版权边界。
  `doctor` 会报告当前用的是哪一层字体。
- 内置官方卡池（`vendor/data/cards_zh.cdb`）仅用于查重与撞号检查，
  **程序永不写入它**（sha256 前后一致已被验收）。
- 出图模型的授权差异极大（animagine / qwen_image 可商用；pony 等禁止商业化），
  选型前请看 `cardforge/art/profiles.py` 各档案的 `notes`。

## 致谢（Acknowledgements)

- [kooriookami/yugioh-card](https://github.com/kooriookami/yugioh-card) — 卡框与图标素材（MIT）
- [ProjectIgnition（EDOPro）](https://github.com/ProjectIgnition) 与 ygopro 生态 — ocgcore 引擎与脚本约定
- [Yugipedia](https://yugipedia.jp/) 整理的官方 PSCT 规范 — 校验规则的语料来源
- OFL 字体社区 — Cinzel / EB Garamond / 思源宋体 / 霞鹜文楷 / Noto Serif KR

## 环境变量（可选）

| 变量 | 作用 |
|---|---|
| `CARDFORGE_WORKSPACE` | 覆盖工作区目录 |
| `CARDFORGE_DATA` | 覆盖内置数据目录 |
| `CARDFORGE_VENDOR` | 覆盖 vendor（引擎/脚本库/卡池）目录 |
| `CARDFORGE_OCGCORE` | 直接指定 ocgcore 原生库路径 |
| `CARDFORGE_PYTHON` | 直接指定启动用的 `python.exe`（便携版 / conda 常用） |
| `CARDFORGE_NO_PIP` | `1` = 启动时不要提示自动安装 Pillow |
