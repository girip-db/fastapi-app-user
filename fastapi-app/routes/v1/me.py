from typing import Any, Dict

from fastapi import APIRouter, Request

router = APIRouter()


def get_user_info(request: Request) -> Dict[str, Any]:
    """Extract Databricks user identity from forwarded headers."""
    return {
        "user": request.headers.get("x-forwarded-user"),
        "email": request.headers.get("x-forwarded-email"),
        "preferred_username": request.headers.get("x-forwarded-preferred-username"),
        "is_authenticated": request.headers.get("x-forwarded-access-token") is not None,
    }


@router.get("/me")
async def who_am_i(request: Request) -> Dict[str, Any]:
    """Return the authenticated user's identity as seen by the app."""
    return get_user_info(request)
