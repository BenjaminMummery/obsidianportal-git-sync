from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from lore_bridge.dndbeyond.render import html_text

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
SAVE_SUBTYPES = {
    "str": "strength-saving-throws",
    "dex": "dexterity-saving-throws",
    "con": "constitution-saving-throws",
    "int": "intelligence-saving-throws",
    "wis": "wisdom-saving-throws",
    "cha": "charisma-saving-throws",
}


def map_dynamic_sheet(data: dict[str, Any], *, synced_at: datetime | None = None) -> dict[str, str]:
    sheet = map_character(data, synced_at=synced_at)
    mods = _active_modifiers(data)
    scores = _ability_scores(data, mods)
    prof = _proficiency_bonus(_total_level(data))
    combat = _plain_combat_buckets(data, scores, prof)

    player = (data.get("username") or "").strip()
    campaign = ((data.get("campaign") or {}).get("name") or "").strip()
    avatar_url = ((data.get("decorations") or {}).get("avatarUrl") or "").strip()

    result: dict[str, str] = {
        "name": sheet["name"],
        "class_summary": sheet["class_summary"],
        "prof_bonus": sheet["prof_bonus"],
        "player_campaign": _plain_player_campaign(player, campaign),
        "avatar_url": avatar_url,
        "ac": sheet["ac"],
        "hp_current": sheet["hp_current"],
        "hp_max": sheet["hp_max"],
        "speed": sheet["speed"],
        "initiative": sheet["initiative"],
        "hit_dice": sheet["hit_dice"],
        "str": sheet["str"],
        "dex": sheet["dex"],
        "con": sheet["con"],
        "int": sheet["int"],
        "wis": sheet["wis"],
        "cha": sheet["cha"],
        "str_save": sheet["str_save"],
        "dex_save": sheet["dex_save"],
        "con_save": sheet["con_save"],
        "int_save": sheet["int_save"],
        "wis_save": sheet["wis_save"],
        "cha_save": sheet["cha_save"],
        "skills": _skills_by_ability(scores, prof, mods, html=False),
        "passive_perception": sheet["passive_perception"],
        "passive_investigation": sheet["passive_investigation"],
        "passive_insight": sheet["passive_insight"],
        "inspiration": sheet["inspiration"],
        "temp_hp": sheet["temp_hp"],
        "conditions": sheet["conditions"],
        "death_saves": sheet["death_saves"],
        "limited_use": sheet["limited_use"],
        "actions": combat["actions"],
        "bonus_actions": combat["bonus_actions"],
        "reactions": combat["reactions"],
        "proficiencies": sheet["proficiencies"],
        "languages": sheet["languages"],
        "tools": sheet["tools"],
        "ddb_last_sync": sheet["ddb_last_sync"],
        "spellcasting_ability": "",
        "spell_save_dc": "",
        "spell_attack": "",
        "spell_slots": "",
        "spells_prepared": "",
        "spells_json": "[]",
    }

    if sheet["has_spellcasting"]:
        result["spellcasting_ability"] = sheet["spellcasting_ability"]
        result["spell_save_dc"] = sheet["spell_save_dc"]
        result["spell_attack"] = sheet["spell_attack"]
        result["spell_slots"] = sheet["spell_slots"]
        result["spells_prepared"] = sheet["spells_prepared"]
        result["spells_json"] = sheet["spells_json"]

    return result


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
    spell_slots = _spell_slots(data, level)
    spells_prepared = _spells_prepared(data)
    has_spellcasting = bool(spell_ability_id) and (spell_slots != "—" or spells_prepared != "—")

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
        "conditions": _conditions(data),
        "death_saves": _death_saves(data),
        "str": _ability_line(scores["str"]),
        "dex": _ability_line(scores["dex"]),
        "con": _ability_line(scores["con"]),
        "int": _ability_line(scores["int"]),
        "wis": _ability_line(scores["wis"]),
        "cha": _ability_line(scores["cha"]),
        "str_save": _save_value("str", scores, prof, mods),
        "dex_save": _save_value("dex", scores, prof, mods),
        "con_save": _save_value("con", scores, prof, mods),
        "int_save": _save_value("int", scores, prof, mods),
        "wis_save": _save_value("wis", scores, prof, mods),
        "cha_save": _save_value("cha", scores, prof, mods),
        "skills": _skills_by_ability(scores, prof, mods, html=True),
        "passive_perception": str(10 + _skill_bonus("perception", scores, prof, mods)),
        "passive_investigation": str(10 + _skill_bonus("investigation", scores, prof, mods)),
        "passive_insight": str(10 + _skill_bonus("insight", scores, prof, mods)),
        "combat_actions": _combat_actions(data, scores, prof),
        "limited_use": _limited_use_deduped(data, scores, prof),
        "features_traits": _features(data, level),
        "proficiencies": _proficiencies(mods),
        "languages": _languages(mods),
        "tools": _tools(mods),
        "equipment": _equipment(data),
        "spellcasting_ability": STAT_IDS.get(spell_ability_id or 0, "int"),
        "spell_save_dc": spell_save_dc,
        "spell_attack": spell_attack,
        "spell_slots": spell_slots,
        "spells_prepared": spells_prepared,
        "spells_json": _spells_json(data),
        "has_spellcasting": has_spellcasting,
        "ddb_last_sync": sync_label,
        "avatar_url": avatar_url,
        "avatar_img": f'<img src="{html_text(avatar_url)}" alt="">' if avatar_url else "",
        "player": html_text(player) if player else "",
        "campaign": html_text(campaign) if campaign else "",
        "player_campaign": _player_campaign(player, campaign),
    }


