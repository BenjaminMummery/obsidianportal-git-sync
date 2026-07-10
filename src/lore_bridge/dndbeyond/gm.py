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


def extract_gm_features_html(gm_info: str) -> str:
    """Return Features & Traits HTML from a legacy managed GM block."""
    gm_info = _normalize_gm_markers(gm_info)
    start = _GM_FEATURES_START_RE.search(gm_info)
    end = _GM_FEATURES_END_RE.search(gm_info)
    if not start or not end or end.start() <= start.end():
        return ""
    block = gm_info[start.end() : end.start()].strip()
    block = re.sub(r"^<notextile>\s*", "", block, flags=re.IGNORECASE)
    block = re.sub(r"\s*</notextile>\s*$", "", block, flags=re.IGNORECASE)
    match = re.search(
        r'<div class="ddb-block">(.*?)</div>\s*</div>\s*</div>\s*$',
        block,
        re.DOTALL | re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()
    cleaned = _DDB_SHEET_GM_RE.sub("", block).strip()
    return cleaned


def migrate_character_features(fm: dict, gm_info: str) -> tuple[dict, str]:
    """Move legacy GM Features & Traits into dynamic_sheet when missing."""
    extracted = extract_gm_features_html(gm_info)
    if not extracted:
        return fm, gm_info
    ds = dict(fm.get("dynamic_sheet") or {})
    if (ds.get("features_traits") or "").strip():
        return fm, _gm_features_narrative(gm_info)
    ds["features_traits"] = extracted
    updated = dict(fm)
    updated["dynamic_sheet"] = ds
    return updated, _gm_features_narrative(gm_info)
