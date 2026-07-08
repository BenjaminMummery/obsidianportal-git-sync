from __future__ import annotations

GM_FEATURES_START = "<!-- OP_DDB_GM_FEATURES -->"
GM_FEATURES_END = "<!-- OP_DDB_GM_FEATURES_END -->"


def merge_ddb_gm_features(gm_info: str, features_html: str) -> str:
    if not features_html.strip():
        if GM_FEATURES_START in gm_info and GM_FEATURES_END in gm_info:
            before, rest = gm_info.split(GM_FEATURES_START, 1)
            _, after = rest.split(GM_FEATURES_END, 1)
            merged = (before.rstrip() + "\n\n" + after.lstrip()).strip()
            return merged
        return gm_info

    block = (
        f"{GM_FEATURES_START}\n"
        f"<notextile>\n{features_html.strip()}\n</notextile>\n"
        f"{GM_FEATURES_END}"
    )
    if GM_FEATURES_START in gm_info and GM_FEATURES_END in gm_info:
        before, rest = gm_info.split(GM_FEATURES_START, 1)
        _, after = rest.split(GM_FEATURES_END, 1)
        parts = [before.rstrip(), block, after.lstrip()]
        return "\n\n".join(part for part in parts if part).strip()

    if gm_info.strip():
        return f"{block}\n\n{gm_info.strip()}"
    return block
