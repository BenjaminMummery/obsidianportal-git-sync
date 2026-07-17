"""Campaign lore dashboard - generated live from the GitHub lore repo."""

from __future__ import annotations

import html
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class LoreRepo:
    """In-memory snapshot of lore paths fetched from GitHub."""

    files: dict[str, str]
    characters_dir: str = "lore/characters"
    wiki_dir: str = "lore/wiki"
    file_ext: str = ".textile"

    @property
    def log_dir(self) -> str:
        return f"{self.wiki_dir}/adventure-log"

    @property
    def adventurers_path(self) -> str:
        return f"{self.wiki_dir}/wiki/the-adventurers{self.file_ext}"

    @property
    def journeymans_answer_path(self) -> str:
        return f"{self.wiki_dir}/wiki/the-journeymans-answer{self.file_ext}"

    def read(self, path: str) -> str | None:
        return self.files.get(path)

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

PRONOUN_TAGS = {
    "he/him",
    "she/her",
    "they/them",
    "he/they",
    "she/they",
    "any/all",
}
MALE_TAGS = {"he/him"}
FEMALE_TAGS = {"she/her"}
NB_TAGS = {"they/them", "he/they", "she/they", "any/all"}
GENDER_LABELS = ["he/him", "she/her", "non-binary"]
GENDER_TARGETS = [0.45, 0.45, 0.10]
RACE_TAGS = {
    "Aarakocra",
    "Aasimar",
    "Autognome",
    "Beast",
    "Bugbear",
    "Centaur",
    "Changeling",
    "Dhampir",
    "Dragon",
    "Dragonborn",
    "Drow",
    "Duergar",
    "Dwarf",
    "Elf",
    "Eladrin",
    "Fairy",
    "Fey",
    "Firbolg",
    "Genasi",
    "Giff",
    "Githyanki",
    "Githzerai",
    "Gnome",
    "Goblin",
    "Goliath",
    "Grung",
    "Harengon",
    "Half-elf",
    "Half-orc",
    "Halfling",
    "Hexblood",
    "Hobgoblin",
    "Human",
    "Kalashtar",
    "Kenku",
    "Kobold",
    "Leonin",
    "Lizardfolk",
    "Loxodon",
    "Minotaur",
    "Orc",
    "Owlin",
    "Plasmoid",
    "Reborn",
    "Satyr",
    "Shifter",
    "Simic Hybrid",
    "Tabaxi",
    "Thri-kreen",
    "Tiefling",
    "Tortle",
    "Triton",
    "Vedalken",
    "Verdan",
    "Warforged",
    "Yuan-ti",
}
RACE_COLORS = {
    "Human": "#ff6b6b",
    "Elf": "#6bcb77",
    "Dwarf": "#c0a060",
    "Halfling": "#ffd93d",
    "Gnome": "#4d96ff",
    "Half-elf": "#9d6bcd",
    "Half-orc": "#7ec8e3",
    "Tiefling": "#b48cff",
    "Dragonborn": "#e8651a",
    "Genasi": "#f4a261",
    "Kenku": "#64748b",
    "Lizardfolk": "#3d9b5a",
    "Drow": "#383838",
    "Tabaxi": "#c9a86c",
    "Fey": "#e85d9a",
}
CREATURE_SLUGS = {
    "zalatan",
    "razorbeak",
    "kithrak-the-black",
    "hunts-by-night",
    "pads-silently",
    "arise-to-victory-over-the-infidel-hoards",
    "nans",
    "tama",
    "kithrak-ii",
}

