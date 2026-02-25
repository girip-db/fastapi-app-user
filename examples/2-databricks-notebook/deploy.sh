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

# --- notebook_example.py (User PKCE flow) ---
cp "$SCRIPT_DIR/notebook_example.py" "$TEMP_DIR/notebook_example.py"
sed -i.bak "s|https://<YOUR_FASTAPI_APP_URL>|${FASTAPI_APP_URL}|g" "$TEMP_DIR/notebook_example.py"
sed -i.bak "s|https://<YOUR_WORKSPACE_URL>|${WORKSPACE_URL%/}|g" "$TEMP_DIR/notebook_example.py"
rm -f "$TEMP_DIR/notebook_example.py.bak"

# --- notebook_sp_groups.py (SP M2M with SCIM scope) ---
cp "$SCRIPT_DIR/notebook_sp_groups.py" "$TEMP_DIR/notebook_sp_groups.py"
sed -i.bak "s|https://<YOUR_FASTAPI_APP_URL>|${FASTAPI_APP_URL}|g" "$TEMP_DIR/notebook_sp_groups.py"
sed -i.bak "s|https://<YOUR_WORKSPACE_URL>|${WORKSPACE_URL%/}|g" "$TEMP_DIR/notebook_sp_groups.py"
rm -f "$TEMP_DIR/notebook_sp_groups.py.bak"

# Import notebooks
echo "Importing notebook_example..."
databricks workspace import "$WORKSPACE_DIR/notebook_example" \
    --file "$TEMP_DIR/notebook_example.py" \
    --language PYTHON \
    --overwrite \
    $PROFILE_FLAG

echo "Importing notebook_sp_groups..."
databricks workspace import "$WORKSPACE_DIR/notebook_sp_groups" \
    --file "$TEMP_DIR/notebook_sp_groups.py" \
    --language PYTHON \
    --overwrite \
    $PROFILE_FLAG

rm -rf "$TEMP_DIR"

echo ""
echo "=== Sync complete ==="
echo ""
echo "Notebooks imported to: $WORKSPACE_DIR/"
echo "  - notebook_example      (User PKCE flow)"
echo "  - notebook_sp_groups    (SP M2M with SCIM scope)"
echo ""
echo "Next steps:"
echo "  1. Open the notebook in your Databricks workspace"
echo "  2. Attach it to a cluster"
echo "  3. For notebook_sp_groups: fill in SP_CLIENT_ID, SP_CLIENT_SECRET, LOOKUP_EMAIL"
echo "  4. Run each cell in order"
