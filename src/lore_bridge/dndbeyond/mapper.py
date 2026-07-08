from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from typing import Any

STAT_IDS = {1: "str", 2: "dex", 3: "con", 4: "int", 5: "wis", 6: "cha"}
STAT_LABELS = {"str": "STR", "dex": "DEX", "con": "CON", "int": "INT", "wis": "WIS", "cha": "CHA"}
ALIGNMENTS = {
    1: "Lawful Good",
    2: "Neutral Good",
    3: "Chaotic Good",
    4: "Lawful Neutral",
    5: "True Neutral",
    6: "Chaotic Neutral",
    7: "Lawful Evil",
    8: "Neutral Evil",
    9: "Chaotic Evil",
}
SKILLS: dict[str, str] = {
    "acrobatics": "dex",
    "animal-handling": "wis",
    "arcana": "int",
    "athletics": "str",
    "deception": "cha",
    "history": "int",
    "insight": "wis",
    "intimidation": "cha",
    "investigation": "int",
    "medicine": "wis",
    "nature": "int",
    "perception": "wis",
    "performance": "cha",
    "persuasion": "cha",
    "religion": "int",
    "sleight-of-hand": "dex",
    "stealth": "dex",
    "survival": "wis",
}
SKILL_LABELS = {key: key.replace("-", " ").title() for key in SKILLS}


def map_character(data: dict[str, Any], *, synced_at: datetime | None = None) -> dict[str, str]:
    mods = _active_modifiers(data)
    scores = _ability_scores(data, mods)
    level = _total_level(data)
    prof = _proficiency_bonus(level)

    race = (data.get("race") or {}).get("fullName") or (data.get("race") or {}).get("baseName") or ""
    background = ((data.get("background") or {}).get("definition") or {}).get("name") or ""
    alignment = ALIGNMENTS.get(data.get("alignmentId") or 0, "")
    inspiration = "Yes" if data.get("inspiration") else "No"

    hp_max = (data.get("overrideHitPoints") or 0) or (data.get("baseHitPoints") or 0) + (data.get("bonusHitPoints") or 0)
    removed = data.get("removedHitPoints") or 0
    temp = data.get("temporaryHitPoints") or 0
    hp_current = max(0, hp_max - removed)

    speed = _speed(data)
    initiative = _signed(_ability_mod(scores["dex"]) + _modifier_bonus(mods, "bonus", "initiative"))

    spell_ability_id = _spellcasting_ability_id(data)
    spell_mod = _ability_mod(scores[STAT_IDS.get(spell_ability_id or 4, "int")])
    spell_save_dc = str(8 + prof + spell_mod) if spell_ability_id else ""
    spell_attack = _signed(prof + spell_mod) if spell_ability_id else ""

    synced = synced_at or datetime.now(timezone.utc)
    sync_label = synced.strftime("%Y-%m-%d %H:%M UTC")

    avatar_url = ((data.get("decorations") or {}).get("avatarUrl") or "").strip()
    campaign = ((data.get("campaign") or {}).get("name") or "").strip()
    player = (data.get("username") or "").strip()

    return {
        "name": data.get("name") or "Unnamed",
        "class_summary": _class_summary(data),
        "race": race,
        "background": background,
        "alignment": alignment,
        "prof_bonus": _signed(prof),
        "inspiration": inspiration,
        "ac": str(_armor_class(data, scores, mods)),
        "hp_current": str(hp_current),
        "hp_max": str(hp_max),
        "temp_hp": str(temp),
        "speed": speed,
        "initiative": initiative,
        "hit_dice": _hit_dice(data),
        "str": _ability_line(scores["str"]),
        "dex": _ability_line(scores["dex"]),
        "con": _ability_line(scores["con"]),
        "int": _ability_line(scores["int"]),
        "wis": _ability_line(scores["wis"]),
        "cha": _ability_line(scores["cha"]),
        "saving_throws": _saving_throws(scores, prof, mods),
        "skills": _skills(scores, prof, mods),
        "passive_perception": str(10 + _skill_bonus("perception", scores, prof, mods)),
        "passive_investigation": str(10 + _skill_bonus("investigation", scores, prof, mods)),
        "passive_insight": str(10 + _skill_bonus("insight", scores, prof, mods)),
        "actions": _actions(data, scores, prof, mods),
        "limited_use": _limited_use(data),
        "features_traits": _features(data, level),
        "proficiencies": _proficiencies(mods),
        "languages": _languages(mods),
        "tools": _tools(mods),
        "equipment": _equipment(data),
        "spellcasting_ability": STAT_IDS.get(spell_ability_id or 0, "int"),
        "spell_save_dc": spell_save_dc,
        "spell_attack": spell_attack,
        "spell_slots": _spell_slots(data, level),
        "spells_prepared": _spells_prepared(data),
        "ddb_last_sync": sync_label,
        "avatar_url": avatar_url,
        "avatar_img": f'<img src="{html.escape(avatar_url)}" alt="">' if avatar_url else "",
        "player": html.escape(player) if player else "",
        "campaign": html.escape(campaign) if campaign else "",
        "player_campaign": _player_campaign(player, campaign),
    }


