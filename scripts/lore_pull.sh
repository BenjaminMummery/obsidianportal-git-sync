#!/usr/bin/env bash
set -euo pipefail

: "${LORE_BRIDGE_URL:?Set LORE_BRIDGE_URL, e.g. https://sindrel-lore-bridge.onrender.com}"
: "${LORE_BRIDGE_API_KEY:?Set LORE_BRIDGE_API_KEY}"

curl -fsS -X POST \
  -H "Authorization: Bearer ${LORE_BRIDGE_API_KEY}" \
  "${LORE_BRIDGE_URL%/}/sync/from-portal"

echo
git pull --ff-only
