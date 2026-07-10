import base64
import difflib
import hashlib
import hmac
import json
import logging
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable

import requests
import yaml
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from rapidfuzz import fuzz
from requests_oauthlib import OAuth1

from lore_bridge.dndbeyond.gm import migrate_character_features, needs_feature_migration
from lore_bridge.dndbeyond.sync import DdbSyncResult, sync_from_dndbeyond_impl

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("lore_bridge")

API_BASE = "https://api.obsidianportal.com/v1"
CONSUMER_KEY = os.environ.get("OP_CONSUMER_KEY", "")
CONSUMER_SECRET = os.environ.get("OP_CONSUMER_SECRET", "")
ACCESS_TOKEN = os.environ.get("OP_ACCESS_TOKEN", "")
ACCESS_TOKEN_SECRET = os.environ.get("OP_ACCESS_TOKEN_SECRET", "")
CAMPAIGN_ID = os.environ.get("OP_CAMPAIGN_ID", "")
BRIDGE_KEY = os.environ.get("LORE_BRIDGE_API_KEY", "")
CACHE_TTL_SECONDS = int(os.environ.get("CACHE_TTL_SECONDS", "900"))

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_OWNER = os.environ.get("GITHUB_OWNER", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "")
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main")
GITHUB_AUTHOR_NAME = os.environ.get("GITHUB_AUTHOR_NAME", "Sindrel Lore Bridge")
GITHUB_AUTHOR_EMAIL = os.environ.get("GITHUB_AUTHOR_EMAIL", "lore-bridge@example.com")
GITHUB_WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "")

LORE_WIKI_DIR = os.environ.get("LORE_WIKI_DIR", "lore/wiki").strip("/")
LORE_CHARACTERS_DIR = os.environ.get("LORE_CHARACTERS_DIR", "lore/characters").strip("/")
LORE_STATE_PATH = os.environ.get("LORE_STATE_PATH", "metadata/sync-state.json").strip("/")
LORE_FILE_EXT = os.environ.get("LORE_FILE_EXT", ".textile").strip()
if not LORE_FILE_EXT.startswith("."):
    LORE_FILE_EXT = f".{LORE_FILE_EXT}"
LEGACY_FILE_EXT = ".md"
OP_AUTHOR_ID = os.environ.get("OP_AUTHOR_ID", "")
ALLOW_CREATE_FROM_GIT = os.environ.get("ALLOW_CREATE_FROM_GIT", "true").lower() == "true"
ALLOW_DELETE_FROM_GIT = os.environ.get("ALLOW_DELETE_FROM_GIT", "true").lower() == "true"
DYNAMIC_SHEET_TEMPLATE_ID = os.environ.get("DYNAMIC_SHEET_TEMPLATE_ID", "").strip() or None
GITHUB_API_RETRIES = max(1, int(os.environ.get("GITHUB_API_RETRIES", "5")))
GITHUB_API_RETRY_BASE_SECONDS = float(os.environ.get("GITHUB_API_RETRY_BASE_SECONDS", "1.0"))
GITHUB_RETRY_STATUS_CODES = {429, 500, 502, 503, 504}

app = FastAPI(
    title="Sindrel Lore Bridge",
    version="0.9.1",
    description="Bidirectional Obsidian Portal ↔ GitHub lore sync bridge with pull-through conflict protection.",
)

_cache: dict[str, Any] = {
    "last_sync": 0,
    "index": [],
    "pages": {},
    "characters_last_sync": 0,
    "characters_index": [],
    "characters": {},
}
_author_id_cache: str | None = None
_jobs: dict[str, "SyncJobRecord"] = {}
_active_job_id: str | None = None
_job_lock = threading.Lock()
_sync_status_cache: dict[str, Any] = {"last_portal_pull": None, "last_git_publish": None, "fetched_at": 0.0}
SYNC_STATUS_CACHE_TTL = 60

PHASE_LABELS = {
    "starting": "Starting",
    "indexing": "Loading indexes",
    "fetching_wiki": "Pulling wiki pages",
    "fetching_characters": "Pulling characters",
    "committing_git": "Committing to GitHub",
    "publishing_portal": "Publishing to Obsidian Portal",
    "deleting_portal": "Removing deleted pages",
    "fetching_dndbeyond": "Syncing D&D Beyond sheets",
    "done": "Finishing",
}
JOB_KIND_LABELS = {
    "from-portal": "Portal → GitHub",
    "from-dndbeyond": "D&D Beyond → GitHub",
    "publish-main": "GitHub → Portal",
}


class JobError(BaseModel):
    phase: str | None = None
    path: str | None = None
    op_id: str | None = None
    title: str | None = None
    detail: str


class SyncJobRecord(BaseModel):
    job_id: str
    kind: str
    status: str = "running"
    phase: str = "starting"
    current: int = 0
    total: int = 0
    current_title: str | None = None
    current_path: str | None = None
    message: str | None = None
    errors: list[JobError] = []
    started_at: str
    finished_at: str | None = None
    result: dict[str, Any] | None = None


class JobStartResponse(BaseModel):
    job_id: str
    status: str = "running"
    kind: str
    message: str = "Sync job started. Poll GET /sync/jobs/{job_id} for progress."


class ProgressReporter:
    def __init__(self, job: SyncJobRecord | None = None) -> None:
        self.job = job

    def phase(
        self,
        phase: str,
        *,
        current: int = 0,
        total: int = 0,
        title: str | None = None,
        path: str | None = None,
        message: str | None = None,
    ) -> None:
        if self.job:
            self.job.phase = phase
            self.job.current = current
            self.job.total = total
            self.job.current_title = title
            self.job.current_path = path
            self.job.message = message
        parts = [phase]
        if total:
            parts.append(f"{current}/{total}")
        if title:
            parts.append(title)
        elif path:
            parts.append(path)
        if message:
            parts.append(message)
        logger.info("sync %s", " | ".join(parts))

    def record_error(
        self,
        detail: str,
        *,
        phase: str | None = None,
        path: str | None = None,
        op_id: str | None = None,
        title: str | None = None,
    ) -> None:
        err = JobError(phase=phase or (self.job.phase if self.job else None), path=path, op_id=op_id, title=title, detail=detail)
        if self.job:
            self.job.errors.append(err)
        logger.error("sync error | %s | path=%s op_id=%s title=%s | %s", err.phase, path, op_id, title, detail)


class SyncResult(BaseModel):
    ok: bool = True
    changed_pages: int = 0
    committed: bool = False
    commit_sha: str | None = None
    message: str | None = None
    conflicts: list[dict[str, Any]] = []


class PublishResult(BaseModel):
    ok: bool = True
    portal_pull: SyncResult | None = None
    created: int = 0
    updated: int = 0
    deleted: int = 0
    skipped: int = 0
    conflicts: list[dict[str, Any]] = []
    message: str | None = None


class DdbSyncResponse(BaseModel):
    ok: bool = True
    updated: int = 0
    skipped: int = 0
    errors: list[dict[str, str]] = []
    committed: bool = False
    commit_sha: str | None = None
    message: str | None = None


class SearchResult(BaseModel):
    id: str
    slug: str | None = None
    title: str
    url: str | None = None
    type: str | None = None
    tags: list[str] = []
    updated_at: str | None = None
    snippet: str | None = None
    score: float


class SearchResponse(BaseModel):
    results: list[SearchResult]


class PageResponse(BaseModel):
    id: str
    slug: str | None = None
    title: str
    url: str | None = None
    type: str | None = None
    tags: list[str] = []
    updated_at: str | None = None
    body: str | None = None
    game_master_info: str | None = None
    is_game_master_only: bool = False
    post_title: str | None = None
    post_tagline: str | None = None
    post_time: str | None = None


class CharacterResponse(BaseModel):
    id: str
    slug: str | None = None
    title: str
    name: str | None = None
    url: str | None = None
    tags: list[str] = []
    updated_at: str | None = None
    description: str | None = None
    bio: str | None = None
    game_master_info: str | None = None
    is_game_master_only: bool = False
    is_player_character: bool = False
    tagline: str | None = None


@dataclass
class RepoFile:
    path: str
    content: str
    sha: str | None = None


@dataclass
class TreeChange:
    path: str
    content: str | None = None  # None removes the path from the tree


# ----------------------------- auth helpers -----------------------------

def require_auth(authorization: str | None = Header(default=None)) -> None:
    if not BRIDGE_KEY:
        raise HTTPException(status_code=500, detail="LORE_BRIDGE_API_KEY is not configured")
    if authorization != f"Bearer {BRIDGE_KEY}":
        raise HTTPException(status_code=401, detail="Invalid or missing bridge API key")


def verify_github_signature(raw_body: bytes, signature: str | None) -> None:
    if not GITHUB_WEBHOOK_SECRET:
        return
    if not signature or not signature.startswith("sha256="):
        raise HTTPException(status_code=401, detail="Missing GitHub signature")
    digest = hmac.new(GITHUB_WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    expected = f"sha256={digest}"
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="Invalid GitHub signature")


def op_auth() -> OAuth1:
    missing = [
        name for name, value in {
            "OP_CONSUMER_KEY": CONSUMER_KEY,
            "OP_CONSUMER_SECRET": CONSUMER_SECRET,
            "OP_ACCESS_TOKEN": ACCESS_TOKEN,
            "OP_ACCESS_TOKEN_SECRET": ACCESS_TOKEN_SECRET,
        }.items() if not value
    ]
    if missing:
        raise HTTPException(status_code=500, detail=f"Missing Obsidian Portal credentials: {', '.join(missing)}")
    return OAuth1(CONSUMER_KEY, CONSUMER_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET, signature_method="HMAC-SHA1")


def ensure_campaign() -> None:
    if not CAMPAIGN_ID:
        raise HTTPException(status_code=500, detail="OP_CAMPAIGN_ID is not configured")


