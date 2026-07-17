"""Campaign lore dashboard - generated live from the GitHub lore repo."""

from __future__ import annotations

import html
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone

from lore_bridge.dashboard_config import (
    DashboardConfig,
    build_faction_mention_groups,
    build_pc_mention_groups,
)
from lore_bridge.dashboard_defaults import (
    OPINION_COLORS,
    OPINION_ORDER,
    OPINION_SCORE,
    WEALTH_STYLES,
)


@dataclass
class LoreRepo:
    """In-memory snapshot of lore paths fetched from GitHub."""

    files: dict[str, str]
    config: DashboardConfig
    characters_dir: str = "lore/characters"
    wiki_dir: str = "lore/wiki"
    file_ext: str = ".textile"

    @property
    def log_dir(self) -> str:
        return f"{self.wiki_dir}/adventure-log"

    def read(self, path: str) -> str | None:
        return self.files.get(path)

    def wiki_page_path(self, slug: str) -> str:
        return self.config.wiki_path(self.wiki_dir, slug, self.file_ext)

    def character_paths(self) -> list[str]:
        prefix = f"{self.characters_dir}/"
        return sorted(
            p
            for p in self.files
            if p.startswith(prefix) and p.endswith(self.file_ext)
        )

    def adventure_log_paths(self) -> list[str]:
        prefix = f"{self.log_dir}/"
        return sorted(
            p
            for p in self.files
            if p.startswith(prefix) and p.endswith(self.file_ext)
        )


def race_bucket(tags: list[str], config: DashboardConfig) -> str | None:
    found = [t for t in tags if t in config.race_tags]
    return found[0] if found else None


def pronoun_bucket(tags: list[str], config: DashboardConfig) -> str | None:
    found = [t for t in tags if t in config.pronoun_tags]
    if not found:
        return None
    tag = found[0]
    if tag in config.male_tags:
        return "he/him"
    if tag in config.female_tags:
        return "she/her"
    return "non-binary"


def _path_stem(path: str, ext: str) -> str:
    name = path.rsplit("/", 1)[-1]
    if name.endswith(ext):
        return name[: -len(ext)]
    return name


def _npc_for_demographics(char: dict, config: DashboardConfig) -> bool:
    if char["is_pc"]:
        return False
    if char["slug"] in config.npc_exclude_slugs:
        return False
    if char["slug"] in config.npc_creature_slugs:
        return False
    return True


def parse_frontmatter(text: str) -> dict:
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 2:
        return {}
    fm_text = parts[1]
    fm: dict = {"tags": []}
    in_tags = False
    for line in fm_text.splitlines():
        if line.startswith("tags:"):
            in_tags = True
            rest = line[5:].strip()
            if rest and rest != "[]":
                fm["tags"].append(rest.strip("'\""))
            continue
        if in_tags:
            if line.strip().startswith("- "):
                fm["tags"].append(line.strip()[2:].strip("'\""))
            elif line.strip():
                in_tags = False
        m = re.match(r"^(\w+):\s*(.+)$", line)
        if m and not in_tags:
            fm[m.group(1)] = m.group(2).strip().strip("'\"")
    return fm


def load_characters(repo: LoreRepo) -> list[dict]:
    config = repo.config
    rows = []
    for path in repo.character_paths():
        text = repo.read(path)
        if not text:
            continue
        stem = _path_stem(path, repo.file_ext)
        fm = parse_frontmatter(text)
        tags = fm.get("tags") or []
        rows.append(
            {
                "slug": stem,
                "name": fm.get("name", stem),
                "is_pc": fm.get("is_player_character") == "true",
                "tags": tags,
                "pronoun": pronoun_bucket(tags, config),
                "race": race_bucket(tags, config),
                "creature": stem in config.npc_creature_slugs,
            }
        )
    return rows


def pct(n: int, d: int) -> str:
    return f"{100 * n / d:.0f}%" if d else "n/a"


def rounded_percents(counts: list[int], total: int) -> list[int]:
    """Integer percentages summing to 100 (largest remainder / Hamilton method)."""
    if not total:
        return [0] * len(counts)
    exact = [100 * n / total for n in counts]
    floors = [int(p) for p in exact]
    remainder = 100 - sum(floors)
    order = sorted(range(len(counts)), key=lambda i: exact[i] - floors[i], reverse=True)
    out = floors[:]
    for k in range(remainder):
        out[order[k]] += 1
    return out


def session_sort_key(stem: str, fm: dict) -> tuple:
    title = fm.get("title") or fm.get("name") or stem
    m = re.search(r"Session\s+(\d+)", title, re.I)
    if m:
        return (0, int(m.group(1)))
    post_time = fm.get("post_time") or ""
    return (1, post_time, stem)


def short_name(name: str) -> str:
    if " " in name:
        return name.split()[0]
    return name[:14]


def race_chart_data(characters: list[dict], config: DashboardConfig) -> dict:
    npcs = [
        c
        for c in characters
        if _npc_for_demographics(c, config) and c["race"]
    ]
    counts = Counter(c["race"] for c in npcs)
    labels = [race for race, _ in counts.most_common()]
    values = [counts[label] for label in labels]
    colors = [config.race_colors.get(label, "#9a9288") for label in labels]
    tagged_n = sum(values)
    untagged = [
        c["slug"]
        for c in characters
        if _npc_for_demographics(c, config) and not c["race"]
    ]
    return {
        "labels": labels,
        "counts": values,
        "percents": rounded_percents(values, tagged_n),
        "colors": colors,
        "tagged": tagged_n,
        "untagged": untagged,
    }


def gender_chart_data(characters: list[dict], config: DashboardConfig) -> dict:
    labels = config.gender_labels
    npcs = [
        c
        for c in characters
        if _npc_for_demographics(c, config) and c["pronoun"]
    ]
    counts = Counter(c["pronoun"] for c in npcs)
    values = [counts.get(label, 0) for label in labels]
    tagged_n = sum(values)
    untagged = [
        c["slug"]
        for c in characters
        if _npc_for_demographics(c, config) and not c["pronoun"]
    ]
    return {
        "labels": labels,
        "counts": values,
        "percents": rounded_percents(values, tagged_n),
        "targets": config.gender_targets,
        "tagged": tagged_n,
        "untagged": untagged,
    }


