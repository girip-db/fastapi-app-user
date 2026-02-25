import logging
from typing import Any, Dict, List, Tuple

import requests as http_requests
from databricks.sdk.core import Config
from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)
router = APIRouter()

_cfg = Config()
_host = _cfg.host


def get_user_info(request: Request) -> Dict[str, Any]:
    """Extract Databricks user identity from forwarded headers."""
    return {
        "user": request.headers.get("x-forwarded-user"),
        "email": request.headers.get("x-forwarded-email"),
        "preferred_username": request.headers.get("x-forwarded-preferred-username"),
        "is_authenticated": request.headers.get("x-forwarded-access-token") is not None,
    }


def _verify_and_fetch_groups(token: str) -> Tuple[str, List[str]]:
    """Call SCIM /Me with a token to get the verified email and groups.

    Works with both user OAuth tokens (x-forwarded-access-token) and
    notebook native tokens (X-User-Token). Returns (email, groups).
    """
    resp = http_requests.get(
        f"{_host}/api/2.0/preview/scim/v2/Me",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    email = data.get("userName", "")
    groups = [g["display"] for g in data.get("groups", []) if g.get("display")]
    return email, groups


@router.get("/me")
async def who_am_i(request: Request) -> Dict[str, Any]:
    """Return the authenticated user's identity as seen by the app."""
    return get_user_info(request)


@router.get("/me/groups")
async def my_groups(request: Request) -> Dict[str, Any]:
    """Return a user's identity and group memberships.

    Two authentication paths (checked in order):

    1. Browser (User Auth): x-forwarded-access-token present from proxy.
       Calls SCIM /Me with the user's token to get verified email + groups.

    2. Programmatic (X-User-Token header): Notebook sends its native token.
       App calls SCIM /Me to verify the caller's identity and get groups.
       No impersonation possible since the token proves who the caller is.
    """
    user_token = request.headers.get("x-forwarded-access-token")
    notebook_token = request.headers.get("x-user-token")

    if user_token:
        try:
            verified_email, groups = _verify_and_fetch_groups(user_token)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"SCIM /Me failed: {str(e)}")
        return {
            "user_info": get_user_info(request),
            "lookup_email": verified_email,
            "groups": groups,
            "group_count": len(groups),
            "scim_auth_method": "user_token",
            "identity_verified": True,
        }

    if notebook_token:
        try:
            verified_email, groups = _verify_and_fetch_groups(notebook_token)
        except Exception as e:
            raise HTTPException(
                status_code=401,
                detail=f"X-User-Token verification failed: {str(e)}",
            )
        return {
            "user_info": get_user_info(request),
            "lookup_email": verified_email,
            "groups": groups,
            "group_count": len(groups),
            "scim_auth_method": "verified_token",
            "identity_verified": True,
        }

    raise HTTPException(
        status_code=400,
        detail=(
            "No verifiable token found. Provide either: "
            "(1) x-forwarded-access-token (automatic in browser), or "
            "(2) X-User-Token header (notebook native token)."
        ),
    )
