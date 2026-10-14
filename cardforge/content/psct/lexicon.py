"""多语言术语与 PSCT 句式词库 —— ``data/lexicons/*.json`` 的唯一访问入口。

设计要点
--------
1. **绝不返回 None。** :func:`term` 的回落链是
   ``请求语言 → en → zh_cn → 返回 key 本身``；引擎在任何数据缺失下都能跑。
2. **数据文件缺失也能工作。** 本模块内联了一份兜底表（覆盖 208 条术语与全部
   PSCT 句式，来自 ``data/lexicons/*.json`` 的快照），文件存在时以文件为准。
3. **缺口要诚实留痕。** 韩文（ko）有 44 条 ``null``（集中在 ``action`` /
   ``psct_phrase``），西文语言也有零星缺口；用 :func:`term_or_fallback`
   能拿到"实际用了哪种语言"，生成器据此标注降级而不是硬造。
4. **加载是惰性的**，导入本模块没有副作用；:func:`reload` 可强制重读
   （测试与"改完词表立刻生效"用）。

数据来源与可信度见 ``data/lexicons/README.md``：
``official`` 147 条 / ``community`` 64 条 / ``unverified`` 2 条
（``card_non_effect_monster``、``stat_ritual_material`` —— 这两条**不可**
直接用于成品卡面）。
"""
from __future__ import annotations

import copy
import json
import threading
from typing import Any, Iterable, Optional

from ...core import paths
from ...core.enums import LANGS
from . import rules

__all__ = [
    "terms", "term", "term_or_fallback", "by_category", "patterns",
    "punctuation", "conjunction", "hopt", "hopt_single", "reload",
    "coverage_report",
    "localize", "race_term", "attribute_term", "zone_term", "stat_term",
    "card_type_term", "quote", "has_native", "lang_coverage",
    "generation_lang", "degraded_reason", "sources", "available",
    "confidence_of", "TERM_LANGS",
]

#: terms.json 里的语言列（与 core.enums.LANGS 对齐）
TERM_LANGS: tuple[str, ...] = ("en", "zh_cn", "zh_tw", "ja", "ko",
                               "de", "fr", "it", "pt", "es")

_STATE: dict[str, Any] = {"terms": None, "patterns": None, "source": {}}
_LOCK = threading.RLock()

TERMS_FILE = "terms.json"
PATTERNS_FILE = "psct_patterns.json"


