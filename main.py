from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from contextlib import asynccontextmanager
from pathlib import Path
import os
import time
import uvicorn
from app.database import init_database, create_db_snapshot
from app.database import get_db_context
from app.config import settings
from app.logger import log_http_request, log_info, log_success
from app.models import Image as ImageModel
from app.services import ImageService
from app.routers.admin_routes import router as admin_router
from app.routers.auth_routes import router as auth_router
from app.routers.integrations.bot import router as bot_router
from app.routers.integrations.sso import router as sso_router
from app.routers.public import router as public_router
from app.routers.system import router as system_router
from app.routers.auth import get_session
from app.security.lan_debug import configured_lan_base_url, configured_lan_hosts, exact_hosts
from app.security.permissions import require_admin_user_id

UI_ASSET_VERSION = str(int(time.time()))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时执行
    log_info("正在初始化数据库...")
    init_database()
    log_success("数据库初始化完成!")
    yield
    # 关闭时执行（如果需要的话）
    create_db_snapshot()

# 创建FastAPI应用
app = FastAPI(
    title="PicManager",
    description="图片编号管理系统 - 基于标签的图片元数据管理工具",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.ENABLE_API_DOCS else None,
    redoc_url="/redoc" if settings.ENABLE_API_DOCS else None,
    openapi_url="/openapi.json" if settings.ENABLE_API_DOCS else None,
)

def _cors_origins() -> list[str]:
    return [origin.strip() for origin in settings.CORS_ALLOW_ORIGINS.split(",") if origin.strip()]


def _trusted_hosts() -> list[str]:
    hosts = exact_hosts(settings.TRUSTED_HOSTS, setting_name="TRUSTED_HOSTS")
    if settings.LAN_DEBUG_ENABLED:
        for host in configured_lan_hosts(settings):
            if host not in hosts:
                hosts.append(host)
        # Validate the optional fixed LAN login origin during application startup.
        configured_lan_base_url(settings)
    return hosts


def _is_ui_cache_sensitive_path(path: str) -> bool:
    if path in {"/", "/login", "/profile"}:
        return True
    if not path.startswith("/static/"):
        return False
    return Path(path).suffix.lower() in {".html", ".css", ".js", ".mjs"}


def _apply_no_store_headers(response) -> None:
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Cloudflare-CDN-Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    response.headers["X-PicManager-Asset-Version"] = UI_ASSET_VERSION


def _apply_production_cache_headers(request: Request, response) -> None:
    """Apply cache policy without ever varying the app shell by authentication state."""
    if request.method not in {"GET", "HEAD"} or response.status_code >= 400:
        return

    path = request.url.path
    if path in {"/login", "/profile"}:
        _apply_no_store_headers(response)
        return

    if path in {"/", "/home"}:
        # Browsers revalidate the HTML shell, while Cloudflare may briefly serve
        # the same authentication-independent shell to every visitor.
        response.headers["Cache-Control"] = "no-cache"
        response.headers["Cloudflare-CDN-Cache-Control"] = (
            "public, max-age=60, stale-while-revalidate=30, stale-if-error=86400"
        )
        return

    if path.startswith("/static/"):
        if request.query_params.get("v"):
            policy = "public, max-age=31536000, immutable"
        else:
            policy = "public, max-age=14400"
        response.headers["Cache-Control"] = policy
        response.headers["Cloudflare-CDN-Cache-Control"] = policy


def _safe_resource_file(base_path: str, filename: str) -> Path:
    if "/" in filename or "\\" in filename or "\x00" in filename:
        raise FileNotFoundError
    root = Path(base_path).resolve()
    path = (root / filename).resolve()
    path.relative_to(root)
    if not path.is_file():
        raise FileNotFoundError
    return path


