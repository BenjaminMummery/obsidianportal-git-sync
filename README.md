# Git-backed Obsidian Portal sync

This is a small FastAPI bridge for using an Obsidian Portal campaign wiki with GitHub as the version-controlled lore repository.

The intended workflow is **pull-through sync**:

```text
Obsidian Portal UI may drift ahead quietly.
Before repo work matters, the bridge pulls the latest wiki into GitHub.
Merged GitHub main changes can then be published back to Obsidian Portal.
Working on the lore can therefore be done in a local IDE with all of the advantages and protections of git.
```

## Two repositories

| Repository | Purpose |
|------------|---------|
| **This repo** (`obsidianportal-git-sync`) | The bridge app (FastAPI service deployed to Render, etc.) |
| **Your lore repo** (e.g. `dnd-lore-lords-of-sindrel`) | The Textile mirror the bridge reads and writes |

If you watch the bridge repo after a sync, it will look like nothing happened. Check the **lore repo** for `lore/wiki/`, `lore/characters/`, and `metadata/sync-state.json`.

## What it does

### Read / lore assistant endpoints

- `GET /search_lore?q=...` — wiki pages only (characters not included yet)
- `GET /get_page?id_or_slug=...` — single wiki page
- `GET /recent_changes` — recently updated wiki pages
- `GET /diff/repo-vs-portal?path=...` — unified diff for one lore-repo file vs portal

All of the above require `Authorization: Bearer <LORE_BRIDGE_API_KEY>`.

### Sync endpoints

- `POST /sync/from-portal`
  - Lists Obsidian Portal wiki pages and characters.
  - Fetches changed records.
  - Writes Textile files (YAML frontmatter + Textile body) into GitHub.
  - Commits all changes in a single Git commit (via the Git Trees API).
  - Updates `metadata/sync-state.json`.
  - Logs progress to stdout; optional `?async=true` returns a job id to poll.

- `POST /sync/publish-main`
  - First runs `/sync/from-portal`.
  - Reads synced files from GitHub `main`.
  - Detects repo-side changes.
  - Updates or creates Obsidian Portal wiki pages and characters.
  - Refuses to publish records with detected conflicts.
  - Optional `?async=true` for progress polling.

- `GET /sync/jobs/{job_id}` — poll async sync progress and final result.
- `GET /sync/jobs/current` — currently running job, if any.

- `POST /github/webhook`
  - Optional GitHub webhook endpoint for push-to-main publishing.
  - Ignores bridge-authored commits to avoid webhook loops.

## Repository layout created by the bridge

By default the bridge writes pages like this:

```text
lore/wiki/wiki/<page-slug>.textile
lore/wiki/adventure-log/<post-slug>.textile
lore/characters/<character-slug>.textile
metadata/sync-state.json
```

Each synced file uses YAML frontmatter plus a **Textile** body (Obsidian Portal’s native markup — **not Markdown**):

```yaml
---
op_id: "stable-obsidian-portal-page-id"
op_slug: "blackspire"
op_kind: Wiki
op_type: "WikiPage"
name: "Blackspire"
op_updated_at: "2026-06-26T18:45:00Z"
op_gm_only: false
tags:
  - city
---
```

Character files use `op_kind: Character` and separate Textile sections:

```yaml
---
op_id: "stable-obsidian-portal-character-id"
op_slug: "gillette-quill"
op_kind: Character
op_type: Character
name: "Gillette Quill"
is_player_character: true
op_updated_at: "2026-06-26T18:45:00Z"
op_gm_only: false
tags:
  - pc
dynamic_sheet:
  race: Human
  class: Wizard
---
```

```text
<!-- OP_DESCRIPTION -->
Short description in Textile.

<!-- OP_BIO -->
Longer bio in Textile.

<!-- GM_INFO_START -->
Secret GM notes here.
<!-- GM_INFO_END -->
```

