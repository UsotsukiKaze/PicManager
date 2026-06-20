from fastapi import APIRouter

from .profile import router as profile_router
from .sessions import router as sessions_router

router = APIRouter()
router.include_router(sessions_router)
router.include_router(profile_router)