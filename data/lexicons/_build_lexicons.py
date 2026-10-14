# -*- coding: utf-8 -*-
"""Build terms.json + psct_patterns.json for the Yu-Gi-Oh! card-creation lexicon.

Generated from web-collected authoritative sources. See README.md.
"""
import json, os
from collections import OrderedDict

OUT = os.path.dirname(os.path.abspath(__file__))
GENERATED = "2026-10-13"

DB_CN = "https://db.yugioh-card-cn.com/card_search.action.html"
SRC = OrderedDict()
SRC["db_cn"] = DB_CN
SRC["psct3"] = "https://www.yugioh-card.com/en/play/psct/psct-3/"
SRC["psct7"] = "https://www.yugioh-card.com/en/play/psct/psct-7/"
SRC["psct1"] = "https://www.yugioh-card.com/en/play/psct/psct-1/"
SRC["psct2"] = "https://www.yugioh-card.com/en/play/psct/psct-2/"
SRC["psct4"] = "https://www.yugioh-card.com/en/play/psct/psct-4/"
SRC["psct5"] = "https://www.yugioh-card.com/en/play/psct/psct-5/"
SRC["psct6"] = "https://www.yugioh-card.com/en/play/psct/psct-6/"
SRC["ygo_monster_card"] = "https://yugipedia.com/wiki/Monster_Card?action=raw"
SRC["ygo_psct"] = "https://yugipedia.com/wiki/Problem-Solving_Card_Text?action=raw"
SRC["ygo_hopt"] = "https://yugipedia.com/wiki/Once_per_turn?action=raw"
SRC["ygo_hopt_only"] = "https://yugipedia.com/wiki/Only_once_per_turn?action=raw"
SRC["ygo_actcond"] = "https://yugipedia.com/wiki/Activation_condition?action=raw"
SRC["ygo_cost"] = "https://yugipedia.com/wiki/Cost?action=raw"
SRC["ygo_quick"] = "https://yugipedia.com/wiki/Quick_Effect?action=raw"
SRC["ygo_cardtext"] = "https://yugipedia.com/wiki/Card_text?action=raw"

def y(page):
    return "https://yugipedia.com/wiki/%s?action=raw" % page

LANG_KEYS = ["en", "zh_cn", "zh_tw", "ja", "ko", "de", "fr", "it", "pt", "es"]

# ---------------------------------------------------------------------------
# Term table.
# Compact row format: key, cat, en, zh_cn, zh_tw, ja, ko, de, fr, it, pt, es, conf, src
# Use None where genuinely not found.
# ---------------------------------------------------------------------------
ROWS = []

def T(key, cat, en, zh_cn=None, zh_tw=None, ja=None, ko=None, de=None, fr=None,
      it=None, pt=None, es=None, conf="official", src=None):
    ROWS.append(dict(key=key, category=cat, en=en, zh_cn=zh_cn, zh_tw=zh_tw, ja=ja,
                     ko=ko, de=de, fr=fr, it=it, pt=pt, es=es,
                     confidence=conf, source=src))

# ======================= ATTRIBUTE (7) =======================
ATTR_SRC = DB_CN
T("attr_dark", "attribute", "DARK", "暗属性", "闇屬性", "闇", "어둠",
  "FINSTERNIS", "TÉNÈBRES", "OSCURITÀ", "TREVAS", "OSCURIDAD", src=y("DARK"))
T("attr_light", "attribute", "LIGHT", "光属性", "光屬性", "光", "빛",
  "LICHT", "LUMIÈRE", "LUCE", "LUZ", "LUZ", src=y("LIGHT"))
T("attr_earth", "attribute", "EARTH", "地属性", "地屬性", "地", "땅",
  "ERDE", "TERRE", "TERRA", "TERRA", "TIERRA", src=y("EARTH"))
T("attr_water", "attribute", "WATER", "水属性", "水屬性", "水", "물",
  "WASSER", "EAU", "ACQUA", "ÁGUA", "AGUA", src=y("WATER"))
T("attr_fire", "attribute", "FIRE", "炎属性", "炎屬性", "炎", "화염",
  "FEUER", "FEU", "FUOCO", "FOGO", "FUEGO", src=y("FIRE"))
T("attr_wind", "attribute", "WIND", "风属性", "風屬性", "風", "바람",
  "WIND", "VENT", "VENTO", "VENTO", "VIENTO", src=y("WIND"))
T("attr_divine", "attribute", "DIVINE", "神属性", "神屬性", "神", "신",
  "GÖTTLICH", "DIVIN", "DIVINO", "DIVINO", "DIVINIDAD", src=y("DIVINE"))

# ======================= RACE / TYPE (26) =======================
# zh_cn follows the official Simplified Chinese database filter labels (with 族 suffix).
# zh_tw follows the Taiwan/HK Traditional Chinese labels (also with 族 suffix in card text).
T("race_spellcaster", "race", "Spellcaster", "魔法师族", "魔法師族", "魔法使い", "마법사",
  "Hexer", "Magicien", "Incantatore", "Mago", "Lanzador de Conjuros", src=y("Spellcaster"))
T("race_dragon", "race", "Dragon", "龙族", "龍族", "ドラゴン", "드래곤",
  "Drache", "Dragon", "Drago", "Dragão", "Dragón", src=y("Dragon"))
T("race_zombie", "race", "Zombie", "不死族", "不死族", "アンデット", "언데드",
  "Zombie", "Zombie", "Zombie", "Zumbi", "Zombi", src=y("Zombie"))
T("race_warrior", "race", "Warrior", "战士族", "戰士族", "戦士", "전사",
  "Krieger", "Guerrier", "Guerriero", "Guerreiro", "Guerrero", src=y("Warrior"))
T("race_beast_warrior", "race", "Beast-Warrior", "兽战士族", "獸戰士族", "獣戦士", "야수전사",
  "Ungeheuer-Krieger", "Bête-Guerrier", "Guerriero-Bestia", "Besta-Guerreira",
  "Guerrero-Bestia", src=y("Beast-Warrior"))
T("race_beast", "race", "Beast", "兽族", "獸族", "獣", "야수",
  "Ungeheuer", "Bête", "Bestia", "Besta", "Bestia", src=y("Beast"))
T("race_winged_beast", "race", "Winged Beast", "鸟兽族", "鳥獸族", "鳥獣", "비행야수",
  "Geflügeltes Ungeheuer", "Bête Ailée", "Bestia Alata", "Besta Alada",
  "Bestia Alada", src=y("Winged_Beast"))
T("race_fiend", "race", "Fiend", "恶魔族", "惡魔族", "悪魔", "악마",
  "Unterweltler", "Démon", "Demone", "Demônio", "Demonio", src=y("Fiend"))
T("race_fairy", "race", "Fairy", "天使族", "天使族", "天使", "천사",
  "Fee", "Elfe", "Fata", "Fada", "Hada", src=y("Fairy"))
T("race_insect", "race", "Insect", "昆虫族", "昆蟲族", "昆虫", "곤충",
  "Insekt", "Insecte", "Insetto", "Inseto", "Insecto", src=y("Insect"))
T("race_dinosaur", "race", "Dinosaur", "恐龙族", "恐龍族", "恐竜", "공룡",
  "Dinosaurier", "Dinosaure", "Dinosauro", "Dinossauro", "Dinosaurio", src=y("Dinosaur"))
T("race_reptile", "race", "Reptile", "爬虫类族", "爬蟲類族", "爬虫類", "파충류",
  "Reptil", "Reptile", "Rettile", "Réptil", "Reptil", src=y("Reptile"))
T("race_fish", "race", "Fish", "鱼族", "魚族", "魚", "어류",
  "Fisch", "Poisson", "Pesce", "Peixe", "Pez", src=y("Fish"))
T("race_sea_serpent", "race", "Sea Serpent", "海龙族", "海龍族", "海竜", "해룡",
  "Seeschlange", "Serpent de Mer", "Serpente Marino", "Serpente Marinha",
  "Serpiente Marina", src=y("Sea_Serpent"))
T("race_aqua", "race", "Aqua", "水族", "水族", "水", "물",
  "Aqua", "Aqua", "Acqua", "Aqua", "Aqua", src=y("Aqua"))
T("race_pyro", "race", "Pyro", "炎族", "炎族", "炎", "화염",
  "Pyro", "Pyro", "Pyro", "Piro", "Piro", src=y("Pyro"))
T("race_thunder", "race", "Thunder", "雷族", "雷族", "雷", "번개",
  "Donner", "Tonnerre", "Tuono", "Trovão", "Trueno", src=y("Thunder"))
T("race_rock", "race", "Rock", "岩石族", "岩石族", "岩石", "암석",
  "Fels", "Rocher", "Roccia", "Rocha", "Roca", src=y("Rock"))
T("race_plant", "race", "Plant", "植物族", "植物族", "植物", "식물",
  "Pflanze", "Plante", "Pianta", "Planta", "Planta", src=y("Plant"))
T("race_machine", "race", "Machine", "机械族", "機械族", "機械", "기계",
  "Maschine", "Machine", "Macchina", "Máquina", "Máquina", src=y("Machine"))
T("race_psychic", "race", "Psychic", "念动力族", "超能族", "サイキック", "사이킥",
  "Psi", "Psychique", "Psichico", "Psíquico", "Psíquico", src=y("Psychic"))
T("race_divine_beast", "race", "Divine-Beast", "幻神兽族", "幻神獸族", "幻神獣", "환신야수",
  "Göttliches Ungeheuer", "Bête Divine", "Divinità-Bestia", "Besta Divina",
  "Bestia Divina", src=y("Divine-Beast"))
T("race_creator_god", "race", "Creator God", "创造神族", "創造神族", "創造神", None,
  None, None, None, None, None, conf="official", src=y("Creator_God"))
T("race_wyrm", "race", "Wyrm", "幻龙族", "幻龍族", "幻竜", "환룡",
  "Wyrm", "Wyrm", "Wyrm", "Wyrm", "Wyrm", src=y("Wyrm"))
T("race_cyberse", "race", "Cyberse", "电子界族", "電子界族", "サイバース", "사이버스",
  "Cyberse", "Cyberse", "Cyberso", "Ciberso", "Ciberso", src=y("Cyberse"))
T("race_illusion", "race", "Illusion", "幻想魔族", "幻想魔族", "幻想魔", "환상마",
  "Illusion", "Illusion", "Illusione", "Ilusão", "Ilusión", src=y("Illusion"))

# ======================= CARD TYPE (35) =======================
T("card_monster", "card_type", "Monster Card", "怪兽卡", "怪獸卡", "モンスターカード", "몬스터 카드",
  "Monsterkarte", "Carte Monstre", "Carta Mostro", "Card de Monstro", "Carta de Monstruo",
  src=y("Monster_Card"))
T("card_normal_monster", "card_type", "Normal Monster", "通常怪兽", "通常怪獸", "通常モンスター",
  "일반 몬스터", "Normales Monster", "Monstre Normal", "Mostro Normale", "Monstro Normal",
  "Monstruo Normal", src=y("Normal_Monster"))
