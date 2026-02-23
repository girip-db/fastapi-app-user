#!/usr/bin/env bash
set -e

# ============================================================
# Sync the notebook to your Databricks workspace
# ============================================================
#
# Reads configuration from ../../.env
#
# Usage:
#   ./deploy.sh
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/../../.env"

if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: .env file not found at $ENV_FILE"
    echo "Run:   cp .env.example .env   and fill in your values."
    exit 1
fi

source "$ENV_FILE"

PROFILE="${CLI_PROFILE:-}"
PROFILE_FLAG=""
[ -n "$PROFILE" ] && PROFILE_FLAG="--profile $PROFILE"

WORKSPACE_DIR="/Workspace/Users/$(databricks current-user me $PROFILE_FLAG --output json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin)['userName'])")/notebooks"

echo "=== Syncing Notebook to Workspace ==="
echo "Local source:   $SCRIPT_DIR"
echo "Workspace path: $WORKSPACE_DIR"
echo "CLI profile:    ${PROFILE:-default}"
echo ""

# Replace placeholders with values from .env
TEMP_DIR=$(mktemp -d)
cp "$SCRIPT_DIR/notebook_example.py" "$TEMP_DIR/notebook_example.py"

sed -i.bak "s|https://<YOUR_FASTAPI_APP_URL>|${FASTAPI_APP_URL}|g" "$TEMP_DIR/notebook_example.py"
sed -i.bak "s|https://<YOUR_WORKSPACE_URL>|${WORKSPACE_URL%/}|g" "$TEMP_DIR/notebook_example.py"
rm -f "$TEMP_DIR/notebook_example.py.bak"

# Import the notebook
databricks workspace import "$WORKSPACE_DIR/notebook_example" \
    --file "$TEMP_DIR/notebook_example.py" \
    --language PYTHON \
    --overwrite \
    $PROFILE_FLAG

rm -rf "$TEMP_DIR"

echo ""
echo "=== Sync complete ==="
echo ""
echo "Notebook imported to: $WORKSPACE_DIR/notebook_example"
echo ""
echo "Next steps:"
echo "  1. Open the notebook in your Databricks workspace"
echo "  2. Attach it to a cluster"
echo "  3. Run each cell in order (follow the PKCE flow instructions)"