# ══════════════════════════════════════════════════════════════════════
#  ⚠️ 内置兜底表（data/lexicons/ 缺失时使用）
#  内容与 data/lexicons/terms.json 的同名键逐字一致，由
#  `_probe/psct/_gen_fallback.py` 生成，勿手改。
# ══════════════════════════════════════════════════════════════════════
# @@FALLBACK_TERMS@@ 由 _probe/psct/_gen_fallback.py 生成（数据源 data/lexicons/terms.json）
# @@FALLBACK_TERMS@@ 由 _probe/psct/_gen_fallback.py 生成（数据源 data/lexicons/terms.json）
# @@FALLBACK_TERMS@@ 由 _probe/psct/_gen_fallback.py 生成（数据源 data/lexicons/terms.json）
_FALLBACK_TERMS: dict[str, dict[str, str]] = {
    "act_add_to_hand": {"zh_cn": "加入手卡", "ja": "手札に加える", "en": "add to hand", "category": "action"},
    "act_attach": {"zh_cn": "重叠", "ja": "重ねる", "en": "attach", "category": "action"},
    "act_attack": {"zh_cn": "攻击", "ja": "攻撃", "en": "attack", "category": "action"},
    "act_banish": {"zh_cn": "除外", "ja": "除外", "en": "banish", "category": "action"},
    "act_change_battle_position": {"zh_cn": "变更表示形式", "ja": "表示形式を変更する", "en": "change its battle position", "category": "action"},
    "act_confirm": {"zh_cn": "确认", "ja": "確認する", "en": "confirm / look at", "category": "action"},
    "act_control": {"zh_cn": "控制", "ja": "コントロール", "en": "control", "category": "action"},
    "act_copy": {"zh_cn": "复制", "ja": "コピーする", "en": "copy (a card name / effect)", "category": "action"},
    "act_declare": {"zh_cn": "宣言", "ja": "宣言", "en": "declare", "category": "action"},
    "act_destroy": {"zh_cn": "破坏", "ja": "破壊", "en": "destroy", "category": "action"},
    "act_destroyed_by_battle": {"zh_cn": "被战斗破坏", "ja": "戦闘で破壊される", "en": "destroyed by battle", "category": "action"},
    "act_detach": {"zh_cn": "去除", "ja": "取り除く", "en": "detach", "category": "action"},
    "act_direct_attack": {"zh_cn": "直接攻击", "ja": "直接攻撃", "en": "attack directly", "category": "action"},
    "act_discard": {"zh_cn": "舍弃", "ja": "捨てる", "en": "discard", "category": "action"},
    "act_draw": {"zh_cn": "抽牌", "ja": "ドロー", "en": "draw", "category": "action"},
    "act_flip_face_down": {"zh_cn": "变成里侧表示", "ja": "裏側表示にする", "en": "change to face-down (Set)", "category": "action"},
    "act_flip_face_up": {"zh_cn": "变成表侧表示", "ja": "表側表示にする", "en": "flip face-up", "category": "action"},
    "act_flip_summon": {"zh_cn": "反转召唤", "ja": "反転召喚", "en": "Flip Summon", "category": "action"},
    "act_fusion_summon": {"zh_cn": "融合召唤", "ja": "融合召喚", "en": "Fusion Summon", "category": "action"},
    "act_gain": {"zh_cn": "上升", "ja": "アップする", "en": "gain (ATK/DEF)", "category": "action"},
    "act_link_summon": {"zh_cn": "连接召唤", "ja": "Ｌ召喚", "en": "Link Summon", "category": "action"},
    "act_lose": {"zh_cn": "下降", "ja": "ダウンする", "en": "lose (ATK/DEF)", "category": "action"},
    "act_negate": {"zh_cn": "无效", "ja": "無効", "en": "negate", "category": "action"},
    "act_negate_activation": {"zh_cn": "发动无效", "ja": "発動を無効", "en": "negate the activation", "category": "action"},
    "act_negate_effect": {"zh_cn": "效果无效化", "ja": "効果を無効にする", "en": "negate the effect / its effects are negated", "category": "action"},
    "act_normal_summon": {"zh_cn": "通常召唤", "ja": "通常召喚", "en": "Normal Summon", "category": "action"},
    "act_pay_lp": {"zh_cn": "支付LP", "ja": "ＬＰを払う", "en": "pay Life Points", "category": "action"},
    "act_pendulum_summon": {"zh_cn": "灵摆召唤", "ja": "Ｐ召喚", "en": "Pendulum Summon", "category": "action"},
    "act_piercing": {"zh_cn": "给予穿刺战斗伤害", "ja": "貫通ダメージを与える", "en": "inflict piercing battle damage", "category": "action"},
    "act_place_counter": {"zh_cn": "放置计数物", "ja": "カウンターを置く", "en": "place a Counter", "category": "action"},
    "act_replace": {"zh_cn": "代替", "ja": "代わりに", "en": "instead / replace", "category": "action"},
    "act_return": {"zh_cn": "回到", "ja": "戻す", "en": "return (to the hand / Deck)", "category": "action"},
    "act_reveal": {"zh_cn": "公开", "ja": "公開する", "en": "reveal", "category": "action"},
    "act_ritual_summon": {"zh_cn": "仪式召唤", "ja": "儀式召喚", "en": "Ritual Summon", "category": "action"},
    "act_search": {"zh_cn": "从卡组把…加入手卡", "ja": "デッキから…手札に加える", "en": "add ... from your Deck to your hand", "category": "action"},
    "act_send": {"zh_cn": "送去墓地", "ja": "墓地へ送る", "en": "send (to the Graveyard)", "category": "action"},
    "act_set": {"zh_cn": "放置", "ja": "セット", "en": "Set", "category": "action"},
    "act_shuffle": {"zh_cn": "洗牌", "ja": "シャッフル", "en": "shuffle", "category": "action"},
    "act_special_summon": {"zh_cn": "特殊召唤", "ja": "特殊召喚", "en": "Special Summon", "category": "action"},
    "act_synchro_summon": {"zh_cn": "同步召唤", "ja": "Ｓ召喚", "en": "Synchro Summon", "category": "action"},
    "act_take_control": {"zh_cn": "获得控制权", "ja": "コントロールを得る", "en": "take control of", "category": "action"},
    "act_target": {"zh_cn": "以…为对象", "ja": "…を対象とする", "en": "target", "category": "action"},
    "act_tribute": {"zh_cn": "解放", "ja": "リリース", "en": "Tribute", "category": "action"},
    "act_tribute_summon": {"zh_cn": "上级召唤", "ja": "Ａ召喚", "en": "Tribute Summon", "category": "action"},
    "act_xyz_summon": {"zh_cn": "超量召唤", "ja": "Ｘ召喚", "en": "Xyz Summon", "category": "action"},
    "attr_dark": {"zh_cn": "暗属性", "ja": "闇", "en": "DARK", "category": "attribute"},
    "attr_divine": {"zh_cn": "神属性", "ja": "神", "en": "DIVINE", "category": "attribute"},
    "attr_earth": {"zh_cn": "地属性", "ja": "地", "en": "EARTH", "category": "attribute"},
    "attr_fire": {"zh_cn": "炎属性", "ja": "炎", "en": "FIRE", "category": "attribute"},
    "attr_light": {"zh_cn": "光属性", "ja": "光", "en": "LIGHT", "category": "attribute"},
    "attr_water": {"zh_cn": "水属性", "ja": "水", "en": "WATER", "category": "attribute"},
    "attr_wind": {"zh_cn": "风属性", "ja": "風", "en": "WIND", "category": "attribute"},
    "card_continuous_spell": {"zh_cn": "永续魔法卡", "ja": "永続魔法カード", "en": "Continuous Spell", "category": "card_type"},
    "card_continuous_trap": {"zh_cn": "永续陷阱卡", "ja": "永続罠カード", "en": "Continuous Trap", "category": "card_type"},
    "card_counter_trap": {"zh_cn": "反击陷阱卡", "ja": "カウンター罠カード", "en": "Counter Trap", "category": "card_type"},
    "card_effect": {"zh_cn": "效果", "ja": "効果", "en": "effect", "category": "card_type"},
    "card_effect_monster": {"zh_cn": "效果怪兽", "ja": "効果モンスター", "en": "Effect Monster", "category": "card_type"},
    "card_equip_spell": {"zh_cn": "装备魔法卡", "ja": "装備魔法カード", "en": "Equip Spell", "category": "card_type"},
    "card_field_spell": {"zh_cn": "场地魔法卡", "ja": "フィールド魔法カード", "en": "Field Spell", "category": "card_type"},
    "card_flip": {"zh_cn": "反转怪兽", "ja": "リバースモンスター", "en": "Flip monster", "category": "card_type"},
    "card_fusion_monster": {"zh_cn": "融合怪兽", "ja": "融合モンスター", "en": "Fusion Monster", "category": "card_type"},
    "card_gemini": {"zh_cn": "二重怪兽", "ja": "デュアルモンスター", "en": "Gemini monster", "category": "card_type"},
    "card_link_monster": {"zh_cn": "连接怪兽", "ja": "Ｌモンスター", "en": "Link Monster", "category": "card_type"},
    "card_monster": {"zh_cn": "怪兽卡", "ja": "モンスターカード", "en": "Monster Card", "category": "card_type"},
    "card_normal_monster": {"zh_cn": "通常怪兽", "ja": "通常モンスター", "en": "Normal Monster", "category": "card_type"},
    "card_normal_spell": {"zh_cn": "通常魔法卡", "ja": "通常魔法カード", "en": "Normal Spell", "category": "card_type"},
    "card_normal_trap": {"zh_cn": "通常陷阱卡", "ja": "通常罠カード", "en": "Normal Trap", "category": "card_type"},
    "card_pendulum_monster": {"zh_cn": "灵摆怪兽", "ja": "Ｐモンスター", "en": "Pendulum Monster", "category": "card_type"},
    "card_quick_play_spell": {"zh_cn": "速攻魔法卡", "ja": "速攻魔法カード", "en": "Quick-Play Spell", "category": "card_type"},
    "card_ritual_monster": {"zh_cn": "仪式怪兽", "ja": "儀式モンスター", "en": "Ritual Monster", "category": "card_type"},
    "card_ritual_spell": {"zh_cn": "仪式魔法卡", "ja": "儀式魔法カード", "en": "Ritual Spell", "category": "card_type"},
    "card_special_summon_monster": {"zh_cn": "特殊召唤怪兽", "ja": "特殊召喚モンスター", "en": "Special Summon Monster", "category": "card_type"},
    "card_spell": {"zh_cn": "魔法卡", "ja": "魔法カード", "en": "Spell Card", "category": "card_type"},
    "card_spirit": {"zh_cn": "灵魂怪兽", "ja": "スピリットモンスター", "en": "Spirit monster", "category": "card_type"},
    "card_synchro_monster": {"zh_cn": "同步怪兽", "ja": "Ｓモンスター", "en": "Synchro Monster", "category": "card_type"},
    "card_token": {"zh_cn": "衍生物", "ja": "モンスタートークン", "en": "Monster Token", "category": "card_type"},
    "card_toon": {"zh_cn": "卡通怪兽", "ja": "トゥーンモンスター", "en": "Toon monster", "category": "card_type"},
    "card_trap": {"zh_cn": "陷阱卡", "ja": "罠カード", "en": "Trap Card", "category": "card_type"},
    "card_tuner": {"zh_cn": "协调怪兽", "ja": "チューナー", "en": "Tuner monster", "category": "card_type"},
    "card_union": {"zh_cn": "联合怪兽", "ja": "ユニオンモンスター", "en": "Union monster", "category": "card_type"},
    "card_xyz_monster": {"zh_cn": "超量怪兽", "ja": "Ｘモンスター", "en": "Xyz Monster", "category": "card_type"},
    "psct_activate_only": {"zh_cn": "1回合只能发动1次", "ja": "１ターンに１度しか発動できない", "en": "You can only activate ... once per turn.", "category": "psct_phrase"},
    "psct_activation_condition": {"zh_cn": "发动条件", "ja": "発動条件", "en": "activation condition / activation requirement", "category": "psct_phrase"},
    "psct_also": {"zh_cn": "此外", "ja": "また", "en": "also", "category": "psct_phrase"},
    "psct_also_after_that": {"zh_cn": "此外，那之后", "ja": "また、その後", "en": "also, after that", "category": "psct_phrase"},
    "psct_always_treated_as": {"zh_cn": "（这张卡也当作「X」卡使用。）", "ja": "（このカードは「X」カードとしても扱う。）", "en": "(This card is always treated as a \"X\" card.)", "category": "psct_phrase"},
    "psct_and": {"zh_cn": "并且", "ja": "し", "en": "and", "category": "psct_phrase"},
    "psct_and_if_you_do": {"zh_cn": "那个场合", "ja": "その場合", "en": "and if you do", "category": "psct_phrase"},
    "psct_banish": {"zh_cn": "把…除外", "ja": "…を除外する。", "en": "Banish ...", "category": "psct_phrase"},
    "psct_cannot_activate": {"zh_cn": "不能发动", "ja": "発動できない", "en": "Cannot be activated.", "category": "psct_phrase"},
    "psct_cannot_be_normal_summoned": {"zh_cn": "这张卡不能通常召唤。", "ja": "このカードは通常召喚できない。", "en": "Cannot be Normal Summoned/Set.", "category": "psct_phrase"},
    "psct_cannot_be_used_as_material": {"zh_cn": "不能作为…召唤的素材。", "ja": "…召喚の素材にできない。", "en": "Cannot be used as material for a ... Summon.", "category": "psct_phrase"},
    "psct_chain_link": {"zh_cn": "连锁", "ja": "チェーン", "en": "Chain Link", "category": "psct_phrase"},
    "psct_condition": {"zh_cn": "条件", "ja": "条件", "en": "condition", "category": "psct_phrase"},
    "psct_cost": {"zh_cn": "费用", "ja": "コスト", "en": "cost", "category": "psct_phrase"},
    "psct_destroy": {"zh_cn": "破坏…", "ja": "…を破壊する。", "en": "Destroy ...", "category": "psct_phrase"},
    "psct_discard_cost": {"zh_cn": "把…舍弃才能发动。…", "ja": "…を捨てて発動できる。…", "en": "Discard ...; ...", "category": "psct_phrase"},
    "psct_during_either_players": {"zh_cn": "在对方回合也能发动", "ja": "相手ターンでも発動できる", "en": "During either player's turn", "category": "psct_phrase"},
    "psct_each_of_these_effects": {"zh_cn": "选择1个效果适用。", "ja": "以下の効果から１つを適用する。", "en": "Apply 1 of these effects.", "category": "psct_phrase"},
    "psct_hopt_gain_once": {"zh_cn": "（这个效果1回合只能获得1次。）", "ja": "（この効果は１ターンに１度しか得られない。）", "en": "(You can only gain this effect once per turn.)", "category": "psct_phrase"},
    "psct_hopt_name_activate": {"zh_cn": "「X」1回合只能发动1张。", "ja": "「X」は１ターンに１枚しか発動できない。", "en": "You can only activate 1 \"X\" per turn.", "category": "psct_phrase"},
    "psct_hopt_name_apply": {"zh_cn": "这个卡名的效果1场决斗中只能适用1次。", "ja": "このカード名の効果はデュエル中に１度しか適用できない。", "en": "You can only apply this effect of \"X\" once per Duel.", "category": "psct_phrase"},
    "psct_hopt_name_each": {"zh_cn": "这个卡名的①②的效果1回合各能使用1次。", "ja": "このカード名の①②の効果はそれぞれ１ターンに１度しか使用できない。", "en": "You can only use each effect of \"X\" once per turn.", "category": "psct_phrase"},
    "psct_hopt_name_this": {"zh_cn": "这个卡名的①的效果1回合只能使用1次。", "ja": "このカード名の①の効果は１ターンに１度しか使用できない。", "en": "You can only use this effect of \"X\" once per turn.", "category": "psct_phrase"},
    "psct_if_mandatory": {"zh_cn": "…的场合，…。", "ja": "…場合、…。", "en": "If ..., ... (mandatory)", "category": "psct_phrase"},
    "psct_if_only_your_opponent_controls": {"zh_cn": "对方场上只有怪兽存在的场合", "ja": "相手フィールドにのみモンスターが存在する場合", "en": "If only your opponent controls a monster", "category": "psct_phrase"},
    "psct_if_you_can": {"zh_cn": "…的场合才能发动。", "ja": "…場合、…できる。", "en": "If ...: You can ...", "category": "psct_phrase"},
    "psct_if_you_do_not_control": {"zh_cn": "自己场上没有…的场合", "ja": "自分フィールドに…が存在しない場合", "en": "If you do not control ...", "category": "psct_phrase"},
    "psct_immediately_after_resolves": {"zh_cn": "这个效果处理后再…", "ja": "この効果の処理後に…", "en": "Immediately after this effect resolves, ...", "category": "psct_phrase"},
    "psct_in_sequence": {"zh_cn": "（按顺序）", "ja": "（順番に）", "en": "(in sequence)", "category": "psct_phrase"},
    "psct_it_ref": {"zh_cn": "那张卡", "ja": "それ", "en": "it / they", "category": "psct_phrase"},
    "psct_its_effects_are_negated": {"zh_cn": "那个效果无效化", "ja": "その効果は無効化される", "en": "its effects are negated", "category": "psct_phrase"},
    "psct_loses_the_timing": {"zh_cn": "错过时机", "ja": "タイミングを逃す", "en": "loses the timing / misses the timing", "category": "psct_phrase"},
    "psct_must_first_be_special_summoned": {"zh_cn": "这张卡不能通常召唤，…才能特殊召唤。", "ja": "このカードは通常召喚できず、…ことで特殊召喚できる。", "en": "Must first be Special Summoned (from your hand) by ...", "category": "psct_phrase"},
    "psct_negate_activation": {"zh_cn": "那个发动无效并破坏", "ja": "その発動を無効にし破壊する。", "en": "negate the activation, and if you do, destroy it", "category": "psct_phrase"},
    "psct_neither_player_can_activate": {"zh_cn": "这个效果的发动，双方不能发动卡的效果。", "ja": "この効果の発動に対して、お互いはカードの効果を発動できない。", "en": "Neither player can activate cards or effects in response to this effect's activation.", "category": "psct_phrase"},
    "psct_once_per_duel": {"zh_cn": "1场决斗1次", "ja": "１デュエルに１度", "en": "once per Duel", "category": "psct_phrase"},
    "psct_once_per_turn": {"zh_cn": "1回合1次", "ja": "１ターンに１度", "en": "once per turn", "category": "psct_phrase"},
    "psct_once_per_turn_colon": {"zh_cn": "1回合1次，", "ja": "１ターンに１度、", "en": "Once per turn:", "category": "psct_phrase"},
    "psct_pay_lp_cost": {"zh_cn": "支付…LP才能发动。…", "ja": "…ＬＰを払って発動できる。…", "en": "Pay ... LP; ...", "category": "psct_phrase"},
    "psct_quick_effect": {"zh_cn": "（这个效果在对方回合也能发动）", "ja": "（この効果は相手ターンでも発動できる）", "en": "(Quick Effect)", "category": "psct_phrase"},
    "psct_return_to_deck": {"zh_cn": "…回到卡组。", "ja": "…をデッキに戻す。", "en": "Return ... to the Deck.", "category": "psct_phrase"},
    "psct_return_to_hand": {"zh_cn": "…回到手卡。", "ja": "…を手札に戻す。", "en": "Return ... to the hand.", "category": "psct_phrase"},
    "psct_search_deck": {"zh_cn": "从卡组把1张…加入手卡。", "ja": "デッキから…１枚を手札に加える。", "en": "Add 1 ... from your Deck to your hand.", "category": "psct_phrase"},
    "psct_send_cost": {"zh_cn": "把…送去墓地才能发动。…", "ja": "…を墓地へ送って発動できる。…", "en": "Send ... to the Graveyard; ...", "category": "psct_phrase"},
    "psct_send_to_gy": {"zh_cn": "从卡组把1张…送去墓地。", "ja": "デッキから…１枚を墓地へ送る。", "en": "Send 1 ... from your Deck to the Graveyard.", "category": "psct_phrase"},
    "psct_simultaneously": {"zh_cn": "（同时）", "ja": "（同時に）", "en": "(simultaneously)", "category": "psct_phrase"},
    "psct_special_summon_deck": {"zh_cn": "从卡组把1只…特殊召唤。", "ja": "デッキから…１体を特殊召喚する。", "en": "Special Summon 1 ... from your Deck.", "category": "psct_phrase"},
    "psct_spell_speed": {"zh_cn": "咒文速度", "ja": "スペルスピード", "en": "Spell Speed", "category": "psct_phrase"},
    "psct_summoning_condition": {"zh_cn": "召唤条件", "ja": "召喚条件", "en": "Summoning condition", "category": "psct_phrase"},
    "psct_target_cost": {"zh_cn": "以…为对象才能发动。…", "ja": "…を対象として発動できる。…", "en": "target ...; ...", "category": "psct_phrase"},
    "psct_targeting_ref": {"zh_cn": "那个对象", "ja": "その対象", "en": "that target / those targets", "category": "psct_phrase"},
    "psct_the_previous_effect": {"zh_cn": "以上全部", "ja": "以上全て", "en": "All of the above / the preceding effect", "category": "psct_phrase"},
    "psct_then": {"zh_cn": "那之后", "ja": "その後", "en": "then", "category": "psct_phrase"},
    "psct_this_card_name_becomes": {"zh_cn": "这张卡的卡名当作「X」使用。", "ja": "このカードのカード名は…の間「X」として扱う。", "en": "This card's name becomes \"X\" while ...", "category": "psct_phrase"},
    "psct_this_effect_cannot_be_negated": {"zh_cn": "这个效果的发动和效果不会被无效化。", "ja": "この効果の発動と効果は無効化されない。", "en": "The activation and effect of this effect cannot be negated.", "category": "psct_phrase"},
    "psct_tribute_cost": {"zh_cn": "把…解放才能发动。…", "ja": "…をリリースして発動できる。…", "en": "Tribute ...; ...", "category": "psct_phrase"},
    "psct_until_end_of_turn": {"zh_cn": "（直到回合结束时）", "ja": "（ターン終了時まで）", "en": "(until the end of this turn)", "category": "psct_phrase"},
    "psct_until_end_phase": {"zh_cn": "直到结束阶段", "ja": "エンドフェイズまで", "en": "until the End Phase", "category": "psct_phrase"},
    "psct_when_mandatory": {"zh_cn": "…时，…。", "ja": "…時、…。", "en": "When ..., ... (mandatory)", "category": "psct_phrase"},
    "psct_when_you_can": {"zh_cn": "…时才能发动。", "ja": "…時、…できる。", "en": "When ...: You can ...", "category": "psct_phrase"},
    "psct_while_face_up_on_field": {"zh_cn": "这张卡在怪兽区域表侧表示存在的场合，1次…", "ja": "このカードがモンスターゾーンに表側表示で存在する場合に１度、…", "en": "Once while face-up on the field: ...", "category": "psct_phrase"},
    "psct_you_can_only_use": {"zh_cn": "1回合只能使用1次", "ja": "１ターンに１度しか使用できない", "en": "You can only use ... once per turn.", "category": "psct_phrase"},
    "race_aqua": {"zh_cn": "水族", "ja": "水", "en": "Aqua", "category": "race"},
    "race_beast": {"zh_cn": "兽族", "ja": "獣", "en": "Beast", "category": "race"},
    "race_beast_warrior": {"zh_cn": "兽战士族", "ja": "獣戦士", "en": "Beast-Warrior", "category": "race"},
    "race_creator_god": {"zh_cn": "创造神族", "ja": "創造神", "en": "Creator God", "category": "race"},
    "race_cyberse": {"zh_cn": "电子界族", "ja": "サイバース", "en": "Cyberse", "category": "race"},
    "race_dinosaur": {"zh_cn": "恐龙族", "ja": "恐竜", "en": "Dinosaur", "category": "race"},
    "race_divine_beast": {"zh_cn": "幻神兽族", "ja": "幻神獣", "en": "Divine-Beast", "category": "race"},
    "race_dragon": {"zh_cn": "龙族", "ja": "ドラゴン", "en": "Dragon", "category": "race"},
    "race_fairy": {"zh_cn": "天使族", "ja": "天使", "en": "Fairy", "category": "race"},
    "race_fiend": {"zh_cn": "恶魔族", "ja": "悪魔", "en": "Fiend", "category": "race"},
    "race_fish": {"zh_cn": "鱼族", "ja": "魚", "en": "Fish", "category": "race"},
    "race_illusion": {"zh_cn": "幻想魔族", "ja": "幻想魔", "en": "Illusion", "category": "race"},
    "race_insect": {"zh_cn": "昆虫族", "ja": "昆虫", "en": "Insect", "category": "race"},
    "race_machine": {"zh_cn": "机械族", "ja": "機械", "en": "Machine", "category": "race"},
    "race_plant": {"zh_cn": "植物族", "ja": "植物", "en": "Plant", "category": "race"},
    "race_psychic": {"zh_cn": "念动力族", "ja": "サイキック", "en": "Psychic", "category": "race"},
    "race_pyro": {"zh_cn": "炎族", "ja": "炎", "en": "Pyro", "category": "race"},
    "race_reptile": {"zh_cn": "爬虫类族", "ja": "爬虫類", "en": "Reptile", "category": "race"},
    "race_rock": {"zh_cn": "岩石族", "ja": "岩石", "en": "Rock", "category": "race"},
    "race_sea_serpent": {"zh_cn": "海龙族", "ja": "海竜", "en": "Sea Serpent", "category": "race"},
    "race_spellcaster": {"zh_cn": "魔法师族", "ja": "魔法使い", "en": "Spellcaster", "category": "race"},
    "race_thunder": {"zh_cn": "雷族", "ja": "雷", "en": "Thunder", "category": "race"},
    "race_warrior": {"zh_cn": "战士族", "ja": "戦士", "en": "Warrior", "category": "race"},
    "race_winged_beast": {"zh_cn": "鸟兽族", "ja": "鳥獣", "en": "Winged Beast", "category": "race"},
    "race_wyrm": {"zh_cn": "幻龙族", "ja": "幻竜", "en": "Wyrm", "category": "race"},
    "race_zombie": {"zh_cn": "不死族", "ja": "アンデット", "en": "Zombie", "category": "race"},
    "stat_atk": {"zh_cn": "攻击力", "ja": "攻撃力", "en": "ATK", "category": "stat"},
    "stat_attribute": {"zh_cn": "属性", "ja": "属性", "en": "Attribute", "category": "stat"},
    "stat_battle_damage": {"zh_cn": "战斗伤害", "ja": "戦闘ダメージ", "en": "battle damage", "category": "stat"},
    "stat_def": {"zh_cn": "守备力", "ja": "守備力", "en": "DEF", "category": "stat"},
    "stat_effect_damage": {"zh_cn": "效果伤害", "ja": "効果ダメージ", "en": "effect damage", "category": "stat"},
    "stat_fusion_material": {"zh_cn": "融合素材", "ja": "融合素材", "en": "Fusion Material", "category": "stat"},
    "stat_level": {"zh_cn": "等级", "ja": "レベル", "en": "Level", "category": "stat"},
    "stat_link_arrow": {"zh_cn": "连接标记", "ja": "リンクマーカー", "en": "Link Arrow / Link Marker", "category": "stat"},
    "stat_link_material": {"zh_cn": "连接素材", "ja": "Ｌ素材", "en": "Link Material", "category": "stat"},
    "stat_link_rating": {"zh_cn": "连接数值", "ja": "LINKの数値", "en": "Link Rating", "category": "stat"},
    "stat_lp": {"zh_cn": "LP", "ja": "ＬＰ", "en": "LP (Life Points)", "category": "stat"},
    "stat_pendulum_scale": {"zh_cn": "灵摆刻度", "ja": "Ｐスケール", "en": "Pendulum Scale", "category": "stat"},
    "stat_rank": {"zh_cn": "阶级", "ja": "ランク", "en": "Rank", "category": "stat"},
    "stat_ritual_material": {"zh_cn": None, "ja": None, "en": "Ritual Material", "category": "stat"},
    "stat_synchro_material": {"zh_cn": "同步素材", "ja": "Ｓ素材", "en": "Synchro Material", "category": "stat"},
    "stat_type": {"zh_cn": "种族", "ja": "種族", "en": "Type (race)", "category": "stat"},
    "stat_xys_material": {"zh_cn": "超量素材", "ja": "Ｘ素材", "en": "Xyz Material", "category": "stat"},
    "zone_banished": {"zh_cn": "除外状态", "ja": "除外状態", "en": "banished (cards) / banishment", "category": "zone"},
    "zone_battle_phase": {"zh_cn": "战斗阶段", "ja": "バトルフェイズ", "en": "Battle Phase", "category": "zone"},
    "zone_battle_step": {"zh_cn": "战斗步骤", "ja": "バトルステップ", "en": "Battle Step", "category": "zone"},
    "zone_damage_calculation": {"zh_cn": "伤害计算", "ja": "ダメージ計算", "en": "damage calculation", "category": "zone"},
    "zone_damage_step": {"zh_cn": "伤害步骤", "ja": "ダメージステップ", "en": "Damage Step", "category": "zone"},
    "zone_deck": {"zh_cn": "卡组", "ja": "デッキ", "en": "Deck", "category": "zone"},
    "zone_draw_phase": {"zh_cn": "抽牌阶段", "ja": "ドローフェイズ", "en": "Draw Phase", "category": "zone"},
    "zone_end_phase": {"zh_cn": "结束阶段", "ja": "エンドフェイズ", "en": "End Phase", "category": "zone"},
    "zone_extra_deck": {"zh_cn": "额外卡组", "ja": "ＥＸデッキ", "en": "Extra Deck", "category": "zone"},
    "zone_extra_monster_zone": {"zh_cn": "额外怪兽区域", "ja": "ＥＸモンスターゾーン", "en": "Extra Monster Zone", "category": "zone"},
    "zone_field": {"zh_cn": "场上", "ja": "フィールド", "en": "field", "category": "zone"},
    "zone_field_zone": {"zh_cn": "场地区域", "ja": "フィールドゾーン", "en": "Field Zone", "category": "zone"},
    "zone_graveyard": {"zh_cn": "墓地", "ja": "墓地", "en": "Graveyard", "category": "zone"},
    "zone_hand": {"zh_cn": "手卡", "ja": "手札", "en": "hand", "category": "zone"},
    "zone_main_deck": {"zh_cn": "主卡组", "ja": "メインのデッキ", "en": "Main Deck", "category": "zone"},
    "zone_main_monster_zone": {"zh_cn": "主要怪兽区域", "ja": "メインモンスターゾーン", "en": "Main Monster Zone", "category": "zone"},
    "zone_main_phase": {"zh_cn": "主要阶段", "ja": "メインフェイズ", "en": "Main Phase", "category": "zone"},
    "zone_monster_zone": {"zh_cn": "怪兽区域", "ja": "モンスターゾーン", "en": "Monster Zone", "category": "zone"},
    "zone_pendulum_zone": {"zh_cn": "灵摆区域", "ja": "Ｐゾーン", "en": "Pendulum Zone", "category": "zone"},
    "zone_side_deck": {"zh_cn": "副卡组", "ja": "サイドデッキ", "en": "Side Deck", "category": "zone"},
    "zone_spell_trap_zone": {"zh_cn": "魔法与陷阱区域", "ja": "魔法＆罠ゾーン", "en": "Spell & Trap Zone", "category": "zone"},
    "zone_standby_phase": {"zh_cn": "准备阶段", "ja": "スタンバイフェイズ", "en": "Standby Phase", "category": "zone"},
}

