#!/usr/bin/env bash
# Serve the Trust Desk locally against Lakebase (uses trustdesk/.env: LAKEBASE_URL).
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] && { set -a; source .env; set +a; }
# Robust local auth for the serving endpoint: mint a fresh static token so the
# SDK doesn't attempt an OAuth refresh (which the older CLI can't do).
export DATABRICKS_HOST="${DATABRICKS_HOST:-https://dbc-b21456ca-95e3.cloud.databricks.com}"
export DATABRICKS_TOKEN="$(databricks auth token -p "${DBX_PROFILE:-lakecode}" 2>/dev/null | python3 -c 'import sys,json;print(json.load(sys.stdin).get("access_token",""))')"
PY=/Users/sachin/Developer/dais2026/hackathon/commons/.venv/bin/python
exec "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port "${PORT:-8099}"