def _safe_store_resource_path(resource_path: str) -> Path:
    if "\x00" in resource_path:
        raise FileNotFoundError
    normalized = resource_path.replace("\\", "/").lstrip("/")
    if normalized.startswith("resource/store/"):
        normalized = normalized.removeprefix("resource/store/")
    if normalized.startswith("store/"):
        normalized = normalized.removeprefix("store/")
    if not normalized or normalized.startswith("../") or "/../" in normalized:
        raise FileNotFoundError

    root = Path(settings.STORE_PATH).resolve()
    path = (root / normalized).resolve()
    path.relative_to(root)
    if not path.is_file():
        raise FileNotFoundError
    return path


def _thumbnail_path(resource_path: str) -> Path:
    thumb_root = Path(settings.THUMB_PATH).resolve()
    thumb_root.mkdir(parents=True, exist_ok=True)

    normalized = resource_path.replace("\\", "/").lstrip("/")
    image_id = Path(normalized).stem
    thumb = (thumb_root / f"{image_id}.webp").resolve()
    thumb.relative_to(thumb_root)
    if thumb.is_file():
        return thumb
    raise FileNotFoundError


@app.middleware("http")
async def log_requests(request: Request, call_next):
    return await log_http_request(request, call_next)


@app.middleware("http")
async def prevent_stale_ui_cache(request: Request, call_next):
    response = await call_next(request)
    if settings.DEBUG and _is_ui_cache_sensitive_path(request.url.path):
        _apply_no_store_headers(response)
    elif not settings.DEBUG:
        _apply_production_cache_headers(request, response)
    return response


# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=_trusted_hosts())
app.add_middleware(GZipMiddleware, minimum_size=1024)

# 挂载静态文件
app.mount("/static", StaticFiles(directory=os.path.join(settings.BASE_DIR, "static")), name="static")

# 确保resource目录存在
os.makedirs(settings.STORE_PATH, exist_ok=True)
os.makedirs(settings.TEMP_PATH, exist_ok=True)
os.makedirs(settings.PENDING_PATH, exist_ok=True)  # 待审核文件目录
os.makedirs(settings.THUMB_PATH, exist_ok=True)
os.makedirs(settings.EMOJI_PATH, exist_ok=True)
os.makedirs(settings.AVATAR_PATH, exist_ok=True)

# 提供resource目录的静态文件服务
@app.get("/resource/temp/{filename}")
async def protected_temp_file(filename: str, request: Request):
    """Serve temp files only to admins."""
    require_admin_user_id(request)
    try:
        return FileResponse(_safe_resource_file(settings.TEMP_PATH, filename))
    except Exception:
        return FileResponse(os.path.join(settings.BASE_DIR, "static", "images", "placeholder.png"))


@app.get("/resource/pending/{filename}")
async def protected_pending_file(filename: str, request: Request):
    """Serve pending files only to admins."""
    require_admin_user_id(request)
    try:
        return FileResponse(_safe_resource_file(settings.PENDING_PATH, filename))
    except Exception:
        return FileResponse(os.path.join(settings.BASE_DIR, "static", "images", "placeholder.png"))


@app.get("/resource/thumbs/{resource_path:path}")
async def thumbnail_file(resource_path: str):
    """Serve thumbnails only; never fall back to a potentially large original."""
    try:
        response = FileResponse(_thumbnail_path(resource_path), media_type="image/webp")
        response.headers["Cache-Control"] = "public, max-age=604800, immutable"
        return response
    except Exception:
        response = FileResponse(os.path.join(settings.BASE_DIR, "static", "images", "placeholder.png"))
        # Missing thumbnails may be generated by maintenance shortly afterwards.
        response.headers["Cache-Control"] = "public, max-age=60"
        response.headers["X-PicManager-Thumbnail"] = "missing"
        return response


