#!/usr/bin/env bash
set -e

# ============================================================
# Deploy the React UI app to Databricks Apps
# ============================================================
#
# Reads configuration from ../../.env (copy from .env.example).
#
# Usage:
#   ./deploy.sh
#
# Prerequisites:
#   - cp ../../.env.example ../../.env  (and fill in your values)
#   - The FastAPI backend app must be deployed first
#   - FASTAPI_APP_URL must be set in .env
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/../../.env"

if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: .env file not found at $ENV_FILE"
    echo "Run:   cp .env.example .env   in the repo root and fill in your values."
    exit 1
fi

source "$ENV_FILE"

APP_NAME="${REACT_APP_NAME:?Set REACT_APP_NAME in .env}"
WORKSPACE_PATH="${REACT_WORKSPACE_PATH:?Set REACT_WORKSPACE_PATH in .env}"
APP_URL="${FASTAPI_APP_URL:?Set FASTAPI_APP_URL in .env (deploy fastapi-app/ first)}"
PROFILE="${CLI_PROFILE:-}"
PROFILE_FLAG=""
[ -n "$PROFILE" ] && PROFILE_FLAG="--profile $PROFILE"

echo "=== Deploying React UI App ==="
echo "App name:       $APP_NAME"
echo "Local source:   $SCRIPT_DIR"
echo "Workspace path: $WORKSPACE_PATH"
echo "FastAPI URL:    $APP_URL"
echo "CLI profile:    ${PROFILE:-default}"
echo ""

# Write FastAPI app URL into app.yaml
sed -i.bak "s|<YOUR_FASTAPI_APP_URL>|${APP_URL}|g" "$SCRIPT_DIR/app.yaml" && rm -f "$SCRIPT_DIR/app.yaml.bak"

# Sync local files to workspace (full overwrite)
echo "Syncing local source to workspace..."
databricks sync "$SCRIPT_DIR" "$WORKSPACE_PATH" $PROFILE_FLAG

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
echo "  1. Apps > $APP_NAME > Permissions -- add users/groups with 'CAN USE'"
