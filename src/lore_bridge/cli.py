from __future__ import annotations

import json
import os
from typing import Any

import typer
from dotenv import load_dotenv

from lore_bridge.client import BridgeClient, BridgeError
from lore_bridge.git_ops import GitError, default_git_branch, default_git_remote, git_branch, git_pull_ff, git_push

app = typer.Typer(
    name="lore-bridge",
    help="CLI for the Obsidian Portal ↔ GitHub lore sync bridge (run from your lore repo clone).",
    no_args_is_help=True,
)


def _load_client() -> BridgeClient:
    load_dotenv()
    base_url = os.environ.get("LORE_BRIDGE_URL", "").strip()
    api_key = os.environ.get("LORE_BRIDGE_API_KEY", "").strip()
    if not base_url:
        typer.secho("LORE_BRIDGE_URL is not set.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    if not api_key:
        typer.secho("LORE_BRIDGE_API_KEY is not set.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    return BridgeClient(base_url, api_key)


def _print_job(job: dict[str, Any]) -> None:
    detail = job.get("current_title") or job.get("current_path") or ""
    line = (
        f"[{job['status']}] {job.get('phase', '')} "
        f"{job.get('current', 0)}/{job.get('total', 0)} {detail}".rstrip()
    )
    typer.echo(line)
    if job.get("message"):
        typer.echo(f"  {job['message']}")
    for err in job.get("errors") or []:
        label = err.get("path") or err.get("op_id") or "error"
        typer.echo(f"  error: {label}: {err.get('detail')}")


def _job_payload(job: dict[str, Any]) -> dict[str, Any]:
    if job.get("result") is not None:
        return job["result"]
    return job


def _print_result(payload: dict[str, Any]) -> None:
    typer.echo(json.dumps(payload, indent=2))


def _check_publish_conflicts(payload: dict[str, Any]) -> None:
    conflicts = payload.get("conflicts") or []
    if conflicts:
        typer.secho(f"Publish finished with {len(conflicts)} conflict(s).", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)


def _sync_from_op(
    *,
    git_pull: bool,
    async_mode: bool,
) -> None:
    client = _load_client()
    typer.echo(f"Triggering portal → GitHub sync at {client.base_url}/sync/from-portal ...")
    try:
        job = client.pull_from_portal(async_mode=async_mode, on_update=_print_job)
    except BridgeError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc

    payload = _job_payload(job)
    _print_result(payload)

    if git_pull:
        typer.echo("Updating local clone (git pull --ff-only) ...")
        try:
            git_pull_ff()
        except GitError as exc:
            typer.secho(str(exc), fg=typer.colors.RED, err=True)
            raise typer.Exit(1) from exc


def _sync_to_op(
    *,
    do_push: bool,
    git_pull: bool,
    async_mode: bool,
    remote: str,
    branch: str | None,
) -> None:
    target_branch = branch or default_git_branch()
    client = _load_client()

    if do_push:
        current = git_branch()
        if current != target_branch:
            typer.secho(
                f"Warning: you are on branch {current!r} but pushing {remote}/{target_branch}.",
                fg=typer.colors.YELLOW,
            )
        typer.echo(f"Pushing {remote}/{target_branch} ...")
        try:
            git_push(remote, target_branch)
        except GitError as exc:
            typer.secho(str(exc), fg=typer.colors.RED, err=True)
            raise typer.Exit(1) from exc

    typer.echo(f"Publishing GitHub → Obsidian Portal at {client.base_url}/sync/publish-main ...")
    try:
        job = client.publish_main(async_mode=async_mode, on_update=_print_job)
    except BridgeError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc

    payload = _job_payload(job)
    _print_result(payload)
    _check_publish_conflicts(payload)

    if git_pull:
        typer.echo("Updating local clone (git pull --ff-only) ...")
        try:
            git_pull_ff()
        except GitError as exc:
            typer.secho(str(exc), fg=typer.colors.RED, err=True)
            raise typer.Exit(1) from exc


@app.command("ddb-sync")
def ddb_sync(
    git_pull: bool = typer.Option(True, "--git-pull/--no-git-pull", help="Fast-forward local clone after bridge sync."),
    publish: bool = typer.Option(False, "--publish", help="Publish to Obsidian Portal after syncing D&D Beyond → GitHub."),
    async_mode: bool = typer.Option(True, "--async/--blocking", help="Use async job with progress polling."),
) -> None:
    """Refresh D&D Beyond sheet HTML in linked character files (GitHub), then optionally publish to OP."""
    client = _load_client()
    typer.echo(f"Syncing D&D Beyond → GitHub at {client.base_url}/sync/from-dndbeyond ...")
    try:
        job = client.sync_from_dndbeyond(async_mode=async_mode, on_update=_print_job)
    except BridgeError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc

    payload = _job_payload(job)
    _print_result(payload)

    errors = payload.get("errors") or []
    if errors:
        typer.secho(f"D&D Beyond sync finished with {len(errors)} error(s).", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    if git_pull:
        typer.echo("Updating local clone (git pull --ff-only) ...")
        try:
            git_pull_ff()
        except GitError as exc:
            typer.secho(str(exc), fg=typer.colors.RED, err=True)
            raise typer.Exit(1) from exc

    if publish:
        _sync_to_op(do_push=False, git_pull=git_pull, async_mode=async_mode, remote=default_git_remote(), branch=None)


@app.command("from-op")
def from_op(
    git_pull: bool = typer.Option(True, "--git-pull/--no-git-pull", help="Fast-forward local clone after bridge sync."),
    async_mode: bool = typer.Option(True, "--async/--blocking", help="Use async job with progress polling."),
) -> None:
    """Sync from Obsidian Portal: trigger bridge pull, wait for completion, then git pull --ff-only."""
    _sync_from_op(git_pull=git_pull, async_mode=async_mode)


@app.command("to-op")
def to_op(
    git_push: bool = typer.Option(True, "--git-push/--no-git-push", help="Push lore repo branch to remote before publish."),
    git_pull: bool = typer.Option(True, "--git-pull/--no-git-pull", help="Fast-forward local clone after publish."),
    async_mode: bool = typer.Option(True, "--async/--blocking", help="Use async job with progress polling."),
    remote: str = typer.Option(default_git_remote(), "--remote", "-r", help="Git remote to push (default: origin)."),
    branch: str | None = typer.Option(None, "--branch", "-b", help="Branch to push (default: LORE_GIT_BRANCH or main)."),
) -> None:
    """Sync to Obsidian Portal: git push, publish via bridge, wait for completion, then git pull --ff-only."""
    _sync_to_op(do_push=git_push, git_pull=git_pull, async_mode=async_mode, remote=remote, branch=branch)


@app.command()
def pull(
    git_pull: bool = typer.Option(True, "--git-pull/--no-git-pull"),
    async_mode: bool = typer.Option(True, "--async/--blocking"),
) -> None:
    """Alias for from-op."""
    _sync_from_op(git_pull=git_pull, async_mode=async_mode)


@app.command()
def publish(
    git_push: bool = typer.Option(True, "--git-push/--no-git-push"),
    git_pull: bool = typer.Option(True, "--git-pull/--no-git-pull"),
    async_mode: bool = typer.Option(True, "--async/--blocking"),
    remote: str = typer.Option(default_git_remote(), "--remote", "-r"),
    branch: str | None = typer.Option(None, "--branch", "-b"),
) -> None:
    """Alias for to-op."""
    _sync_to_op(do_push=git_push, git_pull=git_pull, async_mode=async_mode, remote=remote, branch=branch)


@app.command()
def help() -> None:
    """Show setup, commands, and typical workflows."""
    load_dotenv()
    bridge_url = os.environ.get("LORE_BRIDGE_URL", "").strip() or "(not set)"
    branch = default_git_branch()
    remote = default_git_remote()
    typer.echo(
        f"""lore-bridge — Obsidian Portal ↔ GitHub lore sync (run from your lore repo clone)

Setup (.env in repo root, not committed):
  LORE_BRIDGE_URL={bridge_url}
  LORE_BRIDGE_API_KEY=<your bridge API key>
  LORE_GIT_REMOTE={remote}
  LORE_GIT_BRANCH={branch}

Commands:
  status              Bridge health and last sync times
  from-op  (pull)     Portal → GitHub, then git pull --ff-only
  to-op    (publish)  git push, GitHub → Portal, then git pull --ff-only
  ddb-sync            D&D Beyond → GitHub for characters with dndbeyond_id
                      Add --publish to push sheets to Obsidian Portal after
  serve               Run the bridge API locally (bridge repo checkout)

Typical workflow:
  1. uv run lore-bridge from-op          # refresh local clone from portal
  2. edit lore/**/*.textile on a branch
  3. merge to {branch}, then uv run lore-bridge to-op

D&D Beyond sheets (characters with dndbeyond_id in frontmatter):
  uv run lore-bridge ddb-sync --publish

Per-command options: uv run lore-bridge <command> --help
"""
    )


@app.command()
def status() -> None:
    """Show bridge health and last sync timestamps."""
    client = _load_client()
    try:
        payload = client.health()
    except BridgeError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc

    typer.echo(json.dumps(payload, indent=2))
    job = payload.get("active_job")
    if job and job.get("status") == "running":
        typer.echo()
        _print_job(job)


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="Bind host."),
    port: int = typer.Option(8000, help="Bind port."),
    reload: bool = typer.Option(False, help="Enable auto-reload for local development."),
) -> None:
    """Run the bridge API locally."""
    import uvicorn

    load_dotenv()
    uvicorn.run("lore_bridge.app:app", host=host, port=port, reload=reload)


def main() -> None:
    try:
        app()
    except typer.Exit:
        raise
    except KeyboardInterrupt:
        typer.echo("Interrupted.", err=True)
        raise typer.Exit(130) from None


if __name__ == "__main__":
    main()