T("card_effect_monster", "card_type", "Effect Monster", "效果怪兽", "效果怪獸", "効果モンスター",
  "효과 몬스터", "Effektmonster", "Monstre à Effet", "Mostro con Effetto",
  "Monstro de Efeito", "Monstruo de Efecto", src=y("Effect_Monster"))
T("card_non_effect_monster", "card_type", "non-Effect Monster", None, None, "効果モンスター以外",
  None, None, None, None, None, None, conf="unverified")
T("card_ritual_monster", "card_type", "Ritual Monster", "仪式怪兽", "儀式怪獸", "儀式モンスター",
  "의식 몬스터", "Ritualmonster", "Monstre Rituel", "Mostro Rituale", "Monstro de Ritual",
  "Monstruo de Ritual", src=y("Ritual_Monster"))
T("card_fusion_monster", "card_type", "Fusion Monster", "融合怪兽", "融合怪獸", "融合モンスター",
  "융합 몬스터", "Fusionsmonster", "Monstre Fusion", "Mostro Fusione", "Monstro de Fusão",
  "Monstruo de Fusión", src=y("Fusion_Monster"))
T("card_synchro_monster", "card_type", "Synchro Monster", "同步怪兽", "同步怪獸", "Ｓモンスター",
  "싱크로 몬스터", "Synchromonster", "Monstre Synchro", "Mostro Synchro", "Monstro Sincro",
  "Monstruo de Sincronía", src=y("Synchro_Monster"))
T("card_xyz_monster", "card_type", "Xyz Monster", "超量怪兽", "超量怪獸", "Ｘモンスター",
  "엑시즈 몬스터", "Xyz-Monster", "Monstre Xyz", "Mostro Xyz", "Monstro Xyz",
  "Monstruo Xyz", src=y("Xyz_Monster"))
T("card_pendulum_monster", "card_type", "Pendulum Monster", "灵摆怪兽", "鐘擺怪獸", "Ｐモンスター",
  "펜듈럼 몬스터", "Pendelmonster", "Monstre Pendule", "Mostro Pendulum",
  "Monstro Pêndulo", "Monstruo de Péndulo", src=y("Pendulum_Monster"))
T("card_link_monster", "card_type", "Link Monster", "连接怪兽", "連結怪獸", "Ｌモンスター",
  "링크 몬스터", "Linkmonster", "Monstre Lien", "Mostro Link", "Monstro Link",
  "Monstruo de Enlace", src=y("Link_Monster"))
T("card_token", "card_type", "Monster Token", "衍生物", "衍生物", "モンスタートークン", "몬스터 토큰",
  "Monsterspielmarke", "Jeton Monstre", "Segna-Mostro", "Ficha de Monstro",
  "Ficha de Monstruo", src=y("Monster_Token"))
T("card_spell", "card_type", "Spell Card", "魔法卡", "魔法卡", "魔法カード", "마법 카드",
  "Zauberkarte", "Carte Magie", "Carta Magia", "Card de Magia", "Carta Mágica",
  src=y("Spell_Card"))
T("card_trap", "card_type", "Trap Card", "陷阱卡", "陷阱卡", "罠カード", "함정 카드",
  "Fallenkarte", "Carte Piège", "Carta Trappola", "Card de Armadilha", "Carta de Trampa",
  src=y("Trap_Card"))
T("card_normal_spell", "card_type", "Normal Spell", "通常魔法卡", "通常魔法卡", "通常魔法カード",
  "일반 마법 카드", "Normale Zauberkarte", "Carte Magie Normale", "Carta Magia Normale",
  "Card de Magia Normal", "Carta Mágica Normal", src=y("Normal_Spell_Card"))
T("card_continuous_spell", "card_type", "Continuous Spell", "永续魔法卡", "永續魔法卡",
  "永続魔法カード", "지속 마법 카드", "Permanente Zauberkarte", "Carte Magie Continue",
  "Carta Magia Continua", "Card de Magia Contínuo", "Carta Mágica Continua",
  src=y("Continuous_Spell_Card"))
T("card_equip_spell", "card_type", "Equip Spell", "装备魔法卡", "裝備魔法卡", "装備魔法カード",
  "장착 마법 카드", "Ausrüstungszauberkarte", "Carte Magie d'Équipement",
  "Carta Magia Equipaggiamento", "Card de Magia de Equipamento", "Carta Mágica de Equipo",
  src=y("Equip_Spell_Card"))
T("card_field_spell", "card_type", "Field Spell", "场地魔法卡", "場地魔法卡", "フィールド魔法カード",
  "필드 마법 카드", "Spielfeldzauberkarte", "Carte Magie de Terrain",
  "Carta Magia Terreno", "Card de Magia de Campo", "Carta Mágica de Campo",
  src=y("Field_Spell_Card"))
T("card_quick_play_spell", "card_type", "Quick-Play Spell", "速攻魔法卡", "速攻魔法卡",
  "速攻魔法カード", "속공 마법 카드", "Schnellzauberkarte", "Carte Magie Jeu-Rapide",
  "Carta Magia Rapida", "Card de Magia Rápida", "Carta Mágica de Juego Rápido",
  src=y("Quick-Play_Spell_Card"))
T("card_ritual_spell", "card_type", "Ritual Spell", "仪式魔法卡", "儀式魔法卡", "儀式魔法カード",
  "의식 마법 카드", "Ritualzauberkarte", "Carte Magie Rituelle", "Carta Magia Rituale",
  "Card de Magia de Ritual", "Carta Mágica de Ritual", src=y("Ritual_Spell_Card"))
T("card_normal_trap", "card_type", "Normal Trap", "通常陷阱卡", "通常陷阱卡", "通常罠カード",
  "일반 함정 카드", "Normale Fallenkarte", "Carte Piège Normal", "Carta Trappola Normale",
  "Card de Armadilha Normal", "Carta de Trampa Normal", src=y("Normal_Trap_Card"))
T("card_continuous_trap", "card_type", "Continuous Trap", "永续陷阱卡", "永續陷阱卡",
  "永続罠カード", "지속 함정 카드", "Permanente Fallenkarte", "Carte Piège Continu",
  "Carta Trappola Continua", "Card de Armadilha Contínuo", "Carta de Trampa Continua",
  src=y("Continuous_Trap_Card"))
T("card_counter_trap", "card_type", "Counter Trap", "反击陷阱卡", "反制陷阱卡", "カウンター罠カード",
  "카운터 함정 카드", "Konterfallenkarte", "Carte Contre-Piège", "Carta Contro-Trappola",
  "Card de Armadilha de Resposta", "Carta de Trampa de Contraefecto",
  src=y("Counter_Trap_Card"))
T("card_tuner", "card_type", "Tuner monster", "协调怪兽", "協調怪獸", "チューナー", "튜너",
  "Empfänger-Monster", "monstre Syntoniseur", "mostro Tuner", "monstro Regulador",
  "monstruo Cantante", src=y("Tuner_monster"))
T("card_union", "card_type", "Union monster", "联合怪兽", "聯合怪獸", "ユニオンモンスター",
  "유니온 몬스터", "Union-Monster", "monstre Union", "mostro Unione", "monstro União",
  "monstruo de Unión", src=y("Union_monster"))
T("card_gemini", "card_type", "Gemini monster", "二重怪兽", "二重怪獸", "デュアルモンスター",
  "듀얼 몬스터", "Zwillingsmonster", "monstre Gémeau", "mostro Gemello", "monstro Gêmeos",
  "monstruo Géminis", src=y("Gemini_monster"))
T("card_flip", "card_type", "Flip monster", "反转怪兽", "反轉怪獸", "リバースモンスター",
  "리버스 몬스터", "Flippmonster", "monstre Flip", "mostro Scoperta", "monstro de Virar",
  "monstruo de Volteo", src=y("Flip_monster"))
T("card_spirit", "card_type", "Spirit monster", "灵魂怪兽", "靈魂怪獸", "スピリットモンスター",
  "스피릿 몬스터", "Spirit-Monster", "monstre Spirit", "mostro Spirit", "monstro Espírito",
  "monstruo Spirit", src=y("Spirit_monster"))
T("card_toon", "card_type", "Toon monster", "卡通怪兽", "卡通怪獸", "トゥーンモンスター",
  "툰 몬스터", "Toon-Monster", "monstre Toon", "mostro Toon", "monstro Toon",
  "monstruo Toon", src=y("Toon_monster"))
T("card_special_summon_monster", "card_type", "Special Summon Monster", "特殊召唤怪兽",
  "特殊召喚怪獸", "特殊召喚モンスター", "특수 소환 몬스터", "Spezialbeschwörungsmonster",
  "Monstre à Invocation Spéciale", "Mostro a Evocazione Speciale",
  "Monstro de Invocação-Especial", "Monstruo de Invocación Especial",
  src=y("Special_Summon_Monster"))
T("card_dark_synchro", "card_type", "Dark Synchro Monster", None, None,
  "ダークシンクロモンスター", None, None, None, "Mostro Synchro Oscuro",
  "Monstros Sincro das Trevas", None, conf="official", src=y("Dark_Synchro_Monster"))
T("card_maximum", "card_type", "Maximum Monster", None, None, "マキシマムモンスター",
  "맥시멈 몬스터", None, None, None, None, None, conf="official", src=y("Maximum_Monster"))
T("card_effect", "card_type", "effect", "效果", "效果", "効果", "효과", "Effekt", "effet",
  "effetto", "efeito", "efecto", src=y("Effect"))
T("card_ability", "card_type", "Ability", "能力", "能力", "能力", "능력", None, None,
  None, None, None, src=y("Ability"))

# ======================= ACTION (38) =======================
T("act_search", "action", "add ... from your Deck to your hand", "从卡组把…加入手卡",
  "從牌組將…加入手牌", "デッキから…手札に加える", None, "von deinem Deck ... der Hand hinzufügen",
  "ajouter ... depuis votre Deck à votre main", "aggiungere ... dal tuo Deck alla tua mano",
  "adicionar ... do seu Deck à sua mão", "añadir ... de tu Deck a tu mano",
  conf="community", src=y("Add_a_card"))
T("act_add_to_hand", "action", "add to hand", "加入手卡", "加入手牌", "手札に加える",
  None, None, None, None, None, None, conf="community")
T("act_special_summon", "action", "Special Summon", "特殊召唤", "特殊召喚", "特殊召喚",
  "특수 소환", "Spezialbeschwörung", "Invocation Spéciale", "Evocazione Speciale",
  "Invocação-Especial", "Invocación Especial", src=y("Special_Summon"))
T("act_normal_summon", "action", "Normal Summon", "通常召唤", "通常召喚", "通常召喚",
  "통상 소환", "Normalbeschwörung", "Invocation Normale", "Evocazione Normale",
  "Invocação-Normal", "Invocación Normal", src=y("Normal_Summon"))