def inside_textile_link(body: str, pos: int) -> bool:
    link_start = max(body.rfind("[[", 0, pos), body.rfind("[:", 0, pos))
    if link_start == -1:
        return False
    close = body.find("]]", link_start)
    return close != -1 and close >= pos


def count_group_mentions(body: str, group: dict) -> int:
    total = 0
    for slug in group.get("link_slugs", []):
        total += len(re.findall(rf"\[:{re.escape(slug)}\s*\|", body))
    for page in group.get("wiki_pages", []):
        total += len(re.findall(rf"\[\[{re.escape(page)}\s*\|", body, re.I))
    for pattern in group.get("text_patterns", []):
        for match in re.finditer(pattern, body, re.I):
            if not inside_textile_link(body, match.start()):
                total += 1
    return total


def load_adventure_sessions(repo: LoreRepo) -> list[dict]:
    sessions: list[dict] = []
    for path in repo.adventure_log_paths():
        text = repo.read(path)
        if not text:
            continue
        fm = parse_frontmatter(text)
        body = text.split("---", 2)[-1] if text.startswith("---") else text
        stem = _path_stem(path, repo.file_ext)
        title = fm.get("title") or fm.get("name") or stem
        m = re.search(r"Session\s+(\d+)", title, re.I)
        session_num = int(m.group(1)) if m else None
        sessions.append(
            {
                "title": title,
                "session_num": session_num,
                "post_time": (fm.get("post_time") or "")[:10],
                "body": body,
                "sort": session_sort_key(stem, fm),
            }
        )
    sessions.sort(key=lambda s: s["sort"])
    return sessions


