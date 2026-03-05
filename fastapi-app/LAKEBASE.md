# Lakebase Integration

This document explains how the FastAPI app connects to Lakebase PostgreSQL, including connection pooling, token refresh, and authentication for different callers.

## Architecture

```
                     Request arrives
                          │
                   _extract_user_token()
                          │
              ┌───── user token? ─────┐
              │                       │
             YES                      NO
              │                       │
   get_user_session(token)    get_sp_session()
              │                       │
   WorkspaceClient(token=...)    Uses pre-built
              │                  connection pool
   current_user.me() → email         │
              │                  SQLAlchemy event
   generate_database_credential()    injects current
              │                  SP password
   One-off asyncpg connection         │
   as the user's PG identity          │
              │                       │
              └───────────┬───────────┘
                          │
                   Lakebase PostgreSQL
                    (asyncpg + SSL)
```

## Connection Pooling (SP Path)

When no user token is present, the app uses a **connection pool** managed by SQLAlchemy. This is the default path for notebook calls without `X-User-Token` and scheduled jobs using SP-only auth.

### How it works

1. **At startup** (`init_engine()`): The app creates a `WorkspaceClient` as the service principal, calls `generate_database_credential()` to get a PostgreSQL password, and builds a SQLAlchemy async engine with a connection pool.

2. **Connection pool settings** (configurable via env vars):

   | Setting | Env Var | Default | Description |
   |---|---|---|---|
   | Pool size | `DB_POOL_SIZE` | 5 | Base number of persistent connections |
   | Max overflow | `DB_MAX_OVERFLOW` | 10 | Extra connections under load |
   | Pool timeout | `DB_POOL_TIMEOUT` | 10s | Max wait time for a connection |
   | Pool recycle | `DB_POOL_RECYCLE_INTERVAL` | 3600s | Recycle connections every hour |
   | Command timeout | `DB_COMMAND_TIMEOUT` | 30s | Query timeout |

3. **Password injection**: SQLAlchemy's `do_connect` event listener injects the current SP password into every new connection:

   ```python
   @event.listens_for(engine.sync_engine, "do_connect")
   def _provide_token(dialect, conn_rec, cargs, cparams):
       cparams["password"] = _postgres_password
   ```

   This means the pool automatically uses the latest refreshed password without rebuilding the engine.

## Token Refresh

Lakebase PostgreSQL credentials expire after **60 minutes**. The app runs a background task that refreshes the SP password every **50 minutes** (10-minute safety margin).

### Lifecycle

| Event | What happens |
|---|---|
| App startup | `init_engine()` generates initial credential, `start_token_refresh()` starts background task |
| Every 50 min | Background task calls `generate_database_credential()`, updates global `_postgres_password` |
| New connection | `do_connect` event injects latest password |
| App shutdown | `stop_token_refresh()` cancels the background task |

### What if refresh fails?

The background task catches exceptions and logs them. Existing pooled connections continue working until their credential expires. The task retries on the next 50-minute cycle.

## Authentication

### Token extraction priority (`_extract_user_token` in `lakebase.py`)

| Priority | Header | Condition | Auth mode |
|---|---|---|---|
| 1 | `X-User-Token` | Present | `notebook_native_token` |
| 2 | `x-forwarded-access-token` | Present **and** `x-forwarded-email` contains `@` | `proxy_user_token` |
| 3 | (none) | Fallback | `service_principal` |

**Why the `@` check?** The Databricks Apps proxy sets `x-forwarded-access-token` and `x-forwarded-email` for ALL authenticated callers. For browser users, `x-forwarded-email` is a real email (e.g., `user@company.com`). For SPs from notebooks, it's the SP's client ID (a UUID without `@`). Without this check, SP tokens would be sent to `generate_database_credential()`, which fails because the SP's scoped token lacks the `postgres` permission.

**Note:** Unlike `/trips`, the Lakebase endpoint does NOT treat `Authorization: Bearer` as a user token. The proxy strips this header and replaces it with `x-forwarded-access-token`, so it cannot reliably carry user identity from notebooks.

### SP path (no user token)

- Uses the **pooled connection** authenticated as the app's service principal
- PostgreSQL permissions are those of the SP
- `created_by` / `updated_by` fields show `service_principal`
- `auth_mode` column shows `service_principal`
- Best for: scheduled jobs (SP-only), service-to-service calls

### User path (token present)

1. Creates a `WorkspaceClient` scoped to the user's Databricks token (with `auth_type="pat"` to avoid conflicts with SP env vars)
2. Calls `current_user.me()` to get the user's email (used as PostgreSQL username and for `created_by`)
3. Calls `generate_database_credential()` with the user's identity → returns a user-scoped PostgreSQL password
4. Creates a **one-off asyncpg connection** with the user's credentials
5. PostgreSQL role-based access control enforces the user's permissions
6. `created_by` / `updated_by` fields show the user's email (resolved via `_resolve_caller()`)
7. `auth_mode` column shows the auth method used (e.g., `notebook_native_token`, `proxy_user_token`)
8. Session is closed after the request

