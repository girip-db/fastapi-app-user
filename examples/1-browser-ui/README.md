# Use Case 1: Browser UI

A React dashboard deployed as a **separate Databricks App** that calls the FastAPI backend. Demonstrates that browser-based authentication is fully automatic -- the user's Databricks session handles OAuth transparently.

## How It Works

1. User opens the React app URL in their browser
2. Databricks Apps proxy authenticates the user via their session
3. The React frontend calls `/api/proxy/*` endpoints on its own backend
4. The backend extracts the `x-forwarded-access-token` header and forwards it to the FastAPI app
5. The FastAPI app runs queries **as the user**

No tokens, no login prompts -- it just works.

## Configuration

Edit `app.yaml` -- set the FastAPI backend URL:

```yaml
env:
  - name: FASTAPI_APP_URL
    value: "https://<YOUR_FASTAPI_APP_URL>"  # Replace after deploying fastapi-app/
```

## Deploy

All config is read from the top-level `.env` file. Make sure `FASTAPI_APP_URL` is set (deploy `fastapi-app/` first).

```bash
# Ensure ../../.env exists and FASTAPI_APP_URL is set
./deploy.sh
```

The script reads `REACT_APP_NAME`, `REACT_WORKSPACE_PATH`, `FASTAPI_APP_URL`, and `CLI_PROFILE` from `.env`, syncs local files to the workspace, and deploys.

## Post-Deployment

1. **Permissions**: Apps > your app > Permissions -- add users/groups with **CAN USE**

2. **User Authorization** (required!):
   - Apps > **react-app** > **Settings > User Authorization**
   - Add the same scopes as the FastAPI app: **`sql`**, **`iam.current-user:read`**, **`catalog.tables:read`**, **`iam.access-control:read`**
   - This is needed so the Databricks proxy injects `x-forwarded-access-token` into requests reaching this app's backend, which then forwards it to the FastAPI app
   - **Both the React UI app AND the FastAPI app need all scopes** -- if either is missing them, queries will fall back to the service principal

3. **Clear browser cookies** after adding the scope, then open the app URL

### Troubleshooting

| Symptom | Fix |
|---------|-----|
| Trips card shows data but `auth_mode` is `service_principal` | Add all required scopes on this app + clear cookies |
| Trips card shows 403 error | Add all required scopes on this app AND the FastAPI app + clear cookies |
| `/api/proxy/debug` shows `x-forwarded-access-token_present: false` | Scopes not configured on this app, or cookies are stale |

## What You'll See

- A top bar showing your email (proving user identity flows through)
- Healthcheck status card
- User info card with your authenticated identity
- A table with query results