T("act_tribute_summon", "action", "Tribute Summon", "上级召唤", "升級召喚", "Ａ召喚",
  "어드밴스 소환", "Tributbeschwörung", "Invocation Sacrifice",
  "Evocazione tramite Tributo", "Invocação-Tributo", "Invocación por Sacrificio",
  src=y("Tribute_Summon"))
T("act_flip_summon", "action", "Flip Summon", "反转召唤", "反轉召喚", "反転召喚",
  "반전 소환", "Flippbeschwörung", "Invocation Flip", "Evocazione per Scoperta",
  "Invocação-Virar", "Invocación por Volteo", src=y("Flip_Summon"))
T("act_set", "action", "Set", "放置", "覆蓋", "セット", "세트", "setzen", "Poser",
  "Posizionare", "Baixar", "Colocar", src=y("Set"))
T("act_fusion_summon", "action", "Fusion Summon", "融合召唤", "融合召喚", "融合召喚",
  "융합 소환", "Fusionsbeschwörung", "Invocation Fusion", "Evocazione tramite Fusione",
  "Invocação-Fusão", "Invocación por Fusión", src=y("Fusion_Summon"))
T("act_synchro_summon", "action", "Synchro Summon", "同步召唤", "同步召喚", "Ｓ召喚",
  "싱크로 소환", "Synchrobeschwörung", "Invocation Synchro", "Synchro Evocazione",
  "Invocação-Sincro", "Invocación por Sincronía", src=y("Synchro_Summon"))
T("act_xyz_summon", "action", "Xyz Summon", "超量召唤", "超量召喚", "Ｘ召喚",
  "엑시즈 소환", "Xyz-Beschwörung", "Invocation Xyz", "Evocazione Xyz", "Invocação-Xyz",
  "Invocación Xyz", src=y("Xyz_Summon"))
T("act_pendulum_summon", "action", "Pendulum Summon", "灵摆召唤", "鐘擺召喚", "Ｐ召喚",
  "펜듈럼 소환", "Pendelbeschwörung", "Invocation Pendule", "Evocazione Pendulum",
  "Invocação-Pêndulo", "Invocación por Péndulo", src=y("Pendulum_Summon"))
T("act_link_summon", "action", "Link Summon", "连接召唤", "連結召喚", "Ｌ召喚",
  "링크 소환", "Linkbeschwörung", None, "Evocazione Link", "Invocação-Link",
  "Invocación por Enlace", src=y("Link_Summon"))
T("act_ritual_summon", "action", "Ritual Summon", "仪式召唤", "儀式召喚", "儀式召喚",
  "의식 소환", "Ritualbeschwörung", "Invocation Rituelle", "Evocazione Rituale",
  "Invocação-Ritual", "Invocación de Ritual", src=y("Ritual_Summon"))
T("act_destroy", "action", "destroy", "破坏", "破壞", "破壊", "파괴", "zerstören", "détruire",
  "distruggere", "destruir", "destruir", src=y("Destroy"))
T("act_banish", "action", "banish", "除外", "除外", "除外", "제외", "verbannen", "bannir",
  "bandire", "banir", "desterrar", src=y("Banish"))
T("act_send", "action", "send (to the Graveyard)", "送去墓地", "送去墓地", "墓地へ送る",
  "묘지로 보내다", "auf den Friedhof legen", "envoyer au Cimetière",
  "mandare al Cimitero", "enviar para o Cemitério", "mandar al Cementerio",
  conf="community", src=y("Send"))
T("act_return", "action", "return (to the hand / Deck)", "回到", "回到", "戻す", "되돌리다",
  "zurückgeben", "renvoyer", "ritornare", "devolver", "devolver", src=y("Return"))
T("act_tribute", "action", "Tribute", "解放", "解放", "リリース", "릴리스", "Tribut",
  "Sacrifier", "Tributo", "Tributo", "Sacrificar", src=y("Tribute"))
T("act_discard", "action", "discard", "舍弃", "捨棄", "捨てる", "버리다", "abwerfen",
  "défausser", "scartare", "descartar", "descartar", src=y("Discard"))
T("act_draw", "action", "draw", "抽牌", "抽牌", "ドロー", "드로우", "ziehen", "piocher",
  "pescare", "comprar", "robar", src=y("Draw_a_card"))
T("act_place_counter", "action", "place a Counter", "放置计数物", "放置計數物",
  "カウンターを置く", "카운터를 놓다", "eine Zählmarke legen", "placer un compteur",
  "mettere un segnalino", "colocar um marcador", "poner un contador",
  conf="community", src=y("Counter"))
T("act_change_battle_position", "action", "change its battle position", "变更表示形式",
  "變更表示形式", "表示形式を変更する", None, "die Kampfposition ändern",
  "changer sa position de combat", "cambiare la sua posizione",
  "mudar sua posição de batalha", "cambiar su posición de batalla",
  conf="community", src=y("Battle_position"))
T("act_attack", "action", "attack", "攻击", "攻擊", "攻撃", "공격", "angreifen", "attaquer",
  "attaccare", "atacar", "atacar", src=y("Attack"))
T("act_direct_attack", "action", "attack directly", "直接攻击", "直接攻擊", "直接攻撃",
  "직접 공격", "direkt angreifen", "attaquer directement", "attaccare direttamente",
  "atacar diretamente", "atacar directamente", conf="community", src=y("Direct_attack"))
T("act_destroyed_by_battle", "action", "destroyed by battle", "被战斗破坏", "被戰鬥破壞",
  "戦闘で破壊される", "전투로 파괴되다", "durch Kampf zerstört",
  "détruit au combat", "distrutto in battaglia", "destruído em batalha",
  "destruido en batalla", conf="community")
T("act_piercing", "action", "inflict piercing battle damage", "给予穿刺战斗伤害",
  "給予貫通戰鬥傷害", "貫通ダメージを与える", None,
  "durchschlagenden Kampfschaden zufügen", "infliger des dommages de combat perçants",
  "infliggere danno da combattimento perforante",
  "causar dano de batalha perfurante", "infligir daño de batalla de penetración",
  src=y("Piercing"))
T("act_negate", "action", "negate", "无效", "無效", "無効", "무효", "annullieren", "annuler",
  "annullare", "negar", "negar", src=y("Negate"))
T("act_negate_activation", "action", "negate the activation", "发动无效", "發動無效",
  "発動を無効", None, "die Aktivierung annullieren", "annuler l'activation",
  "annullare l'attivazione", "negar a ativação", "negar la activación",
  conf="community", src=y("Negate"))
T("act_negate_effect", "action", "negate the effect / its effects are negated",
  "效果无效化", "效果無效化", "効果を無効にする", None, "den Effekt annullieren",
  "annuler l'effet", "annullare l'effetto", "negar o efeito", "negar el efecto",
  conf="community", src=y("Negate"))
T("act_target", "action", "target", "以…为对象", "以…為對象", "…を対象とする", "…을 대상으로 하다",
  "als Ziel wählen", "cibler", "scegliere come bersaglio", "escolher como alvo",
  "seleccionar como objetivo", src=y("Target"))
T("act_take_control", "action", "take control of", "获得控制权", "獲得控制權",
  "コントロールを得る", "컨트롤을 얻다", "die Kontrolle erhalten",
  "prendre le contrôle de", "prendere il controllo di", "tomar o controle de",
  "tomar el control de", conf="community", src=y("Control"))
T("act_copy", "action", "copy (a card name / effect)", "复制", "複製", "コピーする", None,
  "kopieren", "copier", "copiare", "copiar", "copiar", conf="community")
T("act_replace", "action", "instead / replace", "代替", "代替", "代わりに", None,
  "stattdessen", "à la place", "invece", "em vez disso", "en su lugar",
  conf="community")
T("act_flip_face_down", "action", "change to face-down (Set)", "变成里侧表示", "變成裏側表示",
  "裏側表示にする", None, "in die verdeckte Position bringen", "mettre face verso",
  "mettere coperta", "colocar com a face para baixo", "poner boca abajo",
  conf="community", src=y("Face-down"))
T("act_flip_face_up", "action", "flip face-up", "变成表侧表示", "變成表側表示",
  "表側表示にする", None, "aufdecken", "retourner face recto", "scoprire",
  "virar com a face para cima", "voltear boca arriba", conf="community",
  src=y("Face-up"))
T("act_shuffle", "action", "shuffle", "洗牌", "洗牌", "シャッフル", "셔플", "mischen",
  "mélanger", "mischiare", "embaralhar", "barajar", src=y("Shuffle"))
T("act_reveal", "action", "reveal", "公开", "公開", "公開する", None, "vorzeigen", "révéler",
  "rivelare", "revelar", "mostrar", src=y("Reveal"))
T("act_confirm", "action", "confirm / look at", "确认", "確認", "確認する", None,
  "bestätigen", "confirmer", "confermare", "confirmar", "confirmar",
  conf="community")
T("act_declare", "action", "declare", "宣言", "宣言", "宣言", "선언", "deklarieren",
  "déclarer", "dichiarare", "declarar", "declarar", src=y("Declare"))
T("act_gain", "action", "gain (ATK/DEF)", "上升", "上升", "アップする", None, "erhalten",
  "gagner", "guadagnare", "ganhar", "ganar", conf="community")
T("act_lose", "action", "lose (ATK/DEF)", "下降", "下降", "ダウンする", None, "verlieren",
  "perdre", "perdere", "perder", "perder", conf="community")
T("act_detach", "action", "detach", "去除", "去除", "取り除く", "제거", "abzuhängen",
  "détacher", "staccare", "desassociar", "desacoplar", src=y("Detach"))
T("act_attach", "action", "attach", "重叠", "重疊", "重ねる", None, "hängen", "attacher",
  "attaccare", "associar", "acoplar", src=y("Attach"))
T("act_pay_lp", "action", "pay Life Points", "支付LP", "支付LP", "ＬＰを払う", "LP를 지불한다",
  "LP bezahlen", "payer des LP", "pagare LP", "pagar PV", "pagar LP", src=y("Pay"))
T("act_control", "action", "control", "控制", "控制", "コントロール", "컨트롤", "kontrollieren",
  "contrôler", "controllare", "controlar", "controlar", src=y("Control"))
T("act_gain_this_effect", "action", "gain this effect (You can only gain this effect once per turn.)",
  "获得这个效果", "獲得這個效果", "この効果を得る", None, "diesen Effekt erhalten",
  "gagner cet effet", "guadagnare questo effetto", "ganhar este efeito",
  "ganar este efecto", conf="community", src=y("Once_per_turn"))

# ======================= ZONE (22) =======================
T("zone_deck", "zone", "Deck", "卡组", "牌組", "デッキ", "덱", "Deck", "Deck", "Deck",
  "Deck", "Deck", src=y("Main_Deck"))
T("zone_main_deck", "zone", "Main Deck", "主卡组", "主要牌組", "メインのデッキ", "메인 덱",
  "Main Deck", "Main Deck", "Main Deck", "Deck Principal", "Deck Principal",
  src=y("Main_Deck"))
