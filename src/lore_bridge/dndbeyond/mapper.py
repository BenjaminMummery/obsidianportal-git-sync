from __future__ import annotations

import ast
import json
import math
import operator
import re
from datetime import datetime, timezone
from typing import Any

from lore_bridge.dndbeyond.render import html_text

STAT_IDS = {1: "str", 2: "dex", 3: "con", 4: "int", 5: "wis", 6: "cha"}
STAT_LABELS = {"str": "STR", "dex": "DEX", "con": "CON", "int": "INT", "wis": "WIS", "cha": "CHA"}
STAT_FULL_NAMES = {
    "str": "Strength",
    "dex": "Dexterity",
    "con": "Constitution",
    "int": "Intelligence",
    "wis": "Wisdom",
    "cha": "Charisma",
}
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
ACTIVATION_TYPE_LABELS = {
    1: "action",
    2: "action",
    3: "bonus action",
    4: "reaction",
    5: "minute",
    6: "hour",
    7: "special",
    8: "hour",
}
SPELL_COMPONENT_LABELS = {1: "V", 2: "S", 3: "M"}


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
        "ability_blocks_json": _ability_blocks_json(scores, prof, mods),
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
        "spell_slots_json": "[]",
        "spell_slots_used_json": "{}",
        "spells_prepared": "",
        "spells_json": "[]",
    }

    if sheet["has_spellcasting"]:
        result["spellcasting_ability"] = sheet["spellcasting_ability"]
        result["spell_save_dc"] = sheet["spell_save_dc"]
        result["spell_attack"] = sheet["spell_attack"]
        result["spell_slots"] = sheet["spell_slots"]
        result["spell_slots_json"] = _spell_slots_json(data, _total_level(data))
        result["spell_slots_used_json"] = _spell_slots_used_json(data, _total_level(data))
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


def _ability_blocks_json(scores: dict[str, int], prof: int, mods: list[dict[str, Any]]) -> str:
    blocks: list[dict[str, Any]] = []
    for stat_key in ("str", "dex", "con", "int", "wis", "cha"):
        save_bonus = _ability_mod(scores[stat_key])
        save_proficient = _has_proficiency(mods, SAVE_SUBTYPES[stat_key])
        if save_proficient:
            save_bonus += prof
        skills: list[dict[str, Any]] = []
        for skill, ability in SKILLS.items():
            if ability != stat_key:
                continue
            expertise = _has_expertise(mods, skill)
            proficient = expertise or _has_proficiency(mods, skill)
            skills.append(
                {
                    "name": SKILL_LABELS[skill],
                    "bonus": _signed(_skill_bonus(skill, scores, prof, mods)),
                    "proficient": proficient,
                    "expertise": expertise,
                }
            )
        blocks.append(
            {
                "key": stat_key,
                "label": STAT_FULL_NAMES[stat_key],
                "score": scores[stat_key],
                "modifier": _signed(_ability_mod(scores[stat_key])),
                "save": {"bonus": _signed(save_bonus), "proficient": save_proficient},
                "skills": skills,
            }
        )
    return json.dumps(blocks, ensure_ascii=False)


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


