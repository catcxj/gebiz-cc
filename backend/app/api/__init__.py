from fastapi import APIRouter

from .opportunities import router as opportunities_router
from .notifications import router as notifications_router
from .admin import router as admin_router

api_router = APIRouter(prefix="/api")
api_router.include_router(opportunities_router)
api_router.include_router(notifications_router)
api_router.include_router(admin_router)
