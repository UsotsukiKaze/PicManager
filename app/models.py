from sqlalchemy import Column, String, Integer, Text, Table, ForeignKey, DateTime, Date, JSON, Float, UniqueConstraint, Index, event, select, delete
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, Session
from datetime import datetime
import enum

Base = declarative_base()

# 用户角色枚举
class UserRole(enum.Enum):
    ROOT = "root"
    ADMIN = "admin"
    USER = "user"
    GUEST = "guest"


class AgeRating(enum.Enum):
    ALL = "all"
    R12 = "r12"
    R16 = "r16"
    R18 = "r18"

# 待审核请求类型枚举
class RequestType(enum.Enum):
    ADD = "add"
    EDIT = "edit"
    DELETE = "delete"

# 待审核请求状态枚举
class RequestStatus(enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    UNCHANGED = "unchanged"

# 图片与角色的多对多关联表
image_character_association = Table(
    'image_character_association',
    Base.metadata,
    Column('image_id', String, ForeignKey('images.image_id'), primary_key=True),
    Column('character_id', Integer, ForeignKey('characters.id'), primary_key=True)
)

image_group_association = Table(
    'image_group_association',
    Base.metadata,
    Column('image_id', String, ForeignKey('images.image_id'), primary_key=True),
    Column('group_id', Integer, ForeignKey('groups.id'), primary_key=True)
)

image_feature_tag_association = Table(
    'image_feature_tag_association',
    Base.metadata,
    Column('image_id', String, ForeignKey('images.image_id'), primary_key=True),
    Column('feature_tag_id', Integer, ForeignKey('feature_tags.id'), primary_key=True)
)

character_feature_tag_association = Table(
    'character_feature_tag_association',
    Base.metadata,
    Column('character_id', Integer, ForeignKey('characters.id'), primary_key=True),
    Column('feature_tag_id', Integer, ForeignKey('feature_tags.id'), primary_key=True)
)

emoji_group_association = Table(
    'emoji_group_association',
    Base.metadata,
    Column('emoji_id', String, ForeignKey('emojis.emoji_id'), primary_key=True),
    Column('group_id', Integer, ForeignKey('groups.id'), primary_key=True)
)

emoji_character_association = Table(
    'emoji_character_association',
    Base.metadata,
    Column('emoji_id', String, ForeignKey('emojis.emoji_id'), primary_key=True),
    Column('character_id', Integer, ForeignKey('characters.id'), primary_key=True)
)

emoji_emotion_association = Table(
    'emoji_emotion_association',
    Base.metadata,
    Column('emoji_id', String, ForeignKey('emojis.emoji_id'), primary_key=True),
    Column('emotion_id', Integer, ForeignKey('emotion_tags.id'), primary_key=True)
)


class User(Base):
    """用户表"""
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    qq_number = Column(String(20), unique=True, nullable=False, index=True)
    role = Column(String(20), nullable=False, default=UserRole.USER.value)
    password_hash = Column(String(255), nullable=True)  # 旧数据库兼容字段；密码登录已禁用
    nickname = Column(String(100), nullable=True)
    avatar_url = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_notice_at = Column(DateTime, default=datetime.utcnow)
    
    # 关联待审核请求（指定外键以避免歧义）
    pending_requests = relationship(
        "PendingRequest", 
        back_populates="user",
        foreign_keys="[PendingRequest.user_id]"
    )


class PendingRequest(Base):
    """待审核请求表"""
    __tablename__ = 'pending_requests'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    request_type = Column(String(20), nullable=False)  # add, edit, delete
    status = Column(String(20), nullable=False, default=RequestStatus.PENDING.value)
    
    # 用户信息（可能是登录用户或游客）
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    guest_ip = Column(String(50), nullable=True)
    guest_name = Column(String(32), nullable=True)
    
    # 图片信息
    image_id = Column(String(10), nullable=True)  # 用于edit和delete
    
    # 图片数据（用于add和edit）- 存储为JSON
    image_data = Column(Text, nullable=True)
    
    # 临时文件路径（用于add）
    temp_file_path = Column(String(500), nullable=True)
    original_filename = Column(String(500), nullable=True)
    rejection_reason = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    reviewed_at = Column(DateTime, nullable=True)
    reviewed_by = Column(Integer, ForeignKey('users.id'), nullable=True)
    
    # 关联
    user = relationship("User", foreign_keys=[user_id], back_populates="pending_requests")
    reviewer = relationship("User", foreign_keys=[reviewed_by])


class GuestLimit(Base):
    """游客操作限制表"""
    __tablename__ = 'guest_limits'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    ip_address = Column(String(50), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    operation_count = Column(Integer, default=0)
    
    # 联合唯一约束由代码层面控制


class UserSession(Base):
    """用户会话表 - 持久化存储登录状态"""
    __tablename__ = 'user_sessions'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(36), unique=True, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True)  # None表示游客
    guest_ip = Column(String(50), nullable=True)  # 游客IP
    guest_name = Column(String(32), nullable=True)  # 签名Cookie对应的游客显示名
    is_guest = Column(String(5), nullable=False, default="false")  # "true" 或 "false"
    created_at = Column(DateTime, default=datetime.utcnow)
    last_activity = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)  # 过期时间
    
    # 关联用户
    user = relationship("User")


