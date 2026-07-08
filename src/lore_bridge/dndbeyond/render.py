from __future__ import annotations

import re
from functools import lru_cache
from importlib import resources
from typing import Any

_PRE_BLOCK_KEYS = {
    "saving_throws",
    "skills",
    "proficiencies",
    "languages",
    "tools",
    "spell_slots",
    "spells_prepared",
}

_HTML_BLOCK_KEYS = {
    "actions",
    "features_traits",
}

_RAW_HTML_KEYS = {
    "avatar_img",
}


def html_text(value: Any) -> str:
    text = str(value or "")
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_sheet(context: dict[str, Any]) -> str:
    template = _load_template()
    rendered = template
    for key, value in context.items():
        if key in _RAW_HTML_KEYS:
            rendered = rendered.replace(f"{{{{{key}}}}}", str(value or ""))
        elif key in _HTML_BLOCK_KEYS:
            rendered = rendered.replace(f"{{{{{key}}}}}", _html_block(value))
        elif key in _PRE_BLOCK_KEYS:
            rendered = rendered.replace(f"{{{{{key}}}}}", _pre_block(value))
        else:
            rendered = rendered.replace(f"{{{{{key}}}}}", html_text(value))
    rendered = re.sub(r"\{\{[a-z_]+\}\}", "", rendered)
    return rendered.strip()


def _pre_block(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text == "—":
        return "—"
    return html_text(text).replace("\n", "<br>\n")


def _html_block(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text == "—":
        return "—"
    return text.replace("\n", "<br>\n")


@lru_cache(maxsize=1)
def _load_template() -> str:
    return resources.files("lore_bridge.dndbeyond").joinpath("templates/sheet.html").read_text(encoding="utf-8")