def ensure_github() -> None:
    missing = [
        name for name, value in {
            "GITHUB_TOKEN": GITHUB_TOKEN,
            "GITHUB_OWNER": GITHUB_OWNER,
            "GITHUB_REPO": GITHUB_REPO,
        }.items() if not value
    ]
    if missing:
        raise HTTPException(status_code=500, detail=f"Missing GitHub configuration: {', '.join(missing)}")


# ----------------------------- Obsidian Portal -----------------------------

def op_request(method: str, path: str, params: dict[str, Any] | None = None, payload: dict[str, Any] | None = None) -> Any:
    ensure_campaign()
    url = f"{API_BASE}{path}"
    response = requests.request(method, url, params=params, json=payload, auth=op_auth(), timeout=30)
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=response.text[:1500])
    if response.status_code == 204 or not response.text:
        return None
    return response.json()


def op_get(path: str, params: dict[str, Any] | None = None) -> Any:
    return op_request("GET", path, params=params)


def op_post(path: str, payload: dict[str, Any]) -> Any:
    return op_request("POST", path, payload=payload)


def op_put(path: str, payload: dict[str, Any]) -> Any:
    return op_request("PUT", path, payload=payload)


def op_delete(path: str) -> None:
    op_request("DELETE", path)


def html_to_textile_fallback(value: str | None) -> str:
    if not value:
        return ""
    soup = BeautifulSoup(value, "html.parser")
    for img in soup.find_all("img"):
        src = (img.get("src") or "").strip()
        alt = (img.get("alt") or "").strip()
        if src:
            replacement = f"!{src}({alt})!" if alt else f"!{src}!"
        else:
            replacement = ""
        img.replace_with(replacement)
    return soup.get_text("\n", strip=True)


def page_title(page: dict[str, Any]) -> str:
    return page.get("post_title") or page.get("name") or page.get("slug") or page.get("id") or "Untitled"


def compact_snippet(text: str, limit: int = 500) -> str:
    text = " ".join(text.split())
    return text[:limit] + ("..." if len(text) > limit else "")


def normalize_page(page: dict[str, Any]) -> dict[str, Any]:
    body = page.get("body") or html_to_textile_fallback(page.get("body_html"))
    gm = page.get("game_master_info") or html_to_textile_fallback(page.get("game_master_info_html"))
    return {
        "id": page.get("id"),
        "slug": page.get("slug"),
        "title": page_title(page),
        "name": page.get("name") or page_title(page),
        "url": page.get("wiki_page_url"),
        "type": page.get("type"),
        "tags": page.get("tags") or [],
        "created_at": page.get("created_at"),
        "updated_at": page.get("updated_at"),
        "body": body or "",
        "game_master_info": gm or "",
        "is_game_master_only": bool(page.get("is_game_master_only")),
        "post_title": page.get("post_title"),
        "post_tagline": page.get("post_tagline"),
        "post_time": page.get("post_time"),
    }


def ensure_index(force: bool = False) -> None:
    now = time.time()
    if not force and _cache["index"] and now - _cache["last_sync"] < CACHE_TTL_SECONDS:
        return
    pages = op_get(f"/campaigns/{CAMPAIGN_ID}/wikis.json")
    _cache["index"] = pages
    _cache["last_sync"] = now


def fetch_page(id_or_slug: str, force: bool = False) -> dict[str, Any]:
    ensure_index(force=force)
    if not force and id_or_slug in _cache["pages"]:
        return _cache["pages"][id_or_slug]
    index_match = next((p for p in _cache["index"] if p.get("id") == id_or_slug or p.get("slug") == id_or_slug), None)
    lookup = index_match.get("id") if index_match else id_or_slug
    params = None if index_match else {"use_slug": "true"}
    page = op_get(f"/campaigns/{CAMPAIGN_ID}/wikis/{lookup}.json", params=params)
    normalized = normalize_page(page)
    _cache["pages"][normalized["id"]] = normalized
    if normalized.get("slug"):
        _cache["pages"][normalized["slug"]] = normalized
    return normalized


def apply_wiki_post_fields(wiki_page: dict[str, Any], frontmatter: dict[str, Any]) -> None:
    if (frontmatter.get("op_type") or "WikiPage") != "Post":
        return
    wiki_page["type"] = "Post"
    post_title = frontmatter.get("post_title") or frontmatter.get("name") or frontmatter.get("title")
    if post_title:
        wiki_page["post_title"] = post_title
    if "post_tagline" in frontmatter:
        wiki_page["post_tagline"] = frontmatter.get("post_tagline") or ""
    if frontmatter.get("post_time"):
        wiki_page["post_time"] = frontmatter["post_time"]


def update_op_page(page_id: str, frontmatter: dict[str, Any], body: str, gm_info: str) -> dict[str, Any]:
    wiki_page = {
        "body": body,
        "tags": frontmatter.get("tags") or [],
        "game_master_info": gm_info,
        "is_game_master_only": bool(frontmatter.get("op_gm_only", False)),
    }
    if frontmatter.get("name"):
        wiki_page["name"] = frontmatter["name"]
    apply_wiki_post_fields(wiki_page, frontmatter)
    return normalize_page(op_put(f"/campaigns/{CAMPAIGN_ID}/wikis/{page_id}.json", {"wiki_page": wiki_page}))


def create_op_page(frontmatter: dict[str, Any], body: str, gm_info: str, *, path: str = "") -> dict[str, Any]:
    wiki_page = {
        "name": frontmatter.get("name") or frontmatter.get("title") or "Untitled Page",
        "body": body,
        "tags": frontmatter.get("tags") or [],
        "game_master_info": gm_info,
        "is_game_master_only": bool(frontmatter.get("op_gm_only", False)),
    }
    if frontmatter.get("op_type"):
        wiki_page["type"] = frontmatter["op_type"]
    apply_wiki_post_fields(wiki_page, frontmatter)
    try:
        return normalize_page(op_post(f"/campaigns/{CAMPAIGN_ID}/wikis.json", {"wiki_page": wiki_page}))
    except HTTPException as exc:
        existing_id = resolve_existing_portal_id(frontmatter, path, "Wiki")
        if is_name_taken_error(exc) and existing_id:
            return update_op_page(existing_id, frontmatter, body, gm_info)
        raise


def op_author_id() -> str:
    global _author_id_cache
    if OP_AUTHOR_ID:
        return OP_AUTHOR_ID
    if _author_id_cache:
        return _author_id_cache
    me = op_get("/users/me")
    _author_id_cache = me.get("id")
    if not _author_id_cache:
        raise HTTPException(status_code=500, detail="Could not determine Obsidian Portal author id for character create")
    return _author_id_cache


def normalize_character(character: dict[str, Any]) -> dict[str, Any]:
    desc = character.get("description") or html_to_textile_fallback(character.get("description_html"))
    bio = character.get("bio") or html_to_textile_fallback(character.get("bio_html"))
    gm = character.get("game_master_info") or html_to_textile_fallback(character.get("game_master_info_html"))
    template = character.get("dynamic_sheet_template") or {}
    return {
        "id": character.get("id"),
        "slug": character.get("slug"),
        "title": character.get("name") or character.get("slug") or character.get("id") or "Untitled",
        "name": character.get("name") or character.get("slug") or "Untitled",
        "url": character.get("character_url"),
        "op_kind": "Character",
        "tags": character.get("tags") or [],
        "created_at": character.get("created_at"),
        "updated_at": character.get("updated_at"),
        "description": desc or "",
        "bio": bio or "",
        "game_master_info": gm or "",
        "is_game_master_only": bool(character.get("is_game_master_only")),
        "is_player_character": bool(character.get("is_player_character")),
        "tagline": character.get("tagline"),
        "dynamic_sheet": character.get("dynamic_sheet") or {},
        "dynamic_sheet_template_id": template.get("id") if isinstance(template, dict) else None,
        "avatar_url": character.get("avatar_url"),
    }


def ensure_characters_index(force: bool = False) -> None:
    now = time.time()
    if not force and _cache["characters_index"] and now - _cache["characters_last_sync"] < CACHE_TTL_SECONDS:
        return
    characters = op_get(f"/campaigns/{CAMPAIGN_ID}/characters.json")
    _cache["characters_index"] = characters
    _cache["characters_last_sync"] = now


def fetch_character(id_or_slug: str, force: bool = False) -> dict[str, Any]:
    ensure_characters_index(force=force)
    if not force and id_or_slug in _cache["characters"]:
        return _cache["characters"][id_or_slug]
    index_match = next(
        (c for c in _cache["characters_index"] if c.get("id") == id_or_slug or c.get("slug") == id_or_slug),
        None,
    )
    lookup = index_match.get("id") if index_match else id_or_slug
    params = None if index_match else {"use_slug": "true"}
    character = op_get(f"/campaigns/{CAMPAIGN_ID}/characters/{lookup}.json", params=params)
    normalized = normalize_character(character)
    _cache["characters"][normalized["id"]] = normalized
    if normalized.get("slug"):
        _cache["characters"][normalized["slug"]] = normalized
    return normalized


def _strip_dynamic_sheet_description(dynamic_sheet: dict[str, Any] | None) -> dict[str, Any]:
    ds = dict(dynamic_sheet or {})
    ds.pop("description", None)
    return ds


def _op_dynamic_sheet_base(frontmatter: dict[str, Any]) -> dict[str, Any]:
    return _strip_dynamic_sheet_description(frontmatter.get("dynamic_sheet"))


def _mirror_dst_description_html(raw: dict[str, Any], ds: dict[str, Any]) -> dict[str, Any]:
    character_id = raw.get("id")
    if not character_id:
        return raw
    ds_mirror = dict(raw.get("dynamic_sheet") or ds)
    ds_mirror["description"] = raw.get("description_html") or ""
    return op_put(
        f"/campaigns/{CAMPAIGN_ID}/characters/{character_id}.json",
        {"character": {"dynamic_sheet": ds_mirror}},
    )