T("zone_extra_deck", "zone", "Extra Deck", "额外卡组", "額外牌組", "ＥＸデッキ",
  "엑스트라 덱", "Extradeck", "Extra Deck", "Extra Deck", "Deck Adicional", "Deck Extra",
  src=y("Extra_Deck"))
T("zone_side_deck", "zone", "Side Deck", "副卡组", "備牌", "サイドデッキ", "사이드 덱",
  "Side Deck", "Side Deck", "Side Deck", "Deck Auxiliar", "Side Deck",
  src=y("Side_Deck"))
T("zone_hand", "zone", "hand", "手卡", "手牌", "手札", "패", "Hand", "main", "mano",
  "mão", "mano", src=y("Hand"))
T("zone_graveyard", "zone", "Graveyard", "墓地", "墓地", "墓地", "묘지", "Friedhof",
  "Cimetière", "Cimitero", "Cemitério", "Cementerio", src=y("Graveyard"))
T("zone_banished", "zone", "banished (cards) / banishment", "除外状态", "除外狀態",
  "除外状態", "제외", "Verbannte Karten", "Bannissement", "Carte bandite",
  "Banimento", "Destierro", conf="official", src=y("Banish"))
T("zone_field", "zone", "field", "场上", "場上", "フィールド", "필드", "Spielfeld",
  "Terrain", "Terreno", "campo", "Campo", src=y("Field"))
T("zone_monster_zone", "zone", "Monster Zone", "怪兽区域", "怪獸區", "モンスターゾーン",
  "몬스터 존", "Monsterzone", "Zone Monstre", "Zona Mostri", "Zona de Monstros",
  "Zona de Monstruos", src=y("Monster_Zone"))
T("zone_spell_trap_zone", "zone", "Spell & Trap Zone", "魔法与陷阱区域", "魔法＆陷阱區",
  "魔法＆罠ゾーン", "마법 & 함정 존", "Zauber- & Fallenzone", "Zone Magie & Piège",
  "Zona Magie & Trappole", "Zona de Magias & Armadilhas", "Zona de Magia y Trampas",
  src=y("Spell_%26_Trap_Zone"))
T("zone_pendulum_zone", "zone", "Pendulum Zone", "灵摆区域", "鐘擺區域", "Ｐゾーン",
  "펜듈럼 존", "Pendelzone", "Zone Pendule", "Zona Pendulum", "Zona de Pêndulo",
  "Zona de Péndulo", src=y("Pendulum_Zone"))
T("zone_field_zone", "zone", "Field Zone", "场地区域", "場地區", "フィールドゾーン",
  "필드 존", "Spielfeldzone", "Zone Terrain", "Zona Terreno", "Zona de Campo",
  "Zona de Campo", src=y("Field_Zone"))
T("zone_extra_monster_zone", "zone", "Extra Monster Zone", "额外怪兽区域", "額外怪獸區",
  "ＥＸモンスターゾーン", "엑스트라 몬스터 존", "Extra-Monsterzone", "Zone Monstre Extra",
  "Zona Mostro Extra", "Zona de Monstros Adicional", "Zona de Monstruos Extra",
  src=y("Extra_Monster_Zone"))
T("zone_main_monster_zone", "zone", "Main Monster Zone", "主要怪兽区域", "主要怪獸區",
  "メインモンスターゾーン", "메인 몬스터 존", "Main-Monsterzone", "Zone Monstre Main",
  "Zona Mostro Main", "Zona de Monstros Principal", "Zona de Monstruos Principal",
  src=y("Main_Monster_Zone"))
T("zone_draw_phase", "zone", "Draw Phase", "抽牌阶段", "抽牌階段", "ドローフェイズ",
  "드로우 페이즈", "Draw Phase", "Draw Phase", "Draw Phase", "Fase de Compra",
  "Draw Phase", src=y("Draw_Phase"))
T("zone_standby_phase", "zone", "Standby Phase", "准备阶段", "準備階段",
  "スタンバイフェイズ", "스탠바이 페이즈", "Standby Phase", "Standby Phase",
  "Standby Phase", "Fase de Apoio", "Standby Phase", src=y("Standby_Phase"))
T("zone_main_phase", "zone", "Main Phase", "主要阶段", "主要階段", "メインフェイズ",
  "메인 페이즈", "Main Phase", "Main Phase", "Main Phase", "Fase Principal",
  "Main Phase", src=y("Main_Phase"))
T("zone_battle_phase", "zone", "Battle Phase", "战斗阶段", "戰鬥階段", "バトルフェイズ",
  "배틀 페이즈", "Battle Phase", "Battle Phase", "Battle Phase", "Fase de Batalha",
  "Battle Phase", src=y("Battle_Phase"))
T("zone_end_phase", "zone", "End Phase", "结束阶段", "結束階段", "エンドフェイズ",
  "엔드 페이즈", "End Phase", "End Phase", "End Phase", "Fase Final", "End Phase",
  src=y("End_Phase"))
T("zone_battle_step", "zone", "Battle Step", "战斗步骤", "戰鬥步驟", "バトルステップ",
  "배틀 스텝", "Battle Step", "Battle Step", "Battle Step", "Etapa de Batalha",
  "Battle Step", src=y("Battle_Step"))
T("zone_damage_step", "zone", "Damage Step", "伤害步骤", "傷害步驟", "ダメージステップ",
  "데미지 스텝", "Damage Step", "Damage Step", "Damage Step", "Etapa de Dano",
  "Damage Step", src=y("Damage_Step"))
T("zone_damage_calculation", "zone", "damage calculation", "伤害计算", "傷害計算",
  "ダメージ計算", None, "Schadensberechnung", "calcul des dommages",
  "calcolo dei danni", "cálculo de dano", "cálculo de daño", conf="community")

# ======================= STAT (17) =======================
T("stat_atk", "stat", "ATK", "攻击力", "攻擊力", "攻撃力", "공격력", "ATK", "ATK", "ATK",
  "ATK", "ATK", src=y("ATK"))
T("stat_def", "stat", "DEF", "守备力", "守備力", "守備力", "수비력", "DEF", "DEF", "DEF",
  "DEF", "DEF", src=y("DEF"))
T("stat_level", "stat", "Level", "等级", "等級", "レベル", "레벨", "Stufe", "Niveau",
  "Livello", "Nível", "Nivel", src=y("Level"))
T("stat_rank", "stat", "Rank", "阶级", "階級", "ランク", "랭크", "Rang", "Rang", "Rango",
  "Classe", "Rango", src=y("Rank"))
T("stat_pendulum_scale", "stat", "Pendulum Scale", "灵摆刻度", None, "Ｐスケール",
  "펜듈럼 스케일", "Pendelbereich", "Échelle Pendule", "Valore Pendulum",
  "Escala de Pêndulo", "Escala de Péndulo", src=y("Pendulum_Scale"))
T("stat_link_rating", "stat", "Link Rating", "连接数值", "連結數值", "LINKの数値",
  "LINK 수치", "Linkbeschwörung", "Classification Lien", "Classificazione Link",
  "Valor Link", "Rating de Enlace", src=y("Link_Rating"))
T("stat_link_arrow", "stat", "Link Arrow / Link Marker", "连接标记", "連結符號",
  "リンクマーカー", "링크 마커", "Linkpfeil", "Flèche Lien", "Freccia Link",
  "Flecha Link", "Flecha de Enlace", src=y("Link_Arrow"))
T("stat_attribute", "stat", "Attribute", "属性", "屬性", "属性", "속성", "Eigenschaft",
  "Attribut", "Attributo", "Atributo", "Atributo", src=y("Attribute"))
T("stat_type", "stat", "Type (race)", "种族", "種族", "種族", "종족", "Typ", "Type",
  "Tipo", "Tipo", "Tipo", src=y("Type"))
T("stat_lp", "stat", "LP (Life Points)", "LP", "LP", "ＬＰ", "LP", "LP", "LP", "LP",
  "PV", "LP", src=y("LP"))
T("stat_battle_damage", "stat", "battle damage", "战斗伤害", "戰鬥傷害", "戦闘ダメージ",
  "전투 데미지", "Kampfschaden", "dommage de combat", "danno da combattimento",
  "dano de batalha", "daño de batalla", src=y("Battle_damage"))
T("stat_effect_damage", "stat", "effect damage", "效果伤害", "效果傷害", "効果ダメージ",
  "효과 데미지", "Effektschaden", "dommage d'effet", "danno da effetto",
  "dano de efeito", "daño de efecto", src=y("Effect_damage"))
T("stat_xys_material", "stat", "Xyz Material", "超量素材", "超量素材", "Ｘ素材",
  "엑시즈 소재", "Xyz-Material", "Matériel Xyz", "Materiale Xyz", "Matéria Xyz",
  "Material Xyz", src=y("Xyz_Material"))
T("stat_synchro_material", "stat", "Synchro Material", "同步素材", "同步素材", "Ｓ素材",
  "싱크로 소재", "Synchromaterial", "Matériel Synchro", "Materiale Synchro",
  "Matéria Sincro", "Material de Sincronía", src=y("Synchro_Material"))
T("stat_fusion_material", "stat", "Fusion Material", "融合素材", "融合素材", "融合素材",
  "융합 소재", "Fusionsmaterial", "Matériel Fusion", "Materiale da Fusione",
  "Matéria de Fusão", "Material de Fusión", src=y("Fusion_Material"))
T("stat_link_material", "stat", "Link Material", "连接素材", "連結素材", "Ｌ素材",
  "링크 소재", None, None, None, None, None, conf="official", src=y("Link_Material"))
T("stat_ritual_material", "stat", "Ritual Material", None, None, None, None, None,
  None, None, None, None, conf="unverified")

# ======================= PSCT PHRASE (60) =======================
# conf: "official" = Konami PSCT article / OCG-governed card-text template;
#       "community" = documented on Yugipedia / wiki-rulebook Chinese text, not verbatim Konami TCG copy.
def P(key, en, zh_cn=None, zh_tw=None, ja=None, ko=None, de=None, fr=None,
      it=None, pt=None, es=None, conf="official", src=None):
    T(key, "psct_phrase", en, zh_cn, zh_tw, ja, ko, de, fr, it, pt, es, conf, src)

P("psct_once_per_turn", "once per turn", "1回合1次", "1回合1次", "１ターンに１度",
  "1턴에 1번", "einmal pro Spielzug", "une fois par tour", "una volta per turno",
  "uma vez por turno", "una vez por turno", src=y("Once_per_turn"))
P("psct_once_per_turn_colon", "Once per turn:", "1回合1次，", "1回合1次，",
  "１ターンに１度、", "1턴에 1번,", "Einmal pro Spielzug:", "Une fois par tour :",
  "Una volta per turno:", "Uma vez por turno:", "Una vez por turno:",
  conf="community", src=y("Once_per_turn"))
