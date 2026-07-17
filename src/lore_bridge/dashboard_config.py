"""Load and merge lore-dashboard.json from the connected lore repo."""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from typing import Any

from lore_bridge.dashboard_defaults import (
    DEFAULT_CONFIG,
    DEFAULT_FEMALE_TAGS,
    DEFAULT_GENDER_LABELS,
    DEFAULT_GENDER_TARGETS,
    DEFAULT_MALE_TAGS,
    DEFAULT_NB_TAGS,
    DEFAULT_PRONOUN_TAGS,
    DEFAULT_RACE_COLORS,
    DEFAULT_RACE_TAGS,
    FACTION_COLOR_PALETTE,
    PC_COLOR_PALETTE,
)


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return re.sub(r"-+", "-", value).strip("-") or "untitled"


@dataclass
class DashboardConfig:
    raw: dict
    title: str
    campaign_status_slug: str
    party_wealth_title: str
    pc_groups: list[dict]
    pc_colors: dict[str, dict]
    npc_exclude_slugs: set[str]
    npc_creature_slugs: set[str]
    pronoun_tags: set[str]
    male_tags: set[str]
    female_tags: set[str]
    nb_tags: set[str]
    gender_labels: list[str]
    gender_targets: list[float]
    race_tags: set[str]
    race_colors: dict[str, str]
    faction_mentions: dict[str, dict]
    custom_tiles: list[dict]
    wiki_slugs_needed: set[str] = field(default_factory=set)

    def wiki_path(self, wiki_dir: str, slug: str, file_ext: str) -> str:
        return f"{wiki_dir.rstrip('/')}/wiki/{slug}{file_ext}"

    def campaign_status_path(self, wiki_dir: str, file_ext: str) -> str:
        return self.wiki_path(wiki_dir, self.campaign_status_slug, file_ext)


