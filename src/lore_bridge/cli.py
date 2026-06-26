from __future__ import annotations

import json
import os
import subprocess
from typing import Any

import typer
from dotenv import load_dotenv

from lore_bridge.client import BridgeClient, BridgeError

app = typer.Typer(
    name="lore-bridge",
    help="CLI for the Obsidian Portal ↔ GitHub lore sync bridge.",
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


def _run_git_pull() -> None:
    result = subprocess.run(["git", "pull", "--ff-only"], check=False)
    if result.returncode != 0:
        raise typer.Exit(result.returncode)


@app.command()
def pull(
    git_pull: bool = typer.Option(True, "--git-pull/--no-git-pull", help="Run git pull --ff-only after sync."),
    async_mode: bool = typer.Option(True, "--async/--blocking", help="Use async job with progress polling."),
) -> None:
    """Pull latest Obsidian Portal wiki and characters into GitHub."""
    client = _load_client()
    typer.echo(f"Starting sync at {client.base_url}/sync/from-portal ...")
    try:
        result = client.pull_from_portal(async_mode=async_mode, on_update=_print_job)
    except BridgeError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc

    if async_mode and "status" in result:
        if result.get("result"):
            typer.echo(json.dumps(result["result"], indent=2))
    else:
        typer.echo(json.dumps(result, indent=2))

    if git_pull:
        _run_git_pull()


@app.command()
def publish(
    async_mode: bool = typer.Option(True, "--async/--blocking", help="Use async job with progress polling."),
) -> None:
    """Pull from portal, then publish safe GitHub changes back to Obsidian Portal."""
    client = _load_client()
    typer.echo(f"Starting publish at {client.base_url}/sync/publish-main ...")
    try:
        result = client.publish_main(async_mode=async_mode, on_update=_print_job)
    except BridgeError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc

    payload = result.get("result") if async_mode and "status" in result else result
    typer.echo(json.dumps(payload, indent=2))


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
    """Run the bridge API locally (requires bridge repo checkout or installed package)."""
    import uvicorn

    load_dotenv()
    uvicorn.run("app:app", host=host, port=port, reload=reload)


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