def _finalize_op_character(raw: dict[str, Any], frontmatter: dict[str, Any], ds: dict[str, Any]) -> dict[str, Any]:
    if frontmatter.get("dynamic_sheet_template_id"):
        raw = _mirror_dst_description_html(raw, ds)
    return normalize_character(raw)


def update_op_character(
    character_id: str,
    frontmatter: dict[str, Any],
    description: str,
    bio: str,
    gm_info: str,
) -> dict[str, Any]:
    character: dict[str, Any] = {
        "name": frontmatter.get("name") or frontmatter.get("title") or "Untitled Character",
        "description": description,
        "bio": bio,
        "tags": frontmatter.get("tags") or [],
        "game_master_info": gm_info,
        "is_game_master_only": bool(frontmatter.get("op_gm_only", False)),
        "is_player_character": bool(frontmatter.get("is_player_character", False)),
    }
    if frontmatter.get("tagline"):
        character["tagline"] = frontmatter["tagline"]
    ds = _op_dynamic_sheet_base(frontmatter)
    if frontmatter.get("dynamic_sheet") is not None or frontmatter.get("dynamic_sheet_template_id"):
        character["dynamic_sheet"] = ds
    if frontmatter.get("dynamic_sheet_template_id"):
        character["dynamic_sheet_template_id"] = frontmatter["dynamic_sheet_template_id"]
    raw = op_put(f"/campaigns/{CAMPAIGN_ID}/characters/{character_id}.json", {"character": character})
    return _finalize_op_character(raw, frontmatter, ds)


def create_op_character(
    frontmatter: dict[str, Any],
    description: str,
    bio: str,
    gm_info: str,
    *,
    path: str = "",
) -> dict[str, Any]:
    character: dict[str, Any] = {
        "name": frontmatter.get("name") or frontmatter.get("title") or "Untitled Character",
        "author_id": op_author_id(),
        "description": description,
        "bio": bio,
        "tags": frontmatter.get("tags") or [],
        "game_master_info": gm_info,
        "is_game_master_only": bool(frontmatter.get("op_gm_only", False)),
        "is_player_character": bool(frontmatter.get("is_player_character", False)),
    }
    if frontmatter.get("tagline"):
        character["tagline"] = frontmatter["tagline"]
    ds = _op_dynamic_sheet_base(frontmatter)
    if frontmatter.get("dynamic_sheet") or frontmatter.get("dynamic_sheet_template_id"):
        character["dynamic_sheet"] = ds
    if frontmatter.get("dynamic_sheet_template_id"):
        character["dynamic_sheet_template_id"] = frontmatter["dynamic_sheet_template_id"]
    try:
        raw = op_post(f"/campaigns/{CAMPAIGN_ID}/characters.json", {"character": character})
        return _finalize_op_character(raw, frontmatter, ds)
    except HTTPException as exc:
        existing_id = resolve_existing_portal_id(frontmatter, path, "Character")
        if is_name_taken_error(exc) and existing_id:
            return update_op_character(existing_id, frontmatter, description, bio, gm_info)
        raise


# ----------------------------- GitHub API -----------------------------

def gh_headers() -> dict[str, str]:
    ensure_github()
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def gh_api(method: str, path: str, payload: dict[str, Any] | None = None, params: dict[str, Any] | None = None, ok: tuple[int, ...] = (200, 201)) -> Any:
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}{path}"
    last_status = 0
    last_body = ""
    for attempt in range(GITHUB_API_RETRIES):
        response = requests.request(method, url, headers=gh_headers(), json=payload, params=params, timeout=30)
        if response.status_code in ok:
            if response.status_code == 204 or not response.text:
                return None
            return response.json()
        last_status = response.status_code
        last_body = response.text[:1500]
        if response.status_code not in GITHUB_RETRY_STATUS_CODES or attempt + 1 >= GITHUB_API_RETRIES:
            break
        retry_after = response.headers.get("Retry-After")
        if retry_after and retry_after.isdigit():
            delay = float(retry_after)
        else:
            delay = GITHUB_API_RETRY_BASE_SECONDS * (2**attempt)
        logger.warning(
            "GitHub %s %s returned %s; retry %d/%d in %.1fs",
            method,
            path,
            response.status_code,
            attempt + 1,
            GITHUB_API_RETRIES,
            delay,
        )
        time.sleep(delay)
    raise HTTPException(
        status_code=502,
        detail=f"GitHub {method} {path} failed: {last_status} {last_body}",
    )


def gh_get_blob_content(sha: str) -> str:
    data = gh_api("GET", f"/git/blobs/{sha}")
    return base64.b64decode(data["content"]).decode("utf-8")


def gh_get_file(path: str, *, blob_sha: str | None = None) -> RepoFile | None:
    if blob_sha:
        try:
            return RepoFile(path=path, content=gh_get_blob_content(blob_sha), sha=blob_sha)
        except HTTPException as exc:
            if "404" not in str(exc.detail):
                raise
    try:
        data = gh_api("GET", f"/contents/{path}", params={"ref": GITHUB_BRANCH})
    except HTTPException as exc:
        if "404" in str(exc.detail):
            return None
        raise
    if isinstance(data, list):
        raise HTTPException(status_code=500, detail=f"Expected file but found directory at {path}")
    raw = base64.b64decode(data["content"]).decode("utf-8")
    return RepoFile(path=path, content=raw, sha=data.get("sha"))


def gh_git_author() -> dict[str, str]:
    return {"name": GITHUB_AUTHOR_NAME, "email": GITHUB_AUTHOR_EMAIL}


def gh_create_blob(content: str) -> str:
    data = gh_api("POST", "/git/blobs", payload={"content": content, "encoding": "utf-8"})
    return data["sha"]


def gh_commit_changes(message: str, changes: list[TreeChange], progress: ProgressReporter | None = None) -> str | None:
    if not changes:
        return None
    by_path: dict[str, TreeChange] = {}
    for change in changes:
        by_path[change.path] = change
    if progress:
        progress.phase("committing_git", message=f"committing {len(by_path)} path(s)")
    else:
        logger.info("committing %d path(s) to GitHub: %s", len(by_path), message)
    ref = gh_api("GET", f"/git/ref/heads/{GITHUB_BRANCH}")
    head_sha = ref["object"]["sha"]
    head_commit = gh_api("GET", f"/git/commits/{head_sha}")
    tree_items: list[dict[str, Any]] = []
    for path, change in sorted(by_path.items()):
        if change.content is None:
            tree_items.append({"path": path, "mode": "100644", "type": "blob", "sha": None})
        else:
            tree_items.append({
                "path": path,
                "mode": "100644",
                "type": "blob",
                "sha": gh_create_blob(change.content),
            })
    new_tree = gh_api("POST", "/git/trees", payload={"base_tree": head_commit["tree"]["sha"], "tree": tree_items})
    new_commit = gh_api(
        "POST",
        "/git/commits",
        payload={
            "message": message,
            "tree": new_tree["sha"],
            "parents": [head_sha],
            "author": gh_git_author(),
            "committer": gh_git_author(),
        },
    )
    gh_api("PATCH", f"/git/refs/heads/{GITHUB_BRANCH}", payload={"sha": new_commit["sha"]}, ok=(200,))
    logger.info("git commit %s (%d paths)", new_commit["sha"][:8], len(by_path))
    return new_commit["sha"]


def gh_list_tree() -> list[dict[str, Any]]:
    branch = gh_api("GET", f"/branches/{GITHUB_BRANCH}")
    tree_sha = branch["commit"]["commit"]["tree"]["sha"]
    tree = gh_api("GET", f"/git/trees/{tree_sha}", params={"recursive": "1"})
    return tree.get("tree") or []


def gh_repo_blob_index(tree: list[dict[str, Any]] | None = None) -> dict[str, str]:
    items = tree if tree is not None else gh_list_tree()
    return {
        item["path"]: item["sha"]
        for item in items
        if item.get("type") == "blob" and item.get("path") and item.get("sha")
    }


def gh_sync_files(tree: list[dict[str, Any]] | None = None) -> list[str]:
    prefixes = [f"{LORE_WIKI_DIR}/", f"{LORE_CHARACTERS_DIR}/"]
    allowed_exts = {LORE_FILE_EXT, LEGACY_FILE_EXT}
    items = tree if tree is not None else gh_list_tree()
    return [
        item["path"]
        for item in items
        if item.get("type") == "blob"
        and any(item.get("path", "").startswith(prefix) for prefix in prefixes)
        and any(item["path"].endswith(ext) for ext in allowed_exts)
    ]


def load_state() -> dict[str, Any]:
    file = gh_get_file(LORE_STATE_PATH)
    if not file:
        return {"version": 1, "pages": {}, "last_portal_pull": None, "last_git_publish": None}
    try:
        data = json.loads(file.content)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail=f"Invalid JSON in {LORE_STATE_PATH}")
    data.setdefault("version", 1)
    data.setdefault("pages", {})
    return data


def state_content(state: dict[str, Any]) -> str:
    return json.dumps(state, indent=2, sort_keys=True) + "\n"


def save_state(state: dict[str, Any], message: str) -> str:
    return gh_commit_changes(message, [TreeChange(LORE_STATE_PATH, state_content(state))]) or ""


# ----------------------------- markdown mapping -----------------------------

def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return re.sub(r"-+", "-", value).strip("-") or "untitled"


def repo_path_slug(path: str) -> str | None:
    basename = path.rsplit("/", 1)[-1]
    for ext in (LORE_FILE_EXT, LEGACY_FILE_EXT):
        if basename.endswith(ext):
            return basename[: -len(ext)] or None
    return None


def is_name_taken_error(exc: HTTPException) -> bool:
    if exc.status_code != 400:
        return False
    detail = str(exc.detail).lower()
    return "name has already been taken" in detail or '"code":4010' in detail


