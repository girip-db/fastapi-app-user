#!/usr/bin/env bash
set -e

# ============================================================
# Set up a local Python environment and authenticate with
# Databricks via OAuth for testing the FastAPI app.
# ============================================================
#
# Reads configuration from ../../.env (copy from .env.example).
#
# Usage:
#   ./setup_local.sh
#
# What it does:
#   1. Creates a Python venv in .venv/
#   2. Installs databricks-sdk and requests
#   3. Runs 'databricks auth login' for OAuth (opens browser)
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/../../.env"
VENV_DIR="$SCRIPT_DIR/.venv"

if [ -f "$ENV_FILE" ]; then
    source "$ENV_FILE"
fi

PROFILE="${CLI_PROFILE:-my-env}"
WS_URL="${WORKSPACE_URL:-}"

echo "=== Setting up local test environment ==="

# 1. Create venv
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment in $VENV_DIR ..."
    python3 -m venv "$VENV_DIR"
else
    echo "Virtual environment already exists at $VENV_DIR"
fi

# 2. Install dependencies
echo "Installing dependencies ..."
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet databricks-sdk requests

echo ""
echo "Installed packages:"
"$VENV_DIR/bin/pip" list --format=columns | grep -iE "databricks|requests"

# 3. Authenticate via OAuth
if ! command -v databricks &> /dev/null; then
    echo ""
    echo "WARNING: 'databricks' CLI not found."
    echo "Install it: pip install databricks-cli  OR  brew install databricks"
    echo ""
else
    echo ""
    echo "=== Databricks OAuth Login (profile: $PROFILE) ==="
    echo ""
    if [ -z "$WS_URL" ]; then
        read -p "Enter your workspace URL (e.g. https://adb-123.12.azuredatabricks.net): " WS_URL
    else
        echo "Using workspace URL from .env: $WS_URL"
    fi
    databricks auth login --host "$WS_URL" --profile "$PROFILE"
    echo ""
    echo "Profile '$PROFILE' saved. Verifying token..."
    databricks auth token --profile "$PROFILE" | head -3
fi

APP_URL="${FASTAPI_APP_URL:-https://<YOUR_FASTAPI_APP_URL>}"

echo ""
echo "=== Setup complete ==="
echo ""
echo "Run the test:"
echo "  source $VENV_DIR/bin/activate"
echo "  python local_test.py --profile $PROFILE --app-url $APP_URL"
