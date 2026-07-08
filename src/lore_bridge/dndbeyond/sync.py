from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from lore_bridge.dndbeyond.fetch import DdbFetchError, fetch_character
from lore_bridge.dndbeyond.mapper import map_character
from lore_bridge.dndbeyond.render import render_sheet


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
            skipped += 1
            continue
        try:
            data = fetch_character(str(ddb_id))
            synced_at = datetime.now(timezone.utc)
            sheet_data = map_character(data, synced_at=synced_at)
            ddb_sheet = render_sheet(sheet_data)
            fm = dict(fm)
            fm["dndbeyond_synced_at"] = synced_at.strftime("%Y-%m-%dT%H:%M:%SZ")
            if not fm.get("dndbeyond_url"):
                fm["dndbeyond_url"] = f"https://www.dndbeyond.com/characters/{ddb_id}"
            new_content = rebuild_character_content(
                fm,
                ddb_sheet=ddb_sheet,
                description=parsed.get("description") or "",
                bio=parsed.get("bio") or "",
                gm_info=parsed.get("gm_info") or "",
            )
        except DdbFetchError as exc:
            errors.append({"path": path, "dndbeyond_id": str(ddb_id), "detail": str(exc)})
            if progress:
                progress.record_error(str(exc), phase="fetching_dndbeyond", path=path)
            continue
        except Exception as exc:
            errors.append({"path": path, "dndbeyond_id": str(ddb_id), "detail": str(exc)})
            if progress:
                progress.record_error(str(exc), phase="fetching_dndbeyond", path=path)
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
