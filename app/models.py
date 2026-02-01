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

# 图片与角色的多对多关联表
image_character_association = Table(
    'image_character_association',
    Base.metadata,
    Column('image_id', String, ForeignKey('images.image_id'), primary_key=True),
    Column('character_id', Integer, ForeignKey('characters.id'), primary_key=True)
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
    is_guest = Column(String(5), nullable=False, default="false")  # "true" 或 "false"
    created_at = Column(DateTime, default=datetime.utcnow)
    last_activity = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)  # 过期时间
    
    # 关联用户
    user = relationship("User")


class Group(Base):
    """分组表 - 游戏/IP分组"""
    __tablename__ = 'groups'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关联角色
    characters = relationship("Character", back_populates="group", cascade="all, delete-orphan")


class Character(Base):
    """角色表"""
    __tablename__ = 'characters'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, index=True)
    group_id = Column(Integer, ForeignKey('groups.id'), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关联分组
    group = relationship("Group", back_populates="characters")
    # 关联图片（多对多）
    images = relationship("Image", secondary=image_character_association, back_populates="characters")
    # 角色昵称
    nicknames = relationship("CharacterNickname", back_populates="character", cascade="all, delete-orphan")


class CharacterNickname(Base):
    """角色昵称表"""
    __tablename__ = 'character_nicknames'

    id = Column(Integer, primary_key=True, autoincrement=True)
    character_id = Column(Integer, ForeignKey('characters.id'), nullable=False, index=True)
    nickname = Column(String(255), nullable=False, index=True)

    character = relationship("Character", back_populates="nicknames")


class Image(Base):
    """图片表 - 核心数据表"""
    __tablename__ = 'images'
    
    # 10位十六进制数作为主键
    image_id = Column(String(10), primary_key=True)  
    # PID - 车牌号（Pixiv ID等）
    pid = Column(String(255), nullable=True, index=True)
    # 图片描述
    description = Column(Text, nullable=True)
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
    # 创建和更新时间
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关联角色（多对多）
    characters = relationship("Character", secondary=image_character_association, back_populates="images")
    
    def __repr__(self):
        return f"<Image(image_id='{self.image_id}', pid='{self.pid}')>"


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