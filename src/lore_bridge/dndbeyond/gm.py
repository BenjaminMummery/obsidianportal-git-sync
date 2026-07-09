from __future__ import annotations

import re

GM_FEATURES_START = "<!-- OP_DDB_GM_FEATURES -->"
GM_FEATURES_END = "<!-- OP_DDB_GM_FEATURES_END -->"

_GM_FEATURES_START_RE = re.compile(r"<!--\s*OP_DDB_GM_FEATURES\s*-->")
_GM_FEATURES_END_RE = re.compile(r"<!--\s*OP_DDB_GM_FEATURES_END\s*-->")
_DDB_SHEET_GM_RE = re.compile(
    r"<div class=\"ddb-sheet ddb-sheet-gm\">.*?</div>\s*</div>",
    re.DOTALL | re.IGNORECASE,
)


def _normalize_gm_markers(gm_info: str) -> str:
    """Repair typographic dashes that break HTML comment marker matching."""
    return (
        gm_info.replace("<!—", "<!--")
        .replace("—>", "-->")
        .replace("<!–", "<!--")
        .replace("–>", "-->")
    )


def _gm_features_narrative(gm_info: str) -> str:
    """Return GM narrative outside the managed features block."""
    gm_info = _normalize_gm_markers(gm_info)
    end_match = _GM_FEATURES_END_RE.search(gm_info)
    if end_match:
        return gm_info[end_match.end() :].lstrip()
    if GM_FEATURES_END in gm_info:
        return gm_info.split(GM_FEATURES_END, 1)[1].lstrip()
    cleaned = _DDB_SHEET_GM_RE.sub("", gm_info)
    cleaned = re.sub(r"<notextile>\s*</notextile>", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def merge_ddb_gm_features(gm_info: str, features_html: str) -> str:
    narrative = _gm_features_narrative(gm_info)

    if not features_html.strip():
        return narrative

    block = (
        f"{GM_FEATURES_START}\n"
        f"<notextile>\n{features_html.strip()}\n</notextile>\n"
        f"{GM_FEATURES_END}"
    )
    if narrative:
        return f"{block}\n\n{narrative}".strip()
    return block
