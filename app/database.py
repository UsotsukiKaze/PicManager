from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker, Session
from contextlib import closing, contextmanager
import os
import sqlite3
import tempfile
import threading
import time
from datetime import datetime, timedelta
from .models import Base
from .config import settings
from .logger import log_error, log_success

# 数据库路径
DATABASE_PATH = os.path.join(settings.DATA_PATH, "picmanager.db")
DATABASE_URL = settings.DATABASE_URL
SQLITE_BUSY_TIMEOUT_MS = 5000


def _configure_sqlite_connection(dbapi_connection, _connection_record) -> None:
    """Apply connection-scoped SQLite concurrency settings."""
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
    finally:
        cursor.close()

# 创建数据库引擎
_is_sqlite = make_url(DATABASE_URL).get_backend_name() == "sqlite"
engine = create_engine(
    DATABASE_URL,
    echo=False,  # 设置为True可以看到SQL语句
    connect_args={"check_same_thread": False, "timeout": SQLITE_BUSY_TIMEOUT_MS / 1000} if _is_sqlite else {},
)
if _is_sqlite:
    event.listen(engine, "connect", _configure_sqlite_connection)

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
    enable_sqlite_wal()
    create_tables()
    apply_migrations()
    start_daily_snapshot_scheduler()
    log_success(f"数据库初始化完成: {DATABASE_PATH}")


def _is_memory_sqlite_database(target_engine) -> bool:
    database_name = str(target_engine.url.database or "").strip().lower()
    mode = str(target_engine.url.query.get("mode", "")).strip().lower()
    return database_name in {"", ":memory:"} or mode == "memory" or database_name.startswith("file::memory:")


def enable_sqlite_wal(target_engine=None) -> bool:
    """Enable persistent WAL mode for file-backed SQLite databases."""
    target_engine = target_engine or engine
    if target_engine.url.get_backend_name() != "sqlite" or _is_memory_sqlite_database(target_engine):
        return False
    try:
        with target_engine.connect() as connection:
            mode = connection.exec_driver_sql("PRAGMA journal_mode=WAL").scalar_one()
        if str(mode).lower() != "wal":
            log_error(f"SQLite WAL mode was not enabled; journal_mode={mode}")
            return False
        return True
    except Exception as exc:
        # A read-only or unsupported filesystem may reject WAL. Keep the
        # database usable in its existing journal mode and make the failure visible.
        log_error(f"Failed to enable SQLite WAL mode: {exc}")
        return False


def get_snapshot_path() -> str:
    return f"{DATABASE_PATH}.snapshot"


def _atomic_sqlite_backup(source_path: str, destination_path: str, *, overwrite: bool) -> bool:
    """Create a consistent SQLite backup and publish it atomically."""
    destination_dir = os.path.dirname(os.path.abspath(destination_path))
    os.makedirs(destination_dir, exist_ok=True)
    if not overwrite and os.path.exists(destination_path):
        return False

    fd, temp_path = tempfile.mkstemp(
        prefix=f".{os.path.basename(destination_path)}.",
        suffix=".tmp",
        dir=destination_dir,
    )
    os.close(fd)
    try:
        # sqlite3.Connection's context manager commits transactions but does
        # not close the handle. Explicit closing is required before publishing
        # the temp file on Windows.
        with closing(sqlite3.connect(source_path, timeout=30)) as source_db:
            with closing(sqlite3.connect(temp_path, timeout=30)) as backup_db:
                source_db.backup(backup_db)
                check = backup_db.execute("PRAGMA quick_check").fetchone()
                if not check or check[0] != "ok":
                    raise RuntimeError("SQLite backup integrity check failed")

        if overwrite:
            os.replace(temp_path, destination_path)
        else:
            # Publishing through a hard link gives restore true create-if-absent
            # semantics: another process creating the live DB wins, and the
            # snapshot can never replace it in the check/rename race window.
            try:
                os.link(temp_path, destination_path)
            except FileExistsError:
                return False
            os.unlink(temp_path)
        temp_path = ""
        return True
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError:
                pass


