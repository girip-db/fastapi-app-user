import os
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List

from databricks import sql
from databricks.sdk.core import Config
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from .me import get_user_info

router = APIRouter()

DATABRICKS_WAREHOUSE_ID = os.environ.get("DATABRICKS_WAREHOUSE_ID")

databricks_cfg = Config()
SERVER_HOSTNAME = databricks_cfg.host.removeprefix("https://").rstrip("/")
HTTP_PATH = f"/sql/1.0/warehouses/{DATABRICKS_WAREHOUSE_ID}" if DATABRICKS_WAREHOUSE_ID else None

SQL_QUERY = os.environ.get(
    "SQL_QUERY",
    "SELECT * FROM samples.nyctaxi.trips LIMIT 5",
)


def make_serializable(value: Any) -> Any:
    """Convert SQL result values to JSON-safe types."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def row_to_dict(row, columns: List[str]) -> Dict[str, Any]:
    """Convert a Row object to a JSON-serializable dict."""
    if hasattr(row, "asDict"):
        raw = row.asDict()
    else:
        raw = dict(zip(columns, row))
    return {k: make_serializable(v) for k, v in raw.items()}


def run_query(sql_query: str, access_token: str | None = None) -> List[Dict[str, Any]]:
    """Execute SQL. Uses user token if provided, otherwise service principal."""
    if access_token:
        conn = sql.connect(
            server_hostname=SERVER_HOSTNAME,
            http_path=HTTP_PATH,
            access_token=access_token,
        )
    else:
        conn = sql.connect(
            server_hostname=SERVER_HOSTNAME,
            http_path=HTTP_PATH,
            credentials_provider=lambda: databricks_cfg.authenticate,
        )
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql_query)
            result = cursor.fetchall()
            columns = [col[0] for col in cursor.description]
            return [row_to_dict(row, columns) for row in result]
    finally:
        conn.close()


def _extract_user_token(request: Request) -> tuple[str | None, str]:
    """Extract a Databricks access token from the request.

    Checks these sources in priority order:
      1. x-forwarded-access-token  (browser via Databricks Apps proxy)
      2. Authorization: Bearer ...  (notebook PKCE / local machine OAuth)
      3. X-User-Token               (notebook native token)

    Returns (token, auth_mode) where token is None if no user token found.
    """
    token = request.headers.get("x-user-token")
    if token:
        return token, "notebook_native_token"

    token = request.headers.get("x-forwarded-access-token")
    if token:
        return token, "proxy_user_token"

    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip(), "bearer_token"

    return None, "service_principal"


@router.get("/trips")
def get_trips(request: Request) -> JSONResponse:
    """Query a table and return results."""
    user_token, auth_mode = _extract_user_token(request)

    if not DATABRICKS_WAREHOUSE_ID:
        raise HTTPException(
            status_code=500,
            detail="DATABRICKS_WAREHOUSE_ID environment variable is not set",
        )

    try:
        results = run_query(SQL_QUERY, access_token=user_token)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Query failed ({auth_mode}): {str(e)}",
        )

    return JSONResponse(
        content={
            "count": len(results),
            "results": results,
            "auth_mode": auth_mode,
            "user_info": get_user_info(request),
        }
    )