P("psct_hopt_name_each", 'You can only use each effect of "X" once per turn.',
  "这个卡名的①②的效果1回合各能使用1次。", "這個卡名的①②的效果1回合各能使用1次。",
  "このカード名の①②の効果はそれぞれ１ターンに１度しか使用できない。",
  "이 카드명의 ①②의 효과는 각각 1턴에 1번밖에 사용할 수 없다.",
  "Du kannst jeden Effekt von „X“ nur einmal pro Spielzug verwenden.",
  "Vous ne pouvez utiliser chaque effet de \"X\" qu'une fois par tour.",
  "Puoi utilizzare ogni effetto di \"X\" una sola volta per turno.",
  "Você só pode usar cada efeito de \"X\" uma vez por turno.",
  "Sólo puedes usar cada efecto de \"X\" una vez por turno.",
  conf="community", src=y("Problem-Solving_Card_Text"))
P("psct_hopt_name_this", 'You can only use this effect of "X" once per turn.',
  "这个卡名的①的效果1回合只能使用1次。", "這個卡名的①的效果1回合只能使用1次。",
  "このカード名の①の効果は１ターンに１度しか使用できない。",
  "이 카드명의 ①의 효과는 1턴에 1번밖에 사용할 수 없다.",
  "Du kannst diesen Effekt von „X“ nur einmal pro Spielzug verwenden.",
  "Vous ne pouvez utiliser cet effet de \"X\" qu'une fois par tour.",
  "Puoi utilizzare questo effetto di \"X\" una sola volta per turno.",
  "Você só pode usar este efeito de \"X\" uma vez por turno.",
  "Sólo puedes usar este efecto de \"X\" una vez por turno.",
  conf="community", src=y("Once_per_turn"))
P("psct_hopt_name_activate", 'You can only activate 1 "X" per turn.',
  "「X」1回合只能发动1张。", "「X」1回合只能發動1張。",
  "「X」は１ターンに１枚しか発動できない。",
  "「X」는 1턴에 1장밖에 발동할 수 없다.",
  "Du kannst nur 1 „X“ pro Spielzug aktivieren.",
  "Vous ne pouvez activer qu'1 \"X\" par tour.",
  "Puoi attivare solo 1 \"X\" per turno.",
  "Você só pode ativar 1 \"X\" por turno.",
  "Sólo puedes activar 1 \"X\" por turno.",
  conf="community", src=y("Once_per_turn"))
P("psct_hopt_name_apply", 'You can only apply this effect of "X" once per Duel.',
  "这个卡名的效果1场决斗中只能适用1次。", "這個卡名的效果1場決鬥中只能適用1次。",
  "このカード名の効果はデュエル中に１度しか適用できない。",
  None, None, None, None, None, None, conf="official", src=y("Once_per_turn"))
P("psct_hopt_gain_once", "(You can only gain this effect once per turn.)",
  "（这个效果1回合只能获得1次。）", "（這個效果1回合只能獲得1次。）",
  "（この効果は１ターンに１度しか得られない。）", None,
  "(Du kannst diesen Effekt nur einmal pro Spielzug erhalten.)",
  "(Vous ne pouvez gagner cet effet qu'une fois par tour.)",
  "(Puoi guadagnare questo effetto una sola volta per turno.)",
  "(Você só pode ganhar este efeito uma vez por turno.)",
  "(Sólo puedes ganar este efecto una vez por turno.)",
  conf="community", src=y("Once_per_turn"))
P("psct_when_you_can", "When ...: You can ...", "…时才能发动。", "…時才能發動。",
  "…時、…できる。", "…때 발동할 수 있다.", "Wenn ...: Du kannst ...",
  "Lorsque ... : Vous pouvez ...", "Quando ...: Puoi ...",
  "Quando ...: Você pode ...", "Cuando ...: Puedes ...",
  conf="community", src=SRC["psct3"])
P("psct_if_you_can", "If ...: You can ...", "…的场合才能发动。", "…的場合才能發動。",
  "…場合、…できる。", "…경우에 발동할 수 있다.", "Falls ...: Du kannst ...",
  "Si ... : Vous pouvez ...", "Se ...: Puoi ...", "Se ...: Você pode ...",
  "Si ...: Puedes ...", conf="community", src=y("Problem-Solving_Card_Text"))
P("psct_when_mandatory", "When ..., ... (mandatory)", "…时，…。", "…時，…。",
  "…時、…。", "…때, ….", "Wenn ..., ...", "Lorsque ..., ...", "Quando ..., ...",
  "Quando ..., ...", "Cuando ..., ...", conf="community", src=y("Problem-Solving_Card_Text"))
P("psct_if_mandatory", "If ..., ... (mandatory)", "…的场合，…。", "…的場合，…。",
  "…場合、…。", "…경우, ….", "Falls ..., ...", "Si ..., ...", "Se ..., ...",
  "Se ..., ...", "Si ..., ...", conf="community", src=y("Problem-Solving_Card_Text"))
P("psct_target_cost", "target ...; ...", "以…为对象才能发动。…", "以…為對象才能發動。…",
  "…を対象として発動できる。…", "…을 대상으로 하여 발동할 수 있다. …",
  "... als Ziel wählen; ...", "ciblez ... ; ...", "scegli come bersaglio ...; ...",
  "escolha ... como alvo; ...", "selecciona ... como objetivo; ...",
  conf="community", src=SRC["psct3"])
P("psct_tribute_cost", "Tribute ...; ...", "把…解放才能发动。…", "把…解放才能發動。…",
  "…をリリースして発動できる。…", "…을 릴리스하고 발동할 수 있다. …",
  "... als Tribut anbieten; ...", "Sacrifiez ... ; ...", "offri come Tributo ...; ...",
  "ofereça como Tributo ...; ...", "Sacrifica ...; ...",
  conf="community", src=SRC["psct3"])
P("psct_send_cost", "Send ... to the Graveyard; ...", "把…送去墓地才能发动。…",
  "把…送去墓地才能發動。…", "…を墓地へ送って発動できる。…",
  "…을 묘지로 보내고 발동할 수 있다. …", "... auf den Friedhof legen; ...",
  "envoyez ... au Cimetière ; ...", "manda ... al Cimitero; ...",
  "envie ... para o Cemitério; ...", "manda ... al Cementerio; ...",
  conf="community", src=SRC["psct3"])
P("psct_discard_cost", "Discard ...; ...", "把…舍弃才能发动。…", "把…捨棄才能發動。…",
  "…を捨てて発動できる。…", "…을 버리고 발동할 수 있다. …", "... abwerfen; ...",
  "défaussez ... ; ...", "scarta ...; ...", "descarte ...; ...", "descarta ...; ...",
  conf="community", src=SRC["psct3"])
P("psct_pay_lp_cost", "Pay ... LP; ...", "支付…LP才能发动。…", "支付…LP才能發動。…",
  "…ＬＰを払って発動できる。…", "…LP를 지불하고 발동할 수 있다. …",
  "... LP bezahlen; ...", "payez ... LP ; ...", "paga ... LP; ...",
  "pague ... PV; ...", "paga ... LP; ...", conf="community", src=SRC["psct3"])
P("psct_search_deck", "Add 1 ... from your Deck to your hand.", "从卡组把1张…加入手卡。",
  "從牌組將1張…加入手牌。", "デッキから…１枚を手札に加える。",
  "덱에서 … 1장을 패에 넣는다.", "Füge deiner Hand 1 ... von deinem Deck hinzu.",
  "Ajoutez 1 ... depuis votre Deck à votre main.",
  "Aggiungi 1 ... dal tuo Deck alla tua mano.",
  "Adicione 1 ... do seu Deck à sua mão.", "Añade 1 ... de tu Deck a tu mano.",
  conf="community", src=y("Add_a_card"))
P("psct_special_summon_deck", "Special Summon 1 ... from your Deck.",
  "从卡组把1只…特殊召唤。", "從牌組將1隻…特殊召喚。",
  "デッキから…１体を特殊召喚する。", "덱에서 … 1장을 특수 소환한다.",
  "Beschwöre 1 ... als Spezialbeschwörung von deinem Deck.",
  "Invoquez Spécialement 1 ... depuis votre Deck.",
  "Evoca Specialmente 1 ... dal tuo Deck.",
  "Invoque por Invocação-Especial 1 ... do seu Deck.",
  "Invoca de Modo Especial 1 ... desde tu Deck.", conf="community",
  src=y("Special_Summon"))
P("psct_send_to_gy", "Send 1 ... from your Deck to the Graveyard.",
  "从卡组把1张…送去墓地。", "從牌組將1張…送去墓地。",
  "デッキから…１枚を墓地へ送る。", "덱에서 … 1장을 묘지로 보낸다.",
  "Lege 1 ... von deinem Deck auf den Friedhof.",
  "Envoyez 1 ... depuis votre Deck au Cimetière.",
  "Manda 1 ... dal tuo Deck al Cimitero.",
  "Envie 1 ... do seu Deck para o Cemitério.",
  "Manda 1 ... de tu Deck al Cementerio.", conf="community", src=y("Send"))
P("psct_destroy", "Destroy ...", "破坏…", "破壞…", "…を破壊する。", "…을 파괴한다.",
  "Zerstöre ...", "Détruisez ...", "Distruggi ...", "Destrua ...", "Destruye ...",
  conf="community", src=y("Destroy"))
P("psct_banish", "Banish ...", "把…除外", "把…除外", "…を除外する。", "…을 제외한다.",
  "Verbanne ...", "Bannissez ...", "Bandisci ...", "Bana ...", "Destierra ...",
  conf="community", src=y("Banish"))
P("psct_return_to_hand", "Return ... to the hand.", "…回到手卡。", "…回到手牌。",
  "…を手札に戻す。", "…을 패로 되돌린다.", "Gib ... auf die Hand zurück.",
  "Renvoyez ... dans la main.", "Fai ritornare ... nella mano.",
  "Devolva ... para a mão.", "Devuelve ... a la mano.", conf="community",
  src=y("Return"))
P("psct_return_to_deck", "Return ... to the Deck.", "…回到卡组。", "…回到牌組。",
  "…をデッキに戻す。", "…을 덱으로 되돌린다.", "Lege ... ins Deck zurück.",
  "Renvoyez ... dans le Deck.", "Fai ritornare ... nel Deck.",
  "Devolva ... para o Deck.", "Devuelve ... al Deck.", conf="community",
  src=y("Return"))
P("psct_negate_activation", "negate the activation, and if you do, destroy it",
  "那个发动无效并破坏", "那個發動無效並破壞", "その発動を無効にし破壊する。",
  "그 발동을 무효로 하고 파괴한다.", "annulliere die Aktivierung und zerstöre sie",
  "annulez l'activation, et si vous le faites, détruisez-la",
  "annulla l'attivazione e, se lo fai, distruggila",
  "negue a ativação e, se isso acontecer, destrua-o",
  "niega la activación y, si lo haces, destrúyelo", conf="community",
  src=y("Problem-Solving_Card_Text"))
