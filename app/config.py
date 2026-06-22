# PicManager 配置文件
from pydantic_settings import BaseSettings
import os
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
    
    # 数据库配置
    DATABASE_URL: str = f"sqlite:///{os.path.join(DATA_PATH, 'picmanager.db')}"
    
    # 上传配置
    MAX_FILE_SIZE: int = 50 * 1024 * 1024  # 50MB
    ALLOWED_EXTENSIONS: set = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
    THUMBNAIL_SIZE: int = 480
    THUMBNAIL_QUALITY: int = 86
    THUMBNAIL_WEBP_METHOD: int = 4
    
    # 分页配置
    DEFAULT_PAGE_SIZE: int = 50
    MAX_PAGE_SIZE: int = 200
    
    # 服务器配置
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = True
    
    # 安全配置
    SECRET_KEY: str = "your-secret-key-here"  # 在生产环境中应该设置为随机字符串
    BOT_API_TOKEN: str = ""
    PUBLIC_BASE_URL: str = ""
    LOGIN_TICKET_TTL_SECONDS: int = 300
    ROOT_QQ: str = "1356890337"
    CORS_ALLOW_ORIGINS: str = "http://127.0.0.1:8000,http://localhost:8000"
    SESSION_COOKIE_SECURE: bool = False
    TRUST_PROXY_HEADERS: bool = False
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

# 创建全局设置实例
settings = Settings()
