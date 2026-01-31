from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
import os
from .models import Base
from .config import settings
from .logger import log_success

# 数据库路径
DATABASE_PATH = os.path.join(settings.DATA_PATH, "picmanager.db")
DATABASE_URL = settings.DATABASE_URL

# 创建数据库引擎
engine = create_engine(
    DATABASE_URL,
    echo=False,  # 设置为True可以看到SQL语句
    connect_args={"check_same_thread": False}
)

# 创建会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def create_tables():
    """创建所有数据表"""
    # 确保数据目录存在
    os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)
    Base.metadata.create_all(bind=engine)

def get_db() -> Session:
    """获取数据库会话"""
    db = SessionLocal()
    try:
        return db
    finally:
        pass  # 不在这里关闭，让调用者管理

@contextmanager
def get_db_context():
    """获取数据库会话的上下文管理器"""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def init_database():
    """初始化数据库"""
    create_tables()
    log_success(f"数据库初始化完成: {DATABASE_PATH}")