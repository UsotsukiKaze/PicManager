from fastapi import APIRouter

from .reviews import router as reviews_router
from .stats import router as stats_router
from .users import router as users_router

router = APIRouter()
router.include_router(reviews_router)
router.include_router(users_router)
router.include_router(stats_router)