# 游戏王效果文本规范化（PSCT）与卡牌设计方法论 — 调研报告

> 用途：为「AI 制卡软件」提供**可编码成校验规则**的规范清单 + 可验证 URL。
> 调研方式：web_search / web_fetch 实抓。凡未实抓或来源为社区经验值的，均标注可信度。
> 最后更新：本次会话。

---

## 目录

- [A. PSCT（Problem-Solving Card Text）完整规范](#a-psctproblem-solving-card-text完整规范)
- [B. 各语言文本规范与可校准数据库](#b-各语言文本规范与可校准数据库)
- [C. 卡牌设计方法论与平衡准则](#c-卡牌设计方法论与平衡准则)
- [D. 现存的 AI 制卡 / NL→Lua / PSCT 校验尝试](#d-现存的-ai-制卡--nlua--psct-校验尝试)
- [E. 汇总：可直接编码的校验规则清单](#e-汇总可直接编码的校验规则清单)
- [F. 不确定项与未验证项](#f-不确定项与未验证项)

---

# A. PSCT（Problem-Solving Card Text）完整规范

## A0. 历史与目标

| 项 | 内容 | 来源 |
|---|---|---|
| 起源 | 2011 年 5 月由 **Kevin Tewart** 在 Konami TCG Strategy Site（北美）以 7 篇博客连载公布 | [PSCT Part 1](https://www.yugioh-card.com/en/play/psct/psct-1/) |
| 生效 | **2011 年 7 月**起，所有 TCG 新印刷卡采用；首批发售为 `Generation Force`（GENF）与 `Starter Deck: Dawn of the Xyz` | [Yugipedia PSCT](https://yugipedia.com/wiki/Problem-Solving_Card_Text)、[PSCT Part 6](https://www.yugioh-card.com/en/play/psct/psct-6/) |
| 动机 | 卡牌数量接近 5000 张，口语化表述导致同一句式对应不同裁定；官方希望「读卡即可解决绝大多数裁定争议」 | [PSCT Part 1](https://www.yugioh-card.com/en/play/psct/psct-1/) |
| 三大目标（官方原文） | 1. The text needed to be **precise**. 2. The text still needed to be **easy to read**. 3. The text can't sound like a **textbook**. | 同上 |
| 旧卡处理 | 旧卡在复刻时改写；官方锦标赛中**任何版本实体卡一律按最新勘误文本处理** | [Yugipedia PSCT](https://yugipedia.com/wiki/Problem-Solving_Card_Text) |

**官方 PSCT 系列全文目录（全部可访问）**

1. [Part 1: Reading the Cards of Tomorrow](https://www.yugioh-card.com/en/play/psct/psct-1/) — 2011-05-20
2. [Part 2: New Words & Phrases](https://www.yugioh-card.com/en/play/psct/psct-2/) — 2011-05-23
3. [Part 3: Conditions, Activations, and Effects](https://www.yugioh-card.com/en/play/psct/psct-3/) — 2011-06-01
4. [Part 4: The Clues on Your Cards](https://www.yugioh-card.com/en/play/psct/psct-4/) — 2011-06-01
5. [Part 5: Special Summons](https://www.yugioh-card.com/en/play/psct/psct-5/) — 2011-07-27
6. [Part 6: Finding Clues in TU6 & GENF](https://www.yugioh-card.com/en/play/psct/psct-6/) — 2011-08-08
7. [Part 7: 2012 Update – Conjunction Functions](https://www.yugioh-card.com/en/play/psct/psct-7/) — 2012-12-12

**欧洲站镜像（内容相同，便于长期引用）**：[Understanding Card Text Part 1–7](https://www.yugioh-card.com/eu/play/understanding-card-text/part-3-conditions-activations-and-effects/)

---

## A1. 标点语义的精确规则（★核心，可直接编码）

官方原文（Part 3）：

> **Conditions (green text) are now always followed by a colon (:).**
> **Activation text (red) is separated from the card effects (blue) by a semicolon (;).**
> **The basic structure is CONDITIONS : ACTIVATION ; RESOLUTION.**

### A1.1 三段式结构

```
[发动条件 / 次数限制]  ：  [发动时做的事：cost + 取对象]  ；  [效果处理]
        ↑ 冒号前                  ↑ 分号前                    ↑ 分号后
```

### A1.2 各标点的精确语义表

| 标点 | 位置 | 语义 | 编码规则 |
|---|---|---|---|
| `：`（冒号） | 条件与后续之间的分隔 | 其**之前**为发动条件（时点、场合、次数限制、控制权/场面要求）。**条件只需在发动时满足**；发动后即使条件不再成立也不影响处理 | 冒号前若出现 cost 类动词（支付/丢弃/解放/破坏）→ **报错**（cost 必须在冒号后、分号前） |
| `；`（分号） | 发动时处理与处理时效果的分隔 | 其**之前**（冒号之后）为 **发动时**发生的事：**cost** 与 **取对象**。其**之后**为**效果处理** | 分号前若出现「从卡组加入手卡 / 特殊召唤 / 破坏对方卡」等结果性动作 → **报错**（那是效果处理，不是 cost） |
| `。`（句号） | 句子分隔 | 官方未把句号定义为「效果处理分段符」；**真正的分段符是「效果编号 ①②③ + 换行」**。句号用于分隔同一张卡上互相独立的**效果**或**效果外文本** | 不要把「句号」当作 PSCT 语义标记；应以「编号 / 换行」为效果边界 |
| `・`（中点） | 卡名内部 | 仅用于卡名排版（如 `D・D・クロウ` / `D.D. Crow`）；**无语法语义**。日文卡名中常见的 `・` 也是排版用 | 卡名归一化时需决定是否保留中点（跨语言匹配会踩坑） |
| `（）`（圆括号） | 多种 | ① **内置特殊召唤的来源地**：「（从手卡）」「（从额外卡组）」等 → 表示这是**不入连锁的召唤手续**，可被「无效召唤」类效果无效 ② 补充说明/限制条件，如「（Quick Effect）」「（这个卡名的效果1回合只能使用1次）」③ 数值/属性/种族的补充，如衍生物「（植物族/地属性/等级2/攻800/守800）」 | 见 A1.4 |
| `●`（圆点/子弹） | 多选/多段效果 | 带编号效果的替代写法，用于「选1个适用」或「全部适用」的多段效果 | 见 A1.5 |
| `①②③`（圈号） | 效果编号 | 用于标记**多个效果**，是 PSCT 后期（第 9 期起，OCG）最重要的分段手段 | 见 A1.6 |

### A1.3 冒号/分号存在性 = 是否入连锁（最强的一条硬规则）

官方原文（Part 3，加粗强调）：

> **BIG TIP: If there's a colon or semicolon in the text, that always means an effect that starts a chain. If there is no colon or semicolon, the effect does NOT start a chain and cannot be chained to.**

| 情况 | 是否入连锁 | 例 |
|---|---|---|
| 怪兽效果含 `：` 或 `；` | ✅ 入连锁 | `Sangan`、`Zombie Master`、`Kinetic Soldier` |
| 怪兽效果**不含**任何 `：` `；` | ❌ 不入连锁 | `Cyber Dragon`、`Blade Knight`、`Bountiful Artemis`、`Vision HERO Trinity` |
| 魔法/陷阱**卡的发动** | ✅ **永远**入连锁（即使文本里没有冒号分号） | `Creature Swap`（无标点但仍入连锁） |
| 魔法/陷阱**效果的发动**（已在场上表侧） | 若含 `：` 或 `；` → 入连锁 | `Fusion Gate`、`Black Garden` 第 2 效果 |

**编码校验点**：对怪兽效果，「是否含冒号/分号」与「是否被 `EFFECT_TYPE_*` 的 ignition/trigger/quick 类型」必须一致；若声明为不入连锁的永续型效果却写了冒号 → 报错。

### A1.4 括号的用法（官方规则汇总）

| 括号用法 | 语义 | 来源 |
|---|---|---|
| `（从手卡）` `（从额外卡组）` `（从墓地）` 等 | **内置特殊召唤（Group 2）**：不入连锁；**且只有这类召唤可以被「无效召唤」类效果无效**（如 `Thunder King Rai-Oh`、`Horn of Heaven`） | [PSCT Part 5](https://www.yugioh-card.com/en/play/psct/psct-5/) |
| 无括号的特殊召唤（含 `：`/`；` 的效果召唤，或魔法陷阱召唤） | **效果召唤（Group 1）**：入连锁；**不能被「无效召唤」类效果无效**，只能被「无效卡的发动/效果」类无效 | 同上 |
| 同调/超量/灵摆/连接召唤 | 虽无括号，但**属于可被无效召唤的召唤** | 同上 |
| `（Quick Effect）` | 怪兽的诱发即时效果标记（2017 年 7 月后统一写法；此前为 `during either player's ...` 或 `(this is a Quick Effect)`） | [Yugipedia PSCT](https://yugipedia.com/wiki/Problem-Solving_Card_Text) |
| `（这个卡名的①②效果1回合各能使用1次）` | 次数限制子句，写在效果文本**开头** | 见 A6 |
| `（植物族/地属性/等级2/攻800/守800）` | 衍生物数值，顺序固定：**种族・属性・等级・攻・守**；攻守相同时写作 `攻800/守800`，日文社区模板指出「同数值可合并」 | [遊戯王オリカ@wiki カードテキストテンプレ](https://w.atwiki.jp/yugiorika/pages/12.html)（旧模板，注意其年代为 2008，术语已过时） |
| `（除了〜之外）` `（不取对象）` 等 | 补充限定 | — |

### A1.5 `●` 与「in sequence / (simultaneously)」（★官方规则，易漏）

来源：[Yugipedia PSCT — Text structure](https://yugipedia.com/wiki/Problem-Solving_Card_Text)（引用官方规则书 v10 p.52–53）

| 写法 | 语义 |
|---|---|
| `●A ●B` 且文本含 **`in sequence`** | 顺序适用（例：`Gravekeeper's Oracle`、`Advance Zone`） |
| `●A ●B` 且文本含 **`(simultaneously)`** | 同时适用（例：`Ryko, Lightsworn Hunter`、`Kunai with Chain`） |
| `●A ●B` 且**两者都未写** | 各自**分别组成连锁**（例：`Metaphys Horus`） |

> 注意：在 bullet 效果中，「each effect activated resolves **independent** of the success of the other(s)」——这与连接词的「一败俱败」逻辑不同，是**独立结算**。
> **编码校验点**：卡文含 2 个以上 `●` 时，必须显式出现 `in sequence` 或 `(simultaneously)`，否则应提示「将被解析为多个连锁块」。

### A1.6 `①②③` 效果编号规则

来源：官方卡文惯例 + [Yugipedia Card layout](https://yugipedia.com/wiki/Card_layout)（第 9 期起 OCG 引入）

- **作用**：把同一张卡上的多个效果明确分开，每个编号是**一个独立效果**（独立入连锁、独立被无效）。
- **与段落的关系**：编号效果通常**每个占一行**（换行后接编号）。
- **灵摆怪兽**：编号是**连续的**，跨越两个文本框——**怪兽效果的编号在前，灵摆效果的编号在后**（即灵摆效果不会重新从 ① 开始，而是接在怪兽效果编号之后）。这是 DIY 最常写错的地方之一。
- **次数限制子句写在哪**：统一写在效果文本**最开头**，格式为「这个卡名的①②效果1回合各能使用1次。」/「You can only use each of the following effects of "X" once per turn.」
- **编号的引用**：正文中引用时用「这个卡名的②效果」。日文为「このカード名の②の効果」。
- 旧式写法 `●`（bullet）与 `①②③` 的区别：`●` 用于「选1个适用」/「同时/顺序适用」的多段效果（常见于魔法陷阱与部分怪兽效果），`①②③` 用于**彼此独立的多个效果**。

> ⚠️ 不确定项：`●` 与 `①②③` 的边界在官方文档中没有一条统一成文的规定，主要靠大量卡文归纳。建议编码时以「是否写了 in sequence / simultaneously」为准，而非以符号类型为准。

### A1.7 「卡」与「怪兽」的区分（★高频错误）

| 写法 | 语义 | 例 |
|---|---|---|
| 「〜**怪兽**」 | 只作用于怪兽区域的怪兽 | 「选对方场上1只怪兽破坏」 |
| 「〜**卡**」 | 作用于该玩家场上任意区域的卡（怪兽区/魔法陷阱区/灵摆区/场地） | 「选对方场上1张卡破坏」 |
| 「**怪兽卡**」 | 指**卡的种类**是怪兽卡（可在任何区域） | 「从卡组把1只怪兽卡送去墓地」 |
| 「场上的卡」 vs 「场上的怪兽」 | 前者含魔法陷阱，后者不含 | — |
| 「这张卡」/「那张卡」 | **指示代词**：一旦卡片离开了当前区域，就不再是「这张卡/那张卡」（例外：陷阱怪兽在魔陷区↔怪兽区之间移动仍算；变里侧、控制权转移仍算） | [OCG Rule 基本用语](https://ocg-rule.readthedocs.io/zh-cn/latest/c02/%E5%9F%BA%E6%9C%AC%E7%94%A8%E8%AF%AD.html) |

**编码校验点**：破坏/除外/回到手卡类效果的候选集声明，必须与用词（怪兽 / 卡）匹配；同时校验「场所」字段（怪兽区域 / 魔法与陷阱区域 / 全部）。

### A1.8 「那个效果处理在〜之后」的时点判定（`in the Graveyard` 等）

官方 Part 6 要点：
- 「in the Graveyard」= 处理时必须**仍在墓地**才有效；否则失去参照点，效果消失（例：`Armory Arm`、`Elemental HERO Flame Wingman`）。
- 对应「（if it was there when ...）」/「(even if not)」这类括号补充。

---

## A2. 连接词语义的精确区分（★核心，官方 Part 7 原文表格）

来源：[PSCT Part 7: 2012 Update – Conjunction Functions](https://www.yugioh-card.com/en/play/psct/psct-7/)（官方原文）+ [Yugipedia 汇总表](https://yugipedia.com/wiki/Problem-Solving_Card_Text)

官方原文说明：
> The key differences between them are about **Timing** and **Causation**.
> If you're checking **activation eligibility**, you need to focus on **timing**. Look for **THEN** vs. **AND/ALSO/AND IF YOU DO**.
> If you're checking **to see how much of the effect you do**, look for **ALSO** vs. **THEN/AND IF YOU DO** vs. just **AND**.

### A2.1 官方四连接词（2012 年更新）

| 连接词 | 时间轴（Timing） | 因果（Causation） | 官方原例 |
|---|---|---|---|
| **`then`**（然后） | **顺序**发生，非同时 → 其后发生的事是「最后一个发生的事」，**会挡住 WHEN 触发** | **A 是 B 的必要条件**，反之不然。A 没做→停；B 做不了→A 照做 | `Heraldry Change`：`Special Summon 1 "Heraldic Beast" monster from your hand, then end the Battle Phase.` |
| **`also`**（也） | **视为同时** | **互不依赖**，能做的都做 | `Masked Ninja Ebisu` |
| **`and if you do`**（并且，若如此做） | **视为同时** | **A 是 B 的必要条件**，反之不然 | `Memory of an Adversary`: `You take damage..., and if you do, banish that monster.` |
| **`and`**（并且） | **视为同时** | **两者都必须做到**，做不到就**全都不做**（一败俱败） | `Number 53: Heart-eartH` |

官方补充：`and` 单独使用**现在很罕见**，只用于「高度受限、不可分割、全有全无」的效果；旧的 `and` 大多已改写为 `and if you do`。

### A2.2 官方未提及但已实装：`also, after that`（2014 年引入）

| 连接词 | 时间轴 | 因果 | 引入 |
|---|---|---|---|
| **`also, after that`** | **顺序** | **互不依赖**（两个都尽量做，但一个不成不影响另一个） | `Premium Gold`（2014） |

> ⚠️ 关键提示（Yugipedia 明确指出）：`also, after that` **从未在 PSCT 系列文章中被讨论过**，因为它在 2014 年才引入。

### A2.3 完整四象限表（可直接编码）

| 结算方式 ↓ / 必要条件 → | 都不必须 | 必须 A | 必须 A 和 B |
|---|---|---|---|
| **顺序（Sequentially）** | `also, after that` | `then` | *（无对应连接词）* |
| **同时（Simultaneously）** | `also` | `and if you do` | `and` |

> Yugipedia 补充：**不存在**「两部分都必需 + 不同时」的连接词。此关系偶尔出现（尤其**融合召唤/仪式召唤**效果），这些效果使用各自的固定句式、**不使用连接词**。唯一例外是 `Luminous Dragon Ritual`，用 `and` + 结尾 `after that` 表示该关系。

### A2.4 关键警告（易被忽略，必须编码进校验器）

官方/Yugipedia 原文：

> Conjunctives **only tell you what to do when an effect resolves** if it is no longer possible to apply some parts of the effect; they **do not tell you whether or not you can legally activate** a card or effect in the first place if it is not possible to apply some parts of the effect.

即：**连接词决定「结算时做多少」，不决定「能不能发动」。** 校验器不能因为用了 `then` 就放宽发动条件检查。

### A2.5 日文对应（★注意与英文不完全一一对应）

| 英文 | 日文 | 关系 |
|---|---|---|
| `and` | 「〜**し**、〜する」 | 同时 + 两者必需（一败俱败） |
| `then` | 「〜**その後**、〜する」 | 顺序 + A 必需 |
| `also` | 「〜**また**、〜する」 | 同时 + 互不依赖 |
| `and if you do` | 「〜し、**その場合**、〜する」 | 同时 + A 必需 |
| `also, after that` | 「〜**また、その後**、〜する」 | 顺序 + 互不依赖 |
| （追加/递进） | 「〜**さらに**、〜する」 | 追加处理（常与 また 混用，需以卡文实际裁定为准） |
| `if you do`（单独） | 「**そうした場合**」 | 前置处理成功才继续 |

> ⚠️ 不确定项：日文「さらに」在英文中并无固定单一对应词（有时对应 `also`，有时是分句的 `Additionally`），建议**以日英官方同卡文本对照**建表，而非硬编码映射。英文 `and if you do` 的日文常见写法是「その場合」，也存在「〜し、〜する」的变体，需按卡核对。

---

## A3. 效果分类与句式模板（★可直接编码）

### A3.1 六大类（OCG 官方分类）

来源：[OCG Rule 怪兽的效果分类](https://ocg-rule.readthedocs.io/zh-cn/latest/c02/%E6%80%AA%E5%85%BD%E7%9A%84%E6%95%88%E6%9E%9C%E5%88%86%E7%B1%BB.html)（中文权威整理，基于官方规则书）

| # | 类型 | 是否入连锁 | 咒文速度 | 句式模板（中文/日文/英文） | 触发条件 |
|---|---|---|---|---|---|
| 1 | **起动效果** | ✅ | 1 | 「**1回合1次，自己主要阶段才能发动。**」<br>「1ターンに1度、自分メインフェイズに発動できる。」<br>`Once per turn: You can ...` | 自己主要阶段主动宣言 |
| 2 | **诱发效果** | ✅ | 1 | 「**〜した時/場合に発動できる。**」<br>「〜した時/場合に発動できる。」<br>`When/If ...: You can ...` | 事件发生时自动满足条件 |
| 3 | **诱发即时效果** | ✅ | **2** | 「**对方回合/伤害步骤也能发动**」→ 英文 `(Quick Effect): You can ...` | 任意时点（有速度 2） |
| 4 | **永续效果** | ❌ | — | **无冒号无分号**的持续适用句<br>`While ... this card gains 400 ATK.` | 持续适用，不宣言 |
| 5 | **无种类效果** | ❌ | — | 不入连锁、也不算永续效果的规则性效果（如召唤手续、"不能特殊召唤"） | — |
| 6 | （召唤手续 / 效果外文本） | ❌ | — | 「这张卡不能通常召唤。」「这个卡名在规则上当作〜使用。」 | 非效果文本，**不可被无效** |

### A3.2 诱发效果：时 vs 场合 / when vs if（★最易错）

**英文侧（官方与社区一致）**

| 写法 | 能否「错过时点」 | 说明 |
|---|---|---|
| `When ... : You can ...`（**when + 可选**） | ⚠️ **会**错过 | 必须是「最后发生的事」才能发动 |
| `When ... : ...`（**when + 必发/强制**） | ❌ 不会 | 强制效果不会错过 |
| `If ... : You can ...`（**if + 可选**） | ❌ 不会 | 只问「是否发生过」，不看时点 |

来源：[YGOPRODeck - Important Yu-Gi-Oh! Rulings: Missing the Timing](https://ygoprodeck.com/article/important-yu-gi-oh-rulings-missing-timing-14035)、[Deciphering Difficult Card Texts](https://ygoprodeck.com/article/deciphering-difficult-card-texts-17506)

> 官方已不再使用「missing the timing」这一术语（该社区文章在 Bibliography 中明确说明），但规则仍有效。

**日文侧（与英文不完全对称，★重要）**

来源：[カードラボ【遊戯王】「時」と「場合」【ルール】](http://www.c-labo.jp/blog/457435/)

| 写法 | 语义 |
|---|---|
| 「〜した**時**、〜できる」 | 有严格时点，**会**错过（タイミングを逃す） |
| 「〜した**場合**、〜できる」 | 只问是否发生过，**不会**错过（タイミングを逃さない） |
| 「〜した**時**、〜する」（必发） | 不会错过 |

**日文「時/場合」的额外一层语义（英文没有的）**：当触发事件是「卡/效果的发动」时，
- 「〜が発動した**時**」→ **直接连锁**该发动（チェーンして発動）
- 「〜を発動した**場合**」→ 等该效果**处理完毕之后**再发动

**官方例证（c-labo 原文）**：
- `ナチュル・ロック`「罠カードが発動した**時**」→ 连锁陷阱卡的发动发动；若对方已连锁其他卡，则无法发动
- `オルターガイスト・マルチフェイカー`「罠カードを発動した**場合**」→ 该陷阱处理完毕后再发动
- `雷神龍－サンダー・ドラゴン`「手札で発動した**時**」→ 连锁；`雷劫龍－サンダー・ドラゴン`「手札で発動した**場合**」→ 处理完毕后

> ★**给 AI 制卡软件的关键结论**：中文/英文的「场合/if」与日文「場合」在「是否错过时点」上语义一致，但**日文的「時」额外携带「直接连锁 vs 处理后再发动」的语义**，而英文的 `When` 并不携带这一层。若软件同时生成日中英三语，**不能做逐词直译**。

### A3.3 诱发即时效果（Quick Effect）写法

- 2017 年 7 月后统一为：`(Quick Effect): You can ...`（冒号**前**标注 Quick Effect）
- 2017 年 7 月前：`During either player's ...` 或句末 `(this is a Quick Effect)`
- 中文：「这个效果在对方回合也能发动。」/「对方回合，〜才能发动。」
- **DIY 红旗**：官方规则中**只有怪兽卡有诱发即时效果**；魔法/陷阱卡（含灵摆效果）**没有**「quick effect」这一说法——它们靠卡种本身（速攻魔法、陷阱）获得速度 2。社区文章明确指出这是「unspoken rule」。
  来源：[YGOPRODeck - How to make better Custom Cards](https://ygoprodeck.com/article/how-to-make-better-yu-gi-oh-custom-cards-33142)

### A3.4 永续效果 / 无种类效果的识别

**编码规则**：怪兽效果文本中**完全不含** `：` 与 `；` → 不是起动/诱发/诱发即时效果 → 只能是**永续效果**或**无种类效果**（二者都不入连锁、不能被 `Divine Wrath` 类效果响应）。
官方例证：`Blade Knight`、`Bountiful Artemis`、`Vision HERO Trinity`、`Cyber Dragon`。
来源：[PSCT Part 3](https://www.yugioh-card.com/en/play/psct/psct-3/) / [Part 4](https://www.yugioh-card.com/en/play/psct/psct-4/) / [Part 6](https://www.yugioh-card.com/en/play/psct/psct-6/)

---

## A4. 选择性 / 强制性与「才能发动」体系

| 中文 | 日文 | 英文 | 语义 |
|---|---|---|---|
| **才能发动** / **可以发动** | 発動**できる** | `You can ...` | **选发（任意）效果**：玩家可选择不发动。**不能空发**（无有效对象/无意义时不能发动） |
| （仅写）**发动** | 発動**する** | （无 `can`） | **必发（强制）效果**：满足条件必须发动。即使空发也要发动，处理时才判断能否适用 |
| **必须发动** | 〜しなければならない | `must` | 强制的规则性要求（多用于召唤手续/誓约） |
| **这个效果在〜才能发动** | 〜でしか発動できない | `can only be activated during ...` | 时点限制 |
| **〜才能发动**（条件） | 〜**でしか**発動できない | `can only ... ` | 「只能…才」的条件限定 |

来源：[OCG Rule 基本用语 — 必发效果·选发效果](https://ocg-rule.readthedocs.io/zh-cn/latest/c02/%E5%9F%BA%E6%9C%AC%E7%94%A8%E8%AF%AD.html)

**关键裁定点（可编码）**：
- 选发效果**不能空发**：例）场上无怪兽时不能发动「黑洞」。
- 必发效果**在无正确对象时也会发动**，此时**不取对象**（例：`月华龙 黑蔷薇` 在对方场上无怪兽时特殊召唤，仍发动 ①效果但不取对象）。
- 必发效果需支付 cost 时必须支付；无法支付则**不发**（例：基本分低于 500 时 `月镜盾` 效果不发）。

---

## A5. 取对象 / 不取对象的写法（★核心）

来源：[OCG Rule — 效果的对象](https://ocg-rule.readthedocs.io/zh-cn/latest/c02/%E5%9F%BA%E6%9C%AC%E7%94%A8%E8%AF%AD.html)、[PSCT Part 4](https://www.yugioh-card.com/en/play/psct/psct-4/)

### A5.1 判定规则（按卡文分期）

| 时期 | 取对象写法 | 不取对象写法 |
|---|---|---|
| **第 9 期以后**（带编号效果） | 「**以○○为对象**才能发动」/ `target ...` | 无「以○○为对象」字样（即使处理时要选卡） |
| **第 8 期** | 「**选择**」 | 「**选**」（无「择」字） |
| 第 8 期以前 | **需查裁定**，无法从文本判断 | 同左 |

英文侧：
- 取对象 → `You can target 1 ...;`（`target` 出现在**分号之前**）
- 不取对象 → 处理时才选，如 `destroy 1 card your opponent controls`

### A5.2 「that target / those targets / it / they / both」（★直接影响结算，官方 Part 4 原文）

| 处理文中的指代 | 语义 | 官方原例 |
|---|---|---|
| **`that target`** / **`those targets`** | 处理时对象**必须仍满足取对象时的条件**，否则该部分效果消失 | `Trap Hole`（`destroy that target`）：若对象 ATK 已不足 1000，效果消失 |
| **`it`** / **`they`/`them`** | 处理时**不要求**仍满足取对象条件，只需原本被取过对象 | `Adreus, Keeper of Armageddon`（`destroy it`）：即使被翻成里侧或转移控制权，仍破坏 |
| **`both (those targets)`** / `all three targets` | **全部**对象都必须仍合格，只要一个不合格 → **整个效果消失** | 官方 Part 4 明确说明 |
| 无条件限定（如「破坏」） vs 「那个**对方**怪兽破坏」 | 若控制权转移到己方，则「对方怪兽」条件不再满足 → 不破坏 | [OCG Rule](https://ocg-rule.readthedocs.io/zh-cn/latest/c02/%E5%9F%BA%E6%9C%AC%E7%94%A8%E8%AF%AD.html) |
| 「in the Graveyard」 | 处理时必须仍在该处 | [PSCT Part 6](https://www.yugioh-card.com/en/play/psct/psct-6/) |

### A5.3 「持续取对象」（Continuous Targeting）

「只要这张卡在场上存在，和其效果的对象持续关联」——装备卡、`Call of the Haunted`、`Number 106: Giant Hand` 等。
规则含义：效果被无效后**仍然保持取对象**（但效果不适用）；恢复适用后继续。
来源：[OCG Rule — 持续取对象](https://ocg-rule.readthedocs.io/zh-cn/latest/c02/%E5%9F%BA%E6%9C%AC%E7%94%A8%E8%AF%AD.html)

---

## A6. 效果发动次数限制的标准写法（★核心，三种必须区分）

来源：[Yugipedia — Once per turn](https://yugipedia.com/wiki/Once_per_turn)（实抓 `?action=raw`）

### A6.1 三种限制的精确差异

| 类型 | 英文写法 | 日文写法 | 作用域 | 被无效后能否再发动 |
|---|---|---|---|---|
| **①「1回合1次」** | `Once per turn: You can ...`（写在**发动条件**里） | 「1ターンに1度」 | **该张卡**（该个体，且在该区域表侧存在期间） | ❌ 不能再发动 |
| **②「只能1次」/ HOPT** | `You can only use/activate this effect of "X" once per turn.`<br>`You can only use each of the following effects of "X" once per turn.` | 「このカード名の①②の効果はそれぞれ1ターンに1度しか使用できない。」 | **该玩家 + 该卡名**（同名卡共用） | 看用词：「**use**」→ 不能再发动；「**activate**」→ 若**发动被无效**可再发动；「**apply**」→ 最宽松，效果被改变/无效后还可再试 |
| **③「1回合只能获得1次这个效果」** | `(You can only gain this effect once per turn.)` | — | **该玩家**，跨卡名（如额外通常召唤类） | — |

### A6.2 ①的关键细节（易错）

- 「1回合1次」限制的是**那张卡本身**，且**仅在当前区域表侧存在期间**。
- 该卡**离开当前区域**（整个场上视为同一区域）或**被翻成里侧** → 限制**重置**，当回合可再次发动。
  - 官方例：`Barrel Dragon` 发动后若被破坏送去墓地、再用 `Call of the Haunted` 特召回来 → **可以再次发动**。
  - 官方例：`甲虫装机 豆娘` 发动 ①效果后变成装备卡，再被特殊召唤 → 可再次发动。
- 控制权转移**不算**重置（还是同一只怪兽），受限不能再发动。
- 例外：明确写「这张卡1回合只有1次可以变成里侧守备表示」（如 `Swarm of Locusts`、`Flip Flop Frog`）→ 再反转后**不能再发动**。
- 玩家可控制**多张同名卡**，各自分别计算 ① 的「1回合1次」。

### A6.3 ②的关键细节

- 「只能使用1次」限制的是**该玩家 + 该原本卡名**；**不受卡名变化影响**（例：`Fairy Archer` 发动后即使被 `Hero Mask` 改名，当回合仍不能再发动）。
- 「这张卡的卡名在规则上当作○○使用」的卡，其效果次数限制与「○○」**分开计数**（例：`阿不思的落胤` 与 `白龙之落胤` 可在同一回合各自发动）。
- 「同一卡名」但通过 `treated_as`（原名不同但规则上当作同名）投入时，**卡组合计 3 张**限制仍适用。

### A6.4 标准写法模板（中文/日文/英文）

```
【单效果 HOPT，中文】
这个卡名的①效果1回合只能使用1次。
【单效果 HOPT，日文】
このカード名の①の効果は1ターンに1度しか使用できない。
【多效果 HOPT，中文】
这个卡名的①②效果1回合各能使用1次。
【多效果 HOPT，日文】
このカード名の①②の効果はそれぞれ1ターンに1度しか使用できない。
【多效果 HOPT，英文】
You can only use each of the following effects of "X" once per turn.
【单卡1回合1次（非 HOPT）】
1回合1次，〜才能发动。/ Once per turn: You can ...
```

**⚠️ 中文官方译法确认**：官方中文卡片数据库的检索界面对应关系确认了官方用词（如「灵摆」「超量」「同步」「连接」「协调」等，见 B3）。

---

## A7. 破坏 / 送去墓地 / 除外 / 回到卡组 / 回到手卡 的官方用词对照

| 中文（官方） | 日文 | 英文 | 备注 |
|---|---|---|---|
| **破坏** | 破壊 | Destroy | 与「解放」「送去墓地」严格区分 |
| **送去墓地** | 墓地へ送る | Send to the Graveyard | |
| **丢弃 / 从手卡丢弃** | 手札から捨てる | Discard | 「送去墓地」≠「丢弃」 |
| **除外** | 除外する（旧：ゲームから除外） | Banish（旧：remove from play） | 2011 年 PSCT 改词 |
| **回到卡组** | デッキに戻す | Return to the Deck | |
| **回到卡组・额外卡组** | デッキ・EXデッキに戻す | Return to the Deck/Extra Deck | 后期补写 |
| **回到手卡** | 手札に戻す | Return to the hand | |
| **解放**（旧：祭品/生け贄） | リリース（旧：生け贄に捧げる） | Tribute → **Release** | 中文官方 = 解放；繁中曾用「祭品」 |
| **放置**（在卡组顶） | デッキの上に置く | Place on top of the Deck | 「回到卡组顶」→「放置」 |
| **翻开 / 确认** | めくる / 確認 | Excavate（旧：pick up）/ Reveal | 2013 年改词 |
| **无视召唤条件** | 召喚条件を無視 | Ignore the Summoning Conditions | |
| **破坏并送去墓地** vs **破坏** | — | — | 「被解放送去墓地」**不视为被破坏** |

来源：[PSCT Part 2](https://www.yugioh-card.com/en/play/psct/psct-2/)、[Yugipedia PSCT — Changes/Terminology](https://yugipedia.com/wiki/Problem-Solving_Card_Text)、[OCG Rule 解放](https://ocg-rule.readthedocs.io/zh-cn/latest/c02/%E5%9F%BA%E6%9C%AC%E7%94%A8%E8%AF%AD.html)

### A7.1 PSCT 术语变更史（编码时做「旧词→新词」归一化）

来源：[Yugipedia PSCT — Changes](https://yugipedia.com/wiki/Problem-Solving_Card_Text)

| 旧写法 | 新写法 | 引入 |
|---|---|---|
| remove from play | **banish** | 2011 |
| removed from the field | **leaves the field** | 2011 |
| select | **target** | 2011 |
| pick up | **excavate** | 2013 |
| Effect Monster's effect | **monster effect** | — |
| When（仅限必发效果） | **If** | Realm of Light SD |
| Life Points | **LP** | 2014 |
| Graveyard | **GY** | 2017 |
| Trap Card（非指发动时） | **Trap** | 2017 |
| Spell Card（非指发动时） | **Spell** | 2017 |
| side of the field | **field** | 2015 |
| Tuner monster | **Tuner** | The Dark Illusion |
| Xyz Material | **material** | 2017 |
| Fusion Material Monster | **Fusion Material** | — |
| Synchro Material Monster | **Synchro Material** | — |
| "-Type"（种族后缀） | 直接删去 | 2017 |
| Elemental Hero / Destiny Hero / Evil Hero | **Elemental HERO / Destiny HERO / Evil HERO** | 2011 |
| "This card's name is treated as X" | **"This card's name becomes X while ..."** / "(This card's name is always treated as X.)" | 2012 / 2013 |
| "This card cannot be Normal Summoned or Set." | **"Cannot be Normal Summoned/Set."** | GENF / LC3 |
| "This card can only be ..." | **"Must first be ..."** | 2011 |
| "Cannot be Special Summoned except ..." | **"Must be Special Summoned ..."** | 2017 简化 |
| attach ... as an Xyz Material | **attach ... as material** | — |
| detach # Xyz Material(s) | **detach # material(s)** | 2017 |
| "that specifically lists the card X in its text" | **"that mentions X"** | 2021 |

---

## A8. 常见文本错误清单（DIY 社区整理 → 可编码的 linter 规则）

来源：[YGOPRODeck - How to make better Yu-Gi-Oh! Custom Cards](https://ygoprodeck.com/article/how-to-make-better-yu-gi-oh-custom-cards-33142)（作者 TreetopDuelist，明确说「**The number one mistake I see when reading other people's custom cards is a distinct lack of colons**」）、[遊戯王オリカ@wiki カードテキストテンプレ](https://w.atwiki.jp/yugiorika/pages/12.html)

### A8.1 错误清单表

| # | 错误 | 检测规则（可编码） | 严重度 |
|---|---|---|---|
| E01 | **漏写冒号**（本应入连锁却不入连锁） | 效果含「发动」「才能发动」「时可以」等触发/起动措辞，但文本中无 `：` → 报错 | 🔴 致命 |
| E02 | **把 cost 写在分号之后** | `；` 之后出现 `支付/丢弃/解放/破坏/送去墓地` 等 cost 类动词且紧跟「〜する」→ 报错（cost 在 `；`前） | 🔴 致命 |
| E03 | **把效果处理写在分号之前** | `；` 之前出现 `加入手卡/特殊召唤/破坏/抽卡` 等结果性动作 → 报错 | 🔴 致命 |
| E04 | **漏写时点** | 诱发效果缺 `时/場合`（英：`When`/`If`）→ 报错 | 🔴 致命 |
| E05 | **写了「场合」但引擎按「时」实现** | 文本 `場合`/`If` 与 Lua 脚本的 trigger timing（`EVENT_*` + `call` 时机）不一致 → 语义校验报错 | 🔴 致命 |
| E06 | **`①②③` 编号使用错误**：编号跳号、灵摆效果编号与怪兽效果编号不连续 | 编号序列必须是 `从①起、连续、无缺失`；灵摆怪兽编号须跨文本框连续 | 🟠 高 |
| E07 | **`①②③` 效果数量 ≠ 实际效果条数** | 统计编号数与文本分句数比对 | 🟠 高 |
| E08 | **HOPT 子句缺失或位置错误** | `这个卡名的①效果1回合只能使用1次` 类子句必须写在**效果文本最开头**、且在编号效果之前 | 🟠 高 |
| E09 | **检索类效果无 HOPT**（除明确设计为无限制） | 文本含「从卡组把…加入手卡」且无 `1回合1次`/`只能使用1次` → 警告 | 🟠 高 |
| E10 | **融合素材写法错误** | 融合怪兽素材行格式：`「A」＋「B」`（中文全角加号）/ `"A" + "B"`（英文半角加号）。**素材行必须在效果文本之前**，且**素材行不是效果** | 🟠 高 |
| E11 | **超量素材写法错误** | 格式：`4星怪兽×2`（中文/日文用 `×`，英文用 `2 Level 4 monsters`）。**超量怪兽没有等级，只有阶级**；`×` 后为数字，通常 ≥2 | 🟠 高 |
| E12 | **同调素材写法错误** | 格式：`协调＋协调以外的怪兽1只以上`（中文）；日文 `「チューナー」＋「チューナー」以外のモンスター○体以上`；英文 `1 Tuner + #+ non-Tuners`。**「协调」在中文官方用语中代替「调整/协调」**（见 B3） | 🟠 高 |
| E13 | **连接怪兽素材写法错误** | 格式：`效果怪兽2只` / `卡名不同の怪兽2只`；**连接怪兽没有等级/守备力，只有连接数值与连接标记**。卡面需标注连接标记位置（上/下/左/右/左上/右上/左下/右下） | 🟠 高 |
| E14 | **灵摆刻度与等级混淆** | 灵摆怪兽有**等级**（左侧）+ **灵摆刻度**（卡图两侧的箭头数字，0–13）。刻度不是等级；`scale` 字段与 `level` 字段必须分开存储 | 🟠 高 |
| E15 | **灵摆效果未分栏** | 灵摆怪兽文本必须能拆成「怪兽效果」与「灵摆效果」两栏；且灵摆效果的编号接续怪兽效果编号 | 🟠 高 |
| E16 | **「卡」与「怪兽」混用** | 破坏/除外/回手 类效果：检查候选集用词（怪兽/卡）与场所声明是否一致 | 🟡 中 |
| E17 | **取对象未写「以〜为对象」** | 效果处理引用了具体卡片（有 `；` 且 `；` 后指代特定卡）但 `；` 前无「以〜为对象」/`target` → 警告（第 9 期后规则） | 🟡 中 |
| E18 | **「that target」与「it」混用** | 处理文指代用词与预期结算语义不符 → 警告 | 🟡 中 |
| E19 | **连接词误用** | 同时关系误用 `then`（会错开时点）／一败俱败误用 `also`（会部分结算） | 🟠 高 |
| E20 | **`and` 滥用** | 单独 `and` 应为高度受限的全有全无效果；普通「同时+一个必需」应写 `and if you do` | 🟡 中 |
| E21 | **多个 `●` 未声明 in sequence / (simultaneously)** | 见 A1.5 | 🟡 中 |
| E22 | **魔法/陷阱出现「quick effect」** | 违 reflection 官方不写规则 → 报错 | 🟡 中 |
| E23 | **效果条数过多** | 单卡效果条数 > 3 → 警告（社区经验：一般 ≤2 条，最多 3 条） | 🟡 中 |
| E24 | **字段引用与文本引用混淆** | 「「XXX」卡」（字段，可匹配所有卡名含 XXX 的卡）vs「有「XXX」卡名记述的卡」（**必须是文本中真的出现该卡名**，不能是字段） | 🟠 高 |
| E25 | **旧术语残留** | 出现 `remove from play` / `select` / `Life Points` / `Graveyard`（应 `GY`）/ `-Type` 等 → 按 A7.1 表归一化 | 🟡 中 |
| E26 | **效果外文本被当成效果** | 「不能通常召唤。」「这个卡名在规则上当作〜使用。」「这个卡名在规则上也当作「○○」卡使用。」属**效果外文本**，不可被无效 | 🟠 高 |
| E27 | **召唤手续被当作效果** | 「这张卡可以把自己场上1只怪兽解放特殊召唤」类**召唤手续**不入连锁、不是效果、不能被无效 | 🟠 高 |
| E28 | **`（从手卡）` 括号缺失** | 内置特殊召唤必须标注来源地括号，否则无法判断能否被「无效召唤」类无效 | 🟠 高 |

### A8.2 DIY 中常见的「数值/写法」注意事项（来自日文オリカ wiki，注意该页年代为 2008，术语需按 A7.1 更新）

来源：[遊戯王オリカ@wiki カードテキストテンプレ](https://w.atwiki.jp/yugiorika/pages/12.html)

原文要点（已翻译）：
1. 「このモンスター」与「このカード」的用法**没有严格规律**（官方自身不统一）。
2. 官方卡文中「できる」几乎**都用平假名**，不用汉字「出来る」。
3. **未写明数量的特殊召唤会歧义**：「〜を1体特殊召喚する」若省略数量，会被读成可以特召复数——オリカ常见错误，需特别注意。
4. **必须写明「自分」还是「相手」**：写不写会极大改变卡的强度。
5. 「使用する」（使用）不仅指发动，**作为 cost 丢弃也算「使用」**。

> ⚠️ 该 wiki 页面最后更新 2008-06-24，术语已过时（如仍用「生け贄」「ゲームから除外」）。**可作为句式的历史参考，但术语必须按 PSCT 更新**。

---

## A9. 卡名与字段（archetype）的写法规范

来源：[OCG Rule — 卡名](https://ocg-rule.readthedocs.io/zh-cn/latest/c02/%E5%9F%BA%E6%9C%AC%E7%94%A8%E8%AF%AD.html)

### A9.1 字段引用 vs 文本引用（★核心区分）

| 中文写法 | 英文 | 匹配范围 |
|---|---|---|
| 「**「XXX」卡**」 | `a "XXX" card` | **字段（archetype）**：卡名中**包含**「XXX」的所有卡 |
| 「有「XXX」卡名**记述**的卡」 | `a card that **mentions** "XXX"` | **文本引用**：效果文本中**真的出现了该卡名**的卡。字段**不算** |
| 「「XXX」怪兽」 | `a "XXX" monster` | 字段 + 卡种限定为怪兽 |
| 卡名不同的卡 | `cards with different names` | — |

**关键裁定（官方例证）**：
- `蒂迈欧之眼`、`黑·魔·导·爆·裂·破` 的效果文本写的是「「黑魔术师」怪兽」「「黑魔术少女」怪兽」——此处的「黑魔术师」是**字段**而非卡名，因此 `黑魔术的继承` 的 ①效果**不能**选这两张卡。
- 反过来，即使是不作为效果处理的**效果外文本**里出现某卡名，也满足「有该卡名记述」的条件（例：`重起士道-金骑士` 可检索 `超二重召唤`）。
- 作为通常怪兽使用的 `混沌战士` **不是**「记述了『青眼白龙』的卡」。

**编码校验点**：
- 存两张表：`archetype_strings`（字段字符串）与 `mentioned_card_names`（精确卡名）。
- 生成卡文时，若意图是字段匹配 → 必须写「「XXX」卡」；若意图是精确卡名 → 必须写「有「XXX」卡名记述的卡」（或英文 `mentions "XXX"`）。混淆是🔴致命错误。
- **新写法**：旧写法「名字带有「XXX」的」已废弃，官方中文统一为「「XXX」卡」；英文统一为 `a "XXX" card` / `that mentions "XXX"`。

### A9.2 HERO 大小写规则（历史遗留，需保留特例表）

- `Elemental Hero` → **`Elemental HERO`**（全大写，作为字段 `HERO` 的一部分）
- `Destiny Hero` → **`Destiny HERO`**
- `Evil HERO` → **`Evil HERO`**（原本就是）
- 例外：`Hero Kid` 保持原样；`Hero's Bond` → **`HERO'S Bond`**；`HERO Flash!!` → **`Hero Flash!!`**
来源：[PSCT Part 2](https://www.yugioh-card.com/en/play/psct/psct-2/)

### A9.3 卡名规则上处理（效果外文本）

| 中文 | 英文 | 语义 |
|---|---|---|
| 「这个卡名在规则上当作「○○」使用」 | `(This card's name is always treated as "○○".)` | 规则上**不存在**原卡名 → 与「○○」**合计 3 张** |
| 「这个卡名在规则上也当作「○○」使用」 | `(This card is also always treated as "○○".)` | 持有**两个卡名** → 与「○○」**合计 3 张** |
| 「这个卡名在规则上也当作「○○」卡使用」 | `(This card is also always treated as a "○○" card.)` | 视为**字段** |
| 「这张卡不是当作「○○」卡」 | `(This card is not treated as a "○○" card.)` | 否定字段 |

> `(This card is always treated as ...)` 引入于 `Battle Pack 2: War of the Giants`（2013）；`(This card is not treated as ...)` 引入于 `Destiny Soldiers`。

---

# B. 各语言文本规范与可校准数据库

## B1. 日文官方卡文规范

### B1.1 句式体系

| 日文 | 语义 | 备注 |
|---|---|---|
| 発動**できる** | 选发（任意） | 平假名，不用汉字 |
| 発動**する** | 必发（强制） | — |
| 〜**時** | 有严格时点，**会**错过；用于「对卡/效果发动」时表示**直接连锁** | ★与英文 When 不完全等价 |
| 〜**場合** | 无严格时点，**不会**错过；用于「对卡/效果发动」时表示**处理完毕后** | ★与英文 If 等价 |
| 〜**し**、〜する | = 英文 `and`（同时 + 两者必需） | |
| 〜**その後**、〜する | = 英文 `then`（顺序 + A 必需） | |
| 〜**また**、〜する | = 英文 `also`（同时 + 互不依赖） | |
| 〜**また、その後**、〜する | = 英文 `also, after that`（顺序 + 互不依赖） | |
| 〜し、**その場合**、〜する | = 英文 `and if you do`（同时 + A 必需） | |
| **さらに** | 追加处理（递进） | ⚠️ 无固定英文对应，需按卡核对 |
| 〜**なければならない** | 必须 | 召唤手续/誓约 |
| 〜**でしか発動できない** | 只能在〜发动 | 时点限制 |
| このカード名の①②の効果は**それぞれ**1ターンに1度しか使用できない | HOPT（多效果） | 官方标准句 |

### B1.2 日文是否有分号（；）

> ⚠️ **未完全验证**。日文 OCG 卡文**使用「：」**（读作逗号感的分隔），但**不使用英文式的「；」**。日文用「〜して発動できる」/「〜を発動する」等**措辞区分**来处理 cost/target 与效果处理的边界，而非分号。

**佐证**：[遊戯王OCGカードデータベース](https://www.db.yugioh-card.com/yugiohdb/?request_locale=ja) 的日文卡文（如「魔知ガエル」等）实为「〜時（場合）に発動できる。〜する。」的连续句式，未见「；」。此外 [OCG Rule 基本用语](https://ocg-rule.readthedocs.io/zh-cn/latest/c02/%E5%9F%BA%E6%9C%AC%E7%94%A8%E8%AF%AD.html) 的中文整理提到「在**第九期以后的情报文本**中，cost 会清楚的写在**『发动』之前**」——即靠**语序**（cost 在「発動」之前）而非标点。

**建议**：不要把「分号」规则套到日文/中文卡文上。**中文官方卡文同样不使用分号**，也是靠语序。这是跨语言生成时最重要的差异之一。

### B1.3 官方来源

- [遊戯王OCG公式サイト](https://www.yugioh-card.com/japan/) — 日文官方入口
- [遊戯王OCGカードデータベース（日文）](https://www.db.yugioh-card.com/yugiohdb/?request_locale=ja) — 官方卡片数据库，含 FAQ 裁定
- 官方完全规则书日文版（通过上述入口进入）
- 卡文写法参考（社区，非官方）：
  - [遊戯王カードWiki — テキスト](http://yugioh-wiki.net) （被 OCG Rule 列为参考站点）
  - [カードラボ「時」と「場合」解説](http://www.c-labo.jp/blog/457435/)

---

## B2. 英文 PSCT 规范

### B2.1 官方规则书

- **Rulebook & Beginner's Guide 官方下载页**：<https://www.yugioh-card.com/en/rulebook/>
- **EU 版规则书页**：<https://www.yugioh-card.com/eu/play/tcg-rulebook/>
- ⚠️ 版本号：Yugipedia 引用的是 **Official Rulebook Version 10**（含 PSCT 相关说明在 p.52–53）。**最新版本号未在本轮验证**，请以官方页面实际 PDF 为准。Yugipedia 有存档：<https://yugipedia.com/wiki/File:Rulebook_v10.pdf>
- PSCT 相关章节位置（Version 10）：**p.52–53**（Conditions / Activation, 冒号分号说明）

### B2.2 官方 PSCT 系列与 EU 镜像

见 A0 表格（Part 1–7 的 14 条链接，en 站与 eu 站各 7 条）。

### B2.3 其他官方/半官方英文资源

| 资源 | URL | 说明 |
|---|---|---|
| Advanced Rules Information | <https://www.yugioh-card.com/en/play/advanced-rules/> | 进阶规则入口 |
| Damage Step Rules | <https://www.yugioh-card.com/eu/play/damage-step-rules/> | 伤害步骤细则 |
| Fast Effect Timing | <https://www.yugioh-card.com/eu/play/fast-effect-timing/> | 快速效果/优先权流程图 |
| 2021 Rules Update | <https://www.yugioh-card.com/eu/play/2021-rules-update/> | 规则更新 |
| Updated Card Names | <https://www.yugioh-card.com/eu/play/updated-card-names/> | 卡名更新表（字段大小写等） |
| Forbidden & Limited List (EU) | <https://www.yugioh-card.com/eu/play/forbidden-and-limited-list/> | 禁限卡表 |
| Deck Construction Rules | <https://www.yugioh-card.com/en/limited/> | 构筑规则 |
| 官方卡片数据库（EN） | <https://www.db.yugioh-card.com/yugiohdb/?request_locale=en> | — |

### B2.4 英文官方术语定义来源

- **Yugipedia**（社区 wiki，但逐条引用官方规则书页码）：<https://yugipedia.com/wiki/Problem-Solving_Card_Text>
- 术语变更全表：同页 `Changes` 段（A7.1 已整理）
- ⚠️ Yugipedia 对爬虫有时返回 403；使用 `?action=raw` 参数可绕过并取得**wiki 源码**（本报告即以此方式实抓成功）。

---

## B3. 简体中文 / 繁体中文官方规范

### B3.1 官方中文版背景

| 项 | 内容 | 来源 |
|---|---|---|
| 官方亚洲简体中文版 | **2020 年**起由 KONAMI 亚洲发行（版权标注 `©2020 Studio Dice/SHUEISHA, TV TOKYO, KONAMI`） | [官方简中卡片数据库](https://db.yugioh-card-cn.com/) 页脚版权 |
| 官方简中入口 | <https://www.yugioh-card-cn.com/> | 同上 |
| 官方简中卡片数据库 | <https://db.yugioh-card-cn.com/> | 实抓成功 |
| 繁体中文版 | 由台湾/香港代理发行，2020 年前后启动；[游戏王卡百科 — 游戏王OCG繁体中文版](https://w.atwiki.jp/yugiohcn/pages/215.html) | 社区整理 |

### B3.2 ★官方中文术语表（从官方卡片数据库检索界面实测提取）

这是**最可靠的官方术语来源**：官方数据库的检索筛选器直接使用了官方译名。

来源：<https://db.yugioh-card-cn.com/card_search.action.html>（实抓）

**属性（7）**：暗属性 / 光属性 / 地属性 / 水属性 / 炎属性 / 风属性 / 神属性

**魔法效果（6）**：装备 / 场地 / 速攻 / 仪式 / 永续 / 通常

**陷阱效果（3）**：永续 / 反击 / 通常

**种族（26）**：魔法师族 / 龙族 / 不死族 / 战士族 / 兽战士族 / 兽族 / 鸟兽族 / 恶魔族 / 天使族 / 昆虫族 / 恐龙族 / 爬虫类族 / 鱼族 / 海龙族 / 水族 / 炎族 / 雷族 / 岩石族 / 植物族 / 机械族 / 念动力族 / 幻神兽族 / 创造神族 / 幻龙族 / 电子界族 / 幻想魔族

**卡种/效果分类（15）**：通常 / 效果 / 仪式 / 融合 / **同步** / **超量** / 卡通 / 灵魂 / **联合** / **二重** / **协调** / **反转** / 灵摆 / 特殊召唤 / **连接**

**等级/阶级**：0–13（界面写「等级/阶级」，灵摆刻度单列 0–13）

**其他界面用词**：
- 攻击力 / 守备力（数值上限 **5000**）
- 灵摆刻度 / 连接 / 连接标记
- 简中禁限卡片 / OCG禁限卡片
- 卡片效果文本检索 / 灵摆效果检索 / 卡片编号检索
- 牌组（deck）/ 卡组

> ★**注意关键译法**：
> - Synchron（同调）→ **同步**（不是「同调」；「同调」是民间译法）
> - Xyz（超量）→ **超量**（不是「多维/XYZ」）
> - Link（连接）→ **连接**
> - Tuner（调整/协调）→ **协调**
> - Union（同盟）→ **联合**
> - Gemini（二重）→ **二重**
> - Flip（反转）→ **反转**
> - Deck → **牌组**（界面「牌组检索」「我的牌组」），但「回到卡组」官方规则书用「**卡组**」（见下）

### B3.3 官方中文规则用语（从官方完全规则书中文翻译提取）

来源：[OCG RuleBook 中文翻译（基于官方完全规则书 2020）](https://ocg-rulebook.readthedocs.io/zh-cn/latest/)、[OCG Rule 中文整理](https://ocg-rule.readthedocs.io/zh-cn/latest/)

| 中文 | 对应 |
|---|---|
| **召唤 / 特殊召唤 / 通常召唤 / 反转召唤 / 上级召唤** | Normal/Special/Tribute Summon |
| **解放**（旧：「做祭品」「生け贄」） | Tribute / Release |
| **破坏** | Destroy |
| **送去墓地 / 从手卡丢弃** | Send to GY / Discard |
| **除外** | Banish |
| **回到卡组 / 回到手卡 / 回到额外卡组** | Return to Deck / hand / Extra Deck |
| **攻击力 / 守备力** | ATK / DEF |
| **基本分** | Life Points / LP |
| **表示形式 / 表侧表示 / 里侧表示 / 攻击表示 / 守备表示** | battle position / face-up / face-down |
| **衍生物 / 指示物** | Token / Counter |
| **素材 / X素材 / 融合素材 / 同步素材** | Material / Xyz Material / Fusion Material |
| **对象 / 取对象 / 不取对象 / 持续取对象** | target / targeting |
| **咒文速度** | Spell Speed |
| **阶段 / 步骤 / 时点** | Phase / Step / timing |
| **连锁 / 优先权** | Chain / Priority |
| **选发效果 / 必发效果**（= 任意效果 / 强制效果） | optional / mandatory |
| **错过时点** | missing the timing |
| **苏生限制 / 召唤限制 / 无视召唤条件** | Nomi / Summoning conditions |
| **效果外文本 / 召唤手续** | non-effect text / Summoning procedure |
| **「○○」卡（字段）** | `"○○" card` (archetype) |
| **有「○○」卡名记述的** | `mentions "○○"` |
| **规则上当作「○○」使用** | always treated as |
| **才能发动 / 可以发动 / 发动** | can / must |
| **1回合1次 / 1回合只能使用1次** | once per turn / only once per turn |

### B3.4 中文社区权威整理

| 资源 | URL | 说明 | 可信度 |
|---|---|---|---|
| **OCG Rule（中文规则总集）** | <https://ocg-rule.readthedocs.io/zh-cn/latest/> | 目前最全面的中文 OCG 规则参考，含官方 FAQ 原文链接与日期 | 🟢 高 |
| **OCG RuleBook（官方完全规则书中文翻译）** | <https://ocg-rulebook.readthedocs.io/zh-cn/latest/> | 基于官方完全规则书 2020 | 🟢 高 |
| 源码仓库 | <https://github.com/lucays/OCG-Rule-documentation> / <https://github.com/lucays/ocg-rulebook> | restructuredText，可结构化提取 | 🟢 高 |
| **ygocdb（中文卡查）** | <https://ygocdb.com> | 中文卡名/卡文查询，被 OCG Rule 官方推荐 | 🟡 中高 |
| **游戏王卡百科（atwiki 中文）** | <https://w.atwiki.jp/yugiohcn/> | 中文用语集，含【解放】等词条（日/中/英对照） | 🟡 中（更新较旧，2013–2014） |
| **CNOCG 游戏王规则用语辞典** | <https://www.cnocg.com/bbs/forum.php?mod=viewthread&tid=67689> | 中文规则用语辞典 | 🟡 中 |
| 大师规则 2020 中文选编 | <https://masteryuten.github.io/ygo408/Articles/Rules/1.Master_Rule_2020_selection/1.Master_Rule_2020_selection.html> | — | 🟡 中 |
| NGA 官方规则书转载 | <https://bbs.nga.cn/read.php?tid=33975599> | — | 🟡 中 |

---

## B4. 韩文 / 德文 / 法文 / 意文 / 西文 / 葡文（概述）

### B4.1 概览表

| 语言 | 官方站点 | 官方数据库 | 备注 |
|---|---|---|---|
| **韩文（ko）** | <https://www.yugioh-card.com/kr/> | db.yugioh-card.com（韩文） | 卡名字体：`HY Yaeso Medium` / `Asia Yeseoche Bold` / `Sandoll Book Bold`。**注意**：日文特有的 Ϝ（希腊 digamma）、∀ 等字符韩文字体不支持，韩文版直接用日文字体 |
| **德文（de）** | <https://www.yugioh-card.com/de/> | 同 | `einmal pro Spielzug` |
| **法文（fr）** | <https://www.yugioh-card.com/fr/> | 同 | `une fois par tour`；EU 站有法文 PSCT 镜像：<https://www.yugioh-card.com/eu/fr/play/comprendre-le-texte-des-cartes/part-7-conjunction-functions/> |
| **意文（it）** | <https://www.yugioh-card.com/it/> | 同 | `una volta per turno` |
| **西文（es）** | <https://www.yugioh-card.com/lat-am/> | 同 | `una vez por turno` |
| **葡文（pt）** | <https://www.yugioh-card.com/lat-am/pt/> | 同 | `uma vez por turno` |
| **繁体中文（zh-TW）** | <https://www.yugioh-card.com/asia/>（亚洲站） | 同 | `每回合1次`（旧：`每1回合1次`） |
| **简体中文（zh-CN）** | <https://www.yugioh-card-cn.com/> | <https://db.yugioh-card-cn.com/> | `1回合1次` |

### B4.2 卡名字体（做卡面渲染时需要）

来源：[Yugipedia — Card layout / Typefaces](https://yugipedia.com/wiki/Card_layout)

| 部位 | 英/法/德/意/葡/西 | 日文 | 韩文 | 繁中 | 简中 |
|---|---|---|---|---|---|
| 卡名 | Matrix Small Caps Regular | DF LeiSho Semi-Bold | Sandoll Book Bold | HanWang LiSu Medium | **DF Kai W5** |
| 卡文 | Matrix Regular | DF Leisho Semi-Bold | Sandoll Book Light | HanWang LiSu Medium | **DF Kai W5** |
| 攻守 | Matrix Small Caps Regular | Matrix Small Caps Bold | Matrix Small Caps Regular | Matrix Small Caps Bold | Matrix Small Caps Bold |

> 简中版是唯一使用**楷体（regular script / DF Kai）**而非隶书的 OCG 语言。

---

## B5. 多语言卡文数据库与术语对照资源（★可编程访问）

### B5.1 YGOPRODeck API v7（★最实用的多语言数据源）

**总入口**：<https://ygoprodeck.com/api-guide/>（实抓成功）

| 项 | 内容 |
|---|---|
| 端点 | `https://db.ygoprodeck.com/api/v7/cardinfo.php` |
| 速率限制 | **20 请求/秒**；超限封禁 1 小时 |
| 缓存 | 卡数据 2 天（172800 秒） |
| **多语言参数** | `&language=`，语言代码：**`fr`（法）/ `de`（德）/ `it`（意）/ `pt`（葡）** |
| ⚠️ **限制** | **语言只能在 `cardinfo.php` 上查询**；**卡图只有英文**；新卡在官方翻译发布前只有英文；每种语言有 9000+ 张卡已翻译 |
| ⚠️ **重要缺口** | API 文档**明确列出的多语言只有 fr/de/it/pt**——**没有 ja（日文）、没有 zh（中文）、没有 ko、没有 es**。这对「中日文制卡」是硬缺口 |

**核心字段**（可直接作为卡牌数据模型）：

```
id, name, type, frameType, desc,
atk, def, level, race, attribute,        // 怪兽
scale,                                    // 灵摆
linkval, linkmarkers[],                   // 连接
archetype,                                // 字段！
card_sets[], card_images[], card_prices[], banlist_info{ban_tcg, ban_ocg, ban_goat}
// misc=yes 追加：
beta_name, views, upvotes, downvotes, formats[], treated_as, tcg_date, ocg_date,
konami_id, md_rarity, has_effect, genesys_points
```

**★关键字段说明（对制卡软件很有用）**：
- `archetype`：字段名（YGOPRODeck 维护的 archetype 表）→ 可用于校验 A9.1 的字段引用
- `treated_as`：规则上当作另一张卡（`Harpie Lady 1,2,3` 当作 `Harpie Lady`）→ 可用于 HOPT 同名校验
- `has_effect`：布尔值，判断是否**真的有**效果文本（0/1）→ 可用于区分通常怪兽
- `frameType` 枚举：`normal/effect/ritual/fusion/synchro/xyz/link/normal_pendulum/effect_pendulum/ritual_pendulum/fusion_pendulum/synchro_pendulum/xyz_pendulum/spell/trap/token/skill`
- `type` 枚举（完整，共 37 个值）：含 `"Flip Effect Monster"`, `"Gemini Monster"`, `"Pendulum Effect Monster"`, `"Spirit Monster"`, `"Toon Monster"`, `"Tuner Monster"`, `"Union Effect Monster"`, `"Synchro Tuner Monster"`, `"XYZ Pendulum Effect Monster"` 等
- `race` 枚举：怪兽 26 种族 + 魔法 6 种 + 陷阱 3 种
- 数值过滤支持 `lt/lte/gt/gte`（例 `atk=lt2500`）

**其他端点**：
- `archetypes.php` — 全部字段名列表 → <https://db.ygoprodeck.com/api/v7/archetypes.php>
- `cardsets.php` — 全部卡包
- `cardsetsinfo.php?setcode=XXX`
- `randomcard.php`
- `checkDBVer.php` — 数据库版本

**示例**：`https://db.ygoprodeck.com/api/v7/cardinfo.php?archetype=Blue-Eyes`
法文卡：`https://db.ygoprodeck.com/api/v7/cardinfo.php?name=Survie%20du%20Plus%20Fort&language=fr`

### B5.2 YGOPRO / EDOPro 的 `cards-<lang>.cdb`

| 项目 | URL | 说明 |
|---|---|---|
| **BabelCDB** | <https://github.com/ProjectIgnis/BabelCDB> | Project Ignis 维护的 EDOPro 多语言卡数据库集合。README: <https://raw.githubusercontent.com/ProjectIgnis/BabelCDB/refs/heads/master/README.md> |
| **CardScripts** | <https://github.com/ProjectIgnis/CardScripts> | Project Ignis 的卡脚本库（Lua），README: <https://raw.githubusercontent.com/ProjectIgnis/CardScripts/refs/heads/master/README.md> |
| ygopro（Fluorohydride） | <https://github.com/Fluorohydride/ygopro> | 原始 YGOPro 引擎与示例 GUI |
| Satellaa/ocgcore | <https://github.com/Satellaa/ocgcore> | 「为便于在 EDOPro 中创建和整合自制卡而改造的核心」→ **制卡相关** |

> ⚠️ **未验证**：`cards-<lang>.cdb` 的确切**语言后缀清单**本轮未能实抓确认（GitHub raw 抓取多次失败）。已知惯例是 `cards.cdb`（英文/主库）+ 各语言后缀（如 `cards-jp.cdb`、`cards-zh.cdb` 等），但**具体后缀名与覆盖语言需以 BabelCDB 仓库实际文件名为准**。建议直接查看仓库文件列表。

### B5.3 官方卡片数据库的语言参数

| 站点 | URL 结构 |
|---|---|
| 日文 | `https://www.db.yugioh-card.com/yugiohdb/?request_locale=ja` |
| 英文 | `https://www.db.yugioh-card.com/yugiohdb/?request_locale=en` |
| 简中 | `https://db.yugioh-card-cn.com/`（**独立域名**，非同一站的语言参数） |
| FAQ 检索 | `https://www.db.yugioh-card.com/yugiohdb/faq_search.action?ope=5&fid=<ID>&request_locale=ja` |

> 参数名确认为 **`request_locale`**（在 OCG Rule 站内多处引用中出现）。⚠️ 完整支持的语言代码清单未逐一验证。

### B5.4 术语多语言对照（★Yugipedia 是意外的好来源）

**Yugipedia 的卡牌/概念页在 Infobox 里内建多语言术语对照**。实抓样例（[Once per turn](https://yugipedia.com/wiki/Once_per_turn?action=raw)）：

| 语言 | 「1回合1次」 |
|---|---|
| 日文 | １ターンに１度（`Ichi Tān ni 1 Do`） |
| 英文 | once per turn |
| 法文 | une fois par tour |
| 德文 | einmal pro Spielzug |
| 意文 | una volta per turno |
| 韩文 | 1턴에 1번（`1 Teon-e 1 Beon`） |
| 繁中 | 每回合1次（旧：每1回合1次） |
| 简中 | 1回合1次 |
| 葡文 | uma vez por turno |
| 西文 | una vez por turno |

> ★**可行方案**：用 `https://yugipedia.com/wiki/<Concept>?action=raw` 批量抓取核心概念页（Destroy / Banish / Tribute / Target / Special Summon / Piercing / Excavate 等），解析 Infobox 的 `japanese=` / `chinese=` / `simplified chinese=` / `korean=` / `french=` / `german=` / `italian=` / `portuguese=` / `spanish=` 字段，**自动构建多语言术语对照表**。这是目前找到的最系统的公开多语言对照来源。
>
> ⚠️ 注意事项：① 需用 `?action=raw` 绕过 Cloudflare；② 页面并非每个概念都有完整多语言 Infobox，需容错；③ 繁中/简中字段名分别是 `chinese` 与 `simplified chinese`。

### B5.5 其他可用资源

| 资源 | URL | 说明 |
|---|---|---|
| 官方卡片数据库爬虫 | <https://github.com/Pietracoops/yugioh_cardlist_scraper> | 抓官方站生成完整卡表 CSV（48 stars）→ **可用来构建本地多语言语料** |
| yugioh-mcp-server | <https://github.com/ludoplex/yugioh-mcp-server> | 见 D3 |
| YGO-CustomDatabaseCreator | <https://github.com/drcael/YGO-CustomDatabaseCreator> | 生成可用于 EDOPro / MSE 的自定义数据库 → **制卡导入链路参考** |
| ygo-proxy-generator | <https://github.com/Linseneintopf/ygo-proxy-generator> | 卡组列表 → 可打印 PDF 代卡 |

> ⚠️ **未找到**：一个官方发布的、权威的「多语言术语对照总表」。官方层面似乎不存在这样的公开文档。**B3.2 的官方数据库界面用词 + B5.4 的 Yugipedia Infobox 组合，是当前最可行的替代方案。**

---

# C. 卡牌设计方法论与平衡准则

## C1. 官方设计准则来源

| 项 | 内容 | 来源 |
|---|---|---|
| 官方设计文档 | ⚠️ **未找到** Konami 公开的卡牌设计方法论文档。官方访谈中偶有零散说明，但无系统性设计规范。 | — |
| 禁限卡表说明 | 官方 Forbidden & Limited List 页面会给出调整理由（简要） | <https://www.yugioh-card.com/eu/play/forbidden-and-limited-list/> |
| 官方构筑限制 | 主卡组 **40–60** 张、额外卡组 **15** 张、副卡组 **15** 张、同名卡最多 **3** 张 | <https://www.yugioh-card.com/en/limited/>、<https://www.yugioh-card.com/eu/play/tcg-rulebook/> |
| 禁限卡分类 | 禁止（0）/ 限制（1）/ 准限制（2）。**2021 年 Cardmarket 文章记录当时 TCG 禁限卡共 185 张** | <https://insight.cardmarket.com/en/Articles/How-to-Clean-Up-the-Forbidden-and-Limited-List> |

---

## C2. 社区总结的设计准则（含文章要点摘要）

### C2.1 YGOrganization "Design Analysis" 系列

<https://ygorganization.com/tributesummon/> — **Design Analysis: Designing a Tribute Summon Archetype**

> ⚠️ 该站对爬虫返回 **403（Cloudflare）**，本轮**未能实抓正文**。仅确认标题与 URL 存在（出现在搜索结果中）。**要点摘要待补**。建议用浏览器直接访问或换用 Google Cache。

YGOrganization 其他可能有价值的页面（搜索结果中出现）：
- <https://ygorganization.com/doublesummonlist/> — 关于「追加通常召唤」效果的分类（被 YGOPRODeck 文章引用为权威参考）

### C2.2 YGOPRODeck 文章（★实抓成功，要点可信）

**(1) How to make better Yu-Gi-Oh! Custom Cards**
<https://ygoprodeck.com/article/how-to-make-better-yu-gi-oh-custom-cards-33142>

要点：
- **头号错误是「冒号缺失」**。条件写在冒号前、cost 写在分号前、效果写在分号后。
- 没有冒号 = 不入连锁、不能被 `Ash Blossom` 响应、**没有 cost**。
- 「`and if you do` / `then` 常被用来让效果**不含 cost**」——此时「丢弃1张卡」是**效果**而非 cost，会触发 `Shaddoll Dragon` 等。
- **建议**：「make effects activate with a colon, and use costs as balancing mechanisms for the majority of your cards.」
- **不确定就抄官方卡文的整句**（例：要写「追加通常召唤」就抄 `Knightmare Goblin` / `Gem-Knight Seraphinite`）。
- **主题性效果（Thematic Effects）**：一个在系列多张卡上重复出现的固定句式 → 降低新玩家的学习成本、强化系列辨识度（举 `Kozmo` 为例：飞船有飞船的句式，驾驶员有驾驶员的句式）。
- **效果要简短**：「Including "Thematic Effects" ... new card creators tend to slap a million effects all onto one card」→ 建议**1 张卡最多 2 个效果**，其余 2 个效果应该拆到魔法/陷阱卡上，增加互动与构筑取舍。
- **未成文规则（Unspoken Rules）**——见 C3。
- 卡图建议：Pendulum 怪兽的卡图应**朝向灵摆刻度方向**（低刻度朝左/高刻度朝右），这样场上一看就知道刻度高低。

**(2) What Defines Post-Modern Card Design?**
<https://ygoprodeck.com/article/what-defines-post-modern-card-design-302642>

要点（★对「什么算超模」给出可操作判据）：
- 提出游戏王卡牌设计的五个历史阶段：**Base → Archetypal → Synergistic → Modern → Post-Modern**。
- **Post-Modern 的两个标志**：① **一卡压缩多个角色**（starter + extender + grind resource）；② **3 个或以上效果**。两者通常同时出现。
- 举例 `Snake-Eyes Poplar`：自我特召（starter）+ 检索 `Original Sinful Spoils`（extender）+ 放置怪兽到魔陷区（grind）——「so that's a lot for one card!」
- 举例 `Maiden of White`：单张卡承载整套 `Blue-Eyes` 的战略，被作者称为「one of the most powerful Yugioh cards designed to date」。
- 作者观点：这**不一定是坏事**（power creep 是 misnomer）——角色压缩意味着可以少带引擎件、多带解场牌与手坑。但「第四次效果」的出现令人忧虑。

**(3) Important Yu-Gi-Oh! Rulings: Missing the Timing**
<https://ygoprodeck.com/article/important-yu-gi-oh-rulings-missing-timing-14035>
→ 已并入 A3.2。**核心可编码结论**：
- 只有「**When... You can**」（when + 可选）会错过时点
- 「**If**」效果与**必发**效果**永不**错过
- 「do A, **then** do B」→ B 成为「最后发生的事」→ 会让人错过时点
- 「do A, **and if you do**, do B」→ 同时 → **不会**让人错过时点

**(4) Deciphering Difficult Card Texts**
<https://ygoprodeck.com/article/deciphering-difficult-card-texts-17506>

要点：
- **无分号 = 无 cost**（`Allure of Darkness` 没有 cost，所以 `Imperial Iron Wall` 连锁后反而**不**需要弃手牌）。
- **Post-PSCT，每个入连锁的效果文本里都有冒号**。没有冒号 = 不入连锁 = 不能被响应。举例：`Trickstar Light Stage`、`Trickstar Candina` 的效果不入连锁。
- **追加通常召唤效果的分类学**（★对设计很有价值）：
  - **第一类：改变游戏的通常召唤次数上限**（`Chain Summoning`）——同类之间**不叠加**
  - **第二类：给你一次额外的通常召唤**（`Gem-Knight Seraphinite`、`Swap Frog`）——同类之间**不叠加**
  - **跨类可以叠加**：`Double Summon` + `Seraphinite` = 3 次通常召唤
  - 第三类更奇怪的见 [YGOrganization doublesummonlist](https://ygorganization.com/doublesummonlist/)
- **卡的发动 vs 效果的发动**：`Union Hangar` 的检索是「**卡的发动**」时，所以 `Ghost Ogre & Snow Rabbit` **不能**响应（它要求「已经表侧表示存在的魔法/陷阱卡发动效果」）。

### C2.3 Yugioh Card Maker Forum（社区经验，可信度中）

**"How to make balanced custom cards"**
<https://www.cardmaker.net/forums/topic/415541-how-to-make-balanced-custom-cards/>

要点（★非常具体，适合编码）：
- **HOPT 是必须的**：「you'd want to make sure that you have a Hard Once per Turn (HOPT) on your cards」
- **检索卡（Searcher）**：系列内检索是**满 3 张**的核心。**全检索（omni-searcher，能检索怪兽/魔法/陷阱任意）→ 必须加 HOPT**，因为它就是系列的 starter。有两个检索（一个检索怪兽、一个检索魔陷）时同理。
- **回收卡（Recycler）**：**2–3 张，最多 2 张为佳**。必须 HOPT 以防 loop。**回收方式决定强度**：除外→墓地、墓地→卡组较弱；**任何「回到手卡/场上」都显著更强**。
- **展开辅助（Extender）**：带自我特召效果；很多 starter 同时也是 extender。
- 「stuff that sends from the Deck/Extra Deck to the GY is broken depending on whether the target(s) that are sent are broken」
- **FTK 是禁忌**：「Stuff that causes an FTK are frowned upon」。社区建议：若 FTK 可能，**其无干扰概率应低于约 20%**（社区经验值，非官方）。
- **不要给每张卡都写「不受效果影响」**：唯一解法变成硬抽 `Kaiju` 或输，且官方卡池里这么写的卡极少。
- **泛用卡（Generic）是平衡的最大风险源**，具体案例：`Link-2 Isolde`（任何战士族卡组）、`Baronne de Fleur`（任何同调卡组）、`Union Carrier`（`Buster Lock` 封锁额外卡组）、`Auroradon`、`Crystron Halqifibrax`（导致大量协调被禁）。
- 「**Do not make materials for monsters to be too generic**」——泛用度越高，效果威力应越低（「the more generic the less power you should give to the effect」）。
- **系列卡数过多 = 设计不良**：「if your archetype has 165 cards just to justify it being playable, chances are that the archetype is badly designed」（HERO 是最大字段，因此有多个子字段）。补充：一副卡组**最多 75 张不同卡**（40+15+15... 实为主40~60+额外15+副15）。
- **引擎（Engine）不应服务所有系列**：否则会变成下一个 `Brave engine`（免费送一个万能无效）。
- **字段命名要查重**：去 DuelingBook 搜字段名，若已有卡用该名 → 不能用作新字段（会冲突）。
- **每个卡组必须有弱点**：「If the opponent cannot hand trap your archetype, it's probably broken.」「If a deck can play through everything, that's not a way to design a custom archetype.」

**"Why does the OCG and TCG banlist affect the way you make yugioh custom cards?"**
<https://www.cardmaker.net/forums/topic/442144-why-does-the-ocg-and-tcg-banlist-affect-the-way-you-make-yugioh-custom-cards>

**"Card Balancing"**
<https://www.cardmaker.net/forums/topic/414690-card-balancing/comment-7201734>

### C2.4 ★HOPT 作为官方平衡工具（★重要设计哲学来源）

**How to Clean Up the Forbidden and Limited List** — Thomas Rose, Cardmarket Insight, 2021-04-23
<https://insight.cardmarket.com/en/Articles/How-to-Clean-Up-the-Forbidden-and-Limited-List>

要点（**极高价值**：把 HOPT 定位为官方的「平衡杠杆」）：
- 当时 TCG 禁限卡共 **185 张**；作者主张其中约 **40 张（≈20%）** 只需加 **HOPT** 即可解禁。
- 「HOPT 勘误是把卡归还无限制状态、又不伤害其身份认同的最可靠方法。」
- **禁卡按 HOPT 可解禁性分四组**（可直接编码成「红旗分类」）：
  1. **FTK 核心组件**：`Phoenixian Cluster Amaryllis`、`Samsara Lotus` 等
  2. **单张多次使用就能产生过多价值**：`Grinder Golem`、`Cyber Angel Benten` 等
  3. **第一次用没问题，但同回合多次使用就出问题**：`Danger!` 怪兽、`Upstart Goblin` 等
  4. 其他（`Royal Oppression`）
- 反例：`T.G. Hyper Librarian`、`Infernity Archfiend` 加 HOPT 后仍应限制（「better off limited」）；`Dandylion`、`Elder Entity Norden` **即使第一次发动都太强**。
- **勘误的两种做法对比**：`Crush Card Virus` 类被改到「从禁卡直接变成废卡」（作者批评）；`Rescue Cat`、`Tiger King of the Ice Barrier` 类只做小改动就重回可玩（作者赞同）。
  → **设计启示**：要削弱一张卡，**优先加 HOPT 而不是砍效果本体**。

### C2.5 Magic: The Gathering 的可迁移设计方法论

YGOPRODeck 文章推荐的资源：
- **Mark Rosewater（MTG 首席设计师）的播客与文章**：<https://magic.wizards.com/en/articles/media/podcasts> — 讨论卡牌设计通论，不限于 MTG
- MTG 的设计骨架概念（**Design Skeleton**）与 **New World Order**（复杂度分级）虽未在本轮直接实抓，但被社区广泛推荐为通用卡牌设计方法论。⚠️ **未验证具体链接**。
- **Extra Credits YouTube 频道 TCG 设计系列**：<https://www.youtube.com/user/ExtraCreditz/search?query=tcg>
- **r/customyugioh** 子版：<https://www.reddit.com/r/customyugioh/>

### C2.6 中文/日文社区

| 资源 | URL | 说明 |
|---|---|---|
| 知乎：游戏王的设计问题到底在哪里？ | <https://www.zhihu.com/question/2041142681963844090/answer/2058532165927826955> | 中文设计批评（⚠️ 未实抓正文） |
| 知乎：游戏王中有哪些充满恶意的数值设计？ | <https://www.zhihu.com/question/58779032> | 数值设计讨论 |
| 知乎：游戏王DIY一套，强度如何？ | <https://www.zhihu.com/question/710593033> | DIY 强度评价实例 |
| NGA：关于展开型卡组手坑携带的新理解 | <https://ngabbs.com/read.php?tid=44247468> | 手坑数量配比讨论 |
| NGA：40 张 vs 41–43 张卡组 | <https://ngabbs.com/read.php?tid=31440643> | 卡组张数取舍 |
| PTT：論主流展開牌牌組結構 | <https://pttweb.tw/YUGIOH/M.1721759161.A.BE8> | 展开型卡组结构分析 |
| 遊戯王オリカ@wiki | <https://w.atwiki.jp/yugiorika/> | 日文 DIY 社区，含卡文模板（2008 年版，术语已旧） |
| 遊戯王オリカ作成 オリカメーカー | <https://yugioh-list.com/orikas> | 日文在线制卡工具 |
| yugioh-wiki.net | <http://yugioh-wiki.net> | 日文卡 Wiki（含裁定） |
| 游戏王卡百科（中文） | <https://w.atwiki.jp/yugiohcn/> | 中文用语集 |

### C2.7 是否存在公开的「游戏王设计方法论」系统性文档？

**结论：不存在由官方发布的系统性设计方法论文档。**

- 官方只发布**规则**（Rulebook）与**禁限卡表**，不发布设计准则。
- 社区侧存在**经验性归纳**（C2.2/C2.3），但**没有统一的、被广泛认可的「设计圣经」**。
- **最接近系统性的是**：
  1. YGOPRODeck 的两篇设计分析文章（Modern → Post-Modern 分期框架）
  2. Cardmarket 的 HOPT 平衡哲学文章
  3. Yugipedia 的**成文惯例页**（见 C3，虽然是「trivia」类目，但内容最接近硬性数值规范）
- 迁移来源（MTG 设计理论）比游戏王本家的文献更系统，但适用性需要人工映射。

---

## C3. ★具体可量化的经验阈值（可编码清单）

### C3.1 等级 4 以下的 ATK / DEF 惯例（★官方卡池统计得出，最可靠）

来源：[Yugipedia — Level 4 ATK and DEF conventions](https://yugipedia.com/wiki/Level_4_ATK_and_DEF_conventions)（实抓 `?action=raw`）

| 规则 | 阈值 | 例外条件 |
|---|---|---|
| **「2000 ATK 惯例」** | 等级 ≤4 且**可通常召唤**的怪兽，若 **ATK > 2000** → **必须**有负面效果或其他限制（如 Nomi 不可通常召唤） | 少数例外 |
| | 若 **ATK = 2000** → 必须是**通常怪兽**，或有效果但**必须是负面效果** | — |
| **「2500 DEF 惯例」** | 等级 ≤4 且**可通常召唤**的怪兽，若 **DEF ≥ 2500** → **必须**有负面效果或其他限制 | — |
| 官方认可上限 | 等级 4 **通常怪兽**的最大可能 ATK = **2000**。官方在 `Alexandrite Dragon` 的 TCG 预览文中明确称之为「the maximum possible ATK for a Level 4 Normal Monster」 | 来源：<https://yugiohblog.konami.com/articles/?p=3246> |
| 等级 4 通常怪兽 2000 ATK 的伴随条件 | 这类怪兽的 DEF 一律是 **100 或 0** | — |
| 允许的「有条件超过」 | 等级 ≤4 的怪兽可以有**条件性 ATK 提升**超过 2000 而无需负面效果（因为「条件性」本身等效于负面效果）。例：`Ghost Bird of Bewitchment` 原本 1300，位于最左怪兽区时 +1000 → 2300 | — |

**官方正面例证**：
- `Thunder King Rai-Oh`：1900 ATK → **允许**有效果
- `Panther Warrior`：2000 ATK → 负面效果（攻击需解放）
- `Zombyra the Dark`：2100 ATK → 负面效果（攻击后失去 ATK）
- `Gear Golem the Moving Fortress`：2200 DEF → 允许正面效果
- `Guard Mantis`：2400 DEF → 允许正面效果
- `Big Shield Gardna`：2600 DEF → 负面效果（被攻击后强制转攻击表示）
- `Meklord Emperor Wisel`：等级 1 / 2500 ATK・DEF（等级 ≤4 最高）→ 不能通常召唤
- `Giant Kozaky`：与 Wisel 并列等级 ≤4 最高 ATK

**Rush Duel 的不同阈值（若支持 RD 模式需分开配置）**：
| 类型 | ATK/DEF 上限 |
|---|---|
| 等级 ≤4 通常怪兽 | **1500** |
| 主卡组效果怪兽 | **1400** |

### C3.2 3000 ATK / DEF 惯例

来源：[Yugipedia — Conventions of 3000 ATK and DEF](https://yugipedia.com/wiki/Conventions_of_3000_ATK_and_DEF)（实抓）

| 规则 | 阈值 |
|---|---|
| **ATK ≤ 3000** | 可以**无任何特殊条件、无任何负面效果**地通常召唤（例：`Blue-Eyes White Dragon`）；很多甚至带正面效果 |
| **ATK > 3000** | 必须**①有负面效果**以维持可通常召唤（如 `Arcana Force XXI - The World`、`Ultimate Obedient Fiend`），或**②有阻止通常召唤的召唤条件**。**所有额外卡组怪兽都属于后者** |
| **DEF ≤ 3000** | 可以无特殊条件地通常召唤/盖放（如 `Labyrinth Wall`、`Millennium Shield`——等级 5，0 ATK / 3000 DEF） |
| **DEF > 3000** | 必须有负面效果或召唤条件 |
| 例外（破例的卡） | ATK > 3000 的破例卡仅 7 张：`Demiurge Ema`、`Earthbound Immortal Red Nova`、`Lord of the Missing Barrows`、`Mighty Dino King Rex`、`Ogdoabyss, the Ogdoadic Overlord`、`Super Conductor Tyranno`、`Super B.E.S. Metal Slave`。DEF > 3000 的破例卡仅 `Superheavy Samurai Big Benkei`（3500 DEF，可通常召唤且有正面效果）及其灵摆版本 |

**ATK 上限**：`5000`（`has_effect` 相关；官方数据库中攻击力/守备力检索最大值标注为 **5000**，与 B3.2 界面一致）

### C3.3 效果条数上限（社区经验）

| 项 | 建议值 | 来源与可信度 |
|---|---|---|
| 单卡效果条数 | **≤ 2 条为佳**，**3 条**已是「Post-Modern」标志 | [YGOPRODeck: Better Custom Cards](https://ygoprodeck.com/article/how-to-make-better-yu-gi-oh-custom-cards-33142)（明确建议拆到魔陷）+ [Post-Modern 文章](https://ygoprodeck.com/article/what-defines-post-modern-card-design-302642)（≥3 效果 = Post-Modern 标志） 🟡 社区经验，可信度**中高** |
| 文本行数 | 「Nobody wants to look at an archetype of 30 cards, each of which have 8 lines of text」→ 保持复杂度最低 | 同上 🟡 中 |
| 编号使用 | `①②③`，从①起连续、无跳号；灵摆效果编号接续怪兽效果 | 官方惯例 🟢 高（见 A1.6） |

### C3.4 卡组构筑比例（社区经验，★数值可信度需谨慎）

> ⚠️ **重要说明**：以下数值**均为社区经验值**，**没有任何官方规定**。官方只规定：主卡组 **40–60**、额外 **15**、副卡组 **15**、同名卡 **3**。
> 编码时应把这些作为**「建议区间 / 警告阈值」**，而非硬性错误。

| 卡位 | 推荐数量区间 | 说明与来源 |
|---|---|---|
| **主卡组总张数** | 40（最优）～ 43 | 40 张最大化核心卡上手率；41–43 常见于需要压 `Side` 或防「削卡」的构筑。来源：[NGA 讨论](https://ngabbs.com/read.php?tid=31440643) 🟡 中 |
| **初动（Starter）** | **12–15 张**（约主卡组 30–37%） | 社区常用「1 枚初动」概念；40 张卡组中 12 张初动的起手（5 张）至少 1 张初动的概率约为 **≈ 85.7%**；15 张约 **≈ 91.5%**。⚠️ 这两个百分比为**本报告依超几何分布计算**，非引用来源 |
| **手坑（Hand Trap）** | **12–15 张**（先攻/后攻对称构筑） | [NGA 手坑理解](https://ngabbs.com/read.php?tid=44247468) 🟡 中 |
| **指名者（Called by the Grave / Crossout Designator / 墓穴指名者等）** | **3–6 张** | 社区惯例 🟡 中低 |
| **诱饵/展开辅助（Extender）** | 视系列而定，常与初动混编 | 🟡 中低 |
| **终端（Boss / 终端怪兽）** | 额外卡组 15 张中通常 **4–8 张为终端**，其余为过渡件 | 🟡 中低 |
| **红坑（Trap）** | 纯展开卡组 **0–3**；Beat/控制卡组 **8–15** | 🟡 中低 |
| **场地/永续魔法** | 视系列，常 **3（场地）+ 1（地形）** | 🟡 低 |
| **额外卡组构成** | 总计 **15 张**；通常 1–2 张为 OTK 用，其余为构筑链与终端 | 🟡 中低 |

> ⚠️ **强烈建议**：这些比例**极难有权威来源**。若软件要给出「卡组健康度」评估，建议**改为「用真实上位卡组统计建立基线」**（可用 YGOPRODeck 的 `/deck-search/` 与 `card-usage` 数据），而非硬编码经验区间。

### C3.5 起手概率计算（建议软件内置）

**超几何分布**：40 张卡组、5 张起手、某类卡 N 张，至少 1 张的概率：

```
P(至少1) = 1 - C(40-N, 5) / C(40, 5)
```

| N（初动数） | P(至少1张) |
|---|---|
| 9 | ≈ 75.4% |
| 12 | ≈ 85.7% |
| 15 | ≈ 91.5% |
| 18 | ≈ 95.2% |

> ⚠️ 上表为本报告**依公式计算**（未引用来源），可用作软件默认基线。**「目标区间」无权威来源**；社区常见说法是「初动 12 张以上算健康」🟡 中低。

### C3.6 素材条件的宽严（可量化的「泛用度」）

| 泛用度 | 素材写法示例 | 设计含义 |
|---|---|---|
| 最泛用 | `4星怪兽×2` / `效果怪兽2只` | 任何卡组可用 → **应给最低威力** |
| 中等 | `「XXX」怪兽2只` / 战士族怪兽2只 | 字段或种族限定 |
| 严格 | `「XXX」怪兽＋「YYY」怪兽`（具名素材） | 只能特定卡组使用 → 可给高威力 |
| 最严格 | 具名且数量 ≥3，或需要特定召唤手续 | 可给极高威力 |

来源：[Cardmaker 论坛](https://www.cardmaker.net/forums/topic/415541-how-to-make-balanced-custom-cards/) 「the more generic the less power you should give to the effect」 🟡 社区经验（可信度中高，且与官方实际设计一致）

---

## C4. ★「超模 / 破坏平衡」红旗清单（可编程检查）

### C4.1 红旗清单表

| # | 红旗 | 检测规则 | 依据 | 严重度 |
|---|---|---|---|---|
| R01 | **无条件从卡组特殊召唤** | 文本含「从卡组特殊召唤」且无 cost（无分号前的代价）且无场面条件（冒号前无条件） | 社区共识；C2.3 | 🔴 极高 |
| R02 | **无代价抽卡** | 文本含「抽 N 张卡」且不在 cost 之后、无 HOPT、无后续代价 | C2.2「老牌强卡的通病」 | 🔴 极高 |
| R03 | **可反复利用的墓地资源（loop 风险）** | 同一张卡同时具备「从墓地特殊召唤自身/其他卡」+「把卡送去墓地」的闭环；或缺少 HOPT 的墓地回收 | C2.4（禁卡第一组） | 🔴 极高 |
| R04 | **无限 loop 风险** | 效果 A 的产物是效果 B 的输入，B 的产物是 A 的输入，且二者均无 HOPT | C2.4 | 🔴 极高 |
| R05 | **FTK（首回合击杀）** | 单回合内可造成的伤害 ≥ 8000 的组合；社区建议无干扰概率 < ~20% | C2.3（社区经验值） | 🔴 极高 |
| R06 | **封锁对手操作** | 文本含「不能发动」「不能攻击」「不能特殊召唤」「跳过〜阶段」且**持续整个回合/整场**且**无解除手段** | Cardmarket/社区 | 🔴 极高 |
| R07 | **手牌破坏（Hand Loop / Hand Rip）** | 文本含「随机丢弃对方 N 张手卡」或可重复的手牌移除 | 社区共识 | 🔴 极高 |
| R08 | **无 HOPT 的检索 / 特召** | 检索类或特召类文本无 `1回合1次` / `只能使用1次` | C2.3「omni-searcher → 必须加 HOPT」 | 🟠 高 |
| R09 | **全检索无 HOPT（omni-searcher）** | 能同时检索怪兽 + 魔法 + 陷阱的检索效果，无 HOPT | C2.3 明确点名 | 🟠 高 |
| R10 | **无视召唤条件的特殊召唤** | 文本含「无视召唤条件」 | 官方用语，本身即为高强度标志 | 🟠 高 |
| R11 | **不取对象 + 不破坏的除去** | 效果同时满足「不取对象」+「不破坏」（如除外、回到卡组、送去墓地）→ 不可被响应 | 社区共识 | 🟠 高 |
| R12 | **「不受效果影响」泛滥** | 单卡或系列内出现「不受效果影响」/`unaffected by card effects` | C2.3 明确警告 | 🟠 高 |
| R13 | **一卡 FTK / 一卡无限** | 单张卡启动即可完成 FTK 或无限 loop | C2.2「Post-Modern」判据 | 🟠 高 |
| R14 | **一卡多角色（Post-Modern 压缩）** | 同一张卡既是 starter（自我特召/检索）、又是 extender（追加展开）、又是 grind resource（墓地回收），**且效果数 ≥3** | C2.2 的 Post-Modern 定义 | 🟠 高 |
| R15 | **素材过泛** | 额外卡组怪兽素材为「任意怪兽 N 只」/「效果怪兽 N 只」且效果强度高（含无效/除去/回收 ≥2 项） | C2.3、C3.6 | 🟠 高 |
| R16 | **卡组直接送去墓地** | 文本含「从卡组把卡送去墓地」（`Deck → GY`） | C2.3「sends from the Deck/Extra Deck to the GY is broken」 | 🟠 高 |
| R17 | **效果条数 ≥ 4** | 编号效果数 ≥4 | C2.2「第四次效果」的忧虑 | 🟡 中 |
| R18 | **额外卡组素材含「任意」+ 无字段/种族限定** | 检测素材行是否含泛用描述 | C3.6 | 🟡 中 |
| R19 | **系列卡数过多** | 单个字段卡数 > 60（社区提及 165 张为病态案例） | C2.3 | 🟡 中 |
| R20 | **字段名与既有字段冲突** | 新字段名已存在于 YGOPRODeck 的 `archetypes.php` 列表 | C2.3 | 🟡 中 |
| R21 | **重复的无条件自我特召** | 多张卡都有「可从手卡/墓地特殊召唤，无 cost」 | 社区共识 | 🟡 中 |
| R22 | **效果无法被手坑阻止** | 系列内所有启动点都不经过「加入手卡」「特殊召唤」「送去墓地」等手坑可响应窗口 | C2.3「If the opponent cannot hand trap your archetype, it's probably broken」 | 🟡 中 |

### C4.2 禁卡表历史案例（用于给红旗规则提供证据）

来源：Cardmarket 2021 文章 <https://insight.cardmarket.com/en/Articles/How-to-Clean-Up-the-Forbidden-and-Limited-List>

| 组别 | 代表卡（原文点名） | 红旗类型 |
|---|---|---|
| FTK 核心 | `Phoenixian Cluster Amaryllis`、`Samsara Lotus` | R05 |
| 单张多次使用即过量 | `Grinder Golem`、`Cyber Angel Benten` | R03/R04 |
| 首用无碍、同回合多次使用出问题 | `Danger!` 怪兽、`Upstart Goblin` | R08 |
| 其他 | `Royal Oppression` | R06 |
| 即使用一次也太强 | `Dandylion`、`Elder Entity Norden` | R01 |

> ⚠️ 该文章为 2021 年版（禁限卡 185 张）。**当前禁限卡表请查官方页面**：<https://www.yugioh-card.com/eu/play/forbidden-and-limited-list/> 或用 YGOPRODeck 的 `banlist=tcg` 参数。

---

## C5. 系列（archetype）设计方法论

### C5.1 核心维度

| 维度 | 好的做法 | 坏的做法 | 检测方式 |
|---|---|---|---|
| **字段一致性（方言句式）** | 一个**固定句式**在系列多张卡上重复（举 `Kozmo`：飞船/驾驶员各一套句式）→ 降低学习成本、强化辨识度 | 每张卡句式都不同 | 统计系列内文本的 n-gram 重复度 |
| **启动路径数量** | 多个**互相独立**的启动点（避免单点被手坑打断即崩） | 只有 1 个启动点 | 统计可独立达成展开的卡数 |
| **资源循环** | 有回收（墓地→卡组/手卡），但**必须 HOPT** 防 loop | 无 HOPT 的墓地→手卡 | 检测回收类效果与 HOPT |
| **终端多样性** | 额外的终端有多个不同定位（无效/除去/压制/续航） | 全部终端都是「无效对方效果」 | 统计终端效果类型分布 |
| **字段大小** | 适中（能支撑起卡组，但不臃肿） | 需 165 张才能玩 → 设计不良 | 统计字段卡数 |
| **泛用度梯度** | 系列内既有 narrow（具名素材）也有 broad（`「XXX」怪兽2只`） | 全部素材都是「任意怪兽2只」 | 统计素材条件的限定强度 |
| **弱点存在性** | 存在手坑/解场可响应的窗口 | 完全无法被手坑阻止 | C4.1 R22 |

来源：主要综合 [Cardmaker 论坛](https://www.cardmaker.net/forums/topic/415541-how-to-make-balanced-custom-cards/)、[YGOPRODeck: Better Custom Cards](https://ygoprodeck.com/article/how-to-make-better-yu-gi-oh-custom-cards-33142)、[Post-Modern 文章](https://ygoprodeck.com/article/what-defines-post-modern-card-design-302642)。🟡 社区经验，可信度中高。

### C5.2 系列设计的「五类卡位」模型

> ⚠️ **不确定项**：用户提到「卡组五类卡位（初动/展开/终端/手坑/红坑/弹性）」。本轮调研**未找到**一个权威的、被广泛引用的「五类卡位」命名体系。社区常见的分类维度是：
>
> | 分类维度 | 常见类别 |
> |---|---|
> | 按**功能角色**（Cardmarket / YGOPRODeck 常用） | **Starter（初动）/ Extender（展开）/ Boss（终端）/ Hand Trap（手坑）/ Board Breaker（解场）/ Floodgate（红坑/压制）/ Grind（续航）** |
> | 按**卡种** | 怪兽 / 魔法 / 陷阱 / 额外 |
> | 按**先攻后攻** | 先攻件 / 后攻件 / 通用 |
>
> 「弹性」这一说法在本轮调研中对应的大概是 **Extender（展开辅助）或 Flex slot（弹性卡位）**。
>
> **建议**：不要声称引用某个「标准五类模型」，而是**基于功能角色自定义分类**，并用真实上位卡组的统计数据来校准配比。

### C5.3 「好系列 / 坏系列」分析文章

| 资源 | URL | 状态 |
|---|---|---|
| YGOrganization "Design Analysis" 系列 | <https://ygorganization.com/tributesummon/> | ⚠️ 403，未实抓 |
| YGOPRODeck 设计分析 | 见 C2.2 | ✅ 实抓 |
| Reddit r/customyugioh | <https://www.reddit.com/r/customyugioh/> | 未逐一验证 |
| DuelingBook 论坛 Custom Cards 版 | <https://forum.duelingbook.com/viewtopic.php?t=16841> | 未实抓 |
| DuelingBook 论坛（另一帖） | <https://forum.duelingbook.com/viewtopic.php?f=23&t=25812> | 未实抓 |

---

# D. 现存的 AI 制卡 / NL→Lua / PSCT 校验尝试

## D1. AI 生成游戏王卡片的项目

### D1.1 ★最直接相关：`Efeincefikir/YugiohPSCT`

| 项 | 内容 |
|---|---|
| **URL** | <https://github.com/Efeincefikir/YugiohPSCT> |
| **仓库描述（原文）** | "Card creator with AI implemented to correct written card text into the PSCT(Problem Solving Card Text) Form" |
| **语言 / 规模** | JavaScript，**18 KB**（极小） |
| **创建 / 最后推送** | 2026-02-13（创建与推送同日） |
| **Stars** | 0 |
| **它做了什么** | 带 AI 的制卡器，把用户写的卡文**纠正为 PSCT 格式** |
| **它没做什么 / 已知问题** | ① 规模极小（18 KB），基本是一次性原型；② 0 stars、无社区验证；③ 未提供效果说明文档；④ 未见测试；⑤ 仅做文本纠正，**不生成 Lua 脚本**、不验证平衡性 |
| **对本项目的意义** | ★**这是「AI + PSCT 纠错」方向的唯一直接先例**，证明该思路有人尝试过，但**没有任何成熟实现** → 本项目有明显空白 |

### D1.2 其他 AI / ML 相关项目

| 项目 | URL | 做了什么 | 没做什么 / 问题 |
|---|---|---|---|
| **Yu-Gi-Oh-LLM**（conbopk） | <https://github.com/conbopk/Yu-Gi-Oh-LLM> | 从零实现 Transformer decoder（复现 Attention Is All You Need），用游戏王卡牌数据训练 | 学术练手性质；**不是制卡工具**；⚠️ GitHub 正文未实抓（fetch 失败） |
| **yu-gi-oh-llm**（ThanhNguyen111, HuggingFace） | <https://huggingface.co/ThanhNguyen111/yu-gi-oh-llm> | 「Yu-Gi-Oh! Card Generator — Decoder-only Transformer from Scratch」 | ⚠️ 页面未实抓（fetch 失败）。推测为同类的从零训练小模型 → **生成的是卡文风格文本，不是可运行的卡** |
| **ECE1786 Project Final Report**（Univ. of Toronto） | <https://www.eecg.utoronto.ca/~jayar/ece1786.2022/download/aimeetyugioh.pdf> | 课程项目报告，涉及游戏王（ECE1786 2022） | ⚠️ PDF 无法直接抓取（`unsupported content type`）。**标题/内容未验证**，仅从搜索结果确认 URL 存在 |
| **ygoAIcardGenerator**（JeffreyWong05） | <https://github.com/JeffreyWong05/ygoAIcardGenerator> | JavaScript 项目，名称含 AI card generator | 0 stars，创建 2023-01，最后推送 2023-01-29 → **已废弃** |
| **YGOWB Card Studio** | <https://www.indiedb.com/games/ygowb-card-studio> | 制卡工具（非 AI） | 未验证 |

### D1.3 传统制卡工具（非 AI，但需了解生态）

| 工具 | URL | 说明 |
|---|---|---|
| **Yugioh Card Maker (YCM)** | <https://www.cardmaker.net/yugioh/> | 最老牌的在线制卡器 + 论坛（C2.3 的来源） |
| **DuelingBook Custom Cards** | <https://www.duelingbook.com/> | 可在对战中测试自制卡（YGOPRODeck 文章提到「probably the best place to test them」） |
| **遊戯王オリカ作成 オリカメーカー** | <https://yugioh-list.com/orikas> | 日文在线制卡器 |
| **YGO-CustomDatabaseCreator** | <https://github.com/drcael/YGO-CustomDatabaseCreator> | 生成兼容 EDOPro / MSE 的自定义数据库 |
| **Semesta19/YugiOh-Card** | <https://github.com/Semesta19/YugiOh-Card> | TypeScript 制卡器，有 Vercel 部署 <https://yugioh-card-two.vercel.app> |
| **Custom-Yugioh-Card-Generator-Python** | <https://github.com/Raioni/Custom-Yugioh-Card-Generator-Python> | Python 制卡器 |
| **ygo-proxy-generator** | <https://github.com/Linseneintopf/ygo-proxy-generator> | 卡组 → 可打印 PDF 代卡 |

### D1.4 Civitai / 卡图生成

> ⚠️ **未验证**：本轮**未搜索 Civitai**（工具限制在 web_search / web_fetch，未针对 civitai.com 做定向检索）。**「是否存在游戏王卡图 LoRA」这一项未确认**。

**已知的卡图相关工作**（从制卡工具侧推断的可行路径）：
- Stable Diffusion / LoRA / ControlNet 生成卡图 → **风格统一是已知难点**（多个制卡器都只做「裁图」而非生成）
- YGOPRODeck 文章明确提到制卡者常见问题：**图片被拉伸变形**（DuelingBook 不裁图，直接拉伸）→ 建议先用 Paint.NET/PS 裁成正方形
- 卡图选择规范：飞行类怪兽不应配海洋图；小支援怪不应配巨型战舰图

### D1.5 ★缺口总结（AI 制卡领域的空白）

| 能力 | 现状 |
|---|---|
| 卡图生成 | 有制卡器做**排版/裁图**，**未见**能保证「风格统一」的 AI 卡图方案 |
| **PSCT 合规文本生成** | ⚠️ **仅 1 个 0-star 的原型**（`YugiohPSCT`，18 KB） |
| PSCT 文本**自动校验（linter）** | ⚠️ **未见独立项目**（见 D3） |
| **自然语言 → ocgcore Lua 脚本** | ⚠️ **未找到任何公开项目**（见 D2） |
| 平衡性自动审计 | ⚠️ **未见任何项目** |
| 端到端（文本 + 脚本 + 卡图 + 平衡） | ⚠️ **完全空白** |

---

## D2. 自然语言 → ocgcore Lua 脚本自动化

### D2.1 调研结论

> 🔴 **未找到任何公开的「自然语言 → 游戏王 Lua 脚本」自动化项目。**
> 搜索了 `LLM generate yugioh lua script`、`natural language to lua yugioh`、`card effect to code generation` 等，无对应结果。

### D2.2 ocgcore Lua API 文档与脚本仓库

| 资源 | URL | 说明 |
|---|---|---|
| **ProjectIgnis/CardScripts** | <https://github.com/ProjectIgnis/CardScripts> | ★EDOPro 的**官方卡脚本库**（Lua）。README: <https://raw.githubusercontent.com/ProjectIgnis/CardScripts/refs/heads/master/README.md> |
| **Fluorohydride/ygopro** | <https://github.com/Fluorohydride/ygopro> | 原始 YGOPro 引擎（含 ocgcore）与示例 GUI |
| **Satellaa/ocgcore** | <https://github.com/Satellaa/ocgcore> | ★「改造过的核心，便于在 EDOPro 中**创建和整合自制卡**」→ **制卡直接相关** |
| Project Ignis（组织） | <https://github.com/ProjectIgnis> | EDOPro 生态主组织 |

> ⚠️ **未验证**：ocgcore Lua API 的**官方参考文档**位置未确认。惯例上分散在 `ygopro` 仓库的 `script/` 目录示例与社区 wiki 中（如 Yugipedia 的 Card Script 类页面），但本轮**未实抓成功**。

### D2.3 可迁移经验（其他 TCG 的 NL→代码）

> ⚠️ **未验证**：本轮**未找到**「LLM 写 MTG Forge 脚本」或「LLM 写炉石卡牌」的具体项目或论文。此方向为**开放问题**。

**从技术角度看，NL→Lua 的可行性障碍**（本报告推断，非引用）：
1. **ocgcore Lua API 无公开权威文档** → LLM 没有稳定的训练语料锚点
2. **效果语义高度依赖裁定细节**（时点、连锁、取对象、错过时点）→ 自然语言本身就有歧义
3. **卡文与脚本是多对多关系** → 同一句卡文在不同上下文下实现不同
4. **无自动验证手段** → 生成的脚本无法被快速测试（EDOPro 只能手动对战验证）

**建议路径**（本报告推断）：先用 A 部分的 PSCT 规则把自然语言**解析成中间结构（IR）**，再从 IR **模板化生成** Lua，而非直接 NL→Lua。这样正确率可控且可验证。

### D2.4 DSL / 中间表示方案的尝试

> ⚠️ **未找到**公开的「用 JSON/DSL 描述效果再编译成 Lua」的项目。
> 唯一沾边的是 **`Gryve/ygo-psct-parser`**（见 D3）与 **`ludoplex/yugioh-mcp-server`**（见 D3），二者都产出**结构化表示**，但**不编译成 Lua**。

---

## D3. ★PSCT 文本的自动校验 / 解析 / 生成器

### D3.1 ★`Gryve/ygo-psct-parser`（最直接相关）

| 项 | 内容 |
|---|---|
| **URL** | <https://github.com/Gryve/ygo-psct-parser> |
| **描述（原文）** | "a parser for problem solving card text for yugioh cards" |
| **语言** | Python |
| **规模** | 2.85 MB |
| **创建 / 最后推送** | 2026-03-26（创建与推送同日） |
| **Stars / Forks** | 0 / 0 |
| **它做了什么** | **PSCT 解析器**：把卡文解析成结构化数据 |
| **它没做什么 / 已知问题** | ① 0 stars，无社区验证；② 单日创建并推送 → 原型/一次性项目；③ 无 license；④ 未见文档、测试说明；⑤ **不生成 Lua**；⑥ 未见覆盖度报告（能解析多少张真实卡？） |
| **对本项目的意义** | ★**这是唯一找到的 PSCT parser 开源项目**。可作为算法参考或基线对比，但**不能直接依赖**（无维护、无 license、无文档） |

### D3.2 ★`ludoplex/yugioh-mcp-server`

| 项 | 内容 |
|---|---|
| **URL** | <https://github.com/ludoplex/yugioh-mcp-server> |
| **GitHub 上显示的描述（原文）** | "Yu-Gi-Oh! OCG/TCG MCP Server — **Deterministic PSCT parser**, card database (YGOProDeck API), and ruling engine for Claude Desktop. **7 tools, 44 tests, 0 LLM interpretation.**" |
| **它做了什么** | ① **确定性（非 LLM）PSCT 解析器**；② 卡牌数据库（封装 YGOProDeck API）；③ **裁定引擎**；④ 以 MCP server 形式提供给 Claude Desktop；⑤ 有 44 个测试 |
| **它没做什么 / 已知问题** | ① ⚠️ **GitHub 页面 fetch 失败**（多次尝试均 `fetch failed`），仅从搜索结果与仓库 API 确认存在；② `api.github.com/repos/ludoplex/yugioh-mcp-server/readme` 返回 **404** → 可能无 README 或仓库为近期创建；③ stars 数量未确认；④ 面向「查询/裁定」而非「制卡生成」 |
| **对本项目的意义** | ★★ **这是发现的最有价值的先例**。「**Deterministic PSCT parser + 0 LLM interpretation**」这一设计理念，**正是本项目应该采用的架构方向**：解析用确定性规则，LLM 只负责创意层。建议本项目**优先深入调研这个仓库** |

> ⚠️ **待办**：`ludoplex/yugioh-mcp-server` 的 README 与源码**未能实抓**（GitHub 网页 fetch 失败、API readme 404）。建议用 `git clone` 或浏览器直接查看。

### D3.3 PSCT 语法描述 / EBNF / 正则

> ⚠️ **未找到**公开的 PSCT 形式化文法（EBNF / 正则语法）。
>
> **当前最接近「语法规范」的公开文本**：
> 1. 官方 PSCT Part 1–7（自然语言描述）→ 本报告 A0 的 7 条链接
> 2. **Yugipedia 的 PSCT 页**（把官方描述整理成了 bullet 规则，且有连接词四象限表）→ <https://yugipedia.com/wiki/Problem-Solving_Card_Text?action=raw> ★**这是目前最结构化的公开规范**
> 3. **OCG Rule 中文站**（把「文本的阅读方法」「cost」「效果的对象」「1回合1次」「必发·选发」等拆成了独立小节，且每条附官方 FAQ 链接与日期）→ <https://ocg-rule.readthedocs.io/zh-cn/latest/c02/%E5%9F%BA%E6%9C%AC%E7%94%A8%E8%AF%AD.html> ★**这是目前最详细、可追溯的规范整理**
>
> **建议**：本项目自行把上述 3 条整理成 EBNF/正则——**没有现成可复用的**。

### D3.4 PSCT 生成器（结构化 → 文本）

> ⚠️ **未找到**任何「从结构化数据反向生成 PSCT 文本」的公开项目。

### D3.5 游戏王卡文 NLP 数据集

> ⚠️ **未验证**：本轮**未针对 HuggingFace datasets 做定向检索**。已知的语料来源：
> - YGOPRODeck API（`desc` 字段，含 `\n` 换行 → 天然带效果分段信息）→ **最实用的语料**
> - `yugioh_cardlist_scraper`（<https://github.com/Pietracoops/yugioh_cardlist_scraper>）→ 可生成 CSV 全卡表
> - ProjectIgnis/CardScripts（Lua 脚本 → **卡文与脚本的配对语料**，是 NL→Lua 训练的关键资源）
> - BabelCDB（多语言卡文）

---

## D4. 相关基础设施

### D4.1 卡牌导入 EDOPro 的流程

| 组件 | 说明 |
|---|---|
| `.cdb` | SQLite 卡牌数据库（`datas` 表 + `texts` 表）→ 多语言存于 `texts` 表按 `id` 关联 |
| `.lua` | 每个卡一个脚本，放在 `script/` 目录，文件名 = 卡牌 passcode（8 位数字） |
| `.conf` | 服务器/客户端配置 |
| 多语言 | `cards-<lang>.cdb`（见 B5.2，⚠️ 后缀清单未验证） |

**相关项目**：
- `drcael/YGO-CustomDatabaseCreator` — <https://github.com/drcael/YGO-CustomDatabaseCreator>
- `Satellaa/ocgcore` — <https://github.com/Satellaa/ocgcore>

### D4.2 卡图生成可行方案（推断，非引用）

> ⚠️ 以下为**技术可行性推断**，本轮未找到直接的游戏王卡图 AI 项目佐证。
- Stable Diffusion / SDXL + LoRA（游戏王卡图风格）
- ControlNet（控制构图，保证怪兽朝向与卡面构图一致）
- 已知难点：**风格统一**（同一系列的卡图应有一致的画风/色调/构图）

### D4.3 卡牌渲染 / 排版

| 资源 | URL | 说明 |
|---|---|---|
| YGOPRODeck 官方卡图（EN） | `https://images.ygoprodeck.com/images/cards/<id>.jpg` | 全尺寸；`cards_small/`、`cards_cropped/` |
| ⚠️ 使用限制 | API guide 明确要求：**不要持续热链图片**，必须下载并自行托管，否则 IP 会被拉黑 | <https://ygoprodeck.com/api-guide/> |
| 卡面字体参考 | <https://yugipedia.com/wiki/Card_layout> | 见 B4.2 字体表 |
| 卡面结构（部件清单） | 同上 | 卡种、卡名、属性、等级/阶级星、魔法陷阱种类、卡图、卡图边框、版本文字、卡号、灵摆刻度、连接标记、文本框、种族、效果/风味文本、ATK/DEF、密码、版权、Anubis 之眼 |

---

# E. 汇总：可直接编码的校验规则清单

## E1. 结构化解析规则（PSCT 分层器）

```
输入：卡文（单一语言）
输出：{ effectClass, activationCondition, cost[], targets[], resolution[], conjunctives[], hopt, arrowRefs[] }

步骤：
1. 拆效果编号（①②③ / ●）→ 得多个独立 effect 单元
   - 校验：编号从①起连续、无跳号
   - 校验：灵摆怪兽的灵摆效果编号接续怪兽效果编号
2. 对每个 effect 单元做三段切分（仅英文/中文按标点；日文按语序）
   - 若含 ':' → condition = 冒号前；否则 condition = 空（永续/无种类）
   - 若含 ';' → activation = 冒号后分号前；resolution = 分号后
   - 否则 → resolution = 冒号后全部
3. 分类：effectClass
   - 无 ':' 且无 ';' → CONTINUOUS 或 NON_EFFECT
   - 有 ':' 且 condition 含 '时/場合/When/If' → TRIGGER
   - 有 ':' 且 condition 含 '主要阶段/メインフェイズ/Main Phase' → IGNITION
   - 有 ':' 且含 'Quick Effect/对方回合' → QUICK
4. HOPT 提取：匹配「这个卡名的①②效果1回合各能使用1次」
5. 取对象提取：'以〜为对象' / 'target' 出现在 ';' 之前
6. 连接词扫描：then / also / and if you do / and / also, after that（英）
                その後 / また / その場合 / し / また、その後（日）
7. 场所与卡种提取：'怪兽' vs '卡'、'场上/墓地/卡组/手卡/除外'
```

## E2. 硬性错误（ERROR，必须拦截）

| ID | 规则 |
|---|---|
| A8.1 E01 | 入连锁的效果缺 `：` |
| A8.1 E02 | cost 写在 `；` 之后 |
| A8.1 E03 | 效果处理写在 `；` 之前 |
| A8.1 E04 | 触发效果缺时点（`时/場合`、`When/If`） |
| A8.1 E05 | 文本 `場合`/`If` 与脚本时点实现不一致 |
| A8.1 E06/E07 | 编号跳号 / 编号数与效果数不符 |
| A8.1 E09 | 检索类效果缺 HOPT |
| A8.1 E10–E15 | 素材/刻度/连接/灵摆写法错误 |
| A8.1 E24 | 字段引用与卡名引用混淆 |
| A8.1 E26/E27 | 效果外文本/召唤手续被当成效果 |
| A8.1 E28 | 内置特召缺 `（从〜）` 括号 |
| A1.5 | 多个 `●` 未声明 `in sequence` / `(simultaneously)` |
| A9.2 | HERO 大小写错误 |
| A7.1 | 旧术语残留（`remove from play` / `select` / `Life Points` / `Graveyard`） |

## E3. 软性警告（WARNING，提示设计者）

| ID | 规则 |
|---|---|
| C4.1 R01–R07 | 超模红旗（极高） |
| C4.1 R08–R16 | 超模红旗（高） |
| C4.1 R17–R22 | 超模红旗（中） |
| C3.1 | 等级 ≤4 且 ATK > 2000 / DEF ≥ 2500 但无负面效果 |
| C3.2 | ATK/DEF > 3000 但无召唤条件或负面效果 |
| C3.3 | 单卡效果条数 ≥3（提示）、≥4（警告） |
| C3.6 | 素材过泛 + 效果过强 |
| C5.1 | 系列内缺字段一致性 / 启动路径 <2 / 无 HOPT 回收 |
| A6.1 | 「1回合1次」而非 HOPT（可被重置 → 潜在 loop 风险） |
| A8.1 E23 | 效果条数过多 |

## E4. 跨语言生成规则（★关键差异）

| 规则 | 英文 | 日文 | 中文 |
|---|---|---|---|
| cost/target 边界 | 靠 `；` 分号 | 靠**语序**（`発動` 之前） | 靠**语序**（`发动` 之前） |
| 「会错过时点」 | `When`+可选 = 会；`If` = 不会 | `時` = 会；`場合` = 不会 | 同英文（`时`/`场合`） |
| 「直接连锁 vs 处理后再发动」 | **不区分** | ★**区分**（`時`=直接连锁；`場合`=处理后） | 同英文（**不区分**）→ ⚠️ 中文无法完整表达日文语义 |
| 同步 / 超量 / 协调 | Synchro / Xyz / Tuner | シンクロ / エクシーズ / チューナー | **同步 / 超量 / 协调**（官方） |
| Deck | Deck | デッキ | **牌组**（界面）/**卡组**（规则书） → ⚠️ 需统一 |

---

# F. 不确定项与未验证项

## F1. 明确未能验证的项

| # | 项 | 状态 | 建议 |
|---|---|---|---|
| 1 | YGOrganization 各文章正文 | HTTP **403**（Cloudflare） | 浏览器直接访问，或换 Google Cache |
| 2 | `ludoplex/yugioh-mcp-server` 的 README 与源码 | GitHub 网页 fetch **失败**；API readme **404** | `git clone` 或浏览器查看 ★**优先级最高** |
| 3 | `gryve/ygo-psct-parser` 的实际能力与覆盖率 | 仅确认仓库元数据 | 克隆后实测 |
| 4 | ECE1786 课程报告内容 | PDF 无法抓取 | 手动下载阅读 |
| 5 | Civitai 上的游戏王 LoRA | **未检索** | 定向搜索 civitai.com |
| 6 | HuggingFace 上的游戏王卡文数据集 | **未检索** | 定向搜索 `datasets?search=yugioh` |
| 7 | `cards-<lang>.cdb` 的确切语言后缀清单 | GitHub raw 抓取失败 | 查看 BabelCDB 仓库文件列表 |
| 8 | 官方规则书**最新版本号**及 PSCT 章节页码 | 仅知 Version 10 的 p.52–53 | 以官方页面实际 PDF 为准 |
| 9 | 官方数据库 `request_locale` 的完整语言代码清单 | 仅确认 `ja` / `en` | 逐一测试 |
| 10 | LLM 写 MTG / 炉石卡牌代码的项目 | **未找到** | 扩大检索范围 |
| 11 | PSCT 的 EBNF / 形式化文法 | **确认不存在公开版本** | 自行整理 |
| 12 | 日文 OCG 是否使用「；」分号 | 推论为**不使用**，未找到明文规定 | 以官方卡文实测验证 |
| 13 | 「卡组五类卡位」的权威命名体系 | **未找到** | 自定义分类 + 真实上位数据校准 |
| 14 | MTG「Design Skeleton」「New World Order」的确切官方链接 | 未验证 | 定向搜索 magic.wizards.com |
| 15 | 官方中文用语表的独立官方文档 | **确认不存在公开文件** | 用官方数据库界面用词（B3.2）+ OCG Rule 中文站（B3.3）替代 |
| 16 | YGOPRODeck API 是否新增 ja / zh 语言支持 | 文档（v7）仅列 fr/de/it/pt，与部分搜索结果表述不符 | 实测 `&language=ja` 与 `&language=zh` |

## F2. 来源可信度分级说明

| 级别 | 含义 | 本报告中的代表 |
|---|---|---|
| 🟢 **高** | 官方一手文档 / 官方规则书 / 官方 FAQ | PSCT Part 1–7、官方卡片数据库界面、OCG Rule（含 FAQ 链接） |
| 🟡 **中高** | 社区 wiki 但逐条引用官方页码；或大型社区站点 | Yugipedia（引用 Rulebook v10 p.52–53）、YGOPRODeck 文章、Cardmarket Insight |
| 🟡 **中** | 社区论坛经验总结 | Cardmaker 论坛、NGA、PTT |
| 🟡 **中低** | 社区惯例数值，无权威出处 | 卡组配比区间、起手率目标 |
| 🔴 **低 / 未验证** | 未能实抓或仅有搜索结果 | YGOrganization、ludoplex 仓库正文、Civitai、ECE1786 报告 |

## F3. ★给本项目的关键建议（基于调研结论）

1. **架构方向**：采用 **`ludoplex/yugioh-mcp-server` 的「Deterministic parser + 0 LLM interpretation」理念**——解析与校验必须确定性，LLM 只负责创意层。理由：PSCT 是**形式化程度很高**的规范，用 LLM 做校验会引入不可控的错误率。

2. **规范来源优先级**：
   - 第一优先：官方 PSCT Part 1–7 + 官方规则书
   - 第二优先：**Yugipedia PSCT 页**（`?action=raw`）——已把官方描述整理成可编码的 bullet 规则 + 连接词四象限表
   - 第三优先：**OCG Rule 中文站**——最详细、每条附官方 FAQ 链接与日期，**是构建测试用例的金矿**（每条裁定都是一个 test case）

3. **数据源选择**：
   - 卡牌数据：**YGOPRODeck API v7**（字段最全，`archetype` / `treated_as` / `has_effect` 直接可用）
   - 多语言：⚠️ **YGOPRODeck 只有 fr/de/it/pt**。中日文需另找来源：
     - 日文：官方日文数据库 / BabelCDB
     - 中文：**官方简中数据库 <https://db.yugioh-card-cn.com/>** ★唯一权威中文来源
   - 术语多语言对照：**Yugipedia Infobox 批量抓取**（B5.4，可自动化）
   - 卡文↔脚本配对语料：**ProjectIgnis/CardScripts** ★NL→Lua 的关键训练/验证资源

4. **优先实现的校验**（投入产出比最高）：
   - 冒号/分号三段切分（A1.2）——覆盖 DIY 最高频错误
   - 连接词语义四象限（A2.3）
   - 时 vs 场合（A3.2）
   - HOPT 三类区分（A6.1）
   - ATK/DEF 惯例阈值（C3.1/C3.2）——**有官方卡池统计支撑，最可靠**
   - 超模红旗 R01–R07（C4.1）

5. **跨语言生成的核心陷阱**：中日文**不使用分号**，且**日文的「時」额外携带「直接连锁 vs 处理后再发动」语义，中英文都无法表达**。若软件做多语言生成，必须为每种语言单独建模板，**不能做逐词直译**。

---

*报告结束。所有 URL 均为本轮调研实际访问或在搜索结果中明确出现；未能实抓的项已在 F1 标注。*