def _player_campaign(player: str, campaign: str) -> str:
    if player and campaign:
        return f"{html.escape(player)} · {html.escape(campaign)}"
    return html.escape(player or campaign)


def _active_modifiers(data: dict[str, Any]) -> list[dict[str, Any]]:
    mods: list[dict[str, Any]] = []
    for group, items in (data.get("modifiers") or {}).items():
        if not items:
            continue
        for mod in items:
            if group == "item" and not _item_modifier_active(data, mod):
                continue
            mods.append(mod)
    return mods


def _item_modifier_active(data: dict[str, Any], mod: dict[str, Any]) -> bool:
    component_id = mod.get("componentId")
    for item in data.get("inventory") or []:
        definition = item.get("definition") or {}
        if definition.get("id") != component_id:
            continue
        return _item_active(item)
    return True


def _item_active(item: dict[str, Any]) -> bool:
    definition = item.get("definition") or {}
    if definition.get("canEquip") and not item.get("equipped"):
        return False
    if definition.get("canAttune") and not item.get("isAttuned"):
        return False
    return True


def _ability_scores(data: dict[str, Any], mods: list[dict[str, Any]]) -> dict[str, int]:
    scores: dict[str, int] = {}
    for stat_id, key in STAT_IDS.items():
        value = 0
        for source in data.get("stats") or []:
            if source.get("id") == stat_id:
                value += source.get("value") or 0
        for source in data.get("bonusStats") or []:
            if source.get("id") == stat_id:
                value += source.get("value") or 0
        for mod in mods:
            if mod.get("type") == "bonus" and mod.get("entityId") == stat_id:
                value += mod.get("value") or 0
        scores[key] = value
    return scores


def _ability_mod(score: int) -> int:
    return (score - 10) // 2


def _ability_line(score: int) -> str:
    mod = _ability_mod(score)
    return f"{score} ({_signed(mod)})"


def _signed(value: int) -> str:
    return f"+{value}" if value >= 0 else str(value)


def _total_level(data: dict[str, Any]) -> int:
    return sum((cls.get("level") or 0) for cls in data.get("classes") or [])


def _proficiency_bonus(level: int) -> int:
    if level <= 0:
        return 2
    return 2 + (level - 1) // 4


def _class_summary(data: dict[str, Any]) -> str:
    parts: list[str] = []
    for cls in data.get("classes") or []:
        name = ((cls.get("definition") or {}).get("name") or "Class").strip()
        subclass = ((cls.get("subclassDefinition") or {}).get("name") or "").strip()
        level = cls.get("level") or 0
        if subclass:
            parts.append(f"{name} ({subclass}) {level}")
        else:
            parts.append(f"{name} {level}")
    return " / ".join(parts) if parts else "Unknown"


def _hit_dice(data: dict[str, Any]) -> str:
    parts: list[str] = []
    for cls in data.get("classes") or []:
        die = ((cls.get("definition") or {}).get("hitDie") or 0)
        level = cls.get("level") or 0
        if die and level:
            parts.append(f"{level}d{die}")
    return ", ".join(parts)


