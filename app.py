import base64
import difflib
import hashlib
import hmac
import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any

import requests
import yaml
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from pydantic import BaseModel
from rapidfuzz import fuzz
from requests_oauthlib import OAuth1

load_dotenv()

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
LORE_STATE_PATH = os.environ.get("LORE_STATE_PATH", "metadata/sync-state.json").strip("/")
ALLOW_CREATE_FROM_GIT = os.environ.get("ALLOW_CREATE_FROM_GIT", "true").lower() == "true"
ALLOW_DELETE_FROM_GIT = os.environ.get("ALLOW_DELETE_FROM_GIT", "false").lower() == "true"

app = FastAPI(
    title="Sindrel Lore Bridge",
    version="0.3.0",
    description="Bidirectional Obsidian Portal ↔ GitHub lore sync bridge with pull-through conflict protection.",
)

_cache: dict[str, Any] = {"last_sync": 0, "index": [], "pages": {}}


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


@dataclass
class RepoFile:
    path: str
    content: str
    sha: str | None = None


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


def html_to_text(value: str | None) -> str:
    if not value:
        return ""
    return BeautifulSoup(value, "html.parser").get_text(" ", strip=True)


def page_title(page: dict[str, Any]) -> str:
    return page.get("post_title") or page.get("name") or page.get("slug") or page.get("id") or "Untitled"


def compact_snippet(text: str, limit: int = 500) -> str:
    text = " ".join(text.split())
    return text[:limit] + ("..." if len(text) > limit else "")


def normalize_page(page: dict[str, Any]) -> dict[str, Any]:
    body = page.get("body") or html_to_text(page.get("body_html"))
    gm = page.get("game_master_info") or html_to_text(page.get("game_master_info_html"))
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


def update_op_page(page_id: str, frontmatter: dict[str, Any], body: str, gm_info: str) -> dict[str, Any]:
    wiki_page = {
        "body": body,
        "tags": frontmatter.get("tags") or [],
        "game_master_info": gm_info,
        "is_game_master_only": bool(frontmatter.get("op_gm_only", False)),
    }
    if frontmatter.get("name"):
        wiki_page["name"] = frontmatter["name"]
    return normalize_page(op_put(f"/campaigns/{CAMPAIGN_ID}/wikis/{page_id}.json", {"wiki_page": wiki_page}))


def create_op_page(frontmatter: dict[str, Any], body: str, gm_info: str) -> dict[str, Any]:
    wiki_page = {
        "name": frontmatter.get("name") or frontmatter.get("title") or "Untitled Page",
        "body": body,
        "tags": frontmatter.get("tags") or [],
        "game_master_info": gm_info,
        "is_game_master_only": bool(frontmatter.get("op_gm_only", False)),
    }
    if frontmatter.get("op_type"):
        wiki_page["type"] = frontmatter["op_type"]
    return normalize_page(op_post(f"/campaigns/{CAMPAIGN_ID}/wikis.json", {"wiki_page": wiki_page}))


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
    response = requests.request(method, url, headers=gh_headers(), json=payload, params=params, timeout=30)
    if response.status_code not in ok:
        raise HTTPException(status_code=502, detail=f"GitHub {method} {path} failed: {response.status_code} {response.text[:1500]}")
    if response.status_code == 204 or not response.text:
        return None
    return response.json()


def gh_get_file(path: str) -> RepoFile | None:
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


def gh_put_file(path: str, content: str, message: str, sha: str | None = None) -> str:
    payload: dict[str, Any] = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "branch": GITHUB_BRANCH,
        "committer": {"name": GITHUB_AUTHOR_NAME, "email": GITHUB_AUTHOR_EMAIL},
        "author": {"name": GITHUB_AUTHOR_NAME, "email": GITHUB_AUTHOR_EMAIL},
    }
    if sha:
        payload["sha"] = sha
    data = gh_api("PUT", f"/contents/{path}", payload=payload)
    return data.get("commit", {}).get("sha")