# @@FALLBACK_PATTERNS@@ 由 _probe/psct/_gen_fallback.py 生成（数据源 data/lexicons/psct_patterns.json，已裁掉 note/source）
# @@FALLBACK_PATTERNS@@ 由 _probe/psct/_gen_fallback.py 生成（数据源 data/lexicons/psct_patterns.json，已裁掉 note/source）
# @@FALLBACK_PATTERNS@@ 由 _probe/psct/_gen_fallback.py 生成（数据源 data/lexicons/psct_patterns.json，已裁掉 note/source）
_FALLBACK_PATTERNS: dict = {
    "punctuation": [
        {
            "symbol": "：",
            "role": "condition_separator",
            "en": ":",
            "ja": "：",
            "zh_cn": "：",
            "zh_tw": "：",
            "position": "before"
        },
        {
            "symbol": "；",
            "role": "activation_separator",
            "en": ";",
            "ja": "；",
            "zh_cn": "；",
            "zh_tw": "；",
            "position": "between"
        },
        {
            "symbol": "。",
            "role": "sentence_terminator",
            "en": ".",
            "ja": "。",
            "zh_cn": "。",
            "zh_tw": "。",
            "position": "after"
        },
        {
            "symbol": "（）",
            "role": "built_in_special_summon",
            "en": "()",
            "ja": "（）",
            "zh_cn": "（）",
            "zh_tw": "（）",
            "position": "inline"
        },
        {
            "symbol": "●",
            "role": "bulleted_effect",
            "en": "●",
            "ja": "●",
            "zh_cn": "●",
            "zh_tw": "●",
            "position": "inline"
        },
        {
            "symbol": "①",
            "role": "effect_number",
            "en": "①",
            "ja": "①",
            "zh_cn": "①",
            "zh_tw": "①",
            "position": "prefix"
        }
    ],
    "conjunctions": [
        {
            "key": "and",
            "en": "and",
            "ja": "し",
            "zh_cn": "并且",
            "zh_tw": "並且",
            "resolution_order": "simultaneous",
            "both_required": True,
            "requires_a_for_b": False,
            "aborts_b_if_a_fails": False
        },
        {
            "key": "then",
            "en": "then",
            "ja": "その後",
            "zh_cn": "那之后",
            "zh_tw": "那之後",
            "resolution_order": "sequential",
            "both_required": False,
            "requires_a_for_b": True,
            "aborts_b_if_a_fails": True
        },
        {
            "key": "also",
            "en": "also",
            "ja": "また",
            "zh_cn": "此外",
            "zh_tw": "此外",
            "resolution_order": "simultaneous",
            "both_required": False,
            "requires_a_for_b": False,
            "aborts_b_if_a_fails": False
        },
        {
            "key": "and_if_you_do",
            "en": "and if you do",
            "ja": "その場合",
            "zh_cn": "那个场合",
            "zh_tw": "那個場合",
            "resolution_order": "simultaneous",
            "both_required": True,
            "requires_a_for_b": True,
            "aborts_b_if_a_fails": True
        },
        {
            "key": "also_after_that",
            "en": "also, after that",
            "ja": "また、その後",
            "zh_cn": "此外，那之后",
            "zh_tw": "此外，那之後",
            "resolution_order": "sequential",
            "both_required": False,
            "requires_a_for_b": False,
            "aborts_b_if_a_fails": False
        }
    ],
    "hopt": [
        {
            "key": "once_per_turn",
            "en": "Once per turn:",
            "ja": "１ターンに１度、",
            "zh_cn": "1回合1次，",
            "zh_tw": "1回合1次，",
            "scope": "this_card",
            "strictness": "activate",
            "reset_on_leave": True,
            "placement": "activation_condition"
        },
        {
            "key": "hopt_name_use",
            "en": "You can only use each effect of \"X\" once per turn.",
            "ja": "このカード名の①②の効果はそれぞれ１ターンに１度しか使用できない。",
            "zh_cn": "这个卡名的①②的效果1回合各能使用1次。",
            "zh_tw": "這個卡名的①②的效果1回合各能使用1次。",
            "scope": "player_and_original_name",
            "strictness": "use",
            "reset_on_leave": False,
            "placement": "separate_sentence",
            "variants": ["You can only use this effect of \"X\" once per turn.", "You can only use 1 \"X\" effect per turn, and only once that turn.", "You can only use each effect of \"X\" once per Duel."]
        },
        {
            "key": "hopt_name_activate",
            "en": "You can only activate 1 \"X\" per turn.",
            "ja": "「X」は１ターンに１枚しか発動できない。",
            "zh_cn": "「X」1回合只能发动1张。",
            "zh_tw": "「X」1回合只能發動1張。",
            "scope": "player_and_original_name",
            "strictness": "activate",
            "reset_on_leave": False,
            "placement": "separate_sentence"
        },
        {
            "key": "hopt_name_apply",
            "en": "You can only apply this effect of \"X\" once per Duel.",
            "ja": "このカード名の効果はデュエル中に１度しか適用できない。",
            "zh_cn": "这个卡名的效果1场决斗中只能适用1次。",
            "zh_tw": "這個卡名的效果1場決鬥中只能適用1次。",
            "scope": "player_and_original_name",
            "strictness": "apply",
            "reset_on_leave": False
        },
        {
            "key": "hopt_gain_effect_once",
            "en": "(You can only gain this effect once per turn.)",
            "ja": "（この効果は１ターンに１度しか得られない。）",
            "zh_cn": "（这个效果1回合只能获得1次。）",
            "zh_tw": "（這個效果1回合只能獲得1次。）",
            "scope": "player",
            "strictness": "gain",
            "reset_on_leave": False
        },
        {
            "key": "hopt_once_while_face_up",
            "en": "Once while face-up on the field: ...",
            "ja": "このカードがモンスターゾーンに表側表示で存在する場合に１度、…",
            "zh_cn": "这张卡在怪兽区域表侧表示存在的场合，1次…",
            "zh_tw": "此卡在怪獸區表側表示存在的場合，1次…",
            "scope": "this_card",
            "strictness": "use",
            "reset_on_leave": True
        }
    ],
    "numbering": {
        "symbols": ["①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩"],
        "ascii_aliases": ["(1)", "(2)", "(3)", "(4)", "(5)"],
        "rule": "OCG 自 Starter Deck 2014 起为标准格式：卡片文本中的每个效果按出现顺序连续编号，编号仅作为「这个卡名的①②效果」这类交叉引用的锚点，本身不是效果内容。",
        "rules": ["编号只按顺序给「效果」编号；召唤条件、素材行、flavor text、灵摆效果（P效果单独另起 ① ②）不参与编号。", "灵摆怪兽有两个独立编号序列：怪兽效果用 ①②…，灵摆效果在「P效果」栏另起 ① ②…。", "「这个卡名的①②的效果1回合各能使用1次」引用的是编号，不是效果种类；因此新增或删除效果时必须重排编号。", "被「这个卡名的①的效果1回合只能使用1次」单独点名的，只有该编号的效果受限制。", "翻转怪兽的「FLIP:」效果在现行 Type line 记作 /反转，其效果文一般置于编号效果之前或作为独立段落。", "若一张卡同时有怪兽效果与灵摆效果，两者的 HOPT 限制互相独立。"]
    },
    "structure": {
        "template": "CONDITIONS : ACTIVATION ; RESOLUTION",
        "segments": [
            {
                "role": "conditions",
                "separator": ":",
                "en_label": "green text",
                "ja_label": "発動条件",
                "zh_cn_label": "发动条件",
                "contains": ["when / if timing", "once per turn", "activation requirement", "optional 'you can'"],
                "note": "只要求在发动时满足；处理时不需再满足。"
            },
            {
                "role": "activation",
                "separator": ";",
                "en_label": "red text",
                "ja_label": "発動時にすること",
                "zh_cn_label": "发动时要做的事",
                "contains": ["cost", "target"],
                "note": "在发动瞬间完成，不可被无效（属于 cost 的部分）。"
            },
            {
                "role": "resolution",
                "separator": ".",
                "en_label": "blue text",
                "ja_label": "効果の処理",
                "zh_cn_label": "效果处理",
                "contains": ["what actually happens"],
                "note": "连锁逆处理时才执行。"
            }
        ],
        "chain_rule": "效果文中出现「：」或「；」即表示该效果会入连锁；两者都没有则不入连锁、不能被连锁。",
        "spell_trap_exception": "魔法/陷阱卡只要发动就一定入连锁，即使效果文里没有冒号或分号（例：Creature Swap）。"
    },
    "timing_keywords": {
        "when": {
            "en": "when",
            "ja": "時",
            "zh_cn": "时",
            "zh_tw": "時",
            "strictness": "strict"
        },
        "if": {
            "en": "if",
            "ja": "場合",
            "zh_cn": "的场合",
            "zh_tw": "的場合",
            "strictness": "loose"
        },
        "you_can": {
            "en": "You can",
            "ja": "できる",
            "zh_cn": "可以",
            "zh_tw": "可以",
            "optionality": "optional"
        }
    },
    "conjunction_quadrants": {
        "axes": ["resolution_order (sequential | simultaneous)", "both_required / a_required_for_b"],
        "grid": [
            {
                "resolution_order": "sequential",
                "neither_required": "also_after_that",
                "a_required_for_b": "then",
                "both_required": None
            },
            {
                "resolution_order": "simultaneous",
                "neither_required": "also",
                "a_required_for_b": "and_if_you_do",
                "both_required": "and"
            }
        ]
    },
}