def resolve_existing_portal_id(fm: dict[str, Any], path: str, kind: str) -> str | None:
    slug = fm.get("op_slug") or repo_path_slug(path)
    name = fm.get("name") or fm.get("title")
    if kind == "Character":
        ensure_characters_index(force=True)
        index = _cache["characters_index"]
    else:
        ensure_index(force=True)
        op_type = fm.get("op_type") or "WikiPage"
        index = [p for p in _cache["index"] if (p.get("type") or "WikiPage") == op_type]
    if slug:
        match = next((m for m in index if m.get("slug") == slug), None)
        if match:
            return match.get("id")
    if name:
        name_lower = name.lower()
        match = next(
            (
                m
                for m in index
                if (m.get("name") or "").lower() == name_lower
                or (m.get("post_title") or "").lower() == name_lower
            ),
            None,
        )
        if match:
            return match.get("id")
    return None


def push_portal_record(
    page_id: str,
    kind: str,
    fm: dict[str, Any],
    *,
    body: str,
    description: str,
    bio: str,
    gm_info: str,
    path: str,
) -> tuple[dict[str, Any], str]:
    try:
        if kind == "Character":
            return update_op_character(page_id, fm, description, bio, gm_info), page_id
        return update_op_page(page_id, fm, body, gm_info), page_id
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        replacement = resolve_existing_portal_id(fm, path, kind)
        if replacement:
            if kind == "Character":
                return update_op_character(replacement, fm, description, bio, gm_info), replacement
            return update_op_page(replacement, fm, body, gm_info), replacement
        if not ALLOW_CREATE_FROM_GIT:
            raise HTTPException(
                status_code=404,
                detail=f"{path} op_id {page_id} not found on Obsidian Portal and no matching record to relink",
            ) from exc
        if kind == "Character":
            created = create_op_character(fm, description, bio, gm_info, path=path)
        else:
            created = create_op_page(fm, body, gm_info, path=path)
        return created, created["id"]


def content_hash(
    fm: dict[str, Any],
    *,
    body: str = "",
    gm_info: str = "",
    description: str = "",
    bio: str = "",
    ddb_sheet: str = "",
) -> str:
    kind = resource_kind(fm)
    if kind == "Character":
        comparable = {
            "ddb_sheet": ddb_sheet or "",
            "description": description or "",
            "bio": bio or "",
            "game_master_info": gm_info or "",
            "tags": fm.get("tags") or [],
            "name": fm.get("name") or fm.get("title") or "",
            "op_gm_only": bool(fm.get("op_gm_only", False)),
            "is_player_character": bool(fm.get("is_player_character", False)),
            "tagline": fm.get("tagline") or "",
            "dynamic_sheet": fm.get("dynamic_sheet") or {},
            "dynamic_sheet_template_id": fm.get("dynamic_sheet_template_id") or "",
        }
    else:
        comparable = {
            "body": body or "",
            "game_master_info": gm_info or "",
            "tags": fm.get("tags") or [],
            "name": fm.get("name") or fm.get("title") or "",
            "op_gm_only": bool(fm.get("op_gm_only", False)),
            "op_type": fm.get("op_type") or "WikiPage",
        }
        if comparable["op_type"] == "Post":
            comparable["post_title"] = fm.get("post_title") or fm.get("name") or fm.get("title") or ""
            comparable["post_tagline"] = fm.get("post_tagline") or ""
            comparable["post_time"] = fm.get("post_time") or ""
    return hashlib.sha256(json.dumps(comparable, sort_keys=True).encode()).hexdigest()


def resource_kind(fm: dict[str, Any]) -> str:
    if fm.get("op_kind") == "Character" or fm.get("op_type") == "Character":
        return "Character"
    return "Wiki"


def page_path(page: dict[str, Any]) -> str:
    if page.get("op_kind") == "Character":
        name = page.get("slug") or slugify(page.get("title") or page.get("name") or page["id"])
        return f"{LORE_CHARACTERS_DIR}/{name}{LORE_FILE_EXT}"
    prefix = "adventure-log" if page.get("type") == "Post" else "wiki"
    name = page.get("slug") or slugify(page.get("title") or page.get("name") or page["id"])
    return f"{LORE_WIKI_DIR}/{prefix}/{name}{LORE_FILE_EXT}"


def page_to_markdown(page: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if page.get("op_kind") == "Character":
        return character_to_markdown(page)
    fm = {
        "op_id": page.get("id"),
        "op_slug": page.get("slug"),
        "op_kind": "Wiki",
        "op_type": page.get("type") or "WikiPage",
        "name": page.get("name") or page.get("title"),
        "title": page.get("title"),
        "op_url": page.get("url"),
        "op_created_at": page.get("created_at"),
        "op_updated_at": page.get("updated_at"),
        "op_gm_only": bool(page.get("is_game_master_only")),
        "tags": page.get("tags") or [],
    }
    if (page.get("type") or "WikiPage") == "Post":
        if page.get("post_title"):
            fm["post_title"] = page["post_title"]
        if page.get("post_tagline"):
            fm["post_tagline"] = page["post_tagline"]
        if page.get("post_time"):
            fm["post_time"] = page["post_time"]
    front = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True).strip()
    body = page.get("body") or ""
    gm = page.get("game_master_info") or ""
    content = normalize_textile_content(f"---\n{front}\n---\n\n{body.rstrip()}\n")
    if gm:
        content += f"\n<!-- GM_INFO_START -->\n{gm.rstrip()}\n<!-- GM_INFO_END -->\n"
    return normalize_textile_content(content), fm


def character_to_markdown(
    character: dict[str, Any],
    *,
    ddb_sheet: str = "",
    tagline_description: str | None = None,
) -> tuple[str, dict[str, Any]]:
    fm = {
        "op_id": character.get("id"),
        "op_slug": character.get("slug"),
        "op_kind": "Character",
        "op_type": "Character",
        "name": character.get("name") or character.get("title"),
        "title": character.get("title"),
        "op_url": character.get("url"),
        "op_created_at": character.get("created_at"),
        "op_updated_at": character.get("updated_at"),
        "op_gm_only": bool(character.get("is_game_master_only")),
        "is_player_character": bool(character.get("is_player_character")),
        "tags": character.get("tags") or [],
    }
    if character.get("tagline"):
        fm["tagline"] = character["tagline"]
    if character.get("dynamic_sheet"):
        fm["dynamic_sheet"] = _strip_dynamic_sheet_description(character["dynamic_sheet"])
    if character.get("dynamic_sheet_template_id"):
        fm["dynamic_sheet_template_id"] = character["dynamic_sheet_template_id"]
    if character.get("avatar_url"):
        fm["avatar_url"] = character["avatar_url"]
    if tagline_description is None:
        tagline_description = character.get("description") or ""
    description = tagline_description.rstrip()
    bio = (character.get("bio") or "").rstrip()
    gm = (character.get("game_master_info") or "").rstrip()
    fm, gm = migrate_character_features(fm, gm)
    content = rebuild_character_content(
        fm,
        ddb_sheet=ddb_sheet,
        description=description,
        bio=bio,
        gm_info=gm,
    )
    return content, fm


def rebuild_character_content(
    fm: dict[str, Any],
    *,
    ddb_sheet: str = "",
    description: str = "",
    bio: str = "",
    gm_info: str = "",
) -> str:
    front = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True).strip()
    parts = [f"---\n{front}\n---\n"]
    if ddb_sheet.strip():
        parts.append(f"\n<!-- OP_DDB_SHEET -->\n{ddb_sheet.rstrip()}\n")
    parts.append(f"\n<!-- OP_DESCRIPTION -->\n{description.rstrip()}\n\n<!-- OP_BIO -->\n{bio.rstrip()}\n")
    content = normalize_textile_content("".join(parts))
    if gm_info:
        content += f"\n<!-- GM_INFO_START -->\n{gm_info.rstrip()}\n<!-- GM_INFO_END -->\n"
    return normalize_textile_content(content)


def op_character_description(ddb_sheet: str, tagline: str) -> str:
    parts: list[str] = []
    if ddb_sheet.strip():
        parts.append("<notextile>\n" + ddb_sheet.strip() + "\n</notextile>")
    if tagline.strip():
        if parts:
            parts.append("\n\n")
        parts.append(tagline.strip())
    return "".join(parts)


def parse_markdown(content: str) -> tuple[dict[str, Any], str, str]:
    parsed = parse_sync_file(content)
    return parsed["fm"], parsed["body"], parsed["gm_info"]


def normalize_textile_content(content: str) -> str:
    return content.replace("\r\n", "\n").replace("\r", "\n")


def parse_sync_file(content: str) -> dict[str, Any]:
    content = normalize_textile_content(content)
    if not content.startswith("---\n"):
        return {"fm": {}, "body": content, "ddb_sheet": "", "description": "", "bio": "", "gm_info": "", "kind": "Wiki"}
    end = content.find("\n---\n", 4)
    if end == -1:
        end = content.find("\n---", 4)
        if end == -1:
            return {"fm": {}, "body": content, "ddb_sheet": "", "description": "", "bio": "", "gm_info": "", "kind": "Wiki"}
    front = content[4:end]
    rest = content[end + 4 :].lstrip("\n")
    if rest.startswith("---\n"):
        rest = rest[4:].lstrip("\n")
    fm = yaml.safe_load(front) or {}
    kind = resource_kind(fm)
    gm_info = ""
    marker_start = "<!-- GM_INFO_START -->"
    marker_end = "<!-- GM_INFO_END -->"
    body = rest
    if marker_start in rest and marker_end in rest:
        before, after_start = rest.split(marker_start, 1)
        gm_info, after_end = after_start.split(marker_end, 1)
        body = before.rstrip() + after_end.strip("\n")
        gm_info = gm_info.strip("\n")
    if kind == "Character":
        ddb_sheet, description, bio = split_character_sections(body)
        return {
            "fm": fm,
            "body": "",
            "ddb_sheet": ddb_sheet,
            "description": description,
            "bio": bio,
            "gm_info": gm_info,
            "kind": "Character",
        }
    return {
        "fm": fm,
        "body": body.rstrip() + "\n",
        "ddb_sheet": "",
        "description": "",
        "bio": "",
        "gm_info": gm_info,
        "kind": "Wiki",
    }


