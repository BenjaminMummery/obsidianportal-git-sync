import os
import sys
import json
from dotenv import load_dotenv
from requests_oauthlib import OAuth1Session

load_dotenv()

API_BASE = "https://api.obsidianportal.com/v1"

required = [
    "OP_CONSUMER_KEY",
    "OP_CONSUMER_SECRET",
    "OP_ACCESS_TOKEN",
    "OP_ACCESS_TOKEN_SECRET",
]
missing = [name for name in required if not os.environ.get(name)]
if missing:
    raise SystemExit(
        "Missing required environment variables: "
        + ", ".join(missing)
        + "\nRun scripts/get_obsidian_tokens.py first, then add the printed tokens to your .env."
    )

oauth = OAuth1Session(
    os.environ["OP_CONSUMER_KEY"],
    client_secret=os.environ["OP_CONSUMER_SECRET"],
    resource_owner_key=os.environ["OP_ACCESS_TOKEN"],
    resource_owner_secret=os.environ["OP_ACCESS_TOKEN_SECRET"],
)

response = oauth.get(f"{API_BASE}/users/me")
if response.status_code >= 400:
    print(f"Request failed: HTTP {response.status_code}", file=sys.stderr)
    print(response.text, file=sys.stderr)
    sys.exit(1)

try:
    data = response.json()
except json.JSONDecodeError:
    print("Response was not JSON:", file=sys.stderr)
    print(response.text, file=sys.stderr)
    sys.exit(1)

campaigns = data.get("campaigns") or []
if not campaigns:
    print("No campaigns found for this authenticated user.")
    sys.exit(0)

print("Campaigns visible to this OAuth user:\n")
for campaign in campaigns:
    name = campaign.get("name") or "(unnamed)"
    campaign_id = campaign.get("id") or "(no id returned)"
    slug = campaign.get("slug") or "(no slug returned)"
    url = campaign.get("campaign_url") or campaign.get("url") or ""
    print(name)
    print(f"  id:   {campaign_id}")
    print(f"  slug: {slug}")
    if url:
        print(f"  url:  {url}")
    print()

print("Copy the id for The Lords of Sindrel into Render as OP_CAMPAIGN_ID.")
