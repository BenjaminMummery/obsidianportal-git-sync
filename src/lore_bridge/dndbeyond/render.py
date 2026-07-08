from __future__ import annotations

import html
import re
from functools import lru_cache
from importlib import resources
from typing import Any

_PRE_BLOCK_KEYS = {
    "saving_throws",
    "skills",
    "actions",
    "limited_use",
    "features_traits",
    "proficiencies",
    "languages",
    "tools",
    "equipment",
    "spell_slots",
    "spells_prepared",
}


def render_sheet(context: dict[str, Any]) -> str:
    template = _load_template()
    rendered = template
    for key, value in context.items():
        if key in _PRE_BLOCK_KEYS:
            rendered = rendered.replace(f"{{{{{key}}}}}", _pre_block(value))
        else:
            rendered = rendered.replace(f"{{{{{key}}}}}", html.escape(str(value or "")))
    rendered = re.sub(r"\{\{[a-z_]+\}\}", "", rendered)
    return rendered.strip()


def _pre_block(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text == "—":
        return "—"
    return html.escape(text).replace("\n", "<br>\n")


@lru_cache(maxsize=1)
def _load_template() -> str:
    return resources.files("lore_bridge.dndbeyond").joinpath("templates/sheet.html").read_text(encoding="utf-8")
