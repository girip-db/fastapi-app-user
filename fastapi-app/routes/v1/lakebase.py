"""Lakebase CRUD endpoints with user token support.

Follows the same token extraction pattern as trips.py:
  1. X-User-Token           (notebook native token)
  2. x-forwarded-access-token (browser via Databricks Apps proxy)
  3. Authorization: Bearer    (notebook PKCE / local machine)
  4. Falls back to service principal

When a user token is found, a user-scoped Lakebase session is created so
that PostgreSQL role-based access control applies to the calling user.
Otherwise, the SP connection pool is used.
"""

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select, text

from config.lakebase import get_sp_session, get_user_session, health_check, is_configured
from models.items import Base, Item

logger = logging.getLogger(__name__)
router = APIRouter(tags=["lakebase"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class ItemCreate(BaseModel):
    name: str
    description: str | None = None
    price: float = 0.0
    quantity: int = 0


class ItemUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    price: float | None = None
    quantity: int | None = None


class ItemResponse(BaseModel):
    id: int
    name: str
    description: str | None
    price: float
    quantity: int
    created_by: str | None
    updated_by: str | None
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Token extraction (shared with trips.py)
# ---------------------------------------------------------------------------

def _extract_user_token(request: Request) -> tuple[str | None, str]:
    """Extract a user-scoped Databricks token from the request.

    For Lakebase, only explicit user tokens are used for user-scoped connections.
    Authorization: Bearer is reserved for proxy/app auth (SP) and is NOT
    treated as a user token here — use X-User-Token for user identity.

    The proxy converts Authorization: Bearer into x-forwarded-access-token for
    ALL callers (browser users AND SPs). To distinguish, we require
    x-forwarded-email — which the proxy only sets for browser users.

    Priority: X-User-Token > x-forwarded-access-token (with email) > fallback to SP.
    """
    token = request.headers.get("x-user-token")
    if token:
        return token, "notebook_native_token"

    token = request.headers.get("x-forwarded-access-token")
    forwarded_email = request.headers.get("x-forwarded-email")
    if token and forwarded_email and "@" in forwarded_email:
        return token, "proxy_user_token"

    return None, "service_principal"


async def _get_session(request: Request):
    """Return (session, auth_mode, user_email). Uses user-scoped session when token is present."""
    user_token, auth_mode = _extract_user_token(request)
    if user_token:
        session, user_email = await get_user_session(user_token)
    else:
        session = await get_sp_session()
        user_email = None
    return session, auth_mode, user_email


def _resolve_caller(request: Request, auth_mode: str, user_email: str | None) -> str:
    """Determine the caller's identity for created_by/updated_by fields."""
    if user_email:
        return user_email
    return request.headers.get("x-forwarded-email") or auth_mode


def _item_to_dict(item: Item) -> dict:
    return {
        "id": item.id,
        "name": item.name,
        "description": item.description,
        "price": item.price,
        "quantity": item.quantity,
        "created_by": item.created_by,
        "updated_by": item.updated_by,
        "auth_mode": item.auth_mode,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


# ---------------------------------------------------------------------------
# Guard: return 503 when Lakebase is not configured
# ---------------------------------------------------------------------------

def _require_lakebase():
    if not is_configured():
        raise HTTPException(
            status_code=503,
            detail="Lakebase is not configured. Set LAKEBASE_INSTANCE_NAME.",
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/lakebase/debug-headers")
async def debug_headers(request: Request) -> Dict[str, Any]:
    """Show auth-related headers the app receives (for debugging proxy behaviour)."""
    return {
        "x-user-token": request.headers.get("x-user-token"),
        "x-forwarded-access-token": request.headers.get("x-forwarded-access-token", "")[:20] + "..." if request.headers.get("x-forwarded-access-token") else None,
        "x-forwarded-email": request.headers.get("x-forwarded-email"),
        "x-forwarded-preferred-username": request.headers.get("x-forwarded-preferred-username"),
        "authorization": request.headers.get("authorization", "")[:30] + "..." if request.headers.get("authorization") else None,
        "resolved_auth_mode": _extract_user_token(request)[1],
    }


@router.get("/lakebase/health")
async def lakebase_health() -> Dict[str, Any]:
    """Check Lakebase connectivity with diagnostic details."""
    configured = is_configured()
    if not configured:
        return {
            "configured": False,
            "connection_healthy": False,
            "status": "unhealthy",
            "error": "LAKEBASE_INSTANCE_NAME not set",
        }

    check = await health_check()
    return {
        "configured": True,
        "connection_healthy": check["healthy"],
        "engine_initialized": check["engine_initialized"],
        "status": "healthy" if check["healthy"] else "unhealthy",
        "error": check.get("error"),
    }


@router.post("/lakebase/items", status_code=201)
async def create_item(body: ItemCreate, request: Request) -> Dict[str, Any]:
    """Create a new item."""
    _require_lakebase()
    try:
        session, auth_mode, user_email = await _get_session(request)
    except Exception as e:
        logger.error(f"Failed to get Lakebase session: {e}")
        raise HTTPException(status_code=500, detail=f"Session failed: {e}")
    try:
        item = Item(
            name=body.name,
            description=body.description,
            price=body.price,
            quantity=body.quantity,
            created_by=_resolve_caller(request, auth_mode, user_email),
            auth_mode=auth_mode,
        )
        session.add(item)
        await session.commit()
        await session.refresh(item)

        return {"item": _item_to_dict(item), "auth_mode": auth_mode}
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        logger.error(f"Create item failed ({auth_mode}): {e}")
        raise HTTPException(status_code=500, detail=f"Create failed: {e}")
    finally:
        await session.close()


@router.get("/lakebase/items")
async def list_items(
    request: Request,
    page: int = 1,
    page_size: int = 20,
) -> Dict[str, Any]:
    """List items with pagination."""
    _require_lakebase()
    session, auth_mode, user_email = await _get_session(request)
    try:
        count_result = await session.execute(select(func.count(Item.id)))
        total = count_result.scalar() or 0

        offset = (page - 1) * page_size
        result = await session.execute(
            select(Item).order_by(Item.id).offset(offset).limit(page_size)
        )
        items = result.scalars().all()

        return {
            "items": [_item_to_dict(i) for i in items],
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": (total + page_size - 1) // page_size if total else 0,
            },
            "auth_mode": auth_mode,
        }
    except Exception as e:
        logger.error(f"List items failed ({auth_mode}): {e}")
        raise HTTPException(status_code=500, detail=f"List failed: {e}")
    finally:
        await session.close()


@router.get("/lakebase/items/{item_id}")
async def get_item(item_id: int, request: Request) -> Dict[str, Any]:
    """Get a single item by ID."""
    _require_lakebase()
    session, auth_mode, user_email = await _get_session(request)
    try:
        result = await session.execute(select(Item).where(Item.id == item_id))
        item = result.scalars().first()
        if not item:
            raise HTTPException(status_code=404, detail=f"Item {item_id} not found")
        return {"item": _item_to_dict(item), "auth_mode": auth_mode}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get item {item_id} failed ({auth_mode}): {e}")
        raise HTTPException(status_code=500, detail=f"Get failed: {e}")
    finally:
        await session.close()


@router.put("/lakebase/items/{item_id}")
async def update_item(item_id: int, body: ItemUpdate, request: Request) -> Dict[str, Any]:
    """Update an existing item (partial update)."""
    _require_lakebase()
    session, auth_mode, user_email = await _get_session(request)
    try:
        result = await session.execute(select(Item).where(Item.id == item_id))
        item = result.scalars().first()
        if not item:
            raise HTTPException(status_code=404, detail=f"Item {item_id} not found")

        update_data = body.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(item, field, value)

        item.updated_by = _resolve_caller(request, auth_mode, user_email)

        await session.commit()
        await session.refresh(item)
        return {"item": _item_to_dict(item), "auth_mode": auth_mode}
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        logger.error(f"Update item {item_id} failed ({auth_mode}): {e}")
        raise HTTPException(status_code=500, detail=f"Update failed: {e}")
    finally:
        await session.close()


@router.delete("/lakebase/items/{item_id}")
async def delete_item(item_id: int, request: Request) -> Dict[str, Any]:
    """Delete an item."""
    _require_lakebase()
    session, auth_mode, user_email = await _get_session(request)
    try:
        result = await session.execute(select(Item).where(Item.id == item_id))
        item = result.scalars().first()
        if not item:
            raise HTTPException(status_code=404, detail=f"Item {item_id} not found")

        await session.delete(item)
        await session.commit()
        return {"deleted": item_id, "auth_mode": auth_mode}
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        logger.error(f"Delete item {item_id} failed ({auth_mode}): {e}")
        raise HTTPException(status_code=500, detail=f"Delete failed: {e}")
    finally:
        await session.close()


@router.post("/lakebase/init-table", status_code=201)
async def init_table(request: Request) -> Dict[str, Any]:
    """Create the items table if it doesn't exist. Admin/setup endpoint."""
    _require_lakebase()
    from config.lakebase import engine as lb_engine

    if lb_engine is None:
        raise HTTPException(status_code=503, detail="Lakebase engine not initialized")

    try:
        async with lb_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        migrations = [
            "ALTER TABLE {schema}.items ADD COLUMN IF NOT EXISTS auth_mode VARCHAR(50)",
        ]
        schema = Item.__table_args__["schema"]
        async with lb_engine.begin() as conn:
            for stmt in migrations:
                await conn.execute(text(stmt.format(schema=schema)))

        return {"status": "ok", "message": "Items table created / migrated"}
    except Exception as e:
        logger.error(f"Init table failed: {e}")
        raise HTTPException(status_code=500, detail=f"Table init failed: {e}")
