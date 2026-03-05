"""Lakebase PostgreSQL connection with automatic token refresh.

Uses the Databricks SDK's w.postgres API (Lakebase Autoscaling) to generate
database credentials. Supports two connection modes:
  - SP (service principal): pooled connection for shared/default access
  - User-scoped: per-request connection using the caller's Databricks token

Required env vars:
  - LAKEBASE_HOST: PostgreSQL hostname (from your DATABASE_URL)
  - LAKEBASE_DATABASE_NAME: database name

Optional env vars:
  - LAKEBASE_ENDPOINT: full endpoint resource path for credential generation
    (e.g. projects/my-proj/branches/br-xxx/endpoints/ep-xxx)
    If not set, auto-discovered from the host.
"""

import asyncio
import logging
import os
import time

from databricks.sdk import WorkspaceClient
from sqlalchemy import URL, event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    create_async_engine,
)
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)

engine: AsyncEngine | None = None
AsyncSessionLocal: sessionmaker | None = None

_workspace_client: WorkspaceClient | None = None
_endpoint_resource: str | None = None
_postgres_password: str | None = None
_last_password_refresh: float = 0
_token_refresh_task: asyncio.Task | None = None
startup_error: str | None = None


def _discover_endpoint(w: WorkspaceClient, host: str) -> str:
    """Find the endpoint resource path by matching the host against all endpoints."""
    ep_prefix = host.split(".")[0]
    logger.info(f"Discovering endpoint for host prefix: {ep_prefix}")

    for project in w.postgres.list_projects():
        project_name = project.name
        for branch in w.postgres.list_branches(parent=project_name):
            branch_name = branch.name
            for endpoint in w.postgres.list_endpoints(parent=branch_name):
                ep_id = endpoint.name.split("/")[-1]
                if ep_id == ep_prefix:
                    logger.info(f"Found endpoint: {endpoint.name}")
                    return endpoint.name

    raise RuntimeError(
        f"Could not find endpoint matching host '{host}'. "
        f"Set LAKEBASE_ENDPOINT explicitly with the full resource path."
    )


def _generate_credential(w: WorkspaceClient, endpoint: str) -> str:
    """Generate a PostgreSQL OAuth credential using the postgres API."""
    cred = w.postgres.generate_database_credential(endpoint=endpoint)
    return cred.token


async def _refresh_token_background():
    """Refresh the SP database credential every 50 minutes."""
    global _postgres_password, _last_password_refresh
    while True:
        try:
            await asyncio.sleep(50 * 60)
            logger.info("Refreshing Lakebase PostgreSQL OAuth token")
            _postgres_password = _generate_credential(_workspace_client, _endpoint_resource)
            _last_password_refresh = time.time()
            logger.info("Lakebase token refreshed successfully")
        except Exception as e:
            logger.error(f"Lakebase token refresh failed: {e}")


def init_engine():
    """Create the async SQLAlchemy engine using SP credentials."""
    global engine, AsyncSessionLocal, _workspace_client, _endpoint_resource
    global _postgres_password, _last_password_refresh

    host = os.getenv("LAKEBASE_HOST")
    if not host:
        raise RuntimeError("LAKEBASE_HOST is required (PostgreSQL hostname from your DATABASE_URL)")

    _workspace_client = WorkspaceClient()

    # Discover or use explicit endpoint resource path
    _endpoint_resource = os.getenv("LAKEBASE_ENDPOINT")
    if not _endpoint_resource:
        _endpoint_resource = _discover_endpoint(_workspace_client, host)

    # Generate initial credential
    _postgres_password = _generate_credential(_workspace_client, _endpoint_resource)
    _last_password_refresh = time.time()

    database_name = os.getenv("LAKEBASE_DATABASE_NAME", "databricks_postgres")
    username = (
        os.getenv("DATABRICKS_CLIENT_ID")
        or _workspace_client.current_user.me().user_name
    )

    url = URL.create(
        drivername="postgresql+asyncpg",
        username=username,
        password="",
        host=host,
        port=int(os.getenv("DATABRICKS_DATABASE_PORT", "5432")),
        database=database_name,
    )

    engine = create_async_engine(
        url,
        pool_pre_ping=False,
        echo=False,
        pool_size=int(os.getenv("DB_POOL_SIZE", "5")),
        max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "10")),
        pool_timeout=int(os.getenv("DB_POOL_TIMEOUT", "10")),
        pool_recycle=int(os.getenv("DB_POOL_RECYCLE_INTERVAL", "3600")),
        connect_args={
            "command_timeout": int(os.getenv("DB_COMMAND_TIMEOUT", "30")),
            "server_settings": {"application_name": "fastapi_lakebase_app"},
            "ssl": "require",
        },
    )

    @event.listens_for(engine.sync_engine, "do_connect")
    def _provide_token(dialect, conn_rec, cargs, cparams):
        cparams["password"] = _postgres_password

    AsyncSessionLocal = sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False,
    )
    logger.info(f"Lakebase engine initialized: host={host}, db={database_name}, endpoint={_endpoint_resource}")


async def start_token_refresh():
    global _token_refresh_task
    if _token_refresh_task is None or _token_refresh_task.done():
        _token_refresh_task = asyncio.create_task(_refresh_token_background())
        logger.info("Lakebase token refresh task started")


async def stop_token_refresh():
    global _token_refresh_task
    if _token_refresh_task and not _token_refresh_task.done():
        _token_refresh_task.cancel()
        try:
            await _token_refresh_task
        except asyncio.CancelledError:
            pass
        logger.info("Lakebase token refresh task stopped")


async def get_sp_session() -> AsyncSession:
    """Get a session using the SP connection pool."""
    if AsyncSessionLocal is None:
        raise RuntimeError("Lakebase engine not initialized; call init_engine() first")
    return AsyncSessionLocal()


async def get_user_session(user_token: str) -> tuple[AsyncSession, str]:
    """Create a one-off session using the caller's Databricks token.

    Returns (session, username) so the caller knows who the user is.
    """
    host = os.getenv("LAKEBASE_HOST")
    database_name = os.getenv("LAKEBASE_DATABASE_NAME", "databricks_postgres")

    w = WorkspaceClient(
        token=user_token,
        host=_workspace_client.config.host,
        auth_type="pat",
    )
    username = w.current_user.me().user_name
    password = _generate_credential(w, _endpoint_resource)

    url = URL.create(
        drivername="postgresql+asyncpg",
        username=username,
        password=password,
        host=host,
        port=int(os.getenv("DATABRICKS_DATABASE_PORT", "5432")),
        database=database_name,
    )

    user_engine = create_async_engine(
        url,
        pool_size=1,
        max_overflow=0,
        connect_args={
            "command_timeout": int(os.getenv("DB_COMMAND_TIMEOUT", "30")),
            "server_settings": {"application_name": "fastapi_lakebase_user"},
            "ssl": "require",
        },
    )

    session_factory = sessionmaker(
        bind=user_engine, class_=AsyncSession, expire_on_commit=False,
    )
    return session_factory(), username


def is_configured() -> bool:
    """Check whether Lakebase env vars are set."""
    return bool(os.getenv("LAKEBASE_HOST"))


async def health_check() -> dict:
    """Returns {"healthy": bool, "error": str | None, "engine_initialized": bool}."""
    if engine is None:
        error = startup_error or "Engine not initialized — init_engine() may have failed at startup"
        return {"healthy": False, "error": error, "engine_initialized": False}
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"healthy": True, "error": None, "engine_initialized": True}
    except Exception as e:
        logger.error(f"Lakebase health check failed: {e}")
        return {"healthy": False, "error": str(e), "engine_initialized": True}