def _action_detail_line(action: dict[str, Any], data: dict[str, Any]) -> str:
    snippet = _snippet_from_fields(
        action.get("snippet") or "",
        action.get("description") or "",
        data=data,
        placeholder_values={"limiteduse": action.get("limitedUse")},
    )
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
                buckets[_activation_bucket(action)].append(_action_detail_line(action, data))

    for action in data.get("customActions") or []:
        buckets[_activation_bucket(action)].append(_action_detail_line(action, data))

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
                snippet = _snippet_from_fields(
                    action.get("snippet") or "",
                    action.get("description") or "",
                    data=data,
                    placeholder_values={"limiteduse": limited},
                )
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
        snippet = _snippet_from_fields(
            definition.get("snippet") or "",
            definition.get("description") or "",
            data=data,
            level_scales=definition.get("levelScales"),
        )
        name = definition.get("name") or "Trait"
        lines.append(_named_detail_line(name, snippet))
    for cls in data.get("classes") or []:
        for feature in cls.get("classFeatures") or []:
            definition = feature.get("definition") or {}
            required = definition.get("requiredLevel") or 0
            if required and level < required:
                continue
            snippet = _snippet_from_fields(
                definition.get("snippet") or "",
                definition.get("description") or "",
                data=data,
                level_scales=definition.get("levelScales"),
            )
            name = definition.get("name") or "Feature"
            if snippet or name:
                lines.append(_named_detail_line(name, snippet))
    for feat in data.get("feats") or []:
        definition = feat.get("definition") or {}
        snippet = _snippet_from_fields(
            definition.get("snippet") or "",
            definition.get("description") or "",
            data=data,
            level_scales=definition.get("levelScales"),
        )
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


def _spell_slots_json(data: dict[str, Any], level: int) -> str:
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

    entries: list[dict[str, Any]] = []
    levels = sorted(set(maxes) | {lvl for lvl, slot in usage.items() if (slot.get("used") or 0) > 0})
    for lvl in levels:
        max_slots = maxes.get(lvl, 0)
        used = int((usage.get(lvl) or {}).get("used") or 0)
        if not max_slots:
            available = int((usage.get(lvl) or {}).get("available") or 0)
            max_slots = used + available
        if not max_slots:
            continue
        entries.append(
            {
                "level": lvl,
                "label": f"{lvl}{_ordinal_suffix(lvl)}",
                "max": max_slots,
            }
        )

    for slot in data.get("pactMagic") or []:
        lvl = int(slot.get("level") or 0)
        if lvl != 1:
            continue
        max_slots = int(slot.get("available") or 0) + int(slot.get("used") or 0)
        if not max_slots:
            continue
        entries.append(
            {
                "level": 0,
                "label": "Pact",
                "max": max_slots,
            }
        )

    return json.dumps(entries, ensure_ascii=False) if entries else "[]"


def _spell_slots_used_json(data: dict[str, Any], level: int) -> str:
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

    used_map: dict[str, int] = {}
    levels = sorted(set(maxes) | {lvl for lvl, slot in usage.items() if (slot.get("used") or 0) > 0})
    for lvl in levels:
        max_slots = maxes.get(lvl, 0)
        used = int((usage.get(lvl) or {}).get("used") or 0)
        if not max_slots:
            available = int((usage.get(lvl) or {}).get("available") or 0)
            max_slots = used + available
        if not max_slots:
            continue
        if used:
            used_map[str(lvl)] = used

    for slot in data.get("pactMagic") or []:
        lvl = int(slot.get("level") or 0)
        if lvl != 1:
            continue
        max_slots = int(slot.get("available") or 0) + int(slot.get("used") or 0)
        if not max_slots:
            continue
        used = int(slot.get("used") or 0)
        if used:
            used_map["0"] = used

    return json.dumps(used_map, ensure_ascii=False)


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


def _spell_casting_time(definition: dict[str, Any]) -> str:
    activation = definition.get("activation") or {}
    if not activation:
        return "—"
    count = int(activation.get("activationTime") or 1)
    kind = ACTIVATION_TYPE_LABELS.get(int(activation.get("activationType") or 1), "action")
    if count == 1:
        return f"1 {kind}"
    if kind in {"action", "bonus action", "reaction"}:
        return f"{count} {kind}s"
    return f"{count} {kind}"


def _spell_range_text(definition: dict[str, Any]) -> str:
    range_obj = definition.get("range") or {}
    origin = (range_obj.get("origin") or "").strip()
    range_value = int(range_obj.get("rangeValue") or 0)
    aoe_type = range_obj.get("aoeType")
    aoe_value = range_obj.get("aoeValue")

    if origin.lower() == "touch":
        text = "Touch"
    elif origin.lower() == "self" and not range_value:
        text = "Self"
    elif range_value:
        text = f"{range_value} ft."
    elif origin:
        text = origin
    else:
        text = "—"

    if aoe_type and aoe_value:
        text += f" ({aoe_value} ft. {str(aoe_type).lower()})"
    return text


