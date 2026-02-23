#!/usr/bin/env bash
set -e

# ============================================================
# Deploy the FastAPI app to Databricks Apps
# ============================================================
#
# Reads configuration from ../.env (copy from .env.example).
#
# Usage:
#   ./deploy.sh
#
# Prerequisites:
#   - cp ../.env.example ../.env  (and fill in your values)
#   - Databricks CLI installed and authenticated
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/../.env"

if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: .env file not found at $ENV_FILE"
    echo "Run:   cp .env.example .env   and fill in your values."
    exit 1
fi

source "$ENV_FILE"

APP_NAME="${FASTAPI_APP_NAME:?Set FASTAPI_APP_NAME in .env}"
WORKSPACE_PATH="${FASTAPI_WORKSPACE_PATH:?Set FASTAPI_WORKSPACE_PATH in .env}"
PROFILE="${CLI_PROFILE:-}"
PROFILE_FLAG=""
[ -n "$PROFILE" ] && PROFILE_FLAG="--profile $PROFILE"

echo "=== Deploying FastAPI App ==="
echo "App name:       $APP_NAME"
echo "Local source:   $SCRIPT_DIR"
echo "Workspace path: $WORKSPACE_PATH"
echo "CLI profile:    ${PROFILE:-default}"
echo ""

# Write warehouse ID into app.yaml (temporarily)
sed -i.bak "s|<YOUR_WAREHOUSE_ID>|${WAREHOUSE_ID}|g" "$SCRIPT_DIR/app.yaml"

# Sync local files to workspace (full overwrite)
echo "Syncing local source to workspace..."
databricks sync "$SCRIPT_DIR" "$WORKSPACE_PATH" --full $PROFILE_FLAG

# Restore app.yaml to its template form so future deploys work
mv "$SCRIPT_DIR/app.yaml.bak" "$SCRIPT_DIR/app.yaml"

# Create the app (ignore error if it already exists)
echo ""
echo "Creating app '$APP_NAME'..."
databricks apps create "$APP_NAME" $PROFILE_FLAG 2>/dev/null || echo "(App may already exist, continuing...)"

# Deploy from workspace path
echo "Deploying from workspace path..."
databricks apps deploy "$APP_NAME" --source-code-path "$WORKSPACE_PATH" $PROFILE_FLAG

echo ""
echo "=== Deployment complete ==="
echo ""
echo "Next steps:"
echo "  1. Note the app URL from the Databricks UI and set FASTAPI_APP_URL in .env"
echo "  2. Apps > $APP_NAME > Permissions -- add users/groups with 'CAN USE'"
echo "  3. Apps > $APP_NAME > Settings > User Authorization -- add the 'sql' scope"
echo "  4. Grant the app's service principal:"
echo "     - CAN USE on the SQL warehouse"
echo "     - SELECT on the table being queried"
