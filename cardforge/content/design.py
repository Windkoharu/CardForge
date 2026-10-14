"""设计辅助与平衡审计 —— G1 / G4 的**确定性**判定核心。

设计哲学
--------
**质量门绝不交给概率模型。** 本模块的每条规则都是可以复现的数值或模式判断，
LLM 只能在"表达层"（艾莉娅的话术）参与，不能影响裁决。

规则来源
--------
* **ATK/DEF 惯例**：Yugipedia ``Level 4 ATK and DEF conventions`` 与
  ``Conventions of 3000 ATK and DEF`` —— 这两页是**官方卡池统计出来的成文惯例**，
  不是社区臆测：
    - 等级 ≤4 且可通常召唤：``ATK > 2000`` 必须有负面效果；``ATK = 2000``
      必须是通常怪兽或带负面效果；``DEF ≥ 2500`` 必须有负面效果或限制。
    - 4 星通常怪兽 ATK 上限 = 2000（官方在 Alexandrite Dragon 预览文里称为
      "the maximum possible ATK for a Level 4 Normal Monster"）。
    - ``ATK/DEF ≤ 3000`` 可无任何条件通常召唤；``> 3000`` 必须有负面效果或
      阻止通常召唤的条件。
* **效果条数**：官方建议单卡 ≤2 条；社区把 ≥3 条视为 Post-Modern 设计标志。
* **HOPT 作为平衡杠杆**：削弱一张卡应优先加 HOPT，而不是砍效果本体
  （Cardmarket 的禁限卡分析指出当时约 20% 的禁卡只需加 HOPT 即可解禁）。
* **泛用素材雷区**：Isolde / Baronne de Fleur / Union Carrier / Auroradon /
  Halqifibrax 的共同死因都是"素材条件太宽"，最终全部禁卡。
* **字段名查重**：Cipher Soldier（2004）因名字含 "Cipher" 被 16 年后的
  「Cipher」系列意外联动 —— 字段命名前必须查重。
* 卡组配比数值**是社区经验值，官方无规定**（官方只规定 40–60 / 15 / 15 / 同名 3），
  因此本模块把配比问题一律标为 ``WARN`` 而非 ``ERROR``。

另见 ``data/knowledge/游戏王设计方法论.md``。
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Iterable, Optional

from ..core.models import Archetype, CardSpec, DeckSpec, Issue, ROLES, RosterSlot
from ..core import constants as C

# ══════════════════════════════════════════════════════════════════════
#  阈值表（集中管理，便于用户覆盖与调参）
# ══════════════════════════════════════════════════════════════════════
LIMITS = {
    "max_effects": 2,             # 官方建议
    "warn_effects": 3,            # Post-Modern 设计警告线
    "error_effects": 4,           # 直接拦截
    "normal_atk_ceiling": 3000,   # 通常怪兽天花板（青眼白龙）
    "atk_hard_max": 5000,
    "l4_normal_atk_max": 2000,    # 4 星通常怪兽官方上限
    "l4_effect_atk_max": 2000,    # 4 星以下效果怪兽（无负面时）
    "low_level_def_max": 2500,
    "generic_summon_atk_max": 3000,   # 可无条件通常召唤的打点上限
    "dialect_max": 5,             # 系列方言句式上限
    "dialect_min": 3,
    "starter_paths_min": 2,       # 从零启动路径数下限
}
DECK_LIMITS = {
    "main_min": 40, "main_max": 60, "extra_max": 15, "side_max": 15, "same_max": 3,
}
#: 卡组功能角色的建议区间（社区经验值，非官方规定）
ROLE_RANGE = {
    "starter": (12, 15), "extender": (6, 10), "handtrap": (9, 15),
    "bomb": (0, 4), "flex": (3, 5),
}


# ══════════════════════════════════════════════════════════════════════
#  红旗规则（22 条，可编程）
# ══════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class RedFlag:
    code: str
    level: str          # ERROR / WARN / INFO
    zh: str             # 中文说明（给用户看）
    hint: str           # 可执行建议
    pattern: str = ""   # 卡文正则（在 PSCT 文本上匹配）
    kinds: tuple = ()   # 命中的效果种类
    only_if_unlimited: bool = False   # 仅当命中效果**没有任何回合限制**时才触发
    note: str = ""


RED_FLAGS: tuple[RedFlag, ...] = (
    RedFlag("RF01", "ERROR", "无条件从卡组特殊召唤",
            "加上「1回合1次」与召唤条件（如「自己场上没有怪兽存在的场合」）",
            pattern=r"从卡组(把|将).{0,12}特殊召唤"),
    RedFlag("RF02", "ERROR", "无代价抽卡",
            "补上代价或限制（每回合 1 次、丢弃 1 张手卡等）",
            pattern=r"自己(从卡组)?抽\d*张?卡(?![^。]{0,20}(回合|才能))"),
    RedFlag("RF03", "WARN", "墓地资源可反复利用且无 HOPT",
            "给该效果加「1回合1次」或「这个卡名的效果1回合只能使用1次」",
            kinds=("recover", "ssummon_grave"), only_if_unlimited=True),
    RedFlag("RF04", "ERROR", "存在无限 loop 风险（自我回收 + 无次数限制）",
            "给回手/特召效果加 HOPT 或「这张卡离场时除外」类限制"),
    RedFlag("RF05", "ERROR", "可能构成 FTK（先攻一回杀）",
            "降低单回合输出或加上「这个效果发动的回合，自己不能进行战斗阶段」类自肃"),
    RedFlag("RF06", "ERROR", "封锁对手操作（不能发动/不能召唤）",
            "改为「无效并破坏」这类可被应对的干扰，而非硬封锁"),
    RedFlag("RF07", "WARN", "手牌破坏效果",
            "手牌破坏强度极高，建议改为随机丢弃或加入发动条件"),
    RedFlag("RF08", "ERROR", "检索/特召未加 HOPT",
            "补「1回合1次」；现代卡默认卡名 HOPT",
            kinds=("search", "ssummon"), only_if_unlimited=True),
    RedFlag("RF09", "ERROR", "全卡组检索且无 HOPT",
            "限定检索范围（字段、种族、属性）并加 HOPT",
            kinds=("search",), only_if_unlimited=True),
    RedFlag("RF10", "ERROR", "无视召唤条件特殊召唤",
            "改为「当作融合召唤作特殊召唤」这类仍受素材限制的写法"),
    RedFlag("RF11", "WARN", "不取对象且不破坏（难以应对）",
            "改为取对象，或让对手有机会响应"),
    RedFlag("RF12", "ERROR", "「不受效果影响」泛滥",
            "全抗性是禁卡级能力，改为「不会被效果破坏」或限定回合数"),
    RedFlag("RF13", "ERROR", "一卡即可 FTK",
            "拆成需要 2 张以上协同的效果"),
    RedFlag("RF14", "WARN", "单卡承担过多角色（Post-Modern 判据）",
            "一张卡同时是检索+特召+终端，建议拆成两张"),
    RedFlag("RF15", "ERROR", "额外卡组素材条件过泛",
            "素材必须绑字段；禁止「任意 2 只怪兽」这类写法"),
    RedFlag("RF16", "WARN", "把卡组直接送去墓地（大规模）",
            "堆墓是强力资源获取，建议限定数量或加上自肃"),
    RedFlag("RF17", "WARN", "效果条数 ≥4",
            "拆成 2 张卡，或把其中一条移到魔法/陷阱上"),
    RedFlag("RF18", "ERROR", "字段名与官方卡池冲突",
            "换一个字段名（会意外联动到老卡）"),
    RedFlag("RF19", "WARN", "系列卡数过多",
            "一个需要大量卡才能自圆其说的系列通常是设计不良"),
    RedFlag("RF20", "WARN", "效果无法被手坑阻止",
            "让关键动作可被「灰流丽」这类手坑响应，保留应对空间"),
    RedFlag("RF21", "WARN", "存在不可被应对的连续压制",
            "至少留一个可以被连锁窗口打断的环节"),
    RedFlag("RF22", "WARN", "自肃过重（会拖垮自身）",
            "过重的自肃会让卡组无法运转，也会挡住未来的支援卡"),
)

#: 卡文中表示"负面效果/限制"的关键词 —— 用于判断高打点是否已有代价
_DRAWBACK_MARKERS = (
    "不能攻击", "不能作为", "不能特殊召唤", "不能通常召唤", "不能发动",
    "这个效果发动的回合", "自己不能", "只能", "必须", "直到回合结束时",
    "破坏", "除外", "丢弃", "解放", "支付", "不能进入战斗阶段",
    "攻击力变成", "原本攻击力",
)


def _has_drawback(spec: CardSpec, lang: str = "zh_cn") -> bool:
    txt = spec.text_in(lang) + " " + spec.flavor_in(lang)
    return any(m in txt for m in _DRAWBACK_MARKERS)


# ══════════════════════════════════════════════════════════════════════
#  G1 · 单卡平衡审计
# ══════════════════════════════════════════════════════════════════════
def audit_card(spec: CardSpec, official=None, lang: str = "zh_cn",
               check_pool: bool = True) -> list[Issue]:
    """G1 主体：返回问题清单（``ERROR`` 需拦截，``WARN`` 可豁免放行）。"""
    out: list[Issue] = []

    def add(code, level, msg, hint="", field=""):
        out.append(Issue(gate="G1", code=code, level=level, message=msg,
                         hint=hint, field=field))

    body = spec.text_in(lang)
    effects = spec.effect_specs()
    n_eff = len(effects)

    # ── 1. 效果条数 ──
    if n_eff >= LIMITS["error_effects"]:
        add("G1_EFFECT_COUNT_ERROR", "ERROR",
            f"效果条数 {n_eff} 条，超过 {LIMITS['error_effects']} 条上限",
            "拆成 2 张卡；单卡效果越多越容易失控，官方建议 ≤2 条", "effects")
    elif n_eff >= LIMITS["warn_effects"]:
        add("G1_EFFECT_COUNT_WARN", "WARN",
            f"效果条数 {n_eff} 条，超出官方建议的 {LIMITS['max_effects']} 条",
            "建议把其中一条移到配套的魔法/陷阱上", "effects")

    if not spec.is_monster:
        if spec.frame == "spell" and spec.spell_kind == "":
            add("G1_SPELL_KIND_MISSING", "WARN", "魔法卡未指定种类",
                "通常魔法/速攻/永续/装备/场地/仪式，缺省会被当作通常魔法",
                "spell_kind")
        if spec.frame == "trap" and spec.trap_kind == "":
            add("G1_TRAP_KIND_MISSING", "WARN", "陷阱卡未指定种类",
                "通常/永续/反击", "trap_kind")

    # ── 2. ATK/DEF 惯例（官方卡池统计出的成文惯例）──
    atk = spec.atk if isinstance(spec.atk, int) else None
    dfd = spec.dfd if isinstance(spec.dfd, int) else None
    lv = spec.effective_level
    drawback = _has_drawback(spec, lang)

    if spec.is_monster and atk is not None:
        if atk > LIMITS["atk_hard_max"]:
            add("G1_ATK_OVER_HARD", "ERROR",
                f"攻击力 {atk} 超过硬上限 {LIMITS['atk_hard_max']}",
                "官方卡池没有任何卡超过 5000", "atk")
        if spec.frame == "normal":
            if atk > LIMITS["normal_atk_ceiling"]:
                add("G1_NORMAL_ATK_CEILING", "ERROR",
                    f"通常怪兽攻击力 {atk} 超过 {LIMITS['normal_atk_ceiling']}",
                    "青眼白龙 3000 是通常怪兽的天花板", "atk")
            if lv <= 4 and atk > LIMITS["l4_normal_atk_max"]:
                add("G1_L4_NORMAL_ATK", "ERROR",
                    f"{lv} 星通常怪兽攻击力 {atk} 超过官方上限 "
                    f"{LIMITS['l4_normal_atk_max']}",
                    "官方明确规定 4 星通常怪兽 ATK 上限为 2000", "atk")
        else:
            can_normal = not (spec.type_bits & C.TYPE_SPSUMMON)
            if can_normal and lv <= 4 and atk > LIMITS["l4_effect_atk_max"] \
                    and not drawback:
                add("G1_L4_EFFECT_ATK", "ERROR",
                    f"{lv} 星可通常召唤的效果怪兽攻击力 {atk} 超过 "
                    f"{LIMITS['l4_effect_atk_max']} 且无负面效果",
                    "补一个负面效果（不能攻击/自肃/维持代价），或降打点", "atk")
            if can_normal and atk > LIMITS["generic_summon_atk_max"] and not drawback:
                add("G1_GENERIC_ATK", "ERROR",
                    f"攻击力 {atk} 超过 {LIMITS['generic_summon_atk_max']} "
                    f"却可无条件通常召唤",
                    "官方惯例：>3000 必须带负面效果或阻止通常召唤的条件", "atk")
        if dfd is not None and lv <= 4 and dfd >= LIMITS["low_level_def_max"] \
                and not drawback:
            add("G1_LOW_LEVEL_DEF", "WARN",
                f"{lv} 星怪兽守备力 {dfd} 达到 {LIMITS['low_level_def_max']} "
                f"且无负面效果",
                "官方惯例：低星高守备需要负面效果或限制", "dfd")

    # ── 3. HOPT ──
    if spec.is_monster and effects:
        risky = [e for e in effects
                 if e.kind in ("search", "ssummon", "draw", "recover", "ssummon_grave")]
        no_limit = [e for e in risky if (e.limit or "none") == "none"]
        if no_limit:
            add("G1_HOPT_MISSING", "ERROR",
                f"{len(no_limit)} 条检索/特召/抽卡类效果没有回合限制",
                "现代卡默认卡名 HOPT；补「这个卡名的①②效果1回合各能使用1次」",
                "effects")
        if len(effects) >= 2 and not any(
                (e.limit or "") in ("hopt_name", "hopt_name_activate") for e in effects):
            add("G1_HOPT_NAME_HINT", "WARN",
                "多效果卡建议使用「这个卡名」级别的 HOPT",
                "「1回合1次」只限制这张卡（离场会重置），卡名 HOPT 更保险",
                "effects")

    # ── 4. 额外卡组素材条件（泛用卡雷区）──
    if spec.frame_def.extra_deck:
        if not spec.archetype:
            add("G1_EXTRA_NO_ARCHETYPE", "ERROR",
                f"{spec.frame_def.zh_cn}没有绑定字段",
                "额外卡组素材必须绑字段；「任意 2 只怪兽」是禁卡制造机"
                "（Isolde / Baronne / Halqifibrax 的共同死因）", "archetype")
        m = re.search(r"任意\s*\d+\s*只", body)
        if m:
            add("G1_GENERIC_MATERIAL", "ERROR",
                f"素材条件含「{m.group(0)}」，过于宽泛",
                "改成「「字段」怪兽 ×2」这类绑定写法", "text")
        if not any(k in body for k in ("＋", "+", "×", "只")) and spec.frame != "link":
            add("G1_MATERIAL_MISSING", "WARN",
                "未找到明确的素材条件写法",
                "融合写「×＋×」、同步写「协调＋协调以外的怪兽」、"
                "超量写「4星怪兽×2」、连接写「效果怪兽2只」", "text")
    if spec.frame == "link" and not spec.link_markers:
        add("G1_LINK_NO_MARKER", "ERROR", "连接怪兽没有指定任何连接标记",
            "至少选 1 个方向；连接数由箭头数量决定", "link_markers")
    if spec.frame == "link":
        if C.link_rating_from_bits(spec.link_bits) > 6:
            add("G1_LINK_RATING", "WARN",
                f"连接数 {spec.effective_level} 偏高", "官方连接怪兽最高为 6", "level")

    # ── 5. 灵摆 ──
    if spec.is_pendulum:
        if spec.pendulum_scale is None:
            add("G1_PENDULUM_NO_SCALE", "ERROR", "灵摆卡没有设置灵摆刻度",
                "刻度范围 1–12，常见 1–8", "pendulum_scale")
        elif not (0 <= int(spec.pendulum_scale) <= 13):
            add("G1_PENDULUM_SCALE_RANGE", "WARN",
                f"灵摆刻度 {spec.pendulum_scale} 超出常规范围",
                "官方刻度在 0–13 之间，竞技常用 1–8", "pendulum_scale")
        if not spec.pendulum_text_in(lang).strip():
            add("G1_PENDULUM_NO_EFFECT", "INFO",
                "灵摆效果框为空", "灵摆卡通常有独立的灵摆效果文本", "pendulum_text")

    # ── 6. 速攻效果只有怪兽卡有 ──
    if not spec.is_monster and "速攻" not in body and spec.spell_kind == "quick":
        pass
    if not spec.is_monster and re.search(r"[②③④]\s*[:：]?.{0,10}(对手回合|对方回合).{0,6}(才能)?发动", body):
        add("G1_ST_SPEED", "WARN",
            "魔法/陷阱写成了「对手回合才能发动」的 2 速效果",
            "只有怪兽有 2 速诱发即时效果；魔陷请用「速攻魔法」「反击陷阱」表达",
            "text")

    # ── 7. 字段名查重（防 Cipher Soldier 事件）──
    if check_pool and spec.archetype:
        dup = dupcheck_archetype(spec.archetype, official)
        if dup.get("exact"):
            add("G1_ARCHETYPE_TAKEN", "ERROR",
                f"字段名「{spec.archetype}」与官方已有字段重名",
                f"官方示例：{'、'.join(dup['exact'][:3])}；换一个名避免意外联动",
                "archetype")
        elif dup.get("substring"):
            add("G1_ARCHETYPE_SUBSTRING", "WARN",
                f"字段名「{spec.archetype}」是官方卡名的子串，可能被意外联动",
                f"命中：{'、'.join(dup['substring'][:3])}", "archetype")
        if dup.get("error"):
            add("G1_POOL_UNAVAILABLE", "INFO",
                f"官方卡池不可用，已跳过字段查重（{dup['error']}）",
                "把 cards_zh.cdb 放到 vendor/data/ 后重跑", "")

    # ── 8. setcode 冲突 ──
    if spec.setcode and spec.setcode not in ("0x0", "0", ""):
        used = _setcode_collision(spec.setcode, official)
        if used:
            add("G1_SETCODE_TAKEN", "ERROR",
                f"setcode {spec.setcode} 已被"
                f"{len(used)} 张卡占用（如 {used[0] if used else ''}）",
                "用 `cardforge archetype new` 自动分配一个空闲 setcode",
                "setcode")

    # ── 9. 卡号冲突 ──
    if spec.id and check_pool and official is not None:
        try:
            if official.id_taken(spec.id):
                add("G1_ID_TAKEN", "ERROR",
                    f"卡号 {spec.id} 已被官方卡占用", "换一个 DIY 专用号段（≥ 210000000）",
                    "id")
        except Exception:
            pass
    if spec.id and spec.id < 210000000:
        add("G1_ID_RANGE", "WARN",
            f"卡号 {spec.id} 在官方号段内，有冲突风险",
            "建议使用 210000000 起的 DIY 号段", "id")

    # ── 10. 卡文红旗（正则扫描）──
    for rf in RED_FLAGS:
        if rf.pattern and re.search(rf.pattern, body):
            add(f"G1_{rf.code}", rf.level, rf.zh, rf.hint, "text")
        elif rf.kinds and any(e.kind in rf.kinds for e in effects):
            hits = [e for e in effects if e.kind in rf.kinds]
            if rf.only_if_unlimited and all(
                    (e.limit or "none") != "none" for e in hits):
                continue        # 已经带了回合限制 —— 不构成红旗
            if not any(i.code == f"G1_{rf.code}" for i in out):
                add(f"G1_{rf.code}", rf.level, rf.zh, rf.hint, "effects")

    # ── 11. 文本是否为空 ──
    if spec.is_monster and spec.frame != "normal" and not effects and not body.strip():
        add("G1_EMPTY_TEXT", "WARN", "效果怪兽没有卡文",
            "补上效果文本，或把卡种改为通常怪兽", "text")
    if spec.frame == "normal" and not spec.flavor_in(lang).strip():
        add("G1_NO_FLAVOR", "INFO", "通常怪兽没有说明文",
            "通常怪兽按惯例应有一段风味说明文", "flavor")

    # ── 12. 命名 ──
    if not spec.name.strip():
        add("G1_NAME_EMPTY", "ERROR", "卡名为空", "填写卡名", "name")
    elif len(spec.name) > 40:
        add("G1_NAME_LONG", "WARN", f"卡名 {len(spec.name)} 字，偏长",
            "过长的卡名会在卡面卡名条上被压缩，建议 ≤20 字", "name")

    return out


def _setcode_collision(setcode, official) -> list[str]:
    if official is None:
        return []
    try:
        rows = official.setcode_used(setcode)
        return [r.get("name", "") for r in (rows or [])][:5]
    except Exception:
        return []


def dupcheck_archetype(name: str, official=None) -> dict:
    """字段名查重：既查"精确同名"，也查"是官方卡名的子串"（后者才是 Cipher 事件的成因）。"""
    name = (name or "").strip()
    res = {"name": name, "exact": [], "substring": [], "error": "", "checked": False}
    if not name or official is None:
        if official is None:
            res["error"] = "未提供官方卡池"
        return res
    try:
        hits = official.archetype_hits(name, limit=8)
        res["checked"] = True
        for h in hits:
            nm = h.get("name", "")
            if nm == name or nm.startswith(name + "·") or nm.endswith("·" + name):
                res["exact"].append(nm)
            elif name in nm:
                res["substring"].append(nm)
    except Exception as e:
        res["error"] = str(e)[:120]
    return res


# ══════════════════════════════════════════════════════════════════════
#  G4 · 系列一致性
# ══════════════════════════════════════════════════════════════════════
def audit_archetype(arch: Archetype, cards: Iterable[CardSpec],
                    official=None) -> list[Issue]:
    """G4：方言句式数量 / 属性种族交集 / 启动路径 / 泛用素材 / 角色覆盖率。"""
    cards = [c for c in cards if c is not None]
    out: list[Issue] = []

    def add(code, level, msg, hint=""):
        out.append(Issue(gate="G4", code=code, level=level, message=msg, hint=hint))

    if not cards:
        add("G4_NO_CARDS", "ERROR", "该系列还没有任何卡", "先用 series build 生成卡表草稿")
        return out

    # ── 1. 方言句式数量 ──
    dialects = [d.strip() for d in (arch.dialects or []) if str(d).strip()]
    if len(dialects) > LIMITS["dialect_max"]:
        add("G4_DIALECT_TOO_MANY", "WARN",
            f"方言句式 {len(dialects)} 条，超过上限 {LIMITS['dialect_max']} 条",
            "超过说明系列失焦；好系列让同一句式在多张卡上重复出现（Kozmo 范式）")
    elif dialects and len(dialects) < LIMITS["dialect_min"]:
        add("G4_DIALECT_FEW", "INFO",
            f"方言句式只有 {len(dialects)} 条", "3–5 条最能形成系列身份感")

    # 实际卡文里出现的共同句式片段（不依赖 arch.dialects 是否填写）
    if len(cards) >= 4:
        shared = _shared_phrases([c.text_in("zh_cn") for c in cards])
        if len(shared) > LIMITS["dialect_max"] + 2:
            add("G4_DIALECT_DRIFT", "WARN",
                f"卡文里检测到 {len(shared)} 种重复句式，系列语言偏散",
                f"最集中的几种：{'；'.join(list(shared)[:3])}")

    # ── 2. 属性 / 种族交集 ──
    attrs = {c.attribute for c in cards if c.is_monster}
    races = {c.race for c in cards if c.is_monster}
    if len(attrs) > 3:
        add("G4_ATTR_SCATTER", "WARN",
            f"系列横跨 {len(attrs)} 种属性（{'、'.join(sorted(attrs))}）",
            "属性越散越难互相支援；绑定 1–2 种属性最稳")
    if len(races) > 3:
        add("G4_RACE_SCATTER", "WARN",
            f"系列横跨 {len(races)} 种族（{'、'.join(sorted(races))}）",
            "种族越散越难互相支援；绑定 1–2 个种族最稳")
    if arch.binding:
        want_a, want_r = arch.binding.get("attribute"), arch.binding.get("race")
        if want_a:
            off = [c.display_name for c in cards if c.is_monster and c.attribute != want_a]
            if off and len(off) > len(cards) * 0.35:
                add("G4_BINDING_BROKEN", "WARN",
                    f"{len(off)} 张卡偏离了锚点属性「{want_a}」",
                    f"偏离的卡：{'、'.join(off[:4])}")
        if want_r:
            off = [c.display_name for c in cards if c.is_monster and c.race != want_r]
            if off and len(off) > len(cards) * 0.35:
                add("G4_BINDING_BROKEN_RACE", "WARN",
                    f"{len(off)} 张卡偏离了锚点种族「{want_r}」",
                    f"偏离的卡：{'、'.join(off[:4])}")

    # ── 3. 从零启动路径 ≥2 ──
    starters = [c for c in cards
                if any(e.kind in ("search", "ssummon", "ssummon_deck") for e in c.effect_specs())]
    if len(starters) < LIMITS["starter_paths_min"]:
        add("G4_STARTER_FEW", "ERROR",
            f"只有 {len(starters)} 条从零启动路径（要求 ≥{LIMITS['starter_paths_min']}）",
            "启动路径少于 2 条，吃一手坑就死；补 1–2 张单卡启动点")
    elif len(starters) < 4:
        add("G4_STARTER_TIGHT", "INFO",
            f"从零启动路径 {len(starters)} 条，偏紧", "建议 4 条以上更稳")

    # ── 4. 泛用素材出现在本家额外卡组 ──
    for c in cards:
        if c.frame_def.extra_deck:
            body = c.text_in("zh_cn")
            if re.search(r"任意\s*\d+\s*只", body) or "任意2只怪兽" in body.replace(" ", ""):
                add("G4_GENERIC_EXTRA", "ERROR",
                    f"「{c.display_name}」的素材条件过于宽泛",
                    "本家额外卡组必须绑字段，否则会被外挂滥用")

    # ── 5. 角色覆盖率 ──
    if arch.roster:
        missing = []
        for slot in arch.roster:
            done = len(slot.done or [])
            if done < int(slot.count or 0):
                role_zh = ROLES.get(slot.role, {}).get("zh_cn", slot.role)
                missing.append(f"{role_zh} {done}/{slot.count}")
        if missing:
            add("G4_ROSTER_INCOMPLETE", "WARN",
                f"卡表仍有空缺：{'；'.join(missing)}",
                "五类角色齐全的系列才转得动")
    else:
        add("G4_NO_ROSTER", "INFO", "系列圣经没有卡表蓝图",
            "用 build_roster 生成初动/展开/终端/支援/回收的槽位")

    # ── 6. 卡数边界 ──
    if len(cards) > 20:
        add("G4_TOO_MANY_CARDS", "WARN",
            f"单次提交 {len(cards)} 张卡，超过 ~20 张的阅读负担线",
            "系列卡数过多通常是设计不良的信号（HERO 因此分裂成大量子系列）")

    # ── 7. 目标强度与泛用度 ──
    if arch.target_power == "casual":
        strong = [c.display_name for c in cards if _power_score(c) >= 4]
        if len(strong) >= 3:
            add("G4_POWER_MISMATCH", "INFO",
                f"声明为娱乐强度，但有 {len(strong)} 张卡强度偏高",
                f"如：{'、'.join(strong[:3])}")

    return out


_DIALECT_RE = re.compile(r"(这张卡在墓地存在的场合|自己场上有.{0,10}存在的场合|"
                         r"把自己场上1只.{0,12}解放才能发动|"
                         r"从卡组把1张.{0,12}加入手卡|"
                         r"这张卡特殊召唤成功(的场合|时))")


def _shared_phrases(texts: list[str]) -> list[str]:
    """找出在多张卡文里重复出现的句式片段（方言句式的实测版）。"""
    from collections import Counter
    cnt: Counter = Counter()
    for t in texts:
        for m in set(_DIALECT_RE.findall(t or "")):
            cnt[m] += 1
    return [p for p, n in cnt.most_common() if n >= 2]


def _power_score(spec: CardSpec) -> int:
    """粗略强度评分（0–6），仅用于提示，不作为拦截依据。"""
    s = 0
    kinds = {e.kind for e in spec.effect_specs()}
    s += 1 if "search" in kinds else 0
    s += 1 if kinds & {"ssummon", "ssummon_deck", "ssummon_grave"} else 0
    s += 1 if kinds & {"negate", "destroy_all", "banish"} else 0
    s += 1 if "draw" in kinds else 0
    if spec.frame_def.extra_deck:
        s += 1
    if isinstance(spec.atk, int) and spec.atk >= 3000:
        s += 1
    if len(spec.effect_specs()) >= 3:
        s += 1
    no_limit = [e for e in spec.effect_specs() if (e.limit or "none") == "none"]
    s -= 1 if len(no_limit) == 0 else 0
    return max(0, min(6, s))


# ══════════════════════════════════════════════════════════════════════
#  系列蓝图
# ══════════════════════════════════════════════════════════════════════
_POWER_SCALE = {"casual": 1.0, "rogue": 1.15, "competitive": 1.35}


def build_roster(arch: Archetype) -> list[RosterSlot]:
    """按目标强度把角色数量缩放到合理区间。"""
    k = _POWER_SCALE.get(getattr(arch, "target_power", "casual"), 1.0)
    slots: list[RosterSlot] = []
    for role, meta in ROLES.items():
        if role == "handtrap":
            continue          # 手坑属于卡组层，不属于系列卡表
        lo, hi = meta["range"]
        n = int(round((lo + hi) / 2 * k))
        n = max(lo, min(hi, n))
        slots.append(RosterSlot(role=role, count=n, brief=meta["brief"]))
    return slots


_TRUMP_FRAME = {
    "FUSION": "fusion", "SYNCHRO": "synchro", "XYZ": "xyz",
    "LINK": "link", "RITUAL": "ritual", "MAIN": "effect",
}


def plan_series(arch: Archetype) -> list[dict]:
    """把系列圣经展开成"待造卡清单"：每个槽位一条需求摘要。"""
    roster = arch.roster or build_roster(arch)
    trump = (arch.trumps or ["MAIN"])[0]
    plan: list[dict] = []
    idx = 1
    for slot in roster:
        role_zh = ROLES.get(slot.role, {}).get("zh_cn", slot.role)
        for i in range(int(slot.count or 0)):
            is_trump = slot.role == "trump"
            frame = _TRUMP_FRAME.get(trump, "effect") if is_trump else (
                "spell" if slot.role == "support" and i % 2 else "effect")
            brief = slot.brief
            if slot.role == "starter":
                brief = "单卡从零启动：检索或特召本家，带卡名 HOPT"
            elif slot.role == "trump":
                brief = f"终端（{frame}）：具备压制或斩杀能力，素材必须绑字段"
            elif slot.role == "recovery":
                brief = "从墓地/除外区回手，闭合资源循环，必须 HOPT"
            elif slot.role == "support":
                brief = "本家魔法/陷阱：检索或干扰，与方言句式一致"
            plan.append({
                "slot": slot.role, "slot_zh": role_zh, "index_in_slot": i + 1,
                "suggested_frame": frame, "brief": brief,
                "dialect_hint": (arch.dialects or [""])[
                    (idx - 1) % max(1, len(arch.dialects or [""]))] if arch.dialects else "",
                "binding": dict(arch.binding or {}),
                "archetype": arch.name, "setcode": arch.setcode,
            })
            idx += 1
    return plan


def suggest_setcode(official=None, start: int = 0x1000, end: int = 0xFFF0) -> str:
    """从安全区挑一个未被官方占用的 setcode。"""
    if official is None:
        return hex(start)
    v = start
    while v <= end:
        try:
            if not official.setcode_used(hex(v)):
                return hex(v)
        except Exception:
            break
        v += 1
    return hex(start)


# ══════════════════════════════════════════════════════════════════════
#  卡组层
# ══════════════════════════════════════════════════════════════════════
def opening_probability(n_starters: int, deck_size: int = 40, hand: int = 5) -> float:
    """起手至少抽到 1 张初动点的概率（超几何分布）。"""
    try:
        from math import comb
        n, d, h = int(n_starters), int(deck_size), int(hand)
        if n <= 0 or d <= 0 or h <= 0 or n > d:
            return 0.0
        return 1.0 - comb(d - n, h) / comb(d, h)
    except Exception:
        return 0.0


def analyze_deck(deck: DeckSpec, cards: dict, *, lang: str = "zh_cn") -> dict:
    """卡组分析：卡位覆盖 / 功能性冗余 / 初动率 / 手牌质量。

    **核心心法**（写进结论里）：如果卡 B 只在卡 A 已启动后才有用，那 B 不是初动的
    冗余，它是展开点。判据：抽到它，能不能多一条"从零启动"的路？
    """
    cards = cards or {}

    def entries(lst):
        return [e for e in (lst or []) if getattr(e, "count", 0)]

    main = entries(deck.main)
    extra = entries(deck.extra)
    side = entries(deck.side)
    main_n = sum(e.count for e in main)

    roles: dict[str, int] = {}
    starters, extenders, garnets = [], [], []
    for e in main:
        role = e.role or ""
        roles[role] = roles.get(role, 0) + e.count
        spec = cards.get(e.card_id)
        if spec is None:
            continue
        kinds = {k.kind for k in spec.effect_specs()}
        has_search = "search" in kinds
        has_summon = bool(kinds & {"ssummon", "ssummon_deck", "ssummon_grave"})
        needs_setup = any(k in (spec.text_in(lang) or "")
                          for k in ("自己场上有", "这张卡在墓地存在", "自己墓地有"))
        if has_search or (has_summon and not needs_setup):
            starters.append((spec.display_name, e.count))
        elif has_summon or has_search:
            extenders.append((spec.display_name, e.count))
        if needs_setup and not has_search:
            garnets.append((spec.display_name, e.count))

    deal_with_later = {
        "main_total": main_n, "extra_total": sum(e.count for e in extra),
        "side_total": sum(e.count for e in side),
        "role_counts": roles,
        "starter_cards": starters, "extender_cards": extenders, "garnet_cards": garnets,
        "starter_copies": sum(c for _, c in starters),
        "opening_rate": round(opening_probability(sum(c for _, c in starters), main_n or 40), 4),
        "issues": [],
    }

    issues: list[dict] = deal_with_later["issues"]

    def add(code, level, msg, hint=""):
        issues.append({"code": code, "level": level, "message": msg, "hint": hint})

    if main_n and not (DECK_LIMITS["main_min"] <= main_n <= DECK_LIMITS["main_max"]):
        add("DK_MAIN_SIZE", "ERROR",
            f"主卡组 {main_n} 张，超出 {DECK_LIMITS['main_min']}–"
            f"{DECK_LIMITS['main_max']} 张", "40 张的初动上手率最高")
    if deal_with_later["extra_total"] > DECK_LIMITS["extra_max"]:
        add("DK_EXTRA_SIZE", "ERROR",
            f"额外卡组 {deal_with_later['extra_total']} 张，超过 "
            f"{DECK_LIMITS['extra_max']} 张", "压缩到 15 张以内")
    if deal_with_later["side_total"] > DECK_LIMITS["side_max"]:
        add("DK_SIDE_SIZE", "ERROR",
            f"副卡组 {deal_with_later['side_total']} 张，超过 "
            f"{DECK_LIMITS['side_max']} 张", "副卡组上限 15 张")

    seen: dict[int, int] = {}
    for e in main + extra:
        seen[e.card_id] = seen.get(e.card_id, 0) + e.count
    for cid, n in seen.items():
        if n > DECK_LIMITS["same_max"]:
            nm = (cards.get(cid).display_name if cards.get(cid) else str(cid))
            add("DK_SAME_LIMIT", "ERROR",
                f"「{nm}」放了 {n} 张，超过同名 3 张上限", "减到 3 张以内")

    # 角色配比（社区经验值 → 一律 WARN）
    role_map = {"starter": "starter", "extender": "extender",
                "handtrap": "handtrap", "bomb": "bomb", "flex": "flex"}
    for role, (lo, hi) in ROLE_RANGE.items():
        n = roles.get(role_map[role], 0)
        if n == 0 and role in ("starter",):
            add("DK_NO_STARTER", "ERROR", "没有任何初动点", "初动至少 12 张")
        elif n < lo:
            add(f"DK_{role.upper()}_LOW", "WARN",
                f"{ROLES.get(role, {}).get('zh_cn', role)} 只有 {n} 张，建议 {lo}–{hi}",
                "配比是社区经验值，按环境微调")
        elif n > hi:
            add(f"DK_{role.upper()}_HIGH", "WARN",
                f"{ROLES.get(role, {}).get('zh_cn', role)} 有 {n} 张，建议 {lo}–{hi}",
                "过多会稀释其他卡位")

    rate = deal_with_later["opening_rate"]
    if rate < 0.75:
        add("DK_LOW_OPENING", "WARN",
            f"初动上手率只有 {rate:.1%}", "官方上位卡组普遍在 85% 以上")
    if garnets:
        add("DK_GARNET", "INFO",
            f"发现 {len(garnets)} 张「必需但难以调度」的组件",
            "抽到手里就是废牌，数量越少越好（石榴石概念）")

    return deal_with_later