class LoginTicket(Base):
    """One-time QQ login ticket issued by trusted bot-side services."""
    __tablename__ = 'login_tickets'

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_hash = Column(String(64), unique=True, nullable=False, index=True)
    qq_number = Column(String(20), nullable=False, index=True)
    purpose = Column(String(50), nullable=False, default="login", index=True)
    redirect_path = Column(String(500), nullable=True)
    created_by = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False, index=True)
    used_at = Column(DateTime, nullable=True)


class Group(Base):
    """分组表 - 游戏/IP分组"""
    __tablename__ = 'groups'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), unique=True, nullable=False, index=True)
    avatar_url = Column(String(1000), nullable=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关联角色
    characters = relationship("Character", back_populates="group", cascade="all, delete-orphan")
    images = relationship("Image", secondary=image_group_association, back_populates="groups")
    emojis = relationship("Emoji", secondary=emoji_group_association, back_populates="groups")
    aliases = relationship("GroupAlias", back_populates="group", cascade="all, delete-orphan")
    pixiv_mappings = relationship("PixivTagMapping", foreign_keys="PixivTagMapping.group_id", cascade="all, delete-orphan")


class GroupAlias(Base):
    """Group alias table."""
    __tablename__ = 'group_aliases'

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(Integer, ForeignKey('groups.id'), nullable=False, index=True)
    alias = Column(String(255), nullable=False, index=True)

    group = relationship("Group", back_populates="aliases")


class Character(Base):
    """角色表"""
    __tablename__ = 'characters'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, index=True)
    group_id = Column(Integer, ForeignKey('groups.id'), nullable=False)
    avatar_url = Column(String(1000), nullable=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关联分组
    group = relationship("Group", back_populates="characters")
    # 关联图片（多对多）
    images = relationship("Image", secondary=image_character_association, back_populates="characters")
    emojis = relationship("Emoji", secondary=emoji_character_association, back_populates="characters")
    # 角色昵称
    nicknames = relationship("CharacterNickname", back_populates="character", cascade="all, delete-orphan")
    feature_tags = relationship("FeatureTag", secondary=character_feature_tag_association, back_populates="characters")
    pixiv_mappings = relationship("PixivTagMapping", foreign_keys="PixivTagMapping.character_id", cascade="all, delete-orphan")


class CharacterNickname(Base):
    """角色昵称表"""
    __tablename__ = 'character_nicknames'

    id = Column(Integer, primary_key=True, autoincrement=True)
    character_id = Column(Integer, ForeignKey('characters.id'), nullable=False, index=True)
    nickname = Column(String(255), nullable=False, index=True)

    character = relationship("Character", back_populates="nicknames")


class FeatureTag(Base):
    """Feature tags such as hair color, eye color, or visual traits."""
    __tablename__ = 'feature_tags'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    characters = relationship("Character", secondary=character_feature_tag_association, back_populates="feature_tags")
    images = relationship("Image", secondary=image_feature_tag_association, back_populates="feature_tags")
    aliases = relationship("FeatureTagAlias", back_populates="feature_tag", cascade="all, delete-orphan")
    pixiv_mappings = relationship("PixivTagMapping", foreign_keys="PixivTagMapping.feature_tag_id", cascade="all, delete-orphan")


class FeatureTagAlias(Base):
    """Feature tag alias table."""
    __tablename__ = 'feature_tag_aliases'

    id = Column(Integer, primary_key=True, autoincrement=True)
    feature_tag_id = Column(Integer, ForeignKey('feature_tags.id'), nullable=False, index=True)
    alias = Column(String(255), nullable=False, index=True)

    feature_tag = relationship("FeatureTag", back_populates="aliases")


class EmotionTag(Base):
    """Emoji tags: basic emotions and #-prefixed functions."""
    __tablename__ = 'emotion_tags'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    emojis = relationship("Emoji", secondary=emoji_emotion_association, back_populates="emotions")
    aliases = relationship("EmotionTagAlias", back_populates="emotion", cascade="all, delete-orphan")

    @property
    def tag_type(self) -> str:
        return "function" if self.name.strip().startswith("#") else "emotion"


class EmotionTagAlias(Base):
    """Emotion tag alias table."""
    __tablename__ = 'emotion_tag_aliases'

    id = Column(Integer, primary_key=True, autoincrement=True)
    emotion_id = Column(Integer, ForeignKey('emotion_tags.id'), nullable=False, index=True)
    alias = Column(String(255), nullable=False, index=True)

    emotion = relationship("EmotionTag", back_populates="aliases")


class Image(Base):
    """图片表 - 核心数据表"""
    __tablename__ = 'images'
    
    # 10位十六进制数作为主键
    image_id = Column(String(10), primary_key=True)  
    # PID - 车牌号（Pixiv ID等）
    pid = Column(String(255), nullable=True, index=True)
    # 图片描述
    description = Column(Text, nullable=True)
    # 独立年龄分级，不与普通特征标签混用
    age_rating = Column(String(10), nullable=False, default=AgeRating.R12.value, index=True)
    # 原始文件名
    original_filename = Column(String(500), nullable=True)
    # 文件扩展名
    file_extension = Column(String(10), nullable=False)
    # 文件大小（字节）
    file_size = Column(Integer, nullable=True)
    # 图片尺寸
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    # 文件路径（相对路径）
    file_path = Column(String(1000), nullable=False)
    file_status = Column(String(20), nullable=False, default="available", index=True)
    file_checked_at = Column(DateTime, nullable=True)
    thumb_status = Column(String(20), nullable=False, default="pending", index=True)
    preview_status = Column(String(20), nullable=False, default="pending", index=True)
    # 64-bit difference hash, stored as 16 lowercase hexadecimal characters.
    perceptual_hash = Column(String(16), nullable=True)
    # Set only after a numeric Pixiv PID has been checked and resolved.
    pixiv_checked_at = Column(DateTime, nullable=True, index=True)
    local_checked_at = Column(DateTime, nullable=True, index=True)
    # 创建和更新时间
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关联角色（多对多）
    characters = relationship("Character", secondary=image_character_association, back_populates="images")
    groups = relationship("Group", secondary=image_group_association, back_populates="images")
    feature_tags = relationship("FeatureTag", secondary=image_feature_tag_association, back_populates="images")
    pixiv_sources = relationship("PixivImageSource", cascade="all, delete-orphan", back_populates="image")
    tag_evidence = relationship("ImageTagEvidence", cascade="all, delete-orphan", back_populates="image")
    pixiv_metadata = relationship("PixivImageMetadata", uselist=False, cascade="all, delete-orphan", back_populates="image")
    visual_fingerprint = relationship("ImageVisualFingerprint", uselist=False, cascade="all, delete-orphan", back_populates="image")
    
    def __repr__(self):
        return f"<Image(image_id='{self.image_id}', pid='{self.pid}')>"


class PixivArtist(Base):
    """Automatically maintained Pixiv artists; no manual CRUD surface."""
    __tablename__ = "pixiv_artists"
    id = Column(String(30), primary_key=True)
    name = Column(String(255), nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    works = relationship("PixivImageMetadata", back_populates="artist")


class ImageVisualFingerprint(Base):
    __tablename__ = "image_visual_fingerprints"
    image_id = Column(String(10), ForeignKey("images.image_id", ondelete="CASCADE"), primary_key=True)
    algorithm = Column(String(32), nullable=False)
    source_signature = Column(JSON, nullable=False)
    descriptor = Column(JSON, nullable=False)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    image = relationship("Image", back_populates="visual_fingerprint")


@event.listens_for(Session, "before_flush")
def invalidate_visual_fingerprints(session, _context, _instances):
    from sqlalchemy import inspect
    for image in list(session.dirty):
        if not isinstance(image, Image):
            continue
        state = inspect(image)
        if any(state.attrs[key].history.has_changes() for key in ("pid", "file_path", "file_size", "width", "height", "perceptual_hash")):
            image.visual_fingerprint = None


class PixivImageMetadata(Base):
    __tablename__ = "pixiv_image_metadata"
    image_id = Column(String(10), ForeignKey("images.image_id"), primary_key=True)
    work_id = Column(String(30), nullable=False, index=True)
    page_index = Column(Integer, nullable=False)
    page_count = Column(Integer, nullable=False)
    artist_id = Column(String(30), ForeignKey("pixiv_artists.id"), nullable=True, index=True)
    status = Column(String(20), nullable=False, default="verified")
    tags = Column(JSON, nullable=False, default=list)
    validated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    image = relationship("Image", back_populates="pixiv_metadata")
    artist = relationship("PixivArtist", back_populates="works")


class PixivCheckReview(Base):
    __tablename__ = "pixiv_check_reviews"
    id = Column(String(64), primary_key=True)
    image_id = Column(String(10), nullable=False, index=True)
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    account_revision = Column(String(32), nullable=False)
    snapshot = Column(JSON, nullable=False)
    artwork = Column(JSON, nullable=False)
    suggested_page = Column(Integer, nullable=True)
    resolved = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=False)


class PixivCheckRun(Base):
    __tablename__ = "pixiv_check_runs"
    id = Column(String(32), primary_key=True)
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    account_revision = Column(String(32), nullable=False)
    active_key = Column(String(30), nullable=True, unique=True)
    status = Column(String(20), nullable=False, default="running")
    workers = Column(Integer, nullable=False, default=3)
    fingerprints = Column(Integer, nullable=False, default=0)
    fingerprint_failures = Column(Integer, nullable=False, default=0)
    error = Column(String(100), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)


class PixivCheckItem(Base):
    __tablename__ = "pixiv_check_items"
    __table_args__ = (UniqueConstraint("run_id", "image_id"), Index("ix_pixiv_check_queue", "status", "available_at", "id"))
    id = Column(Integer, primary_key=True)
    run_id = Column(String(32), ForeignKey("pixiv_check_runs.id"), nullable=False, index=True)
    image_id = Column(String(10), nullable=True)
    kind = Column(String(20), nullable=False, default="pixiv")
    status = Column(String(20), nullable=False, default="queued")
    attempts = Column(Integer, nullable=False, default=0)
    available_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    locked_at = Column(DateTime, nullable=True)
    lease = Column(String(32), nullable=True)
    review_id = Column(String(64), nullable=True, index=True)
    error = Column(String(100), nullable=True)
    result = Column(JSON, nullable=True)


@event.listens_for(Image, "before_insert")
def _normalize_new_pixiv_pid(mapper, connection, image):
    from .pixiv_metadata import normalize_new_pid
    image.pid = normalize_new_pid(image.pid, image.original_filename)


@event.listens_for(Session, "before_flush")
def _track_artist_cleanup(session, context, instances):
    from sqlalchemy import inspect
    from .pixiv_metadata import split_pid
    deleted_groups = [row.id for row in session.deleted if isinstance(row, Group)]
    if deleted_groups:
        session.connection().execute(delete(PixivTagMapping).where(PixivTagMapping.group_context.in_(deleted_groups)))
    for image in [row for row in session.dirty if isinstance(row, Image)]:
        attrs = inspect(image).attrs
        if any(attrs[name].history.has_changes() for name in ("file_path", "file_size", "width", "height", "characters")):
            image.local_checked_at = None
        if attrs.pid.history.has_changes() and image.pixiv_metadata:
            meta = image.pixiv_metadata
            if split_pid(image.pid) != (meta.work_id, meta.page_index):
                image.pixiv_metadata = None
                image.pixiv_sources = []
                image.pixiv_checked_at = None
        elif attrs.pid.history.has_changes() and not attrs.pixiv_checked_at.history.has_changes():
            image.pixiv_checked_at = None
    if any(isinstance(row, (Image, PixivImageMetadata)) for row in session.deleted) or any(
        isinstance(row, (Image, PixivImageMetadata)) for row in session.dirty
    ):
        session.info["prune_pixiv_artists"] = True


@event.listens_for(Session, "after_flush_postexec")
def _prune_unused_artists(session, context):
    if session.info.pop("prune_pixiv_artists", False):
        session.connection().execute(delete(PixivArtist).where(~select(PixivImageMetadata.image_id).where(
            PixivImageMetadata.artist_id == PixivArtist.id
        ).exists()))


class FileOperationReceipt(Base):
    """Commit witness for durable filesystem intents; no reference to a deletable image."""
    __tablename__ = "file_operation_receipts"
    id = Column(String(32), primary_key=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)


class ImageJob(Base):
    """Durable background work item for image derivatives and maintenance."""
    __tablename__ = "image_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_type = Column(String(50), nullable=False, index=True)
    image_id = Column(String(10), ForeignKey("images.image_id"), nullable=True, index=True)
    payload = Column(Text, nullable=True)
    dedupe_key = Column(String(255), nullable=True, index=True)
    status = Column(String(20), nullable=False, default="queued", index=True)
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=5)
    available_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    locked_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class DuplicatePairDecision(Base):
    """A durable decision that two visually similar images are intentionally distinct."""
    __tablename__ = "duplicate_pair_decisions"

    pair_key = Column(String(21), primary_key=True)
    left_image_id = Column(String(10), nullable=False, index=True)
    right_image_id = Column(String(10), nullable=False, index=True)
    decision = Column(String(20), nullable=False, default="distinct")
    decided_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class GroupAgeSetting(Base):
    """Bot group content ceiling managed by PicManager."""
    __tablename__ = 'group_age_settings'

    group_id = Column(String(32), primary_key=True)
    age_rating = Column(String(10), nullable=False, default=AgeRating.R12.value)
    updated_by = Column(String(32), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AgeAuthorizationRequest(Base):
    """Auditable R18 authorization request; approval is owned by PicManager."""
    __tablename__ = 'age_authorization_requests'

    request_id = Column(String(36), primary_key=True)
    group_id = Column(String(32), nullable=False, index=True)
    requested_by = Column(String(32), nullable=False)
    requested_by_name = Column(String(100), nullable=True)
    source_group_name = Column(String(255), nullable=True)
    authorization_group_id = Column(String(32), nullable=True, index=True)
    authorization_message_id = Column(String(32), nullable=True, index=True)
    status = Column(String(20), nullable=False, default="pending", index=True)
    reviewed_by = Column(String(32), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    reviewed_at = Column(DateTime, nullable=True)


class AgeAssertionNonce(Base):
    """Persisted replay guard for signed bot identity assertions."""
    __tablename__ = 'age_assertion_nonces'

    nonce = Column(String(64), primary_key=True)
    used_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)


class Emoji(Base):
    """Emoji image resources isolated from the normal image library."""
    __tablename__ = 'emojis'

    emoji_id = Column(String(10), primary_key=True)
    description = Column(Text, nullable=True)
    original_filename = Column(String(500), nullable=True)
    file_extension = Column(String(10), nullable=False, default="gif")
    file_size = Column(Integer, nullable=True)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    file_path = Column(String(1000), nullable=False)
    file_status = Column(String(20), nullable=False, default="available", index=True)
    file_checked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    groups = relationship("Group", secondary=emoji_group_association, back_populates="emojis")
    characters = relationship("Character", secondary=emoji_character_association, back_populates="emojis")
    emotions = relationship("EmotionTag", secondary=emoji_emotion_association, back_populates="emojis")

    def __repr__(self):
        return f"<Emoji(emoji_id='{self.emoji_id}')>"


class ImageViewCount(Base):
    """图片浏览计数"""
    __tablename__ = 'image_view_counts'

    image_id = Column(String(10), ForeignKey('images.image_id'), primary_key=True)
    view_count = Column(Integer, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    image = relationship("Image")


class CharacterQueryCount(Base):
    """角色查询计数"""
    __tablename__ = 'character_query_counts'

    character_id = Column(Integer, ForeignKey('characters.id'), primary_key=True)
    query_count = Column(Integer, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    character = relationship("Character")


class PixivAccount(Base):
    __tablename__ = "pixiv_accounts"
    id = Column(Integer, primary_key=True)  # singleton: id=1
    user_id = Column(String(30), nullable=False)
    name = Column(String(100), nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    revision = Column(String(32), nullable=False)
    credential = Column(Text, nullable=False)
    status = Column(String(30), default="connected", nullable=False)
    preferences = Column(JSON, default=dict, nullable=False)
    sync_state = Column(JSON, default=dict, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PixivArtwork(Base):
    __tablename__ = "pixiv_artworks"
    __table_args__ = (UniqueConstraint("account_revision", "pid"),
                      Index("ix_pixiv_feed", "account_revision", "published_at", "pid"))
    id = Column(Integer, primary_key=True)
    account_revision = Column(String(32), nullable=False, index=True)
    pid = Column(String(30), nullable=False)
    author_id = Column(String(30), nullable=False)
    title = Column(String(500), nullable=False)
    published_at = Column(DateTime, nullable=False)
    metadata_json = Column(JSON, nullable=False)
    origins = Column(JSON, default=list, nullable=False)
    fetched_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class PixivFollow(Base):
    __tablename__ = "pixiv_follows"
    __table_args__ = (UniqueConstraint("account_revision", "author_id"),)
    id = Column(Integer, primary_key=True)
    account_revision = Column(String(32), nullable=False, index=True)
    author_id = Column(String(30), nullable=False)
    name = Column(String(100), nullable=False)
    restrict = Column(String(10), nullable=False)
    sync_marker = Column(String(32), nullable=False)


class PixivJob(Base):
    __tablename__ = "pixiv_jobs"
    __table_args__ = (Index("ix_pixiv_jobs_claim", "status", "available_at", "id"),)
    id = Column(Integer, primary_key=True)
    account_revision = Column(String(32), nullable=False)
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    kind = Column(String(30), nullable=False)
    dedupe_key = Column(String(200), unique=True, nullable=True)
    status = Column(String(30), default="queued", nullable=False)
    payload = Column(JSON, default=dict, nullable=False)
    result = Column(JSON, default=dict, nullable=False)
    error = Column(String(300), nullable=True)
    attempts = Column(Integer, default=0, nullable=False)
    available_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    locked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class PixivImageSource(Base):
    __tablename__ = "image_sources"
    __table_args__ = (UniqueConstraint("provider", "work_id", "page_index"),)
    id = Column(Integer, primary_key=True)
    image_id = Column(String(10), ForeignKey("images.image_id", ondelete="CASCADE"), nullable=False, index=True)
    provider = Column(String(20), default="pixiv", nullable=False)
    work_id = Column(String(30), nullable=False)
    page_index = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False, index=True)
    metadata_json = Column(JSON, default=dict, nullable=False)
    image = relationship("Image", back_populates="pixiv_sources")


class PixivTagMapping(Base):
    __tablename__ = "pixiv_tag_mappings"
    __table_args__ = (UniqueConstraint("normalized_tag", "group_context", "target_type", "target_id"),)
    id = Column(Integer, primary_key=True)
    normalized_tag = Column(String(255), nullable=False)
    group_context = Column(Integer, default=0, nullable=False)
    target_type = Column(String(20), nullable=False)
    target_id = Column(Integer, nullable=True)
    group_id = Column(Integer, ForeignKey("groups.id", ondelete="CASCADE"), nullable=True, index=True)
    character_id = Column(Integer, ForeignKey("characters.id", ondelete="CASCADE"), nullable=True, index=True)
    feature_tag_id = Column(Integer, ForeignKey("feature_tags.id", ondelete="CASCADE"), nullable=True, index=True)
    original_tag = Column(String(255), nullable=True)
    source = Column(String(20), nullable=False, default="manual")
    confirmed_at = Column(DateTime, nullable=False, default=datetime.utcnow)


@event.listens_for(PixivTagMapping, "before_insert")
@event.listens_for(PixivTagMapping, "before_update")
def _mapping_foreign_keys(mapper, connection, mapping):
    mapping.group_id = mapping.target_id if mapping.target_type == "group" else None
    mapping.character_id = mapping.target_id if mapping.target_type == "character" else None
    mapping.feature_tag_id = mapping.target_id if mapping.target_type == "feature" else None


class PixivFeedback(Base):
    __tablename__ = "pixiv_feedback"
    __table_args__ = (UniqueConstraint("account_revision", "actor_id", "pid"),)
    id = Column(Integer, primary_key=True)
    account_revision = Column(String(32), nullable=False, index=True)
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    pid = Column(String(30), nullable=False)
    value = Column(String(20), nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PixivRecommendationBatch(Base):
    __tablename__ = "pixiv_recommendation_batches"
    id = Column(String(32), primary_key=True)
    account_revision = Column(String(32), nullable=False, index=True)
    mode = Column(String(20), nullable=False)
    items = Column(JSON, nullable=False)
    profile = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ImageTagEvidence(Base):
    __tablename__ = "image_tag_evidence"
    __table_args__ = (UniqueConstraint("image_id", "feature_tag_id", "source"),)
    id = Column(Integer, primary_key=True)
    image_id = Column(String(10), ForeignKey("images.image_id", ondelete="CASCADE"), nullable=False, index=True)
    feature_tag_id = Column(Integer, ForeignKey("feature_tags.id", ondelete="CASCADE"), nullable=False)
    source = Column(String(30), nullable=False)
    confidence = Column(Float, nullable=False)
    confirmed_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    image = relationship("Image", back_populates="tag_evidence")


class PixivCartItem(Base):
    __tablename__ = "pixiv_cart_items"
    __table_args__ = (UniqueConstraint("account_revision", "actor_id", "pid"),)
    id = Column(String(32), primary_key=True)
    account_revision = Column(String(32), nullable=False, index=True)
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    pid = Column(String(30), nullable=False)
    pages = Column(JSON, nullable=False)
    metadata_json = Column(JSON, nullable=False)
    draft = Column(JSON, default=dict, nullable=False)
    cache = Column(JSON, default=dict, nullable=False)
    status = Column(String(30), default="caching", nullable=False)
    cache_job_id = Column(Integer, nullable=True)
    import_job_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class PixivLoginSession(Base):
    __tablename__ = "pixiv_login_sessions"
    id = Column(String(32), primary_key=True)
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    verifier = Column(String(500), nullable=False)
    status = Column(String(30), default="waiting", nullable=False)
    error = Column(String(100), nullable=True)
    expires_at = Column(DateTime, nullable=False)
