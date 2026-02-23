# Databricks Apps -- User Authentication Demo

This repository demonstrates how to build and consume a **FastAPI application** deployed on [Databricks Apps](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/) with **User Authorization** (OAuth).

It covers three real-world scenarios for calling the app with the user's identity:

| # | Use Case | Auth Method | User Identity? |
|---|----------|-------------|----------------|
| 1 | Browser accessing the app UI | Automatic (Databricks session) | Yes |
| 2 | Databricks notebook calling the API | OAuth PKCE (paste code once) | Yes |
| 3 | Local machine (Jupyter/Cursor) calling the API | Databricks CLI OAuth | Yes |

## Architecture

```
                    Databricks Apps Proxy
                    (validates OAuth, injects user headers)
                          |
         +----------------+----------------+
         |                |                |
    [Browser]     [DB Notebook]     [Local Machine]
    Session auth   PKCE + scope     CLI OAuth
         |                |                |
         v                v                v
    React UI App    Direct API call   Direct API call
    (proxies to     with Bearer       with Bearer
     FastAPI app)   token             token
         |                |                |
         +--------> FastAPI App <----------+
                    /api/v1/healthcheck
                    /api/v1/me
                    /api/v1/trips
                         |
                    SQL Warehouse
                    (user's token or SP fallback)
```

## Repository Structure

### [`fastapi-app/`](fastapi-app/)

The core **FastAPI backend** deployed as a Databricks App. Exposes three endpoints (`/api/v1/healthcheck`, `/api/v1/me`, `/api/v1/trips`) that demonstrate user authentication and SQL query execution on behalf of the logged-in user. Includes `deploy.sh` for one-command deployment.

### [`examples/1-browser-ui/`](examples/1-browser-ui/)

A **React dashboard** deployed as a separate Databricks App. The user's browser session handles OAuth transparently -- no tokens or login prompts needed. The React frontend calls proxy endpoints on its own backend, which forwards the user's `x-forwarded-access-token` to the FastAPI app. Includes `deploy.sh`.

### [`examples/2-databricks-notebook/`](examples/2-databricks-notebook/)

A **Databricks notebook** that calls the FastAPI app using the OAuth **PKCE flow**. Since notebooks run on remote clusters with no browser, the user clicks an auth URL once, pastes back a code, and the notebook exchanges it for a scoped OAuth token. Includes `deploy.sh` to sync the notebook to your workspace.

### [`examples/3-local-machine/`](examples/3-local-machine/)

Scripts for calling the FastAPI app from a **local dev machine** (Jupyter, Cursor, terminal). Uses `getOAuth.py` which runs a full automated PKCE flow -- it opens your browser, captures the callback on a local HTTP server, and returns a properly scoped token. Includes `setup_local.sh` for one-command environment setup and `local_test.py` to test all endpoints.

## Configuration

All configuration lives in a single `.env` file at the repo root. Deploy scripts and setup scripts read from it automatically.

```bash
cp .env.example .env   # then edit .env with your values
```

