from __future__ import annotations

import re
from functools import lru_cache
from importlib import resources
from typing import Any

_PRE_BLOCK_KEYS = {
    "skills",
    "proficiencies",
    "languages",
    "tools",
    "spell_slots",
    "spells_prepared",
}

_HTML_BLOCK_KEYS = {
    "features_traits",
}

_RAW_HTML_KEYS = {
    "avatar_img",
    "spellcasting_section",
    "combat_section",
}


def html_text(value: Any) -> str:
    text = str(value or "")
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_sheet(context: dict[str, Any]) -> str:
    context = dict(context)
    context["spellcasting_section"] = (
        _render_partial("spellcasting.html", context) if context.get("has_spellcasting") else ""
    )
    combat = str(context.get("combat_actions") or "").strip()
    context["combat_section"] = (
        f'<div class="ddb-section">\n{combat}\n</div>' if combat else ""
    )
    return _render_partial("sheet.html", context).strip()


def render_gm_features(context: dict[str, Any]) -> str:
    features = str(context.get("features_traits") or "").strip()
    if not features or features == "—":
        return ""
    return _render_partial("gm-features.html", context).strip()


def _render_partial(template_name: str, context: dict[str, Any]) -> str:
    rendered = _load_template(template_name)
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
    return rendered


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


@lru_cache(maxsize=8)
def _load_template(template_name: str) -> str:
    return (
        resources.files("lore_bridge.dndbeyond")
        .joinpath("templates", template_name)
        .read_text(encoding="utf-8")
    )