# ══════════════════════════════════════════════════════════════════════
#  加载
# ══════════════════════════════════════════════════════════════════════
def _read_json(name: str) -> tuple[Any, str]:
    """读一个词表文件。返回 ``(数据|None, 说明)``；**不抛异常**。"""
    path = paths.LEXICONS / name
    try:
        raw = path.read_bytes()
    except Exception as e:                                  # 文件不存在/无权限
        return None, f"不可读（{type(e).__name__}）"
    try:
        text = raw.decode("utf-8-sig")                      # 容忍 BOM
    except Exception as e:
        return None, f"非 UTF-8（{type(e).__name__}）"
    try:
        return json.loads(text), str(path)
    except Exception as e:
        return None, f"JSON 解析失败（{type(e).__name__}: {e}）"


def _norm_entry(raw: dict) -> dict:
    """把 ``None`` 单元格删掉，让回落链统一走"缺键"分支。"""
    out = {}
    for k, v in dict(raw or {}).items():
        if v is None:
            continue
        out[k] = v
    return out


def _load_terms() -> dict[str, dict]:
    data, note = _read_json(TERMS_FILE)
    file_terms = (data or {}).get("terms") if isinstance(data, dict) else None
    merged: dict[str, dict] = {k: _norm_entry(v) for k, v in _FALLBACK_TERMS.items()}
    if isinstance(file_terms, dict):
        for k, v in file_terms.items():
            if not isinstance(v, dict):
                continue
            base = merged.get(k, {})
            merged[k] = {**base, **_norm_entry(v)}
        _STATE["source"]["terms"] = note
    else:
        _STATE["source"]["terms"] = f"内置兜底表（{note}）"
    _STATE["source"]["terms_meta"] = (data or {}).get("_meta", {}) if isinstance(data, dict) else {}
    return merged


