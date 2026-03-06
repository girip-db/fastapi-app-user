# Databricks notebook source
# MAGIC %md
# MAGIC # Lakebase CRUD: Calling Lakebase Endpoints from a Notebook
# MAGIC
# MAGIC This notebook demonstrates how to call the FastAPI app's Lakebase CRUD
# MAGIC endpoints from a Databricks notebook using both **SP token** and **user token**.
# MAGIC
# MAGIC ## Authentication flow
# MAGIC
# MAGIC | Header | Purpose |
# MAGIC |---|---|
# MAGIC | `Authorization: Bearer {sp_token}` | SP authenticates with the app |
# MAGIC | `X-User-Token: {user_token}` | User identity for Lakebase connection |
# MAGIC
# MAGIC The app uses the user token to call `generate_database_credential()`,
# MAGIC which returns a PostgreSQL password scoped to the user. All CRUD
# MAGIC operations then run under the user's PostgreSQL permissions.

# COMMAND ----------

# MAGIC %pip install --upgrade databricks-sdk

# COMMAND ----------

dbutils.library.restartPython()  # noqa: F821

# COMMAND ----------

# MAGIC %md
# MAGIC ## Configuration
# MAGIC
# MAGIC Update these values for your environment.

# COMMAND ----------

APP_URL = "https://<YOUR_FASTAPI_APP_URL>"
WORKSPACE_URL = "https://<YOUR_WORKSPACE_URL>"

SP_CLIENT_ID = "<YOUR_SP_CLIENT_ID>"
SP_CLIENT_SECRET = "<YOUR_SP_CLIENT_SECRET>"  # Use dbutils.secrets.get() in production

SCOPES = "sql iam.current-user:read catalog.tables:read iam.access-control:read"

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1: Get SP OAuth Token

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
    print(f"Expires in: {token_data.get('expires_in')}s")
    print(f"Token prefix: {sp_token[:20]}...")
else:
    print(f"ERROR: {token_resp.text}")
    sp_token = None

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 2: Get the user token
# MAGIC
# MAGIC The notebook's native token represents the interactive user.
# MAGIC The app will use this to create a user-scoped Lakebase connection.

# COMMAND ----------

assert sp_token, "No SP token -- fix Step 1 first"

user_token = (
    dbutils.notebook.entry_point  # noqa: F821
    .getDbutils().notebook().getContext().apiToken().get()
)

headers = {
    "Authorization": f"Bearer {sp_token}",
    "X-User-Token": user_token,
}

print(f"User token prefix: {user_token[:20]}...")
print("Headers configured for user-scoped Lakebase access")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 3: Check Lakebase health

# COMMAND ----------

resp = requests.get(f"{APP_URL}/api/v1/lakebase/health", headers=headers)
print(f"Health [{resp.status_code}]:")
print(json.dumps(resp.json(), indent=2))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 4: Initialize the items table
# MAGIC
# MAGIC Creates the `items` table in Lakebase if it doesn't exist.
# MAGIC Only needed once -- safe to run multiple times.

# COMMAND ----------

resp = requests.post(f"{APP_URL}/api/v1/lakebase/init-table", headers=headers)
print(f"Init table [{resp.status_code}]:")
print(json.dumps(resp.json(), indent=2))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 5: CREATE -- Add items

# COMMAND ----------

items_to_create = [
    {"name": "Laptop", "description": "16-inch MacBook Pro", "price": 2499.99, "quantity": 10},
    {"name": "Monitor", "description": "4K 27-inch display", "price": 599.99, "quantity": 25},
    {"name": "Keyboard", "description": "Mechanical wireless", "price": 149.99, "quantity": 50},
]

created_ids = []
for item_data in items_to_create:
    resp = requests.post(
        f"{APP_URL}/api/v1/lakebase/items",
        headers=headers,
        json=item_data,
    )
    result = resp.json()
    item_id = result.get("item", {}).get("id")
    created_ids.append(item_id)
    item = result.get("item", {})
    print(f"Created [{resp.status_code}]: id={item_id}, name={item_data['name']}, created_by={item.get('created_by')}, auth_mode={item.get('auth_mode')}")

