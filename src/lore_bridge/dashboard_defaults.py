"""Default NPC demographic tags and chart palettes for the lore dashboard."""

from __future__ import annotations

DEFAULT_MALE_TAGS = {"he/him"}
DEFAULT_FEMALE_TAGS = {"she/her"}
DEFAULT_NB_TAGS = {"they/them", "he/they", "she/they", "any/all"}
DEFAULT_PRONOUN_TAGS = DEFAULT_MALE_TAGS | DEFAULT_FEMALE_TAGS | DEFAULT_NB_TAGS
DEFAULT_GENDER_LABELS = ["he/him", "she/her", "non-binary"]
DEFAULT_GENDER_TARGETS = [0.45, 0.45, 0.10]

DEFAULT_RACE_TAGS = {
    "Aarakocra", "Aasimar", "Autognome", "Beast", "Bugbear", "Centaur", "Changeling",
    "Dhampir", "Dragon", "Dragonborn", "Drow", "Duergar", "Dwarf", "Elf", "Eladrin",
    "Fairy", "Fey", "Firbolg", "Genasi", "Giff", "Githyanki", "Githzerai", "Gnome",
    "Goblin", "Goliath", "Grung", "Harengon", "Half-elf", "Half-orc", "Halfling",
    "Hexblood", "Hobgoblin", "Human", "Kalashtar", "Kenku", "Kobold", "Leonin",
    "Lizardfolk", "Loxodon", "Minotaur", "Orc", "Owlin", "Plasmoid", "Reborn", "Satyr",
    "Shifter", "Simic Hybrid", "Tabaxi", "Thri-kreen", "Tiefling", "Tortle", "Triton",
    "Vedalken", "Verdan", "Warforged", "Yuan-ti",
}

DEFAULT_RACE_COLORS = {
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

OPINION_ORDER = [
    "Hostile", "Oppositional", "Wary", "Cool", "Neutral",
    "Favourable", "Friendly", "Allied", "Bonded",
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

PC_COLOR_PALETTE = [
    "#9d6bcd", "#efe9e0", "#383838", "#a67c52", "#3e9b6f", "#4682d6", "#d94f4f",
    "#ffd93d", "#4d96ff", "#6bcb77", "#e8651a", "#b48cff",
]
FACTION_COLOR_PALETTE = [
    "#e63946", "#7ec8e3", "#b48cff", "#6bcb77", "#ffd93d", "#5b9bd5", "#c0c0c0",
    "#e8651a", "#7a8490", "#c9a86c", "#383838", "#c42126",
]

GENDER_PIE_COLORS = ["#ff6b6b", "#6bcb77", "#4d96ff"]

DEFAULT_CONFIG: dict = {
    "title": "Campaign Lore Dashboard",
    "campaign_status": {"wiki_slug": "home-page"},
    "party_wealth_title": "Party wealth",
    "pc_mentions": {"groups": []},
    "npc_demographics": {
        "exclude_slugs": [],
        "creature_slugs": [],
    },
    "faction_mentions": {},
    "custom_tiles": [],
}