def _load_patterns() -> dict:
    data, note = _read_json(PATTERNS_FILE)
    if isinstance(data, dict):
        merged = copy.deepcopy(_FALLBACK_PATTERNS)
        for k, v in data.items():
            if k == "_meta":
                continue
            merged[k] = copy.deepcopy(v)
        _STATE["source"]["patterns"] = note
        merged["_meta"] = data.get("_meta", {})
        return merged
    _STATE["source"]["patterns"] = f"内置兜底表（{note}）"
    return copy.deepcopy(_FALLBACK_PATTERNS)


def reload() -> None:
    """强制重新读取词表（改完 JSON 不必重启进程）。"""
    with _LOCK:
        _STATE["terms"] = None
        _STATE["patterns"] = None
        _STATE["source"] = {}
        terms()
        patterns()


def _ensure() -> None:
    if _STATE["terms"] is None or _STATE["patterns"] is None:
        with _LOCK:
            if _STATE["terms"] is None:
                _STATE["terms"] = _load_terms()
            if _STATE["patterns"] is None:
                _STATE["patterns"] = _load_patterns()


def available() -> bool:
    """两个词表文件是否都真的读到了（False = 正在用内置兜底表）。"""
    _ensure()
    return not str(_STATE["source"].get("terms", "")).startswith("内置")


