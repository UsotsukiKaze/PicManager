from fastapi import APIRouter

from .characters import router as characters_router
from .feature_tags import router as feature_tags_router
from .emojis import router as emojis_router
from .groups import router as groups_router
from .images import router as images_router
from .rankings import router as rankings_router
from .uploads import router as uploads_router

router = APIRouter()
router.include_router(groups_router)
router.include_router(characters_router)
router.include_router(feature_tags_router)
router.include_router(emojis_router)
router.include_router(images_router)
router.include_router(rankings_router)
router.include_router(uploads_router)
