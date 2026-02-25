# Databricks notebook source
# MAGIC %md
# MAGIC # SP OAuth with SCIM Scope -- Fetch User Groups
# MAGIC
# MAGIC This notebook demonstrates using **Service Principal M2M OAuth** (client_credentials flow)
# MAGIC with the `scim` scope to look up a user's group memberships via the SCIM API,
# MAGIC then call the FastAPI app endpoint.
# MAGIC
# MAGIC ## How it works
# MAGIC 1. Get an SP OAuth token using client_credentials grant with `scim` scope
# MAGIC 2. Call SCIM `/Users` API to look up any user's groups
# MAGIC 3. Call the FastAPI app's `/api/v1/me/groups` endpoint

# COMMAND ----------

# MAGIC %md
# MAGIC ## Configuration
# MAGIC
# MAGIC Update these values for your environment.
# MAGIC Use Databricks secrets to store `SP_CLIENT_SECRET` in production.

# COMMAND ----------

APP_URL = "https://<YOUR_FASTAPI_APP_URL>"
WORKSPACE_URL = "https://<YOUR_WORKSPACE_URL>"

SP_CLIENT_ID = "<YOUR_SP_CLIENT_ID>"
SP_CLIENT_SECRET = "<YOUR_SP_CLIENT_SECRET>"  # Use dbutils.secrets.get() in production

SCOPES = "sql iam.current-user:read catalog.tables:read iam.access-control:read scim"

# Auto-detect the current notebook user's email
LOOKUP_EMAIL = spark.sql("SELECT current_user()").first()[0]  # noqa: F821
print(f"Current user: {LOOKUP_EMAIL}")

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
# MAGIC ## Step 2: Call SCIM API directly to look up user groups

# COMMAND ----------

assert sp_token, "No SP token -- fix Step 1 first"

headers = {"Authorization": f"Bearer {sp_token}"}

# Look up a specific user's groups via SCIM /Users
scim_resp = requests.get(
    f"{WORKSPACE_URL}/api/2.0/preview/scim/v2/Users",
    headers=headers,
    params={"filter": f'userName eq "{LOOKUP_EMAIL}"'},
)

print(f"SCIM API status: {scim_resp.status_code}\n")

if scim_resp.status_code == 200:
    data = scim_resp.json()
    for user in data.get("Resources", []):
        print(f"User:   {user.get('userName')}")
        print(f"ID:     {user.get('id')}")
        groups = [g["display"] for g in user.get("groups", []) if g.get("display")]
        print(f"Groups: {groups}")
        break
    else:
        print("User not found")
else:
    print(f"ERROR: {scim_resp.text}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 3: Call the FastAPI app's /me/groups with verified identity
# MAGIC
# MAGIC Pass `X-User-Token` header with the notebook's native token. The app
# MAGIC verifies the caller's identity by calling SCIM `/Me` with that token --
# MAGIC no impersonation is possible since the token proves who the caller is.

# COMMAND ----------

assert sp_token, "No SP token -- fix Step 1 first"

# Get the notebook's native token for identity verification
user_token = dbutils.notebook.entry_point.getDbutils().notebook().getContext().apiToken().get()  # noqa: F821

headers = {
    "Authorization": f"Bearer {sp_token}",
    "X-User-Token": user_token,
}

resp = requests.get(f"{APP_URL}/api/v1/me/groups", headers=headers)
print(f"App /me/groups status: {resp.status_code}")
print(json.dumps(resp.json(), indent=2) if resp.status_code == 200 else resp.text)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary
# MAGIC
# MAGIC | Approach | Token | Identity Verified? | Groups Returned |
# MAGIC |---|---|---|---|
# MAGIC | Browser (User Auth) | `x-forwarded-access-token` | Yes (SCIM `/Me`) | Current user's groups |
# MAGIC | Notebook (`X-User-Token`) | Notebook native token | Yes (SCIM `/Me`) | Current user's groups |