def sources() -> dict:
    """数据来源说明（doctor / 审计用）。"""
    _ensure()
    return dict(_STATE["source"])


# ══════════════════════════════════════════════════════════════════════
#  术语
# ══════════════════════════════════════════════════════════════════════
def terms() -> dict[str, dict]:
    """全部术语（``key → {语言: 文本, "category": …}``）。"""
    _ensure()
    return _STATE["terms"]


def has_native(key: str, lang: str) -> bool:
    """该 key 在目标语言里是否有**权威取值**（不是靠回落拿到的）。"""
    entry = terms().get(key)
    return bool(entry and entry.get(lang))


def term(key: str, lang: str) -> str:
    """取术语。回落链：``lang → en → zh_cn → 其余任意非空 → key``。

    **永不返回 None** —— 这是全引擎的硬约定。
    """
    entry = terms().get(key)
    if not entry:
        return key
    for lg in (lang, "en", "zh_cn"):
        v = entry.get(lg)
        if v:
            return str(v)
    for lg in TERM_LANGS:
        v = entry.get(lg)
        if v:
            return str(v)
    return key


def term_or_fallback(key: str, lang: str) -> tuple[str, str]:
    """返回 ``(文本, 实际使用的语言)``。

    韩文这类缺口语言会返回 ``("add ... from your Deck to your hand", "en")``，
    调用方据此在返回值里标注降级，而**不是**伪造韩文。
    """
    entry = terms().get(key)
    if not entry:
        return key, ""
    if entry.get(lang):
        return str(entry[lang]), lang
    for lg in ("en", "zh_cn"):
        if entry.get(lg):
            return str(entry[lg]), lg
    for lg in TERM_LANGS:
        if entry.get(lg):
            return str(entry[lg]), lg
    return key, ""