def _speed(data: dict[str, Any]) -> str:
    speeds = ((data.get("race") or {}).get("weightSpeeds") or {}).get("normal") or {}
    walk = speeds.get("walk")
    if walk:
        return f"{walk} ft."
    for entry in data.get("customSpeeds") or []:
        if entry.get("distance"):
            return f"{entry['distance']} ft."
    return "30 ft."


def _armor_class(data: dict[str, Any], scores: dict[str, int], mods: list[dict[str, Any]]) -> int:
    if data.get("overrideArmorClass"):
        return int(data["overrideArmorClass"])
    equipped_armor = [
        item
        for item in data.get("inventory") or []
        if _item_active(item) and (item.get("definition") or {}).get("filterType") == "Armor"
        and (item.get("definition") or {}).get("armorTypeId") != 4
    ]
    dex_mod = _ability_mod(scores["dex"])
    ac_bonus = sum(mod.get("value") or 0 for mod in mods if mod.get("type") == "bonus" and mod.get("subType") == "armor-class")
    if equipped_armor:
        base = sum((item.get("definition") or {}).get("armorClass") or 0 for item in equipped_armor)
        armor_type_ids = {(item.get("definition") or {}).get("armorTypeId") for item in equipped_armor}
        if 3 in armor_type_ids:
            base += _proficiency_bonus(_total_level(data))
        elif 4 not in armor_type_ids:
            base += dex_mod
        return base + ac_bonus
    unarmored = next((mod for mod in mods if mod.get("type") == "set" and mod.get("subType") == "unarmored-armor-class"), None)
    if unarmored:
        base = unarmored.get("value") or 10
        if unarmored.get("statId"):
            base += _ability_mod(scores[STAT_IDS.get(unarmored["statId"], "dex")])
        else:
            base += dex_mod
        return base + ac_bonus
    return 10 + dex_mod + ac_bonus


def _has_proficiency(mods: list[dict[str, Any]], sub_type: str) -> bool:
    return any(mod.get("type") == "proficiency" and mod.get("subType") == sub_type for mod in mods)


def _has_expertise(mods: list[dict[str, Any]], sub_type: str) -> bool:
    return any(mod.get("type") == "expertise" and mod.get("subType") == sub_type for mod in mods)


def _modifier_bonus(mods: list[dict[str, Any]], mod_type: str, sub_type: str) -> int:
    return sum(mod.get("value") or 0 for mod in mods if mod.get("type") == mod_type and mod.get("subType") == sub_type)


def _skill_bonus(skill: str, scores: dict[str, int], prof: int, mods: list[dict[str, Any]]) -> int:
    ability = SKILLS[skill]
    bonus = _ability_mod(scores[ability])
    if _has_expertise(mods, skill):
        bonus += prof * 2
    elif _has_proficiency(mods, skill):
        bonus += prof
    return bonus


