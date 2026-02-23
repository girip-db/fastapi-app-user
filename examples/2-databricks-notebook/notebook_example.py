# Databricks notebook source
# MAGIC %md
# MAGIC # Use Case 2: Calling FastAPI App from a Databricks Notebook
# MAGIC
# MAGIC This notebook demonstrates **User Authorization** using the
# MAGIC OAuth Authorization Code + PKCE flow from a Databricks notebook.
# MAGIC
# MAGIC The query runs as **your user identity**, respecting Unity Catalog
# MAGIC row-level security and column masks.
# MAGIC
# MAGIC ## How it works
# MAGIC 1. Generate PKCE credentials (automatic)
# MAGIC 2. Click the authorization URL to authenticate in your browser
# MAGIC 3. Paste the auth code back into the notebook
# MAGIC 4. Token exchange happens automatically
# MAGIC 5. Call the app endpoints with the scoped OAuth token

# COMMAND ----------

# MAGIC %md
# MAGIC ## Configuration
# MAGIC
# MAGIC Update these values for your environment.

# COMMAND ----------

# ---- CONFIGURE THESE ----
APP_URL = "https://<YOUR_FASTAPI_APP_URL>"  # Deployed FastAPI app URL (no trailing slash)
WORKSPACE_URL = "https://<YOUR_WORKSPACE_URL>"  # e.g. https://adb-1234567890.12.azuredatabricks.net

SCOPES = "sql iam.current-user:read catalog.tables:read iam.access-control:read"
CLIENT_ID = "databricks-cli"
REDIRECT_URI = "http://localhost:8020"

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1: Generate PKCE credentials and authorization URL
# MAGIC
# MAGIC Run this cell, then **click the link** that appears.

# COMMAND ----------

import hashlib
import base64
import secrets
import urllib.parse

code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(96)).rstrip(b"=").decode("ascii")

code_challenge = (
    base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode("ascii")).digest())
    .rstrip(b"=")
    .decode("ascii")
)

params = {
    "client_id": CLIENT_ID,
    "redirect_uri": REDIRECT_URI,
    "response_type": "code",
    "code_challenge": code_challenge,
    "code_challenge_method": "S256",
    "scope": SCOPES,
}

authorize_url = f"{WORKSPACE_URL}/oidc/v1/authorize?{urllib.parse.urlencode(params)}"

print("Open this URL in your browser to authenticate:\n")
print(authorize_url)

displayHTML(  # noqa: F821
    f'<h3>Click to authenticate:</h3>'
    f'<a href="{authorize_url}" target="_blank" '
    f'style="font-size:16px; color:#1E88E5;">{authorize_url}</a>'
    f'<br><br>'
    f'<p>After authenticating, the browser redirects to <code>http://localhost:8020?code=XXXX</code>.</p>'
    f'<p>The page will show an error -- that is expected. Copy the <b>code</b> value from the URL bar '
    f'and paste it into the widget below.</p>'
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 2: Paste the authorization code
# MAGIC
# MAGIC After authenticating, your browser URL bar will look like:
# MAGIC ```
# MAGIC http://localhost:8020?code=XXXXXXXX&state=...
# MAGIC ```
# MAGIC Copy everything after `code=` and before `&` (or the end of the URL).

# COMMAND ----------

dbutils.widgets.text("auth_code", "", "Paste auth code here")  # noqa: F821

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 3: Exchange authorization code for an OAuth token

# COMMAND ----------

import requests

auth_code = dbutils.widgets.get("auth_code").strip()  # noqa: F821
assert auth_code, "Paste the authorization code into the widget first!"

token_resp = requests.post(
    f"{WORKSPACE_URL}/oidc/v1/token",
    data={
        "client_id": CLIENT_ID,
        "grant_type": "authorization_code",
        "code": auth_code,
        "code_verifier": code_verifier,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
    },
)

print(f"Token endpoint status: {token_resp.status_code}")

if token_resp.status_code == 200:
    token_data = token_resp.json()
    oauth_token = token_data["access_token"]
    print(f"Token type:    {token_data.get('token_type')}")
    print(f"Expires in:    {token_data.get('expires_in')}s")
    print(f"Scope:         {token_data.get('scope')}")
    print(f"Token prefix:  {oauth_token[:20]}...")
else:
    print(f"ERROR: {token_resp.text}")
    oauth_token = None

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 4: Call the app endpoints

# COMMAND ----------

assert oauth_token, "No OAuth token -- fix Step 3 first"

headers = {"Authorization": f"Bearer {oauth_token}"}

# --- Healthcheck ---
resp = requests.get(f"{APP_URL}/api/v1/healthcheck", headers=headers)
print(f"Healthcheck [{resp.status_code}]: {resp.text}\n")

# --- Who am I ---
resp = requests.get(f"{APP_URL}/api/v1/me", headers=headers)
print(f"Me          [{resp.status_code}]: {resp.text}\n")

# --- Trips ---
resp = requests.get(f"{APP_URL}/api/v1/trips", headers=headers)
print(f"Trips       [{resp.status_code}]: {resp.text}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Cleanup

# COMMAND ----------

dbutils.widgets.remove("auth_code")  # noqa: F821