def confidence_of(key: str) -> str:
    """``official`` / ``community`` / ``unverified``；未知返回 ``""``。"""
    entry = terms().get(key) or {}
    return str(entry.get("confidence", ""))


def by_category(cat: str) -> dict[str, dict]:
    """按分类取术语（``attribute`` / ``race`` / ``card_type`` / ``action`` /
    ``zone`` / ``stat`` / ``psct_phrase``）。"""
    return {k: v for k, v in terms().items() if v.get("category") == cat}


def categories() -> dict[str, int]:
    out: dict[str, int] = {}
    for v in terms().values():
        c = str(v.get("category", ""))
        out[c] = out.get(c, 0) + 1
    return out


# ══════════════════════════════════════════════════════════════════════
#  反向本地化（中文规范值 → 目标语言）
# ══════════════════════════════════════════════════════════════════════
_REVERSE_KEYS: tuple[str, ...] = ("zh_cn", "zh_tw", "en", "ja")
_reverse_cache: dict[tuple[str, str], dict[str, str]] = {}


def _reverse(lang: str, category: str = "") -> dict[str, str]:
    """``{规范值: key}`` 反查表（按分类缓存）。"""
    ck = (lang, category)
    hit = _reverse_cache.get(ck)
    if hit is not None:
        return hit
    table: dict[str, str] = {}
    src = by_category(category) if category else terms()
    for k, v in src.items():
        for col in _REVERSE_KEYS:
            val = v.get(col)
            if val and str(val) not in table:
                table[str(val)] = k
    _reverse_cache[ck] = table
    return table


def localize(value: str, lang: str, category: str = "", *,
             suffixes: Iterable[str] = ("", "属性", "族", "卡")) -> str:
    """把中文规范值翻成目标语言（``"暗"`` → ``"DARK"``）。

    逐级尝试 ``value + suffix``；实在找不到就**原样返回**（并可由调用方
    通过 ``localize(...) == value`` 判断发生了降级）。
    """
    value = str(value or "").strip()
    if not value:
        return ""
    table = _reverse(lang, category)
    for suf in suffixes:
        key = table.get(value + suf)
        if key:
            got = terms().get(key, {}).get(lang)
            if got:
                return str(got)
    # 直接按 key 前缀找（"race_dragon" / "attr_dark" 这类完整键）
    for cand in (value, f"attr_{value}", f"race_{value}"):
        entry = terms().get(cand)
        if entry and entry.get(lang):
            return str(entry[lang])
    return value


def race_term(zh_race: str, lang: str) -> str:
    """种族名。**官方简中与日文一律带「族」后缀**（``龙族`` / ``ドラゴン族``）。"""
    base = localize(zh_race, lang, "race")
    if lang in ("zh_cn", "zh_tw") and base and not base.endswith("族"):
        base += "族"
    if lang == "ja" and base and not base.endswith("族"):
        base += "族"
    return base


def attribute_term(zh_attr: str, lang: str) -> str:
    """属性名（``暗`` → ``暗属性`` / ``闇`` / ``DARK``）。"""
    base = localize(zh_attr, lang, "attribute")
    if lang in ("zh_cn", "zh_tw") and base and not base.endswith("属性"):
        base += "属性"
    return base


def zone_term(zone: str, lang: str) -> str:
    """区域名。先查 IC 键（DECK/HAND/…），再查中文词。"""
    z = str(zone or "").strip().upper()
    words = rules.ZONE_WORDS.get(z)
    if words:
        return words.get(lang) or words.get("en") or z
    return localize(zone, lang, "zone")


def stat_term(zh_stat: str, lang: str) -> str:
    return localize(zh_stat, lang, "stat")


def card_type_term(key_or_zh: str, lang: str) -> str:
    """卡种名。给 key（``card_quick_play_spell``）或中文（``速攻魔法``）都能查。"""
    key = str(key_or_zh or "")
    entry = terms().get(key)
    if entry and entry.get(lang):
        return str(entry[lang])
    return localize(key, lang, "card_type")