def _saving_throws(scores: dict[str, int], prof: int, mods: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for key, label in STAT_LABELS.items():
        bonus = _ability_mod(scores[key])
        if _has_proficiency(mods, f"{key}-saving-throws"):
            bonus += prof
            mark = " *"
        else:
            mark = ""
        lines.append(f"{label} {_signed(bonus)}{mark}")
    return "\n".join(lines)


def _skills(scores: dict[str, int], prof: int, mods: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for skill, ability in SKILLS.items():
        if not (_has_proficiency(mods, skill) or _has_expertise(mods, skill)):
            continue
        bonus = _skill_bonus(skill, scores, prof, mods)
        mark = " *" if _has_proficiency(mods, skill) or _has_expertise(mods, skill) else ""
        lines.append(f"{SKILL_LABELS[skill]} {_signed(bonus)}{mark}")
    return "\n".join(lines) if lines else "—"


def _actions(data: dict[str, Any], scores: dict[str, int], prof: int, mods: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for item in data.get("inventory") or []:
        if not _item_active(item):
            continue
        definition = item.get("definition") or {}
        if definition.get("filterType") != "Weapon":
            continue
        name = definition.get("name") or "Weapon"
        damage = ((definition.get("damage") or {}).get("diceString") or "").strip()
        damage_type = (definition.get("damageType") or "").strip()
        attack_stat = STAT_IDS.get(definition.get("attackStat") or 0, "str")
        attack_bonus = prof + _ability_mod(scores[attack_stat])
        range_obj = definition.get("range")
        range_val = ""
        if isinstance(range_obj, dict):
            range_val = range_obj.get("range") or ""
        elif isinstance(range_obj, int):
            range_val = range_obj
        range_text = f", range {range_val} ft." if range_val else ", melee 5 ft."
        detail = f"{name}. {_signed(attack_bonus)} to hit{range_text}"
        if damage:
            detail += f", {damage}"
            if damage_type:
                detail += f" {damage_type.lower()}"
        lines.append(detail)

    action_groups = data.get("actions") or {}
    if isinstance(action_groups, dict):
        for group in action_groups.values():
            if not group:
                continue
            for action in group:
                snippet = _clean_snippet(action.get("snippet") or action.get("description") or "")
                name = action.get("name") or "Action"
                if snippet:
                    lines.append(f"{name}. {snippet}")
                elif name:
                    lines.append(name)

    for action in data.get("customActions") or []:
        snippet = _clean_snippet(action.get("snippet") or action.get("description") or "")
        name = action.get("name") or "Custom Action"
        lines.append(f"{name}. {snippet}" if snippet else name)

    return "\n".join(lines) if lines else "—"


def _limited_use(data: dict[str, Any]) -> str:
    lines: list[str] = []
    action_groups = data.get("actions") or {}
    if isinstance(action_groups, dict):
        for group in action_groups.values():
            if not group:
                continue
            for action in group:
                limited = action.get("limitedUse") or {}
                if not limited.get("maxUses"):
                    continue
                snippet = _clean_snippet(action.get("snippet") or action.get("description") or "")
                reset = {1: "short rest", 2: "long rest", 3: "day", 4: "none"}.get(limited.get("resetType") or 0, "rest")
                name = action.get("name") or "Feature"
                line = f"{name} ({limited.get('maxUses')}/{reset})"
                if snippet:
                    line += f". {snippet}"
                lines.append(line)
    return "\n".join(lines) if lines else "—"


def _features(data: dict[str, Any], level: int) -> str:
    lines: list[str] = []
    for trait in ((data.get("race") or {}).get("racialTraits") or []):
        definition = trait.get("definition") or {}
        snippet = _clean_snippet(definition.get("snippet") or definition.get("description") or "")
        name = definition.get("name") or "Trait"
        lines.append(f"{name}. {snippet}" if snippet else name)
    for cls in data.get("classes") or []:
        for feature in cls.get("classFeatures") or []:
            definition = feature.get("definition") or {}
            required = definition.get("requiredLevel") or 0
            if required and level < required:
                continue
            snippet = _clean_snippet(definition.get("snippet") or definition.get("description") or "")
            name = definition.get("name") or "Feature"
            if snippet or name:
                lines.append(f"{name}. {snippet}" if snippet else name)
    for feat in data.get("feats") or []:
        definition = feat.get("definition") or {}
        snippet = _clean_snippet(definition.get("snippet") or definition.get("description") or "")
        name = definition.get("name") or "Feat"
        lines.append(f"{name}. {snippet}" if snippet else name)
    return "\n".join(lines) if lines else "—"


def _proficiencies(mods: list[dict[str, Any]]) -> str:
    values = sorted({
        mod.get("friendlySubtypeName") or ""
        for mod in mods
        if mod.get("type") == "proficiency"
        and mod.get("subType")
        and not mod.get("subType", "").endswith("-saving-throws")
        and mod.get("subType") not in SKILLS
        and "weapon" not in (mod.get("subType") or "")
        and "armor" not in (mod.get("subType") or "")
        and "tool" not in (mod.get("subType") or "")
        and mod.get("friendlySubtypeName")
    })
    weapon_values = sorted({
        mod.get("friendlySubtypeName") or ""
        for mod in mods
        if mod.get("type") == "proficiency" and "weapon" in (mod.get("subType") or "")
    })
    armor_values = sorted({
        mod.get("friendlySubtypeName") or ""
        for mod in mods
        if mod.get("type") == "proficiency" and ("armor" in (mod.get("subType") or "") or "shield" in (mod.get("subType") or ""))
    })
    parts = []
    if armor_values:
        parts.append(", ".join(armor_values))
    if weapon_values:
        parts.append(", ".join(weapon_values))
    if values:
        parts.append(", ".join(values))
    return "; ".join(parts) if parts else "—"


def _languages(mods: list[dict[str, Any]]) -> str:
    values = sorted({mod.get("friendlySubtypeName") or "" for mod in mods if mod.get("type") == "language" and mod.get("friendlySubtypeName")})
    return ", ".join(values) if values else "—"


def _tools(mods: list[dict[str, Any]]) -> str:
    values = sorted({
        mod.get("friendlySubtypeName") or ""
        for mod in mods
        if mod.get("type") == "proficiency" and "tool" in (mod.get("subType") or "") and mod.get("friendlySubtypeName")
    })
    return ", ".join(values) if values else "—"


def _equipment(data: dict[str, Any]) -> str:
    lines: list[str] = []
    for item in data.get("inventory") or []:
        definition = item.get("definition") or {}
        name = definition.get("name") or "Item"
        qty = item.get("quantity") or 1
        if qty > 1:
            lines.append(f"{name} x{qty}")
        else:
            lines.append(name)
    currencies = data.get("currencies") or {}
    coin_parts = []
    for key, label in (("gp", "gp"), ("sp", "sp"), ("cp", "cp"), ("ep", "ep"), ("pp", "pp")):
        amount = currencies.get(key)
        if amount:
            coin_parts.append(f"{amount} {label}")
    if coin_parts:
        lines.append(", ".join(coin_parts))
    return "\n".join(lines) if lines else "—"


def _spellcasting_ability_id(data: dict[str, Any]) -> int | None:
    for cls in data.get("classes") or []:
        definition = cls.get("definition") or {}
        if definition.get("canCastSpells"):
            return definition.get("spellCastingAbilityId")
    return None


def _spell_slots(data: dict[str, Any], level: int) -> str:
    lines: list[str] = []
    rules = None
    for cls in data.get("classes") or []:
        definition = cls.get("definition") or {}
        if definition.get("canCastSpells"):
            rules = definition.get("spellRules") or {}
            break
    slot_table = (rules or {}).get("levelSpellSlots") or []
    slot_maxes = slot_table[level] if level < len(slot_table) else []
    used_by_level = {slot.get("level"): slot.get("used") or 0 for slot in data.get("spellSlots") or []}
    for idx, max_slots in enumerate(slot_maxes or [], start=1):
        if not max_slots:
            continue
        used = used_by_level.get(idx, 0)
        remaining = max(0, max_slots - used)
        lines.append(f"{idx}{_ordinal_suffix(idx)} {remaining}/{max_slots}")
    return "\n".join(lines) if lines else "—"


def _ordinal_suffix(level: int) -> str:
    if 10 <= level % 100 <= 20:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(level % 10, "th")


def _spells_prepared(data: dict[str, Any]) -> str:
    lines: list[str] = []
    for class_spell in data.get("classSpells") or []:
        by_level: dict[int, list[str]] = {}
        for spell in class_spell.get("spells") or []:
            definition = spell.get("definition") or {}
            if not (spell.get("prepared") or spell.get("alwaysPrepared") or definition.get("level") == 0):
                continue
            level = definition.get("level") or 0
            by_level.setdefault(level, []).append(definition.get("name") or "Spell")
        for level in sorted(by_level):
            label = "Cantrips" if level == 0 else f"Level {level}"
            lines.append(f"{label}: {', '.join(sorted(by_level[level]))}")
    return "\n".join(lines) if lines else "—"


def _clean_snippet(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    text = re.sub(r"\{\{[^}]+\}\}", "", text)
    return " ".join(text.split())
