# 本地 ComfyUI 批量生成游戏王 DIY 卡图 —— 技术调研报告

> 调研时间：2026 年。所有接口规格以 ComfyUI 官方文档 + 节点文档为准；标注「未验证」的条目表示本次调研未能取得一手可验证来源。

## 0. 结论速览（TL;DR）

| 问题 | 结论 |
|---|---|
| 调用入口 | `POST http://127.0.0.1:8188/prompt`，body 为 `{prompt, client_id, extra_data}` |
| 结果获取 | 首选 WebSocket `ws://127.0.0.1:8188/ws?clientId=<uuid>`，收到 `executing` 且 `node: null` 即完成；再用 `GET /history/{prompt_id}` 拿文件名 |
| 拿文件 | `GET /view?filename=&subfolder=&type=output` |
| 模型探测 | `GET /object_info/CheckpointLoaderSimple` 取 `input.required.ckpt_name[0]` 数组即 checkpoint 列表 |
| 最大坑 | `class_type` 是**节点注册类名**不是 UI 显示名；`seed` 不变时结果完全一致；API 格式 ≠ UI 保存格式 |
| 推荐底模 | Illustrious-XL 系（含 WAI / NoobAI）> Animagine XL 4.0 > Pony V6 XL（授权受限）> SD1.5 系兜底 |
| 卡图分辨率 | 生成 `832×1216`（最接近卡图窗口比例）→ 4x 放大 → 降采样到 `842×1228`（421×614 的 2×） |

---

# A. ComfyUI 的程序化调用接口

## A.1 HTTP API

