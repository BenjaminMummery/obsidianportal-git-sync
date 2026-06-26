import os
from dotenv import load_dotenv
from requests_oauthlib import OAuth1Session

load_dotenv()

REQUEST_TOKEN_URL = "https://www.obsidianportal.com/oauth/request_token"
AUTHORIZE_URL = "https://www.obsidianportal.com/oauth/authorize"
ACCESS_TOKEN_URL = "https://www.obsidianportal.com/oauth/access_token"

consumer_key = os.environ.get("OP_CONSUMER_KEY")
consumer_secret = os.environ.get("OP_CONSUMER_SECRET")

if not consumer_key or not consumer_secret:
    raise SystemExit("Set OP_CONSUMER_KEY and OP_CONSUMER_SECRET in .env first.")

oauth = OAuth1Session(consumer_key, client_secret=consumer_secret, callback_uri="oob")
request_token = oauth.fetch_request_token(REQUEST_TOKEN_URL)
resource_owner_key = request_token.get("oauth_token")
resource_owner_secret = request_token.get("oauth_token_secret")

print("Open this URL in your browser and authorize the app:")
print(oauth.authorization_url(AUTHORIZE_URL))
verifier = input("Paste the verifier/PIN here: ").strip()

oauth = OAuth1Session(
    consumer_key,
    client_secret=consumer_secret,
    resource_owner_key=resource_owner_key,
    resource_owner_secret=resource_owner_secret,
    verifier=verifier,
)
access_token = oauth.fetch_access_token(ACCESS_TOKEN_URL)
print("\nAdd these to your .env:\n")
print(f"OP_ACCESS_TOKEN={access_token.get('oauth_token')}")
print(f"OP_ACCESS_TOKEN_SECRET={access_token.get('oauth_token_secret')}")
