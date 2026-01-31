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
    
    # 数据库配置
    DATABASE_URL: str = f"sqlite:///{os.path.join(DATA_PATH, 'picmanager.db')}"
    
    # 上传配置
    MAX_FILE_SIZE: int = 50 * 1024 * 1024  # 50MB
    ALLOWED_EXTENSIONS: set = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
    
    # 分页配置
    DEFAULT_PAGE_SIZE: int = 50
    MAX_PAGE_SIZE: int = 200
    
    # 服务器配置
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = True
    
    # 安全配置
    SECRET_KEY: str = "your-secret-key-here"  # 在生产环境中应该设置为随机字符串
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

# 创建全局设置实例
settings = Settings()