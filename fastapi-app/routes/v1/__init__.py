from fastapi import APIRouter

from .healthcheck import router as healthcheck_router
from .me import router as me_router
from .trips import router as trips_router

router = APIRouter()

router.include_router(healthcheck_router)
router.include_router(trips_router)
router.include_router(me_router)
