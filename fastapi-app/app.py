import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse

import config.lakebase as lakebase
from routes import api_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if lakebase.is_configured():
        try:
            lakebase.init_engine()
            await lakebase.start_token_refresh()
            logger.info("Lakebase connection initialized")
        except Exception as e:
            lakebase.startup_error = f"{type(e).__name__}: {e}"
            logger.warning(f"Lakebase init failed: {e}", exc_info=True)
    else:
        logger.info("Lakebase not configured — LAKEBASE_INSTANCE_NAME not set")

    yield

    await lakebase.stop_token_refresh()
    logger.info("Application shutdown complete")


app = FastAPI(
    title="FastAPI on Databricks Apps",
    description="A FastAPI application deployed on Databricks Apps with User Authorization",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(api_router)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled error on {request.method} {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": f"{type(exc).__name__}: {exc}"},
    )


@app.get("/")
async def root():
    return RedirectResponse(url="/api/v1/healthcheck")
