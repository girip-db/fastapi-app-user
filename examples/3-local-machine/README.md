# Use Case 3: Local Machine (Jupyter / Cursor)

Call the FastAPI app from your **local development machine** using the Databricks CLI's OAuth flow.

## How It Works

The Databricks CLI handles the full OAuth + PKCE flow automatically -- it opens your browser, you authenticate, and the CLI captures the token. No manual code copying needed.

## Setup

Run the setup script (one-time):

```bash
./setup_local.sh              # uses default profile 'my-env'
./setup_local.sh my-profile   # uses custom profile name
```

This will:
1. Create a Python venv in `.venv/`
2. Install `databricks-sdk` and `requests`
3. Run `databricks auth login` (opens browser for OAuth)

## Run the Test

```bash
source .venv/bin/activate
python local_test.py --profile my-env --app-url https://<YOUR_FASTAPI_APP_URL>
```

## Expected Output

```
Auth type:    databricks-cli
Host:         https://your-workspace.cloud.databricks.com
Token prefix: eyJraWQiOiI2MDZi...

--- Healthcheck ---
Status: 200
{ "status": "OK", "user_info": { "email": "you@company.com", ... } }

--- Who Am I ---
Status: 200
{ "email": "you@company.com", "preferred_username": "Your Name", ... }

--- NYC Taxi Trips ---
Status: 200
{ "count": 5, "results": [...] }
```

## Alternative: Standalone OAuth Token Generator

`getOAuth.py` implements the full PKCE flow as a standalone script. It starts a local HTTP server to capture the redirect automatically.

```bash
python getOAuth.py \
    --host https://<YOUR_WORKSPACE_URL> \
    --scopes "sql iam.current-user:read catalog.tables:read iam.access-control:read"
```

This prints the full token response as JSON to stdout. Use it when you need a raw OAuth token for testing with curl or other tools.

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `ValueError: OAuth tokens are not available for pat authentication` | Your profile uses a PAT. Re-run: `databricks auth login --host <url> --profile <profile>` |
| `401` from the app | Check that your user has `CAN USE` permission on the app |
| `403` from the app | Token doesn't include all required scopes (`sql`, `iam.current-user:read`, `catalog.tables:read`, `iam.access-control:read`). Verify User Authorization config. |
