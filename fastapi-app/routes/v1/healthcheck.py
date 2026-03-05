from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Request

from .me import get_user_info

router = APIRouter()


@router.get("/healthcheck")
async def healthcheck(request: Request) -> Dict[str, Any]:
    """Return the API status and the authenticated caller's identity."""
    return {
        "status": "OK",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_info": get_user_info(request),
    }


@router.get("/debug/headers")
async def debug_headers(request: Request) -> Dict[str, Any]:
    """Return all incoming headers — use to verify proxy behavior."""
    auth_headers = {
        "x-forwarded-access-token": request.headers.get("x-forwarded-access-token", "NOT PRESENT"),
        "x-forwarded-user": request.headers.get("x-forwarded-user", "NOT PRESENT"),
        "x-forwarded-email": request.headers.get("x-forwarded-email", "NOT PRESENT"),
        "authorization": request.headers.get("authorization", "NOT PRESENT"),
        "x-user-token": request.headers.get("x-user-token", "NOT PRESENT"),
    }
    return {
        "auth_headers": auth_headers,
        "all_headers": dict(request.headers),
    }
