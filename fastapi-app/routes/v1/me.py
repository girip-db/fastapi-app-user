import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import requests as http_requests
from databricks.sdk.core import Config
from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)
router = APIRouter()

_cfg = Config()
_host = _cfg.host

_SP_CLIENT_ID = os.environ.get("DATABRICKS_CLIENT_ID", "")
_SP_CLIENT_SECRET = os.environ.get("DATABRICKS_CLIENT_SECRET", "")


def _get_sp_token(scope: str = "scim") -> str:
    """Get an SP OAuth token with explicit scopes via client_credentials flow."""
    resp = http_requests.post(
        f"{_host}/oidc/v1/token",
        data={
            "grant_type": "client_credentials",
            "client_id": _SP_CLIENT_ID,
            "client_secret": _SP_CLIENT_SECRET,
            "scope": scope,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def get_user_info(request: Request) -> Dict[str, Any]:
    """Extract Databricks user identity from forwarded headers."""
    return {
        "user": request.headers.get("x-forwarded-user"),
        "email": request.headers.get("x-forwarded-email"),
        "preferred_username": request.headers.get("x-forwarded-preferred-username"),
        "is_authenticated": request.headers.get("x-forwarded-access-token") is not None,
    }


def _fetch_groups_with_user_token(token: str) -> List[str]:
    """Call SCIM /Me endpoint with the user's bearer token."""
    resp = http_requests.get(
        f"{_host}/api/2.0/preview/scim/v2/Me",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    return [g["display"] for g in data.get("groups", []) if g.get("display")]


def _fetch_groups_with_sp(email: str) -> List[str]:
    """Look up groups using an SP token with explicit 'scim' scope.

    Gets a fresh SP token via client_credentials with the scim scope,
    then calls SCIM /Users to look up the target user's groups.
    SP must be a workspace admin for groups to be returned.
    """
    sp_token = _get_sp_token("scim")
    resp = http_requests.get(
        f"{_host}/api/2.0/preview/scim/v2/Users",
        headers={"Authorization": f"Bearer {sp_token}"},
        params={"filter": f'userName eq "{email}"'},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    groups = []
    for user_resource in data.get("Resources", []):
        for g in user_resource.get("groups", []):
            if g.get("display"):
                groups.append(g["display"])
        break
    return groups


def get_user_groups(email: str, token: Optional[str] = None) -> Tuple[List[str], str]:
    """Look up a user's group memberships via SCIM API.

    Uses the user's forwarded token when available (browser flow),
    falls back to SP credentials otherwise.
    """
    auth_method = "user_token" if token else "service_principal"
    try:
        if token:
            groups = _fetch_groups_with_user_token(token)
        else:
            groups = _fetch_groups_with_sp(email)
    except Exception:
        logger.exception("SCIM group lookup failed for %s (via %s)", email, auth_method)
        raise

    return (groups, auth_method)


@router.get("/me")
async def who_am_i(request: Request) -> Dict[str, Any]:
    """Return the authenticated user's identity as seen by the app."""
    return get_user_info(request)


@router.get("/me/groups")
async def my_groups(request: Request) -> Dict[str, Any]:
    """Return a user's identity and group memberships.

    Browser (User Auth): uses x-forwarded-email and x-forwarded-access-token
      from the proxy. No extra headers needed.

    Programmatic (SP Auth): requires X-User-Email header to identify the
      target user. Uses SP credentials with SCIM /Users for group lookup.
    """
    user_token = request.headers.get("x-forwarded-access-token")

    if user_token:
        lookup_email = request.headers.get("x-forwarded-email")
    else:
        lookup_email = request.headers.get("x-user-email")
        if not lookup_email:
            raise HTTPException(
                status_code=400,
                detail="X-User-Email header is required when calling with SP credentials.",
            )

    try:
        groups, auth_method = get_user_groups(lookup_email, token=user_token)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch groups for {lookup_email}: {str(e)}",
        )

    return {
        "user_info": get_user_info(request),
        "lookup_email": lookup_email,
        "groups": groups,
        "group_count": len(groups),
        "scim_auth_method": auth_method,
    }