def quote(name: str, lang: str) -> str:
    """按语言给卡名/字段名加引号（中「」 / 英 "…"）。"""
    st = rules.style(lang)
    return f"{st.quote_open}{name}{st.quote_close}"


# ══════════════════════════════════════════════════════════════════════
#  句式（psct_patterns.json）
# ══════════════════════════════════════════════════════════════════════
def patterns() -> dict:
    """``psct_patterns.json`` 的完整结构（缺失时用内置兜底）。"""
    _ensure()
    return _STATE["patterns"]


def punctuation(lang: str) -> dict:
    """标点角色 → 该语言符号。

    返回形如 ``{"condition_separator": "：", "activation_separator": "；", …}``。
    注意：**符号存在 ≠ 该语言会用它** —— 中日文官方卡文不用「；」，
    是否使用请查 :data:`rules.LANG_STYLE` / ``LANGS[lang].uses_semicolon``。
    """
    out = dict(rules.punctuation_of(lang))
    for item in patterns().get("punctuation", []) or []:
        role = item.get("role")
        sym = item.get(lang) or item.get("en")
        if role and sym:
            out[str(role)] = str(sym)
    return out


def _find(seq: Iterable[dict], key: str) -> Optional[dict]:
    for item in seq or []:
        if isinstance(item, dict) and item.get("key") == key:
            return item
    return None


def conjunction(key: str, lang: str) -> str:
    """连接词译法（``then`` → ``那之后`` / ``その後`` / ``then``）。

    以 ``patterns().conjunctions`` 为唯一来源，缺该语言时回落 en → zh_cn →
    :data:`rules.CONJUNCTIONS` 里的内置值 → 返回 key 本身。
    """
    item = _find(patterns().get("conjunctions", []), key)
    if item:
        v = item.get(lang) or item.get("en") or item.get("zh_cn")
        if v:
            return str(v)
    builtin = rules.CONJUNCTIONS.get(key)
    if builtin:
        return builtin.text(lang)
    return key


def hopt(key: str, lang: str, name: str = "", numbers: str = "①②") -> str:
    """HOPT 句式（整句，含句末标点），可带入卡名与编号。

    :param key: ``once_per_turn`` / ``hopt_name_use``（``hopt_name`` 亦可）/
        ``hopt_name_activate`` / ``hopt_name_apply`` / ``hopt_gain_effect_once`` /
        ``hopt_once_while_face_up``
    :param name: 卡名。模板里的 ``X`` / ``「X」`` / ``"X"`` 会被替换；
        不传时**保留占位符**（便于人读，不伪造）。
    :param numbers: 编号引用串，默认 ``①②``；单效果卡传 ``①``。
    """
    k = rules.LIMIT_ALIASES.get(key, key)
    tpl = ""
    item = _find(patterns().get("hopt", []), k)
    if item:
        tpl = str(item.get(lang) or item.get("en") or item.get("zh_cn") or "")
    if not tpl:
        spec = rules.HOPT_SPECS.get(k)
        if spec:
            tpl = spec.text(lang)
    if not tpl:
        return key

    out = tpl
    if numbers:
        out = out.replace("①②", numbers)
        if numbers != "①②":
            out = out.replace("①", numbers)
    else:
        out = out.replace("①②", "").replace("①", "")
    if name:
        q = quote(name, lang)
        out = out.replace('"X"', q).replace("「X」", q).replace("'X'", q)
        if "X" in out:                       # 兜底：模板里可能有裸 X
            out = out.replace("X", name)
    return out


def hopt_single(lang: str, name: str = "", numbers: str = "①") -> str:
    """**只限制其中一个效果**时的 HOPT 句式（官方单数写法）。

    中文「这个卡名的①的效果1回合只能使用1次。」/ 日文
    「このカード名の①の効果は１ターンに１度しか使用できない。」/ 英文
    ``You can only use this effect of "X" once per turn.``

    数据源是术语 ``psct_hopt_name_this``；缺失时退回 :func:`hopt` 的复数句式。
    """
    tpl, _used = term_or_fallback("psct_hopt_name_this", lang)
    if not tpl or tpl == "psct_hopt_name_this":
        return hopt("hopt_name_use", lang, name, numbers=numbers)
    out = tpl
    if numbers:
        out = out.replace("①②", numbers).replace("①", numbers)
    if name:
        q = quote(name, lang)
        out = out.replace('"X"', q).replace("「X」", q)
        if "X" in out:
            out = out.replace("X", name)
    return out


# ══════════════════════════════════════════════════════════════════════
#  覆盖率 / 降级
# ══════════════════════════════════════════════════════════════════════
def lang_coverage(lang: str) -> float:
    """某语言的术语覆盖率（0–1）。"""
    all_terms = terms()
    if not all_terms:
        return 0.0
    have = sum(1 for v in all_terms.values() if v.get(lang))
    return have / float(len(all_terms))


def coverage_report() -> dict:
    """覆盖率报告：按语言 + 按分类 + 可生成性判定。

    结构与 ``data/lexicons/README.md`` §3 对应，另加生成器需要的
    ``usable_for_generation`` / ``degraded`` 两个判定字段。
    """
    all_terms = terms()
    total = len(all_terms)
    by_lang: dict[str, dict] = {}
    for lg in TERM_LANGS:
        present = sum(1 for v in all_terms.values() if v.get(lg))
        missing = [k for k, v in all_terms.items() if not v.get(lg)]
        missing_by_cat: dict[str, int] = {}
        for k in missing:
            c = str(all_terms[k].get("category", ""))
            missing_by_cat[c] = missing_by_cat.get(c, 0) + 1
        cov = present / float(total) if total else 0.0
        native_gen = lg in rules.NATIVE_GEN_LANGS
        usable = native_gen and cov >= rules.COVERAGE_FLOOR
        by_lang[lg] = {
            "label": getattr(LANGS.get(lg), "zh_cn", lg),
            "present": present, "null": total - present,
            "coverage": round(cov, 4),
            "missing_by_category": missing_by_cat,
            "native_templates": native_gen,
            "usable_for_generation": usable,
            "degraded": not usable,
            "fallback_chain": ([] if usable
                               else (["en"] if lg != "en" else ["zh_cn"])),
            "missing_examples": missing[:6],
        }
    return {
        "total": total,
        "by_lang": by_lang,
        "by_category": categories(),
        "native_gen_langs": list(rules.NATIVE_GEN_LANGS),
        "coverage_floor": rules.COVERAGE_FLOOR,
        "degraded_langs": [lg for lg, d in by_lang.items() if d["degraded"]],
        "sources": sources(),
        "available": available(),
        "note": "coverage 只统计「该语言是否有权威取值」，不代表整句式可直接拼装；"
                "本引擎只为 zh_cn/ja/en 提供原生句式模板，其余语言降级到 en。",
    }


def generation_lang(lang: str) -> tuple[str, str]:
    """生成前决定实际使用哪种语言。

    返回 ``(实际语言, 降级原因)``；``""`` 表示无需降级。
    """
    if lang in rules.NATIVE_GEN_LANGS:
        return lang, ""
    if lang == "en":
        return "en", ""
    cov = lang_coverage(lang)
    return "en", (f"没有 {lang} 的原生 PSCT 句式模板"
                  f"（术语覆盖率 {cov:.1%}），已降级到 en")


def degraded_reason(lang: str) -> str:
    return generation_lang(lang)[1]


__all__ += ["categories"]
