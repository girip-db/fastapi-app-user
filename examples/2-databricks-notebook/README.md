# Use Case 2: Databricks Notebook

Call the FastAPI app from a **Databricks notebook** using the user's own OAuth identity via the PKCE (Proof Key for Code Exchange) flow.

## Why PKCE?

A Databricks notebook runs on a remote cluster with no browser. The default notebook runtime token doesn't include the OAuth scopes required by apps with User Authorization. PKCE lets you obtain a properly scoped token with one manual step (pasting a code).

## How It Works

1. The notebook generates PKCE credentials and an authorization URL
2. You click the URL and authenticate in your browser
3. The browser redirects to `http://localhost:8020?code=XXXX` (the page errors -- expected)
4. You copy the `code` from the URL bar and paste it into a notebook widget
5. The notebook exchanges the code for an OAuth token with the required scopes
6. API calls use that token -- queries run as **your user identity**

## Configuration

In the notebook, update the first configuration cell:

```python
APP_URL = "https://<YOUR_FASTAPI_APP_URL>"      # Deployed FastAPI app URL
WORKSPACE_URL = "https://<YOUR_WORKSPACE_URL>"   # Your Databricks workspace URL
SCOPES = "sql iam.current-user:read catalog.tables:read iam.access-control:read"
```

The scopes must match what is configured under **User Authorization** on the FastAPI app:

| Scope | Purpose |
|-------|---------|
| `sql` | Execute SQL queries on behalf of the user |
| `iam.current-user:read` | Read the authenticated user's identity |
| `catalog.tables:read` | Read tables in Unity Catalog |
| `iam.access-control:read` | Read access control information |

> **Important:** If any scope is missing, the Apps proxy may return 401 or fall back to the service principal.

## Usage

1. Import `notebook_example.py` into your Databricks workspace
2. Attach to a cluster and run the cells in order
3. When prompted, click the auth URL, authenticate, paste the code back
4. The remaining cells call the endpoints and print the results

## Expected Output

```
Healthcheck [200]: {"status": "OK", "timestamp": "...", "user_info": {"email": "you@company.com", ...}}
Me          [200]: {"email": "you@company.com", "preferred_username": "Your Name", ...}
Trips       [200]: {"count": 5, "results": [...], "user_info": {"email": "you@company.com", ...}}
```

The `user_info` block confirms the query ran as your identity.

---

## Notebook 2: SP Group Lookup (`notebook_sp_groups.py`)

Uses the app's **service principal** with M2M OAuth (`client_credentials` flow) and the `scim` scope to look up a user's group memberships. The notebook user's email is auto-detected.

### Prerequisites

- The app's SP must be a **workspace admin** (added to the `admins` group)
- You need the SP's `client_id` and `client_secret`

### Configuration

Update the configuration cell:

```python
SP_CLIENT_ID = "<YOUR_SP_CLIENT_ID>"
SP_CLIENT_SECRET = "<YOUR_SP_CLIENT_SECRET>"  # Use dbutils.secrets.get() in production
```

`LOOKUP_EMAIL` is auto-detected via `spark.sql("SELECT current_user()")`.

### How It Works

1. **Step 1**: Gets an SP OAuth token via `client_credentials` with `scope=scim`
2. **Step 2**: Calls the SCIM `/Users` API directly to look up the user's groups
3. **Step 3**: Calls the app's `/api/v1/me/groups` with the `X-User-Email` header -- the app uses its SP credentials with an explicit `scim`-scoped token to fetch groups

### Key Learnings

- The `scim` scope must be **explicitly requested** in the SP token -- the Databricks SDK's default token does not include it
- The SP must be a **workspace admin** for the SCIM `/Users` endpoint to return group memberships (non-admin SPs get the user data but with empty groups)
- When calling the app programmatically, set the `X-User-Email` header to specify the real user's identity instead of relying on `x-forwarded-email` (which would be the SP's identity for M2M callers)