def _section_text(value: str) -> str:
    value = value.strip("\n")
    return value + ("\n" if value and not value.endswith("\n") else "")


def split_character_sections(body: str) -> tuple[str, str, str]:
    ddb_sheet = ""
    description = ""
    bio = ""
    text = body.lstrip("\n")

    if "<!-- OP_DDB_SHEET -->" in text:
        _, after = text.split("<!-- OP_DDB_SHEET -->", 1)
        if "<!-- OP_DESCRIPTION -->" in after:
            ddb_sheet, text = after.split("<!-- OP_DESCRIPTION -->", 1)
        elif "<!-- OP_BIO -->" in after:
            ddb_sheet, text = after.split("<!-- OP_BIO -->", 1)
            text = "<!-- OP_DESCRIPTION -->\n" + text
        else:
            ddb_sheet = after
            text = ""

    if "<!-- OP_BIO -->" in text:
        desc_part, bio = text.split("<!-- OP_BIO -->", 1)
        if "<!-- OP_DESCRIPTION -->" in desc_part:
            _, description = desc_part.split("<!-- OP_DESCRIPTION -->", 1)
        else:
            description = desc_part
    elif "<!-- OP_DESCRIPTION -->" in text:
        _, description = text.split("<!-- OP_DESCRIPTION -->", 1)
    else:
        description = text

    return _section_text(ddb_sheet), _section_text(description), _section_text(bio)


def unified_diff(old: str, new: str, old_name: str, new_name: str, limit: int = 12000) -> str:
    diff = "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), fromfile=old_name, tofile=new_name))
    return diff[:limit]


# ----------------------------- sync logic -----------------------------

def portal_record_hash(
    record: dict[str, Any],
    fm: dict[str, Any],
    *,
    ddb_sheet: str = "",
    description: str | None = None,
    bio: str | None = None,
) -> str:
    if record.get("op_kind") == "Character":
        return content_hash(
            fm,
            gm_info=record.get("game_master_info") or "",
            description=description if description is not None else (record.get("description") or ""),
            bio=bio if bio is not None else (record.get("bio") or ""),
            ddb_sheet=ddb_sheet,
        )
    return content_hash(fm, body=record.get("body") or "", gm_info=record.get("game_master_info") or "")


def meta_repo_path(meta: dict[str, Any], *, is_character: bool) -> str:
    if is_character:
        return page_path({**meta, "op_kind": "Character"})
    return page_path(meta)


def portal_index_unchanged(
    meta: dict[str, Any],
    known: dict[str, Any],
    *,
    repo_blobs: dict[str, str],
    is_character: bool,
) -> bool:
    if not known or known.get("op_updated_at") != meta.get("updated_at"):
        return False
    path = known.get("repo_path") or meta_repo_path(meta, is_character=is_character)
    return bool(path and path in repo_blobs)


def sync_pages_state_entry(
    pages_state: dict[str, Any],
    record_id: str,
    *,
    path: str,
    record: dict[str, Any],
    repo_hash: str,
    repo_blobs: dict[str, str],
) -> None:
    pages_state[record_id] = {
        "repo_path": path,
        "op_id": record_id,
        "op_kind": record.get("op_kind") or "Wiki",
        "op_slug": record.get("slug"),
        "op_updated_at": record.get("updated_at"),
        "repo_hash_at_sync": repo_hash,
        "repo_blob_sha": repo_blobs.get(path),
        "last_synced_title": record.get("title"),
    }


def refresh_pages_state_blob_shas(pages_state: dict[str, Any], repo_blobs: dict[str, str]) -> None:
    for entry in pages_state.values():
        path = entry.get("repo_path")
        if path and path in repo_blobs and not entry.get("repo_blob_sha"):
            entry["repo_blob_sha"] = repo_blobs[path]


def sync_resource_from_portal(
    meta: dict[str, Any],
    *,
    fetch_record,
    pages_state: dict[str, Any],
    repo_blobs: dict[str, str],
    is_character: bool = False,
    progress: ProgressReporter | None = None,
) -> tuple[int, list[TreeChange], int]:
    record_id = meta.get("id")
    if not record_id:
        return 0, [], 0
    title = page_title(meta)
    known = pages_state.get(record_id, {})
    if portal_index_unchanged(meta, known, repo_blobs=repo_blobs, is_character=is_character):
        return 0, [], 1
    try:
        record = fetch_record(record_id, force=True)
    except HTTPException as exc:
        if progress:
            progress.record_error(str(exc.detail), op_id=record_id, title=title, phase=progress.job.phase if progress.job else None)
        raise
    except Exception as exc:
        if progress:
            progress.record_error(str(exc), op_id=record_id, title=title, phase=progress.job.phase if progress.job else None)
        raise
    path = page_path(record)
    legacy_path = known.get("repo_path")
    old_file = gh_get_file(path) if path in repo_blobs else None
    if not old_file and legacy_path and legacy_path != path and legacy_path in repo_blobs:
        old_file = gh_get_file(legacy_path)
    preserved_ddb_sheet = ""
    preserved_ddb_fm: dict[str, Any] = {}
    preserved_description = None
    if old_file and is_character:
        existing = parse_sync_file(old_file.content)
        if existing.get("kind") == "Character" and existing["fm"].get("dndbeyond_id"):
            preserved_ddb_sheet = existing.get("ddb_sheet") or ""
            preserved_description = existing.get("description") or ""
            for key in ("dndbeyond_id", "dndbeyond_url", "dndbeyond_synced_at"):
                if existing["fm"].get(key):
                    preserved_ddb_fm[key] = existing["fm"][key]
    if is_character:
        content, fm = character_to_markdown(
            record,
            ddb_sheet=preserved_ddb_sheet,
            tagline_description=preserved_description,
        )
    else:
        content, fm = page_to_markdown(record)
    fm.update(preserved_ddb_fm)
    parsed_content = parse_sync_file(content)
    repo_hash = portal_record_hash(
        record,
        fm,
        ddb_sheet=parsed_content.get("ddb_sheet") or "",
        description=parsed_content.get("description") or "",
        bio=parsed_content.get("bio") or "",
    )
    changes: list[TreeChange] = []
    changed = 0
    if not old_file or old_file.content != content or legacy_path != path:
        changes.append(TreeChange(path, content))
        changed = 1
        if legacy_path and legacy_path != path and legacy_path in repo_blobs:
            changes.append(TreeChange(legacy_path, None))
    sync_pages_state_entry(
        pages_state,
        record_id,
        path=path,
        record=record,
        repo_hash=repo_hash,
        repo_blobs=repo_blobs,
    )
    return changed, changes, 0