P("psct_cannot_be_used_as_material", 'Cannot be used as material for a ... Summon.',
  "不能作为…召唤的素材。", "不能作為…召喚的素材。",
  "…召喚の素材にできない。", "…소환의 소재로 할 수 없다.",
  "Kann nicht als Material für eine ... Beschwörung verwendet werden.",
  "Ne peut pas être utilisé comme Matériel pour une Invocation ...",
  "Non può essere utilizzato come Materiale per un'Evocazione ...",
  "Não pode ser usado como Matéria para uma Invocação ...",
  "No puede ser usado como Material para una Invocación ...",
  conf="community", src=y("Problem-Solving_Card_Text"))
P("psct_cannot_be_normal_summoned", "Cannot be Normal Summoned/Set.",
  "这张卡不能通常召唤。", "此卡不能通常召喚。", "このカードは通常召喚できない。",
  "이 카드는 통상 소환할 수 없다.", "Kann nicht als Normalbeschwörung beschworen/gesetzt werden.",
  "Ne peut pas être Invoqué/Posé Normalement.",
  "Non può essere Evocato Normalmente/Posizionato.",
  "Não pode ser Invocado/Colocado por Invocação-Normal.",
  "No puede ser Invocado/Colocado de Modo Normal.", conf="community",
  src=y("Special_Summon_Monster"))
P("psct_must_first_be_special_summoned", "Must first be Special Summoned (from your hand) by ...",
  "这张卡不能通常召唤，…才能特殊召唤。", "此卡不能通常召喚，…才能特殊召喚。",
  "このカードは通常召喚できず、…ことで特殊召喚できる。",
  "이 카드는 통상 소환할 수 없으며, …로 특수 소환할 수 있다.",
  "Muss zuerst als Spezialbeschwörung (von deiner Hand) beschworen werden durch ...",
  "Doit d'abord être Invoqué Spécialement (depuis votre main) par ...",
  "Deve prima essere Evocato Specialmente (dalla tua mano) tramite ...",
  "Deve primeiro ser Invocado por Invocação-Especial (da sua mão) por ...",
  "Debe ser Invocado de Modo Especial (desde tu mano) por ...",
  conf="community", src=y("Problem-Solving_Card_Text"))
P("psct_each_of_these_effects", "Apply 1 of these effects.", "选择1个效果适用。",
  "選擇1個效果適用。", "以下の効果から１つを適用する。", None,
  "Wende 1 dieser Effekte an.", "Appliquez 1 de ces effets.",
  "Applica 1 di questi effetti.", "Aplique 1 destes efeitos.",
  "Aplica 1 de estos efectos.", conf="community")
P("psct_the_previous_effect", "All of the above / the preceding effect", "以上全部", "以上全部",
  "以上全て", None, "Alle oben genannten", "Tout ce qui précède",
  "Tutto quanto sopra", "Todos os acima", "Todo lo anterior", conf="community")
P("psct_and", "and", "并且", "並且", "し", "그리고", "und", "et", "e", "e", "y",
  conf="official", src=SRC["psct7"])
P("psct_then", "then", "那之后", "那之後", "その後", "그 후", "dann", "puis", "poi",
  "depois", "después", conf="official", src=SRC["psct7"])
P("psct_also", "also", "此外", "此外", "また", "또한", "außerdem", "aussi", "inoltre",
  "também", "también", conf="official", src=SRC["psct7"])
P("psct_and_if_you_do", "and if you do", "那个场合", "那個場合", "その場合", "그 경우",
  "und falls du dies tust", "et si vous le faites", "e, se lo fai",
  "e, se isso acontecer", "y, si lo haces", conf="official", src=SRC["psct7"])
P("psct_also_after_that", "also, after that", "此外，那之后", "此外，那之後",
  "また、その後", "또한, 그 후", "außerdem, danach", "aussi, après cela",
  "inoltre, dopodiché", "também, depois disso", "también, después de eso",
  conf="official", src=y("Problem-Solving_Card_Text"))
P("psct_in_sequence", "(in sequence)", "（按顺序）", "（按順序）", "（順番に）", None,
  "(in Reihenfolge)", "(dans l'ordre)", "(in ordine)", "(em sequência)",
  "(en secuencia)", conf="official")
P("psct_simultaneously", "(simultaneously)", "（同时）", "（同時）", "（同時に）", None,
  "(gleichzeitig)", "(simultanément)", "(simultaneamente)", "(simultaneamente)",
  "(simultáneamente)", conf="official")
P("psct_targeting_ref", "that target / those targets", "那个对象", "那個對象",
  "その対象", None, "jenes Ziel", "cette cible", "quel bersaglio", "aquele alvo",
  "ese objetivo", conf="official", src=y("Problem-Solving_Card_Text"))
P("psct_it_ref", "it / they", "那张卡", "那張卡", "それ", None, "es", "il", "esso",
  "ele", "él", conf="official", src=y("Problem-Solving_Card_Text"))
P("psct_during_either_players", "During either player's turn", "在对方回合也能发动",
  "在對方回合也能發動", "相手ターンでも発動できる", None, "Während des Spielzugs eines beliebigen Spielers",
  "Durant le tour de chaque joueur", "Durante il turno di qualsiasi giocatore",
  "Durante o turno de qualquer duelista", "Durante el turno de cualquier jugador",
  conf="official", src=y("Quick_Effect"))
P("psct_quick_effect", "(Quick Effect)", "（这个效果在对方回合也能发动）",
  "（這個效果在對方回合也能發動）", "（この効果は相手ターンでも発動できる）", None,
  "(Schnelleffekt)", "(Effet Rapide)", "(Effetto Rapido)", "(Efeito Rápido)",
  "(Efecto Rápido)", conf="community", src=y("Quick_Effect"))
P("psct_neither_player_can_activate", "Neither player can activate cards or effects in response to this effect's activation.",
  "这个效果的发动，双方不能发动卡的效果。", "這個效果的發動，雙方不能發動卡的效果。",
  "この効果の発動に対して、お互いはカードの効果を発動できない。", None,
  "Kein Spieler kann Karten oder Effekte als Reaktion auf die Aktivierung dieses Effekts aktivieren.",
  "Aucun joueur ne peut activer de cartes ou d'effets en réponse à l'activation de cet effet.",
  "Nessun giocatore può attivare carte o effetti in risposta all'attivazione di questo effetto.",
  "Nenhum duelista pode ativar cards ou efeitos em resposta à ativação deste efeito.",
  "Ningún jugador puede activar cartas o efectos en respuesta a la activación de este efecto.",
  conf="community", src=y("Problem-Solving_Card_Text"))
P("psct_while_face_up_on_field", "Once while face-up on the field: ...",
  "这张卡在怪兽区域表侧表示存在的场合，1次…", "此卡在怪獸區表側表示存在的場合，1次…",
  "このカードがモンスターゾーンに表側表示で存在する場合に１度、…", None,
  "Einmal, solange diese Karte offen auf dem Spielfeld liegt: ...",
  "Une fois tant que cette carte est face recto sur le Terrain : ...",
  "Una volta mentre questa carta è scoperta sul Terreno: ...",
  "Uma vez enquanto este card estiver com a face para cima no campo: ...",
  "Una vez mientras esta carta esté boca arriba en el Campo: ...",
  conf="community", src=y("Problem-Solving_Card_Text"))
P("psct_if_only_your_opponent_controls", "If only your opponent controls a monster",
  "对方场上只有怪兽存在的场合", "對方場上只有怪獸存在的場合",
  "相手フィールドにのみモンスターが存在する場合", None,
  "Falls nur dein Gegner ein Monster kontrolliert",
  "Si seulement votre adversaire contrôle un monstre",
  "Se solo il tuo avversario controlla un mostro",
  "Se apenas seu oponente controlar um monstro",
  "Si sólo tu adversario controla un monstruo", conf="community",
  src=y("Problem-Solving_Card_Text"))
P("psct_you_can_only_use", "You can only use ... once per turn.", "1回合只能使用1次",
  "1回合只能使用1次", "１ターンに１度しか使用できない", "1턴에 1번밖에 사용할 수 없다",
  "Du kannst ... nur einmal pro Spielzug verwenden.",
  "Vous ne pouvez utiliser ... qu'une fois par tour.",
  "Puoi utilizzare ... una sola volta per turno.",
  "Você só pode usar ... uma vez por turno.",
  "Sólo puedes usar ... una vez por turno.", conf="community", src=y("Once_per_turn"))
P("psct_activate_only", "You can only activate ... once per turn.", "1回合只能发动1次",
  "1回合只能發動1次", "１ターンに１度しか発動できない", "1턴에 1번밖에 발동할 수 없다",
  "Du kannst ... nur einmal pro Spielzug aktivieren.",
  "Vous ne pouvez activer ... qu'une fois par tour.",
  "Puoi attivare ... una sola volta per turno.",
  "Você só pode ativar ... uma vez por turno.",
  "Sólo puedes activar ... una vez por turno.", conf="community", src=y("Once_per_turn"))
P("psct_cannot_activate", "Cannot be activated.", "不能发动", "不能發動", "発動できない",
  "발동할 수 없다", "Kann nicht aktiviert werden.", "Ne peut pas être activé.",
  "Non può essere attivato.", "Não pode ser ativado.", "No puede ser activado.",
  conf="community")
P("psct_this_effect_cannot_be_negated", "The activation and effect of this effect cannot be negated.",
  "这个效果的发动和效果不会被无效化。", "這個效果的發動和效果不會被無效化。",
  "この効果の発動と効果は無効化されない。", None,
  "Die Aktivierung und der Effekt dieses Effekts können nicht annulliert werden.",
  "L'activation et l'effet de cet effet ne peuvent pas être annulés.",
  "L'attivazione e l'effetto di questo effetto non possono essere annullati.",
  "A ativação e o efeito deste efeito não podem ser negados.",
  "La activación y el efecto de este efecto no pueden ser negados.",
  conf="community")
P("psct_this_card_name_becomes", "This card's name becomes \"X\" while ...",
  "这张卡的卡名当作「X」使用。", "此卡的卡名當作「X」使用。",
  "このカードのカード名は…の間「X」として扱う。", None,
  "Der Name dieser Karte wird zu „X“, solange ...",
  "Le nom de cette carte devient \"X\" tant que ...",
  "Il nome di questa carta diventa \"X\" mentre ...",
  "O nome deste card se torna \"X\" enquanto ...",
  "El nombre de esta carta se convierte en \"X\" mientras ...",
  conf="community", src=y("Problem-Solving_Card_Text"))
P("psct_always_treated_as", "(This card is always treated as a \"X\" card.)",
  "（这张卡也当作「X」卡使用。）", "（此卡也當作「X」卡使用。）",
  "（このカードは「X」カードとしても扱う。）", None,
  "(Diese Karte wird immer als „X“-Karte behandelt.)",
  "(Cette carte est toujours traitée comme une carte \"X\".)",
  "(Questa carta viene sempre considerata come una carta \"X\".)",
  "(Este card é sempre tratado como um card \"X\".)",
  "(Esta carta se trata siempre como una carta \"X\".)",
  conf="community", src=y("Problem-Solving_Card_Text"))
