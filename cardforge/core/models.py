"""领域模型 —— 全工程的数据契约。

设计原则
--------
1. **``CardSpec`` 是全流程唯一真相源。** 卡面、卡文、Lua、cdb、ydk 全部由它派生。
2. 所有模型都是 ``dataclass``，带 ``to_dict`` / ``from_dict`` / ``SCHEMA_VERSION``。
   读旧文件时自动迁移，写文件时总是写最新版。
3. 面向用户的字段用**中文/可读值**（``"炎"``、``"魔法师族"``、``"效果"``），
   位掩码等引擎细节由 ``CardSpec.type_bits`` 等**属性**惰性推导。
4. 面向脚本的字段用**稳定键**（``kind``、``trigger``），不随展示名变化。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Optional

from . import constants as C
from .enums import (
    DEFAULT_LANG, FRAMES, LANGS, MONSTER_TAGS, RARITIES, SPELL_KINDS, TRAP_KINDS,
)

SCHEMA_VERSION = 2


# ══════════════════════════════════════════════════════════════════════
#  通用小工具
# ══════════════════════════════════════════════════════════════════════
def _clean(d: dict) -> dict:
    """丢掉 None 与空容器，让落盘 JSON 干净可读。"""
    out = {}
    for k, v in d.items():
        if v is None or v == "" or v == [] or v == {}:
            continue
        out[k] = v
    return out


class _Base:
    """给所有 dataclass 提供 to_dict / from_dict（忽略未知字段，向后兼容）。"""

    SCHEMA_VERSION = SCHEMA_VERSION

    def to_dict(self) -> dict:
        d = asdict(self)  # type: ignore[arg-type]
        d["schema_version"] = self.SCHEMA_VERSION
        return d

    def to_json_dict(self) -> dict:
        """落盘用：去掉空值，保留 schema_version。"""
        d = _clean(asdict(self))  # type: ignore[arg-type]
        d["schema_version"] = self.SCHEMA_VERSION
        return d

    @classmethod
    def from_dict(cls, d: dict):
        if not isinstance(d, dict):
            raise TypeError(f"{cls.__name__}.from_dict 需要 dict，收到 {type(d).__name__}")
        allowed = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in allowed})  # type: ignore[call-arg]


# ══════════════════════════════════════════════════════════════════════
#  效果 IR
# ══════════════════════════════════════════════════════════════════════
@dataclass
class EffectTarget:
    """效果的作用对象描述。"""
    from_zone: str = ""          # DECK/HAND/GRAVE/REMOVED/FIELD/EXTRA/MZONE/SZONE
    to_zone: str = ""
    filter_kind: str = "any"     # any/archetype/race/attribute/type/level/name
    filter_value: Any = None
    count: int = 1
    count_max: int = 0           # 0 = 与 count 相同
    controller: str = "self"     # self/opponent/both
    exclude_self: bool = False

    def to_dict(self) -> dict:
        return _clean(asdict(self))

    @classmethod
    def from_dict(cls, d):
        if isinstance(d, str):  # 容错：直接给个 zone 名
            return cls(from_zone=d)
        return _Base.from_dict.__func__(cls, d)  # type: ignore[attr-defined]


@dataclass
class EffectCost:
    """代价（写在卡文分号之前；中文/日文靠语序表达）。"""
    kind: str = "none"           # none/release/discard/send_grave/pay_lp/banish/tribute_self/detach
    zone: str = ""
    count: int = 1
    filter_kind: str = "any"
    filter_value: Any = None
    lp: int = 0

    def to_dict(self) -> dict:
        return _clean(asdict(self))

    @classmethod
    def from_dict(cls, d):
        if not d:
            return None
        if isinstance(d, str):
            return cls(kind=d)
        return _Base.from_dict.__func__(cls, d)  # type: ignore[attr-defined]


#: 效果发动次数限制 —— 三种写法语义不同，绝不合并（调研结论）
EFFECT_LIMITS = {
    "none": "无限制",
    "once_per_turn": "1回合1次（限制这张卡；离场/翻里侧重置）",
    "hopt_name": "这个卡名的①②效果1回合各能使用1次（限制玩家+原本卡名；use）",
    "hopt_name_activate": "这个卡名的效果1回合只能发动1次（activate，被无效可再发）",
    "once_while_faceup": "这张卡表侧表示期间1次",
    "once_duel": "决斗中1次",
}


@dataclass
class EffectSpec:
    """一条效果的 IR。卡文与 Lua 都是它的投影。

    ``kind`` 对应 ``content/effects.py`` 注册表里的效果种类键。
    ``trigger`` 对应时点键；``IGNITION``/``CONTINUOUS`` 等为无时点类。
    """
    kind: str = ""
    trigger: str = "IGNITION"
    target: Optional[EffectTarget] = None
    cost: Optional[EffectCost] = None
    limit: str = "once_per_turn"
    params: dict = field(default_factory=dict)
    raw_text: str = ""           # 用户原话，供追溯与 linter 提示
    note: str = ""               # 作者备注，不进卡文
    source: str = "manual"       # manual | template | llm

    @property
    def index(self) -> int:
        return int(self.params.get("_index", 0))

    def to_dict(self) -> dict:
        d = _clean(asdict(self))
        if self.target:
            d["target"] = self.target.to_dict()
        if self.cost:
            d["cost"] = self.cost.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "EffectSpec":
        d = dict(d or {})
        tgt = d.pop("target", None)
        cost = d.pop("cost", None)
        allowed = set(cls.__dataclass_fields__)
        obj = cls(**{k: v for k, v in d.items() if k in allowed})
        obj.target = EffectTarget.from_dict(tgt) if tgt else None
        obj.cost = EffectCost.from_dict(cost) if cost else None
        return obj


#: 常用时点键（供 UI 下拉与 linter 校验；Lua 侧映射在 content/lua/fragments）
TRIGGERS = {
    "IGNITION": "起动效果（自己主要阶段）",
    "CONTINUOUS": "永续效果（不入连锁）",
    "QUICK": "诱发即时效果（2 速）",
    "NORMAL_SUMMON_SUCCESS": "召唤成功时",
    "SPECIAL_SUMMON_SUCCESS": "特殊召唤成功时",
    "FLIP_SUMMON": "反转召唤成功时",
    "SUMMON_ANY_SUCCESS": "召唤·特殊召唤成功时",
    "WHEN_DESTROYED": "被破坏时",
    "WHEN_SENT_GRAVE": "被送去墓地时",
    "WHEN_BANISHED": "被除外时",
    "WHEN_TO_HAND": "加入手卡时",
    "ON_ACTIVATE": "发动时",
    "DAMAGE_STEP_START": "伤害步骤开始时",
    "BATTLE_DESTROY_SELF": "战斗破坏对方怪兽时",
    "BATTLE_DESTROYED_SELF": "被战斗破坏时",
    "ATTACK_DECLARE": "攻击宣言时",
    "OPPONENT_ACTIVATE": "对方发动效果时",
    "END_PHASE": "结束阶段",
    "STANDBY_PHASE": "准备阶段",
    "EQUIP_RELATED": "装备相关",
}


# ══════════════════════════════════════════════════════════════════════
#  渲染选项
# ══════════════════════════════════════════════════════════════════════
@dataclass
class FullArtOptions:
    """出框参数（与罕贵正交，可叠加）。"""
    mode: str = "none"                 # enums.FULL_ART_MODES 的键
    bleed_top: float = 0.0             # 向上溢出（卡图窗高度的比例）
    bleed_bottom: float = 0.0
    panel_opacity: float = 0.86        # 被插画压住时文本面板的不透明度
    name_stroke: float = 1.6           # 卡名描边强度（超框时保证可读）
    fade_px: float = 0.0               # 插画下缘渐隐高度（0=硬边）
    #: 仅 ``subject_bleed`` 档使用：主体层相对卡图窗的放大倍率（1.0=不出框）
    subject_scale: float = 0.0         # 0 = 按 geometry.FULLART_DEFAULTS 取默认
    #: 主体层垂直偏移（占窗高比例，负=上移，让头/武器越出窗沿）
    subject_offset_y: float = 0.0

    def to_dict(self) -> dict:
        return _clean(asdict(self))

    @classmethod
    def from_dict(cls, d):
        return _Base.from_dict.__func__(cls, d or {})  # type: ignore[attr-defined]


@dataclass
class RenderOptions:
    """卡面渲染参数。默认值即"看起来最像官方卡"的一组。"""
    rarity: str = "common"
    fullart: FullArtOptions = field(default_factory=FullArtOptions)
    # 语言：卡名 / 卡文 / 界面分别可控（支持"日中双语卡"这类 DIY 玩法）
    lang_name: str = DEFAULT_LANG
    lang_text: str = DEFAULT_LANG
    lang_flavor: str = DEFAULT_LANG
    # 美术
    art_fit: str = "cover"             # cover/contain/smart（smart=按卡种构图裁切）
    art_offset_y: float = 0.0          # -0.5 ~ 0.5，微调插画垂直构图
    art_scale: float = 1.0
    art_ring: float = 0.0              # 卡图窗内描边（0=不画）
    #: 卡图窗的**官方斜切框 + 过渡**（钢色带/暗线/亮发丝/框侧暗部渐变）。
    #: 默认开 —— 官方印刷卡实测每一张都有这层，关掉就变成"贴图"。0=关，1=官方量。
    bezel: float = 1.0
    # 文本
    font_scale_name: float = 1.0
    font_scale_text: float = 1.0
    text_align: str = "left"
    psct_bold: bool = True             # 效果编号与关键词加粗（还原官方观感）
    # 元信息
    show_password: bool = True
    show_copyright: bool = True
    copyright_lang: str = ""           # 空=跟随 lang_text
    show_stamp20: bool = False
    show_laser: bool = True
    set_number: str = ""               # 卡号，如 "CF01-JP001"
    # 输出
    preview_width: int = 480
    output_size: str = "edopro"        # edopro(421x614) | share(813x1185) | print(1394x2031) | native(1394x2031)

    def to_dict(self) -> dict:
        d = _clean(asdict(self))
        d["fullart"] = self.fullart.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "RenderOptions":
        d = dict(d or {})
        fa = d.pop("fullart", None)
        # 界面上「出框档位」是个下拉，历史实现把**字符串**直接塞回 render.fullart，
        # 于是改完档位再保存就炸（"需要 dict，收到 str"）。这里两种写法都收：
        #   "art_over"            → {"mode": "art_over"}
        #   {"mode": "..."}       → 原样
        # 另外把散落在 render 层的出框子键收进 fullart —— 界面滑杆就是平铺发的，
        # 不收的话它们会被"未知字段忽略"静默丢掉，用户调了没反应。
        if isinstance(fa, str):
            fa = {"mode": fa}
        elif fa is None:
            fa = {}
        elif not isinstance(fa, dict):
            raise ValueError(
                "render.fullart 只能是档位名字符串（如 \"art_over\"）或 "
                f"{{\"mode\": ...}} 对象，收到 {type(fa).__name__}：{fa!r}")
        if isinstance(fa, dict):
            for k in ("bleed_top", "bleed_bottom", "panel_opacity", "name_stroke",
                      "fade_px", "subject_scale", "subject_offset_y"):
                if k in d and k not in fa:
                    fa[k] = d.pop(k)
            if not str(fa.get("mode") or "").strip():
                fa["mode"] = "none"       # 空档位会让界面下拉框选中"无"以外的空项
        allowed = set(cls.__dataclass_fields__)
        obj = cls(**{k: v for k, v in d.items() if k in allowed})
        if fa:
            obj.fullart = FullArtOptions.from_dict(fa)
        return obj


# ══════════════════════════════════════════════════════════════════════
#  卡牌规格（真相源）
# ══════════════════════════════════════════════════════════════════════
@dataclass
class CardSpec(_Base):
    """单卡规格。字段全部面向用户可读，位掩码由属性推导。"""
    SCHEMA_VERSION = SCHEMA_VERSION

    id: int = 0
    name: str = ""
    name_i18n: dict = field(default_factory=dict)      # {"ja": "...", "en": "..."}
    frame: str = "effect"                              # enums.FRAMES 的键
    attribute: str = "暗"                              # 中文属性名
    race: str = "战士族"                                # 中文种族名
    level: int = 4                                     # 等级/阶级/连接数（连接数由箭头推导）
    atk: Any = 0                                       # int 或 "?" 
    dfd: Any = 0                                       # 守备力（避免与内置 def 冲突）
    pendulum_scale: Optional[int] = None
    spell_kind: str = ""                               # SPELL_KINDS 的键
    trap_kind: str = ""                                # TRAP_KINDS 的键
    tags: list = field(default_factory=list)           # MONSTER_TAGS 的键：tuner/spirit/...
    link_markers: list = field(default_factory=list)   # ["左下","右",...]
    archetype: str = ""
    setcode: str = "0x0"
    # 文本
    flavor: str = ""
    flavor_i18n: dict = field(default_factory=dict)
    text_i18n: dict = field(default_factory=dict)      # 生成/编辑后的卡文，按语言
    #: 灵摆卡的「灵摆效果」文本（与怪兽效果是**两个独立文本框**，官方版式如此）
    pendulum_text_i18n: dict = field(default_factory=dict)
    effects: list = field(default_factory=list)        # list[EffectSpec]
    #: 归属灵摆效果框的效果（索引），其余进怪兽效果框
    pendulum_effect_indices: list = field(default_factory=list)
    # 渲染与产物
    render: RenderOptions = field(default_factory=RenderOptions)
    lua: str = ""
    strings: list = field(default_factory=list)        # cdb texts.str1..str16
    # 溯源
    created: str = ""
    updated: str = ""
    source_note: str = ""
    dirty: list = field(default_factory=list)          # 需要重算的产物名

    # ── 派生属性（不落盘） ──────────────────────────────────────────
    @property
    def frame_def(self):
        return FRAMES.get(self.frame) or FRAMES["effect"]

    @property
    def is_monster(self) -> bool:
        return self.frame_def.is_monster

    @property
    def is_pendulum(self) -> bool:
        return "pendulum" in self.frame or self.frame_def.base in ("normal", "ritual", "fusion", "synchro", "xyz") and "pendulum" in self.frame

    @property
    def is_extra(self) -> bool:
        return self.frame_def.extra_deck

    @property
    def art_ratio(self) -> float:
        return self.frame_def.art_ratio

    @property
    def race_bits(self) -> int:
        return C.RACE_MAP.get(self.race, 0)

    @property
    def attr_bits(self) -> int:
        return C.ATTRIBUTE_MAP.get(self.attribute, 0)

    @property
    def link_bits(self) -> int:
        return C.link_markers_bits(self.link_markers)

    @property
    def type_bits(self) -> int:
        """按 frame/spell_kind/trap_kind/tags 组合出引擎 type 位。"""
        f = self.frame_def
        bits = 0
        if f.is_monster:
            bits |= C.TYPE_MONSTER
            base = f.base
            # 衍生物不是效果怪兽：官方 token 的 type 是 MONSTER|TOKEN（0x4001），
            # 不带 NORMAL/EFFECT 位。之前一律给 EFFECT，会多出 0x20。
            if self.frame == "token":
                pass
            elif base == "normal":
                bits |= C.TYPE_NORMAL
            else:
                bits |= C.TYPE_EFFECT
            if base == "ritual":
                bits |= C.TYPE_RITUAL
            elif base == "fusion":
                bits |= C.TYPE_FUSION
            elif base == "synchro":
                bits |= C.TYPE_SYNCHRO
            elif base == "xyz":
                bits |= C.TYPE_XYZ
            elif base == "link":
                bits |= C.TYPE_LINK
            if "pendulum" in self.frame:
                bits |= C.TYPE_PENDULUM
            if self.frame == "token":
                bits |= C.TYPE_TOKEN
            for t in self.tags:
                bits |= int(MONSTER_TAGS.get(t, {}).get("bit", 0))
        else:
            bits |= C.TYPE_SPELL if self.frame == "spell" else C.TYPE_TRAP
            kinds = SPELL_KINDS if self.frame == "spell" else TRAP_KINDS
            k = self.spell_kind if self.frame == "spell" else self.trap_kind
            bits |= int(kinds.get(k, {}).get("bit", 0))
        return bits

    @property
    def def_value(self) -> Any:
        """引擎 def 字段：连接怪兽存箭头掩码，其余存守备力。"""
        if self.frame == "link":
            return self.link_bits
        return self.dfd

    @property
    def effective_level(self) -> int:
        if self.frame == "link":
            return C.link_rating_from_bits(self.link_bits) or int(self.level or 0)
        return int(self.level or 0)

    @property
    def display_name(self) -> str:
        """默认展示名（当前卡名语言，回落主卡名）。"""
        lang = self.render.lang_name if self.render else DEFAULT_LANG
        return self.name_i18n.get(lang) or self.name

    def name_in(self, lang: str) -> str:
        return self.name_i18n.get(lang) or self.name

    def text_in(self, lang: str) -> str:
        if self.text_i18n.get(lang):
            return self.text_i18n[lang]
        if not self.is_monster and self.flavor and lang == DEFAULT_LANG:
            return self.flavor
        return self.text_i18n.get(DEFAULT_LANG, "") or ""

    def pendulum_text_in(self, lang: str) -> str:
        """灵摆效果框的文本（灵摆卡专用）。"""
        if self.pendulum_text_i18n.get(lang):
            return self.pendulum_text_i18n[lang]
        return self.pendulum_text_i18n.get(DEFAULT_LANG, "") or ""

    def flavor_in(self, lang: str) -> str:
        return self.flavor_i18n.get(lang) or self.flavor

    def effect_specs(self) -> list:
        out = []
        for i, e in enumerate(self.effects or []):
            if isinstance(e, EffectSpec):
                e.params.setdefault("_index", i)
                out.append(e)
            elif isinstance(e, dict):
                es = EffectSpec.from_dict(e)
                es.params.setdefault("_index", i)
                out.append(es)
        return out

    # ── 序列化 ────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        d = self.to_json_dict()
        d["effects"] = [e.to_dict() if isinstance(e, EffectSpec) else dict(e)
                        for e in (self.effects or [])]
        d["render"] = self.render.to_dict()
        for k in ("race_bits", "attr_bits", "type_bits", "link_bits", "def_value"):
            d[k] = getattr(self, k)   # 冗余写入，方便外部工具直读
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "CardSpec":
        d = dict(d or {})
        d.pop("schema_version", None)
        render = d.pop("render", None)
        effects = d.pop("effects", None)
        # 兼容旧版（v0.x）字段名
        if "def" in d and "dfd" not in d:
            d["dfd"] = d.pop("def")
        if "type_flags" in d and "tags" not in d:
            d["tags"] = d.pop("type_flags") or []
        if "text" in d and "text_i18n" not in d:
            t = d.pop("text")
            d["text_i18n"] = {DEFAULT_LANG: t} if isinstance(t, str) and t else {}
        if "_lua" in d and "lua" not in d:
            d["lua"] = d.pop("_lua") or ""
        if "_strings" in d and "strings" not in d:
            d["strings"] = d.pop("_strings") or []
        for junk in ("race_bits", "attr_bits", "type_bits", "link_bits", "def_value",
                     "effect_tier", "detected_effects"):
            d.pop(junk, None)
        allowed = set(cls.__dataclass_fields__)
        obj = cls(**{k: v for k, v in d.items() if k in allowed})
        if render:
            obj.render = RenderOptions.from_dict(render)
        obj.effects = [EffectSpec.from_dict(e) if isinstance(e, dict) else e
                       for e in (effects or [])]
        return obj

    # ── 便捷 ──────────────────────────────────────────────────────
    def labels(self) -> dict:
        """给 UI 用的展示标签包。"""
        f = self.frame_def
        return {
            "frame": f.zh_cn, "frame_ja": f.ja, "frame_en": f.en,
            "attribute": self.attribute, "race": self.race,
            "rarity": (RARITIES.get(self.render.rarity).zh_cn
                       if self.render.rarity in RARITIES else self.render.rarity),
            "lang": LANGS.get(self.render.lang_text, LANGS[DEFAULT_LANG]).zh_cn,
        }

    def summary(self) -> dict:
        """列表视图用的精简结构。"""
        return {
            "id": self.id, "name": self.display_name, "frame": self.frame,
            "frame_label": self.frame_def.zh_cn, "attribute": self.attribute,
            "race": self.race, "level": self.effective_level,
            "atk": self.atk, "def": self.def_value if self.frame != "link" else None,
            "archetype": self.archetype, "rarity": self.render.rarity,
            "n_effects": len(self.effects or []),
        }


# ══════════════════════════════════════════════════════════════════════
#  系列圣经
# ══════════════════════════════════════════════════════════════════════
@dataclass
class RosterSlot:
    """卡表蓝图里的一个角色槽位。"""
    role: str = "starter"        # starter/extender/trump/support/recovery
    count: int = 3
    brief: str = ""              # 需求摘要
    frame_hint: str = ""         # 期望卡种
    done: list = field(default_factory=list)   # 已完成的卡 id

    def to_dict(self) -> dict:
        return _clean(asdict(self))

    @classmethod
    def from_dict(cls, d):
        return _Base.from_dict.__func__(cls, d or {})  # type: ignore[attr-defined]


#: 卡表角色（自定义分类，避免声称引用某个不存在的"标准五类模型"）
ROLES = {
    "starter": {"zh_cn": "初动点", "en": "Starter", "range": (2, 3),
                "brief": "零前置条件即可启动，检索或特召本家"},
    "extender": {"zh_cn": "展开点", "en": "Extender", "range": (2, 3),
                 "brief": "被干扰后仍能继续接，墓地/手卡特召"},
    "trump": {"zh_cn": "王牌终端", "en": "Boss", "range": (2, 3),
              "brief": "终端，具备压制或斩杀能力"},
    "support": {"zh_cn": "支援", "en": "Support", "range": (3, 5),
                "brief": "本家魔法/陷阱，检索与干扰"},
    "recovery": {"zh_cn": "回收", "en": "Recovery", "range": (1, 2),
                 "brief": "从墓地/除外区回手，闭合资源循环"},
    "handtrap": {"zh_cn": "手坑", "en": "Hand Trap", "range": (0, 3),
                 "brief": "对手回合的干扰点"},
}


@dataclass
class Archetype(_Base):
    """系列圣经：三锚点 + 方言句式 + 卡表蓝图。"""
    SCHEMA_VERSION = SCHEMA_VERSION

    name: str = ""
    name_i18n: dict = field(default_factory=dict)   # 官方译名对照（用于多语言卡文里的字段引用）
    setcode: str = "0x0"
    concept: str = ""                    # 一句话概念
    win_method: str = "BATTLE"           # BATTLE/EFFECT/BURN/MIX
    trumps: list = field(default_factory=list)   # 王牌形态：FUSION/SYNCHRO/XYZ/LINK/RITUAL/MAIN
    binding: dict = field(default_factory=dict)  # {"attribute": "炎", "race": "战士族"}
    dialects: list = field(default_factory=list)  # 方言句式（硬约束 ≤5 条）
    roster: list = field(default_factory=list)    # list[RosterSlot]
    target_power: str = "casual"         # casual/rogue/competitive
    notes: str = ""
    created: str = ""
    updated: str = ""

    def roster_total(self) -> int:
        return sum(int(s.count or 0) for s in (self.roster or []))

    def to_dict(self) -> dict:
        d = self.to_json_dict()
        d["roster"] = [s.to_dict() if isinstance(s, RosterSlot) else dict(s)
                       for s in (self.roster or [])]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Archetype":
        d = dict(d or {})
        d.pop("schema_version", None)
        roster = d.pop("roster", None)
        allowed = set(cls.__dataclass_fields__)
        obj = cls(**{k: v for k, v in d.items() if k in allowed})
        obj.roster = [RosterSlot.from_dict(s) if isinstance(s, dict) else s
                      for s in (roster or [])]
        return obj


# ══════════════════════════════════════════════════════════════════════
#  卡组
# ══════════════════════════════════════════════════════════════════════
@dataclass
class DeckEntry:
    card_id: int = 0
    count: int = 1
    role: str = ""        # ROLES 的键
    name: str = ""        # 冗余，便于人读

    def to_dict(self) -> dict:
        return _clean(asdict(self))


@dataclass
class DeckSpec(_Base):
    SCHEMA_VERSION = SCHEMA_VERSION
    name: str = ""
    main: list = field(default_factory=list)     # list[DeckEntry]
    extra: list = field(default_factory=list)
    side: list = field(default_factory=list)
    archetype: str = ""
    target: str = "casual"
    notes: str = ""

    def to_dict(self) -> dict:
        d = self.to_json_dict()
        for k in ("main", "extra", "side"):
            d[k] = [e.to_dict() if isinstance(e, DeckEntry) else dict(e)
                    for e in (getattr(self, k) or [])]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "DeckSpec":
        d = dict(d or {})
        d.pop("schema_version", None)
        parts = {k: d.pop(k, None) for k in ("main", "extra", "side")}
        allowed = set(cls.__dataclass_fields__)
        obj = cls(**{k: v for k, v in d.items() if k in allowed})
        for k, v in parts.items():
            setattr(obj, k, [DeckEntry(**e) if isinstance(e, dict) else e for e in (v or [])])
        return obj


# ══════════════════════════════════════════════════════════════════════
#  审计与出图
# ══════════════════════════════════════════════════════════════════════
@dataclass
class Issue:
    """质量门产出的一条问题。"""
    gate: str = "G1"                 # G1..G5
    code: str = ""                   # 稳定规则号，如 "ATK_L4_OVER"
    level: str = "WARN"              # ERROR/WARN/INFO
    message: str = ""                # 中文说明（给用户）
    hint: str = ""                   # 可执行建议
    field: str = ""                  # 相关字段路径，如 "atk"
    waived: bool = False             # 是否被强制放行
    waiver_reason: str = ""

    def to_dict(self) -> dict:
        return _clean(asdict(self))


@dataclass
class GateReport:
    gate: str = "G1"
    status: str = "pending"          # pass/warn/fail/waived/pending/skipped
    issues: list = field(default_factory=list)
    summary: str = ""
    took_ms: int = 0
    degraded: str = ""               # 降级原因（如"未检测到引擎，仅静态校验"）

    def to_dict(self) -> dict:
        return {"gate": self.gate, "status": self.status,
                "summary": self.summary, "took_ms": self.took_ms,
                "degraded": self.degraded,
                "issues": [i.to_dict() if isinstance(i, Issue) else dict(i)
                           for i in (self.issues or [])]}

    @property
    def has_error(self) -> bool:
        return any((i.level if isinstance(i, Issue) else i.get("level")) == "ERROR"
                   and not (i.waived if isinstance(i, Issue) else i.get("waived"))
                   for i in (self.issues or []))


@dataclass
class ArtRequest:
    """一次卡图生成请求。"""
    card_id: int = 0
    archetype: str = ""
    subject: str = ""                 # 主体描述（中文即可）
    #: 分层出图时的背景描述（主体 pass 之外单独生成背景）
    background: str = ""
    style: str = ""                   # 风格描述（中文即可）
    extra_positive: str = ""
    extra_negative: str = ""
    preset: str = "t2i_single"        # art/presets.py 的键
    profile: str = "auto"             # 模型档案键，auto=自动选择
    loras: list = field(default_factory=list)     # ["krea2_flat_cel_anime.safetensors:0.8"]
    style_refs: list = field(default_factory=list)  # 风格参考图路径
    width: int = 0                    # 0=按档案与卡种自动
    height: int = 0
    seed: int = -1                    # -1=随机
    count: int = 1
    steps: int = 0                    # 0=按档案默认
    cfg: float = 0.0
    sampler: str = ""
    scheduler: str = ""
    upscale: bool = False
    remove_bg: bool = False
    #: 分层出图：背景与主体**分两次生成**，主体自动抠底，之后按出框需要叠加
    layers: bool = False
    #: 主体 pass 的纯色底（抠底用）。留空 = 按主体明暗自动选中性灰
    cutout_bg: str = ""
    #: 抠底 mask 极性。``True``=反相（默认，适配「暗主体亮底」）；
    #: 亮色主体（白龙/光属性）实测会被抠空，分层出图会自动探测并翻转重试。
    cutout_invert: bool = True
    series_context: dict = field(default_factory=dict)  # 系列一致性上下文

    def to_dict(self) -> dict:
        return _clean(asdict(self))


@dataclass
class ArtResult:
    ok: bool = False
    images: list = field(default_factory=list)   # 绝对路径
    meta: dict = field(default_factory=dict)     # 提示词/模型/seed/耗时
    workflow: dict = field(default_factory=dict) # 实际提交的 API 图
    error: str = ""
    hint: str = ""
    took_ms: int = 0

    def to_dict(self) -> dict:
        return _clean(asdict(self))


# ══════════════════════════════════════════════════════════════════════
#  辅助
# ══════════════════════════════════════════════════════════════════════
def iter_effect_dicts(spec: CardSpec) -> Iterable[dict]:
    for e in spec.effect_specs():
        yield e.to_dict()


__all__ = [
    "SCHEMA_VERSION", "CardSpec", "EffectSpec", "EffectTarget", "EffectCost",
    "RenderOptions", "FullArtOptions", "Archetype", "RosterSlot", "DeckSpec",
    "DeckEntry", "Issue", "GateReport", "ArtRequest", "ArtResult",
    "TRIGGERS", "EFFECT_LIMITS", "ROLES",
]