def strip_textile(text: str) -> str:
    text = re.sub(r"\[\[:[^\|]+\|([^\]]+)\]\]", r"\1", text)
    text = re.sub(r"\[\[[^\|]+\|([^\]]+)\]\]", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_campaign_status(repo: LoreRepo) -> dict:
    path = repo.config.campaign_status_path(repo.wiki_dir, repo.file_ext)
    text = repo.read(path)
    if not text:
        return {
            "wealth": {},
            "campaign": {},
            "factions": {"as_of": "", "entries": []},
            "status_as_of": "",
        }
    wealth_level = 3
    wealth_name = "Comfortable"
    m = re.search(r"Wealth level:.*?>\s*(\d+)\s*-\s*([^<]+)<", text, re.I)
    if m:
        wealth_level = int(m.group(1))
        wealth_name = m.group(2).strip()

    summary = ""
    sm = re.search(
        r"h[34]\. Current standing\s*\n+\*\*Wealth level:\*\*.*?\n\n(.+?)(?=\n\*Pending:|\nh[234]\.)",
        text,
        re.S,
    )
    if sm:
        summary = strip_textile(sm.group(1).strip())

    pending = ""
    pm = re.search(r"\*Pending:\*\s*(.+?)(?=\n\nh[234]\.)", text, re.S)
    if pm:
        pending = strip_textile(pm.group(1).strip())

    assets: list[str] = []
    am = re.search(r"h[34]\. Other assets\s*\n\n((?:\* .+\n?)+)", text)
    if am:
        for line in am.group(1).splitlines():
            if line.startswith("* "):
                assets.append(strip_textile(line[2:].strip()))

    status_as_of = ""
    wealth_as_of = re.search(
        r"h[23]\. Party Wealth\s*\n\n_Through Session (\d+) \(([^)]+)\)\._", text
    )
    if wealth_as_of:
        status_as_of = f"Session {wealth_as_of.group(1)} ({wealth_as_of.group(2)})"
    else:
        status_as_of_match = re.search(
            r"h[23]\. Campaign status\s*\n\n_Through Session (\d+) \(([^)]+)\)\._",
            text,
        )
        if status_as_of_match:
            status_as_of = (
                f"Session {status_as_of_match.group(1)} ({status_as_of_match.group(2)})"
            )

    campaign: dict = {}
    date_match = re.search(r"\*\*Current date:\*\*\s*([^\n]+)", text, re.I)
    if date_match:
        campaign["date"] = strip_textile(date_match.group(1).strip())
    session_match = re.search(r"\*\*As of session:\*\*\s*(\d+)", text, re.I)
    if session_match:
        campaign["session"] = int(session_match.group(1))
    if not campaign.get("date"):
        fallback = re.search(
            r"Through Session (\d+) \((\d+(?:st|nd|rd|th) [^)]+)\)", text, re.I
        )
        if fallback:
            campaign.setdefault("session", int(fallback.group(1)))
            campaign["date"] = fallback.group(2).strip()

    gm_match = re.search(r"GM_INFO_START -->(.*?)<!-- GM_INFO_END -->", text, re.S)
    gm = gm_match.group(1) if gm_match else ""

    as_of = ""
    ao = re.search(r"_Through Session (\d+) \(([^)]+)\)\._", gm)
    if ao:
        as_of = f"Session {ao.group(1)} ({ao.group(2)})"

    factions: list[dict] = []
    for line in gm.splitlines():
        fm = re.match(
            r"\|\s*\[\[[^\|]+\|([^\]]+)\]\]\s*\|\s*(\w+)\s*\|\s*(.+?)\s*\|\s*$",
            line.strip(),
        )
        if fm:
            name = fm.group(1).strip()
            opinion = fm.group(2).strip()
            rationale = strip_textile(fm.group(3).strip())
            factions.append(
                {
                    "name": name,
                    "opinion": opinion,
                    "rationale": rationale,
                    "score": OPINION_SCORE.get(opinion, 0),
                    "color": OPINION_COLORS.get(opinion, "#9a9288"),
                }
            )

    for i, entry in enumerate(factions):
        cfg = repo.config.faction_mentions.get(entry["name"]) or {}
        if cfg.get("color"):
            entry["color"] = cfg["color"]

    mention_groups = build_faction_mention_groups(factions, repo.config)
    color_by_name = {g["name"]: g["color"] for g in mention_groups}
    for entry in factions:
        entry["color"] = color_by_name.get(
            entry["name"], OPINION_COLORS.get(entry["opinion"], "#9a9288")
        )

    style = WEALTH_STYLES.get(wealth_level, WEALTH_STYLES[3])
    return {
        "wealth": {
            "level": wealth_level,
            "name": wealth_name,
            "style": style,
            "summary": summary,
            "pending": pending,
            "assets": assets,
        },
        "campaign": campaign,
        "factions": {"as_of": as_of, "entries": factions},
        "status_as_of": status_as_of,
    }


def _wiki_text(repo: LoreRepo, slug: str | None) -> str:
    if slug:
        return repo.read(repo.wiki_page_path(slug)) or ""
    return repo.read(repo.config.campaign_status_path(repo.wiki_dir, repo.file_ext)) or ""


def parse_stay_bar(text: str, tile: dict, status_as_of: str) -> dict:
    heading = tile.get("heading") or "Days remaining"
    heading_re = re.escape(heading).replace(r"\ ", r"\s+")
    stay_days: int | None = None
    stay_limit = int(tile.get("default_limit") or 36)
    stay_detail = ""
    stay_match = re.search(
        rf"h[34]\.\s*{heading_re}\s*\n+\*\*~?(\d+)\s*days?\*\*(.*)",
        text,
        re.S | re.I,
    )
    if stay_match:
        stay_days = int(stay_match.group(1))
        detail_line = stay_match.group(2).strip().split("\n")[0]
        stay_detail = strip_textile(detail_line)
    else:
        fallback = tile.get("fallback_pattern") or r"~(\d+)\s*days'? stay remaining"
        fb = re.search(fallback, text, re.I)
        if fb:
            stay_days = int(fb.group(1))

    limit_pattern = tile.get("limit_pattern") or r"(\d+)-day visitor limit"
    limit_match = re.search(limit_pattern, text, re.I)
    if limit_match:
        stay_limit = int(limit_match.group(1))

    return {
        "days": stay_days,
        "limit": stay_limit,
        "as_of": status_as_of,
        "detail": stay_detail,
    }


def parse_charge_count(text: str, tile: dict) -> dict:
    pattern = tile.get("pattern") or r"\*\*Stored charges:\*\*\s*(\d+)\s*(?:_\(([^)]+)\)_)?"
    m = re.search(pattern, text)
    if not m:
        return {}
    as_of = strip_textile(m.group(2).strip()) if m.lastindex and m.lastindex >= 2 and m.group(2) else ""
    return {"charges": int(m.group(1)), "as_of": as_of}


def parse_custom_tiles(repo: LoreRepo, status: dict) -> dict[str, dict]:
    cs_text = repo.read(repo.config.campaign_status_path(repo.wiki_dir, repo.file_ext)) or ""
    out: dict[str, dict] = {}
    for tile in repo.config.custom_tiles:
        tid = tile.get("id") or tile.get("title", "tile").lower().replace(" ", "-")
        ttype = tile.get("type")
        if ttype == "stay_bar":
            source = _wiki_text(repo, tile.get("wiki_slug")) or cs_text
            out[tid] = parse_stay_bar(source, tile, status.get("status_as_of", ""))
        elif ttype == "charge_count":
            out[tid] = parse_charge_count(_wiki_text(repo, tile.get("wiki_slug")), tile)
        else:
            out[tid] = {}
    return out


def faction_chart_data(adventurers: dict) -> dict:
    entries = adventurers["factions"]["entries"]
    return {
        "as_of": adventurers["factions"]["as_of"],
        "labels": [e["name"] for e in entries],
        "scores": [e["score"] for e in entries],
        "opinions": [e["opinion"] for e in entries],
        "colors": [e["color"] for e in entries],
        "max": len(OPINION_ORDER),
        "scale": OPINION_ORDER,
    }


def build_proportion_chart(sessions: list[dict], groups: list[dict], color_key: str) -> dict:
    labels = [s["title"] for s in sessions]
    series = []
    for i, group in enumerate(groups):
        proportions = []
        totals = []
        for s in sessions:
            n = s["counts"][group["id"]]
            totals.append(n)
            proportions.append(0 if s["total"] == 0 else round(n / s["total"], 4))
        color = group.get(color_key or "color", "#9a9288")
        row = {
            "id": group["id"],
            "name": group["name"],
            "fullName": group["name"],
            "color": color,
            "proportions": proportions,
            "totals": totals,
        }
        if group.get("borderColor"):
            row["borderColor"] = group["borderColor"]
        series.append(row)
    return {
        "sessions": [
            {
                "label": labels[i],
                "title": s["title"],
                "date": s["post_time"],
                "session_num": s.get("session_num"),
                "total": s["total"],
            }
            for i, s in enumerate(sessions)
        ],
        "series": series,
    }


def pc_mentions_chart_data(repo: LoreRepo, groups: list[dict]) -> dict:
    sessions = []
    for s in load_adventure_sessions(repo):
        counts = {g["id"]: count_group_mentions(s["body"], g) for g in groups}
        total = sum(counts.values())
        sessions.append({**s, "counts": counts, "total": total})
    return build_proportion_chart(sessions, groups, "color")


def faction_mentions_chart_data(repo: LoreRepo, groups: list[dict]) -> dict:
    sessions = []
    for s in load_adventure_sessions(repo):
        counts = {g["id"]: count_group_mentions(s["body"], g) for g in groups}
        total = sum(counts.values())
        sessions.append({**s, "counts": counts, "total": total})
    return build_proportion_chart(sessions, groups, "color")


def markdown_summary(
    gender: dict,
    race: dict,
    mentions: dict,
    faction: dict,
    wealth: dict,
    stay: dict,
    campaign: dict,
    greeting: dict,
    generated: str,
) -> str:
    counts = gender["counts"]
    tagged = gender["tagged"]
    male, female, nb = counts
    gender_pcts = gender.get("percents") or rounded_percents(counts, tagged)
    wl = wealth.get("level", "?")
    wn = wealth.get("name", "")
    lines = [
        "# Lore dashboard",
        "",
        f"_Auto-generated on {generated}. Open "
        "[lore-dashboard.html](lore-dashboard.html) for charts._",
        "",
    ]
    if campaign.get("date"):
        session = campaign.get("session")
        sess = f" (Session {session})" if session else ""
        lines.extend([f"## Current date{sess}", "", f"- {campaign['date']}", ""])
    lines.extend([
        "## NPC gender (tagged persons only; percents sum to 100% of pie)",
        "",
        f"- he/him: {male} ({gender_pcts[0]}%) - target 45%",
        f"- she/her: {female} ({gender_pcts[1]}%) - target 45%",
        f"- non-binary: {nb} ({gender_pcts[2]}%) - target 10%",
        f"- Untagged: {len(gender['untagged'])}",
        "",
        "## NPC race (tagged persons only; percents sum to 100% of pie)",
        "",
    ])
    race_tagged = race["tagged"]
    race_counts = race.get("counts", [])
    race_pcts = race.get("percents") or rounded_percents(race_counts, race_tagged)
    for label, count, pct_val in zip(race.get("labels", []), race_counts, race_pcts):
        lines.append(f"- {label}: {count} ({pct_val}%)")
    lines.extend([
        f"- Untagged: {len(race['untagged'])}",
        "",
        "## Party wealth",
        "",
        f"- Level {wl} - {wn}",
        "",
    ])
    if stay.get("days") is not None:
        lines.extend(
            [
                f"## Days remaining in Sindrel ({stay.get('as_of', 'unknown')})",
                "",
                f"- ~{stay['days']} of {stay.get('limit', 36)} days",
                "",
            ]
        )
    if greeting.get("charges") is not None:
        lines.extend(
            [
                "## The Journeyman's Answer",
                "",
                f"- {greeting['charges']} stored charge(s)",
            ]
        )
        if greeting.get("as_of"):
            lines.append(f"- {greeting['as_of']}")
        lines.append("")
    lines.extend(
        [
            "## PC & faction mention proportions",
            "",
            "See stacked proportion charts in HTML (wiki links plus plain-name mentions per session).",
            "",
            f"## Faction clocks ({faction.get('as_of', 'unknown')})",
            "",
        ]
    )
    for label, opinion in zip(faction.get("labels", []), faction.get("opinions", [])):
        lines.append(f"- {label}: {opinion}")
    lines.append("")
    return "\n".join(lines)


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>__TITLE__ - Lore dashboard</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
  <style>
    :root {
      --bg: #141110;
      --panel: #1e1a18;
      --ink: #ece8df;
      --muted: #9a9288;
      --border: #3a3433;
      --accent: #e85d5d;
      --code-bg: #2a2523;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      padding: 16px 20px 24px;
      font-family: Georgia, "Times New Roman", serif;
      background: var(--bg);
      color: var(--ink);
      line-height: 1.45;
    }
    h1 {
      font-family: "Cinzel", Georgia, serif;
      color: var(--accent);
      border-bottom: 3px double var(--accent);
      padding-bottom: 6px;
      margin: 0 0 4px;
      font-size: 1.5rem;
    }
    .meta {
      font-size: 12px;
      color: var(--muted);
      margin-bottom: 12px;
    }
    .meta code {
      background: var(--code-bg);
      padding: 2px 6px;
      border-radius: 3px;
      font-size: 12px;
    }
    .dashboard {
      display: grid;
      grid-template-columns: minmax(200px, 25%) 1fr;
      gap: 10px;
      align-items: stretch;
    }
    @media (max-width: 900px) {
      .dashboard { grid-template-columns: 1fr; }
    }
    .col-left, .col-right {
      display: flex;
      flex-direction: column;
      gap: 10px;
      min-width: 0;
      min-height: 0;
    }
    .col-right { flex: 1; }
    .col-right .panel { flex: 1; min-height: 200px; }
    .panel-row-demographics {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
      flex: 0 1 auto;
    }
    @media (max-width: 1100px) {
      .panel-row-demographics { grid-template-columns: 1fr; }
    }
    .panel-row-demographics .panel { flex: 1; min-height: 0; }
    .col-right .panel-gender, .col-right .panel-race { flex: 0 1 auto; min-height: 0; }
    .col-right .chart-wrap { flex: 1; min-height: 290px; }
    .panel {
      background: var(--panel);
      border: 1px solid var(--border);
      min-height: 0;
      display: flex;
      flex-direction: column;
    }
    .col-left .panel { padding: 8px 10px 10px; }
    .col-right .panel { padding: 10px 12px 12px; }
    .panel h2 {
      font-family: "Cinzel", Georgia, serif;
      color: var(--accent);
      margin: 0 0 6px;
      border-bottom: 1px solid var(--border);
      padding-bottom: 4px;
      flex-shrink: 0;
    }
    .col-left .panel h2 { font-size: 12px; margin-bottom: 4px; padding-bottom: 3px; }
    .col-right .panel h2 { font-size: 14px; }
    .panel p.note {
      font-size: 11px;
      color: var(--muted);
      margin: 0 0 6px;
      flex-shrink: 0;
    }
    .panel p.note code {
      background: var(--code-bg);
      padding: 1px 5px;
      border-radius: 3px;
      font-size: 12px;
    }
    .chart-wrap {
      position: relative;
      flex: 1;
      min-height: 0;
    }
    #genderChart, #raceChart { max-width: 100%; margin: 0 auto; }
    #mentionsChart, #factionMentionsChart { height: 100%; min-height: 290px; }
    #factionChart { height: 100%; min-height: 140px; }
    .panel-gender .chart-wrap, .panel-race .chart-wrap { flex: 1; min-height: 180px; max-height: 220px; }
    .panel-clocks .chart-wrap { flex: none; }
    .panel-clocks, .wealth-panel { flex: 0 1 auto; }
    .legend-target {
      font-size: 10px;
      color: var(--muted);
      margin-top: 4px;
      padding-top: 4px;
      border-top: 1px solid var(--border);
      flex-shrink: 0;
    }
    .legend-target span {
      display: inline-block;
      width: 28px;
      border-top: 2px dashed var(--accent);
      vertical-align: middle;
      margin-right: 6px;
    }
    ul.untagged {
      font-size: 10px;
      color: var(--muted);
      margin: 4px 0 0;
      padding-left: 16px;
      max-height: 48px;
      overflow-y: auto;
    }
    .stat-value {
      font-family: "Cinzel", Georgia, serif;
      font-weight: 600;
      line-height: 1.15;
      color: var(--ink);
      font-size: 0.95rem;
    }
    .stat-sub { font-size: 9px; color: var(--muted); margin-top: 2px; }
    .stay-number {
      font-family: "Cinzel", Georgia, serif;
      font-size: 1.35rem;
      font-weight: 600;
      line-height: 1;
    }
    .col-left .stay-bar { height: 4px; margin-top: 4px; }
    .stay-bar-fill { height: 100%; border-radius: 3px; }
    .stay-bar {
      height: 6px;
      background: var(--border);
      border-radius: 3px;
      margin-top: 6px;
      overflow: hidden;
    }
    .wealth-badge {
      display: inline-block;
      font-family: "Cinzel", Georgia, serif;
      font-size: 12px;
      font-weight: 600;
      padding: 4px 8px;
      border-radius: 3px;
      margin-top: 2px;
    }
    .wealth-detail {
      font-size: 10px;
      line-height: 1.45;
      color: var(--muted);
      margin-top: 8px;
    }
    .wealth-detail p { margin: 0 0 8px; }
    .wealth-detail ul {
      margin: 0;
      padding-left: 14px;
    }
    .wealth-detail li { margin-bottom: 4px; }
    .wealth-pending {
      font-size: 10px;
      color: var(--muted);
      border-left: 2px solid #ffd93d;
      padding-left: 6px;
      margin: 6px 0 0;
      line-height: 1.35;
    }
    .bridge-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 10px;
      margin-top: 4px;
    }
    .bridge-table td {
      padding: 3px 0;
      border-bottom: 1px solid var(--border);
      vertical-align: top;
    }
    .bridge-table td:last-child {
      text-align: right;
      color: var(--muted);
      white-space: nowrap;
    }
    .bridge-ok { color: #6bcb77; font-weight: 600; }
    .bridge-bad { color: #e85d5d; font-weight: 600; }
    .bridge-badge {
      display: inline-block;
      font-size: 9px;
      font-weight: 600;
      padding: 2px 6px;
      border-radius: 3px;
      background: #1b5e20;
      color: #c8e6c9;
      margin-bottom: 4px;
    }
    .bridge-job {
      margin-top: 6px;
      padding-top: 6px;
      border-top: 1px solid var(--border);
      font-size: 10px;
      color: var(--muted);
    }
    .bridge-progress {
      height: 4px;
      background: var(--border);
      border-radius: 3px;
      margin-top: 4px;
      overflow: hidden;
    }
    .bridge-progress-fill {
      height: 100%;
      background: var(--accent);
      border-radius: 3px;
    }
  </style>
</head>
<body>
  <h1>__TITLE__</h1>
  <p class="meta">Generated __GENERATED__ UTC from GitHub <code>__BRANCH__</code> · <a href="/health" style="color: var(--muted)">bridge status</a> · <a href="/docs" style="color: var(--muted)">API docs</a></p>

  <div class="dashboard">
    <div class="col-left">
      __LEFT_COLUMN__
    </div>

    <div class="col-right">
      <section class="panel panel-pc">
        <h2>PC mentions</h2>
        <div class="chart-wrap">
          <canvas id="mentionsChart"></canvas>
        </div>
      </section>

      <section class="panel panel-fc-mentions">
        <h2>Faction mentions</h2>
        <div class="chart-wrap">
          <canvas id="factionMentionsChart"></canvas>
        </div>
      </section>

      <div class="panel-row-demographics">
        <section class="panel panel-gender">
          <h2>NPC gender</h2>
          <p class="note">__GENDER_PIE_TOTAL__ in pie · __UNTAGGED__ untagged excluded from pie</p>
          <div class="chart-wrap">
            <canvas id="genderChart"></canvas>
          </div>
          __UNTAGGED_LIST__
        </section>

        <section class="panel panel-race">
          <h2>NPC race</h2>
          <p class="note">__RACE_PIE_TOTAL__ in pie · __RACE_UNTAGGED__ untagged excluded from pie</p>
          <div class="chart-wrap">
            <canvas id="raceChart"></canvas>
          </div>
          __RACE_UNTAGGED_LIST__
        </section>
      </div>
    </div>
  </div>

  <script>
    const genderData = __GENDER_JSON__;
    const raceData = __RACE_JSON__;
    const mentionsData = __MENTIONS_JSON__;
    const factionMentionsData = __FACTION_MENTIONS_JSON__;
    const factionData = __FACTION_JSON__;

    const chartText = "#ece8df";
    const chartGrid = "#3a3433";
    const chartMuted = "#9a9288";

    /** Percents of pie slices only — always sums to 100. */
    function pieSlicePercents(counts) {
      const total = counts.reduce((a, b) => a + b, 0);
      if (!total) return counts.map(() => 0);
      const exact = counts.map((n) => (100 * n) / total);
      const floors = exact.map((p) => Math.floor(p));
      let remainder = 100 - floors.reduce((a, b) => a + b, 0);
      const order = counts
        .map((_, i) => i)
        .sort((a, b) => (exact[b] - floors[b]) - (exact[a] - floors[a]));
      const out = floors.slice();
      for (let k = 0; k < remainder; k++) out[order[k]] += 1;
      return out;
    }

    function pieLegendLabel(name, count, percent) {
      return name + ": " + percent + "% (" + count + ")";
    }

    function pieLegendLabels(names, counts) {
      const percents = pieSlicePercents(counts);
      return names.map((name, i) => pieLegendLabel(name, counts[i], percents[i]));
    }

    const targetLinesPlugin = {
      id: "targetLines",
      afterDraw(chart) {
        if (chart.canvas.id !== "genderChart") return;
        const meta = chart.getDatasetMeta(0);
        if (!meta.data.length) return;
        const arc = meta.data[0];
        const cx = arc.x;
        const cy = arc.y;
        const r = arc.outerRadius;
        const start = -Math.PI / 2;
        const cumTargets = [0.45, 0.90];
        const ctx = chart.ctx;
        ctx.save();
        cumTargets.forEach((t) => {
          const angle = start + t * 2 * Math.PI;
          ctx.beginPath();
          ctx.moveTo(cx, cy);
          ctx.lineTo(cx + r * Math.cos(angle), cy + r * Math.sin(angle));
          ctx.strokeStyle = "#ffd93d";
          ctx.lineWidth = 2;
          ctx.setLineDash([7, 5]);
          ctx.stroke();
        });
        ctx.setLineDash([]);
        ctx.font = "11px Georgia, serif";
        ctx.fillStyle = "#ffd93d";
        cumTargets.forEach((t) => {
          const angle = start + t * 2 * Math.PI;
          const lx = cx + (r * 0.62) * Math.cos(angle);
          const ly = cy + (r * 0.62) * Math.sin(angle);
          ctx.fillText(Math.round(t * 100) + "%", lx - 10, ly + 4);
        });
        ctx.restore();
      },
    };

    new Chart(document.getElementById("genderChart"), {
      type: "pie",
      data: {
        labels: pieLegendLabels(genderData.labels, genderData.counts),
        datasets: [{
          data: genderData.counts,
          backgroundColor: ["#ff6b6b", "#6bcb77", "#4d96ff"],
          borderColor: "#1e1a18",
          borderWidth: 2,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            position: "bottom",
            labels: { color: chartText, font: { family: "Georgia, serif" } },
          },
          tooltip: {
            callbacks: {
              label(ctx) {
                const percents = pieSlicePercents(genderData.counts);
                const name = genderData.labels[ctx.dataIndex];
                const n = genderData.counts[ctx.dataIndex];
                return pieLegendLabel(name, n, percents[ctx.dataIndex]);
              },
              afterLabel(ctx) {
                const target = genderData.targets[ctx.dataIndex];
                return "Target: " + Math.round(target * 100) + "%";
              },
            },
          },
        },
      },
      plugins: [targetLinesPlugin],
    });

    new Chart(document.getElementById("raceChart"), {
      type: "pie",
      data: {
        labels: pieLegendLabels(raceData.labels, raceData.counts),
        datasets: [{
          data: raceData.counts,
          backgroundColor: raceData.colors,
          borderColor: "#1e1a18",
          borderWidth: 2,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            position: "bottom",
            labels: { color: chartText, font: { family: "Georgia, serif", size: 10 } },
          },
          tooltip: {
            callbacks: {
              label(ctx) {
                const percents = pieSlicePercents(raceData.counts);
                const name = raceData.labels[ctx.dataIndex];
                const n = raceData.counts[ctx.dataIndex];
                return pieLegendLabel(name, n, percents[ctx.dataIndex]);
              },
            },
          },
        },
      },
    });

    function proportionStackChart(canvasId, data, yTitle) {
      new Chart(document.getElementById(canvasId), {
        type: "line",
        data: {
          labels: data.sessions.map((s, i) =>
            "S" + (s.session_num != null ? s.session_num : i + 1)
          ),
          datasets: data.series.map((s) => ({
            label: s.name,
            data: s.proportions,
            borderColor: s.borderColor || s.color,
            backgroundColor: s.color + "cc",
            fill: true,
            stack: "proportions",
            tension: 0.35,
            pointRadius: 0,
            pointHoverRadius: 4,
            borderWidth: 1,
          })),
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: { mode: "nearest", intersect: false },
          scales: {
            x: {
              stacked: true,
              title: { display: false },
              ticks: {
                color: chartMuted,
                font: { family: "Georgia, serif", size: 9 },
                autoSkip: false,
              },
              grid: { color: chartGrid },
            },
            y: {
              stacked: true,
              min: 0,
              max: 1,
              title: { display: false },
              ticks: {
                color: chartMuted,
                font: { family: "Georgia, serif", size: 9 },
                callback: (v) => Math.round(v * 1000) / 10 + "%",
              },
              grid: { color: chartGrid },
            },
          },
          plugins: {
            legend: {
              position: "bottom",
              labels: {
                color: chartText,
                font: { family: "Georgia, serif", size: 9 },
                boxWidth: 8,
                padding: 4,
              },
            },
            tooltip: {
              mode: "nearest",
              intersect: false,
              callbacks: {
                title(items) {
                  const i = items[0].dataIndex;
                  const s = data.sessions[i];
                  return s.title + " (" + s.date + ")";
                },
                label(ctx) {
                  const s = data.series[ctx.datasetIndex];
                  const n = s.totals[ctx.dataIndex];
                  const p = Math.round(ctx.parsed.y * 1000) / 10;
                  return s.fullName + ": " + p + "% (" + n + " mentions)";
                },
              },
            },
          },
        },
      });
    }

    proportionStackChart("mentionsChart", mentionsData, "Share of mentions");
    proportionStackChart("factionMentionsChart", factionMentionsData, "Share of mentions");

    new Chart(document.getElementById("factionChart"), {
      type: "bar",
      data: {
        labels: factionData.labels,
        datasets: [{
          label: "Opinion",
          data: factionData.scores,
          backgroundColor: factionData.colors,
          borderColor: "#1e1a18",
          borderWidth: 1,
        }],
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: {
            min: 0,
            max: factionData.max + 0.4,
            title: { display: false },
            ticks: {
              color: chartMuted,
              font: { family: "Georgia, serif", size: 9 },
              stepSize: 1,
              callback: (v) => {
                const labels = ["", ...factionData.scale];
                return labels[v] || "";
              },
            },
            grid: { color: chartGrid },
          },
          y: {
            ticks: {
              color: chartMuted,
              font: { family: "Georgia, serif", size: 9 },
              autoSkip: false,
            },
            grid: { color: chartGrid },
          },
        },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label(ctx) {
                return factionData.opinions[ctx.dataIndex] + " (" + ctx.parsed.x + "/" + factionData.max + ")";
              },
            },
          },
        },
      },
    });
  </script>
  __BRIDGE_POLL_SCRIPT__
