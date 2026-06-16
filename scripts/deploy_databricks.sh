#!/usr/bin/env bash
# Deploy the Facility Trust Desk as a Databricks App (reads the commons Lakebase).
# Stages a clean copy with a deploy app.yaml (carrying LAKEBASE_URL), syncs, deploys.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] && { set -a; source .env; set +a; }
: "${LAKEBASE_URL:?set LAKEBASE_URL in trustdesk/.env}"
P="${DBX_PROFILE:-lakecode}"
APP=facility-trust-desk
WS_USER="$(databricks current-user me -p "$P" -o json | python3 -c 'import sys,json;print(json.load(sys.stdin)["userName"])')"
WS="/Users/$WS_USER/$APP"

echo "▶ staging…"
STAGE=/tmp/trustdesk-deploy; rm -rf "$STAGE"; mkdir -p "$STAGE/app"
cp -r app/main.py app/db.py app/static "$STAGE/app/"
printf 'fastapi>=0.115\nuvicorn[standard]>=0.30\npsycopg[binary]>=3.2\ndatabricks-sdk>=0.30\n' > "$STAGE/requirements.txt"
cp -r app/llm.py app/copilot.py app/agent_tools.py app/policy.py app/publichealth.py app/network.py "$STAGE/app/"
python3 - "$LAKEBASE_URL" > "$STAGE/app.yaml" <<'PY'
import sys
print('command:')
print('  - sh')
print('  - "-c"')
print('  - "uvicorn app.main:app --host 0.0.0.0 --port ${DATABRICKS_APP_PORT:-8000}"')
print('env:')
print('  - name: LAKEBASE_URL')
print(f'    value: "{sys.argv[1]}"')
PY

echo "▶ create app (if needed)…"
databricks apps create "$APP" -p "$P" --no-wait 2>/dev/null || echo "  (exists)"
echo "▶ start app + wait for RUNNING…"
databricks apps start "$APP" -p "$P" --no-wait >/dev/null 2>&1 || true
for _ in $(seq 1 60); do
  cs=$(databricks apps get "$APP" -p "$P" -o json 2>/dev/null | python3 -c 'import sys,json;print(json.load(sys.stdin).get("compute_status",{}).get("state",""))' 2>/dev/null)
  [ "$cs" = "ACTIVE" ] && break
  sleep 10
done
echo "▶ sync source → $WS"
databricks sync --full "$STAGE" "$WS" -p "$P"
echo "▶ deploy…"
databricks apps deploy "$APP" --source-code-path "/Workspace$WS" --mode SNAPSHOT -p "$P" -o json \
  | python3 -c 'import sys,json;d=json.load(sys.stdin);print("  deploy:",d.get("status",{}).get("state"))'
echo "▶ URL:"; databricks apps get "$APP" -p "$P" -o json | python3 -c 'import sys,json;print("  "+json.load(sys.stdin).get("url",""))'
