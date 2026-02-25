# FastAPI Backend App

The core API application deployed as a Databricks App. Provides four endpoints that demonstrate user authentication and group membership lookup.

## Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/v1/healthcheck` | Returns status + authenticated user info |
| `GET /api/v1/me` | Returns the caller's identity (email, username, auth status) |
| `GET /api/v1/me/groups` | Returns the user's group memberships (see below) |
| `GET /api/v1/trips` | Runs a SQL query and returns results as JSON |

### `/api/v1/me/groups` -- Group Membership Lookup

All paths verify the caller's identity via SCIM `/Me` -- no self-asserted headers:

| Access Method | Token Source | How Identity Is Verified |
|---|---|---|
| **Browser** | `x-forwarded-access-token` (injected by Databricks proxy) | SCIM `/Me` with the user's OAuth token |
| **Notebook** (`X-User-Token` header) | Notebook native token via `dbutils` | SCIM `/Me` with the notebook token |

If neither token is present, the endpoint returns `400`.

## How Authentication Works

- The Databricks Apps proxy sits in front of this app
- It validates incoming OAuth tokens and injects `x-forwarded-*` headers
- `/api/v1/trips` uses the `x-forwarded-access-token` to run SQL **as the user**
- `/api/v1/me/groups` uses a verified token (browser or `X-User-Token`) with SCIM `/Me` for group lookups
- If no user token is present, SQL queries fall back to the app's service principal

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

4. **Group Lookup** (`/me/groups`):
   - All paths use SCIM `/Me` with a verified token (browser OAuth token or notebook native token via `X-User-Token` header)
   - No SP admin permissions needed -- each token proves the caller's own identity

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
