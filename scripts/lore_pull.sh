#!/usr/bin/env bash
set -euo pipefail

: "${LORE_BRIDGE_URL:?Set LORE_BRIDGE_URL, e.g. https://sindrel-lore-bridge.onrender.com}"
: "${LORE_BRIDGE_API_KEY:?Set LORE_BRIDGE_API_KEY}"

BASE="${LORE_BRIDGE_URL%/}"
AUTH=(-H "Authorization: Bearer ${LORE_BRIDGE_API_KEY}")

poll_job() {
  local job_id="$1"
  while true; do
    status_json="$(curl -fsS "${AUTH[@]}" "${BASE}/sync/jobs/${job_id}")"
    set +e
    python3 - <<'PY' "$status_json"
import json, sys
job = json.loads(sys.argv[1])
print(
    f"[{job['status']}] {job['phase']} "
    f"{job.get('current', 0)}/{job.get('total', 0)} "
    f"{job.get('current_title') or job.get('current_path') or ''}".rstrip()
)
if job.get("message"):
    print(f"  {job['message']}")
for err in job.get("errors") or []:
    print(f"  error: {err.get('path') or err.get('op_id')}: {err.get('detail')}")
if job["status"] == "completed":
    sys.exit(0)
if job["status"] == "failed":
    sys.exit(1)
sys.exit(2)
PY
    code=$?
    set -e
    if [ "$code" -eq 0 ]; then
      return 0
    fi
    if [ "$code" -eq 1 ]; then
      return 1
    fi
    sleep 2
  done
}

echo "Starting async sync at ${BASE}/sync/from-portal ..."

start_json="$(curl -fsS -X POST "${AUTH[@]}" "${BASE}/sync/from-portal?async=true")"
job_id="$(python3 - <<'PY' "$start_json"
import json, sys
print(json.loads(sys.argv[1])["job_id"])
PY
)"

echo "Started sync job ${job_id}"
poll_job "$job_id"
echo
git pull --ff-only
