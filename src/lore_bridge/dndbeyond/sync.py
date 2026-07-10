from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from lore_bridge.dndbeyond.fetch import DdbFetchError, fetch_character
from lore_bridge.dndbeyond.gm import migrate_character_features, needs_feature_migration
from lore_bridge.dndbeyond.mapper import map_character, map_dynamic_sheet
from lore_bridge.dndbeyond.render import render_sheet

logger = logging.getLogger("lore_bridge")


class DdbSyncResult:
    def __init__(
        self,
        *,
        ok: bool = True,
        updated: int = 0,
        skipped: int = 0,
        errors: list[dict[str, str]] | None = None,
        committed: bool = False,
        commit_sha: str | None = None,
        message: str | None = None,
    ) -> None:
        self.ok = ok
        self.updated = updated
        self.skipped = skipped
        self.errors = errors or []
        self.committed = committed
        self.commit_sha = commit_sha
        self.message = message

    def model_dump(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "updated": self.updated,
            "skipped": self.skipped,
            "errors": self.errors,
            "committed": self.committed,
            "commit_sha": self.commit_sha,
            "message": self.message,
        }


def sync_from_dndbeyond_impl(
    *,
    gh_sync_files: Callable[[], list[str]],
    gh_get_file: Callable[[str], Any],
    gh_commit_changes: Callable[[str, list[Any], Any | None], str | None],
    parse_sync_file: Callable[[str], dict[str, Any]],
    rebuild_character_content: Callable[..., str],
    TreeChange: type,
    LORE_CHARACTERS_DIR: str,
    progress: Any | None = None,
    dynamic_sheet_template_id: str | None = None,
) -> DdbSyncResult:
    paths = sorted(
        path
        for path in gh_sync_files()
        if path.startswith(f"{LORE_CHARACTERS_DIR}/")
    )
    changes: list[Any] = []
    updated = 0
    skipped = 0
    errors: list[dict[str, str]] = []
    total = len(paths)

    for i, path in enumerate(paths, start=1):
        if progress:
            progress.phase("fetching_dndbeyond", current=i, total=total, path=path)
        file = gh_get_file(path)
        if not file:
            skipped += 1
            continue
        parsed = parse_sync_file(file.content)
        if parsed.get("kind") != "Character":
            skipped += 1
            continue
        fm = parsed["fm"]
        ddb_id = fm.get("dndbeyond_id")
        if not ddb_id:
            if not needs_feature_migration(fm, parsed.get("gm_info") or ""):
                skipped += 1
                continue
            fm, gm_info = migrate_character_features(dict(fm), parsed.get("gm_info") or "")
            new_content = rebuild_character_content(
                fm,
                ddb_sheet=parsed.get("ddb_sheet") or "",
                description=parsed.get("description") or "",
                bio=parsed.get("bio") or "",
                gm_info=gm_info,
            )
            if new_content == file.content:
                skipped += 1
                continue
            changes.append(TreeChange(path, new_content))
            updated += 1
            if progress:
                progress.phase("writing_github", current=i, total=total, path=path)
            continue
        try:
            data = fetch_character(str(ddb_id))
            synced_at = datetime.now(timezone.utc)
            sheet_data = map_character(data, synced_at=synced_at)
            ddb_sheet = render_sheet(sheet_data)
            fm = dict(fm)
            ds = map_dynamic_sheet(data, synced_at=synced_at)
            existing_ds = fm.get("dynamic_sheet") or {}
            if isinstance(existing_ds, dict):
                if existing_ds.get("hp_current") not in (None, ""):
                    ds["hp_current"] = str(existing_ds["hp_current"])
                if existing_ds.get("temp_hp") not in (None, ""):
                    ds["temp_hp"] = str(existing_ds["temp_hp"])
                if existing_ds.get("spell_slots_used_json") not in (None, ""):
                    ds["spell_slots_used_json"] = str(existing_ds["spell_slots_used_json"])
                if existing_ds.get("inspiration") not in (None, ""):
                    ds["inspiration"] = str(existing_ds["inspiration"])
                if existing_ds.get("companions_json") not in (None, "", "[]"):
                    ds["companions_json"] = str(existing_ds["companions_json"])
            fm["dynamic_sheet"] = ds
            fm, gm_info = migrate_character_features(fm, parsed.get("gm_info") or "")
            if dynamic_sheet_template_id:
                fm["dynamic_sheet_template_id"] = dynamic_sheet_template_id
            fm["dndbeyond_synced_at"] = synced_at.strftime("%Y-%m-%dT%H:%M:%SZ")
            if not fm.get("dndbeyond_url"):
                fm["dndbeyond_url"] = f"https://www.dndbeyond.com/characters/{ddb_id}"
            new_content = rebuild_character_content(
                fm,
                ddb_sheet=ddb_sheet,
                description=parsed.get("description") or "",
                bio=parsed.get("bio") or "",
                gm_info=gm_info,
            )
        except DdbFetchError as exc:
            errors.append({"path": path, "dndbeyond_id": str(ddb_id), "detail": str(exc)})
            if progress:
                progress.record_error(str(exc), phase="fetching_dndbeyond", path=path)
            continue
        except Exception as exc:
            logger.exception("DDB sync failed for %s / %s", path, ddb_id)
            detail = f"{type(exc).__name__}: {exc!r}"
            errors.append({"path": path, "dndbeyond_id": str(ddb_id), "detail": detail})
            if progress:
                progress.record_error(detail, phase="fetching_dndbeyond", path=path)
            continue

        if new_content != file.content:
            changes.append(TreeChange(path, new_content))
            updated += 1

    commit_sha = None
    if changes:
        if progress:
            progress.phase("committing_git", message=f"committing {len(changes)} D&D Beyond sheet(s)")
        commit_sha = gh_commit_changes(
            f"Sync from D&D Beyond ({updated} updated)",
            changes,
            progress,
        )

    if progress:
        progress.phase("done", message=f"updated={updated} skipped={skipped} errors={len(errors)}")

    return DdbSyncResult(
        ok=not errors,
        updated=updated,
        skipped=skipped,
        errors=errors,
        committed=bool(commit_sha),
        commit_sha=commit_sha,
        message="Synced D&D Beyond sheets into GitHub" if not errors else "D&D Beyond sync finished with errors",
    )