print(f"\nCreated item IDs: {created_ids}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 6: READ -- List all items

# COMMAND ----------

resp = requests.get(
    f"{APP_URL}/api/v1/lakebase/items",
    headers=headers,
    params={"page": 1, "page_size": 10},
)
result = resp.json()
print(f"List items [{resp.status_code}] (auth_mode: {result.get('auth_mode')}):\n")
print(f"Total: {result['pagination']['total']}")
for item in result.get("items", []):
    print(f"  id={item['id']}  name={item['name']}  price={item['price']}  qty={item['quantity']}  created_by={item['created_by']}  auth_mode={item.get('auth_mode')}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 7: READ -- Get a single item

# COMMAND ----------

if created_ids and created_ids[0]:
    resp = requests.get(f"{APP_URL}/api/v1/lakebase/items/{created_ids[0]}", headers=headers)
    print(f"Get item [{resp.status_code}]:")
    print(json.dumps(resp.json(), indent=2))
else:
    print("No items created -- skip")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 8: UPDATE -- Change an item

# COMMAND ----------

if created_ids and created_ids[0]:
    resp = requests.put(
        f"{APP_URL}/api/v1/lakebase/items/{created_ids[0]}",
        headers=headers,
        json={"price": 2299.99, "description": "16-inch MacBook Pro (refurbished)"},
    )
    result = resp.json()
    print(f"Update [{resp.status_code}] (auth_mode: {result.get('auth_mode')}):")
    item = result.get("item", {})
    print(f"  price: {item.get('price')}")
    print(f"  description: {item.get('description')}")
    print(f"  updated_by: {item.get('updated_by')}")
    print(f"  updated_at: {item.get('updated_at')}")
else:
    print("No items created -- skip")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 9: DELETE -- Remove an item

# COMMAND ----------

if created_ids and created_ids[-1]:
    item_to_delete = created_ids[-1]
    resp = requests.delete(f"{APP_URL}/api/v1/lakebase/items/{item_to_delete}", headers=headers)
    print(f"Delete [{resp.status_code}]: {resp.json()}")

    # Verify it's gone
    resp = requests.get(f"{APP_URL}/api/v1/lakebase/items/{item_to_delete}", headers=headers)
    print(f"Verify deleted [{resp.status_code}]: {resp.json()}")
else:
    print("No items created -- skip")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 10: Compare SP vs User auth
# MAGIC
# MAGIC Call the same endpoint **without** `X-User-Token` to see it fall back
# MAGIC to the service principal connection pool.

# COMMAND ----------

sp_only_headers = {"Authorization": f"Bearer {sp_token}"}

# Create one item as SP for comparison
resp_sp_create = requests.post(
    f"{APP_URL}/api/v1/lakebase/items",
    headers=sp_only_headers,
    json={"name": "SP-created item", "price": 9.99, "quantity": 1},
)
if resp_sp_create.status_code == 201:
    sp_item = resp_sp_create.json().get("item", {})
    print(f"SP create [{resp_sp_create.status_code}]: created_by={sp_item.get('created_by')}, auth_mode={sp_item.get('auth_mode')}")
else:
    print(f"SP create [{resp_sp_create.status_code}]: {resp_sp_create.text}")

resp_user = requests.get(f"{APP_URL}/api/v1/lakebase/items", headers=headers, params={"page_size": 5})
resp_sp = requests.get(f"{APP_URL}/api/v1/lakebase/items", headers=sp_only_headers, params={"page_size": 5})

user_items = resp_user.json().get("items", [])
sp_items = resp_sp.json().get("items", [])

print("=== With user token ===")
print(f"  auth_mode: {resp_user.json().get('auth_mode')}")
if user_items:
    print(f"  created_by: {user_items[0].get('created_by')}")
    print(f"  item auth_mode: {user_items[0].get('auth_mode')}")

print("\n=== Without user token (SP only) ===")
if resp_sp.status_code == 200:
    print(f"  auth_mode: {resp_sp.json().get('auth_mode')}")
    if sp_items:
        print(f"  created_by: {sp_items[0].get('created_by')}")
        print(f"  item auth_mode: {sp_items[0].get('auth_mode')}")
else:
    print(f"  [{resp_sp.status_code}]: {resp_sp.text}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary
# MAGIC
# MAGIC | Operation | Endpoint | Method | Auth |
# MAGIC |---|---|---|---|
# MAGIC | Health check | `/api/v1/lakebase/health` | GET | Any |
# MAGIC | Init table | `/api/v1/lakebase/init-table` | POST | Any |
# MAGIC | Create item | `/api/v1/lakebase/items` | POST | User or SP |
# MAGIC | List items | `/api/v1/lakebase/items` | GET | User or SP |
# MAGIC | Get item | `/api/v1/lakebase/items/{id}` | GET | User or SP |
# MAGIC | Update item | `/api/v1/lakebase/items/{id}` | PUT | User or SP |
# MAGIC | Delete item | `/api/v1/lakebase/items/{id}` | DELETE | User or SP |
# MAGIC
# MAGIC **Token flow**: SP token authenticates with the app → user token is exchanged
# MAGIC for a PostgreSQL credential via `generate_database_credential()` → CRUD
# MAGIC operations run under the user's PostgreSQL permissions.
# MAGIC
# MAGIC **`created_by` / `updated_by`** fields record who performed each operation.