def gh_delete_file(path: str, message: str, sha: str) -> str:
    payload = {
        "message": message,
        "sha": sha,
        "branch": GITHUB_BRANCH,
        "committer": {"name": GITHUB_AUTHOR_NAME, "email": GITHUB_AUTHOR_EMAIL},
        "author": {"name": GITHUB_AUTHOR_NAME, "email": GITHUB_AUTHOR_EMAIL},
    }
    data = gh_api("DELETE", f"/contents/{path}", payload=payload, ok=(200,))
    return data.get("commit", {}).get("sha")


def gh_list_tree() -> list[dict[str, Any]]:
    branch = gh_api("GET", f"/branches/{GITHUB_BRANCH}")
    tree_sha = branch["commit"]["commit"]["tree"]["sha"]
    tree = gh_api("GET", f"/git/trees/{tree_sha}", params={"recursive": "1"})
    return tree.get("tree") or []


def gh_markdown_files() -> list[str]:
    prefix = f"{LORE_WIKI_DIR}/"
    return [item["path"] for item in gh_list_tree() if item.get("type") == "blob" and item.get("path", "").startswith(prefix) and item["path"].endswith(".md")]


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


def save_state(state: dict[str, Any], message: str) -> str:
    old = gh_get_file(LORE_STATE_PATH)
    content = json.dumps(state, indent=2, sort_keys=True) + "\n"
    return gh_put_file(LORE_STATE_PATH, content, message, old.sha if old else None)


# ----------------------------- markdown mapping -----------------------------

def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return re.sub(r"-+", "-", value).strip("-") or "untitled"


def body_hash(body: str, gm_info: str, fm: dict[str, Any]) -> str:
    comparable = {
        "body": body or "",
        "game_master_info": gm_info or "",
        "tags": fm.get("tags") or [],
        "name": fm.get("name") or fm.get("title") or "",
        "op_gm_only": bool(fm.get("op_gm_only", False)),
        "op_type": fm.get("op_type") or "WikiPage",
    }
    return hashlib.sha256(json.dumps(comparable, sort_keys=True).encode()).hexdigest()


def page_path(page: dict[str, Any]) -> str:
    prefix = "adventure-log" if page.get("type") == "Post" else "wiki"
    name = page.get("slug") or slugify(page.get("title") or page.get("name") or page["id"])
    return f"{LORE_WIKI_DIR}/{prefix}/{name}.md"


def page_to_markdown(page: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    fm = {
        "op_id": page.get("id"),
        "op_slug": page.get("slug"),
        "op_type": page.get("type") or "WikiPage",
        "name": page.get("name") or page.get("title"),
        "title": page.get("title"),
        "op_url": page.get("url"),
        "op_created_at": page.get("created_at"),
        "op_updated_at": page.get("updated_at"),
        "op_gm_only": bool(page.get("is_game_master_only")),
        "tags": page.get("tags") or [],
    }
    if page.get("post_tagline"):
        fm["post_tagline"] = page["post_tagline"]
    if page.get("post_time"):
        fm["post_time"] = page["post_time"]
    front = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True).strip()
    body = page.get("body") or ""
    gm = page.get("game_master_info") or ""
    content = f"---\n{front}\n---\n\n{body.rstrip()}\n"
    if gm:
        content += f"\n<!-- GM_INFO_START -->\n{gm.rstrip()}\n<!-- GM_INFO_END -->\n"
    return content, fm


def parse_markdown(content: str) -> tuple[dict[str, Any], str, str]:
    if not content.startswith("---\n"):
        return {}, content, ""
    end = content.find("\n---", 4)
    if end == -1:
        return {}, content, ""
    front = content[4:end]
    rest = content[end + 4 :].lstrip("\n")
    fm = yaml.safe_load(front) or {}
    gm_info = ""
    marker_start = "<!-- GM_INFO_START -->"
    marker_end = "<!-- GM_INFO_END -->"
    if marker_start in rest and marker_end in rest:
        before, after_start = rest.split(marker_start, 1)
        gm_info, after_end = after_start.split(marker_end, 1)
        body = before.rstrip() + after_end.strip("\n")
        gm_info = gm_info.strip("\n")
    else:
        body = rest
    return fm, body.rstrip() + "\n", gm_info