P("psct_if_you_do_not_control", "If you do not control ...", "自己场上没有…的场合",
  "自己場上沒有…的場合", "自分フィールドに…が存在しない場合", None,
  "Falls du ... nicht kontrollierst", "Si vous ne contrôlez pas ...",
  "Se non controlli ...", "Se você não controlar ...", "Si no controlas ...",
  conf="community")
P("psct_once_per_duel", "once per Duel", "1场决斗1次", "1場決鬥1次",
  "１デュエルに１度", "1 duel에 1번", "einmal pro Duell", "une fois par Duel",
  "una volta per Duello", "uma vez por Duelo", "una vez por Duelo",
  src=y("Once_per_turn"))
P("psct_until_end_of_turn", "(until the end of this turn)", "（直到回合结束时）",
  "（直到回合結束時）", "（ターン終了時まで）", None, "(bis zum Ende dieses Spielzugs)",
  "(jusqu'à la fin de ce tour)", "(fino alla fine di questo turno)",
  "(até o final deste turno)", "(hasta el final de este turno)", conf="official",
  src=y("Problem-Solving_Card_Text"))
P("psct_until_end_phase", "until the End Phase", "直到结束阶段", "直到結束階段",
  "エンドフェイズまで", "엔드 페이즈까지", "bis zur End Phase",
  "jusqu'à la End Phase", "fino alla End Phase", "até a Fase Final",
  "hasta la End Phase", conf="community", src=y("End_Phase"))
P("psct_immediately_after_resolves", "Immediately after this effect resolves, ...",
  "这个效果处理后再…", "這個效果處理後再…", "この効果の処理後に…",
  "이 효과의 처리를 하고 …", "Sofort nachdem dieser Effekt aufgelöst wurde, ...",
  "Immédiatement après la résolution de cet effet, ...",
  "Immediatamente dopo che questo effetto si è risolto, ...",
  "Imediatamente depois que este efeito resolver, ...",
  "Inmediatamente después de que se resuelva este efecto, ...",
  conf="community", src=y("Problem-Solving_Card_Text"))
P("psct_its_effects_are_negated", "its effects are negated", "那个效果无效化",
  "那個效果無效化", "その効果は無効化される", None, "seine Effekte werden annulliert",
  "ses effets sont annulés", "i suoi effetti sono annullati",
  "seus efeitos são negados", "sus efectos son negados", conf="community",
  src=y("Problem-Solving_Card_Text"))
P("psct_loses_the_timing", "loses the timing / misses the timing", "错过时机",
  "錯過時機", "タイミングを逃す", None, "verpasst den Zeitpunkt",
  "manque le timing", "perde il momento", "perde o timing",
  "pierde el momento", conf="community")
P("psct_cost", "cost", "费用", "費用", "コスト", "코스트", "Kosten", "Coût", "Costo",
  "Custo", "Coste", src=y("Cost"))
P("psct_activation_condition", "activation condition / activation requirement",
  "发动条件", "發動條件", "発動条件", None, "Aktivierungsbedingung",
  "condition d'activation", "condizione di attivazione",
  "condição de ativação", "condición de activación", src=y("Activation_condition"))
P("psct_condition", "condition", "条件", "條件", "条件", None, "Bedingung", "condition",
  "condizione", "condição", "condición", conf="community")
P("psct_spell_speed", "Spell Speed", "咒文速度", "咒文速度", "スペルスピード",
  "스펠 스피드", "Zaubergeschwindigkeit", "Spell Speed", "Spell Speed",
  "Velocidade de Magia", "Velocidad de Hechizo", src=y("Spell_Speed"))
P("psct_chain_link", "Chain Link", "连锁", "連鎖", "チェーン", "체인", "Kettenglied",
  "Chaîne", "Anello (della Catena)", "Elo da Corrente", "Eslabón (de Cadena)",
  conf="community", src=y("Chain_Link"))
P("psct_summoning_condition", "Summoning condition", "召唤条件", "召喚條件",
  "召喚条件", None, "Beschwörungsbedingung", "condition d'Invocation",
  "condizione di Evocazione", "condição de Invocação",
  "condición de Invocación", conf="community", src=y("Special_Summon_Monster"))

# ---------------------------------------------------------------------------
# Build terms.json
# ---------------------------------------------------------------------------
assert len(ROWS) >= 160, len(ROWS)
keys = [r["key"] for r in ROWS]
assert len(keys) == len(set(keys)), [k for k in keys if keys.count(k) > 1]

terms = OrderedDict()
for r in ROWS:
    d = OrderedDict()
    d["key"] = r["key"]
    d["en"] = r["en"]
    d["zh_cn"] = r["zh_cn"]
    d["zh_tw"] = r["zh_tw"]
    d["ja"] = r["ja"]
    d["ko"] = r["ko"]
    d["de"] = r["de"]
    d["fr"] = r["fr"]
    d["it"] = r["it"]
    d["pt"] = r["pt"]
    d["es"] = r["es"]
    d["category"] = r["category"]
    d["confidence"] = r["confidence"]
    if r.get("source"):
        d["source"] = r["source"]
    terms[r["key"]] = d

# Coverage stats
cats = {}
for d in terms.values():
    cats[d["category"]] = cats.get(d["category"], 0) + 1
nulls = {}
for lang in LANG_KEYS:
    nulls[lang] = sum(1 for d in terms.values() if d.get(lang) is None)

meta = OrderedDict()
meta["generated"] = GENERATED
meta["note"] = ("官方简中译名以 db.yugioh-card-cn.com 为准；zh_cn 采用官方卡片数据库筛选器用词"
                "（种族一律带「族」字后缀，如 魔法师族/电子界族）。"
                "zh_tw 采用台湾/香港繁体官方用词。"
                "EN/JA 效果文句以 Konami PSCT 官方文章与 OCG 标准卡片文本格式为准。")
meta["sources"] = [DB_CN] + [SRC[k] for k in
    ["psct1", "psct2", "psct3", "psct4", "psct5", "psct6", "psct7",
     "ygo_psct", "ygo_hopt", "ygo_hopt_only", "ygo_actcond", "ygo_cost",
     "ygo_quick", "ygo_cardtext", "ygo_monster_card"]]
meta["source_index"] = OrderedDict(sorted(SRC.items()))
meta["total_terms"] = len(terms)
meta["by_category"] = OrderedDict(sorted(cats.items()))
meta["null_counts"] = OrderedDict((k, nulls[k]) for k in LANG_KEYS)
meta["coverage_note"] = ("null = 未在权威来源中找到官方译名，未做推测。"
                         "详见 README.md 的覆盖率统计与缺口清单。")

terms_doc = OrderedDict()
terms_doc["_meta"] = meta
terms_doc["terms"] = terms

with open(os.path.join(OUT, "terms.json"), "w", encoding="utf-8") as f:
    json.dump(terms_doc, f, ensure_ascii=False, indent=2)
    f.write("\n")

# ---------------------------------------------------------------------------
# Build psct_patterns.json
# ---------------------------------------------------------------------------
def conj(key, en, ja, zh_cn, zh_tw, order, both, seq_note, official_src):
    return OrderedDict([
        ("key", key), ("en", en), ("ja", ja), ("zh_cn", zh_cn), ("zh_tw", zh_tw),
        ("resolution_order", order), ("both_required", both),
        ("requires_a_for_b", key in ("then", "and_if_you_do")),
        ("aborts_b_if_a_fails", key in ("then", "and_if_you_do")),
        ("note", seq_note), ("source", official_src),
    ])

punctuation = [
    OrderedDict([("symbol", "："), ("role", "condition_separator"), ("en", ":"),
                 ("ja", "："), ("zh_cn", "："), ("zh_tw", "："),
                 ("position", "before"),
                 ("note", "冒号前是发动条件（何时/如何/多少次能发动）；有冒号或分号即入连锁。有条件时小写 when/if 引导。"),
                 ("source", SRC["psct3"])]),
    OrderedDict([("symbol", "；"), ("role", "activation_separator"), ("en", ";"),
                 ("ja", "；"), ("zh_cn", "；"), ("zh_tw", "；"),
                 ("position", "between"),
                 ("note", "分号前（冒号之后）是发动时要做的事：cost 与 target。分号后是效果处理（resolution）。"),
                 ("source", SRC["psct3"])]),
    OrderedDict([("symbol", "。"), ("role", "sentence_terminator"), ("en", "."),
                 ("ja", "。"), ("zh_cn", "。"), ("zh_tw", "。"),
                 ("position", "after"),
                 ("note", "句号只是句子边界，不代表入连锁。真正判定入连锁的标记是「：」或「；」。"),
                 ("source", SRC["psct3"])]),
    OrderedDict([("symbol", "（）"), ("role", "built_in_special_summon"), ("en", "()"),
                 ("ja", "（）"), ("zh_cn", "（）"), ("zh_tw", "（）"),
                 ("position", "inline"),
                 ("note", "括号标注 Built-In Special Summon 的召唤来源，如「（从手卡）」/“(from your hand)”。"),
                 ("source", "https://www.yugioh-card.com/en/play/psct/psct-5/")]),
    OrderedDict([("symbol", "●"), ("role", "bulleted_effect"), ("en", "●"),
                 ("ja", "●"), ("zh_cn", "●"), ("zh_tw", "●"),
                 ("position", "inline"),
                 ("note", "同一连锁内处理的分支效果。写「按顺序」= 依次处理；写「（同时）」= 同时处理；两者都没写 = 各自另开连锁。"),
                 ("source", y("Problem-Solving_Card_Text"))]),
    OrderedDict([("symbol", "①"), ("role", "effect_number"), ("en", "①"),
                 ("ja", "①"), ("zh_cn", "①"), ("zh_tw", "①"),
                 ("position", "prefix"),
                 ("note", "OCG 自 Starter Deck 2014 起为每个效果编号；编号本身不是效果文的一部分，但「这个卡名的①②效果」句式依赖编号。"),
                 ("source", y("Card_text"))]),
]

conjunctions = [
    conj("and", "and", "し", "并且", "並且", "simultaneous", True,
         "同时处理，A 与 B 都必须执行；两者任一做不到就整段都不做（全有或全无）。",
         SRC["psct7"]),
    conj("then", "then", "その後", "那之后", "那之後", "sequential", False,
         "依次处理，B 在 A 之后。A 是 B 的前提，反之不然：A 没做成则停止；B 做不成就只做 A。",
         SRC["psct7"]),
    conj("also", "also", "また", "此外", "此外", "simultaneous", False,
         "视为同时处理。互不为前提，能做到多少做多少。",
         SRC["psct7"]),
    conj("and_if_you_do", "and if you do", "その場合", "那个场合", "那個場合",
         "simultaneous", True,
         "时间轴上等同 and（同时），因果上等同 then（A 是 B 的前提）。A 未发生则停止；B 做不成仍做 A。",
         SRC["psct7"]),
    conj("also_after_that", "also, after that", "また、その後", "此外，那之后", "此外，那之後",
         "sequential", False,
         "依次处理，B 在 A 之后。互不为前提（2014 年新增，未见于 PSCT 原始连载）。",
         y("Problem-Solving_Card_Text")),
]