def _spell_duration_text(definition: dict[str, Any]) -> str:
    duration = definition.get("duration") or {}
    duration_type = (duration.get("durationType") or "").strip()
    if duration_type.lower() == "instantaneous":
        return "Instantaneous"
    interval = int(duration.get("durationInterval") or 0)
    unit = (duration.get("durationUnit") or "").strip().lower()
    unit_text = unit or "round"
    if interval != 1 and not unit_text.endswith("s"):
        unit_text += "s"
    if duration_type.lower() == "concentration":
        if interval:
            return f"Concentration, up to {interval} {unit_text}"
        return "Concentration"
    if interval:
        return f"{interval} {unit_text}"
    return duration_type or "—"


def _spell_components_text(definition: dict[str, Any]) -> str:
    components = definition.get("components") or []
    labels = [SPELL_COMPONENT_LABELS.get(int(component), "") for component in components]
    labels = [label for label in labels if label]
    if labels:
        return ", ".join(labels)
    description = (definition.get("componentsDescription") or "").strip()
    return description or "—"


def _spell_hit_dc_text(definition: dict[str, Any], data: dict[str, Any]) -> str:
    mods = _active_modifiers(data)
    scores = _ability_scores(data, mods)
    prof = _proficiency_bonus(_total_level(data))
    spell_ability_id = _spellcasting_ability_id(data)
    spell_key = STAT_IDS.get(spell_ability_id or 5, "wis")
    spell_mod = _ability_mod(scores[spell_key])
    save_dc = str(8 + prof + spell_mod)

    if definition.get("attackType"):
        return f"{_signed(prof + spell_mod)} to hit"
    save_id = definition.get("saveDcAbilityId")
    if save_id:
        save_key = STAT_IDS.get(int(save_id), "str")
        return f"DC {save_dc} ({STAT_LABELS[save_key]})"
    return "—"


def _spell_plain_body(definition: dict[str, Any], *, data: dict[str, Any] | None = None) -> str:
    snippet = _snippet_from_fields(
        definition.get("snippet") or "",
        definition.get("description") or "",
        data=data,
        level_scales=definition.get("levelScales"),
    )
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
                    "casting_time": _spell_casting_time(definition),
                    "range": _spell_range_text(definition),
                    "hit_dc": _spell_hit_dc_text(definition, data),
                    "components": _spell_components_text(definition),
                    "duration": _spell_duration_text(definition),
                    "body": _spell_plain_body(definition, data=data),
                }
            )
    spells.sort(key=lambda item: (item["level"], item["name"].lower()))
    return spells


def _spells_json(data: dict[str, Any]) -> str:
    spells = _collect_spells(data)
    if not spells:
        return "[]"
    return json.dumps(spells, ensure_ascii=False)


def _snippet_from_fields(
    snippet: str,
    description: str,
    *,
    data: dict[str, Any] | None,
    level_scales: list[dict[str, Any]] | None = None,
    placeholder_values: dict[str, Any] | None = None,
) -> str:
    cleaned = _clean_snippet(snippet, data=data, level_scales=level_scales, placeholder_values=placeholder_values) if snippet else ""
    if _snippet_looks_broken(cleaned) and description:
        cleaned = _clean_snippet(description, data=data, level_scales=level_scales, placeholder_values=placeholder_values)
    elif not cleaned and description:
        cleaned = _clean_snippet(description, data=data, level_scales=level_scales, placeholder_values=placeholder_values)
    return cleaned


def _snippet_looks_broken(text: str) -> bool:
    return bool(re.search(r"(up to|within|for|equal to) ,|\{\{", text))