Wiki pages with GM-only info use `<!-- GM_INFO_START -->` / `<!-- GM_INFO_END -->` at the bottom of the file.

**Important:** IDE Markdown preview will not match what Obsidian Portal renders. Do not convert Textile to Markdown before publishing.

If you put this repo in front of players, remember that GM info may remain in Git history even after deletion.

---

## Full setup guide

### Prerequisites

- An [Obsidian Portal](https://www.obsidianportal.com/) campaign with GM (or co-GM) API access
- A GitHub account
- A host for the bridge (e.g. [Render](https://render.com/)) — free tier works but cold-starts are slow
- Python 3.11+ locally (for OAuth setup scripts only)

### Step 1 — Register an Obsidian Portal API application

While logged in to Obsidian Portal, go to:

```text
https://www.obsidianportal.com/oauth/clients/new
```

Fill in:

| Field | Value |
|-------|--------|
| Name | Something like `Sindrel Lore Bridge` |
| Homepage URL | Your deployed bridge URL once you have one (can update later), e.g. `https://obsidianportal-git-sync.onrender.com` |
| Callback URL | Out-of-band / OOB is fine for the token script |

Save the **Consumer Key** and **Consumer Secret**.

Docs: [Obsidian Portal OAuth](https://help.obsidianportal.com/article/105-api-authentication-oauth)

### Step 2 — Local OAuth token setup

In **this repo** (the bridge):

```bash
cp .env.example .env
```

Edit `.env` and set at minimum:

```text
OP_CONSUMER_KEY=...
OP_CONSUMER_SECRET=...
```

Then:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/get_obsidian_tokens.py
```

Open the URL printed in the terminal, authorize the app, paste the verifier/PIN when prompted.

Add the printed values to `.env`:

```text
OP_ACCESS_TOKEN=...
OP_ACCESS_TOKEN_SECRET=...
```

### Step 3 — Find your campaign ID

Still in `.env` with tokens set:

```bash
source .venv/bin/activate
python scripts/list_obsidian_campaigns.py
```

Copy the `id` for your campaign into `.env`:

```text
OP_CAMPAIGN_ID=...
```

### Step 4 — Create the GitHub lore repo

Create a **new** GitHub repository for lore only, for example:

```text
dnd-lore-lords-of-sindrel
```

This repo can be **private** (recommended if you sync GM-only content).

Create a GitHub personal access token (classic or fine-grained) with **Contents: Read and write** on that repo.

Add to `.env`:

```text
GITHUB_TOKEN=ghp_... or github_pat_...
GITHUB_OWNER=your-github-username-or-org
GITHUB_REPO=dnd-lore-lords-of-sindrel
GITHUB_BRANCH=main
```

### Step 5 — Configure bridge identity for Git commits

Every commit the bridge makes to the lore repo uses these values:

```text
GITHUB_AUTHOR_NAME=Obsidianportal Git Sync
GITHUB_AUTHOR_EMAIL=lore-bridge-sindrel@example.com
```

**Do not use your personal GitHub email here.** See [Troubleshooting: webhook never publishes](#webhook-never-publishes-after-i-merge-to-main).

The email does not need to be a real mailbox. It must be:

- Unique to this bridge
- Different from your local `git config user.email` when you edit the lore repo

### Step 6 — Generate a bridge API key

Create a long random secret:

```text
LORE_BRIDGE_API_KEY=...
```

This protects all bridge endpoints except `/github/webhook` (which uses the GitHub webhook secret instead).

Add to `.env` for local scripts:

```text
LORE_BRIDGE_URL=https://your-bridge.onrender.com
```

### Step 7 — Deploy the bridge

Deploy **this repo** to Render (or similar).

| Setting | Value |
|---------|--------|
| Build command | `pip install .` (or `pip install -r requirements.txt` for a flat install without the CLI) |
| Start command | `uvicorn app:app --host 0.0.0.0 --port $PORT` |

Copy **all** relevant variables from `.env` into the host’s environment settings. At minimum:

```text
LORE_BRIDGE_API_KEY
OP_CONSUMER_KEY
OP_CONSUMER_SECRET
OP_ACCESS_TOKEN
OP_ACCESS_TOKEN_SECRET
OP_CAMPAIGN_ID
GITHUB_TOKEN
GITHUB_OWNER
GITHUB_REPO
GITHUB_BRANCH
GITHUB_AUTHOR_NAME
GITHUB_AUTHOR_EMAIL
ALLOW_CREATE_FROM_GIT=true
ALLOW_DELETE_FROM_GIT=false
```

Optional:

```text
OP_AUTHOR_ID=...                  # only if character create-from-Git fails
GITHUB_WEBHOOK_SECRET=...         # required for webhook auto-publish
LORE_WIKI_DIR=lore/wiki
LORE_CHARACTERS_DIR=lore/characters
LORE_FILE_EXT=.textile
LORE_STATE_PATH=metadata/sync-state.json
CACHE_TTL_SECONDS=900
```

**Never commit `.env` to git.**

Verify deployment (open in a browser, or use curl):

```bash
# Browser-friendly status page
open "${LORE_BRIDGE_URL}/"

# JSON status (public — no token required)
curl -sS "${LORE_BRIDGE_URL}/health"

# With token — includes in-memory cache timestamps
curl -sS -H "Authorization: Bearer ${LORE_BRIDGE_API_KEY}" \
  "${LORE_BRIDGE_URL}/health"
```

Expected (public JSON):

```json
{"ok":true,"service":"Sindrel Lore Bridge","version":"0.4.1","campaign_id_configured":true,"github_configured":true,...}
```

### Step 8 — First sync (portal → GitHub)

**Recommended (async with progress):**

```bash
set -a && source .env && set +a

# Start job
curl -sS -X POST \
  -H "Authorization: Bearer ${LORE_BRIDGE_API_KEY}" \
  "${LORE_BRIDGE_URL}/sync/from-portal?async=true"

# Poll (replace JOB_ID from response)
curl -sS -H "Authorization: Bearer ${LORE_BRIDGE_API_KEY}" \
  "${LORE_BRIDGE_URL}/sync/jobs/JOB_ID"
```

Or use the helper script (async + poll + git pull):

```bash
./scripts/lore_pull.sh
```

**Blocking (waits until finished, no live progress in terminal):**

```bash
curl -X POST \
  -H "Authorization: Bearer ${LORE_BRIDGE_API_KEY}" \
  "${LORE_BRIDGE_URL}/sync/from-portal"
```

Progress is always written to Render logs, e.g. `sync fetching_wiki | 12/82 | Osteomantic Archives`.

This can take **several minutes** on a first run while pages are fetched from Obsidian Portal. The lore repo should receive **one commit** containing all changed files plus `metadata/sync-state.json`.

Watch progress in the **lore repo** commits page:

```text
https://github.com/YOUR_OWNER/YOUR_LORE_REPO/commits/main
```

You should see:

- `lore/wiki/wiki/*.textile`
- `lore/wiki/adventure-log/*.textile`
- `lore/characters/*.textile`
- `metadata/sync-state.json`

If you previously synced `.md` files, the next pull migrates them to `.textile` and removes the old `.md` copies.

### Step 9 — Enable auto-publish (recommended)

Merging to `main` does **not** update Obsidian Portal until you configure one of these:

#### Option A — GitHub webhook (automatic on push to main)

In the **lore repo** → Settings → Webhooks → Add webhook:

| Field | Value |
|-------|--------|
| Payload URL | `https://YOUR-BRIDGE.onrender.com/github/webhook` |
| Content type | `application/json` |
| Secret | Same value as `GITHUB_WEBHOOK_SECRET` on Render |
| Events | Just the **push** event |

Set `GITHUB_WEBHOOK_SECRET` on Render and redeploy if needed.

When someone pushes to `main` (and not all commits are bridge-authored), the bridge will:

```text
1. Pull Obsidian Portal into GitHub first.
2. Check changed synced files.
3. Publish safe changes back to Obsidian Portal.
4. Skip conflicted files and report conflicts.
```

#### Option B — GitHub Actions (manual publish)

Copy these workflow files from **this repo** into the **lore repo**:

```text
.github/workflows/sync-from-portal.yml
.github/workflows/publish-main.yml
```

Add lore repo secrets:

```text
LORE_BRIDGE_URL=https://YOUR-BRIDGE.onrender.com
LORE_BRIDGE_API_KEY=the-same-bridge-api-key
```

Run manually from the Actions tab:

- **Sync from Obsidian Portal**
- **Publish main to Obsidian Portal**

### Step 10 — Clone the lore repo locally

```bash
git clone git@github.com:YOUR_OWNER/YOUR_LORE_REPO.git
cd YOUR_LORE_REPO
```

Add bridge settings to your shell or a local `.env` in the lore repo (do not commit):

```text
LORE_BRIDGE_URL=https://YOUR-BRIDGE.onrender.com
LORE_BRIDGE_API_KEY=...
```

---

## Daily workflow

```text
1. Sync portal → GitHub before editing (curl, Action, or lore_pull.sh).
2. git pull in your lore repo clone.
3. Create a branch, edit .textile files (preserve Textile syntax).
4. Open a PR, review, merge to main.
5. Webhook (or manual publish Action) pushes merged changes to Obsidian Portal.
```

Local pull helper (run from your **lore repo** clone):

```bash
set -a && source .env && set +a
/path/to/obsidianportal-git-sync/scripts/lore_pull.sh
```

Or install the bridge as a CLI dependency with [uv](https://docs.astral.sh/uv/):

```toml
# pyproject.toml in your lore repo
[project]
dependencies = [
  "lore-bridge @ git+https://github.com/YOUR_OWNER/obsidianportal-git-sync.git@feat/cli-package",
]
```

```bash
set -a && source .env && set +a
uv run lore-bridge pull      # portal → GitHub, then git pull --ff-only
uv run lore-bridge publish   # pull + publish safe changes to portal
uv run lore-bridge status    # health + last sync timestamps
```

From a bridge repo checkout you can also run `uv run lore-bridge serve` for local API development.

That starts an async sync, prints progress every 2 seconds, then runs `git pull --ff-only` when complete.

---

## Environment variable reference

| Variable | Required | Description |
|----------|----------|-------------|
| `LORE_BRIDGE_API_KEY` | Yes | Bearer token for calling the bridge API |
| `LORE_BRIDGE_URL` | Local/scripts | Deployed bridge base URL (not needed on Render itself) |
| `OP_CONSUMER_KEY` | Yes | Obsidian Portal OAuth app key |
| `OP_CONSUMER_SECRET` | Yes | Obsidian Portal OAuth app secret |
| `OP_ACCESS_TOKEN` | Yes | OAuth access token |
| `OP_ACCESS_TOKEN_SECRET` | Yes | OAuth access token secret |
| `OP_CAMPAIGN_ID` | Yes | Campaign UUID |
| `OP_AUTHOR_ID` | No | Your OP user UUID; fallback for character create-from-Git |
| `GITHUB_TOKEN` | Yes | PAT with contents write on lore repo |
| `GITHUB_OWNER` | Yes | GitHub user or org |
| `GITHUB_REPO` | Yes | Lore repo name |
| `GITHUB_BRANCH` | No | Default `main` |
| `GITHUB_AUTHOR_NAME` | No | Label on bridge commits |
| `GITHUB_AUTHOR_EMAIL` | No | Must be bridge-only; used for webhook loop prevention |
| `GITHUB_WEBHOOK_SECRET` | For webhook | Must match lore repo webhook secret |
| `LORE_WIKI_DIR` | No | Default `lore/wiki` |
| `LORE_CHARACTERS_DIR` | No | Default `lore/characters` |
| `LORE_FILE_EXT` | No | Default `.textile` |
| `LORE_STATE_PATH` | No | Default `metadata/sync-state.json` |
| `ALLOW_CREATE_FROM_GIT` | No | Default `true` — new files without `op_id` create portal records |
| `ALLOW_DELETE_FROM_GIT` | No | Default `false` — deleting a file deletes the portal record |
| `CACHE_TTL_SECONDS` | No | In-memory OP index cache TTL (default 900) |

---

## Troubleshooting

### `/health` returns errors or looks wrong

**Public access:** `/` and `/health` work in a browser without a token and show a status page (HTML) or JSON with `ok`, version, and configuration flags.

**With token:** pass `Authorization: Bearer ${LORE_BRIDGE_API_KEY}` to `/health` for extra fields like `last_sync`.

```bash
curl -sS "${LORE_BRIDGE_URL}/health"
curl -H "Authorization: Bearer ${LORE_BRIDGE_API_KEY}" "${LORE_BRIDGE_URL}/health"
```

If `campaign_id_configured` or `github_configured` is `false`, check Render env vars. Common misses: `OP_CAMPAIGN_ID`, `GITHUB_TOKEN`, `GITHUB_OWNER`, or `GITHUB_REPO`.

### Sync appears to do nothing

- Confirm you are watching the **lore repo**, not the bridge repo.
- First sync can take many minutes with no curl output — watch for **one new commit** on the lore repo (not dozens).
- Use `curl -v --max-time 600` so the client does not give up early.
- Render free tier may cold-start; the first request after idle is slow.

### Obsidian Portal API / OAuth errors

| Symptom | Fix |
|---------|-----|
| 401 from OP API | Re-run `scripts/get_obsidian_tokens.py` and update tokens on Render |
| 403 from OP API | OAuth user lacks GM access to a private campaign |
| 500 on sync | Check Render logs for the specific page/character that failed |

Tokens do not auto-refresh; if sync suddenly fails after months, regenerate tokens.

### Webhook never publishes after I merge to main

**Cause:** `GITHUB_AUTHOR_EMAIL` is set to your personal GitHub/git email.

The webhook ignores pushes where **every** commit author email equals `GITHUB_AUTHOR_EMAIL` (loop prevention). If that matches your own commits, your merges are ignored too.

**Fix:** Use a dedicated bridge-only email, e.g. `lore-bridge-sindrel@example.com`, and keep your personal email for your own git commits only.

**Also check:**

- Webhook is on the **lore repo**, not the bridge repo
- Payload URL is correct
- `GITHUB_WEBHOOK_SECRET` matches on Render and in the webhook settings
- Push was to `main` (or whatever `GITHUB_BRANCH` is)

### Webhook loops or duplicate syncs

**Cause:** `GITHUB_AUTHOR_EMAIL` does not match the email on bridge commits, so the webhook treats bridge commits as human pushes.

**Fix:** Ensure Render’s `GITHUB_AUTHOR_EMAIL` exactly matches the author email on bridge commits in the lore repo commit history.

Large syncs may also cause GitHub to **retry** the webhook on timeout. Check Render logs for overlapping runs.

### Character create-from-Git fails (author errors)

Creating a **new** character from a lore-repo file without `op_id` requires an Obsidian Portal author.

The bridge tries `GET /users/me` using your OAuth token. If that fails, set on Render:

```text
OP_AUTHOR_ID=your-obsidian-portal-user-uuid
```

Find your user id from the OAuth app owner account or OP profile/API docs.

Wiki page create-from-Git does not need `OP_AUTHOR_ID`.

### Accidental pages or characters created on the portal

`ALLOW_CREATE_FROM_GIT=true` (default) means any new `.textile` file **without** `op_id` in frontmatter becomes a new portal record on publish.

**Prevention:**

- Always branch/PR; review new files carefully
- Set `draft: true` in frontmatter to skip publish (bridge skips files with `draft: true`)
- Set `ALLOW_CREATE_FROM_GIT=false` if you only ever want updates, never creates

### Publish skipped some files / `conflicts` in response

The portal changed a record **after** the last sync base while Git also changed it. Those files are not overwritten on publish.

**Fix:**

1. Run sync from portal to see current portal state in Git.
2. Manually reconcile the file in Git.
3. Merge and publish again.

**Note:** On publish, the bridge pulls portal changes **before** publishing. If the same page was edited in both places, portal content can overwrite Git during that pull. Prefer editing one side at a time per page until three-way merge support exists.

### Dynamic sheet data wiped on a character

Obsidian Portal replaces the **entire** `dynamic_sheet` JSON on update.

**Prevention:**

- Do not remove or empty `dynamic_sheet:` in frontmatter unless you intend to clear the sheet
- Do not publish character edits with a partial `dynamic_sheet` unless you mean to replace the whole object

Docs: [API: Characters — Dynamic Sheets](https://help.obsidianportal.com/article/99-api-characters)

### Textile looks wrong after editing in VS Code / Cursor

The files are **Textile**, not Markdown. `# Heading`, `**bold**`, etc. will not render correctly on Obsidian Portal.

Use OP’s wiki link syntax, e.g. `[[Page Name | label]]` and `[[Character | label]]`. Item links `[[ :item-slug | name ]]` refer to objects that are **not synced** (no public items API).

### GM secrets exposed

GM-only sections sync into the lore repo and remain in Git history. Use a **private** lore repo if players might access it.

### Items missing from the repo

Campaign **items** (inventory objects) have no public Obsidian Portal API. They cannot be synced. Links to items in Textile bodies will still point at portal-only objects.

### `.md` and `.textile` files both present

During migration, publish reads both extensions. After a full portal pull, bridge writes only `.textile` and deletes legacy `.md` copies for tracked records.

### GitHub API rate limits or very slow sync

Large first syncs still require many Obsidian Portal and GitHub blob API calls, but the lore repo receives **one commit per sync operation** instead of one commit per file.

### Render deploy/build failures

| Check | Expected |
|-------|----------|
| Build command | `pip install .` (or `pip install -r requirements.txt` for a flat install without the CLI) |
| Start command | `uvicorn app:app --host 0.0.0.0 --port $PORT` |
| Python version | 3.11+ |

---

## Suggested AI-agent rule

```text
Before reading or editing campaign lore, call the bridge's sync_from_portal operation or run the Sync from Obsidian Portal GitHub Action. Work from the GitHub lore repo. Files are Obsidian Portal Textile (.textile), not Markdown — do not convert syntax. Make changes in a branch and open a pull request. Do not push directly to main. Do not create new .textile files without op_id unless intentionally creating a new portal page or character. The bridge publishes merged main changes back to Obsidian Portal only after it has pulled the latest portal state first.
```

## Safety defaults

- Create-from-Git is enabled by default.
- Delete-from-Git is disabled by default.
- Publish pulls Obsidian Portal first.
- Records with timestamp conflicts are not published.
- Bridge-authored GitHub webhook commits are ignored to avoid publish loops.

## Known limitations

- Obsidian Portal UI changes are not instant in Git unless you trigger `/sync/from-portal`, run the GitHub Action, run the local helper, or use a scheduled job.
- Publish pulls portal state before pushing Git changes; concurrent edits on the same page in both places need manual care.
- The bridge stores GM-only info in the repo. Use a private repo if you sync GM-only pages or characters.
- Character avatars are not synced; only text fields and dynamic sheet JSON are mirrored.
- Obsidian Portal **items** do not have a public API endpoint and cannot be synced.
- Read/search API endpoints cover wiki pages only, not characters.
- Async job status is in-memory only; redeploy/restart clears job history.
