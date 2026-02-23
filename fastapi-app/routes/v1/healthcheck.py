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
