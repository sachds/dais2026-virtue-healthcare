#!/usr/bin/env bash
# Run the Referral Copilot as a REAL Omnigent agent over the trust_desk MCP — the
# same Lakebase the app reads. Proves the governed referral loop (plan → retrieve
# → scrutinize → challenge → govern → compose) runs under the actual harness, not
# only in-process. Renders the config with concrete paths + Lakebase URL so the
# password stays out of git. Pass the request as $1.
#
#   ./scripts/run_referral_agent.sh "cancer care near Ranchi"
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] && { set -a; source .env; set +a; }
: "${LAKEBASE_URL:?set LAKEBASE_URL in trustdesk/.env}"

TRUSTDESK="$(pwd)"
HACK="$(cd .. && pwd)"
PYTHON="${MCP_PYTHON:-$HACK/commons/.venv/bin/python}"   # a venv with mcp + psycopg
MCP_SERVER="$TRUSTDESK/mcp_server.py"

OMNI=omnigent
for c in "$HACK/.omni-venv/bin/omnigent" "$HOME/.omni-venv/bin/omnigent"; do
  [ -x "$c" ] && OMNI="$c" && break
done
if ! { command -v "$OMNI" >/dev/null 2>&1 || [ -x "$OMNI" ]; }; then
  echo "Omnigent isn't installed. See commons/scripts/run_omnigent.sh for setup"
  echo "  (python -m venv ../.omni-venv && ../.omni-venv/bin/pip install omnigent)."
  exit 1
fi

# Render the config with concrete python / server / Lakebase URL (# delimiter so
# the URL's slashes are safe; the token-hex password has no '#'). An omnigent spec
# (declares spec_version) must live in a BUNDLE DIRECTORY as config.yaml — not a
# bare file — so render into a temp dir kept out of git (the password is in it).
CFGDIR="${REFERRAL_CFG_DIR:-/tmp/referral-agent}"
mkdir -p "$CFGDIR"
sed -e "s#__PYTHON__#$PYTHON#g" \
    -e "s#__MCP_SERVER__#$MCP_SERVER#g" \
    -e "s#__LAKEBASE_URL__#$LAKEBASE_URL#g" \
    agents/referral/config.yaml > "$CFGDIR/config.yaml"
echo "✓ rendered $CFGDIR/config.yaml (trust_desk MCP → Lakebase)"

QUERY="${1:-emergency and ICU near Patna}"
echo "▶ omnigent run — referral: \"$QUERY\""
# Default topology: omnigent spawns a local server + runs the agent headless (-p).
exec "$OMNI" run "$CFGDIR" -p "$QUERY"
