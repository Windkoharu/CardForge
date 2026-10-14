# 角色三视图（设定稿） —— ComfyUI 工作流使用说明

> 由 **CardForge `cardforge.art`** 自动生成。工作流文件：`final_workflow_character_sheet.json`

## 1. 怎么用

1. 打开 ComfyUI（本机默认 `http://127.0.0.1:8188`）。
2. 把 `final_workflow_character_sheet.json` **直接拖进 ComfyUI 画布**（或菜单 Workflow → Open 选中它）。
3. 检查三个 Loader 节点的下拉值是否是**你本机实际有**的模型（见下面「需要的模型」一节）。下拉里选不到 = 文件不在对应目录。
4. 直接点 **Queue** 就能出图。
5. 想复现当前这张：seed 已经固定为 `10286342475651303898`，`control_after_generate` 保持 `fixed` 就是同一张；改成 `randomize` 才会每跑一次换一张。

## 2. 用途

给艾莉娅这类角色出**参考设定稿**：正面/侧面/背面同框 + 中性背景，作为后续卡图的角色锚点。用横版画布，一次出一张图。

## 3. 需要的模型

- 档案：**Krea 2 Turbo（本机首选）**（键 `krea2`，链路 `krea2`）
- 扩散模型 `UNETLoader.unet_name` = `krea2_turbo_bf16.safetensors`  → 放 `ComfyUI/models/diffusion_models/`
- 文本编码器 `CLIPLoader.clip_name` = `qwen3vl_4b_fp8_scaled.safetensors`，**type = `krea2`**  → 放 `ComfyUI/models/text_encoders/`
- VAE `VAELoader.vae_name` = `qwen_image_vae.safetensors`  → 放 `ComfyUI/models/vae/`

> ⚠️ **`CLIPLoader.type` 必须是 `krea2`（Krea 2 链路）**，写错必失败。
- 同 t2i_single

## 4. 参数含义（当前值 → 怎么调）

| 参数 | 当前值 | 含义 / 调整建议 |
|---|---|---|
| 画布 | 1536×1024 | 卡图窗比例 0.68567；832×1216 误差仅 0.21%。改尺寸请取 **16 的倍数**。|
| steps | 8 | Krea 2 是 8 步蒸馏模型，**别加步数**（会更糊更慢），想更清晰就升画布。 |
| cfg | 1.0 | **必须 1.0，不能设 0**（设 0 ComfyUI 会直接失败）。cfg=1 时**负向提示词基本不生效** —— 要排除的东西已写进正向描述。 |
| sampler | `euler` | 流匹配系用 euler 家族；Karras 调度器在流匹配模型上会直接失败。 |
| scheduler | `simple` | Krea 2 / Qwen-Image 用 `simple`；SDXL/SD1.5 常用 `normal` 或 `karras`。 |
| seed | `10286342475651303898` | **IS_CHANGED 缓存坑**：seed 与参数都不变时 ComfyUI 会判定 cache hit，直接复用旧输出文件而**不重新生成**。要出新图就换 seed。 |

## 5. 提示词（当前正向 / 负向）

**正向**

```text
character design reference sheet, three views of the same character side by side: front view, side view, back view, full body, identical outfit and proportions across all views, neutral plain light-grey background, even soft studio lighting, no text, no labels, no annotations
```

**负向**

```text
multiple characters, different outfits, inconsistent design, text, labels, annotation, arrows, watermark, signature, chibi, deformed
```

> ⚠️ 负向在 `cfg=1.0` 下**不参与计算**（那一遍前向不跑），上面这段只是留给你手动调高 cfg 时用。

## 6. 授权要点

链路：UNETLoader(krea2_turbo_bf16 / weight_dtype=default) → LoraLoaderModelOnly×0-2 → ModelSamplingFlux(max_shift=1.15) → CLIPTextEncode + ConditioningZeroOut → CFGGuider(cfg=1.0) → SamplerCustomAdvanced(RandomNoise + KSamplerSelect(euler) + BasicScheduler(simple, steps=8)) → VAEDecode → SaveImage。
CLIP 必须用 CLIPLoader(clip_name=qwen3vl_4b_fp8_scaled.safetensors, type="krea2")，VAE 用 VAELoader(qwen_image_vae.safetensors) —— type 写错必失败。
参数口径：**8 步 / cfg 1.0 / euler / simple / shift 1.15**。这是蒸馏少步模型，别沿用 SD 的 30 步（会更糊更慢）；cfg 不能设 0（ComfyUI 会直接失败）。
cfg=1.0 时**负向提示词基本不生效**（那一遍前向不跑）：要排除的东西必须写进正向描述，例如把「背景是干净的纯色空墙，画面里没有任何文字」写进正向。
画布取 16 的倍数；2:3 → 1024×1536，卡图窗比例 0.68567 → **832×1216 最贴合（误差 0.21%）**。
授权：Krea 2 Community License（含 Acceptable Use Policy）。自托管、个人/研究用途清晰；**商用与「在允许变现的平台上推理」需自行核对 Krea 的最新条款**，本工程不代为解释。禁止 CSAM / 未成年性化 / NCII / 诽谤类内容。

## 7. 节点结构（共 15 个节点 / 16 条连线）

```text
  [1] UNETLoader
  [2] CLIPLoader
  [3] VAELoader
  [4] ModelSamplingFlux
  [5] CLIPTextEncode
  [6] CLIPTextEncode
  [7] ConditioningZeroOut
  [8] CFGGuider
  [9] RandomNoise
  [10] KSamplerSelect
  [11] BasicScheduler
  [12] EmptyLatentImage
  [13] SamplerCustomAdvanced
  [14] VAEDecode
  [15] SaveImage
```

工作流指纹（**忽略 seed**）：`657a50a1235df294`

## 9. 排障

| 症状 | 处理 |
|---|---|
| 下拉里选不到模型 | 文件不在 `ComfyUI/models/<对应目录>/`；放进去后在界面点一次刷新 |
| 提交即报 400 | 多半是 `class_type` 拼错或 COMBO 值不在候选里；看 `node_errors` 指出的节点 |
| 重跑还是同一张 | `IS_CHANGED` 缓存：换 seed，或改 `filename_prefix` |
| 图上有文字/水印 | Krea 2 在 cfg=1 下负向无效 → 把「画面里没有任何文字」写进**正向** |
| 显存不足 | 降画布 → 去掉大 LoRA → `POST /free {"unload_models":true}` |

*导出时 ComfyUI 在线——工作流已按本机实际模型与节点填写。*