Base URL 默认 `http://127.0.0.1:8188`。**所有端点都支持可选的 `/api` 前缀**（`/prompt` 与 `/api/prompt` 等价）。
来源：[REST API Overview](https://mintlify.wiki/Comfy-Org/ComfyUI/api/overview)

### A.1.1 `POST /prompt` —— 提交任务

请求体字段（来源：[POST /prompt](https://mintlify.wiki/Comfy-Org/ComfyUI/api/prompt)）：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `prompt` | object | ✅ | API 格式工作流，key 为节点 id，value 为 `{class_type, inputs}` |
| `prompt_id` | string | ❌ | 自定义 id；不传则自动生成 UUID |
| `client_id` | string | ❌ | 用于 WebSocket 追踪；**会被自动写入 `extra_data`** |
| `number` | number | ❌ | 指定队列位置 |
| `front` | boolean | ❌ | `true` 插队到队首；仅在未指定 `number` 时生效 |
| `extra_data` | object | ❌ | 元数据。子字段：`client_id`、`api_key_comfy_org`（API 节点用） |
| `partial_execution_targets` | array | ❌ | 只执行指定节点及其依赖（**部分执行，对「只重跑采样」很有用**） |

**可直接使用的请求示例**（单角色卡图，SDXL 系）：

```json
{
  "prompt": {
    "1": { "class_type": "CheckpointLoaderSimple",
           "inputs": { "ckpt_name": "wai-illustrious-sdxl-v17.safetensors" } },
    "2": { "class_type": "CLIPTextEncode",
           "inputs": { "text": "masterpiece, best quality, amazing quality, 1boy, solo, dragon, glowing, yugioh monster, duel monster, full body, centered, dramatic lighting",
                       "clip": ["1", 1] } },
    "3": { "class_type": "CLIPTextEncode",
           "inputs": { "text": "lowres, worst quality, low quality, text, watermark, signature, username, border, frame, multiple views, 2girls",
                       "clip": ["1", 1] } },
    "4": { "class_type": "EmptyLatentImage",
           "inputs": { "width": 832, "height": 1216, "batch_size": 4 } },
    "5": { "class_type": "KSampler",
           "inputs": { "seed": 123456789, "steps": 28, "cfg": 5.0,
                       "sampler_name": "euler_ancestral", "scheduler": "normal",
                       "denoise": 1.0,
                       "model": ["1", 0], "positive": ["2", 0],
                       "negative": ["3", 0], "latent_image": ["4", 0] } },
    "6": { "class_type": "VAEDecode",
           "inputs": { "samples": ["5", 0], "vae": ["1", 2] } },
    "7": { "class_type": "SaveImage",
           "inputs": { "filename_prefix": "ygo/card", "images": ["6", 0] } }
  },
  "client_id": "ygo-batch-01",
  "extra_data": { "client_id": "ygo-batch-01" }
}
```

成功响应：

```json
{ "prompt_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890", "number": 42, "node_errors": {} }
```

失败响应（`400`，**必须解析 `node_errors`，它精确指出哪个节点哪个参数缺失**）：

```json
{
  "error": { "type": "invalid_prompt", "message": "Missing required input",
             "details": "Node 3 is missing required input: model", "extra_info": {} },
  "node_errors": {
    "3": { "errors": [ { "type": "required", "message": "Required input is missing", "details": "model" } ],
           "dependent_outputs": ["8", "9"], "class_type": "KSampler" }
  }
}
```

> ⚠️ 本地未开 CORS 时有同源校验（防 CSRF）。跨源需启动时加 `--enable-cors-header`。

### A.1.2 `GET /history` 与 `GET /history/{prompt_id}` —— 取结果

来源：[GET /history](https://mintlify.wiki/Comfy-Org/ComfyUI/api/history)

- `GET /history?max_items=20&offset=0` —— 分页取全部
- `GET /history/{prompt_id}` —— 取单个

响应结构（key 为 `prompt_id`）：

```json
{
  "<prompt_id>": {
    "prompt": [42, "<prompt_id>", { /* workflow */ }, { "client_id": "...", "create_time": 1709596800000 }, ["9"]],
    "outputs": {
      "9": { "images": [ { "filename": "card_00001_.png", "subfolder": "ygo", "type": "output" } ] }
    },
    "status": { "status_str": "success", "completed": true, "messages": [] }
  }
}
```

关键点：
- `outputs` 是 **`节点id -> {images:[{filename, subfolder, type}]}`**。只有 `SaveImage` / `PreviewImage` 这类输出节点会出现在这里。
- `status.status_str` 取值 `success` / `error`；`status.messages` 内含错误详情。
- **历史存在内存里，服务重启即清空**。批量任务要自己落盘记录。
- 清理：`POST /history` + `{"clear": true}` 或 `{"delete": ["id1","id2"]}`。

### A.1.3 `GET /view` —— 下载图片

来源：[history 文档「Retrieving Generated Images」](https://mintlify.wiki/Comfy-Org/ComfyUI/api/history)

```
GET /view?filename=card_00001_.png&subfolder=ygo&type=output
```

| 参数 | 说明 |
|---|---|
| `filename` | 来自 history 的 `filename`，**必须 URL-encode** |
| `subfolder` | 来自 history 的 `subfolder`；无子目录时为空串 `""` |
| `type` | `output` / `temp` / `input`。`SaveImage` → `output`；`PreviewImage` → `temp` |

> `SaveImage` 的 `filename_prefix` 支持路径与变量：写 `ygo/card` 会存到 `output/ygo/card_00001_.png`；支持 `%date:yyyy-MM-dd%`、`%Empty Latent Image.width%`、`%batch_num%` 等格式化 token。来源：[Save Image 节点文档](https://comfy.icu/node/SaveImage)

### A.1.4 队列控制

来源：[Queue Management](https://mintlify.wiki/Comfy-Org/ComfyUI/api/queue)

| 方法 | 端点 | 说明 |
|---|---|---|
| `GET` | `/queue` | 返回 `{queue_running: [...], queue_pending: [...]}`，每项是数组 `[number, prompt_id, workflow, extra_data, outputs_to_execute]` |
| `POST` | `/queue` | `{"clear": true}` 清空待执行；`{"delete": ["prompt_id"]}` 删指定项 |
| `GET` | `/prompt` | 返回 `{"exec_info": {"queue_remaining": 5}}`，**最轻量的存活/负载探测** |
| `POST` | `/interrupt` | `{}` 全局打断；`{"prompt_id": "..."}` 只打断该任务 |
| `POST` | `/free` | `{"unload_models": true, "free_memory": true}` 释放显存（批量任务之间调用可防 OOM） |

> 注意：`/queue` 的 **running 任务无法删除，只能用 `/interrupt` 打断**。

### A.1.5 `GET /object_info` —— 能力探测（零配置方案的核心）

`GET /object_info` 返回**服务端所有已注册节点的完整 schema**，`GET /object_info/{class_type}` 取单个节点。

利用它做三件事：

1. **判断 ComfyUI 是否在跑**：能拿到 200 即存活。
2. **列出可用 checkpoint / lora**（不需要单独的 `/models` 端点）：
   ```
   GET /object_info/CheckpointLoaderSimple
   → { "CheckpointLoaderSimple": { "input": { "required": { "ckpt_name": [ ["a.safetensors","b.safetensors"], {...} ] } }, ... } }
   ```
   `input.required.<参数名>[0]` 就是该 COMBO 的**候选字符串数组**。同理：
   - LoRA 列表 → `/object_info/LoraLoader` 的 `lora_name`
   - VAE 列表 → `/object_info/VAELoader` 的 `vae_name`
   - ControlNet 列表 → `/object_info/ControlNetLoader` 的 `control_net_name`
   - 放大模型列表 → `/object_info/UpscaleModelLoader` 的 `model_name`
   - **input 目录里的图片** → `/object_info/LoadImage` 的 `image`
3. **判断某个自定义节点是否装了**：查 `/object_info/IPAdapterAdvanced` 是否 404 / key 缺失。

schema 结构（`input` 下分 `required` / `optional`，每项是 `[类型或候选数组, 选项字典]`）：

```json
{
  "KSampler": {
    "input": {
      "required": {
        "model": ["MODEL"],
        "seed":  ["INT", { "default": 0, "min": 0, "max": 18446744073709551615 }],
        "cfg":   ["FLOAT", { "default": 8.0, "min": 0.0, "max": 100.0 }],
        "sampler_name": [["euler","euler_ancestral","dpmpp_2m","..."], {}]
      }
    },
    "output": ["LATENT"],
    "output_name": ["LATENT"],
    "category": "sampling",
    "output_node": false
  }
}
```

> **这是「自适应选模型」和「自适应填参数」的唯一正确数据源**——不要硬编码枚举值，运行时从 `/object_info` 读。

### A.1.6 其他端点

- `POST /upload/image` —— 上传参考图到 `input/`（multipart：`image` 文件 + `overwrite` 字段），返回 `{name, subfolder, type}`，随后 `LoadImage` 的 `image` 填返回的 `name`。
- `GET /models` 与 `GET /models/{folder}` —— 列出模型文件夹与文件。**未验证**：本次调研未取得这两个端点在自托管版的一手文档，建议优先用 `/object_info` 方案（已验证）。

### A.1.7 轮询 vs 订阅

| 方案 | 做法 | 适用 |
|---|---|---|
| 纯 HTTP 轮询 | `POST /prompt` → 循环 `GET /history/{prompt_id}`，直到出现该 key 且 `status.completed == true` | 最简单，无额外依赖；**建议 1–2s 间隔 + 总超时** |
| WebSocket 订阅 | 连 `/ws`，等 `executing` 且 `node == null` → 再 `GET /history/{prompt_id}` | **推荐**。能拿实时进度百分比、预览图、精确错误 |

轮询要注意：`/history` 里**任务完成前不会有该 `prompt_id` 的 key**，所以「key 不存在」= 仍在队列/执行中，不是错误。要区分「排队中」和「卡死」，需配合 `GET /prompt` 的 `queue_remaining` 或 WebSocket 心跳。

---

## A.2 WebSocket API

连接：`ws://127.0.0.1:8188/ws?clientId=<uuid>`
来源：[WebSocket API Overview](https://mintlify.wiki/Comfy-Org/ComfyUI/api/websocket-overview)、[WebSocket Events](https://mintlify.wiki/Comfy-Org/ComfyUI/api/websocket-events)

- 必须用**同一个 `clientId`** 同时用于 WS 连接和 `POST /prompt` 的 `client_id`，否则无法对应。
- 同一 `clientId` 重连时，服务端会**踢掉旧连接**（保证单一连接）。
- **未提供 `clientId` 时服务端会自动生成**，但那样你就无法在提交时指定了，所以始终自己生成。

### A.2.1 JSON 消息类型

所有消息形如 `{"type": "...", "data": {...}}`。

| `type` | 关键字段 | 用途 |
|---|---|---|
| `status` | `data.status.exec_info.queue_remaining`；首次连接额外带 `data.sid` | 队列长度；**连接成功握手信号** |
| `execution_start` | `data.prompt_id`（另有 `timestamp`） | 任务开始执行 |
| `executing` | `data.node`（节点 id，或 **`null` 表示全部完成**）、`data.display_node`、`data.prompt_id` | **判断完成的核心依据** |
| `progress` | `data.value` / `data.max` / `data.node` / `data.prompt_id` | **进度百分比 = value/max** |
| `executed` | `data.node`、`data.output`（如 `{images:[{filename,subfolder,type}]}`）、`data.prompt_id` | 节点产出；可直接拿文件名 |
| `execution_cached` | `data.nodes`（被缓存跳过的节点 id 数组）、`data.prompt_id` | **告诉你哪些节点没重跑** |
| `execution_error` | `data.prompt_id`、`data.node_id`、`data.exception_message`、`data.exception_type`、`data.traceback` | 精确报错 |
| `execution_interrupted` | `data.prompt_id`、`data.node_id` | 被打断 |
| `execution_success` | `data.prompt_id` | 成功收尾 |
| `feature_flags` | `data.{binary_preview_images, image_metadata, ...}` | 能力协商（可选） |
| `logs` | `data.entries[]`、`data.size` | 需开启日志流 |

> ⚠️ **`execution_cached` / `execution_success` / `execution_start` 的字段名在不同 ComfyUI 版本间有差异**，本次调研中官方 mintlify 文档只对 `status` / `executing` / `executed` / `progress` / `execution_error` 做了带示例的完整记录。**工程上应以 `executing` + `node == null` 作为唯一的完成判据**（这是官方明确担保的语义），其余消息作为增强信息。

### A.2.2 拿「节点进度百分比」

`progress` 消息直接给：

```json
{ "type": "progress", "data": { "value": 15, "max": 20, "prompt_id": "550e8400-...", "node": "3" } }
```

百分比 = `value / max * 100`（上例 75%）。

要换算成**整个工作流的进度**，需要两步：
1. 从 `/object_info` 或预先分析 API 工作流的依赖图，算出「会被执行的非缓存节点」总数 `N`；
2. 用 `executing` 事件累计已完成节点数 `k`，整体进度 ≈ `(k + value/max) / N`。
   （`execution_cached` 里的节点应从 `N` 中排除，否则进度条永远到不了 100%。）

### A.2.3 拿「输出文件名」

两条路，**推荐第二条**：

1. 监听 `executed`，`data.output.images[].filename`（还有 `subfolder` / `type`）。**缺点**：只在你连接期间有效，断线即丢失。
2. 收到 `executing` + `node == null` 后，`GET /history/{prompt_id}`，从 `outputs.<节点id>.images[]` 读取。**优点**：幂等、可重试、可断线恢复。

### A.2.4 二进制消息（预览图）

格式：`[4 字节大端事件类型][数据]`。类型定义在 `protocol.py` 的 `BinaryEventTypes`：

| ID | 名称 | 结构 |
|---|---|---|
| 1 | `PREVIEW_IMAGE` | `[type=1][4B 图片类型][图片数据]`，图片类型 `1`=JPEG `2`=PNG |
| 2 | `UNENCODED_PREVIEW_IMAGE` | 原始未编码数据（少用） |
| 3 | `TEXT` | 二进制文本（少用） |
| 4 | `PREVIEW_IMAGE_WITH_METADATA` | `[type=4][4B metadata 长度][metadata JSON][图片数据]`，metadata 含 `image_type` / `node_id` / `prompt_id` |

⚠️ 二进制消息**没有 JSON 的 `type` 字段**，必须用 `struct.unpack(">I", data[:4])[0]` 判断，否则会把预览图当字符串解析而崩溃。

### A.2.5 完整事件流

```
Client → WS 连接
Server → status (queue_remaining + sid)
Client → POST /prompt          （带同一 client_id）
Server → status (队列更新)
Server → execution_start
Server → executing (node:"3")
Server → progress (5/20)  ...  (20/20)
Server → Binary PREVIEW_IMAGE        （可选）
Server → executed  (node:"3")
Server → execution_cached (nodes:[...])   （若有缓存）
Server → executing (node:"9")
Server → executed  (node:"9", output:{images:[...]})
Server → executing (node: null)      ← 完成信号
Server → status (队列更新)
Client → GET /history/{prompt_id}
```

### A.2.6 可用的优雅处理策略

- **超时**：双层。① 单任务 wall-clock 超时（按分辨率×steps 估算，超时后 `POST /interrupt`）；② 空闲超时（连续 N 秒没收到任何消息 → 判定断线，重连）。
- **错误**：把 `execution_error.data.exception_type` 分类。`ValueError` + 消息含 `seed` → 重试换 seed；含 `not found` → 模型名不存在，回退到另一模型；`torch.cuda.OutOfMemoryError` → 降分辨率/降 batch，并调 `POST /free`。
- **重连**：指数退避 + 复用原 `clientId`；重连后服务端会补发当前 `executing` 节点。
- **断线后恢复**：不要依赖内存状态，用 `/history/{prompt_id}` 查最终结果。

---

## A.3 UI workflow JSON → API "prompt" 格式的转换

来源：[Workflow API Format](https://docs.comfy.org/development/api-development/workflow-api-format)

### A.3.1 两种格式的差异

| | Save 格式（UI 导出） | API 格式（`prompt`） |
|---|---|---|
| 菜单 | `File → Save` / `Ctrl+S` | `File → Export Workflow (API)` |
| 节点键 | `nodes[]` 数组，每项有 `id` | **对象**，key 为节点 id 字符串 |
| 拓扑 | `links[]` 数组单独存放 | **内联为 `[源节点id, 输出槽序号]`** |
| 位置/尺寸/颜色/分组 | 有 | **无**（API 格式省略所有 UI 元数据） |
| 用途 | 前端重新打开 | API 提交 |

### A.3.2 映射规则（核心 4 条）

1. **节点 id → 对象 key**：`nodes[].id`（数字）字符串化为 key。
2. **`class_type` = `nodes[].type`**。⚠️ 这是**注册类名**，不是 UI 上的标题（如 UI 显示 `Load Checkpoint`，`class_type` 是 `CheckpointLoaderSimple`）。用 `/object_info` 校验存在性。
3. **输入的两种来源**：
   - **连线输入** → 找 `links[]` 中 `target_id` 为该节点、`target_slot` 为该输入槽序号的 link，取 `[str(origin_id), origin_slot]`。
   - **控件值（widget）** → 来自 `nodes[].widgets_values`，这是一个**只含值的数组**，**必须按 `inputs[]` 中同名顺序 / 该节点的 widget 声明顺序对齐**。这是整个转换最容易出错的地方：`widgets_values` 不含参数名。
     - 例如 `KSampler` 的 `widgets_values = [seed, "randomize", steps, cfg, "euler", "normal", 1.0]` —— 注意 **`control_after_generate`（"randomize"）夹在 `seed` 后面**，它**不是** API 参数，必须跳过。这是最常见的 off-by-one 来源。
4. **丢弃**：`pos`、`size`、`flags`、`order`、`mode`、`color`、`bgcolor`、`groups`、`extra`、`title`。

### A.3.3 稳妥的实现路线（推荐）

**路线 1（最稳，零转换风险）：直接用 `File → Export Workflow (API)` 导出的 JSON 作为模板。**
把其中的 `ckpt_name` / `text` / `seed` / `width` / `height` 等当成**命名占位符**，用代码按参数名替换。因为 API 格式里的 key 就是参数名，**不存在 widgets_values 对齐问题**。批量生成场景强烈推荐这条。

**路线 2（需要处理用户上传的 UI 格式 JSON 时）：**
- 不要自己硬写转换器去猜 widget 顺序。正确做法是**先调 `/object_info/{class_type}` 拿到该节点的 `input.required` / `input.optional` 的参数名有序列表**，再用它把 `widgets_values` 按序映射到真正的参数名（跳过 `control_after_generate` 这类 UI-only 值）。
- 或者调用**前端自己的导出逻辑**：ComfyUI 前端的 `app.graphToPrompt()` 就是官方转换器；社区做法是写一个浏览器扩展/书签脚本，在页面里调用它并 `console.log` 出 API 格式。

**路线 3（现成工具）：**
- `pydn/ComfyUI-to-Python-Extension` —— 把工作流转成可执行 Python 代码，不是直接转 API JSON，但可作参考。
- MCP 生态里的转换实现（如 `sandraschi/comfyops-mcp` 的 `workflow_utils.py` 做「normalize ComfyUI workflow JSON for API submission」）。
- ⚠️ 本次调研中 GitHub 域名在本环境不可达，上述仓库我**只见到搜索索引层面的一手描述，未逐行核对源码**，标注为**部分未验证**。建议落地时自行 `pip install` 后实测。

### A.3.4 转换后必须做的自检

1. `class_type` 是否都在 `/object_info` 里存在（缺失 = 用户没装该自定义节点）。
2. 所有 `inputs` 里的连线引用 `["id", slot]` 的 `id` 是否真实存在于同一份 prompt 里。
3. `input.required` 里没有默认值的参数是否都给了值（否则 400 + `node_errors`）。
4. `SaveImage` 这类输出节点是否存在且可达（否则任务跑完没有任何产物）。

---

## A.4 常用节点的 `class_type` 与 `inputs` 精确命名

来源：官方节点文档 [Loaders](https://mintlify.wiki/Comfy-Org/ComfyUI/nodes/loaders) / [Conditioning](https://mintlify.wiki/Comfy-Org/ComfyUI/nodes/conditioning) / [Sampling](https://mintlify.wiki/Comfy-Org/ComfyUI/nodes/sampling) / [Latent](https://mintlify.wiki/Comfy-Org/ComfyUI/nodes/latent) / [Image](https://mintlify.wiki/Comfy-Org/ComfyUI/nodes/image)，以及节点级文档站 [comfy.icu](https://comfy.icu/node/KSampler)。

### A.4.1 加载类

| class_type | inputs（必填加粗） | 输出 |
|---|---|---|
| `CheckpointLoaderSimple` | **`ckpt_name`** | `MODEL`(0) `CLIP`(1) `VAE`(2) |
| `LoraLoader` | **`model`** **`clip`** **`lora_name`** `strength_model`(默认1.0, -100~100) `strength_clip`(默认1.0) | `MODEL`(0) `CLIP`(1) |
| `LoraLoaderModelOnly` | **`model`** **`lora_name`** `strength_model` | `MODEL` |
| `VAELoader` | **`vae_name`** | `VAE` |
| `CLIPLoader` | **`clip_name`** **`type`** `device` | `CLIP` |
| `DualCLIPLoader` | **`clip_name1`** **`clip_name2`** **`type`** `device` | `CLIP` |
| `UNETLoader` | **`unet_name`** `weight_dtype`(`default`/`fp8_e4m3fn`/`fp8_e4m3fn_fast`/`fp8_e5m2`) | `MODEL` |
| `ControlNetLoader` | **`control_net_name`** | `CONTROL_NET` |
| `CLIPVisionLoader` | **`clip_name`** | `CLIP_VISION` |
| `UpscaleModelLoader` | **`model_name`** | `UPSCALE_MODEL` |
| `StyleModelLoader` | **`style_model_name`** | `STYLE_MODEL` |

### A.4.2 文本与条件

| class_type | inputs |
|---|---|
| `CLIPTextEncode` | **`text`** **`clip`** → `CONDITIONING` |
| `CLIPSetLastLayer` | **`clip`** `stop_at_clip_layer`（默认 `-1`，范围 -24~-1；**SD1.5 动漫模型常设 `-2`**）→ `CLIP` |
| `ConditioningCombine` | **`conditioning_1`** **`conditioning_2`** |
| `ConditioningAverage` | **`conditioning_to`** **`conditioning_from`** `conditioning_to_strength` |
| `ConditioningSetArea` | **`conditioning`** `width` `height` `x` `y` `strength` |
| `ConditioningSetAreaPercentage` | **`conditioning`** `width` `height` `x` `y` `strength`（均为 0~1 比例） |
| `ConditioningSetMask` | **`conditioning`** **`mask`** `strength` `set_cond_area`(`default`/`mask bounds`) |
| `ConditioningSetTimestepRange` | **`conditioning`** `start` `end`（0~1，做提示词分段调度） |
| `ConditioningZeroOut` | **`conditioning`** |
| `CLIPVisionEncode` | **`clip_vision`** **`image`** `crop`(`center`/`none`) → `CLIP_VISION_OUTPUT` |
| `unCLIPConditioning` | **`conditioning`** **`clip_vision_output`** `strength` `noise_augmentation` |
| `StyleModelApply` | **`conditioning`** **`style_model`** **`clip_vision_output`** `strength` `strength_type`(`multiply`/`attn_bias`) |

### A.4.3 ControlNet（核心节点）

| class_type | inputs |
|---|---|
| `ControlNetApplyAdvanced` | **`positive`** **`negative`** **`control_net`** **`image`** `strength`(1.0, 0~10) `start_percent`(0.0) `end_percent`(1.0) `vae`(可选) → `positive`, `negative` |
| `ControlNetApply` | ⚠️ **已弃用**，无 `start_percent`/`end_percent`。新工作流一律用 Advanced |

> 实测经验（来自 [comfy.icu 节点说明](https://comfy.icu/node/ControlNetApplyAdvanced)）：SD 时代 ControlNet 用 `strength 0.3~0.7` 松引导 / `0.8~1.2` 严格；**2025-26 的 union ControlNet 反而要用 0.65~0.8，1.0 会「过熟」**。`start_percent=0, end_percent=0.5` 是「只锁构图、后期交给模型」的经典配方。
> `vae` 输入只对需要把 hint 编码到 latent 空间的新式 ControlNet 有意义，SD1.5/SDXL 像素空间 ControlNet 用不上。

### A.4.4 采样与潜空间

| class_type | inputs |
|---|---|
| `KSampler` | **`model`** **`seed`** **`steps`** **`cfg`** **`sampler_name`** **`scheduler`** **`positive`** **`negative`** **`latent_image`** `denoise`(1.0) |
| `KSamplerAdvanced` | **`model`** `add_noise`(`enable`/`disable`) **`noise_seed`** `steps` `cfg` `sampler_name` `scheduler` `positive` `negative` `latent_image` `start_at_step`(0) `end_at_step`(10000) `return_with_leftover_noise`(`disable`/`enable`) |
| `EmptyLatentImage` | `width`(512) `height`(512) `batch_size`(1) |
| `VAEEncode` | **`pixels`** **`vae`** |
| `VAEDecode` | **`samples`** **`vae`** |
| `VAEEncodeForInpaint` | **`pixels`** **`vae`** **`mask`** `grow_mask_by`(6) |
| `VAEEncodeTiled` | **`pixels`** **`vae`** `tile_size`(512) `overlap`(64) `temporal_size` `temporal_overlap` |
| `VAEDecodeTiled` | **`samples`** **`vae`** `tile_size` `overlap` `temporal_size` `temporal_overlap` |
| `SetLatentNoiseMask` | **`samples`** **`mask`** → `LATENT`（白=重绘，黑=保留） |
| `LatentUpscale` | **`samples`** **`upscale_method`**(`nearest-exact`/`bilinear`/`area`/`bicubic`/`bislerp`) `width` `height` `crop`(`disabled`/`center`) |
| `LatentUpscaleBy` | **`samples`** **`upscale_method`** `scale_by`(1.5) |
| `LatentCrop` | **`samples`** `width` `height` `x` `y` |
| `LatentComposite` | **`samples_to`** **`samples_from`** `x` `y` `feather` |
| `InpaintModelConditioning` | **`positive`** **`negative`** **`vae`** **`pixels`** **`mask`** `noise_mask`(true) → `positive`, `negative`, `latent` |

> ⚠️ **`KSamplerAdvanced` 没有 `return_with_leftover_noise` 以外的 `denoise`**；且 `start_at_step` 是相对**本节点自己的 `steps`**，不是上一个采样器。两段式采样最常见的 bug 就是这里（[来源](https://comfy.icu/node/KSamplerAdvanced)）。

### A.4.5 图像处理

| class_type | inputs |
|---|---|
| `LoadImage` | **`image`** → `IMAGE`(0) `MASK`(1)。MASK 来自 **alpha 通道取反**（`1 - alpha`），无 alpha 时全黑 |
| `LoadImageMask` | **`image`** **`channel`**(`alpha`/`red`/`green`/`blue`) → `MASK` |
| `SaveImage` | **`images`** `filename_prefix`(默认 `ComfyUI`)。**会把完整 workflow 写进 PNG 元数据** |
| `PreviewImage` | **`images`**（存 `temp/`，重启即删） |
| `ImageScale` | **`image`** **`upscale_method`**(`nearest-exact`/`bilinear`/`area`/`bicubic`/`lanczos`) `width`(512) `height`(512) `crop`(`disabled`/`center`)。**`width=0` 或 `height=0` 时按另一维等比推算**（等比缩放的正确姿势） |
| `ImageScaleBy` | **`image`** **`upscale_method`** `scale_by`(1.0, 0.01~8.0) |
| `ImageUpscaleWithModel` | **`upscale_model`** **`image`** → `IMAGE`。**缩放倍率由模型固定决定（通常 4x），本节点不能指定目标尺寸** |
| `ImagePadForOutpaint` | **`image`** `left` `top` `right` `bottom`(step 8) `feathering`(40) → `IMAGE`, `MASK` |
| `EmptyImage` | `width` `height` `batch_size` `color` |
| `ImageInvert` | **`image`** |

### A.4.6 插件节点（一致性用）

**ComfyUI_IPAdapter_plus**（[GitHub](https://github.com/cubiq/ComfyUI_IPAdapter_plus)，[节点文档](https://uinodes.com/plugins/ComfyUI_IPAdapter_plus)）

| class_type | 说明 |
|---|---|
| `IPAdapterUnifiedLoader` | inputs: **`model`** `ipadapter`(可选)；控件 **`preset`**；outputs: `model`, `ipadapter` |
| `IPAdapterAdvanced` | inputs: **`model`** **`ipadapter`** **`image`** `image_negative` `attn_mask` `clip_vision`；控件 `weight`(-1~5) `weight_type` `combine_embeds` `start_at`(0~1,默认0) `end_at`(默认1) `embeds_scaling` |
| `IPAdapter` | 简版，`IPAdapterAdvanced` 是其超集（控制参数取默认时两者结果一致） |
| `IPAdapterFaceID` / `IPAdapterUnifiedLoaderFaceID` | 人脸身份，需额外 LoRA |
| `IPAdapterEncoder` / `IPAdapterEmbeds` / `IPAdapterCombineEmbeds` / `IPAdapterCombineWeights` | 多参考图融合、embedding 复用 |
| `IPAdapterStyleComposition` | SDXL 专用，风格与构图分离加权 |
| `IPAdapterTiled` | 大幅面平铺 |
| `IPAdapterMS`（Mad Scientist） | 逐层权重微调 |
| `PrepImageForClipVision` | 参考图预处理（`interpolation` / `crop_position` / `sharpening`） |

`IPAdapterUnifiedLoader` 的 `preset` 取值与限制（[来源](https://uinodes.com/plugins/ComfyUI_IPAdapter_plus/IPAdapterUnifiedLoader)）：
`LIGHT`（**SD1.5 only**，低强度省显存）、`STANDARD`（通用中等强度，默认推荐）、`VIT-G`（用 ViT-G 大视觉模型，表达力更强）、`PLUS`（高强度多任务）、`PLUS FACE`（人像）、`FULL FACE`（**SD1.5 only**，人脸还原最强）。
⚠️ **部分 preset 只能用于 SD1.5，用在 SDXL 上会直接报错**——程序化调用时必须根据底模架构选 preset。

`IPAdapterAdvanced` 的 `weight_type` 关键取值：`linear`（线性，默认）、`style transfer`（风格迁移，不改内容）、`composition`（构图迁移）、`strong style transfer`（强风格）、`style and composition`（风格+构图分离加权）；负权重产生反向效果。
`embeds_scaling`：`V only` / `K+V` / `K+V w/ C penalty` / `K+mean(V) w/ C penalty`，推荐 `K+V` 或带 C penalty 的变体。
`combine_embeds`：`concat` / `add` / `subtract` / `average` / `norm average`。

所需模型文件与目录（[来源](https://uinodes.com/plugins/ComfyUI_IPAdapter_plus)）：
- `ComfyUI/models/clip_vision/`：`CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors`（SD1.5/SDXL）、`CLIP-ViT-bigG-14-laion2B-39B-b160k.safetensors`（ViT-G）
- `ComfyUI/models/ipadapter/`：`ip-adapter_sd15.safetensors`、`ip-adapter-plus_sd15.safetensors`、`ip-adapter_sd15_vit-G.safetensors`、`ip-adapter_sdxl_vit-h.safetensors`、`ip-adapter-plus_sdxl_vit-h.safetensors`、`ip-adapter_sdxl.safetensors`、faceid 系列 `.bin`
- `ComfyUI/models/loras/`：`ip-adapter-faceid*_lora.safetensors`
- 官方模型仓库：[h94/IP-Adapter](https://huggingface.co/h94/IP-Adapter)、[h94/IP-Adapter-FaceID](https://huggingface.co/h94/IP-Adapter-FaceID)

**ComfyUI_InstantID**（[GitHub](https://github.com/cubiq/ComfyUI_InstantID)，[节点文档](https://uinodes.com/plugins/ComfyUI_InstantID/ApplyInstantID)）

| class_type | 说明 |
|---|---|
| `InstantIDModelLoader` | 加载 `models/instantid/` 下的 ip_adapter 模型 |
| `InstantIDFaceAnalysis` | 加载 InsightFace（provider 参数） |
| `ApplyInstantID` | inputs: **`instantid`** **`insightface`** **`control_net`** **`image`** **`model`** **`positive`** **`negative`** `image_kps` `mask`；控件 `weight`(默认 **0.8**, 0~5, step 0.01) `start_at`(0.0) `end_at`(1.0)；outputs: `MODEL`, `positive`, `negative` |
| `ApplyInstantIDAdvanced` | 追加 `ip_weight` / `cn_strength` / `noise` / `combine_embeds` 等 |
| `ApplyInstantIDControlNet` | 单独控制 ControlNet 部分 |
| `FaceKeypointsPreprocessor` | 关键点预处理 |
| `InstantIDAttentionPatch` | 底层 attention patch |

> ⚠️ `weight > 1.0` 就会过曝，> 2 基本毁图（[实测记录](https://uinodes.com/plugins/ComfyUI_InstantID/ApplyInstantID)）。
> ⚠️ **InstantID 仅支持 SDXL**。依赖：`models/insightface/models/antelopev2/`（首次运行自动下载，但**会自动解压到嵌套目录 `antelopev2/antelopev2`，必须手工上移一层**——这是极高频的踩坑点）、`models/instantid/`、`models/controlnet/`。

**PuLID**（[GitHub](https://github.com/cubiq/PuLID_ComfyUI)，[节点文档](https://uinodes.com/plugins/pulid_comfyui)）

| class_type | 说明 |
|---|---|
| `PulidModelLoader` | 加载 `models/pulid/` |
| `PulidEvaClipLoader` | 加载 EVA02-CLIP-L-14-336（首次自动下载） |
| `PulidInsightFaceLoader` | 加载 InsightFace |
| `ApplyPulid` | 应用 PuLID |
| `ApplyPulidAdvanced` | 高级参数 |

**Reference-only / Reference Latent**：ComfyUI **核心**提供 `ReferenceOnlySimple`（旧版「Reference-only」）与 2025 年新增的 **`ReferenceLatent`**（配合 Flux Kontext / Qwen-Image-Edit 的参考图条件化）。
> ⚠️ **未验证**：本次调研未能取得这两个节点在官方节点文档中的精确定义页，`class_type` 拼写建议落地时以 `GET /object_info/ReferenceLatent` 实测为准。

---

## A.5 种子 / 批量 / 分辨率 / 采样参数

### A.5.1 种子

- `KSampler.seed` 范围 **0 ~ 18446744073709551615**（uint64）。
- `KSamplerAdvanced` 用 **`noise_seed`**（名字不同！）。
- UI 上的 `control_after_generate`（`fixed` / `increment` / `decrement` / `randomize`）**只是前端行为，不进入 API**。程序化调用时**必须自己每次改 seed**，改为 `fixed` 并保持不变会导致完全相同的输出（这既是坑也是特性——可复现性靠它）。

### A.5.2 批量

三种方式，各有取舍：

| 方式 | 做法 | 优点 | 缺点 |
|---|---|---|---|
| **latent 批** | `EmptyLatentImage.batch_size = N` | 一次采样出 N 张，最快 | **N 张共享同一个 seed 序列但共用一次 CLIP 编码**；显存随 N 线性增长；出错全批失败 |
| **多次提交** | 循环 `POST /prompt`，每次改 seed | 隔离性好，可断点续跑，可精确控制每张参数 | 需要自己管队列 |
| **`RepeatLatentBatch`** | 复制 latent 后采样 | 同 latent 多 seed | 场景特殊 |

> **建议**：批量做卡图用「多次提交 + `/queue` 观察 `queue_remaining`」，把 ComfyUI 当成异步任务队列。一次塞太多容易 OOM 且难以定位单张失败。

### A.5.3 分辨率

- `EmptyLatentImage.width/height` **必须能被 8 整除**（step 8，范围 16~16384），因为 latent 是 1/8 压缩。**不整除会报错或静默取整**。
- SDXL 系请用「训练桶」尺寸，非桶尺寸会明显掉质量、出现重复主体。

### A.5.4 采样参数可选值

`sampler_name`：**44 个可选值**。开头为 `euler`, `euler_cfg_pp`, `euler_ancestral`, `euler_ancestral_cfg_pp`, `heun`, `heunpp2`, …
（完整列表**必须**运行时从 `GET /object_info/KSampler` 的 `input.required.sampler_name[0]` 读取——[comfy.icu 记录到 44 个](https://comfy.icu/node/KSamplerAdvanced)，但不同 ComfyUI 版本会增删。）

`scheduler`：**9 个可选值**，前 6 个为 `simple`, `sgm_uniform`, `karras`, `exponential`, `ddim_uniform`, `beta`，另 3 个（含 `normal`）。
（官方节点文档另列出 `normal` / `karras` / `exponential` / `sgm_uniform` / `simple` / `ddim_uniform` 六种常用值。）

**关键经验法则**（[来源](https://comfy.icu/node/KSampler)）：
- `sampler` 和 `scheduler` 是**一对**，不是两个独立偏好。SD1.5/SDXL 系：`dpmpp_2m + karras`，20–30 步。流匹配系（Flux/Z-Image/Klein）：Euler 家族 + `normal` 或 `beta`——**Karras 用在流匹配模型上会直接失败**。
- `cfg` 是**架构相关**的，不是「越高越听话」：SD1.5/SDXL **5–9**；Pony/Illustrious **4–6**；蒸馏模型（Turbo/Lightning）**约 1**。
- **CFG=1 时 negative prompt 基本无效**（那一遍前向根本不跑）。

---

## A.6 检测 ComfyUI 是否在跑 + 探测有哪些模型

```text
① 存活探测：GET http://127.0.0.1:8188/prompt
   → 200 + {"exec_info":{"queue_remaining":N}}  = 活着
   → 连接被拒 / 超时                            = 没启动

② 节点能力探测：GET /object_info
   → 拿到全部 class_type 集合，判断插件是否安装

③ 模型探测（从 ② 里挑）：
   GET /object_info/CheckpointLoaderSimple → input.required.ckpt_name[0]     → [checkpoint 列表]
   GET /object_info/LoraLoader            → input.required.lora_name[0]      → [lora 列表]
   GET /object_info/VAELoader             → input.required.vae_name[0]       → [vae 列表]
   GET /object_info/ControlNetLoader      → input.required.control_net_name[0]
   GET /object_info/UpscaleModelLoader    → input.required.model_name[0]
```

`/object_info` 支持 `/object_info/{class_type}` 取单个，**批量生成场景建议只请求需要的几个节点**，全量 `/object_info` 在装了大量插件时可能几 MB。

### 超时与错误处理清单

| 场景 | 处理 |
|---|---|
| 连接被拒 | 判为「ComfyUI 未启动」，给出启动指引，不要重试死循环 |
| `POST /prompt` 返回 400 | 解析 `node_errors`，逐节点报错信息回传用户；**不要盲目重试**（参数错误重试无用） |
| 任务长时间无进展 | WebSocket 空闲超时 → `POST /interrupt` → 标记失败 → 换 seed/降分辨率重试一次 |
| CUDA OOM（`execution_error`） | `POST /free {"unload_models":true,"free_memory":true}` → 分辨率降一档 / `batch_size` 降到 1 → 重试 |
| 断线 | 指数退避重连（复用 `clientId`）；重连后先查 `/history/{prompt_id}` 确认状态 |
| 超长队列 | 提交前查 `GET /prompt` 的 `queue_remaining`，超过阈值就等待而不是继续堆 |

---

## A.7 常见坑清单（踩过一次就记住）

1. **`class_type` ≠ UI 显示名**。UI 上是 `Load Checkpoint` / `KSampler (Advanced)` / `Upscale Image (using Model)`，API 里是 `CheckpointLoaderSimple` / `KSamplerAdvanced` / `ImageUpscaleWithModel`。**永远用 `/object_info` 校验，不要凭 UI 文字猜。**
2. **`required` vs `optional`**。`optional` 不传会用默认值；`required` 且无 `default` 的必须传。`ControlNetApplyAdvanced.vae` 是 optional，`InpaintModelConditioning` 的所有输入都是 required。
3. **`IS_CHANGED` 缓存导致重跑不出新图**。ComfyUI 会跳过输入未变的节点。如果 `seed` 不变、prompt 不变、参数不变，采样节点会被判定为 cache hit（你会收到 `execution_cached`），**直接复用上次的输出文件而不重新生成**。
   - 后果：你以为「重跑了一次」，其实拿到的是旧图。
   - 解法：① 每次改 `seed`；② 改任意一个会进入节点 hash 的输入；③ 用 `partial_execution_targets` 强制重跑特定节点；④ 重启服务（粗暴但有效）。
   - ⚠️ 注意 `LoadImage` 是**按文件内容 hash** 判断变更的，所以覆盖同名参考图会触发重跑，而只是改文件名不一定。
4. **`seed` 必须变化**（见上）。这是批量出图最常见的「怎么都一样」的原因。
5. **VAE 缺失 / 用错 VAE**。SD1.5 出现灰白、发灰、噪点通常是 VAE 问题 → 单独 `VAELoader` 挂 `vae-ft-mse-840000-ema-pruned` 并覆盖 checkpoint 的 `VAE` 输出。SDXL 系多数已内建正确 VAE。
6. **显存不足**。优先顺序：降分辨率 → 降 `batch_size` 到 1 → 用 `VAEDecodeTiled` 替代 `VAEDecode` → `--lowvram` 启动 → 用 fp8/GGUF 量化模型。
7. **图片保存路径与 `/view` 参数不匹配**。`SaveImage` 的 `filename_prefix` 写 `ygo/card` 后，history 里返回的 `filename` 是 `card_00001_.png`、`subfolder` 是 `ygo`——**必须把 `subfolder` 一起传给 `/view`**，否则 404。`type` 对 `SaveImage` 是 `output`，对 `PreviewImage` 是 `temp`。
8. **`width`/`height` 不是 8 的倍数** → 报错或尺寸被静默改变。
9. **`ImageUpscaleWithModel` 不能指定目标尺寸**，倍率由模型固定（通常 4x）。要特定尺寸需接 `ImageScale`/`ImageScaleBy` 降采样。
10. **`CLIPTextEncode` 的 77 token 限制**。SDXL 用双编码器会自动分块，但超出部分影响会衰减。**关键标签要前置**。
11. **`IPAdapterUnifiedLoader` 的 preset 与底模架构不匹配会直接报错**（`LIGHT`/`FULL FACE` 仅 SD1.5）。
12. **SDXL/Pony/Illustrious 的 LoRA 互相「能选但不能用」**。下拉框里能选不代表兼容——它们共享 SDXL 代码基，但 LoRA 训练目标不同。**必须按模型页标注的底模族匹配**。
13. **InsightFace 的 antelopev2 嵌套目录问题**（见 A.4.6）。
14. **`/queue` 的 running 项无法删除**，只能 `/interrupt`。
15. **history 在内存里，重启即失**。批量任务必须自己落盘。

---

# B. 适合游戏王卡图 / 二次元插画的本地模型与工作流

## B.1 二次元底模清单（2024–2026）

### B.1.1 SDXL 系（当前主力）

#### **Illustrious-XL 系**（**首选推荐**）

| 项目 | 值 |
|---|---|
| 主页 | [illustriousxl.org](https://illustriousxl.org/) ／ HF: [OnomaAIResearch/Illustrious-XL-v2.0](https://huggingface.co/OnomaAIResearch/Illustrious-XL-v2.0) |
| 官方 ComfyUI 节点 | [github.com/onomaai/ComfyUI_Illustrious](https://github.com/onomaai/ComfyUI_Illustrious) |
| 架构 | SDXL finetune，**原生 1536×1536**（也支持 1248×1824 等非标比例） |
| 版本演进 | v0.1 → v1.0（1536px 里程碑）→ v2.0 STABLE（cosine annealing，可预测的色彩）→ v3.5 VPred（SDXL 极限）；下一代是 Lumina 架构的 Illustrious LU |
| 提示词体系 | **混合式**：自然语言英文句 + Danbooru2023 标签，两者都吃得很好 |
| 训练数据 | Danbooru2023，知识截止 2024-06 |
| 授权 | **CreativeML OpenRAIL-M / Fair AI Public License**；明确**禁止闭源专有商业化**（prohibits closed-source proprietary monetization） |
| 定位 | **刻意「未调优」的中性画布**——这不是缺点，它是做 LoRA/融合底模最稳的父模型；也就是说**原版出图偏素**，实际批量出卡图建议用它的 finetune（见下） |

**推荐 finetune：`WAI-illustrious-SDXL`**（社区最常用的开箱即用选择）

| 项目 | 值 |
|---|---|
| Civitai | [civitai.com/models/827184/wai-illustrious-sdxl](https://civitai.com/models/827184/wai-illustrious-sdxl) |
| 说明页 | [illustriousxl.org/wai-illustrious-sdxl](https://illustriousxl.org/wai-illustrious-sdxl) |
| 底模 | Illustrious XL |
| 特点 | 内建海量角色知识（**很多角色不用 LoRA，纯 Danbooru 标签就能出**）、软质感、色彩浓郁、**多 LoRA 叠加不崩**（v15 起）、v17 修了背景色调脱节 |
| 最佳设置 | Euler a 或 `k_euler_ancestral`；**Steps 20–30**；**CFG 5–7** |
| 正向开头 | `masterpiece, best quality, amazing quality, newest` |
| 高分辨修复 | R-ESRGAN 4x+ Anime6B，20 步，**denoise 0.35~0.5** |
| 小技巧 | 白点噪点 → 负向加 `lens flare, particles, dust`；瞳孔莫名变红 → 负向加 `heart pupil` |
| 低显存 | 有 GGUF 量化版 |
| 授权 | ⚠️ 基于 Illustrious，**继承 OpenRAIL-M / Fair AI Public License 的限制** |

#### **NoobAI-XL**（[Laxhar/noobai-XL-1.0](https://huggingface.co/Laxhar/noobai-XL-1.0) / [noobai-XL-Vpred-0.5](https://huggingface.co/Laxhar/noobai-XL-Vpred-0.5)）

- Illustrious 的进一步训练版，**Danbooru 标签依从性极强**，社区风格 LoRA 生态最繁荣。
- 分 **Epsilon-pred（eps）** 与 **V-prediction（vpred）** 两条线。**vpred 版本必须配 `ModelSamplingDiscrete`（v_prediction）节点或启动参数**，否则出图全糊——这是高频坑。
- 授权：标注为 `license: other`，需看模型页。
- ⚠️ **未验证**：本次调研未取得 NoobAI 官方推荐 CFG/steps 的一手页面（HF README 抓取失败）。社区普遍用 **CFG 4–5 / Euler a / 28 步 / karras**，请以模型页为准。

#### **Animagine XL 4.0（Anim4gine）**（**授权最干净，工程落地最省心**）

| 项目 | 值 |
|---|---|
| 机构 | Cagliostro Research Lab |
| 许可 | [CreativeML Open RAIL++-M](https://huggingface.co/spaces/CompVis/stable-diffusion-license) —— **允许商用**，仅禁止有害/不道德用途 |
| HF | [easygoing0114/animagine-xl-4.0-opt_clear](https://huggingface.co/easygoing0114/animagine-xl-4.0-opt_clear) |
| 基座 | Stable Diffusion XL 1.0 |
| 训练 | **8.4M** 动漫图像，知识截止 **2025-01-07**，约 2650 GPU 小时；用 **tag ordering method** 训练身份与风格 |
| 提示词结构 | `1girl/1boy/1other, 角色名, 出自哪部作品, 其余任意顺序` |
| 画质词 | `masterpiece, high score, great score, absurdres`（放开头或结尾） |
| 推荐负向 | `lowres, bad anatomy, bad hands, text, error, missing finger, extra digits, fewer digits, cropped, worst quality, low quality, low score, bad score, average score, signature, watermark, username, blurry` |
| **CFG** | **5–7，推荐 6** |
| **Steps** | **25–28，推荐 25** |
| **采样器** | **Euler Ancestral（Euler a）** |
| 完整示例 | `masterpiece, high score, great score, absurdres, 1girl, firefly (honkai: star rail), honkai (series), honkai: star rail, casual, solo, looking at viewer, outdoors, smile, reaching towards viewer, night` |

推荐分辨率桶（**官方给出，可直接当枚举表用**）：

| 方向 | 尺寸 | 比例 |
|---|---|---|
| 方 | 1024×1024 | 1:1 |
| 横 | 1152×896 | 9:7 |
| 横 | 1216×832 | 3:2 |
| 横 | 1344×768 | 7:4 |
| 横 | 1536×640 | 12:5 |
| 竖 | 896×1152 | 7:9 |
| 竖 | **832×1216** | 2:3 |
| 竖 | 768×1344 | 4:7 |
| 竖 | 640×1536 | 5:12 |

来源：[Replicate Animagine XL 4.0 model card](https://replicate.com/rocketdigitalai/animagine-xl-4.0/readme)

#### **Pony Diffusion V6 XL**（能力强，但**授权是最大的雷**）

| 项目 | 值 |
|---|---|
| 页面 | [civitai.com/models/257749](https://civitai.com/models/257749/pony-diffusion-v6-xl) ／ [CivArchive 镜像](https://civarchive.com/models/257749/pony-diffusion-v6-xl?modelVersionId=290640) |
| 文件 | `ponyDiffusionV6XL_v6StartWithThisOne.safetensors`，**6.46 GB** |
| SHA256 | `67ab2fd8ec439a89b3fedb15cc65f54336af163c7eb5e4f2acc98f090a29b0b3` |
| 训练 | ~2.6M 图像，动漫/卡通/兽人/小马约 1:1 |
| **必须 CLIP skip 2** | 原文：不设 clip skip 2 会「getting low quality blobs」 |
| 必备正向前缀 | `score_9, score_8_up, score_7_up, score_6_up, score_5_up, score_4_up`（短版 `score_9` 效果弱得多） |
| 来源标签 | `source_pony` / `source_furry` / `source_cartoon` / **`source_anime`** |
| 分级标签 | `rating_safe` / `rating_questionable` / `rating_explicit` |
| **推荐参数** | **Euler a，25 步，1024px** |
| 负向 | 官方称**多数情况不需要负向词**，也不需要 `masterpiece`/`hd` 之类画质词 |
| 已知缺陷 | **会生成伪签名，很难用负向词去掉**（官方承认是训练问题，建议改用 V5.5 或 inpaint） |
| ⚠️ **授权** | **修改版 Fair AI Public License 1.0-SD**（[freedevproject.org/faipl-1.0-sd](https://freedevproject.org/faipl-1.0-sd/)）。额外条款：**禁止在任何允许变现的网站/应用上推理**（含付费推理、加速档），**此限制同样适用于所有衍生模型与融合模型**。商用需邮件申请授权。已获商用推理许可的仅 **CivitAI** 与 **Hugging Face**。 |

> **结论：如果你的 DIY 卡图项目有任何商业化可能，直接用 Animagine XL 4.0（OpenRAIL++-M）或自训 LoRA 配 OpenRAIL 底模；Pony 只适合纯个人/研究用途。**

#### 其他 SDXL 动漫模型（简要）

- **Kohaku-XL**（[KBlueLeaf/Kohaku-XL-Zeta](https://huggingface.co/KBlueLeaf/Kohaku-XL-Zeta)，作者 KBlueLeaf）—— 分 Epsilon / Alpha / Zeta 等版本；Zeta 作者本人写过「Why do you still use SDXL but not any brand new DiT based models?」的讨论，说明其定位是精调 SDXL。⚠️ **未验证**：本次未能抓到其推荐参数一手页。
- **Hassaku XL / blue_pencil-XL / AutismMix / Prefect Pony / Pony Realism** —— 均为 Illustrious 或 Pony 的社区 finetune。⚠️ 本次未逐一验证具体版本号与参数。

### B.1.2 SD1.5 系（低显存兜底）

**Anything V3/V4.5、Counterfeit V2.5/V3.0、MeinaMix、Cetus-Mix**

- 文件约 **2 GB**，**4–6 GB 显存即可跑**。
- 推荐分辨率 **512×768 / 768×512 / 512×512**（768×768 起开始出现双头）。
- **必须设 `CLIPSetLastLayer.stop_at_clip_layer = -2`**。
- 典型参数：`dpmpp_2m + karras`，CFG 7，20–25 步。
- **对 Danbooru 标签的理解远弱于 SDXL 系**，更依赖自然语言 + 少量标签，且**角色知识差**（多数具体角色要 LoRA）。
- ⚠️ 本次调研未逐一取得这些模型的一手页面，**标注为未验证**。
- **定位**：只在用户显存 < 6 GB 或已有 SD1.5 资产时作为兜底。

### B.1.3 Flux 系

| 模型 | 授权 | 说明 |
|---|---|---|
| **FLUX.1-dev** | **非商用**（[BFL Non-Commercial License](https://bfl.ai/legal/non-commercial-license-terms)） | 约 12 GB（fp16）。自然语言提示，T5 编码器，**guidance scale 3.5**，不用 booru 标签 |
| **FLUX.1-schnell** | **Apache 2.0**（可商用） | 蒸馏版，**guidance 1.0**，1–4 步 |
| **FLUX.1-Krea-dev** | ⚠️ 未验证具体条款 | 偏写实/审美的社区版 |
| 动漫 LoRA | 视 LoRA 授权 | 生态远不如 SDXL 系丰富 |

来源：[black-forest-labs/flux docs](https://github.com/black-forest-labs/flux/blob/main/docs/text-to-image.md)、[BFL 非商用条款](https://bfl.ai/legal/non-commercial-license-terms)

> **对「游戏王卡图」这个具体任务，Flux 系不推荐作为主力**：① 动漫风格与 Danbooru 标签体系支持弱；② 授权（dev）或质量（schnell）都有硬伤；③ 12 GB 显存门槛。**Flux 的合理用途是当「卡图之外」的补充**（如需要写实向的魔法阵/场景素材）。

### B.1.4 选型决策表

| 优先级 | 模型 | 触发条件 | 参数 |
|---|---|---|---|
| 1 | **WAI-illustrious-SDXL** | 用户已装 | Euler a / 20–30 步 / CFG 5–7 / 832×1216 或 1024×1024 |
| 2 | **NoobAI-XL** | 用户已装 | Euler a / 28 步 / CFG 4–5（vpred 需配套设置） |
| 3 | **Illustrious-XL v1.0/v2.0** | 用户已装 | 同 WAI，但**画风偏素，建议配风格 LoRA** |
| 4 | **Animagine XL 4.0** | **需要干净商用授权** | Euler a / 25 步 / CFG 6 |
| 5 | **Pony V6 XL** | 仅个人用途 | Euler a / 25 步 / CFG 7 / **CLIP skip 2** / 带 score_9 前缀 |
| 6 | **SD1.5 系**（Anything/Counterfeit） | 显存 < 6 GB | dpmpp_2m+karras / 20 步 / CFG 7 / **CLIP skip -2** / 512×768 |

---

## B.2 卡图特点与推荐分辨率

### B.2.1 构图需求 → 提示词对策

| 卡图特点 | 提示词对策 |
|---|---|
| 单角色居中 | `solo`, `centered`, `1boy`/`1girl`/`1monster` |
| 无文字、无边框 | 负向必须含 `text, watermark, signature, username, logo, border, frame, card, card (medium)` |
| 鲜艳 | `vibrant colors`, `high contrast`, `saturated` |
| 构图留白（便于后期排版） | `simple background`, `gradient background`（后期抠图），或 `full body` + `from below` 制造气势 |
| 游戏王特有的「发光」质感 | **`glowing`** —— 这是 YGO LoRA 的触发关键词之一（见 B.5） |

### B.2.2 分辨率组合

| 场景 | 分辨率 | 说明 |
|---|---|---|
| 方形（部分卡框） | **1024×1024** | 通用安全选择 |
| **竖版（主力）** | **832×1216** | SDXL 竖版标准桶，比例 ≈ 0.684 |
| 竖版（大图） | 896×1152 | Illustrious 系友好 |
| 横版 | **1216×832** | 需要横构图时 |
| Illustrious 专属 | 1536×1536 / 1248×1824 | 原生高分辨率，省掉放大步骤 |

### B.2.3 卡图窗口比例 —— 关于「3:4 还是 4:3」

⚠️ **注意：这两个都不对。**

主流游戏王卡面比例约为 **59:86 ≈ 0.686**（宽:高），即**竖版**。
你给出的实际卡图窗口 **421×614** 精确计算：

```
421 / 614 = 0.68567
```

对比各候选：

| 比例 | 小数 | 与 0.68567 的误差 |
|---|---|---|
| 卡图窗口 421:614 | 0.68567 | — |
| **SDXL 桶 832:1216** | **0.68421** | **−0.00146（0.21%）** |
| 3:4 | 0.75000 | +0.0643（9.4%） |
| 4:3 | 1.33333 | +0.6477（94%） |
| 2:3 | 0.66667 | −0.0190（2.8%） |
| 1216:1774（卡面近似整比例） | 0.68546 | −0.00021 |

**结论：`832×1216` 与 421×614 的比例几乎完全一致（误差 0.21%），是最优生成尺寸。** 3:4 会导致左右裁剪掉约 9% 画面，4:3 则完全方向错误。

> 补充：卡图窗口是**竖版**（高 > 宽），所以「竖版构图」是默认要求。若某些卡种（如同调/灵摆区域）需要横版，用 1216×832。

---

## B.3 一致性 / 系列卡图的实现手法

多张卡图要保持「同一角色」或「同一画风」，有 5 条技术路线，成本与效果递增：

| 路线 | 一致性维度 | 成本 | 说明 |
|---|---|---|---|
| **① 固定 seed + 固定 style preamble** | 画风（弱） | 免费 | 只改 subject 部分，画风词完全不动。**最便宜，见效立竿见影**，但角色外观会漂 |
| **② IPAdapter 参考图** | 画风 + 构图 | 低 | 一张「风格锚点图」，`weight_type="style transfer"` |
| **③ ControlNet** | 姿势 + 构图 | 低 | 姿势骨架/线稿锁定，**不锁画风** |
| **④ InstantID / PuLID / FaceID** | 人脸身份 | 中 | 仅对人形角色有效，且**仅 SDXL** |
| **⑤ 训练 LoRA** | 角色 + 画风（最强） | 高 | 20–50 张图，可达到「换任何场景都是这个角色」 |

### 方案 A：纯提示词锚定（零依赖，先做这个）

零插件、零额外模型，立刻可用。核心是**把 style preamble 做成字符串常量**：

```
STYLE = "masterpiece, best quality, amazing quality, newest, \
         yugioh style, duel monster, glowing, dramatic lighting, \
         dynamic pose, vibrant colors, detailed, cinematic composition, \
         depth of field, official art"

SUBJECT = "<每张卡变化的角色描述>"

NEGATIVE = "lowres, worst quality, low quality, text, watermark, signature, \
            username, logo, border, frame, multiple views, 2girls, 2boys, \
            bad anatomy, bad hands, extra digits, cropped, blurry"
```

固定 `seed` 基准（如每张卡用 `base_seed + index`），`832×1216`，Euler a，28 步，CFG 5。

### 方案 B：IPAdapter 风格锚点（推荐主力方案）

**先出一张「风格母版」**（挑最满意的一张卡图），之后所有卡图都参考它。

节点链（SDXL）：

```
CheckpointLoaderSimple(WAI-illustrious)
   ├─ MODEL ─→ IPAdapterUnifiedLoader(preset="STANDARD")  ─→ model, ipadapter
   │                                                              │
   └─ CLIP ──→ CLIPTextEncode(正向) ──┐                           │
              CLIPTextEncode(负向) ──┤                           │
                                     │                           │
LoadImage(风格母版.png) ── IMAGE ────┴──→ IPAdapterAdvanced(model, ipadapter, image)
                                              weight=0.6~0.8
                                              weight_type="style transfer"
                                              start_at=0.0, end_at=1.0
                                              embeds_scaling="K+V"
                                              combine_embeds="average"
                                                   │
EmptyLatentImage(832×1216, batch_size=1) ──────────┤
                                                   ↓
                                               KSampler
                                                   ↓
                                              VAEDecode → SaveImage
```

**参数要点**（来自 [IPAdapterUnifiedLoader 文档](https://uinodes.com/plugins/ComfyUI_IPAdapter_plus/IPAdapterUnifiedLoader) / [IPAdapterAdvanced 文档](https://uinodes.com/plugins/ComfyUI_IPAdapter_plus/IPAdapterAdvanced)）：

| 目标 | `weight` | `weight_type` |
|---|---|---|
| **只统一画风，不改内容** | **0.5–0.8** | `style transfer` |
| 统一画风 + 构图 | 0.7–1.0 | `style and composition` |
| 强风格注入 | 1.0–1.5 | `strong style transfer` |
| 角色外观相似 | 0.8–1.2 | `linear` |
| 抑制某特征 | **负值**（如 −0.5） | 配合 `image_negative` |

- `embeds_scaling` 推荐 `K+V`；若出现通道过拟合改 `K+V w/ C penalty`。
- **多张参考图**：用 `IPAdapterEncoder` 分别编码 → `IPAdapterCombineEmbeds`（`combine_embeds` 取 `average`/`concat`）→ `IPAdapterEmbeds`。
- **风格与构图分离**（SDXL 专属）：`IPAdapterStyleComposition`，可给风格图和构图图不同权重。

> ⚠️ SDXL 必须用 `ip-adapter-plus_sdxl_vit-h.safetensors` 或 `ip-adapter_sdxl_vit-h.safetensors` + `CLIP-ViT-H-14`；`preset` 不要选 `LIGHT` 或 `FULL FACE`（仅 SD1.5）。

### 方案 C：LoRA 训练（角色/画风强锚定）

一次性投入，之后最省事。

| 工具 | 链接 | 特点 |
|---|---|---|
| **Kohya_ss** | [github.com/bmaltais/kohya_ss](https://github.com/bmaltais/kohya_ss) | 功能最全，SDXL 支持成熟，社区文档最多 |
| **OneTrainer** | [github.com/Nerogar/OneTrainer](https://github.com/Nerogar/OneTrainer) | GUI 友好，显存优化好 |
| **ComfyUI 原生训练节点** | 核心新增 `TrainLoraNode` / `LoraModelLoader` | 可在 ComfyUI 内直接训练，无需外部工具 |
| **ai-toolkit** | [github.com/ostris/ai-toolkit](https://github.com/ostris/ai-toolkit) | Flux/SDXL LoRA 训练，含 bucket 逻辑 |

**数据集与超参经验值**（社区通行，⚠️ 具体数值请按实际效果调）：

| 项 | 角色 LoRA | 画风 LoRA |
|---|---|---|
| 图片数 | 15–30 张（多角度、多表情、统一画风） | 30–100 张 |
| 分辨率 | 1024（SDXL 桶） | 1024 |
| network dim / alpha | 16–32 / 8–16 | **8–16 / 4–8**（画风宜小，否则污染底模） |
| learning rate (UNet) | 1e-4 ~ 5e-4 | 5e-5 ~ 2e-4 |
| learning rate (TE) | 1e-5 ~ 5e-5 | 1e-5 或不用 |
| epochs / repeats | 10–20 epoch | 10–15 epoch |
| 打标 | 触发词 + 外观标签 | 触发词 + 风格标签 |
| 底模 | **必须与推理底模同族**（Illustrious 训练的 LoRA 用在 WAI 上没问题，用在 Pony 上会崩） |

使用：`LoraLoader` 的 `strength_model` 取 **0.6–0.85**（SDXL 时代经验值），`strength_clip` 通常同值或略低。触发词必须在正向 prompt 里出现。

### 方案 D：姿势/构图锁定（ControlNet）

适合「同一组卡的构图要统一」：

```
ControlNetLoader(controlnet-union-sdxl-1.0.safetensors)
   ↓
ControlNetApplyAdvanced(positive, negative, control_net, image=骨架图,
                        strength=0.65~0.8, start_percent=0.0, end_percent=0.5)
```

- SDXL 动漫友好 ControlNet：**`controlnet-union-sdxl-1.0` (promax, xinsir)** —— 一个模型覆盖 openpose/depth/canny/scribble 等多种模式；另有 `controlnet-openpose-sdxl`。
  ⚠️ **未验证**：本次未取得 xinsir union ControlNet 的一手 HF 页面，请以 HF 搜索 `xinsir/controlnet-union-sdxl-1.0` 为准。
- 预处理器用 `comfyui_controlnet_aux` 里的 `OpenPosePreprocessor` / `DWPreprocessor`（⚠️ class_type 建议用 `/object_info` 实测确认）。
- **union ControlNet 的 `strength` 要用 0.65–0.8，1.0 会「过熟」**；且**mode 必须与预处理图匹配**（union 设成 depth 却喂 canny 边缘 = 完全无效果）。

### 方案 E：人脸身份（仅人形角色，仅 SDXL）

- **InstantID**：`ApplyInstantID` 的 `weight` **0.8 起步，超过 1.0 就过曝**。
- **PuLID**：更适合「保持身份同时大幅改变风格/妆容」，对动漫脸比 InstantID 宽容。
- **IPAdapter FaceID**：`IPAdapterUnifiedLoaderFaceID` + `IPAdapterFaceID`，需额外 LoRA。
- ⚠️ **对游戏王最常见的「龙/魔法师/机械」类怪兽，这三者全部无效**——它们只处理人脸。**怪兽类角色一致性只能靠 LoRA（方案 C）或 IPAdapter（方案 B）。**

### 推荐的 2 套完整落地方案

**方案 ①「零额外模型 · 提示词 + 固定 seed」**（无插件依赖，立即可跑）
```
CheckpointLoaderSimple → CLIPTextEncode(固定 STYLE + 变化 SUBJECT) × 2
                       → EmptyLatentImage(832×1216, batch_size=1)
                       → KSampler(seed=base+i, euler_ancestral, 28, cfg=5, normal)
                       → VAEDecode → SaveImage("ygo/card")
```
适用：用户什么都没装，或首批试水。

**方案 ②「IPAdapter 风格锚点 + 4x 放大」**（推荐生产用）
```
[准备阶段，一次性] 用方案 ① 出 10 张，人工挑 1 张作为 style_anchor.png，放进 input/

[每张卡图]
CheckpointLoaderSimple
  → LoraLoader(可选角色/画风 LoRA, strength 0.7)
  → IPAdapterUnifiedLoader(preset="STANDARD")
  → IPAdapterAdvanced(image=style_anchor, weight=0.65,
                      weight_type="style transfer", embeds_scaling="K+V")
  → KSampler(seed=base+i, euler_ancestral, 28, cfg=5)
  → VAEDecode
  → UpscaleModelLoader(4x-UltraSharp) → ImageUpscaleWithModel
  → ImageScale(width=842, height=1228, upscale_method="lanczos", crop="disabled")
  → SaveImage("ygo/final")
```

---

## B.4 卡图专用后处理链

### B.4.1 放大

| 节点 `class_type` | inputs | 说明 |
|---|---|---|
| `UpscaleModelLoader` | **`model_name`** | 从 `models/upscale_models/` 加载 |
| `ImageUpscaleWithModel` | **`upscale_model`** **`image`** | 倍率由模型固定（通常 4x） |
| `ImageScale` | **`image`** **`upscale_method`** `width` `height` `crop` | 精确尺寸；**`width=0` 或 `height=0` 时等比推算**；放大用 `lanczos`，缩小用 `area` |
| `ImageScaleBy` | **`image`** **`upscale_method`** `scale_by` | 按倍率 |
| `LatentUpscale` | **`samples`** **`upscale_method`** `width` `height` `crop` | 潜空间放大，更省显存 |
| `LatentUpscaleBy` | **`samples`** **`upscale_method`** `scale_by` | 潜空间按倍率 |

**该选哪个放大模型**（[来源](https://comfy.icu/node/ImageUpscaleWithModel)）：

| 模型 | 适用 |
|---|---|
| **4x-UltraSharp** | 通用默认推荐，锐利但不过度 |
| **RealESRGAN_x4plus_anime_6B** | **动漫/插画首选**（WAI 官方也推荐这个做 hires fix） |
| **4x_NMKD-Siax_200k** | 动漫/插画 |
| **RealESRGAN_x4plus** | 通用 4x |
| **4x_foolhardy_Remacri** | 通用备选 |
| **SwinIR** | 老牌，动漫可用但已被 ESRGAN 系超越 |

下载：**[OpenModelDB](https://openmodeldb.info/)**（社区模型数据库，全部可验证来源）。模型放入 `ComfyUI/models/upscale_models/`。

> **关键认知**：`ImageUpscaleWithModel` 是**像素放大器，只加分辨率不加内容**。源图糊的话它救不了——那需要生成式修复（SUPIR / SeedVR2 之类），是不同的节点。

**Hires fix 两段式放大（既加分辨率又加细节）**：

```
KSampler(第一段, 832×1216, denoise=1.0)
  → VAEDecode → ImageUpscaleWithModel(4x模型)
  → ImageScaleBy(0.5)              # 4x 变 2x，控制到目标尺寸
  → VAEEncode
  → KSampler(第二段, denoise=0.35~0.5, steps=20)   # WAI 官方推荐 0.35~0.5
  → VAEDecode → SaveImage
```

或用潜空间版本：`LatentUpscaleBy(scale_by=1.5)` → `KSampler(denoise=0.4~0.6)`。

### B.4.2 去背景

| 方案 | 节点 `class_type` | 仓库 / 说明 |
|---|---|---|
| **ComfyUI 核心（2025+）** | 核心已内建 BiRefNet 背景移除（模型放 `models/background_removal/`） | [BiRefNet 教程](https://docs.comfy.org/ko/tutorials/utility/remove-background-birefnet)；⚠️ 核心节点的 `class_type` 需 `/object_info` 实测确认 |
| **ComfyUI-RMBG**（推荐，变体最全） | `BiRefNetRMBG` | [github.com/1038lab/ComfyUI-RMBG](https://github.com/1038lab/ComfyUI-RMBG)，[节点文档](https://comfy.icu/node/BiRefNetRMBG) |
| ComfyUI_BiRefNet_ll | `BiRefNet_LL` 系列 | ⚠️ 未验证 |
| ComfyUI-rembg | `Image Remove Background (rembg)` | ⚠️ 未验证精确 class_type |
| BRIA RMBG | ComfyUI-BRIA_AI-RMBG | ⚠️ 未验证 |

**`BiRefNetRMBG` 的完整 inputs**：

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| **`image`** | IMAGE | — | 输入图 |
| `model` | COMBO | — | **11 个权重可选，选错比调参影响大** |
| `sensitivity` | FLOAT | 1.00 | 检测强度（可选） |
| `mask_blur` | INT | 0 | 边缘模糊（可选） |
| `mask_offset` | INT | 0（−20~20） | 正=扩，负=缩（可选） |
| `invert_output` | BOOLEAN | false | 反转（可选） |
| `refine_foreground` | BOOLEAN | false | 前景色估计，清理透明边缘毛边（可选） |
| `unload_model` | BOOLEAN | false | 用完卸载显存（可选） |
| `background` | COMBO | `Alpha` | `Alpha`（透明）或 `Color`（纯色）（可选） |
| `background_color` | COLORCODE | `#222222` | 背景色（可选） |

输出：`IMAGE`（抠好的图）、`MASK`、`MASK_IMAGE`。

**模型变体选择指南**（这才是关键）：
- `BiRefNet-general` —— 默认，1024px 通用
- **`BiRefNet-HR`** —— 2048 训练，**输入超过约 1500px 必须用它**，否则 general 会内部降采样丢掉你想保的边缘
- `BiRefNet_dynamic` —— 批内分辨率不一致时用
- **`_toonout`** —— **为插画/动漫调优，卡图首选**
- `_matting` / `-HR-matting` / `_lite-matting` —— **是不同输出类型**（预测半透明 alpha），不是「更好的版本」
- `_lite` / `_lite-2K` —— Swin-Tiny 轻量版，弱显卡用
- `-portrait` —— 人像特化

> 性能：1024 分辨率下 FP16 推理**不到 1 秒/张**，几 GB 显存，不用担心开销。
> 备选：`InSPyReNet` 在某些材质上仍优于 BiRefNet——抠得不满意就换模型再试，不要以为是参数问题。
> 授权：**BiRefNet 是 MIT**，可商用。

**卡图场景的建议**：如果卡面需要角色和背景一体（多数怪兽卡就是完整插画），**不需要去背景**。去背景只在需要「角色 + 程序化卡框/背景」时才用——这时 `_toonout` + `background="Alpha"` 输出 PNG 透明图。

### B.4.3 去文字 / 去水印

三条路，按可靠性排序：

1. **预防 > 治疗（首选）**。负向词强制压制：`text, watermark, signature, username, logo, artist name, twitter username, web address, copyright name, letterboxed, border, frame, speech bubble`。
   - **Pony 特例**：官方承认 Pony V6 **会生成伪签名且负向词难以去掉**（[来源](https://civarchive.com/models/257749/pony-diffusion-v6-xl?modelVersionId=290640)），这是训练缺陷。**如果卡图对「无文字」是硬要求，不要用 Pony V6。**
2. **局部重绘（inpaint）**。用 `SetLatentNoiseMask` 或 `VAEEncodeForInpaint`：
   ```
   LoadImage → VAEEncode → SetLatentNoiseMask(mask=文字区域) → KSampler(denoise=0.6~0.8)
   → VAEDecode → ImageCompositeMasked（贴回原图，保证未遮罩区域像素完全一致）
   ```
   ⚠️ 两个坑：**mask 尺寸必须与图像一致**（否则重绘区域错位）；**`denoise` 忘了从 1.0 降下来**（那就等于整图重画）。即使 mask 完美，VAE encode/decode 往返也会轻微改变未遮罩像素，**所以最后要用 `ImageCompositeMasked` 把只重绘的区域贴回原图**，其余保持像素一致（[来源](https://comfy.icu/node/SetLatentNoiseMask)）。
   - 若用 inpainting 专用模型（SDXL inpaint），改用 `InpaintModelConditioning`（inputs: `positive` `negative` `vae` `pixels` `mask` `noise_mask`）。
3. **粗暴裁剪**：`ImageScale(crop="center")` 或 `ImageCrop` 切掉边缘水印区。⚠️ `crop="center"` 是**先按目标比例裁剪再缩放**，会真的丢画面。

### B.4.4 负向词清单

**通用动漫卡图负向（SDXL / Illustrious / Animagine 通用）**：

```
lowres, worst quality, low quality, bad anatomy, bad hands, bad proportions,
extra digits, fewer digits, missing fingers, extra limbs, fused fingers,
cropped, out of frame, jpeg artifacts, blurry,
text, watermark, signature, username, logo, artist name, copyright name,
web address, speech bubble, border, frame, letterboxed,
multiple views, character sheet, 2girls, 2boys, multiple characters,
sketch, monochrome, greyscale
```

**Pony 专属负向**（Pony 官方称多数情况不需要负向，但实际工程建议加）：

```
score_1, score_2, score_3, score_4,
source_pony, source_furry, source_cartoon,
worst quality, low quality, lowres
```

**Animagine XL 4.0 官方负向**（照抄即可）：

```
lowres, bad anatomy, bad hands, text, error, missing finger, extra digits,
fewer digits, cropped, worst quality, low quality, low score, bad score,
average score, signature, watermark, username, blurry
```

**WAI-illustrious 专属小技巧**（[来源](https://illustriousxl.org/wai-illustrious-sdxl)）：

```
# 出现白点/光斑噪点
lens flare, particles, dust
# 瞳孔莫名变红
heart pupil
# 不想要 NSFW
nsfw
```

**SD1.5 动漫模型**：

```
lowres, bad anatomy, bad hands, text, error, missing fingers,
extra digit, fewer digits, cropped, worst quality, low quality,
normal quality, jpeg artifacts, signature, watermark, username, blurry,
artist name
```

---

## B.5 现成的「游戏王卡图」ComfyUI 工作流 / 社区项目

### 已找到的一手资源

#### **Yu-Gi-Oh! card art SDXL**（LoRA，nicolai256）

| 项目 | 值 |
|---|---|
| Civitai | [civitai.com/models/130658/yu-gi-oh-card-art-sdxl](https://civitai.com/models/130658/yu-gi-oh-card-art-sdxl?modelVersionId=143400) |
| CivArchive 镜像（含完整说明） | [civitaiarchive.com/models/130658](https://civitaiarchive.com/models/130658?modelVersionId=143400) |
| 文件 | `yugioh-000001.safetensors`，**651.12 MB** |
| SHA256 | `0de4ef0d7c8d18195c1ada2639dbb1c52a148b347904b284ac0dca44297138f4` |
| HF 镜像 | [rml94867530922/ygo-loras](https://huggingface.co/rml948675322/ygo-loras) （原链接 `rml94867530922/ygo-loras`） |
| 触发词 | `yugioh` |
| 训练量 | **14,000 张带标注图** |
| 配套底模建议 | [Anime Art Diffusion XL](https://civarchive.com/models/117259/anime-art-diffusion-xl) |
| 配套节点 | [github.com/nicolai256/comfyUI_Nodes_nicolai256](https://github.com/nicolai256/comfyUI_Nodes_nicolai256)（作者为方便提示词写的自定义节点，仓库里也有他自用的工作流） |

**⭐ 这就是「游戏王卡图提示词范式」的一手来源**，作者明确给出：

必须放的核心关键词：
```
glowing, yugioh style, yugioh monster, duel monster
```

增强风格的可选关键词（**注意：这些是模仿「卡牌文本框」的元数据，会诱导模型画出文字，卡图场景慎用或只取 `outline`**）：
```
level: 9              (数字可改)
Attribute: Aqua/Beast/Beast-Warrior/Cyberse/Dinosaur/Divine-Beast/Dragon/
           Fairy/Fiend/Fish/Insect/Machine/Plant/Psychic/Pyro/Reptile/Rock/
           Sea Serpent/Spellcaster/Thunder/Warrior/Winged Beast/Wyrm/Zombie
Type: Dark/Divine/Earth/Fire/Light/Water/Wind
Attack: 2600          (数字可改)
Defense: 1900         (数字可改)
outline, digimon, pokemon, sparkle
```

> 💡 **关键提示**：`level:` / `Attack:` / `Defense:` 这类**会显著诱导模型生成卡面文字和数字**。对「只要纯卡图、不要文字」的需求，**建议只用 `glowing, yugioh style, yugioh monster, duel monster, outline`，把 `level/Attack/Defense` 全部去掉，并在负向加强 `text, numbers`**。

其他平台同一 LoRA 的镜像（可验证）：
- [PixAI](https://pixai.art/zh/model/1733739673061451542)
- [Tensor.Art](https://tensor.art/models/782326893077666010)
- [SeaArt](https://www.seaart.ai/)
- [Civitai 页面](https://civitai.com/models/130658/yu-gi-oh-card-art-sdxl)

### 中文社区讨论（可作为思路参考）

- NGA 讨论帖：[有没有什么适合做游戏王卡图的AI模型？](https://ngabbs.com/read.php?tid=41109238)
- 即刻 App 帖（用 ComfyUI 印卡的实践分享）：[牌佬打牌打不赢怎么办？当然是自己印卡啦](https://m.okjike.com/originalPosts/66becd9ba76a0c9d65ec3ccc)

### 其他相关生态

- **Aesthetic Quality Modifiers**（Tensor.Art，[链接](https://tensor.art/models/833342480259932397)）——v3.0 标注 `[animagine v4]` 兼容，是一组可复用的画质修正词库，适合直接并入 style preamble。
- ⚠️ **未找到**：一个成熟的、开源的、专门做「游戏王卡图批量生成 + 卡面合成」的完整 ComfyUI 工作流项目。**当前最接近的是上述 LoRA + 作者的自定义节点**。这实际上意味着：**你需要自己搭这套 pipeline**——而本报告 A/D 两节正是为此准备的。

---

# C. 提示词工程本地化

## C.1 二次元卡图的提示词结构范式

**推荐槽位顺序**（越靠前 CLIP 权重越高，且 SD1.5/SDXL 的 77-token 分块会让靠后内容衰减）：

```
[1] 画质词       masterpieces, best quality, amazing quality, absurdres
[2] 来源/风格     yugioh style, anime style, official art
[3] 主体数量     solo, 1monster / 1boy / 1girl
[4] 角色/种族     dragon, warrior, spellcaster, mechanical
[5] 外观细节      red hair, glowing eyes, golden armor, long tail, wings
[6] 动作/姿势     standing, roaring, holding sword, looking at viewer, arms raised
[7] 构图/镜头     full body, centered, from below, dynamic angle, close-up
[8] 背景/场景     dark background, ruins, stormy sky, magical circle
[9] 光照         dramatic lighting, rim light, backlighting, glowing, cinematic lighting
[10] 氛围        epic, ominous, holy, mysterious, powerful
[11] 技术词       depth of field, detailed, high contrast, vibrant colors
```

**完整可复制示例（Illustrious / WAI 系）**：

```
masterpiece, best quality, amazing quality, absurdres,
yugioh style, official art, anime style,
solo, 1monster, dragon,
black scales, glowing red eyes, golden horns, large wings, long tail,
roaring, standing, looking at viewer, mouth open,
full body, centered composition, from below, dynamic angle,
stormy sky, ruins, crackling lightning,
dramatic lighting, rim light, backlighting, glowing, cinematic lighting,
epic, powerful, ominous,
depth of field, detailed, high contrast, vibrant colors
```

**关于 77-token 分块**：SDXL 使用双文本编码器（CLIP-L + OpenCLIP-bigG），ComfyUI 会自动把长 prompt 分成多个 77-token chunk 并拼接。**这不是「超了就没用」**，但后续 chunk 的引导力度会衰减。**对策：把 [1]–[4] 这些决定成败的槽位放在最前面**，技术词和氛围词放最后。

## C.2 Danbooru 标签体系在不同模型中的用法差异

这是本次调研中**最容易出错、也最影响成品质量**的部分。四个模型族的 prompt 范式差异极大：

| 维度 | SD1.5 动漫系 | **Pony V6 XL** | **Illustrious / NoobAI** | **Animagine XL 4.0** | **Flux** |
|---|---|---|---|---|---|
| 提示词形态 | 自然语言 + 少量 booru | **必须带 score 前缀** + 标签 | **Danbooru2023 标签为主** + 自然语言（混合式） | **tag ordering** 结构化标签 | **完整自然语言句子** |
| 必备前缀 | `masterpiece, best quality` | **`score_9, score_8_up, score_7_up, score_6_up, score_5_up, score_4_up`** | `masterpiece, best quality` | **`masterpiece, high score, great score, absurdres`** | 无 |
| 来源标签 | 无 | **`source_anime`**（关键！不写会偏向兽人/小马） | 无 | 无 | 无 |
| 分级标签 | 无 | `rating_safe` 等 | 无 | 无 | 无 |
| **CLIP skip** | **必须 −2** | **必须 −2** | −1（默认，通常不用改） | −1 | N/A |
| **CFG** | 7–12 | **7**（官方样例 Euler a 25 步） | **4–5** | **5–7（推荐 6）** | dev: 3.5 / schnell: 1.0 |
| **采样器** | dpmpp_2m + karras | **Euler a** | **Euler a** / dpmpp_2m_sde + karras | **Euler a** | Euler + normal/beta |
| **Steps** | 20–25 | **25** | 20–30（常用 28） | **25–28（推荐 25）** | 20–28（schnell 1–4） |
| 负向词 | 长清单 | **官方称多数情况不需要**；`score_1..4, source_pony, source_furry, worst quality, low quality` | `lowres, worst quality, low quality` + 具体抑制项 | **官方长清单**（见 B.4.4） | 通常不用，靠 guidance |
| 画质词 | 需要 | **官方说不需要**（`masterpiece`/`hd` 无效） | 需要（WAI 对 `masterpiece` 反应强烈） | 需要 | 不需要 |
| 标签权重语法 | `(tag:1.2)` | `(tag:1.2)` | **`(tag:1.2)`** 支持良好 | `(tag:1.2)` | 不适用（自然语言描述程度） |
| 角色知识 | 差（需 LoRA） | 好 | **极好（Danbooru2023 全量）** | 好（8.4M，截止 2025-01） | 中 |

**关键结论**：
1. **`source_anime` 是 Pony 的必备项**。Pony 训练数据里动漫/卡通/兽人/小马各占约 1:1，不写 `source_anime` 会明显偏向其他域。
2. **Pony 与 Illustrious/NoobAI 的负向词无法通用**。Pony 用 `score_1..4`，其他用 `worst quality, low quality`。
3. **不要把 Pony 的 `score_9` 前缀搬到 Illustrious 上**——那是 Pony 特有的训练产物，在别的模型上是纯噪声 token。
4. **Illustrious/NoobAI 的 `(tag:1.2)` 加权最可靠**，因为它们是纯 Danbooru 标签训练的。
5. **SD1.5 系的 CLIP skip −2 是硬要求**；SDXL 系默认就用了倒数第二层，所以「CLIP skip 2」在 SDXL 上往往等于「什么都不用做」（[来源](https://comfy.icu/node/LoraLoader)）。

## C.3 系列卡图的一致性提示词模板

核心思想：**把「系列不变的部分」冻结成常量前缀，只让「单张变化的部分」做变量**。

### 模板结构

```python
# ============ 系列常量（所有卡图完全相同，一个字都不改）============
SERIES_STYLE = (
    "masterpiece, best quality, amazing quality, absurdres, "
    "yugioh style, official art, anime style, "
    "glowing, duel monster, dramatic lighting, rim light, "
    "vibrant colors, high contrast, depth of field, "
    "centered composition, full body, no text"
)

# ============ 每张卡变量 ============
SUBJECT_TMPL = "{count}, 1monster, {race}, {appearance}, {pose}, {background}, {mood}"

# ============ 系列常量负向 ============
SERIES_NEGATIVE = (
    "lowres, worst quality, low quality, bad anatomy, bad hands, "
    "text, watermark, signature, username, logo, border, frame, "
    "multiple views, character sheet, 2girls, 2boys, "
    "cropped, blurry, jpeg artifacts, sketch"
)
```

### 示例 1：龙族系列（5 张，同一画风不同龙）

| # | SUBJECT 变量部分 |
|---|---|
| 1 | `solo, 1monster, dragon, black scales, glowing red eyes, golden horns, large wings, roaring, standing, looking at viewer, stormy sky, ruins, epic, powerful, ominous` |
| 2 | `solo, 1monster, dragon, white scales, ice crystals, silver armor plating, breathing frost, flying, snowfield, frozen lake, majestic, serene, cold` |
| 3 | `solo, 1monster, dragon, crimson scales, molten cracks, fire breath, two heads, coiled, volcano, lava, raging, destructive, infernal` |
| 4 | `solo, 1monster, dragon, emerald scales, feathered wings, gentle eyes, perched, ancient forest, sunbeams, wise, protective, verdant` |
| 5 | `solo, 1monster, dragon, mechanical dragon, chrome plating, glowing blue circuits, energy cannon, hovering, futuristic city, neon, technological, imposing` |

正向 = `SERIES_STYLE + ", " + SUBJECT`；负向 = `SERIES_NEGATIVE`。**seed 各不相同**（`base_seed + i`）。

### 示例 2：魔法师系列（4 张）

| # | SUBJECT 变量部分 |
|---|---|
| 1 | `solo, 1girl, spellcaster, long silver hair, purple robe, holding staff, casting spell, magic circle, arcane library, mystical, focused` |
| 2 | `solo, 1boy, spellcaster, dark robe, eye patch, floating grimoire, forbidden runes, dark altar, sinister, forbidden` |
| 3 | `solo, 1girl, spellcaster, blonde twin tails, white and gold robe, healing light, holy sigil, cathedral, radiant, benevolent` |
| 4 | `solo, 1girl, spellcaster, blue hair, water magic, flowing dress, summoning, ocean temple, ethereal, graceful` |

### 系列一致性的三步加固

1. **固定 `SERIES_STYLE`**（提示词层）——免费，效果 60%
2. **固定 seed 基准 + 单调递增偏移**（`base_seed + index`）——保证噪声分布同族，降低风格漂移 ⚠️ **不要用同一个 seed**，否则五张构图会高度雷同
3. **接 IPAdapter 指向系列首张满意图**（`weight 0.5~0.65, weight_type="style transfer"`）——效果拉到 90%+

## C.4 中文风格描述 → 英文提示词

### 方案对比

| 方案 | 可行性 | 优点 | 缺点 |
|---|---|---|---|
| **A. 本地 LLM（Ollama / llama.cpp + Qwen 系）** | **高** | 完全离线，能理解「赛博朋克 + 水墨」这类复合中文描述，可让它按槽位输出结构化英文 | 需额外部署；LLM 输出的标签未必是「有效 Danbooru 标签」，需要后处理校验 |
| **B. 静态中文→Danbooru 词典** | 中 | 零延迟、零依赖、**输出 100% 是有效 booru 标签** | 覆盖不了自由描述，只能做关键词替换 |
| **C. 推荐：A + B 混合** | **最高** | LLM 做语义拆解 → 词典做标签校正 → 确保每个输出标签都在 Danbooru 词表内 | 实现稍复杂 |
| **D. 云端翻译 API** | 高 | 质量好 | **违反「本地」要求**，且有隐私/成本问题 |
| **E. 图像反推（JoyCaption / Qwen-VL）** | 高 | 给一张参考图就能得到风格 prompt | 需要有参考图 |

### 方案 A 的具体落地

**ComfyUI 内的本地 LLM 节点**（⚠️ class_type 需 `/object_info` 实测确认）：

| 插件 | 仓库 | 用途 |
|---|---|---|
| `comfyui-ollama` | ⚠️ 未验证精确仓库 URL | 调用本地 Ollama 服务 |
| `comfyui_LLM_party` | ⚠️ 未验证 | 功能最全的 LLM 节点包 |
| `ComfyUI-IF_AI_tools` | ⚠️ 未验证 | 多后端 LLM |
| `ComfyUI-GGUF` | ⚠️ 未验证 | 直接加载 GGUF 量化文本模型 |

**推荐做法（不推荐在 ComfyUI 图里做 LLM，而是在外部做）**：
批量生成场景下，**中文→英文的转换应该在调用 ComfyUI 之前、在你的批处理脚本里用一次 LLM 完成**，而不是每张图都在 ComfyUI 图里跑一次 LLM。理由：
- LLM 推理比出图慢得多，放进图里会严重拖慢流水线
- 外部做可以加**缓存**（同一风格描述只翻译一次）
- 外部做可以加**标签校验**（把 LLM 输出与 Danbooru 词表求交集）

**LLM 系统提示词模板**（可直接用）：

```
You are a Danbooru tag translator for Stable Diffusion anime models.
Input: a Chinese description of a card artwork style/character.
Output: ONLY a comma-separated list of English Danbooru tags, in this exact order:
  [quality tags], [style tags], [subject count tags], [character/race tags],
  [appearance tags], [pose tags], [composition tags], [background tags],
  [lighting tags], [mood tags]
Rules:
- Use ONLY real Danbooru tags (e.g. "1girl", "solo", "full body", "from below",
  "dramatic lighting", "glowing", "official art", "depth of field").
- NEVER output card metadata tags: level, attack, defense, attribute, type.
- NEVER output text/watermark-related words.
- No explanations, no markdown, no preamble. Tags only.
```

### 方案 B 的词典骨架

准备两张表：

```json
// zh2tag.json —— 中文词 → Danbooru 标签（多对多）
{
  "龙": ["dragon"],
  "机械": ["mechanical", "mecha"],
  "发光": ["glowing"],
  "霸气": ["imposing", "powerful", "epic"],
  "神秘": ["mysterious", "mystical"],
  "神圣": ["holy", "divine", "radiant"],
  "冰": ["ice", "frozen", "snowfield"],
  "火": ["fire", "flame", "molten"],
  "魔法阵": ["magic circle", "magic sigil"],
  "全身": ["full body"],
  "居中": ["centered", "centered composition"],
  "仰视": ["from below"],
  "俯视": ["from above"],
  "戏剧性光照": ["dramatic lighting"],
  "边缘光": ["rim light"],
  "逆光": ["backlighting"],
  "景深": ["depth of field"]
}
```

```json
// negative_base.json —— 系列固定负向词
["lowres","worst quality","low quality","text","watermark","signature",
 "username","logo","border","frame","multiple views","cropped","blurry"]
```

### 方案 E：图像反推（有参考图时最优）

用视觉模型对参考图生成描述 → 直接当 style preamble。
- **JoyCaption**（[github.com/fpgaminer/joycaption](https://github.com/fpgaminer/joycaption)，⚠️ 未验证）—— 专为 SD 训练/提示词设计的 captioner
- **Qwen2.5-VL / Qwen3-VL** 本地部署 + 同样的系统提示词
- ComfyUI 内的 `Florence2` 节点（`ComfyUI-RMBG` 包里带 `AILab_Florence2`）

---

# D. 落地建议

## D.1 「零配置即用」的自适应模型探测

核心思路：**不问用户装了什么，直接问 ComfyUI。**

### 探测与选择算法

```
STEP 1  存活探测
        GET http://127.0.0.1:8188/prompt
        失败 → 报「ComfyUI 未启动」，终止

STEP 2  拉 checkpoint 列表
        GET /object_info/CheckpointLoaderSimple
        ckpts = resp["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0]
        ckpts 为空 → 报「没有可用模型」，终止

STEP 3  按优先级关键字匹配（全部小写比对）
        优先级 1（Illustrious 系，最优）:
            ["illustrious", "wai", "noobai", "noob-ai", "hassaku",
             "blue_pencil", "kohaku", "nova", "c2fn"]
            → 架构 SDXL_IL，CFG 5, steps 28, sampler euler_ancestral,
              negative = IL_NEGATIVE, 需 CLIP skip 默认
        优先级 2（Animagine，授权最干净）:
            ["animagine", "anim4gine"]
            → 架构 SDXL_ANIMAGINE, CFG 6, steps 25, sampler euler_ancestral,
              positive 前缀 "masterpiece, high score, great score, absurdres",
              negative = ANIMAGINE_NEGATIVE
        优先级 3（Pony）:
            ["pony", "prefect", "autismmix", "homosimile"]
            → 架构 SDXL_PONY, CFG 7, steps 25, sampler euler_ancestral,
              positive 前缀 "score_9, score_8_up, score_7_up, score_6_up,
                              score_5_up, score_4_up, source_anime",
              negative = PONY_NEGATIVE, **CLIPSetLastLayer(-2)**
        优先级 4（其它 SDXL）:
            ["xl", "sdxl", "juggernaut", "dreamshaper"]
            → 架构 SDXL, CFG 7, steps 25
        优先级 5（SD1.5 兜底）:
            ["anything", "counterfeit", "meina", "cetus", "sd15", "v1-5"]
            或 上面全不匹配 → 架构 SD15
            → CFG 7, steps 22, sampler dpmpp_2m, scheduler karras,
              **必须 CLIPSetLastLayer(-2)**, 分辨率 512×768

STEP 4  分辨率决策（按架构）
        SDXL_IL        → 832×1216（竖）/ 1024×1024（方）/ 1216×832（横）
        SDXL_ANIMAGINE → 832×1216（官方 2:3 桶）
        SDXL_PONY      → 832×1216 或 1024×1024
        SDXL 通用      → 832×1216 / 1024×1024 / 1216×832
        SD15           → 512×768（竖）/ 512×512（方）/ 768×512（横）

STEP 5  插件探测（决定能否启用增强链）
        GET /object_info/IPAdapterUnifiedLoader  → 200 则启用方案 B
        GET /object_info/ControlNetApplyAdvanced → 200 且
        GET /object_info/ControlNetLoader        → 200 则启用 ControlNet
        GET /object_info/UpscaleModelLoader      → 200 则启用放大链
        GET /object_info/BiRefNetRMBG            → 200 则启用抠图

STEP 6  放大模型选择
        GET /object_info/UpscaleModelLoader → names
        按优先级匹配：
          1. 含 "anime" 或 "Anime6B"   → RealESRGAN_x4plus_anime_6B（动漫最优）
          2. 含 "UltraSharp"           → 4x-UltraSharp
          3. 含 "Siax"                 → 4x_NMKD-Siax_200k
          4. 含 "Remacri"              → 4x_foolhardy_Remacri
          5. 任意可用                   → 用它
          6. 无                        → 跳过放大，用 ImageScale(lanczos) 直接降采样
```

### 关键设计原则

1. **永远从 `/object_info` 读枚举值**，不要硬编码 sampler / scheduler / 模型名列表。不同 ComfyUI 版本和插件组合会让硬编码失效。
2. **优雅降级**：任何一个增强节点不可用（404），就跳过那一环，而不是报错终止。基础 txt2img 链（CheckpointLoaderSimple → 2×CLIPTextEncode → EmptyLatentImage → KSampler → VAEDecode → SaveImage）在任何 ComfyUI 上都存在。
3. **首次运行先做一次「探测+试跑」**：用最低成本参数（`steps=8`, `832×1216`, `batch_size=1`）跑一张，确认整条链路通，再开始批量。
4. **把探测结果缓存到本地 JSON**（模型列表、采样器列表、可用插件），下次启动直接读，避免每次都请求几 MB 的 `/object_info`。
5. **把 `class_type` 与显示名的映射表内置**，用于给用户友好的错误提示（例如「找不到节点 `CheckpointLoaderSimple`（界面名：Load Checkpoint）」）。

### 与 ComfyUI 的交互骨架（伪代码）

```
client_id = uuid4()
ws = connect(f"ws://127.0.0.1:8188/ws?clientId={client_id}")

for card in cards:
    workflow = build_workflow(card, arch_profile, seed=base_seed + card.index)

    # 提交
    r = POST /prompt {prompt: workflow, client_id: client_id}
    if r.status == 400:
        log_and_skip(card, r.node_errors)   # 参数错误，重试无用
        continue
    prompt_id = r.prompt_id

    # 等待（优先 WS，超时兜底）
    wait_for(ws, prompt_id,
             on_progress = lambda v,m: report(v/m),
             timeout     = estimate_timeout(arch, res, steps))

    # 取结果
    h = GET /history/{prompt_id}
    if h.status.status_str != "success":
        handle_error(h)
        continue

    for node_id, out in h.outputs.items():
        for img in out.get("images", []):
            data = GET /view?filename={img.filename}
                             &subfolder={img.subfolder}
                             &type={img.type}
            save(f"cards/{card.id}.png", data)
```

### 超时估算参考

| 架构 | 分辨率 | steps | 显存 | 单张耗时（估） |
|---|---|---|---|---|
| SD1.5 | 512×768 | 20 | 4–6 GB | 3–8 s |
| SDXL | 832×1216 | 25 | 8–12 GB | 15–35 s |
| SDXL | 832×1216 | 28 + hires fix | 10–12 GB | 45–90 s |
| SDXL + IPAdapter | 832×1216 | 28 | 12 GB | 50–100 s |

建议超时设成估算值的 **3 倍**，并监听 WebSocket：**只要有 `progress` 消息就不算超时**（真正的卡死是无消息，不是慢）。

---

## D.2 从生成到最终卡面素材的完整链路

### D.2.1 421×614 卡图窗口的实际像素需求

**核心计算**：

```
卡图窗口：421 × 614 px
比例：421 / 614 = 0.68567
```

**这个比例非常接近 SDXL 的 832×1216 桶（0.68421，误差仅 0.21%）。** 所以生成尺寸就选 832×1216。

### 为什么不能直接生成 421×614？

1. **421 不是 8 的倍数**：`421 / 8 = 52.625` → ComfyUI 会报错或静默取整到 416 或 424，导致比例失真。
2. **分辨率太低**：SDXL 在 421×614 上会生成严重退化的图像（远低于 1024 级训练分布）。
3. **降采样才有锐度**：高分辨率生成 → 高质量降采样，边缘和线条会明显更锐利（这是标准的「超采样」原理）。

### 推荐的完整链路

```
┌─ 阶段 1：生成 ──────────────────────────────────────────────┐
│  832 × 1216  （SDXL 竖版标准桶，比例误差 0.21%）              │
│  KSampler: euler_ancestral, 28 steps, CFG 5, denoise=1.0    │
│  可选：IPAdapterAdvanced(style_anchor, weight=0.65,          │
│                          weight_type="style transfer")       │
└──────────────────────────────────────────────────────────────┘
                            ↓ VAEDecode
┌─ 阶段 2：放大（像素级，4x）──────────────────────────────────┐
│  UpscaleModelLoader → ImageUpscaleWithModel                  │
│  模型：RealESRGAN_x4plus_anime_6B 或 4x-UltraSharp            │
│  832×1216  →  3328 × 4864                                    │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌─ 阶段 2b（可选）：细节回填 hires fix ────────────────────────┐
│  ImageScaleBy(0.5) → 1664×2432 → VAEEncode                   │
│  → KSampler(denoise=0.35, steps=20) → VAEDecode              │
│  （WAI 官方推荐 denoise 0.35~0.5）                            │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌─ 阶段 3：降采样到目标 2x ────────────────────────────────────┐
│  ImageScale(width=842, height=1228,                          │
│             upscale_method="lanczos", crop="disabled")       │
│  842 = 421 × 2,  1228 = 614 × 2                              │
│  ⚠️ crop 必须 "disabled"，否则会裁掉画面                      │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌─ 阶段 4（可选）：抠图 / 统一背景 ───────────────────────────┐
│  BiRefNetRMBG(model="BiRefNet_toonout", background="Alpha")  │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌─ 阶段 5：保存 ──────────────────────────────────────────────┐
│  SaveImage(filename_prefix="ygo/<card_id>")                  │
│  或从 /view 下载后由外部脚本转存为 <id>.png / <id>.jpg        │
└──────────────────────────────────────────────────────────────┘
```

### 尺寸换算表

| 目标卡图窗口 | 用途 | 生成尺寸 | 放大后 | 最终交付 |
|---|---|---|---|---|
| 421×614 | **1× 显示** | 832×1216 | 3328×4864 | **421×614** |
| 421×614 | **2× 高清屏**（推荐） | 832×1216 | 3328×4864 | **842×1228** |
| 421×614 | 3× 印刷级 | 832×1216 | 3328×4864 | **1263×1842** |
| 421×614 | 4× 印刷级 | 1024×1496* | 4096×5984 | **1684×2456** |

\* 1024×1496：1024/1496 = 0.6845，同样贴合 0.68567；且都是 8 的倍数。

**推荐交付 2×（842×1228）**：① 高清屏上清晰；② 文件大小合理（约 200–500 KB PNG）；③ 若界面缩放，浏览器降采样也比 1× 放大好看得多。

### D.2.2 关于「裁剪/构图」这一步

**如果生成比例已经匹配（832×1216 → 0.68421 vs 目标 0.68567，误差 0.21%）**，那么：

- **不需要裁剪**。0.21% 的误差在 614px 高度上只有约 **1.3 px** 的宽度差，肉眼不可见。
- 直接 `ImageScale(width=842, height=1228, crop="disabled")` 即可，允许极轻微的横向拉伸（0.2%）或改用 `crop="center"` 裁掉约 1.3px。

**如果用户坚持要精确比例且不能有任何变形**：

```
ImageScale(width=842, height=0, upscale_method="lanczos", crop="disabled")
  → 得到 842×1230（等比）
ImageCrop(width=842, height=1228, x=0, y=1)
  → 从上下各裁 1px 得到精确 842×1228
```

**如果需要「主体居中 + 留白」的构图**（很多卡面希望角色略偏下，上方留空间给标题）：
在生成阶段用提示词控制（`full body, centered, from below`），**而不是后期裁剪**——后期裁剪会破坏构图平衡。

### D.2.3 文件命名与目录规范建议

```
output/
  ygo/
    <card_id>_raw_00001_.png       # SaveImage 直出（832×1216）
    <card_id>_4x_00001_.png        # 放大后（3328×4864）
    <card_id>_final_00001_.png     # 降采样后（842×1228）
```

用 `SaveImage` 的 `filename_prefix` 直接实现（支持路径）：
- 阶段 1：`filename_prefix = "ygo/{card_id}_raw"`
- 阶段 2：`filename_prefix = "ygo/{card_id}_4x"`
- 阶段 3：`filename_prefix = "ygo/{card_id}_final"`

或者**只保存最终图**（推荐，省磁盘）：中间阶段不落盘，直接在节点链里流转，只在最后接一个 `SaveImage`。批量出 500 张卡图时，中间产物会占掉几十 GB。

### D.2.4 批量生成的工程建议

| 项 | 建议 |
|---|---|
| **并发** | ComfyUI 是单队列串行执行。**不要并发提交**，靠队列自然排队（可 `front: true` 插队紧急任务） |
| **批量大小** | 一次 `batch_size` 建议 ≤ 4（显存换速度）。**大批量用「多次提交」而不是大 batch_size**，隔离性更好 |
| **seed 管理** | 每张卡 `seed = base_seed + index`，并把 `base_seed` + 实际 seed 记录到卡图元数据（便于重出） |
| **断点续跑** | 每张卡完成后立刻写一条记录（`card_id, prompt_id, seed, filename, status`）到本地 DB/JSONL。重启后跳过已完成的 |
| **失败重试** | OOM → 降分辨率或 batch_size 重试 1 次；seed 相关错误 → 换 seed 重试 1 次；参数错误（400）→ **不重试**，记录并跳过 |
| **显存管理** | 每 N 张（如 20 张）调一次 `POST /free {"unload_models": false, "free_memory": true}`；切换底模时 `unload_models: true` |
| **历史清理** | 定期 `POST /history {"clear": true}`，否则内存里的 history 会持续增长 |
| **日志** | 保存 `prompt_id` → 可随时用 `GET /history/{prompt_id}` 追溯当时用的完整参数（history 里存了整份 workflow！） |

### D.2.5 最容易翻车的三个点（重申）

1. **seed 不变 = 图不变**。批量脚本里如果忘了改 seed，你会得到 N 张一模一样的图，而且 ComfyUI 还可能因为缓存**根本不重新生成**（收到 `execution_cached`），你拿到的是旧文件。
2. **`/view` 必须带 `subfolder`**。用了 `filename_prefix="ygo/card"` 之后，history 返回的 `filename` 只有 `card_00001_.png`，`subfolder` 才是 `ygo`。漏传参数直接 404。
3. **`class_type` 用注册名**。UI 显示 `Load Checkpoint` → API 必须写 `CheckpointLoaderSimple`。**每次写完 workflow 用 `/object_info` 校验一遍所有 `class_type` 是否存在**，能在提交前就发现「用户没装这个插件」。

---

# 附录：URL 汇总

## 官方文档

| 主题 | URL |
|---|---|
| REST API 总览 | https://docs.comfy.org/development/comfyui-server/comms_overview |
| 服务器路由（HTTP + WS） | https://docs.comfy.org/development/comfyui-server/comms_routes |
| WebSocket 消息类型 | https://docs.comfy.org/development/comfyui-server/comms_messages |
| API 示例（三种调用模式） | https://docs.comfy.org/development/comfyui-server/api-examples |
| Workflow API 格式 | https://docs.comfy.org/development/api-development/workflow-api-format |
| 启动参数 | https://docs.comfy.org/development/comfyui-server/startup-flags |
| `POST /prompt` 详解 | https://mintlify.wiki/Comfy-Org/ComfyUI/api/prompt |
| `GET /history` 详解 | https://mintlify.wiki/Comfy-Org/ComfyUI/api/history |
| 队列管理 | https://mintlify.wiki/Comfy-Org/ComfyUI/api/queue |
| WebSocket 总览 | https://mintlify.wiki/Comfy-Org/ComfyUI/api/websocket-overview |
| WebSocket 事件 | https://mintlify.wiki/Comfy-Org/ComfyUI/api/websocket-events |
| 节点文档：Loaders | https://mintlify.wiki/Comfy-Org/ComfyUI/nodes/loaders |
| 节点文档：Conditioning | https://mintlify.wiki/Comfy-Org/ComfyUI/nodes/conditioning |
| 节点文档：Sampling | https://mintlify.wiki/Comfy-Org/ComfyUI/nodes/sampling |
| 节点文档：Latent | https://mintlify.wiki/Comfy-Org/ComfyUI/nodes/latent |
| 节点文档：Image | https://mintlify.wiki/Comfy-Org/ComfyUI/nodes/image |
| BiRefNet 去背景教程 | https://docs.comfy.org/ko/tutorials/utility/remove-background-birefnet |

## 节点级规格（含枚举值）

| 节点 | URL |
|---|---|
| SaveImage / LoadImage / CheckpointLoaderSimple | https://comfy.icu/node/SaveImage ／ https://comfy.icu/node/LoadImage ／ https://comfy.icu/node/CheckpointLoaderSimple |
| KSampler / KSamplerAdvanced | https://comfy.icu/node/KSampler ／ https://comfy.icu/node/KSamplerAdvanced |
| LoraLoader | https://comfy.icu/node/LoraLoader |
| ControlNetApplyAdvanced | https://comfy.icu/node/ControlNetApplyAdvanced |
| ImageScale / ImageUpscaleWithModel | https://comfy.icu/node/ImageScale ／ https://comfy.icu/node/ImageUpscaleWithModel |
| SetLatentNoiseMask | https://comfy.icu/node/SetLatentNoiseMask |
| BiRefNetRMBG | https://comfy.icu/node/BiRefNetRMBG |
| IPAdapterAdvanced（中文，含参数表） | https://uinodes.com/plugins/ComfyUI_IPAdapter_plus/IPAdapterAdvanced |
| IPAdapterUnifiedLoader（preset 说明） | https://uinodes.com/plugins/ComfyUI_IPAdapter_plus/IPAdapterUnifiedLoader |
| IPAdapter 插件总览（模型文件清单） | https://uinodes.com/plugins/ComfyUI_IPAdapter_plus |
| ApplyInstantID | https://uinodes.com/plugins/ComfyUI_InstantID/ApplyInstantID |
| ComfyUI_InstantID 总览 | https://uinodes.com/plugins/ComfyUI_InstantID |
| PuLID-ComfyUI | https://uinodes.com/plugins/pulid_comfyui |

## 模型

| 模型 | URL |
|---|---|
| Illustrious XL 官网 | https://illustriousxl.org/ |
| Illustrious XL v2.0 (HF) | https://huggingface.co/OnomaAIResearch/Illustrious-XL-v2.0 |
| Illustrious 官方 ComfyUI 节点 | https://github.com/onomaai/ComfyUI_Illustrious |
| WAI-illustrious-SDXL (Civitai) | https://civitai.com/models/827184/wai-illustrious-sdxl |
| WAI-illustrious 说明页 | https://illustriousxl.org/wai-illustrious-sdxl |
| NoobAI-XL v1.0 (HF) | https://huggingface.co/Laxhar/noobai-XL-1.0 |
| NoobAI-XL Vpred 0.5 (HF) | https://huggingface.co/Laxhar/noobai-XL-Vpred-0.5 |
| Animagine XL 4.0 模型卡 | https://replicate.com/rocketdigitalai/animagine-xl-4.0/readme |
| Animagine XL 4.0 (HF) | https://huggingface.co/easygoing0114/animagine-xl-4.0-opt_clear |
| OpenRAIL++-M 许可 | https://huggingface.co/spaces/CompVis/stable-diffusion-license |
| Pony Diffusion V6 XL (Civitai) | https://civitai.com/models/257749/pony-diffusion-v6-xl |
| Pony V6 XL 完整说明（CivArchive） | https://civarchive.com/models/257749/pony-diffusion-v6-xl?modelVersionId=290640 |
| Fair AI Public License 1.0-SD | https://freedevproject.org/faipl-1.0-sd/ |
| Kohaku-XL Zeta (HF) | https://huggingface.co/KBlueLeaf/Kohaku-XL-Zeta |
| FLUX 官方文档 | https://github.com/black-forest-labs/flux/blob/main/docs/text-to-image.md |
| BFL 非商用许可条款 | https://bfl.ai/legal/non-commercial-license-terms |

## 游戏王卡图专项

| 资源 | URL |
|---|---|
| Yu-Gi-Oh! card art SDXL (Civitai) | https://civitai.com/models/130658/yu-gi-oh-card-art-sdxl?modelVersionId=143400 |
| 同上（CivArchive，含完整提示词范式） | https://civitaiarchive.com/models/130658?modelVersionId=143400 |
| 配套自定义节点 | https://github.com/nicolai256/comfyUI_Nodes_nicolai256 |
| 配套底模 Anime Art Diffusion XL | https://civarchive.com/models/117259/anime-art-diffusion-xl |
| HF LoRA 镜像 | https://huggingface.co/rml94867530922/ygo-loras |
| PixAI 镜像 | https://pixai.art/zh/model/1733739673061451542 |
| NGA 中文讨论 | https://ngabbs.com/read.php?tid=41109238 |
| 即刻 App 实践分享 | https://m.okjike.com/originalPosts/66becd9ba76a0c9d65ec3ccc |

## 插件与工具

| 资源 | URL |
|---|---|
| ComfyUI_IPAdapter_plus | https://github.com/cubiq/ComfyUI_IPAdapter_plus |
| h94/IP-Adapter 官方模型 | https://huggingface.co/h94/IP-Adapter |
| h94/IP-Adapter-FaceID | https://huggingface.co/h94/IP-Adapter-FaceID |
| ComfyUI_InstantID | https://github.com/cubiq/ComfyUI_InstantID |
| PuLID_ComfyUI | https://github.com/cubiq/PuLID_ComfyUI |
| ComfyUI-RMBG（BiRefNet 等） | https://github.com/1038lab/ComfyUI-RMBG |
| Kohya_ss（LoRA 训练） | https://github.com/bmaltais/kohya_ss |
| OneTrainer（LoRA 训练） | https://github.com/Nerogar/OneTrainer |
| ai-toolkit（LoRA 训练） | https://github.com/ostris/ai-toolkit |
| ComfyUI-to-Python-Extension | https://github.com/pydn/ComfyUI-to-Python-Extension |
| OpenModelDB（放大模型库） | https://openmodeldb.info/ |
| comfyops-mcp workflow 转换工具 | https://github.com/sandraschi/comfyops-mcp |
| 官方 WebSocket 调用示例 | https://github.com/Comfy-Org/ComfyUI/blob/master/script_examples/websockets_api_example.py |
| 官方 HTTP 调用示例 | https://github.com/Comfy-Org/ComfyUI/blob/master/script_examples/basic_api_example.py |

---

# 未验证 / 需实测确认的条目

以下条目在本次调研中**未能取得一手可验证来源**（主要是 GitHub 原始文件与部分 HF 模型卡在本环境网络不可达），落地前请实测确认：

1. `GET /models` 与 `GET /models/{folder}` 在**自托管版**的精确响应结构（建议直接用 `/object_info` 方案替代）。
2. `GET /object_info` 完整响应的**逐字段**结构（本文给出的 schema 是基于官方节点文档的参数表 + 通用约定推导的，字段名 `input.required` / `input.optional` / `output` / `output_name` / `category` / `output_node` 在社区实现中被广泛引用，但未逐字核对源码）。
3. `execution_start` / `execution_cached` / `execution_success` / `execution_interrupted` 的**精确 data 字段名**（官方 mintlify 文档只对 5 种消息做了带示例的完整记录）。**工程上建议只用 `executing(node==null)` 作为完成判据。**
4. `ReferenceOnlySimple` 与 `ReferenceLatent` 的**精确 class_type 拼写与 inputs**。
5. `GET /upload/image` 的精确 multipart 字段名（`image` / `overwrite` 为社区通行约定）。
6. ComfyUI **核心** BiRefNet 去背景节点的 `class_type`（核心已内建，但节点名未取得一手文档）。
7. 完整的 **44 个 sampler / 9 个 scheduler** 枚举值清单（本文只给出了开头若干个 + 常用值；**必须运行时从 `/object_info/KSampler` 读取**）。
8. **NoobAI-XL** 的官方推荐 CFG/steps（HF README 抓取失败）。
9. **Kohaku-XL** 各版本的推荐参数与授权细则。
10. SD1.5 系（Anything / Counterfeit / MeinaMix / Cetus-Mix）的官方页面与参数。
11. 各 ControlNet 模型（`controlnet-union-sdxl-1.0` by xinsir、`controlnet-openpose-sdxl`）的 HF 官方页面。
12. ComfyUI LoRA 训练节点（`TrainLoraNode` / `LoraModelLoader`）的精确 `class_type` 与 inputs。
13. 本地 LLM 节点插件（comfyui-ollama / comfyui_LLM_party / ComfyUI-IF_AI_tools / ComfyUI-GGUF）的仓库 URL 与节点名。
14. `ComfyUI_BiRefNet_ll`、`ComfyUI-rembg`、`ComfyUI-BRIA_AI-RMBG` 的精确 `class_type`。
15. `workflow_utils.py` 等社区转换脚本的**源码级**验证（仅见搜索索引描述）。