def restore_db_snapshot() -> bool:
    """Restore the snapshot only when the live database is missing."""
    snapshot_path = get_snapshot_path()
    with _snapshot_lock:
        if os.path.exists(DATABASE_PATH) or not os.path.isfile(snapshot_path):
            return False
        try:
            return _atomic_sqlite_backup(snapshot_path, DATABASE_PATH, overwrite=False)
        except Exception as exc:
            log_error(f"Failed to restore database snapshot: {exc}")
            return False


def restore_snapshot_if_needed() -> bool:
    """启动时仅在实时数据库缺失时从快照恢复，绝不覆盖现有数据库。"""
    return restore_db_snapshot()


def create_db_snapshot() -> bool:
    """创建数据库快照"""
    if engine.url.get_backend_name() != "sqlite" or not os.path.isfile(DATABASE_PATH):
        return False
    with _snapshot_lock:
        try:
            return _atomic_sqlite_backup(DATABASE_PATH, get_snapshot_path(), overwrite=True)
        except Exception as exc:
            log_error(f"Failed to create database snapshot: {exc}")
            return False


def register_db_commit() -> None:
    """记录一次数据库提交，累计到阈值后更新快照"""
    global _commit_counter
    should_snapshot = False
    with _snapshot_lock:
        _commit_counter += 1
        if _commit_counter >= 50:
            _commit_counter = 0
            should_snapshot = True
    if should_snapshot:
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
        group_columns = [row[1] for row in conn.execute(text("PRAGMA table_info(groups)"))]
        if group_columns and "avatar_url" not in group_columns:
            conn.execute(text("ALTER TABLE groups ADD COLUMN avatar_url VARCHAR(1000)"))

        character_columns = [row[1] for row in conn.execute(text("PRAGMA table_info(characters)"))]
        if character_columns and "avatar_url" not in character_columns:
            conn.execute(text("ALTER TABLE characters ADD COLUMN avatar_url VARCHAR(1000)"))

        # users.last_notice_at
        user_columns = [row[1] for row in conn.execute(text("PRAGMA table_info(users)"))]
        if "last_notice_at" not in user_columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN last_notice_at DATETIME"))

        # pending_requests.rejection_reason
        pending_columns = [row[1] for row in conn.execute(text("PRAGMA table_info(pending_requests)"))]
        if "rejection_reason" not in pending_columns:
            conn.execute(text("ALTER TABLE pending_requests ADD COLUMN rejection_reason TEXT"))
        if "guest_name" not in pending_columns:
            conn.execute(text("ALTER TABLE pending_requests ADD COLUMN guest_name VARCHAR(32)"))

        session_columns = [row[1] for row in conn.execute(text("PRAGMA table_info(user_sessions)"))]
        if session_columns and "guest_name" not in session_columns:
            conn.execute(text("ALTER TABLE user_sessions ADD COLUMN guest_name VARCHAR(32)"))

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

        # images storage status columns
        image_columns = [row[1] for row in conn.execute(text("PRAGMA table_info(images)"))]
        if "age_rating" not in image_columns:
            conn.execute(text("ALTER TABLE images ADD COLUMN age_rating VARCHAR(10) NOT NULL DEFAULT 'all'"))
        if "file_status" not in image_columns:
            conn.execute(text("ALTER TABLE images ADD COLUMN file_status VARCHAR(20) NOT NULL DEFAULT 'available'"))
        if "file_checked_at" not in image_columns:
            conn.execute(text("ALTER TABLE images ADD COLUMN file_checked_at DATETIME"))
        if "thumb_status" not in image_columns:
            conn.execute(text("ALTER TABLE images ADD COLUMN thumb_status VARCHAR(20) NOT NULL DEFAULT 'pending'"))
        if "perceptual_hash" not in image_columns:
            conn.execute(text("ALTER TABLE images ADD COLUMN perceptual_hash VARCHAR(16)"))
        if "pixiv_checked_at" not in image_columns:
            conn.execute(text("ALTER TABLE images ADD COLUMN pixiv_checked_at DATETIME"))

        conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS duplicate_pair_decisions (
                pair_key VARCHAR(21) PRIMARY KEY,
                left_image_id VARCHAR(10) NOT NULL,
                right_image_id VARCHAR(10) NOT NULL,
                decision VARCHAR(20) NOT NULL DEFAULT 'distinct',
                decided_by INTEGER,
                created_at DATETIME,
                updated_at DATETIME,
                FOREIGN KEY(decided_by) REFERENCES users(id)
            )
            """
        ))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_duplicate_pair_left ON duplicate_pair_decisions (left_image_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_duplicate_pair_right ON duplicate_pair_decisions (right_image_id)"))

        auth_columns = [row[1] for row in conn.execute(text("PRAGMA table_info(age_authorization_requests)"))]
        if auth_columns and "authorization_group_id" not in auth_columns:
            conn.execute(text("ALTER TABLE age_authorization_requests ADD COLUMN authorization_group_id VARCHAR(32)"))
        if auth_columns and "authorization_message_id" not in auth_columns:
            conn.execute(text("ALTER TABLE age_authorization_requests ADD COLUMN authorization_message_id VARCHAR(32)"))

        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_images_file_status_created_id ON images (file_status, created_at, image_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_images_thumb_status ON images (thumb_status)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_images_age_rating ON images (age_rating)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_images_perceptual_hash ON images (perceptual_hash)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_images_pixiv_checked_at ON images (pixiv_checked_at)"))

        # guestbook_messages.parent_id
        guestbook_columns = [row[1] for row in conn.execute(text("PRAGMA table_info(guestbook_messages)"))]
        if guestbook_columns and "parent_id" not in guestbook_columns:
            conn.execute(text("ALTER TABLE guestbook_messages ADD COLUMN parent_id INTEGER"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_guestbook_messages_parent_id ON guestbook_messages (parent_id)"))
        if guestbook_columns and "author_qq" not in guestbook_columns:
            conn.execute(text("ALTER TABLE guestbook_messages ADD COLUMN author_qq VARCHAR(20)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_guestbook_messages_author_qq ON guestbook_messages (author_qq)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_image_character_character_image ON image_character_association (character_id, image_id)"))

        conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS feature_tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(255) NOT NULL UNIQUE,
                description TEXT,
                created_at DATETIME,
                updated_at DATETIME
            )
            """
        ))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_feature_tags_name ON feature_tags (name)"))

        conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS group_aliases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER NOT NULL,
                alias VARCHAR(255) NOT NULL,
                FOREIGN KEY(group_id) REFERENCES groups(id)
            )
            """
        ))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_group_aliases_group_id ON group_aliases (group_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_group_aliases_alias ON group_aliases (alias)"))

        conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS feature_tag_aliases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                feature_tag_id INTEGER NOT NULL,
                alias VARCHAR(255) NOT NULL,
                FOREIGN KEY(feature_tag_id) REFERENCES feature_tags(id)
            )
            """
        ))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_feature_tag_aliases_feature_tag_id ON feature_tag_aliases (feature_tag_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_feature_tag_aliases_alias ON feature_tag_aliases (alias)"))

        conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS image_group_association (
                image_id VARCHAR(10) NOT NULL,
                group_id INTEGER NOT NULL,
                PRIMARY KEY (image_id, group_id),
                FOREIGN KEY(image_id) REFERENCES images(image_id),
                FOREIGN KEY(group_id) REFERENCES groups(id)
            )
            """
        ))
        conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS image_feature_tag_association (
                image_id VARCHAR(10) NOT NULL,
                feature_tag_id INTEGER NOT NULL,
                PRIMARY KEY (image_id, feature_tag_id),
                FOREIGN KEY(image_id) REFERENCES images(image_id),
                FOREIGN KEY(feature_tag_id) REFERENCES feature_tags(id)
            )
            """
        ))
        conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS character_feature_tag_association (
                character_id INTEGER NOT NULL,
                feature_tag_id INTEGER NOT NULL,
                PRIMARY KEY (character_id, feature_tag_id),
                FOREIGN KEY(character_id) REFERENCES characters(id),
                FOREIGN KEY(feature_tag_id) REFERENCES feature_tags(id)
            )
            """
        ))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_image_group_group_image ON image_group_association (group_id, image_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_image_feature_tag_tag_image ON image_feature_tag_association (feature_tag_id, image_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_character_feature_tag_tag_character ON character_feature_tag_association (feature_tag_id, character_id)"))

        conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS emotion_tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(255) NOT NULL UNIQUE,
                description TEXT,
                created_at DATETIME,
                updated_at DATETIME
            )
            """
        ))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_emotion_tags_name ON emotion_tags (name)"))

        conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS emotion_tag_aliases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                emotion_id INTEGER NOT NULL,
                alias VARCHAR(255) NOT NULL,
                FOREIGN KEY(emotion_id) REFERENCES emotion_tags(id)
            )
            """
        ))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_emotion_tag_aliases_emotion_id ON emotion_tag_aliases (emotion_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_emotion_tag_aliases_alias ON emotion_tag_aliases (alias)"))

        conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS emojis (
                emoji_id VARCHAR(10) PRIMARY KEY,
                description TEXT,
                original_filename VARCHAR(500),
                file_extension VARCHAR(10) NOT NULL DEFAULT 'gif',
                file_size INTEGER,
                width INTEGER,
                height INTEGER,
                file_path VARCHAR(1000) NOT NULL,
                file_status VARCHAR(20) NOT NULL DEFAULT 'available',
                file_checked_at DATETIME,
                created_at DATETIME,
                updated_at DATETIME
            )
            """
        ))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_emojis_file_status_created_id ON emojis (file_status, created_at, emoji_id)"))

        conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS emoji_group_association (
                emoji_id VARCHAR(10) NOT NULL,
                group_id INTEGER NOT NULL,
                PRIMARY KEY (emoji_id, group_id),
                FOREIGN KEY(emoji_id) REFERENCES emojis(emoji_id),
                FOREIGN KEY(group_id) REFERENCES groups(id)
            )
            """
        ))
        conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS emoji_character_association (
                emoji_id VARCHAR(10) NOT NULL,
                character_id INTEGER NOT NULL,
                PRIMARY KEY (emoji_id, character_id),
                FOREIGN KEY(emoji_id) REFERENCES emojis(emoji_id),
                FOREIGN KEY(character_id) REFERENCES characters(id)
            )
            """
        ))
        conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS emoji_emotion_association (
                emoji_id VARCHAR(10) NOT NULL,
                emotion_id INTEGER NOT NULL,
                PRIMARY KEY (emoji_id, emotion_id),
                FOREIGN KEY(emoji_id) REFERENCES emojis(emoji_id),
                FOREIGN KEY(emotion_id) REFERENCES emotion_tags(id)
            )
            """
        ))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_emoji_group_group_emoji ON emoji_group_association (group_id, emoji_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_emoji_character_character_emoji ON emoji_character_association (character_id, emoji_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_emoji_emotion_emotion_emoji ON emoji_emotion_association (emotion_id, emoji_id)"))

        conn.execute(text(
            """
            INSERT OR IGNORE INTO image_group_association (image_id, group_id)
            SELECT DISTINCT ica.image_id, c.group_id
            FROM image_character_association ica
            JOIN characters c ON c.id = ica.character_id
            """
        ))
        conn.execute(text(
            """
            INSERT OR IGNORE INTO image_feature_tag_association (image_id, feature_tag_id)
            SELECT DISTINCT ica.image_id, cfta.feature_tag_id
            FROM image_character_association ica
            JOIN character_feature_tag_association cfta ON cfta.character_id = ica.character_id
            """
        ))

        unchecked_images = conn.execute(text(
            "SELECT image_id, file_path FROM images WHERE file_checked_at IS NULL"
        )).fetchall()
        checked_at = datetime.utcnow()
        for image_id, file_path in unchecked_images:
            normalized = (file_path or "").replace("\\", "/").lstrip("/")
            full_path = os.path.join(settings.BASE_DIR, *normalized.split("/")) if normalized else ""
            exists = bool(full_path) and os.path.isfile(full_path)
            thumb_path = os.path.join(settings.THUMB_PATH, f"{image_id}.webp")
            conn.execute(text(
                """
                UPDATE images
                SET file_status = :file_status,
                    file_checked_at = :file_checked_at,
                    thumb_status = :thumb_status
                WHERE image_id = :image_id
                """
            ), {
                "file_status": "available" if exists else "missing",
                "file_checked_at": checked_at,
                "thumb_status": "ready" if exists and os.path.isfile(thumb_path) else ("pending" if exists else "missing"),
                "image_id": image_id,
            })

        conn.commit()
