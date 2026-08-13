# PicManager 配置文件
from pydantic_settings import BaseSettings
import os
import secrets
from pathlib import Path

class Settings(BaseSettings):
    """应用配置"""
    
    # 路径配置
    BASE_DIR: str = str(Path(__file__).resolve().parents[1])
    DATA_PATH: str = os.path.join(BASE_DIR, "data")
    RESOURCE_PATH: str = os.path.join(BASE_DIR, "resource")
    STORE_PATH: str = os.path.join(RESOURCE_PATH, "store")
    TEMP_PATH: str = os.path.join(RESOURCE_PATH, "temp")
    PENDING_PATH: str = os.path.join(RESOURCE_PATH, "pending")
    THUMB_PATH: str = os.path.join(RESOURCE_PATH, "thumbs")
    EMOJI_PATH: str = os.path.join(RESOURCE_PATH, "emojis")
    AVATAR_PATH: str = os.path.join(RESOURCE_PATH, "avatars")
    
    # 数据库配置
    DATABASE_URL: str = f"sqlite:///{os.path.join(DATA_PATH, 'picmanager.db')}"
    HOMEPAGE_HOSTS: str = "usotsuki-kaze.com,www.usotsuki-kaze.com"
    
    # 上传配置
    MAX_FILE_SIZE: int = 50 * 1024 * 1024  # 50MB
    ALLOWED_EXTENSIONS: set = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
    THUMBNAIL_SIZE: int = 480
    THUMBNAIL_QUALITY: int = 86
    THUMBNAIL_WEBP_METHOD: int = 4
    AVATAR_MAX_FILE_SIZE: int = 256 * 1024
    AVATAR_UPLOAD_MAX_FILE_SIZE: int = 10 * 1024 * 1024
    AVATAR_SIZE: int = 512
    
    # 分页配置
    DEFAULT_PAGE_SIZE: int = 50
    MAX_PAGE_SIZE: int = 200
    
    # 服务器配置
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = False
    ENABLE_API_DOCS: bool = False
    
    # 安全配置
    SECRET_KEY: str = "your-secret-key-here"  # 在生产环境中应该设置为随机字符串
    BOT_API_TOKEN: str = ""
    PHROLOVA_SSO_TOKEN: str = ""
    PHROLOVA_PUBLIC_BASE_URL: str = ""
    PUBLIC_BASE_URL: str = ""
    LOGIN_TICKET_TTL_SECONDS: int = 300
    ROOT_QQ: str = "1356890337"
    AGE_RATING_SUPERUSERS: str = ""
    AGE_RATING_ASSERTION_SECRET: str = ""
    CORS_ALLOW_ORIGINS: str = "http://127.0.0.1:8000,http://localhost:8000"
    SESSION_COOKIE_SECURE: bool = False
    SESSION_COOKIE_DOMAIN: str | None = None
    TRUST_PROXY_HEADERS: bool = False
    TRUSTED_HOSTS: str = "localhost,127.0.0.1,pic.usotsuki-kaze.com,usotsuki-kaze.com,www.usotsuki-kaze.com"
    LAN_DEBUG_ENABLED: bool = False
    LAN_DEBUG_HOSTS: str = ""
    LAN_DEBUG_BASE_URL: str = ""
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

# 创建全局设置实例
settings = Settings()


_INSECURE_SECRET_KEYS = {
    "",
    "your-secret-key-here",
    "your-secret-key-change-this-in-production-min-32-chars",
}


def _resolve_secret_key(config: Settings) -> str:
    """Return a stable signing key without accepting shipped placeholders."""
    configured = str(config.SECRET_KEY or "").strip()
    if configured not in _INSECURE_SECRET_KEYS:
        if len(configured) < 32:
            raise RuntimeError("SECRET_KEY must contain at least 32 characters")
        return configured

    secret_path = Path(config.DATA_PATH) / ".secret_key"
    secret_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        persisted = secret_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        persisted = ""
    if persisted:
        if len(persisted) < 32:
            raise RuntimeError(f"Runtime signing key is invalid: {secret_path}")
        return persisted

    generated = secrets.token_urlsafe(48)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        descriptor = os.open(secret_path, flags, 0o600)
    except FileExistsError:
        persisted = secret_path.read_text(encoding="utf-8").strip()
        if len(persisted) < 32:
            raise RuntimeError(f"Runtime signing key is invalid: {secret_path}")
        return persisted

    with os.fdopen(descriptor, "w", encoding="utf-8") as secret_file:
        secret_file.write(generated)
    return generated


settings.SECRET_KEY = _resolve_secret_key(settings)