def _parse_pc_colors(raw: dict | None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for slug, val in (raw or {}).items():
        if isinstance(val, str):
            out[slug] = {"color": val}
        elif isinstance(val, dict):
            out[slug] = val
    return out


def load_dashboard_config(data: dict | None) -> DashboardConfig:
    merged = _deep_merge(DEFAULT_CONFIG, data or {})
    demo = merged.get("npc_demographics") or {}
    pronoun_tags = set(demo.get("pronoun_tags") or DEFAULT_PRONOUN_TAGS)
    male_tags = set(demo.get("male_tags") or DEFAULT_MALE_TAGS)
    female_tags = set(demo.get("female_tags") or DEFAULT_FEMALE_TAGS)
    nb_tags = set(demo.get("nb_tags") or DEFAULT_NB_TAGS)
    race_tags = set(demo.get("race_tags") or DEFAULT_RACE_TAGS)
    race_colors = {**DEFAULT_RACE_COLORS, **(demo.get("race_colors") or {})}
    for tag in demo.get("extra_race_tags") or []:
        race_tags.add(tag)
        race_colors.setdefault(tag, "#9a9288")

    cs = merged.get("campaign_status") or {}
    slug = cs.get("wiki_slug") or "home-page"
    wiki_slugs = {slug}
    for tile in merged.get("custom_tiles") or []:
        if tile.get("wiki_slug"):
            wiki_slugs.add(tile["wiki_slug"])

    pc_mentions = merged.get("pc_mentions") or {}

    return DashboardConfig(
        raw=merged,
        title=merged.get("title") or DEFAULT_CONFIG["title"],
        campaign_status_slug=slug,
        party_wealth_title=merged.get("party_wealth_title") or "Party wealth",
        pc_groups=list(pc_mentions.get("groups") or []),
        pc_colors=_parse_pc_colors(pc_mentions.get("colors")),
        npc_exclude_slugs=set(demo.get("exclude_slugs") or []),
        npc_creature_slugs=set(demo.get("creature_slugs") or []),
        pronoun_tags=pronoun_tags,
        male_tags=male_tags,
        female_tags=female_tags,
        nb_tags=nb_tags,
        gender_labels=list(demo.get("gender_labels") or DEFAULT_GENDER_LABELS),
        gender_targets=list(demo.get("gender_targets") or DEFAULT_GENDER_TARGETS),
        race_tags=race_tags,
        race_colors=race_colors,
        faction_mentions=dict(merged.get("faction_mentions") or {}),
        custom_tiles=list(merged.get("custom_tiles") or []),
        wiki_slugs_needed=wiki_slugs,
    )


def parse_config_json(text: str) -> dict:
    return json.loads(text)


def _pc_color_for_slugs(
    config: DashboardConfig,
    slugs: list[str],
    *,
    fallback: str,
) -> tuple[str, str | None]:
    for slug in slugs:
        style = config.pc_colors.get(slug) or {}
        if style.get("color"):
            return style["color"], style.get("borderColor")
    return fallback, None


def build_pc_mention_groups(characters: list[dict], config: DashboardConfig) -> list[dict]:
    pcs = [c for c in characters if c.get("is_pc")]
    slug_to_pc = {c["slug"]: c for c in pcs}
    groups: list[dict] = []
    used_slugs: set[str] = set()
    color_idx = 0

    def next_color() -> str:
        nonlocal color_idx
        c = PC_COLOR_PALETTE[color_idx % len(PC_COLOR_PALETTE)]
        color_idx += 1
        return c

    for g in config.pc_groups:
        slugs = g.get("character_slugs") or g.get("link_slugs") or []
        link_slugs = list(slugs)
        patterns = list(g.get("text_patterns") or [])
        if not patterns:
            for slug in link_slugs:
                pc = slug_to_pc.get(slug)
                if pc:
                    label = _pc_short_name(pc["name"])
                    patterns.append(rf"\b{re.escape(label)}(?:'s|'s)?\b")
        color = g.get("color")
        border = g.get("borderColor")
        if not color:
            color, border_from_slug = _pc_color_for_slugs(
                config, link_slugs, fallback=next_color()
            )
            if border is None:
                border = border_from_slug
        row = {
            "id": g.get("id") or _slugify(g.get("name") or link_slugs[0]),
            "name": g.get("name") or (slug_to_pc[link_slugs[0]]["name"] if link_slugs else "PC"),
            "color": color,
            "link_slugs": link_slugs,
            "text_patterns": patterns,
        }
        if border:
            row["borderColor"] = border
        groups.append(row)
        used_slugs.update(link_slugs)

    for pc in pcs:
        if pc["slug"] in used_slugs:
            continue
        label = _pc_short_name(pc["name"])
        color, border = _pc_color_for_slugs(
            config, [pc["slug"]], fallback=next_color()
        )
        row = {
            "id": pc["slug"],
            "name": label,
            "color": color,
            "link_slugs": [pc["slug"]],
            "text_patterns": [rf"\b{re.escape(label)}(?:'s|'s)?\b"],
        }
        if border:
            row["borderColor"] = border
        groups.append(row)
    return groups


def _pc_short_name(name: str) -> str:
    name = name.strip()
    if " " in name:
        return name.split()[0]
    return name[:20]


def _default_faction_text_patterns(name: str) -> list[str]:
    patterns = [rf"\b{re.escape(name)}\b"]
    if name.startswith("House "):
        short = name[6:].strip()
        if short:
            patterns.append(rf"\b{re.escape(short)}(?:'s|'s)?\b")
    return patterns


def build_faction_mention_groups(faction_entries: list[dict], config: DashboardConfig) -> list[dict]:
    groups: list[dict] = []
    for i, entry in enumerate(faction_entries):
        name = entry["name"]
        fid = _slugify(name)
        cfg = config.faction_mentions.get(name) or config.faction_mentions.get(fid) or {}
        color = cfg.get("color") or entry.get("color") or FACTION_COLOR_PALETTE[i % len(FACTION_COLOR_PALETTE)]
        patterns = _default_faction_text_patterns(name)
        for pattern in cfg.get("text_patterns") or []:
            if pattern not in patterns:
                patterns.append(pattern)
        groups.append({
            "id": fid,
            "name": name,
            "color": color,
            "link_slugs": list(cfg.get("link_slugs") or []),
            "wiki_pages": list(cfg.get("wiki_pages") or [name]),
            "text_patterns": patterns,
            **({"borderColor": cfg["borderColor"]} if cfg.get("borderColor") else {}),
        })
    return groups


def collect_repo_paths(
    config: DashboardConfig,
    *,
    characters_dir: str,
    wiki_dir: str,
    log_dir: str,
    file_ext: str,
    config_path: str,
    blob_paths: list[str],
) -> list[str]:
    needed: set[str] = {config_path}
    char_prefix = f"{characters_dir.rstrip('/')}/"
    log_prefix = f"{log_dir.rstrip('/')}/"
    for path in blob_paths:
        if path.startswith(char_prefix) and path.endswith(file_ext):
            needed.add(path)
        elif path.startswith(log_prefix) and path.endswith(file_ext):
            needed.add(path)
    for slug in config.wiki_slugs_needed:
        needed.add(config.wiki_path(wiki_dir, slug, file_ext))
    return sorted(needed)
