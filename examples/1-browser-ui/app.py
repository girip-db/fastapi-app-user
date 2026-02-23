import logging
import os

import httpx
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

FASTAPI_APP_URL = os.environ.get(
    "FASTAPI_APP_URL",
    "<YOUR_FASTAPI_APP_URL>",
).rstrip("/")

app = FastAPI(title="React UI for Databricks App")

proxy_router = APIRouter(prefix="/api/proxy")


def _get_token(request: Request) -> str | None:
    """Extract the user's OAuth token forwarded by the Databricks Apps proxy."""
    return request.headers.get("x-forwarded-access-token")


def _get_user_headers(request: Request) -> dict:
    return {
        "user": request.headers.get("x-forwarded-user"),
        "email": request.headers.get("x-forwarded-email"),
        "preferred_username": request.headers.get("x-forwarded-preferred-username"),
    }


@proxy_router.get("/debug")
async def debug_headers(request: Request):
    """Show all forwarded headers -- use this to verify token is present."""
    return {
        "x-forwarded-access-token_present": request.headers.get("x-forwarded-access-token") is not None,
        "x-forwarded-user": request.headers.get("x-forwarded-user"),
        "x-forwarded-email": request.headers.get("x-forwarded-email"),
        "x-forwarded-preferred-username": request.headers.get("x-forwarded-preferred-username"),
        "fastapi_app_url": FASTAPI_APP_URL,
        "all_x_forwarded": {k: ("***" if "token" in k else v) for k, v in request.headers.items() if k.startswith("x-forwarded")},
    }


@proxy_router.get("/healthcheck")
async def proxy_healthcheck(request: Request):
    return await _proxy(request, "/api/v1/healthcheck")


@proxy_router.get("/me")
async def proxy_me(request: Request):
    token = _get_token(request)
    if not token:
        return {
            "user_info": _get_user_headers(request),
            "note": "No access token forwarded (user auth scopes may not be configured)",
        }
    return await _proxy(request, "/api/v1/me")


@proxy_router.get("/trips")
async def proxy_trips(request: Request):
    return await _proxy(request, "/api/v1/trips")


async def _proxy(request: Request, path: str):
    """Forward the request to the FastAPI app, passing the user's OAuth token."""
    token = _get_token(request)

    logger.info("=== Proxy debug for %s ===", path)
    logger.info("x-forwarded-access-token present: %s", token is not None)
    logger.info("x-forwarded-user: %s", request.headers.get("x-forwarded-user"))
    logger.info("x-forwarded-email: %s", request.headers.get("x-forwarded-email"))
    logger.info("FASTAPI_APP_URL: %s", FASTAPI_APP_URL)
    logger.info("All x-forwarded headers: %s", {k: v for k, v in request.headers.items() if k.startswith("x-forwarded")})

    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    target = f"{FASTAPI_APP_URL}{path}"
    logger.info("Proxying to: %s (with auth: %s)", target, "yes" if token else "no")

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(target, headers=headers)
            logger.info("Upstream response: %s", resp.status_code)
            return resp.json()
    except httpx.HTTPStatusError as e:
        logger.error("Upstream HTTP error: %s", e)
        raise HTTPException(status_code=e.response.status_code, detail=str(e))
    except Exception as e:
        logger.error("Proxy error: %s", e)
        raise HTTPException(status_code=502, detail=f"Proxy error: {str(e)}")


app.include_router(proxy_router)

app.mount("/", StaticFiles(directory="static", html=True), name="static")
