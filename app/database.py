from sqlalchemy import create_engine, text
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
    apply_migrations()
    log_success(f"数据库初始化完成: {DATABASE_PATH}")


def apply_migrations():
    """对SQLite执行必要的结构迁移（增量）"""
    with engine.connect() as conn:
        # users.last_notice_at
        user_columns = [row[1] for row in conn.execute(text("PRAGMA table_info(users)"))]
        if "last_notice_at" not in user_columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN last_notice_at DATETIME"))

        # pending_requests.rejection_reason
        pending_columns = [row[1] for row in conn.execute(text("PRAGMA table_info(pending_requests)"))]
        if "rejection_reason" not in pending_columns:
            conn.execute(text("ALTER TABLE pending_requests ADD COLUMN rejection_reason TEXT"))

        # image_view_counts table
        conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS image_view_counts (
                image_id VARCHAR(10) PRIMARY KEY,
                view_count INTEGER DEFAULT 0,
                updated_at DATETIME,
                FOREIGN KEY(image_id) REFERENCES images(image_id)
            )
            """
        ))

        # character_query_counts table
        conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS character_query_counts (
                character_id INTEGER PRIMARY KEY,
                query_count INTEGER DEFAULT 0,
                updated_at DATETIME,
                FOREIGN KEY(character_id) REFERENCES characters(id)
            )
            """
        ))

        conn.commit()