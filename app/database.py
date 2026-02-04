from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
import os
import shutil
import hashlib
import threading
import time
from datetime import datetime, timedelta
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

_snapshot_lock = threading.Lock()
_commit_counter = 0
_snapshot_daily_thread_started = False

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
        register_db_commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def init_database():
    """初始化数据库"""
    restore_snapshot_if_needed()
    create_tables()
    apply_migrations()
    start_daily_snapshot_scheduler()
    log_success(f"数据库初始化完成: {DATABASE_PATH}")


def get_snapshot_path() -> str:
    return f"{DATABASE_PATH}.snapshot"


def file_hash(path: str) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def restore_snapshot_if_needed() -> None:
    """启动时检查快照与当前数据库是否一致，不一致则用快照替换"""
    snapshot_path = get_snapshot_path()
    if not os.path.exists(snapshot_path):
        return

    if not os.path.exists(DATABASE_PATH):
        shutil.copy2(snapshot_path, DATABASE_PATH)
        return

    try:
        current_hash = file_hash(DATABASE_PATH)
        snapshot_hash = file_hash(snapshot_path)
    except Exception:
        return

    if current_hash != snapshot_hash:
        try:
            engine.dispose()
        except Exception:
            pass
        shutil.copy2(snapshot_path, DATABASE_PATH)


def create_db_snapshot() -> None:
    """创建数据库快照"""
    if not os.path.exists(DATABASE_PATH):
        return
    snapshot_path = get_snapshot_path()
    try:
        shutil.copy2(DATABASE_PATH, snapshot_path)
    except Exception:
        pass


def register_db_commit() -> None:
    """记录一次数据库提交，累计到阈值后更新快照"""
    global _commit_counter
    with _snapshot_lock:
        _commit_counter += 1
        if _commit_counter >= 50:
            _commit_counter = 0
            create_db_snapshot()


def _seconds_until_next_midnight() -> float:
    now = datetime.now()
    next_midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max((next_midnight - now).total_seconds(), 1.0)


def start_daily_snapshot_scheduler() -> None:
    """每天 0 点创建一次快照"""
    global _snapshot_daily_thread_started
    if _snapshot_daily_thread_started:
        return
    _snapshot_daily_thread_started = True

    def _worker():
        while True:
            time.sleep(_seconds_until_next_midnight())
            create_db_snapshot()

    threading.Thread(target=_worker, name="db_snapshot_scheduler", daemon=True).start()


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