from sqlalchemy import Column, String, Integer, Text, Table, ForeignKey, DateTime, Enum, Date
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
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
    password_hash = Column(String(255), nullable=True)  # 只有管理员需要密码
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


class FeatureTagAlias(Base):
    """Feature tag alias table."""
    __tablename__ = 'feature_tag_aliases'

    id = Column(Integer, primary_key=True, autoincrement=True)
    feature_tag_id = Column(Integer, ForeignKey('feature_tags.id'), nullable=False, index=True)
    alias = Column(String(255), nullable=False, index=True)

    feature_tag = relationship("FeatureTag", back_populates="aliases")


class EmotionTag(Base):
    """Emoji-only emotion tags such as happy, angry, or confused."""
    __tablename__ = 'emotion_tags'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    emojis = relationship("Emoji", secondary=emoji_emotion_association, back_populates="emotions")
    aliases = relationship("EmotionTagAlias", back_populates="emotion", cascade="all, delete-orphan")


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
    age_rating = Column(String(10), nullable=False, default=AgeRating.ALL.value, index=True)
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
    # 创建和更新时间
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关联角色（多对多）
    characters = relationship("Character", secondary=image_character_association, back_populates="images")
    groups = relationship("Group", secondary=image_group_association, back_populates="images")
    feature_tags = relationship("FeatureTag", secondary=image_feature_tag_association, back_populates="images")
    
    def __repr__(self):
        return f"<Image(image_id='{self.image_id}', pid='{self.pid}')>"


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


class GuestbookMessage(Base):
    """Public messages left on the personal homepage."""
    __tablename__ = "guestbook_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    nickname = Column(String(32), nullable=False)
    content = Column(Text, nullable=False)
    parent_id = Column(Integer, ForeignKey("guestbook_messages.id"), nullable=True, index=True)
    author_qq = Column(String(20), nullable=True, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
