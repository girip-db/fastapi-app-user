from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from routes import api_router

app = FastAPI(
    title="FastAPI on Databricks Apps",
    description="A FastAPI application deployed on Databricks Apps with User Authorization",
    version="1.0.0",
)

app.include_router(api_router)


@app.get("/")
async def root():
    return RedirectResponse(url="/api/v1/healthcheck")
