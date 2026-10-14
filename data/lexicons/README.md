# 游戏王制卡术语表（Lexicons）

可机器读取的多语言术语数据，供制卡软件生成卡名、卡类行与效果文时做译名对照与 PSCT 句式校验。

| 文件 | 内容 | 大小 |
|---|---|---|
| `terms.json` | 213 条术语 × 10 种语言 | 117,897 字节 |
| `psct_patterns.json` | PSCT 标点／连接词／HOPT／编号规则 | 15,855 字节 |
| `_build_lexicons.py` | 生成脚本（可重跑复现两个 JSON） | 77,686 字节 |

---

## 1. 数据来源

### 1.1 官方来源（`confidence: "official"`）

| 来源 | 用途 |
|---|---|
| [`db.yugioh-card-cn.com` 卡片检索](https://db.yugioh-card-cn.com/card_search.action.html) | **官方简中译名的唯一权威来源**。7 属性、26 种族、各类卡种与效果的筛选器用词全部逐字取自该页面的筛选面板 HTML。 |
| [Konami PSCT 第 3 篇：Conditions, Activations, and Effects](https://www.yugioh-card.com/en/play/psct/psct-3/) | `CONDITIONS : ACTIVATION ; RESOLUTION` 三段式、"有冒号或分号即入连锁"、cost/target 的位置。 |
| [Konami PSCT 第 7 篇：Conjunction Functions](https://www.yugioh-card.com/en/play/psct/psct-7/) | `then` / `also` / `and if you do` / `and` 连接词四象限的官方定义。 |
| [Konami PSCT 第 1、2、4、5、6 篇](https://www.yugioh-card.com/en/play/psct/) | 术语变更、Built-In Special Summon 括号写法、触发时机。 |
| [Yugipedia: Once per turn](https://yugipedia.com/wiki/Once_per_turn?action=raw) | HOPT 三种写法（`Once per turn` / `You can only use…` / `You can only gain this effect…`）及其重置规则。 |

### 1.2 社区整理来源（`confidence: "community"`）

Yugipedia 的 `?action=raw` 接口（**必须带 `?action=raw`，否则返回 403**）。逐页解析
`{{In other languages}}` / `{{Infobox/Archetype/ExtendedName}}` 模板中的
`ja_name` / `zh_name` / `tc_name` / `sc_name` / `ko_name` / `fr_name` / `de_name` /
`it_name` / `pt_name` / `es_name` 字段。

覆盖的页面类型：属性页、种族页、卡种页（通常/效果/仪式/融合/同步/超量/灵摆/连接/
衍生物/魔法与陷阱各子类）、能力页（协调/联合/二重/反转/灵魂/卡通/特殊召唤/暗黑同调）、
动作与区域页、规则页（Problem-Solving Card Text、Activation condition、Cost、Quick Effect、Card text）。

### 1.3 无法验证（`confidence: "unverified"`）

全字段为 `null`，仅保留 key 占位。见第 4 节。

---

## 2. 可信度分级

`confidence` 字段取值与含义：

| 值 | 条数 | 含义 |
|---|---:|---|
| `official` | 147 | 直接取自官方简中数据库筛选器用词，或 Konami PSCT 官方文章原文。可直接用于成品卡面。 |
| `community` | 64 | 由 Yugipedia 模板或官方卡片文本实例整理。译名可靠，但「整句式效果文」的具体字面可能因卡而异（不同卡片会微调措辞）。 |
| `unverified` | 2 | 未在权威来源中找到，全语言 `null`。**不可用于成品，需人工确认。** |

### 关于官方简中的两条重要约定

1. **种族一律带「族」字后缀。** 数据库筛选器写作 `魔法师族` / `电子界族` / `幻想魔族` / `幻神兽族` / `创造神族`，
   而 Yugipedia 的 `sc_name` 常写作不带后缀的 `魔法师` / `电子界` 等。`terms.json` 的 `zh_cn`
   统一采用**数据库用词（带「族」）**，因为制卡软件的卡类行需要这个形态：
   `龙族／效果` 而非 `龙／效果`。
2. **同步 / 超量 / 连接 / 协调 / 联合 / 二重 / 反转** 为官方简中定名，与民间译名不同：

   | 官方简中 | 常见民间译名 |
   |---|---|
   | 同步 | 同调 |
   | 超量 | XYZ |
   | 连接 | 链接 / Link |
   | 协调 | 调整 / Tuner |
   | 联合 | 同盟 / Union |
   | 二重 | 双面 / Gemini |
   | 反转 | 翻转 / Flip |
   | 上级召唤 | 祭品召唤 / 解放召唤 |

### 关于繁体（`zh_tw`）的重要提示

繁体官方译名存在**地区双轨**，本表统一采用**台湾 / 香港（Konami 亚洲繁体）用词**：

| 概念 | 本表 `zh_tw`（台港） | 另一轨（部分旧印刷 / 民间） |
|---|---|---|
| 灵摆 | `鐘擺` | `靈擺` |
| 额外卡组 | `額外牌組` | `額外卡組` |
| 场地 | `場地` | `場地` |
| 超量 | `超量`（同简中） | `超量` |
| 同步 | `同步`（同简中） | `同調` |

若你的软件面向大陆简体用户，请只取 `zh_cn`；面向台湾用户取 `zh_tw`。
**不要把 `zh_cn` 用字符转换工具「转」成 `zh_tw`** —— `灵摆`→`靈擺`、`额外`→`額外` 这类
逐字转换在「钟摆 vs 灵摆」这一处会直接转错。

---

## 3. 语言覆盖率统计

术语总数：**213**。

| 语言 | 字段 | 有值条数 | `null` 条数 | 覆盖率 |
|---|---|---:|---:|---:|
| 英文 | `en` | 213 | **0** | 100.0% |
| 日文 | `ja` | 212 | **1** | 99.5% |
| 简体中文 | `zh_cn` | 209 | **4** | 98.1% |
| 繁体中文 | `zh_tw` | 208 | **5** | 97.7% |
| 意大利文 | `it` | 205 | **8** | 96.2% |
| 葡萄牙文 | `pt` | 205 | **8** | 96.2% |
| 德文 | `de` | 204 | **9** | 95.8% |
| 西班牙文 | `es` | 204 | **9** | 95.8% |
| 法文 | `fr` | 203 | **10** | 95.3% |
| 韩文 | `ko` | 169 | **44** | 79.3% |

> `null` 表示**在权威来源中确实找不到**，不是漏采。全部 213 条术语均经过
> 至少一个来源核对，未使用任何推测值。

### 按分类

| category | 条数 | 说明 |
|---|---:|---|
| `attribute` | 7 | 暗 / 光 / 地 / 水 / 炎 / 风 / 神 |
| `race` | 26 | 全部种族，含 幻神兽族 / 创造神族 / 幻龙族 / 电子界族 / 幻想魔族 |
| `card_type` | 33 | 卡种、魔法陷阱各子类、能力（协调/联合/二重/反转/灵魂/卡通/特殊召唤/暗黑同调/极巨） |
| `action` | 46 | 检索、召唤、破坏、除外、cost、无效、控制权等 |
| `zone` | 22 | 卡组/手卡/墓地/除外/场上各区 + 全部阶段与步骤 |
| `stat` | 17 | 攻击力、守备力、等级、阶级、灵摆刻度、连接标记、素材等 |
| `psct_phrase` | 62 | PSCT 标准句式短语（要求 ≥40，实际 62） |

### 韩文覆盖率偏低的原因

Yugipedia 的 `{{In other languages}}` 模板对**规则/动作类**页面（`add to hand`、
`destroy`、各 PSCT 句式等）通常只填 `ja/zh/fr/de/it/pt/es`，不填 `ko_name`，
因此 44 条韩文缺口集中在 `action` 与 `psct_phrase` 两类。
卡种、种族、属性等**具体名词**的韩文覆盖率是完整的。
如需补全，应改采韩国官方卡片数据库 `db.yugioh-card.com/yugiohdb/?request_locale=ko`，
本次未采集。

---

## 4. 未查到而留 `null` 的关键术语清单

### 4.1 整条完全 `null`（`confidence: "unverified"`，2 条）

| key | 英文 | 说明 |
|---|---|---|
| `card_non_effect_monster` | non-Effect Monster | Yugipedia 对应页面 404，官方库无独立筛选器。简中通常表述为「效果怪兽以外的怪兽」。 |
| `stat_ritual_material` | Ritual Material | 无独立术语页；仪式召唤的祭品在卡文中直接写作「…作为仪式召唤的祭品」。 |

### 4.2 简中 `null`（4 条）

| key | 英文 | 说明 |
|---|---|---|
| `card_non_effect_monster` | non-Effect Monster | 同上 |
| `card_dark_synchro` | Dark Synchro Monster | 暗黑同调仅存在于动画/漫画/Tag Force，OCG 无实体卡，故无官方简中名 |
| `card_maximum` | Maximum Monster | Rush Duel 专属，未进入 OCG/简中 |
| `stat_ritual_material` | Ritual Material | 同上 |

### 4.3 繁体 `null`（5 条）

4.2 的 4 条，外加：

| key | 英文 | 说明 |
|---|---|---|
| `stat_pendulum_scale` | Pendulum Scale | Yugipedia 未填 `tc_name`；台港官方繁中的「靈擺刻度／鐘擺刻度」未找到可直接引用的官方页面，故不臆测。简中 `灵摆刻度` 已确认。 |

### 4.4 日文 `null`（1 条）

`stat_ritual_material`（Ritual Material）。

### 4.5 西欧语言缺口（`de` 9 / `fr` 10 / `it` 8 / `pt` 8 / `es` 9）

集中在同一批「无独立术语页」或「Rush Duel / 动画专属」的词条：

`race_creator_god`、`card_non_effect_monster`、`card_dark_synchro`、`card_maximum`、
`card_ability`、`act_add_to_hand`、`stat_link_material`、`stat_ritual_material`、
`psct_hopt_name_apply`，外加 `fr` 的 `act_link_summon`。

> 这些都是**真实缺口**：例如 `act_add_to_hand`（「加入手卡」单独成词）在西文卡文中
> 从来没有独立名词形态，永远是动词短语（`add ... to your hand`），所以词典里没有可填的名词项。

### 4.6 未采集但可能补全的官方源

- **官方日文数据库** `https://www.db.yugioh-card.com/yugiohdb/` —— 本次未采集（需处理 JS 渲染与 `request_locale`）。
  补上后可显著提升 `ja` 与整套 `psct_phrase` 的置信度。
- **官方韩文数据库** —— 可补 44 条韩文缺口。
- **官方中文规则页面** `https://www.yugioh-card-cn.com/` 的规则书 PDF —— 可把 `zone`/`action`
  类由 `community` 提升为 `official`。

---

## 5. 数据结构

### `terms.json`

```jsonc
{
  "_meta": {
    "generated": "2026-10-13",
    "sources": ["..."],
    "source_index": { "db_cn": "...", "psct3": "...", "ygo_hopt": "..." },
    "total_terms": 213,
    "by_category": { "action": 46, "...": 0 },
    "null_counts": { "en": 0, "zh_cn": 4, "...": 0 }
  },
  "terms": {
    "act_search": {
      "key": "act_search",
      "en": "add ... from your Deck to your hand",
      "zh_cn": "从卡组把…加入手卡",
      "zh_tw": "從牌組將…加入手牌",
      "ja": "デッキから…手札に加える",
      "ko": null,
      "de": "von deinem Deck ... der Hand hinzufügen",
      "fr": "ajouter ... depuis votre Deck à votre main",
      "it": "aggiungere ... dal tuo Deck alla tua mano",
      "pt": "adicionar ... do seu Deck à sua mão",
      "es": "añadir ... de tu Deck a tu mano",
      "category": "action",
      "confidence": "community",
      "source": "https://yugipedia.com/wiki/Add_a_card?action=raw"
    }
  }
}
```

字段顺序固定为 `key, en, zh_cn, zh_tw, ja, ko, de, fr, it, pt, es, category, confidence[, source]`，
便于直接按序读取而不依赖键名。每条的 `source` 指向该条实际被核对的那一个页面。

### `psct_patterns.json`

顶层键：

| 键 | 内容 |
|---|---|
| `punctuation` | 6 条标点规则：`：`/`；`/`。`/`（）`/`●`/`①`，各带 `role` 与多语言符号 |
| `conjunctions` | 5 条连接词，各带 `resolution_order`、`both_required`、`requires_a_for_b`、`aborts_b_if_a_fails` |
| `conjunction_quadrants` | 官方四象限网格（`then` / `also` / `and if you do` / `and` / `also, after that`） |
| `hopt` | 6 种 HOPT 写法，各带 `scope`、`strictness`、`reset_on_leave`、`placement` |
| `numbering` | ①②③ 符号表 + 编号规则 6 条 |
| `structure` | `CONDITIONS : ACTIVATION ; RESOLUTION` 三段式分解 |
| `timing_keywords` | `when`（严格）/ `if`（宽松）/ `You can`（可选）三档 |
| `sources` | 该文件的来源 URL |

`strictness` 由宽到严：`apply` < `activate` < `use`。
`hopt` 中 `reset_on_leave: true` 表示该卡离场或翻里侧后限制重置。

---

## 6. 重新生成

```powershell
cd D:\游戏王DIY设计\data\lexicons
python _build_lexicons.py
```

脚本无第三方依赖，仅用标准库。数据全部内联在脚本的 `ROWS` 表中，
每条都带 `source` 字段指向采集页面；修改数据后重跑即可。

校验：

```powershell
python -c "import json;json.load(open(r'terms.json',encoding='utf-8'))"
python -c "import json;json.load(open(r'psct_patterns.json',encoding='utf-8'))"
```

两个文件均为 UTF-8（无 BOM）合法 JSON。

---

## 7. 使用建议

1. **卡类行**用 `race` + `card_type`，简中取 `zh_cn`（带「族」后缀）。例：
   `龙族／协调／效果`。
2. **效果文**用 `psct_phrase` 的对应语言整句，不要逐词拼接 —— PSCT 的固定搭配
   （`这个卡名的①②的效果1回合各能使用1次。`）是整句模板，拆词拼装会产生非官方措辞。
3. **校验器**可直接读 `psct_patterns.json`：检查效果文是否含 `：`/`；` 来判断该不该入连锁；
   检查连接词与 `resolution_order` / `both_required` 是否自洽。
4. **发布前**务必过滤掉 `confidence == "unverified"` 的条目，并人工复核
   `confidence == "community"` 的整句效果文。