PC_MENTION_GROUPS = [
    {
        "id": "amanira",
        "name": "Amanira",
        "color": "#9d6bcd",
        "link_slugs": ["amanira"],
        "text_patterns": [r"\bAmanira(?:'s|'s)?\b"],
    },
    {
        "id": "ayr",
        "name": "Ayr",
        "color": "#efe9e0",
        "link_slugs": ["ayr"],
        "text_patterns": [r"\bAyr(?:'s|'s)?\b"],
    },
    {
        "id": "nakoma-kithrak",
        "name": "Nakoma / Kithrak",
        "color": "#383838",
        "borderColor": "#c8c4bc",
        "link_slugs": ["nakoma-deathwalker-mor-got-ha", "kithrak-ii"],
        "text_patterns": [
            r"Deathwalker(?:'s|'s)?",
            r"Mor['']got['']ha",
            r"\bDW(?:'s|'s)?\b",
            r"Kithrak(?:'s|'s)?\b",
        ],
    },
    {
        "id": "pin",
        "name": "Pin",
        "color": "#a67c52",
        "link_slugs": ["pin"],
        "text_patterns": [r"\bPin(?:'s|'s)?\b"],
    },
    {
        "id": "ros-tama",
        "name": "Ros / Tama",
        "color": "#3e9b6f",
        "link_slugs": ["rossin-ros-greyhirst", "tama"],
        "text_patterns": [
            r"\bRos(?:'s|'s)?\b",
            r"\bGreyhirst(?:'s|'s)?\b",
            r"\bTama(?:'s|'s)?\b",
            r"giant stoat",
            r"\bthe stoat\b",
            r"\bStoat(?:'s|'s)?\b",
        ],
    },
    {
        "id": "silrie",
        "name": "Silrie",
        "color": "#4682d6",
        "link_slugs": ["silrie-aegiskiir"],
        "text_patterns": [r"\bSilrie(?:'s|'s)?\b"],
    },
    {
        "id": "wilrin",
        "name": "Wilrin",
        "color": "#d94f4f",
        "link_slugs": ["wilrin-racenglade"],
        "text_patterns": [r"\bWilrin(?:'s|'s)?\b"],
    },
]

FACTION_MENTION_GROUPS = [
    {
        "id": "oestra",
        "name": "Oestra",
        "color": "#e63946",
        "link_slugs": ["house-oestra"],
        "wiki_pages": ["House Oestra"],
        "text_patterns": [r"House Oestra", r"\bOestra Leageur\b", r"\bthe Leageur\b"],
    },
    {
        "id": "meness",
        "name": "Meness",
        "color": "#7ec8e3",
        "link_slugs": ["house-meness"],
        "wiki_pages": ["House Meness"],
        "text_patterns": [r"House Meness", r"\bPanopticon\b"],
    },
    {
        "id": "goela",
        "name": "Goela",
        "color": "#b48cff",
        "link_slugs": ["house-goela"],
        "wiki_pages": ["House Goela"],
        "text_patterns": [r"House Goela"],
    },
    {
        "id": "grimbolg",
        "name": "Grimbolg",
        "color": "#6bcb77",
        "link_slugs": ["house-grimbolg"],
        "wiki_pages": ["House Grimbolg"],
        "text_patterns": [
            r"House Grimbolg",
            r"\bGrimbolg(?:'s|'s)?\b",
            r"\bCornucopia\b",
            r"\bAmalthean\b",
        ],
    },
    {
        "id": "beltus",
        "name": "Beltus",
        "color": "#ffd93d",
        "link_slugs": ["house-beltus", "beltan-institute"],
        "wiki_pages": ["House Beltus", "Beltan Institute"],
        "text_patterns": [r"House Beltus", r"\bBeltan Institute\b"],
    },
    {
        "id": "mabon",
        "name": "Mabon",
        "color": "#5b9bd5",
        "link_slugs": ["house-mabon"],
        "wiki_pages": ["House Mabon"],
        "text_patterns": [r"House Mabon"],
    },
    {
        "id": "lithra",
        "name": "Lithra",
        "color": "#c0c0c0",
        "link_slugs": ["house-lithra"],
        "wiki_pages": ["House Lithra"],
        "text_patterns": [r"House Lithra", r"\bEidolon\b"],
    },
    {
        "id": "anathemists",
        "name": "Anathemists",
        "color": "#e8651a",
        "wiki_pages": ["Anathemists"],
        "text_patterns": [r"\bAnathemists\b", r"\bAnathemist\b"],
    },
    {
        "id": "black-cats",
        "name": "Black Cats",
        "color": "#7a8490",
        "wiki_pages": ["The Black Cats"],
        "text_patterns": [r"\bBlack Cats\b"],
    },
    {
        "id": "city-cats",
        "name": "City Cats",
        "color": "#c9a86c",
        "wiki_pages": ["The City Cats"],
        "text_patterns": [
            r"\bCity Cats\b",
            r"\bcity cats\b",
            r"\bcity cat population\b",
            r"\bcats of Sindrel\b",
            r"\bWalks-Among-Us\b",
            r"\blocal feline populace\b",
        ],
    },
    {
        "id": "eighth-house",
        "name": "Eighth House",
        "color": "#383838",
        "borderColor": "#c8c4bc",
        "wiki_pages": ["The Eighth House"],
        "text_patterns": [
            r"\bEighth House\b",
            r"\bSamhain\b",
            r"\bnecromantic House\b",
            r"\bdefunct necromantic\b",
        ],
    },
    {
        "id": "vermillion-company",
        "name": "Vermillion Company",
        "color": "#c42126",
        "wiki_pages": ["The Vermillion Company"],
        "text_patterns": [r"\bVermillion Company\b", r"\bVermillion\b"],
    },
]

