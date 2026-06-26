# Git-backed Obsidian Portal sync

This is a small FastAPI bridge for using an Obsidian Portal campaign wiki with GitHub as the version-controlled lore repository.

The intended workflow is **pull-through sync**:

```text
Obsidian Portal UI may drift ahead quietly.
Before repo work matters, the bridge pulls the latest wiki into GitHub.
Merged GitHub main changes can then be published back to Obsidian Portal.
Working on the lore can therefore be done in a local IDE with all of the advantages and protections of git.
```

## What it does

### Read / lore assistant endpoints

- `GET /search_lore?q=...`
- `GET /get_page?id_or_slug=...`
- `GET /recent_changes`

### Sync endpoints

- `POST /sync/from-portal`
  - Lists Obsidian Portal wiki pages.
  - Fetches changed pages.
  - Writes markdown files into GitHub.
  - Commits changes.
  - Updates `metadata/sync-state.json`.

- `POST /sync/publish-main`
  - First runs `/sync/from-portal`.
  - Reads markdown files from GitHub `main`.
  - Detects repo-side changes.
  - Updates or creates Obsidian Portal wiki pages.
  - Refuses to publish pages with detected conflicts.

- `POST /github/webhook`
  - Optional GitHub webhook endpoint for push-to-main publishing.
  - Ignores bridge-authored commits to avoid webhook loops.

## Repository layout created by the bridge

By default the bridge writes pages like this:

```text
lore/wiki/wiki/<page-slug>.md
lore/wiki/adventure-log/<post-slug>.md
metadata/sync-state.json
```

Each markdown page has YAML frontmatter:

```yaml
---
op_id: "stable-obsidian-portal-page-id"
op_slug: "blackspire"
op_type: "WikiPage"
name: "Blackspire"
op_updated_at: "2026-06-26T18:45:00Z"
op_gm_only: false
tags:
  - city
---
```

If a page has GM-only info, it is placed at the bottom of the markdown file:

```markdown
<!-- GM_INFO_START -->
Secret GM notes here.
<!-- GM_INFO_END -->
```

If you put this repo in front of players, remember that GM info may be in Git history.

## Setup

### 1. Register an Obsidian Portal API application

While logged in to Obsidian Portal, go to:

```text
https://www.obsidianportal.com/oauth/clients/new
```

For homepage URL, use your deployed bridge URL once you have one, for example:

```text
https://sindrel-lore-bridge.onrender.com
```

### 2. Generate Obsidian Portal OAuth tokens

Copy `.env.example` to `.env`, fill in `OP_CONSUMER_KEY` and `OP_CONSUMER_SECRET`, then run:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/get_obsidian_tokens.py
```

Paste the resulting `OP_ACCESS_TOKEN` and `OP_ACCESS_TOKEN_SECRET` into your environment variables.

### 3. Create the GitHub lore repo

Create a new GitHub repo, for example:

```text
sindrel-lore
```

This is the repo that stores your markdown lore mirror. It can be private.

Create a GitHub token with contents read/write access to that repo and set:

```text
GITHUB_TOKEN=...
GITHUB_OWNER=your-user-or-org
GITHUB_REPO=sindrel-lore
GITHUB_BRANCH=main
```

### 4. Configure the bridge environment

Set these in Render/Railway/etc.:

```text
LORE_BRIDGE_API_KEY=long-random-secret
OP_CONSUMER_KEY=...
OP_CONSUMER_SECRET=...
OP_ACCESS_TOKEN=...
OP_ACCESS_TOKEN_SECRET=...
OP_CAMPAIGN_ID=...
GITHUB_TOKEN=...
GITHUB_OWNER=...
GITHUB_REPO=sindrel-lore
GITHUB_BRANCH=main
GITHUB_AUTHOR_NAME=Sindrel Lore Bridge
GITHUB_AUTHOR_EMAIL=lore-bridge@example.com
ALLOW_CREATE_FROM_GIT=true
ALLOW_DELETE_FROM_GIT=false
```

Use a unique `GITHUB_AUTHOR_EMAIL`; the webhook uses it to ignore bridge-authored commits and avoid loops.

### 5. Deploy

For Render:

```text
Build command: pip install -r requirements.txt
Start command: uvicorn app:app --host 0.0.0.0 --port $PORT
```

Test:

```bash
curl -H "Authorization: Bearer $LORE_BRIDGE_API_KEY" \
  https://YOUR-BRIDGE.onrender.com/health
```

### 6. First sync

Trigger the first pull from Obsidian Portal into GitHub:

```bash
curl -X POST \
  -H "Authorization: Bearer $LORE_BRIDGE_API_KEY" \
  https://YOUR-BRIDGE.onrender.com/sync/from-portal
```

You should see markdown files appear in the GitHub lore repo.

## GitHub Actions option

This starter includes two workflow files you can copy into the **lore repo**:

```text
.github/workflows/sync-from-portal.yml
.github/workflows/publish-main.yml
```

Add these repo secrets in GitHub:

```text
LORE_BRIDGE_URL=https://YOUR-BRIDGE.onrender.com
LORE_BRIDGE_API_KEY=the-same-bridge-api-key
```

Then you can manually run:

- **Sync from Obsidian Portal**
- **Publish main to Obsidian Portal**

## GitHub webhook option

Instead of manually running the publish action, you can add a GitHub webhook in the lore repo:

```text
Payload URL: https://YOUR-BRIDGE.onrender.com/github/webhook
Content type: application/json
Secret: same value as GITHUB_WEBHOOK_SECRET
Events: Just the push event
```

Then set `GITHUB_WEBHOOK_SECRET` in the bridge environment.

When `main` receives a push, the bridge will:

```text
1. Pull Obsidian Portal into GitHub first.
2. Check changed markdown pages.
3. Publish safe changes back to Obsidian Portal.
4. Skip conflicted pages and report conflicts.
```

## Local pull helper

Instead of running `git pull` directly in your local clone, you can run:

```bash
export LORE_BRIDGE_URL=https://YOUR-BRIDGE.onrender.com
export LORE_BRIDGE_API_KEY=...
./scripts/lore_pull.sh
```

That script does:

```text
POST /sync/from-portal
git pull --ff-only
```

## Suggested AI-agent rule

Use this as a standing rule for coding/lore agents:

```text
Before reading or editing campaign lore, call the bridge's sync_from_portal operation or run the Sync from Obsidian Portal GitHub Action. Work from the GitHub lore repo. Make changes in a branch and open a pull request. Do not push directly to main. The bridge publishes merged main changes back to Obsidian Portal only after it has pulled the latest portal state first.
```

## Safety defaults

- Create-from-Git is enabled by default.
- Delete-from-Git is disabled by default.
- Publish pulls Obsidian Portal first.
- Pages with conflicts are not published.
- Bridge-authored GitHub webhook commits are ignored to avoid publish loops.

## Known limitations

- Obsidian Portal UI changes are not instant in Git unless you trigger `/sync/from-portal`, run the GitHub Action, run the local helper, or use a scheduled job.
- The bridge stores GM-only info in the repo. Use a private repo if you sync GM-only pages.
- GitHub Contents API writes one file per commit. This is simple and reliable for small campaign wikis, but a later version could use the Git Trees API to create one multi-file commit per sync.
