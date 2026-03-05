# Databricks notebook source
# MAGIC %md
# MAGIC # Lakebase Scheduled Job: Create & Retrieve
# MAGIC
# MAGIC Lightweight notebook designed to run as a **scheduled job**.
# MAGIC It creates one item and retrieves it, recording who the job ran as.
# MAGIC
# MAGIC **How to test:** Schedule this as a job with "Run as" set to a specific
# MAGIC user or SP.  Check `created_by` and `auth_mode` on the resulting item.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Configuration
# MAGIC
# MAGIC Set these via job parameters or edit directly.

# COMMAND ----------

APP_URL = "https://<YOUR_FASTAPI_APP_URL>"
WORKSPACE_URL = "https://<YOUR_WORKSPACE_URL>"

SP_CLIENT_ID = "<YOUR_SP_CLIENT_ID>"
SP_CLIENT_SECRET = "<YOUR_SP_CLIENT_SECRET>"  # Use dbutils.secrets.get() in production

SCOPES = "sql iam.current-user:read catalog.tables:read iam.access-control:read"

# COMMAND ----------

# MAGIC %pip install --upgrade databricks-sdk

# COMMAND ----------

dbutils.library.restartPython()  # noqa: F821

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1: Get SP token (for app access)

# COMMAND ----------

# Re-read config after restartPython
APP_URL = "https://<YOUR_FASTAPI_APP_URL>"
WORKSPACE_URL = "https://<YOUR_WORKSPACE_URL>"
SP_CLIENT_ID = "<YOUR_SP_CLIENT_ID>"
SP_CLIENT_SECRET = "<YOUR_SP_CLIENT_SECRET>"
SCOPES = "sql iam.current-user:read catalog.tables:read iam.access-control:read"

import requests
import json
import time
from datetime import datetime

_sp_token = None
_sp_token_expiry = 0

def get_sp_token():
    """Get a valid SP token, refreshing if expired or about to expire (5 min buffer)."""
    global _sp_token, _sp_token_expiry
    if _sp_token and time.time() < _sp_token_expiry - 300:
        return _sp_token

    resp = requests.post(
        f"{WORKSPACE_URL}/oidc/v1/token",
        data={
            "grant_type": "client_credentials",
            "client_id": SP_CLIENT_ID,
            "client_secret": SP_CLIENT_SECRET,
            "scope": SCOPES,
        },
    )
    assert resp.status_code == 200, f"SP token failed: {resp.text}"
    data = resp.json()
    _sp_token = data["access_token"]
    _sp_token_expiry = time.time() + data.get("expires_in", 3600)
    print(f"SP token obtained (expires in {data.get('expires_in')}s)")
    return _sp_token

sp_token = get_sp_token()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 2: Get user token (identity of the job runner)

# COMMAND ----------

from databricks.sdk import WorkspaceClient

w = WorkspaceClient()

# Notebook session token — represents the interactive user or job owner
user_token = (
    dbutils.notebook.entry_point  # noqa: F821
    .getDbutils().notebook().getContext().apiToken().get()
)

# Identify who is running
try:
    me = w.current_user.me()
    runner = me.user_name
except Exception:
    runner = "unknown"

print(f"Job runner: {runner}")
print(f"User token prefix: {user_token[:20]}...")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 3: Create an item

# COMMAND ----------

def get_user_headers():
    """Fresh headers with both SP and user tokens."""
    token = (
        dbutils.notebook.entry_point  # noqa: F821
        .getDbutils().notebook().getContext().apiToken().get()
    )
    return {
        "Authorization": f"Bearer {get_sp_token()}",
        "X-User-Token": token,
    }

def get_sp_only_headers():
    """Fresh headers with SP token only."""
    return {"Authorization": f"Bearer {get_sp_token()}"}

timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# Create with user token
resp = requests.post(
    f"{APP_URL}/api/v1/lakebase/items",
    headers=get_user_headers(),
    json={
        "name": f"Scheduled job item ({timestamp})",
        "description": f"Created by scheduled job runner: {runner}",
        "price": 1.00,
        "quantity": 1,
    },
)

if resp.status_code == 201:
    item = resp.json().get("item", {})
    item_id = item.get("id")
    print(f"Created item {item_id}:")
    print(f"  created_by:  {item.get('created_by')}")
    print(f"  auth_mode:   {item.get('auth_mode')}")
    print(f"  description: {item.get('description')}")
else:
    print(f"Create failed [{resp.status_code}]: {resp.text}")
    item_id = None

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 4: Retrieve the item

# COMMAND ----------

if item_id:
    resp = requests.get(
        f"{APP_URL}/api/v1/lakebase/items/{item_id}",
        headers=get_user_headers(),
    )
    if resp.status_code == 200:
        item = resp.json().get("item", {})
        print(f"Retrieved item {item_id}:")
        print(json.dumps(item, indent=2))
    else:
        print(f"Get failed [{resp.status_code}]: {resp.text}")
else:
    print("Skipped -- no item was created")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 5: Also create with SP-only (for comparison)

# COMMAND ----------

resp_sp = requests.post(
    f"{APP_URL}/api/v1/lakebase/items",
    headers=get_sp_only_headers(),
    json={
        "name": f"Scheduled job SP item ({timestamp})",
        "description": f"Created by SP-only, job runner was: {runner}",
        "price": 1.00,
        "quantity": 1,
    },
)

if resp_sp.status_code == 201:
    sp_item = resp_sp.json().get("item", {})
    print(f"SP item {sp_item.get('id')}:")
    print(f"  created_by:  {sp_item.get('created_by')}")
    print(f"  auth_mode:   {sp_item.get('auth_mode')}")
else:
    print(f"SP create failed [{resp_sp.status_code}]: {resp_sp.text}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary
# MAGIC
# MAGIC | Field | User token item | SP-only item |
# MAGIC |---|---|---|
# MAGIC | `created_by` | Job runner's email | `service_principal` |
# MAGIC | `auth_mode` | `notebook_native_token` | `service_principal` |
# MAGIC
# MAGIC When scheduled as a job:
# MAGIC - **Run as user**: `created_by` shows that user's email
# MAGIC - **Run as SP**: user token might not be available; falls back to SP
