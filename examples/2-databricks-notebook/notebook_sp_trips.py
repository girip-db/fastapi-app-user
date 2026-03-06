# Databricks notebook source
# MAGIC %md
# MAGIC # SP Auth + User Identity: Calling App Endpoints from a Notebook
# MAGIC
# MAGIC This notebook demonstrates two ways to call the FastAPI app's `/trips` endpoint
# MAGIC with an **SP token for app access** and a **user token for SQL execution**:
# MAGIC
# MAGIC | Method | SP Token | User Token (X-User-Token) | Manual Steps |
# MAGIC |---|---|---|---|
# MAGIC | **Method 1**: Notebook native token | `client_credentials` | `dbutils` apiToken | None |
# MAGIC | **Method 2**: WorkspaceClient OAuth | `client_credentials` | `WorkspaceClient` token | None |
# MAGIC
# MAGIC Both methods are fully automated -- no browser login or paste steps required.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Configuration
# MAGIC
# MAGIC Update these values for your environment.
# MAGIC Use `dbutils.secrets.get()` for `SP_CLIENT_SECRET` in production.

# COMMAND ----------

APP_URL = "https://<YOUR_FASTAPI_APP_URL>"
WORKSPACE_URL = "https://<YOUR_WORKSPACE_URL>"

SP_CLIENT_ID = "<YOUR_SP_CLIENT_ID>"
SP_CLIENT_SECRET = "<YOUR_SP_CLIENT_SECRET>"  # Use dbutils.secrets.get() in production

SCOPES = "sql iam.current-user:read catalog.tables:read iam.access-control:read"

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1: Get SP OAuth Token (client_credentials flow)

# COMMAND ----------

import requests
import json

token_resp = requests.post(
    f"{WORKSPACE_URL}/oidc/v1/token",
    data={
        "grant_type": "client_credentials",
        "client_id": SP_CLIENT_ID,
        "client_secret": SP_CLIENT_SECRET,
        "scope": SCOPES,
    },
)

print(f"Token endpoint status: {token_resp.status_code}")

if token_resp.status_code == 200:
    token_data = token_resp.json()
    sp_token = token_data["access_token"]
    print(f"Token type:    {token_data.get('token_type')}")
    print(f"Expires in:    {token_data.get('expires_in')}s")
    print(f"Scope:         {token_data.get('scope')}")
    print(f"Token prefix:  {sp_token[:20]}...")
else:
    print(f"ERROR: {token_resp.text}")
    sp_token = None

# COMMAND ----------

# MAGIC %md
# MAGIC ## Method 1: Notebook Native Token as X-User-Token
# MAGIC
# MAGIC The simplest approach. The notebook's built-in token represents the
# MAGIC interactive user. Pass it as `X-User-Token` so the app runs SQL
# MAGIC as the user (not the SP).

# COMMAND ----------

assert sp_token, "No SP token -- fix Step 1 first"

native_token = (
    dbutils.notebook.entry_point  # noqa: F821
    .getDbutils().notebook().getContext().apiToken().get()
)

print(f"Native token prefix: {native_token[:20]}...")

headers = {
    "Authorization": f"Bearer {sp_token}",
    "X-User-Token": native_token,
}

# Call /trips -- SQL runs as the user
resp = requests.get(f"{APP_URL}/api/v1/trips", headers=headers)
print(f"\n/trips status: {resp.status_code}")
print(f"auth_mode:     {resp.json().get('auth_mode')}")
print(json.dumps(resp.json(), indent=2) if resp.status_code == 200 else resp.text)


# COMMAND ----------

# MAGIC %md
# MAGIC ## Method 3: Debug Headers (verify what the app receives)
# MAGIC
# MAGIC Call the `/debug/headers` endpoint to see exactly which headers
# MAGIC arrive at the app for each method.

# COMMAND ----------

assert sp_token, "No SP token -- fix Step 1 first"

print("=== Method 1: Notebook native token ===")
resp = requests.get(
    f"{APP_URL}/api/v1/debug/headers",
    headers={"Authorization": f"Bearer {sp_token}", "X-User-Token": native_token},
)
print(json.dumps(resp.json().get("auth_headers", {}), indent=2))


# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary
# MAGIC
# MAGIC | Method | User Token Source | Automated? | SQL Runs As |
# MAGIC |---|---|---|---|
# MAGIC | Notebook native token | `dbutils...apiToken().get()` | Yes | Interactive user |
# MAGIC
# MAGIC - Use SP `client_credentials` for app access (`Authorization: Bearer`)
# MAGIC - Pass user identity via `X-User-Token` header
# MAGIC - The app checks `X-User-Token` first, so SQL runs as the user
# MAGIC - Are fully automated -- no browser or paste steps needed