def _scale_from_level_scales(level_scales: list[dict[str, Any]] | None, level: int) -> int | None:
    if not level_scales:
        return None
    best: tuple[int, int] | None = None
    for scale in level_scales:
        required = int(scale.get("level") or 0)
        fixed = scale.get("fixedValue")
        if fixed is None or required > level:
            continue
        if best is None or required > best[0]:
            best = (required, int(fixed))
    return best[1] if best else None


def _safe_eval_arithmetic(expr: str) -> float:
    ops = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.USub: operator.neg,
    }

    def _eval(node: ast.AST) -> float:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.BinOp):
            return ops[type(node.op)](_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -_eval(node.operand)
        raise ValueError(expr)

    tree = ast.parse(expr.strip(), mode="eval")
    return _eval(tree.body)


def _substitute_placeholder_expr(expr: str, *, level: int, prof: int, scores: dict[str, int]) -> str:
    expr = re.sub(r"classlevel", str(level), expr, flags=re.I)
    expr = re.sub(r"proficiency", str(prof), expr, flags=re.I)
    return re.sub(
        r"modifier:(\w+)",
        lambda match: str(_ability_mod(scores.get(match.group(1), 10))),
        expr,
        flags=re.I,
    )


def _format_placeholder_number(value: int, *, unsigned: bool) -> str:
    if unsigned:
        return str(value)
    return _signed(value)


def _resolve_ddb_placeholder(
    token: str,
    *,
    level: int,
    prof: int,
    scores: dict[str, int],
    level_scales: list[dict[str, Any]] | None,
    placeholder_values: dict[str, Any] | None = None,
) -> str | None:
    unsigned = False
    if token.endswith("#unsigned"):
        unsigned = True
        token = token[:-9]

    token_key = token.lower()
    if placeholder_values and token_key in placeholder_values:
        value = placeholder_values[token_key]
        if isinstance(value, dict):
            uses = int(value.get("maxUses") or 0)
            if value.get("useProficiencyBonus"):
                uses += prof
            return str(uses) if uses else None
        if value not in (None, ""):
            return str(value)
        return None

    if token == "scalevalue":
        scale = _scale_from_level_scales(level_scales, level)
        return str(scale) if scale is not None else None

    if token.startswith("savedc:"):
        ability = token.split(":", 1)[1].split("@", 1)[0].lower()
        return str(8 + prof + _ability_mod(scores.get(ability, 10)))

    if token.startswith("spellattack:"):
        ability = token.split(":", 1)[1].split("@", 1)[0].lower()
        return _format_placeholder_number(prof + _ability_mod(scores.get(ability, 10)), unsigned=unsigned)

    if token.startswith("modifier:"):
        ability_part = token[len("modifier:") :]
        min_value: int | None = None
        if "@min:" in ability_part:
            ability, min_part = ability_part.split("@min:", 1)
            min_value = int(min_part)
        else:
            ability = ability_part.split("@", 1)[0]
        ability = ability.lower()
        bonus = _ability_mod(scores.get(ability, 10))
        if min_value is not None:
            bonus = max(bonus, min_value)
        return _format_placeholder_number(bonus, unsigned=unsigned)

    rounded = re.fullmatch(r"\((.+)\)@(roundup|rounddown)", token, flags=re.I)
    if rounded:
        expr = _substitute_placeholder_expr(rounded.group(1), level=level, prof=prof, scores=scores)
        value = _safe_eval_arithmetic(expr)
        if rounded.group(2).lower() == "roundup":
            value = math.ceil(value)
        else:
            value = math.floor(value)
        return _format_placeholder_number(int(value), unsigned=True)

    paren_expr = re.fullmatch(r"\((.+)\)([+*/-]\d+)?", token)
    if paren_expr:
        expr = _substitute_placeholder_expr(paren_expr.group(1), level=level, prof=prof, scores=scores)
        if paren_expr.group(2):
            expr += paren_expr.group(2)
        value = _safe_eval_arithmetic(expr)
        return _format_placeholder_number(int(value), unsigned=True)

    if re.fullmatch(r"[\w:+\-*/.()]+", token):
        expr = _substitute_placeholder_expr(token, level=level, prof=prof, scores=scores)
        value = _safe_eval_arithmetic(expr)
        return _format_placeholder_number(int(value), unsigned=True)

    return None


def _replace_ddb_placeholders(
    text: str,
    *,
    data: dict[str, Any],
    level_scales: list[dict[str, Any]] | None = None,
    placeholder_values: dict[str, Any] | None = None,
) -> str:
    mods = _active_modifiers(data)
    scores = _ability_scores(data, mods)
    level = _total_level(data)
    prof = _proficiency_bonus(level)

    def repl(match: re.Match[str]) -> str:
        resolved = _resolve_ddb_placeholder(
            match.group(1),
            level=level,
            prof=prof,
            scores=scores,
            level_scales=level_scales,
            placeholder_values=placeholder_values,
        )
        return resolved if resolved is not None else ""

    return re.sub(r"\{\{([^}]+)\}\}", repl, text)


def _clean_snippet(
    value: str,
    *,
    data: dict[str, Any] | None = None,
    level_scales: list[dict[str, Any]] | None = None,
    placeholder_values: dict[str, Any] | None = None,
) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    if data is not None:
        text = _replace_ddb_placeholders(text, data=data, level_scales=level_scales, placeholder_values=placeholder_values)
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


def _plain_action_detail_line(action: dict[str, Any], data: dict[str, Any]) -> str:
    snippet = _snippet_from_fields(
        action.get("snippet") or "",
        action.get("description") or "",
        data=data,
        placeholder_values={"limiteduse": action.get("limitedUse")},
    )
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
                buckets[_activation_bucket(action)].append(_plain_action_detail_line(action, data))

    for action in data.get("customActions") or []:
        buckets[_activation_bucket(action)].append(_plain_action_detail_line(action, data))

    return {key: "\n".join(lines) if lines else "" for key, lines in buckets.items()}


def _plain_actions(data: dict[str, Any], scores: dict[str, int], prof: int) -> str:
    lines = _plain_weapon_attack_lines(data, scores, prof)

    action_groups = data.get("actions") or {}
    if isinstance(action_groups, dict):
        for group in action_groups.values():
            if not group:
                continue
            for action in group:
                lines.append(_plain_action_detail_line(action, data))

    for action in data.get("customActions") or []:
        lines.append(_plain_action_detail_line(action, data))

    return "\n".join(lines) if lines else "—"


def _plain_limited_use(data: dict[str, Any]) -> str:
    limited = _limited_use(data)
    return limited if limited else "—"


def _plain_features(data: dict[str, Any], level: int) -> str:
    lines: list[str] = []
    for trait in ((data.get("race") or {}).get("racialTraits") or []):
        definition = trait.get("definition") or {}
        snippet = _snippet_from_fields(
            definition.get("snippet") or "",
            definition.get("description") or "",
            data=data,
            level_scales=definition.get("levelScales"),
        )
        name = definition.get("name") or "Trait"
        lines.append(_plain_named_detail_line(name, snippet))
    for cls in data.get("classes") or []:
        for feature in cls.get("classFeatures") or []:
            definition = feature.get("definition") or {}
            required = definition.get("requiredLevel") or 0
            if required and level < required:
                continue
            snippet = _snippet_from_fields(
                definition.get("snippet") or "",
                definition.get("description") or "",
                data=data,
                level_scales=definition.get("levelScales"),
            )
            name = definition.get("name") or "Feature"
            if snippet or name:
                lines.append(_plain_named_detail_line(name, snippet))
    for feat in data.get("feats") or []:
        definition = feat.get("definition") or {}
        snippet = _snippet_from_fields(
            definition.get("snippet") or "",
            definition.get("description") or "",
            data=data,
            level_scales=definition.get("levelScales"),
        )
        name = definition.get("name") or "Feat"
        lines.append(_plain_named_detail_line(name, snippet))
    return "\n".join(lines) if lines else "—"
