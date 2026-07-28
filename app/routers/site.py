"""Public homepage configuration and protected editor endpoints."""

from fastapi import APIRouter, Request

from ..security.permissions import require_admin_user_id
from ..site_config import SiteConfig, load_site_config, save_site_config


router = APIRouter()


@router.get("/site/config", response_model=SiteConfig)
async def get_site_config():
    return load_site_config()


@router.put("/admin/site/config", response_model=SiteConfig)
async def update_site_config(payload: SiteConfig, request: Request):
    require_admin_user_id(request)
    save_site_config(payload)
    return payload