</body>
</html>
"""


def date_block(campaign: dict) -> str:
    if not campaign.get("date"):
        return '<p class="note">No date set.</p>'
    session = campaign.get("session")
    sub = f"Session {session}" if session else ""
    return (
        f'<div class="stat-value">{html.escape(campaign["date"])}</div>'
        f'<div class="stat-sub">{html.escape(sub)}</div>'
    )


def stay_block(stay: dict) -> str:
    if stay.get("days") is None:
        return '<p class="note">No stay data found.</p>'
    days = stay["days"]
    limit = stay.get("limit", 36)
    pct = min(100, max(0, round(100 * days / limit))) if limit else 0
    if days <= 7:
        color = "#e85d5d"
    elif days <= 14:
        color = "#ffd93d"
    else:
        color = "#7ec8e3"
    return (
        f'<div class="stay-number" style="color:{color}">~{days}</div>'
        f'<div class="stat-sub">of {limit} days</div>'
        f'<div class="stay-bar"><div class="stay-bar-fill" style="width:{pct}%;background:{color}"></div></div>'
    )


def wealth_block(wealth: dict) -> str:
    if not wealth:
        return '<p class="note">No wealth data found.</p>'
    s = wealth["style"]
    badge = (
        f'<div class="wealth-badge" style="background:{s["bg"]};color:{s["fg"]}">'
        f'{wealth["level"]} - {html.escape(wealth["name"])}</div>'
    )
    pending = ""
    if wealth.get("pending"):
        pending = (
            f'<p class="wealth-pending"><strong>Pending:</strong> '
            f'{html.escape(wealth["pending"])}</p>'
        )
    detail = f'<div class="wealth-detail">'
    if wealth.get("summary"):
        detail += f"<p>{html.escape(wealth['summary'])}</p>"
    if wealth.get("assets"):
        items = "".join(f"<li>{html.escape(a)}</li>" for a in wealth["assets"])
        detail += f"<ul>{items}</ul>"
    detail += "</div>"
    return badge + pending + detail


def charge_block(data: dict, tile: dict) -> str:
    if data.get("charges") is None:
        return '<p class="note">No charge data found.</p>'
    charges = data["charges"]
    singular = tile.get("label_singular") or "charge"
    plural = tile.get("label_plural") or "charges"
    label = singular if charges == 1 else plural
    sub = tile.get("sub_label") or f"stored {label}"
    sub = sub.replace("{label}", label).replace("{charges}", str(charges))
    as_of = data.get("as_of") or ""
    as_of_html = (
        f'<div class="stat-sub">{html.escape(as_of)}</div>' if as_of else ""
    )
    color = tile.get("color") or "#efe9e0"
    return (
        f'<div class="stay-number" style="color:{color}">{charges}</div>'
        f'<div class="stat-sub">{html.escape(sub)}</div>'
        f"{as_of_html}"
    )


def custom_tile_section(tile: dict, data: dict) -> str:
    title = html.escape(tile.get("title") or "Custom")
    tid = html.escape(tile.get("id") or "custom")
    ttype = tile.get("type")
    if ttype == "stay_bar":
        body = stay_block(data)
    elif ttype == "charge_count":
        body = charge_block(data, tile)
    else:
        body = '<p class="note">Unknown custom tile type.</p>'
    return (
        f'<section class="panel custom-tile-{tid}">'
        f"<h2>{title}</h2>{body}</section>"
    )


def build_left_column(
    config: DashboardConfig,
    *,
    bridge_block: str,
    campaign: dict,
    wealth: dict,
    faction_as_of: str,
    faction_chart_height_px: int,
    custom_tiles: dict[str, dict],
) -> str:
    sections: list[str] = [
        '<section class="panel panel-bridge">'
        "<h2>Lore bridge</h2>"
        f"{bridge_block}</section>",
        '<section class="panel status-date">'
        "<h2>Current date</h2>"
        f"{date_block(campaign)}</section>",
    ]

    def tiles_after(marker: str) -> None:
        for tile in config.custom_tiles:
            if (tile.get("after") or "date") == marker:
                tid = tile.get("id") or tile.get("title", "tile").lower().replace(" ", "-")
                sections.append(custom_tile_section(tile, custom_tiles.get(tid, {})))

    tiles_after("date")

    sections.append(
        '<section class="panel panel-clocks">'
        "<h2>Faction clocks</h2>"
        f'<p class="note">{html.escape(faction_as_of)}</p>'
        f'<div class="chart-wrap" style="height: {faction_chart_height_px}px">'
        '<canvas id="factionChart"></canvas></div></section>'
    )

    sections.append(
        '<section class="panel wealth-panel">'
        f"<h2>{html.escape(config.party_wealth_title)}</h2>"
        f"{wealth_block(wealth)}</section>"
    )

    tiles_after("wealth")
    tiles_after("end")

    return "\n\n      ".join(sections)


def _format_ts_display(value: str | None) -> str:
    if not value:
        return "never"
    return value.replace("T", " ").rstrip("Z") + " UTC"


def bridge_status_block(status: dict) -> tuple[str, str]:
    def mark(ok: bool) -> str:
        return f'<span class="{"bridge-ok" if ok else "bridge-bad"}">{"yes" if ok else "no"}</span>'

    portal_ts = html.escape(_format_ts_display(status.get("last_portal_pull")))
    publish_ts = html.escape(_format_ts_display(status.get("last_git_publish")))
    branch = html.escape(status.get("branch") or "main")
    version = html.escape(status.get("version") or "")

    rows = (
        f"<tr><td>Obsidian Portal</td><td>{mark(status.get('campaign_id_configured'))}</td></tr>"
        f"<tr><td>GitHub repo</td><td>{mark(status.get('github_configured'))}</td></tr>"
        f"<tr><td>Portal → GitHub</td><td>{portal_ts}</td></tr>"
        f"<tr><td>GitHub → Portal</td><td>{publish_ts}</td></tr>"
    )

    job_html = ""
    poll_script = ""
    job = status.get("active_job")
    if job and job.get("status") == "running":
        percent = job.get("percent")
        width = f"{percent}%" if percent is not None else "35%"
        kind = html.escape(job.get("kind_label") or job.get("kind") or "Sync")
        phase = html.escape(job.get("phase_label") or job.get("phase") or "Running")
        detail = html.escape(job.get("detail") or job.get("message") or "")
        count = ""
        if job.get("total"):
            count = f' <span id="bridge-sync-count">{job["current"]}/{job["total"]}</span>'
        job_html = (
            f'<div class="bridge-job" id="bridge-sync-panel" aria-live="polite">'
            f"<strong id=\"bridge-sync-kind\">{kind}</strong> · "
            f'<span id="bridge-sync-phase">{phase}</span>{count}'
            f'<div class="bridge-progress"><div class="bridge-progress-fill" id="bridge-sync-bar" '
            f'style="width:{width}"></div></div>'
            f'<div class="stat-sub" id="bridge-sync-detail">{detail}</div></div>'
        )
        poll_script = """
  <script>
    (function () {
      function fmt(ts) {
        if (!ts) return "never";
        try { return new Date(ts.endsWith("Z") ? ts : ts + "Z").toLocaleString(); }
        catch (e) { return ts; }
      }
      setInterval(function () {
        fetch("/health", { headers: { Accept: "application/json" } })
          .then(function (r) { return r.json(); })
          .then(function (data) {
            var job = data.active_job;
            if (!job || job.status !== "running") {
              var panel = document.getElementById("bridge-sync-panel");
              if (panel) location.reload();
              return;
            }
            document.getElementById("bridge-sync-kind").textContent = job.kind_label || job.kind;
            document.getElementById("bridge-sync-phase").textContent = job.phase_label || job.phase;
            var count = document.getElementById("bridge-sync-count");
            if (job.total) {
              if (!count) {
                count = document.createElement("span");
                count.id = "bridge-sync-count";
                document.getElementById("bridge-sync-phase").after(" ", count);
              }
              count.textContent = job.current + "/" + job.total;
            } else if (count) {
              count.remove();
            }
            var bar = document.getElementById("bridge-sync-bar");
            if (job.percent != null) {
              bar.style.width = job.percent + "%";
            }
            document.getElementById("bridge-sync-detail").textContent = job.detail || job.message || "";
          })
          .catch(function () {});
      }, 2000);
    })();
  </script>"""

    block = (
        f'<span class="bridge-badge">Running v{version}</span>'
        f'<p class="note">Branch <code>{branch}</code></p>'
        f'<table class="bridge-table">{rows}</table>'
        f"{job_html}"
    )
    return block, poll_script


def faction_chart_height(count: int) -> int:
    return max(240, count * 26 + 32)


def render_html(
    gender: dict,
    race: dict,
    mentions: dict,
    faction_mentions: dict,
    faction: dict,
    wealth: dict,
    campaign: dict,
    generated: str,
    *,
    config: DashboardConfig,
    custom_tiles: dict[str, dict],
    branch: str,
    bridge_status: dict,
) -> str:
    untagged_list = ""
    if gender["untagged"]:
        items = "".join(f"<li>{slug}</li>" for slug in gender["untagged"])
        untagged_list = (
            f'<p class="note"><strong>Untagged NPCs:</strong></p>'
            f'<ul class="untagged">{items}</ul>'
        )

    race_untagged_list = ""
    if race["untagged"]:
        items = "".join(f"<li>{slug}</li>" for slug in race["untagged"])
        race_untagged_list = (
            f'<p class="note"><strong>Untagged NPCs:</strong></p>'
            f'<ul class="untagged">{items}</ul>'
        )

    as_of = faction.get("as_of") or "As of latest GM notes"
    bridge_block, bridge_poll = bridge_status_block(bridge_status)
    left_column = build_left_column(
        config,
        bridge_block=bridge_block,
        campaign=campaign,
        wealth=wealth,
        faction_as_of=as_of,
        faction_chart_height_px=faction_chart_height(len(faction.get("labels", []))),
        custom_tiles=custom_tiles,
    )
    return (
        HTML_TEMPLATE.replace("__TITLE__", html.escape(config.title))
        .replace("__GENERATED__", generated)
        .replace("__BRANCH__", html.escape(branch))
        .replace("__LEFT_COLUMN__", left_column)
        .replace("__BRIDGE_POLL_SCRIPT__", bridge_poll)
        .replace("__GENDER_PIE_TOTAL__", str(sum(gender["counts"])))
        .replace("__UNTAGGED__", str(len(gender["untagged"])))
        .replace("__UNTAGGED_LIST__", untagged_list)
        .replace("__RACE_PIE_TOTAL__", str(sum(race["counts"])))
        .replace("__RACE_UNTAGGED__", str(len(race["untagged"])))
        .replace("__RACE_UNTAGGED_LIST__", race_untagged_list)
        .replace("__GENDER_JSON__", json.dumps(gender))
        .replace("__RACE_JSON__", json.dumps(race))
        .replace("__MENTIONS_JSON__", json.dumps(mentions))
        .replace("__FACTION_MENTIONS_JSON__", json.dumps(faction_mentions))
        .replace("__FACTION_JSON__", json.dumps(faction))
    )


def generate_dashboard_html(repo: LoreRepo, *, bridge_status: dict, branch: str) -> str:
    config = repo.config
    characters = load_characters(repo)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    gender = gender_chart_data(characters, config)
    race = race_chart_data(characters, config)
    pc_groups = build_pc_mention_groups(characters, config)
    status = parse_campaign_status(repo)
    faction_groups = build_faction_mention_groups(status["factions"]["entries"], config)
    mentions = pc_mentions_chart_data(repo, pc_groups)
    faction_mentions = faction_mentions_chart_data(repo, faction_groups)
    faction = faction_chart_data(status)
    custom_tiles = parse_custom_tiles(repo, status)
    return render_html(
        gender,
        race,
        mentions,
        faction_mentions,
        faction,
        status["wealth"],
        status["campaign"],
        generated,
        config=config,
        custom_tiles=custom_tiles,
        branch=branch,
        bridge_status=bridge_status,
    )
