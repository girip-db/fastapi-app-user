# FastAPI Backend App

The core API application deployed as a Databricks App. Provides three endpoints that demonstrate user authentication.

## Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/v1/healthcheck` | Returns status + authenticated user info |
| `GET /api/v1/me` | Returns the caller's identity (email, username, auth status) |
| `GET /api/v1/trips` | Runs a SQL query and returns results as JSON |

## How Authentication Works

- The Databricks Apps proxy sits in front of this app
- It validates incoming OAuth tokens and injects `x-forwarded-*` headers
- `/api/v1/trips` uses the `x-forwarded-access-token` to run SQL **as the user**
- If no user token is present, it falls back to the app's service principal

## Configuration

Edit `app.yaml` before deploying:

```yaml
env:
  - name: DATABRICKS_WAREHOUSE_ID
    value: "<YOUR_WAREHOUSE_ID>"  # Replace with your SQL warehouse ID
```

Optionally set `SQL_QUERY` to change the default query:

```yaml
  - name: SQL_QUERY
    value: "SELECT * FROM my_catalog.my_schema.my_table LIMIT 10"
```

## Deploy

All config is read from the top-level `.env` file. See [../.env.example](../.env.example).

```bash
cp ../.env.example ../.env   # fill in your values
./deploy.sh
```

The script reads `FASTAPI_APP_NAME`, `FASTAPI_WORKSPACE_PATH`, `WAREHOUSE_ID`, and `CLI_PROFILE` from `.env`, syncs local files to the workspace, and deploys.

## Post-Deployment Setup

1. **Permissions**: Apps > your app > Permissions -- add users/groups with **CAN USE**

2. **User Authorization** (required for user-token queries):
   - Apps > your app > **Settings > User Authorization**
   - Add the following scopes:
     - **`sql`** -- execute SQL queries
     - **`iam.current-user:read`** -- read user identity
     - **`catalog.tables:read`** -- read Unity Catalog tables
     - **`iam.access-control:read`** -- read access control info
   - Without these, `x-forwarded-access-token` will **not** be injected and all queries fall back to the service principal
   - **After adding scopes, users must clear browser cookies** to get a new token with the updated scopes

3. **Service Principal Grants** (for fallback when no user token):
   - `CAN USE` on the SQL warehouse
   - `SELECT` on the table being queried

### Verifying User Authorization Works

Hit `/api/v1/trips` in your browser. The response includes:

```json
{
  "auth_mode": "user_token",   // <-- confirms user's token is being used
  "user_info": {
    "email": "you@example.com",
    "is_authenticated": true
  }
}
```

If `auth_mode` is `service_principal`, the required scopes are missing or cookies need clearing.

## Local Development

```bash
pip install -r requirements.txt
export DATABRICKS_WAREHOUSE_ID=<your-warehouse-id>
uvicorn app:app --reload
```

Then open http://127.0.0.1:8000/docs for the interactive API docs.