hopt = [
    OrderedDict([
        ("key", "once_per_turn"),
        ("en", "Once per turn:"),
        ("ja", "１ターンに１度、"),
        ("zh_cn", "1回合1次，"),
        ("zh_tw", "1回合1次，"),
        ("scope", "this_card"),
        ("scope_note", "限制作用于「这一张卡」在当前所在位置（整个场上视为同一位置）。同名不同卡各自可用。"),
        ("strictness", "activate"),
        ("strictness_note", "等同 activate：发动被无效也不可再次发动。"),
        ("reset_on_leave", True),
        ("reset_note", "该卡离开当前所在位置或被翻成里侧表示后，同一回合可以再次发动。"),
        ("placement", "activation_condition"),
        ("placement_note", "写在冒号之前的发动条件段落。"),
        ("source", SRC["ygo_hopt"]),
    ]),
    OrderedDict([
        ("key", "hopt_name_use"),
        ("en", 'You can only use each effect of "X" once per turn.'),
        ("ja", "このカード名の①②の効果はそれぞれ１ターンに１度しか使用できない。"),
        ("zh_cn", "这个卡名的①②的效果1回合各能使用1次。"),
        ("zh_tw", "這個卡名的①②的效果1回合各能使用1次。"),
        ("scope", "player_and_original_name"),
        ("scope_note", "限制作用于「玩家 + 卡名」，与具体是哪一张卡无关；卡名被改写也不解除限制。"),
        ("strictness", "use"),
        ("strictness_note", "最严格：即使发动被无效，本回合也不能再用。"),
        ("reset_on_leave", False),
        ("reset_note", "不会因离场/翻里侧重置。"),
        ("placement", "separate_sentence"),
        ("placement_note", "写在独立句子里（通常在效果文段之后另起一句），不出现在冒号前。"),
        ("variants", [
            'You can only use this effect of "X" once per turn.',
            'You can only use 1 "X" effect per turn, and only once that turn.',
            'You can only use each effect of "X" once per Duel.',
        ]),
        ("source", SRC["ygo_hopt"]),
    ]),
    OrderedDict([
        ("key", "hopt_name_activate"),
        ("en", 'You can only activate 1 "X" per turn.'),
        ("ja", "「X」は１ターンに１枚しか発動できない。"),
        ("zh_cn", "「X」1回合只能发动1张。"),
        ("zh_tw", "「X」1回合只能發動1張。"),
        ("scope", "player_and_original_name"),
        ("scope_note", "同样作用于玩家 + 卡名。"),
        ("strictness", "activate"),
        ("strictness_note", "比 use 宽松：若这次发动被无效，本回合还可以再发动另一张同名卡。"),
        ("reset_on_leave", False),
        ("placement", "separate_sentence"),
        ("source", SRC["ygo_hopt"]),
    ]),
    OrderedDict([
        ("key", "hopt_name_apply"),
        ("en", 'You can only apply this effect of "X" once per Duel.'),
        ("ja", "このカード名の効果はデュエル中に１度しか適用できない。"),
        ("zh_cn", "这个卡名的效果1场决斗中只能适用1次。"),
        ("zh_tw", "這個卡名的效果1場決鬥中只能適用1次。"),
        ("scope", "player_and_original_name"),
        ("strictness", "apply"),
        ("strictness_note", "最宽松的一档：效果被改写或无效后，之后仍可再次尝试。"),
        ("reset_on_leave", False),
        ("note", "strictness 由宽到严：apply < activate < use。"),
        ("source", SRC["ygo_hopt"]),
    ]),
    OrderedDict([
        ("key", "hopt_gain_effect_once"),
        ("en", "(You can only gain this effect once per turn.)"),
        ("ja", "（この効果は１ターンに１度しか得られない。）"),
        ("zh_cn", "（这个效果1回合只能获得1次。）"),
        ("zh_tw", "（這個效果1回合只能獲得1次。）"),
        ("scope", "player"),
        ("scope_note", "限制作用于玩家，与卡名、卡的种类都无关（例如追加通常召唤类效果）。"),
        ("strictness", "gain"),
        ("reset_on_leave", False),
        ("source", SRC["ygo_hopt"]),
    ]),
    OrderedDict([
        ("key", "hopt_once_while_face_up"),
        ("en", "Once while face-up on the field: ..."),
        ("ja", "このカードがモンスターゾーンに表側表示で存在する場合に１度、…"),
        ("zh_cn", "这张卡在怪兽区域表侧表示存在的场合，1次…"),
        ("zh_tw", "此卡在怪獸區表側表示存在的場合，1次…"),
        ("scope", "this_card"),
        ("strictness", "use"),
        ("reset_on_leave", True),
        ("note", "旧句式「This effect can only be used once while this card is face-up on the field.」的现行写法（自 Code of the Duelist 起）。"),
        ("source", y("Problem-Solving_Card_Text")),
    ]),
]

numbering = OrderedDict([
    ("symbols", ["①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩"]),
    ("ascii_aliases", ["(1)", "(2)", "(3)", "(4)", "(5)"]),
    ("rule", "OCG 自 Starter Deck 2014 起为标准格式：卡片文本中的每个效果按出现顺序连续编号，编号仅作为「这个卡名的①②效果」这类交叉引用的锚点，本身不是效果内容。"),
    ("rules", [
        "编号只按顺序给「效果」编号；召唤条件、素材行、flavor text、灵摆效果（P效果单独另起 ① ②）不参与编号。",
        "灵摆怪兽有两个独立编号序列：怪兽效果用 ①②…，灵摆效果在「P效果」栏另起 ① ②…。",
        "「这个卡名的①②的效果1回合各能使用1次」引用的是编号，不是效果种类；因此新增或删除效果时必须重排编号。",
        "被「这个卡名的①的效果1回合只能使用1次」单独点名的，只有该编号的效果受限制。",
        "翻转怪兽的「FLIP:」效果在现行 Type line 记作 /反转，其效果文一般置于编号效果之前或作为独立段落。",
        "若一张卡同时有怪兽效果与灵摆效果，两者的 HOPT 限制互相独立。",
    ]),
    ("source", y("Card_text")),
])

structure = OrderedDict([
    ("template", "CONDITIONS : ACTIVATION ; RESOLUTION"),
    ("segments", [
        OrderedDict([("role", "conditions"), ("separator", ":"),
                     ("en_label", "green text"), ("ja_label", "発動条件"),
                     ("zh_cn_label", "发动条件"),
                     ("contains", ["when / if timing", "once per turn",
                                   "activation requirement", "optional 'you can'"]),
                     ("note", "只要求在发动时满足；处理时不需再满足。")]),
        OrderedDict([("role", "activation"), ("separator", ";"),
                     ("en_label", "red text"), ("ja_label", "発動時にすること"),
                     ("zh_cn_label", "发动时要做的事"),
                     ("contains", ["cost", "target"]),
                     ("note", "在发动瞬间完成，不可被无效（属于 cost 的部分）。")]),
        OrderedDict([("role", "resolution"), ("separator", "."),
                     ("en_label", "blue text"), ("ja_label", "効果の処理"),
                     ("zh_cn_label", "效果处理"),
                     ("contains", ["what actually happens"]),
                     ("note", "连锁逆处理时才执行。")]),
    ]),
    ("chain_rule", "效果文中出现「：」或「；」即表示该效果会入连锁；两者都没有则不入连锁、不能被连锁。"),
    ("spell_trap_exception", "魔法/陷阱卡只要发动就一定入连锁，即使效果文里没有冒号或分号（例：Creature Swap）。"),
    ("source", SRC["psct3"]),
])

patterns_doc = OrderedDict()
patterns_doc["_meta"] = OrderedDict([
    ("generated", GENERATED),
    ("scope", "PSCT（Problem-Solving Card Text）与 OCG 标准卡片文本的标点／连接词／HOPT／编号规则"),
    ("note", "本文件描述可编程的语法规则；具体短语的多语言对照见 terms.json 的 psct_phrase 分类。"),
    ("sources", [SRC["psct3"], SRC["psct7"], SRC["psct5"], y("Problem-Solving_Card_Text"),
                 SRC["ygo_hopt"], SRC["ygo_hopt_only"], SRC["ygo_cost"],
                 SRC["ygo_actcond"], SRC["ygo_quick"], y("Card_text")]),
])
patterns_doc["punctuation"] = punctuation
patterns_doc["conjunctions"] = conjunctions
patterns_doc["conjunction_quadrants"] = OrderedDict([
    ("axes", ["resolution_order (sequential | simultaneous)",
              "both_required / a_required_for_b"]),
    ("grid", [
        OrderedDict([("resolution_order", "sequential"), ("neither_required", "also_after_that"),
                     ("a_required_for_b", "then"), ("both_required", None)]),
        OrderedDict([("resolution_order", "simultaneous"), ("neither_required", "also"),
                     ("a_required_for_b", "and_if_you_do"), ("both_required", "and")]),
    ]),
    ("note", "不存在「两部分都必需且又不同时」的连接词；融合召唤/仪式召唤的效果文因此不使用连接词。"),
    ("source", y("Problem-Solving_Card_Text")),
])
patterns_doc["hopt"] = hopt
patterns_doc["numbering"] = numbering
patterns_doc["structure"] = structure
patterns_doc["timing_keywords"] = OrderedDict([
    ("when", OrderedDict([("en", "when"), ("ja", "時"), ("zh_cn", "时"), ("zh_tw", "時"),
                          ("strictness", "strict"),
                          ("note", "严格的触发时机：只在该事件是「最后发生的事」时才能发动。")])),
    ("if", OrderedDict([("en", "if"), ("ja", "場合"), ("zh_cn", "的场合"), ("zh_tw", "的場合"),
                        ("strictness", "loose"),
                        ("note", "宽松的触发时机：即使该事件之后又发生了别的事，仍可发动。")])),
    ("you_can", OrderedDict([("en", "You can"), ("ja", "できる"), ("zh_cn", "可以"),
                             ("zh_tw", "可以"), ("optionality", "optional"),
                             ("note", "可选效果；没有 You can／できる 的是必发效果。")])),
])
patterns_doc["sources"] = patterns_doc["_meta"]["sources"]

with open(os.path.join(OUT, "psct_patterns.json"), "w", encoding="utf-8") as f:
    json.dump(patterns_doc, f, ensure_ascii=False, indent=2)
    f.write("\n")

print("terms:", len(terms), "| categories:", cats)
print("nulls:", nulls)
print("psct_patterns: punctuation=%d conjunctions=%d hopt=%d numbering=%d" % (
    len(punctuation), len(conjunctions), len(hopt), len(numbering["symbols"])))