@app.get("/resource/originals/{image_id}")
def original_image(image_id: str, request: Request):
    """Serve a published original by id after the user explicitly opens it."""
    with get_db_context() as db:
        session_id = request.cookies.get("session_id")
        if not session_id:
            raise HTTPException(status_code=401, detail="Login required")
        if not get_session(db, session_id):
            raise HTTPException(status_code=401, detail="Login required")
        image = db.query(ImageModel).filter(
            ImageModel.image_id == image_id,
            ImageModel.file_status == ImageService.AVAILABLE,
        ).first()
        if not image:
            raise HTTPException(status_code=404, detail="Image not found")

        try:
            path = _safe_store_resource_path(image.file_path)
        except Exception as exc:
            ImageService.mark_file_status(db, image, exists=False)
            db.commit()
            raise HTTPException(status_code=404, detail="Image not found") from exc

        response = FileResponse(path)
        # This endpoint is authenticated. Never allow a shared intermediary to
        # cache an original and replay it to a request without a valid session.
        response.headers["Cache-Control"] = "private, max-age=3600"
        response.headers["Cloudflare-CDN-Cache-Control"] = "no-store"
        return response


# Originals are intentionally not mounted as static files. They are served by
# the id-based authenticated routes above so restricted content has no direct
# `/resource/store/...` bypass.
app.mount("/resource/emojis", StaticFiles(directory=settings.EMOJI_PATH), name="resource_emojis")
app.mount("/resource/avatars", StaticFiles(directory=settings.AVATAR_PATH), name="resource_avatars")

# 注册API路由
app.include_router(public_router, prefix="/api")
app.include_router(system_router, prefix="/api/system")
app.include_router(bot_router, prefix="/api/bot")
app.include_router(sso_router, prefix="/api/sso")
app.include_router(admin_router, prefix="/api/admin")
app.include_router(auth_router, prefix="/auth")
app.include_router(admin_router, prefix="/admin")
@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Serve the personal homepage on its domains, otherwise PicManager."""
    homepage_hosts = {
        host.strip().lower()
        for host in settings.HOMEPAGE_HOSTS.split(",")
        if host.strip()
    }
    request_host = (request.url.hostname or "").lower()
    if request_host in homepage_hosts:
        return FileResponse(os.path.join(settings.BASE_DIR, "static", "homepage", "index.html"))
    return FileResponse(os.path.join(settings.BASE_DIR, "static", "index.html"))


@app.get("/home", response_class=HTMLResponse)
async def homepage_preview():
    """Direct preview route for the personal homepage."""
    return FileResponse(os.path.join(settings.BASE_DIR, "static", "homepage", "index.html"))


@app.get("/login", response_class=HTMLResponse)
async def login_page():
    """登录页路由"""
    return FileResponse(os.path.join(settings.BASE_DIR, "static", "login.html"))

@app.get("/profile", response_class=HTMLResponse)
async def profile_page():
    """个人中心页路由"""
    return FileResponse(os.path.join(settings.BASE_DIR, "static", "profile.html"))

@app.get("/favicon.ico")
async def favicon():
    """网站图标"""
    return FileResponse(os.path.join(settings.BASE_DIR, "static", "icon", "Pic.ico"))

@app.get("/health")
async def health_check():
    """健康检查接口"""
    return {"status": "healthy", "message": "PicManager is running"}

def main():
    """主函数"""
    log_info("正在启动 PicManager 图片管理系统...")
    log_info(f"工作目录: {settings.BASE_DIR}")
    log_info(f"数据存储: {settings.DATA_PATH}")
    log_info(f"图片存储: {settings.STORE_PATH}")
    log_info(f"临时目录: {settings.TEMP_PATH}")
    log_info(f"Web界面: http://{settings.HOST}:{settings.PORT}")
    if settings.ENABLE_API_DOCS:
        log_info(f"API文档: http://{settings.HOST}:{settings.PORT}/docs")
    else:
        log_info("API文档: 已关闭")
    
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        reload_dirs=["app", "static"] if settings.DEBUG else None,
        log_level="info"
    )

if __name__ == "__main__":
    main()