def sync_from_portal_impl(progress: ProgressReporter | None = None) -> SyncResult:
    progress = progress or ProgressReporter()
    ensure_github()
    progress.phase("indexing", message="loading wiki and character indexes")
    ensure_index(force=True)
    ensure_characters_index(force=True)
    wiki_total = len(_cache["index"])
    char_total = len(_cache["characters_index"])
    logger.info("indexed %d wiki records and %d characters", wiki_total, char_total)
    state = load_state()
    changed = 0
    skipped = 0
    changes: list[TreeChange] = []
    pages_state = state.setdefault("pages", {})
    progress.phase("indexing", message="loading GitHub tree")
    repo_tree = gh_list_tree()
    repo_blobs = gh_repo_blob_index(repo_tree)

    for i, meta in enumerate(_cache["index"], start=1):
        progress.phase("fetching_wiki", current=i, total=wiki_total, title=page_title(meta))
        item_changed, item_changes, item_skipped = sync_resource_from_portal(
            meta,
            fetch_record=fetch_page,
            pages_state=pages_state,
            repo_blobs=repo_blobs,
            progress=progress,
        )
        changed += item_changed
        skipped += item_skipped
        changes.extend(item_changes)

    for i, meta in enumerate(_cache["characters_index"], start=1):
        progress.phase("fetching_characters", current=i, total=char_total, title=page_title(meta))
        item_changed, item_changes, item_skipped = sync_resource_from_portal(
            meta,
            fetch_record=fetch_character,
            pages_state=pages_state,
            repo_blobs=repo_blobs,
            is_character=True,
            progress=progress,
        )
        changed += item_changed
        skipped += item_skipped
        changes.extend(item_changes)

    commit_sha = None
    state_exists = LORE_STATE_PATH in repo_blobs
    if changed > 0 or not state_exists:
        state["last_portal_pull"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        changes.append(TreeChange(LORE_STATE_PATH, state_content(state)))
        commit_sha = gh_commit_changes(
            f"Sync from Obsidian Portal ({changed} changed)",
            changes,
            progress=progress,
        )
        if commit_sha and changed > 0:
            refresh_pages_state_blob_shas(pages_state, gh_repo_blob_index())
            follow_up = gh_commit_changes(
                "Sync from Obsidian Portal (sync-state blob metadata)",
                [TreeChange(LORE_STATE_PATH, state_content(state))],
                progress=progress,
            )
            if follow_up:
                commit_sha = follow_up
    logger.info("portal pull: %d changed, %d skipped unchanged", changed, skipped)
    progress.phase("done", message=f"changed {changed}, skipped {skipped} unchanged")
    update_sync_status_cache(state)
    return SyncResult(changed_pages=changed, committed=bool(commit_sha), commit_sha=commit_sha, message="Pulled Obsidian Portal into GitHub")


def publish_git_to_portal_impl(force_portal_pull: bool = True, progress: ProgressReporter | None = None) -> PublishResult:
    progress = progress or ProgressReporter()
    portal_pull = sync_from_portal_impl(progress=progress) if force_portal_pull else None
    state = load_state()
    pages_state = state.setdefault("pages", {})
    conflicts: list[dict[str, Any]] = []
    created = updated = skipped = deleted = 0
    repo_tree = gh_list_tree()
    repo_blobs = gh_repo_blob_index(repo_tree)
    repo_paths = sorted(gh_sync_files(repo_tree))
    repo_path_set = set(repo_paths)
    git_changes: list[TreeChange] = []
    publish_total = len(repo_paths)
    path_to_state = {
        entry.get("repo_path"): (page_id, entry)
        for page_id, entry in pages_state.items()
        if entry.get("repo_path")
    }

    for i, path in enumerate(repo_paths, start=1):
        progress.phase("publishing_portal", current=i, total=publish_total, path=path)
        page_id = None
        title = path
        try:
            blob_sha = repo_blobs.get(path)
            file = gh_get_file(path, blob_sha=blob_sha)
            if not file:
                continue
            parsed = parse_sync_file(file.content)
            fm = parsed["fm"]
            if fm.get("draft", False):
                skipped += 1
                continue
            kind = parsed["kind"]
            body = parsed["body"]
            ddb_sheet = parsed.get("ddb_sheet") or ""
            description = parsed["description"]
            bio = parsed["bio"]
            gm_info = parsed["gm_info"]
            if kind == "Character":
                fm, gm_info = migrate_character_features(fm, gm_info)
            op_description = description if kind == "Character" and fm.get("dynamic_sheet_template_id") else (
                op_character_description(ddb_sheet, description) if kind == "Character" else description
            )
            page_id = fm.get("op_id")
            had_op_id = bool(page_id)
            if not page_id:
                candidate = resolve_existing_portal_id(fm, path, kind)
                if candidate:
                    other_path = pages_state.get(candidate, {}).get("repo_path")
                    if other_path and other_path != path:
                        conflicts.append({
                            "path": path,
                            "op_id": candidate,
                            "op_kind": kind,
                            "reason": f"Obsidian Portal record already synced as {other_path}",
                            "portal_updated_at": None,
                            "known_updated_at": pages_state.get(candidate, {}).get("op_updated_at"),
                        })
                        continue
                    page_id = candidate
            current_hash = content_hash(
                fm,
                body=body,
                gm_info=gm_info,
                description=description,
                bio=bio,
                ddb_sheet=ddb_sheet,
            )
            title = fm.get("name") or fm.get("title") or path

            if page_id:
                known = pages_state.get(page_id, {})
                if (
                    current_hash == known.get("repo_hash_at_sync")
                    and blob_sha
                    and blob_sha == known.get("repo_blob_sha")
                    and not needs_feature_migration(parsed["fm"], parsed.get("gm_info") or "")
                ):
                    skipped += 1
                    if blob_sha:
                        known["repo_blob_sha"] = blob_sha
                    continue
                if kind == "Character":
                    ensure_characters_index(force=True)
                    meta = next((c for c in _cache["characters_index"] if c.get("id") == page_id), None)
                else:
                    ensure_index(force=True)
                    meta = next((p for p in _cache["index"] if p.get("id") == page_id), None)
                if meta and known.get("op_updated_at") and meta.get("updated_at") != known.get("op_updated_at"):
                    conflicts.append({
                        "path": path,
                        "op_id": page_id,
                        "op_kind": kind,
                        "reason": "Obsidian Portal changed after the repo's last synced base",
                        "portal_updated_at": meta.get("updated_at"),
                        "known_updated_at": known.get("op_updated_at"),
                    })
                    continue
                progress.phase("publishing_portal", current=i, total=publish_total, path=path, title=title)
                stale_id = page_id if had_op_id else None
                pushed, page_id = push_portal_record(
                    page_id,
                    kind,
                    fm,
                    body=body,
                    description=op_description,
                    bio=bio,
                    gm_info=gm_info,
                    path=path,
                )
                updated += 1
                if not had_op_id or stale_id != page_id:
                    if stale_id and stale_id in pages_state:
                        del pages_state[stale_id]
                    if kind == "Character":
                        new_content, new_fm = character_to_markdown(
                            pushed,
                            ddb_sheet=ddb_sheet,
                            tagline_description=description,
                        )
                        new_fm.update({k: fm[k] for k in ("dndbeyond_id", "dndbeyond_url", "dndbeyond_synced_at") if fm.get(k)})
                        new_content = rebuild_character_content(
                            new_fm,
                            ddb_sheet=ddb_sheet,
                            description=description,
                            bio=bio,
                            gm_info=gm_info,
                        )
                    else:
                        new_content, new_fm = page_to_markdown(pushed)
                    git_changes.append(TreeChange(path, new_content))
                sync_pages_state_entry(
                    pages_state,
                    page_id,
                    path=path,
                    record=pushed,
                    repo_hash=content_hash(
                        fm,
                        gm_info=gm_info,
                        description=description,
                        bio=bio,
                        ddb_sheet=ddb_sheet,
                    ),
                    repo_blobs=repo_blobs,
                )
            else:
                if not ALLOW_CREATE_FROM_GIT:
                    skipped += 1
                    continue
                if re.search(r"^op_id:\s", body, re.MULTILINE):
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            f"{path} looks like an existing synced page but frontmatter was not parsed "
                            "(often CRLF line endings). Fix the file and retry."
                        ),
                    )
                progress.phase("publishing_portal", current=i, total=publish_total, path=path, title=title)
                if kind == "Character":
                    pushed = create_op_character(fm, op_description, bio, gm_info, path=path)
                else:
                    pushed = create_op_page(fm, body, gm_info, path=path)
                created += 1
                if kind == "Character":
                    new_content, new_fm = character_to_markdown(
                        pushed,
                        ddb_sheet=ddb_sheet,
                        tagline_description=description,
                    )
                    new_fm.update({k: fm[k] for k in ("dndbeyond_id", "dndbeyond_url", "dndbeyond_synced_at") if fm.get(k)})
                    new_content = rebuild_character_content(
                        new_fm,
                        ddb_sheet=ddb_sheet,
                        description=description,
                        bio=bio,
                        gm_info=gm_info,
                    )
                else:
                    new_content, new_fm = page_to_markdown(pushed)
                git_changes.append(TreeChange(path, new_content))
                sync_pages_state_entry(
                    pages_state,
                    pushed["id"],
                    path=path,
                    record=pushed,
                    repo_hash=content_hash(
                        new_fm,
                        gm_info=gm_info,
                        description=description,
                        bio=bio,
                        ddb_sheet=ddb_sheet,
                    ),
                    repo_blobs=repo_blobs,
                )
        except HTTPException as exc:
            progress.record_error(str(exc.detail), phase="publishing_portal", path=path, op_id=page_id, title=title)
            raise
        except Exception as exc:
            progress.record_error(str(exc), phase="publishing_portal", path=path, op_id=page_id, title=title)
            raise

    if ALLOW_DELETE_FROM_GIT:
        progress.phase("deleting_portal", message="checking deleted repo files")
        for page_id, known in list(pages_state.items()):
            path = known.get("repo_path")
            if path and path not in repo_path_set:
                kind = known.get("op_kind") or ("Character" if path.startswith(f"{LORE_CHARACTERS_DIR}/") else "Wiki")
                try:
                    if kind == "Character":
                        op_delete(f"/campaigns/{CAMPAIGN_ID}/characters/{page_id}.json")
                    else:
                        op_delete(f"/campaigns/{CAMPAIGN_ID}/wikis/{page_id}.json")
                except HTTPException as exc:
                    if exc.status_code != 404:
                        progress.record_error(str(exc.detail), phase="deleting_portal", path=path, op_id=page_id)
                        raise
                deleted += 1
                del pages_state[page_id]

    if created or updated or deleted or git_changes:
        state["last_git_publish"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        git_changes.append(TreeChange(LORE_STATE_PATH, state_content(state)))
        parts = []
        if created:
            parts.append(f"{created} created")
        if updated:
            parts.append(f"{updated} updated")
        if deleted:
            parts.append(f"{deleted} deleted")
        message = "Publish to Obsidian Portal"
        if parts:
            message += f" ({', '.join(parts)})"
        gh_commit_changes(message, git_changes, progress=progress)

    update_sync_status_cache(state)
    progress.phase("done", message=f"created={created} updated={updated} skipped={skipped} conflicts={len(conflicts)}")
    return PublishResult(
        portal_pull=portal_pull,
        created=created,
        updated=updated,
        deleted=deleted,
        skipped=skipped,
        conflicts=conflicts,
        ok=len(conflicts) == 0,
        message="Published GitHub main to Obsidian Portal" if not conflicts else "Conflicts found; no conflicted files were published",
    )


def sync_from_dndbeyond_bridge(progress: ProgressReporter | None = None) -> DdbSyncResponse:
    result = sync_from_dndbeyond_impl(
        gh_sync_files=lambda: gh_sync_files(gh_list_tree()),
        gh_get_file=gh_get_file,
        gh_commit_changes=gh_commit_changes,
        parse_sync_file=parse_sync_file,
        rebuild_character_content=rebuild_character_content,
        TreeChange=TreeChange,
        LORE_CHARACTERS_DIR=LORE_CHARACTERS_DIR,
        progress=progress,
        dynamic_sheet_template_id=DYNAMIC_SHEET_TEMPLATE_ID,
    )
    return DdbSyncResponse(**result.model_dump())


# ----------------------------- sync jobs -----------------------------

def update_sync_status_cache(state: dict[str, Any]) -> None:
    _sync_status_cache["last_portal_pull"] = state.get("last_portal_pull")
    _sync_status_cache["last_git_publish"] = state.get("last_git_publish")
    _sync_status_cache["fetched_at"] = time.time()


def refresh_sync_status_cache(*, force: bool = False) -> dict[str, Any]:
    now = time.time()
    if not force and now - float(_sync_status_cache.get("fetched_at") or 0) < SYNC_STATUS_CACHE_TTL:
        return _sync_status_cache
    if not (GITHUB_TOKEN and GITHUB_OWNER and GITHUB_REPO):
        return _sync_status_cache
    try:
        state = load_state()
        update_sync_status_cache(state)
    except Exception:
        pass
    return _sync_status_cache


def job_public_snapshot(job: SyncJobRecord) -> dict[str, Any]:
    percent = round(job.current / job.total * 100) if job.total else None
    detail = job.current_title or job.current_path
    return {
        "job_id": job.job_id,
        "kind": job.kind,
        "kind_label": JOB_KIND_LABELS.get(job.kind, job.kind),
        "status": job.status,
        "phase": job.phase,
        "phase_label": PHASE_LABELS.get(job.phase, job.phase.replace("_", " ").title()),
        "current": job.current,
        "total": job.total,
        "percent": percent,
        "message": job.message,
        "detail": detail,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }


def _running_job_unlocked() -> SyncJobRecord | None:
    if _active_job_id and _active_job_id in _jobs:
        job = _jobs[_active_job_id]
        if job.status == "running":
            return job
    return None


def active_job() -> SyncJobRecord | None:
    with _job_lock:
        return _running_job_unlocked()


def start_sync_job(kind: str, runner: Callable[[ProgressReporter], Any]) -> str:
    job_id, job = _begin_sync_job(kind)

    def execute() -> None:
        try:
            _execute_sync_job(job_id, job, runner)
        except Exception:
            pass

    threading.Thread(target=execute, daemon=True).start()
    logger.info("sync job %s started (%s)", job_id, kind)
    return job_id


def _begin_sync_job(kind: str) -> tuple[str, SyncJobRecord]:
    with _job_lock:
        current = _running_job_unlocked()
        if current:
            raise HTTPException(
                status_code=409,
                detail=f"Sync job {current.job_id} is already running ({current.phase})",
            )
        job_id = uuid.uuid4().hex
        job = SyncJobRecord(job_id=job_id, kind=kind, started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        _jobs[job_id] = job
        global _active_job_id
        _active_job_id = job_id
    return job_id, job


def _finish_sync_job(job_id: str) -> None:
    with _job_lock:
        global _active_job_id
        if _active_job_id == job_id:
            _active_job_id = None


def _execute_sync_job(job_id: str, job: SyncJobRecord, runner: Callable[[ProgressReporter], Any]) -> Any:
    progress = ProgressReporter(job)
    try:
        result = runner(progress)
        job.status = "completed"
        job.result = result.model_dump() if hasattr(result, "model_dump") else result
        job.message = getattr(result, "message", None) or "Completed"
        logger.info("sync job %s completed (%s)", job_id, job.kind)
        return result
    except Exception as exc:
        job.status = "failed"
        if isinstance(exc, HTTPException):
            detail = str(exc.detail)
        else:
            detail = str(exc)
        job.message = detail[:500]
        if not job.errors:
            job.errors.append(JobError(phase=job.phase, detail=detail))
        logger.exception("sync job %s failed (%s)", job_id, job.kind)
        raise
    finally:
        job.finished_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        _finish_sync_job(job_id)


def run_sync_job_blocking(kind: str, runner: Callable[[ProgressReporter], Any]) -> Any:
    job_id, job = _begin_sync_job(kind)
    logger.info("sync job %s started (%s, blocking)", job_id, kind)
    return _execute_sync_job(job_id, job, runner)


def get_sync_job(job_id: str) -> SyncJobRecord:
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Unknown sync job: {job_id}")
    return job


# ----------------------------- API routes -----------------------------

def health_payload(*, authenticated: bool) -> dict[str, Any]:
    sync_times = refresh_sync_status_cache()
    running = active_job()
    payload: dict[str, Any] = {
        "ok": True,
        "service": app.title,
        "version": app.version,
        "campaign_id_configured": bool(CAMPAIGN_ID),
        "github_configured": bool(GITHUB_TOKEN and GITHUB_OWNER and GITHUB_REPO),
        "branch": GITHUB_BRANCH,
        "message": "Bridge is running. Sync and lore API endpoints require Authorization: Bearer <LORE_BRIDGE_API_KEY>.",
        "last_portal_pull": sync_times.get("last_portal_pull"),
        "last_git_publish": sync_times.get("last_git_publish"),
        "active_job": job_public_snapshot(running) if running else None,
    }
    if authenticated:
        payload["last_sync"] = _cache["last_sync"]
        payload["wiki_index_cached"] = bool(_cache["index"])
        payload["characters_index_cached"] = bool(_cache["characters_index"])
    return payload


def _format_ts_display(value: str | None) -> str:
    if not value:
        return "never"
    return f'{value.replace("T", " ").rstrip("Z")} UTC'


def status_html(payload: dict[str, Any]) -> str:
    def row(label: str, ok: bool) -> str:
        mark = "✓" if ok else "✗"
        css = "ok" if ok else "bad"
        return f'<tr><td>{label}</td><td class="{css}">{mark}</td></tr>'

    extra = ""
    if "last_sync" in payload:
        extra = f'<p class="meta">In-memory index last refreshed: {payload["last_sync"] or "not yet"}</p>'

    job = payload.get("active_job")
    job_html = ""
    poll_script = ""
    if job and job.get("status") == "running":
        percent = job.get("percent")
        width = f"{percent}%" if percent is not None else "35%"
        indeterminate = "" if percent is not None else " indeterminate"
        count = ""
        if job.get("total"):
            count = f' <span id="sync-count">{job["current"]}/{job["total"]}</span>'
        detail = job.get("detail") or job.get("message") or ""
        job_html = f"""
  <section id="sync-progress" class="sync-panel" aria-live="polite">
    <p class="sync-heading"><strong id="sync-kind">{job.get("kind_label", "Sync")}</strong> · <span id="sync-phase">{job.get("phase_label", "Running")}</span>{count}</p>
    <div class="progress-track{indeterminate}" id="sync-track"><div class="progress-fill" id="sync-bar" style="width:{width}"></div></div>
    <p class="meta" id="sync-detail">{detail}</p>
  </section>"""
        poll_script = """
  <script>
    (function () {
      function fmt(ts) {
        if (!ts) return "never";
        try { return new Date(ts.endsWith("Z") ? ts : ts + "Z").toLocaleString(); }
        catch (e) { return ts; }
      }
      function apply(data) {
        var portal = document.getElementById("last-portal-pull");
        var publish = document.getElementById("last-git-publish");
        if (portal) portal.textContent = fmt(data.last_portal_pull);
        if (publish) publish.textContent = fmt(data.last_git_publish);
        var job = data.active_job;
        var panel = document.getElementById("sync-progress");
        if (!job || job.status !== "running") {
          if (panel) location.reload();
          return;
        }
        if (!panel) { location.reload(); return; }
        document.getElementById("sync-kind").textContent = job.kind_label || job.kind;
        document.getElementById("sync-phase").textContent = job.phase_label || job.phase;
        var count = document.getElementById("sync-count");
        if (job.total) {
          if (!count) {
            count = document.createElement("span");
            count.id = "sync-count";
            document.getElementById("sync-phase").after(" ", count);
          }
          count.textContent = job.current + "/" + job.total;
        } else if (count) {
          count.remove();
        }
        var track = document.getElementById("sync-track");
        var bar = document.getElementById("sync-bar");
        if (job.percent != null) {
          track.classList.remove("indeterminate");
          bar.style.width = job.percent + "%";
        } else {
          track.classList.add("indeterminate");
          bar.style.width = "35%";
        }
        document.getElementById("sync-detail").textContent = job.detail || job.message || "";
      }
      setInterval(function () {
        fetch("/health", { headers: { Accept: "application/json" } })
          .then(function (r) { return r.json(); })
          .then(apply)
          .catch(function () {});
      }, 2000);
    })();
  </script>"""

    portal_ts = _format_ts_display(payload.get("last_portal_pull"))
    publish_ts = _format_ts_display(payload.get("last_git_publish"))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{payload["service"]}</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 42rem; margin: 2rem auto; padding: 0 1rem; line-height: 1.5; color: #1a1a1a; }}
    h1 {{ font-size: 1.5rem; margin-bottom: 0.25rem; }}
    .badge {{ display: inline-block; background: #e6f4ea; color: #137333; padding: 0.2rem 0.6rem; border-radius: 999px; font-size: 0.875rem; }}
    table {{ border-collapse: collapse; margin: 1.25rem 0; width: 100%; }}
    td {{ padding: 0.35rem 0; border-bottom: 1px solid #eee; }}
    td:last-child {{ text-align: right; font-weight: 600; }}
    .ok {{ color: #137333; }} .bad {{ color: #c5221f; }}
    .meta, .note {{ color: #555; font-size: 0.925rem; }}
    a {{ color: #1558d6; }}
    code {{ background: #f4f4f4; padding: 0.1rem 0.35rem; border-radius: 3px; }}
    .sync-panel {{ margin: 1.25rem 0; padding: 1rem; background: #f8f9fc; border: 1px solid #e3e6ee; border-radius: 8px; }}
    .sync-heading {{ margin: 0 0 0.75rem; }}
    .progress-track {{ height: 0.55rem; background: #e3e6ee; border-radius: 999px; overflow: hidden; }}
    .progress-fill {{ height: 100%; background: #1558d6; border-radius: 999px; transition: width 0.35s ease; }}
    .progress-track.indeterminate .progress-fill {{ width: 35% !important; animation: sync-slide 1.2s ease-in-out infinite; }}
    @keyframes sync-slide {{ 0% {{ transform: translateX(-120%); }} 100% {{ transform: translateX(320%); }} }}
  </style>
</head>
<body>
  <p class="badge">Running</p>
  <h1>{payload["service"]}</h1>
  <p>Obsidian Portal ↔ GitHub lore sync bridge (v{payload["version"]}).</p>
  <p>{payload["message"]}</p>
  <table>
    {row("Obsidian Portal campaign configured", payload["campaign_id_configured"])}
    {row("GitHub lore repo configured", payload["github_configured"])}
  </table>
  <p class="meta">Git branch: <code>{payload["branch"]}</code></p>
  <table>
    <tr><td>Last portal → GitHub sync</td><td id="last-portal-pull">{portal_ts}</td></tr>
    <tr><td>Last GitHub → portal publish</td><td id="last-git-publish">{publish_ts}</td></tr>
  </table>
  {job_html}
  {extra}
  <p class="note">API docs: <a href="/docs">/docs</a> · JSON status: <a href="/health">/health</a></p>
  {poll_script}
</body>
</html>"""


def wants_html(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "text/html" in accept and "application/json" not in accept


@app.get("/", response_class=HTMLResponse, response_model=None)
def root(request: Request):
    payload = health_payload(authenticated=False)
    if wants_html(request):
        return HTMLResponse(status_html(payload))
    return JSONResponse(payload)


@app.get("/health", response_model=None)
def health(request: Request, authorization: str | None = Header(default=None)):
    authenticated = bool(BRIDGE_KEY and authorization == f"Bearer {BRIDGE_KEY}")
    payload = health_payload(authenticated=authenticated)
    if wants_html(request):
        return HTMLResponse(status_html(payload))
    return JSONResponse(payload)


@app.post("/sync", response_model=SyncResult, dependencies=[Depends(require_auth)])
def sync_legacy() -> SyncResult:
    ensure_index(force=True)
    return SyncResult(changed_pages=len(_cache["index"]), committed=False, message="Refreshed in-memory Obsidian Portal index only")


@app.post("/sync/from-portal", dependencies=[Depends(require_auth)])
def sync_from_portal(async_mode: bool = Query(False, alias="async")):
    if async_mode:
        job_id = start_sync_job("from-portal", lambda progress: sync_from_portal_impl(progress))
        body = JobStartResponse(job_id=job_id, kind="from-portal").model_dump()
        return JSONResponse(status_code=202, content=body)
    return run_sync_job_blocking("from-portal", lambda progress: sync_from_portal_impl(progress))


@app.post("/sync/from-dndbeyond", dependencies=[Depends(require_auth)])
def sync_from_dndbeyond(async_mode: bool = Query(False, alias="async")):
    if async_mode:
        job_id = start_sync_job("from-dndbeyond", lambda progress: sync_from_dndbeyond_bridge(progress))
        body = JobStartResponse(job_id=job_id, kind="from-dndbeyond").model_dump()
        return JSONResponse(status_code=202, content=body)
    return run_sync_job_blocking("from-dndbeyond", lambda progress: sync_from_dndbeyond_bridge(progress))


@app.post("/sync/publish-main", dependencies=[Depends(require_auth)])
def publish_main(async_mode: bool = Query(False, alias="async")):
    if async_mode:
        job_id = start_sync_job("publish-main", lambda progress: publish_git_to_portal_impl(force_portal_pull=True, progress=progress))
        body = JobStartResponse(job_id=job_id, kind="publish-main").model_dump()
        return JSONResponse(status_code=202, content=body)
    return run_sync_job_blocking("publish-main", lambda progress: publish_git_to_portal_impl(force_portal_pull=True, progress=progress))


@app.get("/sync/jobs/current", response_model=SyncJobRecord, dependencies=[Depends(require_auth)])
def sync_job_current() -> SyncJobRecord:
    job = active_job()
    if not job:
        raise HTTPException(status_code=404, detail="No sync job is currently running")
    return job


@app.get("/sync/jobs/{job_id}", response_model=SyncJobRecord, dependencies=[Depends(require_auth)])
def sync_job_status(job_id: str) -> SyncJobRecord:
    return get_sync_job(job_id)


@app.post("/github/webhook")
async def github_webhook(request: Request, x_hub_signature_256: str | None = Header(default=None), x_github_event: str | None = Header(default=None)) -> dict[str, Any]:
    raw = await request.body()
    verify_github_signature(raw, x_hub_signature_256)
    payload = json.loads(raw.decode("utf-8")) if raw else {}
    if x_github_event != "push":
        return {"ok": True, "ignored": True, "reason": f"Ignoring {x_github_event}"}
    ref = payload.get("ref")
    if ref != f"refs/heads/{GITHUB_BRANCH}":
        return {"ok": True, "ignored": True, "reason": f"Ignoring {ref}"}
    commits = payload.get("commits") or []
    if commits and all((c.get("author") or {}).get("email") == GITHUB_AUTHOR_EMAIL for c in commits):
        return {"ok": True, "ignored": True, "reason": "Ignoring bridge-authored commit to avoid webhook loop"}
    result = run_sync_job_blocking(
        "publish-main",
        lambda progress: publish_git_to_portal_impl(force_portal_pull=True, progress=progress),
    )
    return result.model_dump()


@app.get("/search_lore", response_model=SearchResponse, dependencies=[Depends(require_auth)])
def search_lore(q: str = Query(...), limit: int = Query(8, ge=1, le=20), include_full_text: bool = Query(False)) -> SearchResponse:
    ensure_index()
    query = q.lower().strip()
    results: list[SearchResult] = []
    for meta in _cache["index"]:
        title = page_title(meta)
        tags = meta.get("tags") or []
        haystack = " ".join([title, meta.get("slug") or "", " ".join(tags), meta.get("type") or ""])
        page = None
        if include_full_text:
            try:
                page = fetch_page(meta.get("id") or meta.get("slug"))
                haystack += " " + (page.get("body") or "") + " " + (page.get("game_master_info") or "")
            except Exception:
                pass
        score = max(fuzz.partial_ratio(query, haystack.lower()), fuzz.token_set_ratio(query, haystack.lower()))
        if score >= 35:
            snippet = compact_snippet(" ".join([page.get("body") or "", page.get("game_master_info") or ""])) if page else None
            results.append(SearchResult(
                id=meta.get("id"), slug=meta.get("slug"), title=title, url=meta.get("wiki_page_url"), type=meta.get("type"),
                tags=tags, updated_at=meta.get("updated_at"), snippet=snippet, score=float(score),
            ))
    results.sort(key=lambda r: r.score, reverse=True)
    return SearchResponse(results=results[:limit])


@app.get("/get_page", response_model=PageResponse, dependencies=[Depends(require_auth)])
def get_page(id_or_slug: str = Query(...)) -> PageResponse:
    return PageResponse(**fetch_page(id_or_slug))


@app.get("/search_characters", response_model=SearchResponse, dependencies=[Depends(require_auth)])
def search_characters(q: str = Query(...), limit: int = Query(8, ge=1, le=20), include_full_text: bool = Query(False)) -> SearchResponse:
    ensure_characters_index()
    query = q.lower().strip()
    results: list[SearchResult] = []
    for meta in _cache["characters_index"]:
        title = meta.get("name") or meta.get("slug") or meta.get("id") or "Untitled"
        tags = meta.get("tags") or []
        haystack = " ".join([title, meta.get("slug") or "", " ".join(tags)])
        character = None
        if include_full_text:
            try:
                character = fetch_character(meta.get("id") or meta.get("slug") or "")
                haystack += " " + (character.get("description") or "") + " " + (character.get("bio") or "") + " " + (character.get("game_master_info") or "")
            except Exception:
                pass
        score = max(fuzz.partial_ratio(query, haystack.lower()), fuzz.token_set_ratio(query, haystack.lower()))
        if score >= 35:
            snippet = None
            if character:
                snippet = compact_snippet(" ".join([
                    character.get("description") or "",
                    character.get("bio") or "",
                    character.get("game_master_info") or "",
                ]))
            results.append(SearchResult(
                id=meta.get("id"), slug=meta.get("slug"), title=title, url=meta.get("character_url"), type="Character",
                tags=tags, updated_at=meta.get("updated_at"), snippet=snippet, score=float(score),
            ))
    results.sort(key=lambda r: r.score, reverse=True)
    return SearchResponse(results=results[:limit])


@app.get("/get_character", response_model=CharacterResponse, dependencies=[Depends(require_auth)])
def get_character(id_or_slug: str = Query(...)) -> CharacterResponse:
    character = fetch_character(id_or_slug)
    return CharacterResponse(
        id=character["id"],
        slug=character.get("slug"),
        title=character.get("title") or character.get("name") or "Untitled",
        name=character.get("name"),
        url=character.get("url"),
        tags=character.get("tags") or [],
        updated_at=character.get("updated_at"),
        description=character.get("description"),
        bio=character.get("bio"),
        game_master_info=character.get("game_master_info"),
        is_game_master_only=bool(character.get("is_game_master_only")),
        is_player_character=bool(character.get("is_player_character")),
        tagline=character.get("tagline"),
    )


@app.get("/recent_changes", response_model=SearchResponse, dependencies=[Depends(require_auth)])
def recent_changes(limit: int = Query(10, ge=1, le=30)) -> SearchResponse:
    ensure_index()
    pages = sorted(_cache["index"], key=lambda p: p.get("updated_at") or "", reverse=True)[:limit]
    return SearchResponse(results=[SearchResult(
        id=p.get("id"), slug=p.get("slug"), title=page_title(p), url=p.get("wiki_page_url"), type=p.get("type"),
        tags=p.get("tags") or [], updated_at=p.get("updated_at"), score=100.0,
    ) for p in pages])


@app.get("/diff/repo-vs-portal", dependencies=[Depends(require_auth)])
def diff_repo_vs_portal(path: str = Query(..., description="Synced file path in repo, e.g. lore/wiki/wiki/blackspire.textile")) -> dict[str, Any]:
    file = gh_get_file(path)
    if not file:
        raise HTTPException(status_code=404, detail="Repo file not found")
    parsed = parse_sync_file(file.content)
    fm = parsed["fm"]
    page_id = fm.get("op_id")
    if not page_id:
        raise HTTPException(status_code=400, detail="Repo file has no op_id; it would create a new portal record")
    if parsed["kind"] == "Character":
        portal = fetch_character(page_id, force=True)
    else:
        portal = fetch_page(page_id, force=True)
    portal_content, _ = page_to_markdown(portal)
    return {"path": path, "op_id": page_id, "op_kind": parsed["kind"], "diff": unified_diff(portal_content, file.content, "portal", "repo")}