def unified_diff(old: str, new: str, old_name: str, new_name: str, limit: int = 12000) -> str:
    diff = "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), fromfile=old_name, tofile=new_name))
    return diff[:limit]


# ----------------------------- sync logic -----------------------------

def sync_from_portal_impl() -> SyncResult:
    ensure_github()
    ensure_index(force=True)
    state = load_state()
    changed = 0
    last_commit: str | None = None
    pages_state = state.setdefault("pages", {})

    for meta in _cache["index"]:
        page_id = meta.get("id")
        if not page_id:
            continue
        known = pages_state.get(page_id, {})
        if known.get("op_updated_at") == meta.get("updated_at") and known.get("repo_path"):
            continue
        page = fetch_page(page_id, force=True)
        content, fm = page_to_markdown(page)
        path = known.get("repo_path") or page_path(page)
        old_file = gh_get_file(path)
        repo_hash = body_hash(page.get("body") or "", page.get("game_master_info") or "", fm)
        if old_file and old_file.content == content:
            pass
        else:
            last_commit = gh_put_file(
                path,
                content,
                f"Sync from Obsidian Portal: {page.get('title') or page_id}",
                old_file.sha if old_file else None,
            )
            changed += 1
        pages_state[page_id] = {
            "repo_path": path,
            "op_id": page_id,
            "op_slug": page.get("slug"),
            "op_updated_at": page.get("updated_at"),
            "repo_hash_at_sync": repo_hash,
            "last_synced_title": page.get("title"),
        }

    state_commit = None
    if changed > 0 or gh_get_file(LORE_STATE_PATH) is None:
        state["last_portal_pull"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        state_commit = save_state(state, "Update sync state after Obsidian Portal pull")
    return SyncResult(changed_pages=changed, committed=changed > 0, commit_sha=last_commit or state_commit, message="Pulled Obsidian Portal into GitHub")


def publish_git_to_portal_impl(force_portal_pull: bool = True) -> PublishResult:
    portal_pull = sync_from_portal_impl() if force_portal_pull else None
    state = load_state()
    pages_state = state.setdefault("pages", {})
    conflicts: list[dict[str, Any]] = []
    created = updated = skipped = deleted = 0
    repo_paths = set(gh_markdown_files())

    # Publish new/changed markdown files.
    for path in sorted(repo_paths):
        file = gh_get_file(path)
        if not file:
            continue
        fm, body, gm_info = parse_markdown(file.content)
        if fm.get("draft", False):
            skipped += 1
            continue
        page_id = fm.get("op_id")
        current_hash = body_hash(body, gm_info, fm)

        if page_id:
            known = pages_state.get(page_id, {})
            if current_hash == known.get("repo_hash_at_sync"):
                skipped += 1
                continue
            ensure_index(force=True)
            meta = next((p for p in _cache["index"] if p.get("id") == page_id), None)
            if meta and known.get("op_updated_at") and meta.get("updated_at") != known.get("op_updated_at"):
                conflicts.append({
                    "path": path,
                    "op_id": page_id,
                    "reason": "Obsidian Portal changed after the repo's last synced base",
                    "portal_updated_at": meta.get("updated_at"),
                    "known_updated_at": known.get("op_updated_at"),
                })
                continue
            pushed = update_op_page(page_id, fm, body, gm_info)
            updated += 1
            pages_state[page_id] = {
                "repo_path": path,
                "op_id": page_id,
                "op_slug": pushed.get("slug"),
                "op_updated_at": pushed.get("updated_at"),
                "repo_hash_at_sync": body_hash(pushed.get("body") or body, pushed.get("game_master_info") or gm_info, fm),
                "last_synced_title": pushed.get("title"),
            }
        else:
            if not ALLOW_CREATE_FROM_GIT:
                skipped += 1
                continue
            pushed = create_op_page(fm, body, gm_info)
            created += 1
            new_content, new_fm = page_to_markdown(pushed)
            gh_put_file(path, new_content, f"Add Obsidian Portal id after creating page: {pushed.get('title')}", file.sha)
            pages_state[pushed["id"]] = {
                "repo_path": path,
                "op_id": pushed["id"],
                "op_slug": pushed.get("slug"),
                "op_updated_at": pushed.get("updated_at"),
                "repo_hash_at_sync": body_hash(pushed.get("body") or "", pushed.get("game_master_info") or "", new_fm),
                "last_synced_title": pushed.get("title"),
            }

    # Optional delete support: only delete if state says a page existed and its repo file is gone.
    if ALLOW_DELETE_FROM_GIT:
        for page_id, known in list(pages_state.items()):
            path = known.get("repo_path")
            if path and path not in repo_paths:
                op_delete(f"/campaigns/{CAMPAIGN_ID}/wikis/{page_id}.json")
                deleted += 1
                del pages_state[page_id]

    if created or updated or deleted:
        state["last_git_publish"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        save_state(state, "Update sync state after Git publish")
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


# ----------------------------- API routes -----------------------------

@app.get("/health", dependencies=[Depends(require_auth)])
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "campaign_id_configured": bool(CAMPAIGN_ID),
        "github_configured": bool(GITHUB_TOKEN and GITHUB_OWNER and GITHUB_REPO),
        "branch": GITHUB_BRANCH,
        "last_sync": _cache["last_sync"],
    }


@app.post("/sync", response_model=SyncResult, dependencies=[Depends(require_auth)])
def sync_legacy() -> SyncResult:
    ensure_index(force=True)
    return SyncResult(changed_pages=len(_cache["index"]), committed=False, message="Refreshed in-memory Obsidian Portal index only")


@app.post("/sync/from-portal", response_model=SyncResult, dependencies=[Depends(require_auth)])
def sync_from_portal() -> SyncResult:
    return sync_from_portal_impl()


@app.post("/sync/publish-main", response_model=PublishResult, dependencies=[Depends(require_auth)])
def publish_main() -> PublishResult:
    return publish_git_to_portal_impl(force_portal_pull=True)


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
    result = publish_git_to_portal_impl(force_portal_pull=True)
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


@app.get("/recent_changes", response_model=SearchResponse, dependencies=[Depends(require_auth)])
def recent_changes(limit: int = Query(10, ge=1, le=30)) -> SearchResponse:
    ensure_index()
    pages = sorted(_cache["index"], key=lambda p: p.get("updated_at") or "", reverse=True)[:limit]
    return SearchResponse(results=[SearchResult(
        id=p.get("id"), slug=p.get("slug"), title=page_title(p), url=p.get("wiki_page_url"), type=p.get("type"),
        tags=p.get("tags") or [], updated_at=p.get("updated_at"), score=100.0,
    ) for p in pages])


@app.get("/diff/repo-vs-portal", dependencies=[Depends(require_auth)])
def diff_repo_vs_portal(path: str = Query(..., description="Markdown path in repo, e.g. lore/wiki/wiki/blackspire.md")) -> dict[str, Any]:
    file = gh_get_file(path)
    if not file:
        raise HTTPException(status_code=404, detail="Repo file not found")
    fm, body, gm_info = parse_markdown(file.content)
    page_id = fm.get("op_id")
    if not page_id:
        raise HTTPException(status_code=400, detail="Repo file has no op_id; it would create a new page")
    portal = fetch_page(page_id, force=True)
    portal_content, _ = page_to_markdown(portal)
    return {"path": path, "op_id": page_id, "diff": unified_diff(portal_content, file.content, "portal", "repo")}