HOUSE_FACTION_IDS = {
    "oestra", "meness", "goela", "grimbolg", "beltus", "mabon", "lithra",
}

FACTION_CLOCK_COLORS: dict[str, str] = {}
for _g in FACTION_MENTION_GROUPS:
    FACTION_CLOCK_COLORS[_g["name"]] = _g["color"]
    for _page in _g.get("wiki_pages", []):
        FACTION_CLOCK_COLORS[_page] = _g["color"]
    if _g["id"] in HOUSE_FACTION_IDS:
        FACTION_CLOCK_COLORS[f"House {_g['name']}"] = _g["color"]

OPINION_ORDER = [
    "Hostile",
    "Oppositional",
    "Wary",
    "Cool",
    "Neutral",
    "Favourable",
    "Friendly",
    "Allied",
    "Bonded",
]

OPINION_SCORE = {name: i + 1 for i, name in enumerate(OPINION_ORDER)}

OPINION_COLORS = {
    "Hostile": "#c42126",
    "Oppositional": "#e63946",
    "Wary": "#ff9f43",
    "Cool": "#ffd93d",
    "Neutral": "#9a9288",
    "Favourable": "#8ecf9a",
    "Friendly": "#6bcb77",
    "Allied": "#3d9b5a",
    "Bonded": "#1e6b38",
}

WEALTH_STYLES = {
    1: {"bg": "#5e1013", "fg": "#ffcdd2", "name": "Strapped"},
    2: {"bg": "#8a4f00", "fg": "#ffe0b2", "name": "Scraping by"},
    3: {"bg": "#8a7010", "fg": "#fff9c4", "name": "Comfortable"},
    4: {"bg": "#1b5e20", "fg": "#c8e6c9", "name": "Well-funded"},
    5: {"bg": "#006064", "fg": "#b2ebf2", "name": "Opulent"},
}


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


def race_bucket(tags: list[str]) -> str | None:
    found = [t for t in tags if t in RACE_TAGS]
    return found[0] if found else None


def pronoun_bucket(tags: list[str]) -> str | None:
    found = [t for t in tags if t in PRONOUN_TAGS]
    if not found:
        return None
    tag = found[0]
    if tag in MALE_TAGS:
        return "he/him"
    if tag in FEMALE_TAGS:
        return "she/her"
    return "non-binary"


def _path_stem(path: str, ext: str) -> str:
    name = path.rsplit("/", 1)[-1]
    if name.endswith(ext):
        return name[: -len(ext)]
    return name