| Variable | Description |
|----------|-------------|
| `WORKSPACE_URL` | Your Databricks workspace URL |
| `WAREHOUSE_ID` | SQL warehouse ID |
| `CLI_PROFILE` | Databricks CLI profile name (default: `my-env`) |
| `SCOPES` | OAuth scopes for User Authorization (see [Required Scopes](#required-scopes)) |
| `FASTAPI_APP_NAME` | Name for the FastAPI Databricks App |
| `FASTAPI_WORKSPACE_PATH` | Workspace path to sync FastAPI source to |
| `FASTAPI_APP_URL` | Deployed FastAPI app URL (set after first deploy) |
| `REACT_APP_NAME` | Name for the React UI Databricks App |
| `REACT_WORKSPACE_PATH` | Workspace path to sync React UI source to |

## Quick Start

### 1. Create `.env`

```bash
cp .env.example .env
# Edit .env -- fill in WORKSPACE_URL, WAREHOUSE_ID, paths, and app names
```

### 2. Deploy the FastAPI backend

```bash
cd fastapi-app
./deploy.sh
```

After deployment, note the app URL from the Databricks UI and set `FASTAPI_APP_URL` in `.env`.

### 3. Configure User Authorization

> **This is the most critical step.** Without it, queries will fall back to the service principal and user identity will not flow through.

In the Databricks UI, for **each** app (FastAPI app **and** React UI app):

1. Go to **Apps > your app > Settings > User Authorization**
2. Add **all required scopes** (see table below)
3. Go to **Permissions** and add users/groups with **CAN USE**

After changing scopes, users must **clear their browser cookies** (or open an incognito window) to get a new token with the updated scopes.

### Required Scopes

Add these scopes under **User Authorization** for **each** deployed app (FastAPI app and React UI app):

| Scope | Purpose |
|-------|---------|
| `sql` | Execute SQL and manage SQL resources |
| `iam.current-user:read` | Read the authenticated user's identity (default scope) |
| `catalog.tables:read` | Read tables in Unity Catalog |
| `iam.access-control:read` | Read access control information (default scope) |

When calling the app from a **notebook or local machine** (Use Cases 2 & 3), the OAuth token request must also include these same scopes. The deploy scripts read the `SCOPES` variable from `.env` and inject them automatically.

### 4. Try each use case

- **Browser UI**: `cd examples/1-browser-ui && ./deploy.sh`
- **Notebook**: Import `examples/2-databricks-notebook/notebook_example.py` into your workspace
- **Local**: `cd examples/3-local-machine && ./setup_local.sh`

See the README in each directory for detailed instructions.

## How User Authorization Works

When a user accesses a Databricks App, the Apps proxy:
1. Validates the user's OAuth token
2. Injects identity headers: `x-forwarded-email`, `x-forwarded-user`, `x-forwarded-preferred-username`
3. If User Authorization scopes are configured, also injects `x-forwarded-access-token`

The FastAPI app reads these headers to:
- Identify who is calling (`/api/v1/me`)
- Run SQL queries **as the user** using their forwarded token (`/api/v1/trips`)
- Fall back to the app's service principal if no user token is present

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `auth_mode` shows `service_principal` instead of `user_token` | User Authorization not configured or missing scopes | Add all required scopes in **Apps > Settings > User Authorization** for the app |
| 403 "OAuth token does not have required scopes: sql" | Token was issued before scopes were added | Clear browser cookies / incognito window to force a new token |
| 500 "Error during request to server" from SQL connector | `server_hostname` includes `https://` scheme | Ensure code strips the scheme: `Config().host.removeprefix("https://")` |
| 500 "more than one authorization method configured" | Mixing `token=` param with env vars `DATABRICKS_CLIENT_ID`/`DATABRICKS_CLIENT_SECRET` | Don't use `WorkspaceClient(token=...)` inside a Databricks App -- use raw REST calls or `sql.connect(access_token=...)` instead |
| React UI returns data but `auth_mode` is `service_principal` | React UI app missing User Authorization `sql` scope | Add `sql` scope on the **React UI app too**, not just the FastAPI app |
| Queries work in browser but not from notebook | Notebook token lacks required scopes | Use OAuth PKCE flow with all required scopes (see Use Case 2) |
| 401 from notebook calling the app | Token scope too narrow (e.g. only `sql`) | Request all scopes: `sql iam.current-user:read catalog.tables:read iam.access-control:read` |

### Key Lessons

1. **Both apps need all scopes** -- if the React UI proxies to the FastAPI app, the React UI also needs User Authorization with the same scopes so it can receive and forward the user's token.
2. **Clear cookies after changing scopes** -- the Databricks Apps proxy caches the OAuth token in a session cookie. After updating scopes, the old token (without the new scope) remains until the cookie expires or is cleared.
3. **The `x-forwarded-access-token` header** is only injected when User Authorization scopes are configured on the app. Without it, all requests fall back to the service principal.
4. **The SQL connector works with forwarded tokens** -- `databricks-sql-connector`'s `sql.connect(access_token=...)` accepts the `x-forwarded-access-token` value directly.

## Prerequisites

- Databricks workspace with Unity Catalog enabled
- Databricks CLI installed and authenticated (`pip install databricks-cli`)
- A SQL warehouse (serverless recommended)
- Python 3.10+
