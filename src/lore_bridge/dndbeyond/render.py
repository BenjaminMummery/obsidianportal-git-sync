from __future__ import annotations

import re
from functools import lru_cache
from importlib import resources
from typing import Any

_PRE_BLOCK_KEYS = {
    "proficiencies",
    "languages",
    "tools",
    "spell_slots",
    "spells_prepared",
    "limited_use",
}

_HTML_BLOCK_KEYS = {
    "features_traits",
    "skills",
}

_RAW_HTML_KEYS = {
    "avatar_img",
    "spellcasting_section",
    "combat_section",
    "limited_use_section",
    "status_section",
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
    limited_use = str(context.get("limited_use") or "").strip()
    context["limited_use_section"] = (
        '<div class="ddb-section">\n'
        '<h2 class="ddb-section-title">Class Resources</h2>\n'
        f'<div class="ddb-block">{_pre_block(limited_use)}</div>\n'
        "</div>"
        if limited_use
        else ""
    )
    conditions = str(context.get("conditions") or "").strip()
    death_saves = str(context.get("death_saves") or "").strip()
    status_parts: list[str] = []
    if conditions:
        status_parts.append(
            f'<div class="ddb-kv"><span class="ddb-label">Conditions</span>'
            f'<span class="ddb-kv-value">{html_text(conditions)}</span></div>'
        )
    if death_saves:
        status_parts.append(
            f'<div class="ddb-kv"><span class="ddb-label">Death Saves</span>'
            f'<span class="ddb-kv-value">{html_text(death_saves)}</span></div>'
        )
    context["status_section"] = (
        f'<div class="ddb-status-row">{"".join(status_parts)}</div>' if status_parts else ""
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