def load_characters(repo: LoreRepo) -> list[dict]:
    rows = []
    for path in repo.character_paths():
        text = repo.read(path)
        if not text:
            continue
        stem = _path_stem(path, repo.file_ext)
        fm = parse_frontmatter(text)
        rows.append(
            {
                "slug": stem,
                "name": fm.get("name", stem),
                "is_pc": fm.get("is_player_character") == "true",
                "tags": fm.get("tags") or [],
                "pronoun": pronoun_bucket(fm.get("tags") or []),
                "race": race_bucket(fm.get("tags") or []),
                "creature": stem in CREATURE_SLUGS,
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


def race_chart_data(characters: list[dict]) -> dict:
    npcs = [
        c
        for c in characters
        if not c["is_pc"] and not c["creature"] and c["race"]
    ]
    counts = Counter(c["race"] for c in npcs)
    labels = [race for race, _ in counts.most_common()]
    values = [counts[label] for label in labels]
    colors = [RACE_COLORS.get(label, "#9a9288") for label in labels]
    tagged_n = sum(values)
    untagged = [
        c["slug"]
        for c in characters
        if not c["is_pc"] and not c["creature"] and not c["race"]
    ]
    return {
        "labels": labels,
        "counts": values,
        "percents": rounded_percents(values, tagged_n),
        "colors": colors,
        "tagged": tagged_n,
        "untagged": untagged,
    }


def gender_chart_data(characters: list[dict]) -> dict:
    npcs = [
        c
        for c in characters
        if not c["is_pc"] and not c["creature"] and c["pronoun"]
    ]
    counts = Counter(c["pronoun"] for c in npcs)
    values = [counts.get(label, 0) for label in GENDER_LABELS]
    tagged_n = sum(values)
    untagged = [
        c["slug"]
        for c in characters
        if not c["is_pc"] and not c["creature"] and not c["pronoun"]
    ]
    return {
        "labels": GENDER_LABELS,
        "counts": values,
        "percents": rounded_percents(values, tagged_n),
        "targets": GENDER_TARGETS,
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


def parse_adventurers(repo: LoreRepo) -> dict:
    text = repo.read(repo.adventurers_path)
    if not text:
        return {
            "wealth": {},
            "stay": {},
            "campaign": {},
            "factions": {"as_of": "", "entries": []},
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

    stay_days: int | None = None
    stay_limit = 36
    stay_as_of = ""
    stay_detail = ""
    stay_match = re.search(
        r"h[34]\. Days remaining in Sindrel\s*\n+\*\*~?(\d+)\s*days?\*\*(.*)",
        text,
        re.S | re.I,
    )
    if stay_match:
        stay_days = int(stay_match.group(1))
        detail_line = stay_match.group(2).strip().split("\n")[0]
        stay_detail = strip_textile(detail_line)
    else:
        fallback = re.search(r"~(\d+)\s*days'? stay remaining", text, re.I)
        if fallback:
            stay_days = int(fallback.group(1))

    wealth_as_of = re.search(
        r"h[23]\. Party Wealth\s*\n\n_Through Session (\d+) \(([^)]+)\)\._", text
    )
    if wealth_as_of:
        stay_as_of = f"Session {wealth_as_of.group(1)} ({wealth_as_of.group(2)})"
    else:
        status_as_of = re.search(
            r"h[23]\. Campaign status\s*\n\n_Through Session (\d+) \(([^)]+)\)\._",
            text,
        )
        if status_as_of:
            stay_as_of = f"Session {status_as_of.group(1)} ({status_as_of.group(2)})"

    limit_match = re.search(r"(\d+)-day visitor limit", text, re.I)
    if limit_match:
        stay_limit = int(limit_match.group(1))

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
                    "color": FACTION_CLOCK_COLORS.get(
                        name, OPINION_COLORS.get(opinion, "#9a9288")
                    ),
                }
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
        "stay": {
            "days": stay_days,
            "limit": stay_limit,
            "as_of": stay_as_of,
            "detail": stay_detail,
        },
        "campaign": campaign,
        "factions": {"as_of": as_of, "entries": factions},
    }


def parse_journeymans_answer_charges(repo: LoreRepo) -> dict:
    text = repo.read(repo.journeymans_answer_path)
    if not text:
        return {}
    m = re.search(
        r"\*\*Stored charges:\*\*\s*(\d+)\s*(?:_\(([^)]+)\)_)?",
        text,
    )
    if not m:
        return {}
    as_of = strip_textile(m.group(2).strip()) if m.group(2) else ""
    return {"charges": int(m.group(1)), "as_of": as_of}


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


def pc_mentions_chart_data(repo: LoreRepo) -> dict:
    sessions = []
    for s in load_adventure_sessions(repo):
        counts = {g["id"]: count_group_mentions(s["body"], g) for g in PC_MENTION_GROUPS}
        total = sum(counts.values())
        sessions.append({**s, "counts": counts, "total": total})
    return build_proportion_chart(sessions, PC_MENTION_GROUPS, "color")


def faction_mentions_chart_data(repo: LoreRepo) -> dict:
    sessions = []
    for s in load_adventure_sessions(repo):
        counts = {
            g["id"]: count_group_mentions(s["body"], g)
            for g in FACTION_MENTION_GROUPS
        }
        total = sum(counts.values())
        sessions.append({**s, "counts": counts, "total": total})
    return build_proportion_chart(sessions, FACTION_MENTION_GROUPS, "color")


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
  <title>Lords of Sindrel - Lore dashboard</title>
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
  <h1>Lords of Sindrel</h1>
  <p class="meta">Generated __GENERATED__ UTC from GitHub <code>__BRANCH__</code> · <a href="/health" style="color: var(--muted)">bridge status</a> · <a href="/docs" style="color: var(--muted)">API docs</a></p>

  <div class="dashboard">
    <div class="col-left">
      <section class="panel panel-bridge">
        <h2>Lore bridge</h2>
        __BRIDGE_BLOCK__
      </section>

      <section class="panel status-date">
        <h2>Current date</h2>
        __DATE_BLOCK__
      </section>

      <section class="panel status-stay">
        <h2>Time remaining</h2>
        __STAY_BLOCK__
      </section>

      <section class="panel panel-clocks">
        <h2>Faction clocks</h2>
        <p class="note">__FACTION_AS_OF__</p>
        <div class="chart-wrap" style="height: __FACTION_CHART_HEIGHT__px">
          <canvas id="factionChart"></canvas>
        </div>
      </section>

      <section class="panel wealth-panel">
        <h2>Wonch wealth</h2>
        __WEALTH_BLOCK__
      </section>

      <section class="panel item-tracker-panel">
        <h2>The Journeyman's Answer</h2>
        __GREETING_BLOCK__
      </section>
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
          interaction: { mode: "index", intersect: false },
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


def greeting_block(greeting: dict) -> str:
    if greeting.get("charges") is None:
        return '<p class="note">No charge data found.</p>'
    charges = greeting["charges"]
    label = "charge" if charges == 1 else "charges"
    sub = f"stored {label} · +1 at dawn"
    as_of = greeting.get("as_of") or ""
    as_of_html = (
        f'<div class="stat-sub">{html.escape(as_of)}</div>' if as_of else ""
    )
    return (
        f'<div class="stay-number" style="color:#efe9e0">{charges}</div>'
        f'<div class="stat-sub">{sub}</div>'
        f"{as_of_html}"
    )


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
    stay: dict,
    campaign: dict,
    greeting: dict,
    generated: str,
    *,
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
    return (
        HTML_TEMPLATE.replace("__GENERATED__", generated)
        .replace("__BRANCH__", html.escape(branch))
        .replace("__BRIDGE_BLOCK__", bridge_block)
        .replace("__BRIDGE_POLL_SCRIPT__", bridge_poll)
        .replace("__GENDER_PIE_TOTAL__", str(sum(gender["counts"])))
        .replace("__UNTAGGED__", str(len(gender["untagged"])))
        .replace("__UNTAGGED_LIST__", untagged_list)
        .replace("__RACE_PIE_TOTAL__", str(sum(race["counts"])))
        .replace("__RACE_UNTAGGED__", str(len(race["untagged"])))
        .replace("__RACE_UNTAGGED_LIST__", race_untagged_list)
        .replace("__FACTION_AS_OF__", html.escape(as_of))
        .replace(
            "__FACTION_CHART_HEIGHT__",
            str(faction_chart_height(len(faction.get("labels", [])))),
        )
        .replace("__DATE_BLOCK__", date_block(campaign))
        .replace("__STAY_BLOCK__", stay_block(stay))
        .replace("__WEALTH_BLOCK__", wealth_block(wealth))
        .replace("__GREETING_BLOCK__", greeting_block(greeting))
        .replace("__GENDER_JSON__", json.dumps(gender))
        .replace("__RACE_JSON__", json.dumps(race))
        .replace("__MENTIONS_JSON__", json.dumps(mentions))
        .replace("__FACTION_MENTIONS_JSON__", json.dumps(faction_mentions))
        .replace("__FACTION_JSON__", json.dumps(faction))
    )


def generate_dashboard_html(repo: LoreRepo, *, bridge_status: dict, branch: str) -> str:
    characters = load_characters(repo)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    gender = gender_chart_data(characters)
    race = race_chart_data(characters)
    mentions = pc_mentions_chart_data(repo)
    faction_mentions = faction_mentions_chart_data(repo)
    adventurers = parse_adventurers(repo)
    faction = faction_chart_data(adventurers)
    return render_html(
        gender,
        race,
        mentions,
        faction_mentions,
        faction,
        adventurers["wealth"],
        adventurers["stay"],
        adventurers["campaign"],
        parse_journeymans_answer_charges(repo),
        generated,
        branch=branch,
        bridge_status=bridge_status,
    )