def _player_campaign(player: str, campaign: str) -> str:
    if player and campaign:
        return f"{html_text(player)} · {html_text(campaign)}"
    return html_text(player or campaign)


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


def _save_value(key: str, scores: dict[str, int], prof: int, mods: list[dict[str, Any]]) -> str:
    bonus = _ability_mod(scores[key])
    proficient = _has_proficiency(mods, SAVE_SUBTYPES[key])
    if proficient:
        bonus += prof
    mark = " *" if proficient else ""
    return f"{_signed(bonus)}{mark}"


def _skills(scores: dict[str, int], prof: int, mods: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for skill in SKILLS:
        bonus = _skill_bonus(skill, scores, prof, mods)
        proficient = _has_proficiency(mods, skill) or _has_expertise(mods, skill)
        mark = " *" if proficient else ""
        lines.append(f"{SKILL_LABELS[skill]} {_signed(bonus)}{mark}")
    return "\n".join(lines)


def _skills_by_ability(scores: dict[str, int], prof: int, mods: list[dict[str, Any]], *, html: bool) -> str:
    parts: list[str] = []
    for stat_key in ("str", "dex", "con", "int", "wis", "cha"):
        lines: list[str] = []
        for skill, ability in SKILLS.items():
            if ability != stat_key:
                continue
            bonus = _skill_bonus(skill, scores, prof, mods)
            proficient = _has_proficiency(mods, skill) or _has_expertise(mods, skill)
            mark = " *" if proficient else ""
            lines.append(f"{SKILL_LABELS[skill]} {_signed(bonus)}{mark}")
        if not lines:
            continue
        if html:
            parts.append(f'<h3 class="ddb-subsection-title">{STAT_LABELS[stat_key]}</h3>')
            parts.append(
                '<div class="ddb-block ddb-skill-group">'
                + "<br>\n".join(html_text(line) for line in lines)
                + "</div>"
            )
        else:
            parts.append(STAT_LABELS[stat_key])
            parts.extend(lines)
            parts.append("")
    if html:
        return "\n".join(parts)
    return "\n".join(parts).strip()


def _conditions(data: dict[str, Any]) -> str:
    names: list[str] = []
    for condition in data.get("conditions") or []:
        if isinstance(condition, str):
            names.append(condition.strip())
            continue
        if not isinstance(condition, dict):
            continue
        name = (condition.get("name") or (condition.get("definition") or {}).get("name") or "").strip()
        if name:
            names.append(name)
    return ", ".join(names)


def _death_saves(data: dict[str, Any]) -> str:
    saves = data.get("deathSaves") or {}
    if saves.get("isStabilized"):
        return "Stabilized"
    fails = saves.get("failCount")
    successes = saves.get("successCount")
    if fails in (None, 0) and successes in (None, 0):
        return ""
    return f"Failures {fails or 0}, Successes {successes or 0}"


def _combat_entry_names(*bucket_texts: str) -> set[str]:
    names: set[str] = set()
    for text in bucket_texts:
        for line in str(text or "").splitlines():
            line = line.strip()
            if not line:
                continue
            if ". " in line:
                names.add(line.split(". ", 1)[0].strip().lower())
            elif "." in line:
                names.add(line.split(".", 1)[0].strip().lower())
            else:
                names.add(line.lower())
    return names


def _limited_use_deduped(data: dict[str, Any], scores: dict[str, int], prof: int) -> str:
    raw = _limited_use(data)
    if not raw or raw == "—":
        return ""
    combat = _plain_combat_buckets(data, scores, prof)
    combat_names = _combat_entry_names(
        combat.get("actions", ""),
        combat.get("bonus_actions", ""),
        combat.get("reactions", ""),
    )
    kept: list[str] = []
    for line in raw.splitlines():
        name = line.split(" (", 1)[0].strip().lower()
        if name in combat_names:
            continue
        kept.append(line)
    return "\n".join(kept)


def _activation_bucket(action: dict[str, Any]) -> str:
    activation_type = (action.get("activation") or {}).get("activationType")
    if activation_type == 3:
        return "bonus_actions"
    if activation_type == 4:
        return "reactions"
    return "actions"


def _action_detail_line(action: dict[str, Any]) -> str:
    snippet = _clean_snippet(action.get("snippet") or action.get("description") or "")
    name = action.get("name") or "Action"
    if snippet:
        return _named_detail_line(name, snippet)
    return _named_detail_line(name, "")


def _weapon_attack_lines(data: dict[str, Any], scores: dict[str, int], prof: int) -> list[str]:
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
        detail = f"{_signed(attack_bonus)} to hit{range_text}"
        if damage:
            detail += f", {damage}"
            if damage_type:
                detail += f" {damage_type.lower()}"
        lines.append(_named_detail_line(name, detail))
    return lines


def _combat_actions(data: dict[str, Any], scores: dict[str, int], prof: int) -> str:
    buckets: dict[str, list[str]] = {
        "actions": _weapon_attack_lines(data, scores, prof),
        "bonus_actions": [],
        "reactions": [],
    }

    action_groups = data.get("actions") or {}
    if isinstance(action_groups, dict):
        for group in action_groups.values():
            if not group:
                continue
            for action in group:
                buckets[_activation_bucket(action)].append(_action_detail_line(action))

    for action in data.get("customActions") or []:
        buckets[_activation_bucket(action)].append(_action_detail_line(action))

    titles = {
        "actions": "Actions",
        "bonus_actions": "Bonus Actions",
        "reactions": "Reactions",
    }
    parts: list[str] = []
    for key, title in titles.items():
        lines = buckets[key]
        if not lines:
            continue
        content = "<br>\n".join(lines)
        parts.append(
            f'<h3 class="ddb-subsection-title">{title}</h3>\n<div class="ddb-block">{content}</div>'
        )
    if not parts:
        return ""
    return '<h2 class="ddb-section-title">Combat</h2>\n' + "\n".join(parts)


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
        lines.append(_named_detail_line(name, snippet))
    for cls in data.get("classes") or []:
        for feature in cls.get("classFeatures") or []:
            definition = feature.get("definition") or {}
            required = definition.get("requiredLevel") or 0
            if required and level < required:
                continue
            snippet = _clean_snippet(definition.get("snippet") or definition.get("description") or "")
            name = definition.get("name") or "Feature"
            if snippet or name:
                lines.append(_named_detail_line(name, snippet))
    for feat in data.get("feats") or []:
        definition = feat.get("definition") or {}
        snippet = _clean_snippet(definition.get("snippet") or definition.get("description") or "")
        name = definition.get("name") or "Feat"
        lines.append(_named_detail_line(name, snippet))
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


def _spell_slot_table_maxes(data: dict[str, Any]) -> dict[int, int]:
    maxes: dict[int, int] = {}
    for cls in data.get("classes") or []:
        definition = cls.get("definition") or {}
        if not definition.get("canCastSpells"):
            continue
        cls_level = cls.get("level") or 0
        rules = definition.get("spellRules") or {}
        slot_table = rules.get("levelSpellSlots") or []
        if cls_level >= len(slot_table):
            continue
        for idx, slots in enumerate(slot_table[cls_level] or [], start=1):
            if slots:
                maxes[idx] = max(maxes.get(idx, 0), slots)
    return maxes


def _spell_slots(data: dict[str, Any], level: int) -> str:
    usage = {
        int(slot["level"]): slot
        for slot in (data.get("spellSlots") or [])
        if slot.get("level") is not None
    }
    maxes = _spell_slot_table_maxes(data)
    if not maxes:
        rules = None
        for cls in data.get("classes") or []:
            definition = cls.get("definition") or {}
            if definition.get("canCastSpells"):
                rules = definition.get("spellRules") or {}
                break
        slot_table = (rules or {}).get("levelSpellSlots") or []
        slot_maxes = slot_table[level] if level < len(slot_table) else []
        for idx, max_slots in enumerate(slot_maxes or [], start=1):
            if max_slots:
                maxes[idx] = max_slots

    lines: list[str] = []
    levels = sorted(set(maxes) | {lvl for lvl, slot in usage.items() if (slot.get("used") or 0) > 0})
    for lvl in levels:
        max_slots = maxes.get(lvl, 0)
        used = int((usage.get(lvl) or {}).get("used") or 0)
        if not max_slots:
            available = int((usage.get(lvl) or {}).get("available") or 0)
            max_slots = used + available
        if not max_slots:
            continue
        remaining = max(0, max_slots - used)
        lines.append(f"{lvl}{_ordinal_suffix(lvl)} {remaining}/{max_slots}")

    pact_lines: list[str] = []
    for slot in data.get("pactMagic") or []:
        lvl = int(slot.get("level") or 0)
        if lvl != 1:
            continue
        max_slots = int(slot.get("available") or 0) + int(slot.get("used") or 0)
        if not max_slots:
            continue
        used = int(slot.get("used") or 0)
        remaining = max(0, max_slots - used)
        pact_lines.append(f"Pact {remaining}/{max_slots}")
    lines.extend(pact_lines)
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
            if not _spell_included(spell, definition):
                continue
            level = definition.get("level") or 0
            by_level.setdefault(level, []).append(definition.get("name") or "Spell")
        for level in sorted(by_level):
            label = "Cantrips" if level == 0 else f"Level {level}"
            lines.append(f"{label}: {', '.join(sorted(by_level[level]))}")
    return "\n".join(lines) if lines else "—"


def _spell_included(spell: dict[str, Any], definition: dict[str, Any]) -> bool:
    level = definition.get("level") or 0
    if level == 0:
        return True
    if spell.get("prepared") or spell.get("alwaysPrepared"):
        return True
    return bool(definition.get("ritual"))


def _spell_level_label(level: int) -> str:
    if level == 0:
        return "Cantrip"
    return f"{level}{_ordinal_suffix(level)}"


def _spell_plain_body(definition: dict[str, Any]) -> str:
    snippet = _clean_snippet(definition.get("snippet") or "")
    if snippet:
        return snippet
    text = definition.get("description") or ""
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</p>", "\n\n", text, flags=re.I)
    text = re.sub(r"<li>", "\n• ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _collect_spells(data: dict[str, Any]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    spells: list[dict[str, Any]] = []
    for class_spell in data.get("classSpells") or []:
        for spell in class_spell.get("spells") or []:
            definition = spell.get("definition") or {}
            name = (definition.get("name") or "Spell").strip()
            key = name.lower()
            if key in seen or not _spell_included(spell, definition):
                continue
            seen.add(key)
            level = int(definition.get("level") or 0)
            spells.append(
                {
                    "name": name,
                    "level": level,
                    "level_label": _spell_level_label(level),
                    "school": (definition.get("school") or "").strip().lower(),
                    "concentration": bool(definition.get("concentration")),
                    "ritual": bool(definition.get("ritual")),
                    "body": _spell_plain_body(definition),
                }
            )
    spells.sort(key=lambda item: (item["level"], item["name"].lower()))
    return spells


def _spells_json(data: dict[str, Any]) -> str:
    spells = _collect_spells(data)
    if not spells:
        return "[]"
    return json.dumps(spells, ensure_ascii=False)


def _clean_snippet(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    text = re.sub(r"\{\{[^}]+\}\}", "", text)
    return " ".join(text.split())


def _named_detail_line(name: str, detail: str) -> str:
    name = (name or "").strip()
    detail = (detail or "").strip()
    if detail:
        return f"<strong>{html_text(name)}.</strong> {html_text(detail)}"
    return f"<strong>{html_text(name)}</strong>"


def _plain_named_detail_line(name: str, detail: str) -> str:
    name = (name or "").strip()
    detail = (detail or "").strip()
    if detail:
        return f"{name}. {detail}"
    return name


def _saving_throws(scores: dict[str, int], prof: int, mods: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for key in STAT_LABELS:
        bonus = _ability_mod(scores[key])
        proficient = _has_proficiency(mods, SAVE_SUBTYPES[key])
        if proficient:
            bonus += prof
        mark = " *" if proficient else ""
        lines.append(f"{STAT_LABELS[key]} {_signed(bonus)}{mark}")
    return "\n".join(lines)


def _plain_weapon_attack_lines(data: dict[str, Any], scores: dict[str, int], prof: int) -> list[str]:
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
        detail = f"{_signed(attack_bonus)} to hit{range_text}"
        if damage:
            detail += f", {damage}"
            if damage_type:
                detail += f" {damage_type.lower()}"
        lines.append(_plain_named_detail_line(name, detail))
    return lines


def _plain_action_detail_line(action: dict[str, Any]) -> str:
    snippet = _clean_snippet(action.get("snippet") or action.get("description") or "")
    name = action.get("name") or "Action"
    return _plain_named_detail_line(name, snippet)


def _plain_player_campaign(player: str, campaign: str) -> str:
    if player and campaign:
        return f"{player} · {campaign}"
    return player or campaign or ""


def _plain_combat_buckets(data: dict[str, Any], scores: dict[str, int], prof: int) -> dict[str, str]:
    buckets: dict[str, list[str]] = {
        "actions": _plain_weapon_attack_lines(data, scores, prof),
        "bonus_actions": [],
        "reactions": [],
    }

    action_groups = data.get("actions") or {}
    if isinstance(action_groups, dict):
        for group in action_groups.values():
            if not group:
                continue
            for action in group:
                buckets[_activation_bucket(action)].append(_plain_action_detail_line(action))

    for action in data.get("customActions") or []:
        buckets[_activation_bucket(action)].append(_plain_action_detail_line(action))

    return {key: "\n".join(lines) if lines else "" for key, lines in buckets.items()}


def _plain_actions(data: dict[str, Any], scores: dict[str, int], prof: int) -> str:
    lines = _plain_weapon_attack_lines(data, scores, prof)

    action_groups = data.get("actions") or {}
    if isinstance(action_groups, dict):
        for group in action_groups.values():
            if not group:
                continue
            for action in group:
                lines.append(_plain_action_detail_line(action))

    for action in data.get("customActions") or []:
        lines.append(_plain_action_detail_line(action))

    return "\n".join(lines) if lines else "—"


def _plain_limited_use(data: dict[str, Any]) -> str:
    limited = _limited_use(data)
    return limited if limited else "—"


def _plain_features(data: dict[str, Any], level: int) -> str:
    lines: list[str] = []
    for trait in ((data.get("race") or {}).get("racialTraits") or []):
        definition = trait.get("definition") or {}
        snippet = _clean_snippet(definition.get("snippet") or definition.get("description") or "")
        name = definition.get("name") or "Trait"
        lines.append(_plain_named_detail_line(name, snippet))
    for cls in data.get("classes") or []:
        for feature in cls.get("classFeatures") or []:
            definition = feature.get("definition") or {}
            required = definition.get("requiredLevel") or 0
            if required and level < required:
                continue
            snippet = _clean_snippet(definition.get("snippet") or definition.get("description") or "")
            name = definition.get("name") or "Feature"
            if snippet or name:
                lines.append(_plain_named_detail_line(name, snippet))
    for feat in data.get("feats") or []:
        definition = feat.get("definition") or {}
        snippet = _clean_snippet(definition.get("snippet") or definition.get("description") or "")
        name = definition.get("name") or "Feat"
        lines.append(_plain_named_detail_line(name, snippet))
    return "\n".join(lines) if lines else "—"
