from __future__ import annotations

import os
import subprocess


class GitError(Exception):
    pass


def git_branch() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise GitError(result.stderr.strip() or "not a git repository")
    return result.stdout.strip()


def git_pull_ff() -> None:
    result = subprocess.run(["git", "pull", "--ff-only"], check=False)
    if result.returncode != 0:
        raise GitError("git pull --ff-only failed")


def git_push(remote: str, branch: str) -> None:
    result = subprocess.run(
        ["git", "push", remote, branch],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "git push failed").strip()
        raise GitError(detail)


def default_git_remote() -> str:
    return os.environ.get("LORE_GIT_REMOTE", "origin").strip() or "origin"


def default_git_branch() -> str:
    return os.environ.get("LORE_GIT_BRANCH", "main").strip() or "main"