**Note**: User-scoped connections are not pooled (pool_size=1, max_overflow=0) since each user gets a unique credential. This adds latency compared to the SP pool.

### Comparison with /trips (SQL Warehouse)

| | /trips (SQL Warehouse) | /lakebase (PostgreSQL) |
|---|---|---|
| Token usage | Passed directly to `sql.connect(access_token=...)` | Exchanged for a PostgreSQL password via `generate_database_credential()` |
| `Authorization: Bearer` | Treated as user token | NOT treated as user token (reserved for SP/proxy) |
| `x-forwarded-access-token` | Always used as user token | Only used when `x-forwarded-email` contains `@` |
| Protocol | Databricks SQL over HTTPS | PostgreSQL wire protocol over SSL |
| Connection pool | No (new connection per request) | Yes (SP path); No (user path) |
| Token refresh | Not needed (token per request) | Background task every 50 min (SP path) |

## Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/v1/lakebase/debug-headers` | GET | Show auth-related headers received by the app (for debugging proxy behavior) |
| `/api/v1/lakebase/health` | GET | Check Lakebase connectivity |
| `/api/v1/lakebase/init-table` | POST | Create the `items` table and run column migrations (admin) |
| `/api/v1/lakebase/items` | GET | List items (paginated) |
| `/api/v1/lakebase/items` | POST | Create an item |
| `/api/v1/lakebase/items/{id}` | GET | Get a single item |
| `/api/v1/lakebase/items/{id}` | PUT | Update an item |
| `/api/v1/lakebase/items/{id}` | DELETE | Delete an item |

Every mutating endpoint (`POST`, `PUT`, `DELETE`) returns the `auth_mode` so you can verify which authentication path was used.

## Configuration

### Required env vars

| Variable | Description |
|---|---|
| `LAKEBASE_HOST` | PostgreSQL hostname (from your DATABASE_URL, e.g., `ep-lucky-math-d2kk5aed.database.us-east-1.cloud.databricks.com`) |
| `LAKEBASE_DATABASE_NAME` | Database name (default: `databricks_postgres`) |

### Optional env vars

| Variable | Default | Description |
|---|---|---|
| `LAKEBASE_ENDPOINT` | Auto-discovered from host | Full endpoint resource path (e.g., `projects/.../branches/.../endpoints/primary`). Set explicitly if auto-discovery fails. |
| `LAKEBASE_SCHEMA` | `public` | PostgreSQL schema for the items table |
| `DB_POOL_SIZE` | `5` | Connection pool size |
| `DB_MAX_OVERFLOW` | `10` | Extra connections under load |
| `DB_POOL_TIMEOUT` | `10` | Max wait for a connection (seconds) |
| `DB_POOL_RECYCLE_INTERVAL` | `3600` | Recycle connections (seconds) |
| `DB_COMMAND_TIMEOUT` | `30` | Query timeout (seconds) |

### Graceful degradation

If `LAKEBASE_HOST` is not set:
- The app starts normally — all other endpoints (`/trips`, `/me`, etc.) work
- Lakebase endpoints return **503** with "Lakebase is not configured"
- No Lakebase connection is attempted at startup

## Database Table

The `items` table is created in the schema specified by `LAKEBASE_SCHEMA` (default: `public`):

| Column | Type | Description |
|---|---|---|
| `id` | SERIAL PK | Auto-increment primary key |
| `name` | VARCHAR(255) | Item name (required) |
| `description` | VARCHAR(1000) | Optional description |
| `price` | FLOAT | Price (default 0.0) |
| `quantity` | INTEGER | Stock quantity (default 0) |
| `created_by` | VARCHAR(255) | User email or `service_principal` |
| `updated_by` | VARCHAR(255) | User email or `service_principal` (set on update) |
| `auth_mode` | VARCHAR(50) | Authentication method used (`notebook_native_token`, `proxy_user_token`, `service_principal`) |
| `created_at` | TIMESTAMP | Auto-set on creation |
| `updated_at` | TIMESTAMP | Auto-set on update |

The `init-table` endpoint also runs column migrations (e.g., `ALTER TABLE ADD COLUMN IF NOT EXISTS auth_mode`) so it's safe to call on existing tables.

## References

- [Databricks Docs: Tutorial - Connect App to Lakebase Autoscaling](https://docs.databricks.com/aws/en/oltp/projects/tutorial-databricks-apps-autoscaling)
- [Databricks Docs: Connect external app to Lakebase](https://docs.databricks.com/aws/en/oltp/projects/external-apps-connect)
- [Databricks Apps Cookbook: Connect FastAPI to Lakebase](https://apps-cookbook.dev/docs/fastapi/getting_started/lakebase_connection/)
