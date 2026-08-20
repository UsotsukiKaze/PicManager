from pydantic import BaseModel, Field, field_validator
from typing import List, Optional
from datetime import datetime

from .config import settings

# 分组相关模型
class GroupBase(BaseModel):
    name: str
    aliases: Optional[List[str]] = None
    avatar_url: Optional[str] = None
    description: Optional[str] = None

class GroupCreate(GroupBase):
    pass

class GroupUpdate(BaseModel):
    name: Optional[str] = None
    aliases: Optional[List[str]] = None
    avatar_url: Optional[str] = None
    description: Optional[str] = None

class Group(GroupBase):
    id: int
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

class GroupWithCharacters(Group):
    characters: List['Character'] = []

# 角色相关模型
class CharacterBase(BaseModel):
    name: str
    nicknames: Optional[List[str]] = None
    group_id: int
    feature_tag_ids: Optional[List[int]] = None
    avatar_url: Optional[str] = None
    description: Optional[str] = None

class CharacterCreate(CharacterBase):
    pass

class CharacterUpdate(BaseModel):
    name: Optional[str] = None
    nicknames: Optional[List[str]] = None
    group_id: Optional[int] = None
    feature_tag_ids: Optional[List[int]] = None
    avatar_url: Optional[str] = None
    description: Optional[str] = None

class Character(CharacterBase):
    id: int
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

class CharacterWithGroupName(Character):
    group_name: str = ""
    feature_tags: List[dict] = []

# 特征标签相关模型
class FeatureTagBase(BaseModel):
    name: str
    aliases: Optional[List[str]] = None
    description: Optional[str] = None

class FeatureTagCreate(FeatureTagBase):
    pass

class FeatureTagUpdate(BaseModel):
    name: Optional[str] = None
    aliases: Optional[List[str]] = None
    description: Optional[str] = None

class FeatureTag(FeatureTagBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class EmotionTagBase(BaseModel):
    name: str
    aliases: Optional[List[str]] = None
    description: Optional[str] = None


class EmotionTagCreate(EmotionTagBase):
    pass


class EmotionTagUpdate(BaseModel):
    name: Optional[str] = None
    aliases: Optional[List[str]] = None
    description: Optional[str] = None


class EmotionTag(EmotionTagBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# 图片相关模型
class ImageBase(BaseModel):
    pid: Optional[str] = None
    description: Optional[str] = None
    age_rating: str = "all"

    @field_validator("age_rating")
    @classmethod
    def validate_age_rating(cls, value: str) -> str:
        normalized = str(value or "all").strip().lower()
        if normalized not in {"all", "r12", "r16", "r18"}:
            raise ValueError("age_rating must be one of: all, r12, r16, r18")
        return normalized

class ImageCreate(ImageBase):
    character_ids: List[int] = []
    group_ids: List[int] = []
    feature_tag_ids: List[int] = []


class DirectUploadPrepare(BaseModel):
    filename: str
    content_type: str
    size: int = Field(gt=0)


class DirectUploadFinalize(ImageCreate):
    token: str

class ImageUpdate(BaseModel):
    pid: Optional[str] = None
    description: Optional[str] = None
    character_ids: Optional[List[int]] = None
    group_ids: Optional[List[int]] = None
    feature_tag_ids: Optional[List[int]] = None
    age_rating: Optional[str] = None

    @field_validator("age_rating")
    @classmethod
    def validate_age_rating(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = str(value).strip().lower()
        if normalized not in {"all", "r12", "r16", "r18"}:
            raise ValueError("age_rating must be one of: all, r12, r16, r18")
        return normalized

class Image(ImageBase):
    image_id: str
    original_filename: Optional[str] = None
    file_extension: str
    file_size: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    file_path: str
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

class ImageWithCharacters(Image):
    characters: List[CharacterWithGroupName] = []
    groups: List[Group] = []
    feature_tags: List[FeatureTag] = []

class RandomImageResponse(BaseModel):
    image_id: str
    file_path: str
    pid: Optional[str] = None
    characters: List[CharacterWithGroupName] = []
    groups: List[Group] = []
    feature_tags: List[FeatureTag] = []
    age_rating: str = "all"

# 搜索和查询模型
class ImageSearchParams(BaseModel):
    group_id: Optional[int] = None
    character_id: Optional[int] = None
    feature_tag_id: Optional[int] = None
    pid: Optional[str] = None
    description: Optional[str] = None
    age_rating: Optional[str] = None
    limit: int = Field(default=50, ge=1, le=settings.MAX_PAGE_SIZE)
    offset: int = Field(default=0, ge=0)

class ImageSearchResult(BaseModel):
    images: List[ImageWithCharacters]
    total: int
    offset: int
    limit: int


class EmojiCreate(BaseModel):
    character_ids: List[int] = []
    group_ids: List[int] = []
    emotion_ids: List[int] = []
    description: Optional[str] = None


class EmojiUpdate(BaseModel):
    character_ids: Optional[List[int]] = None
    group_ids: Optional[List[int]] = None
    emotion_ids: Optional[List[int]] = None
    description: Optional[str] = None


class Emoji(BaseModel):
    emoji_id: str
    description: Optional[str] = None
    original_filename: Optional[str] = None
    file_extension: str
    file_size: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    file_path: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class EmojiWithTags(Emoji):
    characters: List[CharacterWithGroupName] = []
    groups: List[Group] = []
    emotions: List[EmotionTag] = []


class EmojiSearchParams(BaseModel):
    group_id: Optional[int] = None
    character_id: Optional[int] = None
    emotion_id: Optional[int] = None
    description: Optional[str] = None
    limit: int = Field(default=50, ge=1, le=settings.MAX_PAGE_SIZE)
    offset: int = Field(default=0, ge=0)


class EmojiSearchResult(BaseModel):
    emojis: List[EmojiWithTags]
    total: int
    offset: int
    limit: int

# 上传相关模型
class UploadImageRequest(BaseModel):
    character_ids: List[int]
    group_ids: List[int] = []
    feature_tag_ids: List[int] = []
    pid: Optional[str] = None
    description: Optional[str] = None
    age_rating: str = "all"

class DuplicateImageMatch(BaseModel):
    image_id: str
    distance: int
    thumbnail_url: str
    character_names: List[str] = Field(default_factory=list)
    pid: Optional[str] = None
    description: Optional[str] = None
    age_rating: str = "all"
    original_filename: Optional[str] = None
    file_size: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    file_status: str = "available"
    group_ids: List[int] = Field(default_factory=list)
    group_names: List[str] = Field(default_factory=list)
    character_ids: List[int] = Field(default_factory=list)
    feature_tag_ids: List[int] = Field(default_factory=list)
    feature_tag_names: List[str] = Field(default_factory=list)

class UploadImageResponse(BaseModel):
    image_id: str
    message: str
    status: str = "success"
    duplicates: List[DuplicateImageMatch] = Field(default_factory=list)
    incoming: Optional[DuplicateImageMatch] = None
    duplicate_algorithm: Optional[str] = None
    duplicate_threshold: Optional[int] = None
    duplicate_token: Optional[str] = None

class DuplicateImageResolveRequest(BaseModel):
    token: str = Field(min_length=32, max_length=16384)
    keep: str = Field(min_length=3, max_length=32)
    metadata_sources: dict[str, str] = Field(default_factory=dict)

    @field_validator("metadata_sources")
    @classmethod
    def validate_metadata_sources(cls, values: dict[str, str]) -> dict[str, str]:
        allowed_fields = {"pid", "description", "age_rating", "groups", "characters", "feature_tags"}
        if set(values) - allowed_fields or any(value not in {"keep", "other", "merge"} for value in values.values()):
            raise ValueError("Invalid duplicate metadata source")
        return values

class ExistingDuplicateResolveRequest(BaseModel):
    image_ids: List[str] = Field(min_length=2, max_length=20)
    action: str = Field(pattern="^(distinct|merge)$")
    keep_image_id: Optional[str] = Field(default=None, min_length=10, max_length=10)
    metadata_sources: dict[str, str] = Field(default_factory=dict)

    @field_validator("image_ids")
    @classmethod
    def validate_image_ids(cls, values: List[str]) -> List[str]:
        unique = list(dict.fromkeys(values))
        if len(unique) != 2 or any(len(value) != 10 for value in unique):
            raise ValueError("Exactly two valid image IDs are required")
        return unique

    @field_validator("metadata_sources")
    @classmethod
    def validate_existing_metadata_sources(cls, values: dict[str, str]) -> dict[str, str]:
        return DuplicateImageResolveRequest.validate_metadata_sources(values)

class ExistingDuplicateScanRequest(BaseModel):
    excluded_pairs: List[List[str]] = Field(default_factory=list, max_length=500)

    @field_validator("excluded_pairs")
    @classmethod
    def validate_excluded_pairs(cls, pairs: List[List[str]]) -> List[List[str]]:
        normalized = []
        seen = set()
        for pair in pairs:
            unique = sorted(set(pair))
            if len(unique) != 2 or any(len(value) != 10 for value in unique):
                raise ValueError("Excluded pairs must contain two valid image IDs")
            key = tuple(unique)
            if key not in seen:
                seen.add(key)
                normalized.append(unique)
        return normalized


class PixivUpgradeResolveRequest(BaseModel):
    token: str = Field(min_length=32, max_length=16384)
    action: str = Field(pattern="^(replace|skip)$")

# Temp目录上传
class TempImageUpload(BaseModel):
    filename: str
    character_ids: List[int]
    group_ids: List[int] = []
    feature_tag_ids: List[int] = []
    pid: Optional[str] = None
    description: Optional[str] = None
    age_rating: str = "all"


class TempDuplicateResolveRequest(BaseModel):
    token: str = Field(min_length=32, max_length=16384)
    keep: str = Field(pattern="^(existing|temp)$")
    metadata: ImageCreate

# 批量上传
class BatchUploadImageRequest(BaseModel):
    uploads: List[UploadImageRequest]

class BatchUploadImageResponse(BaseModel):
    success_count: int
    failed_count: int
    results: List[UploadImageResponse]

# Lightweight public counters used by the home page.
class PublicSystemStatus(BaseModel):
    total_images: int
    total_emojis: int = 0
    total_groups: int
    total_characters: int


# Admin-only storage and maintenance diagnostics.
class SystemStatus(PublicSystemStatus):
    available_images: int = 0
    missing_images: int = 0
    archived_images: int = 0
    thumb_missing: int = 0
    thumb_failed: int = 0
    temp_images_count: int
    store_path: str
    temp_path: str


# ==================== 用户管理相关模型 ====================

# 用户登录
class UserLogin(BaseModel):
    qq_number: str
    password: Optional[str] = None  # 只有管理员需要

class GuestLogin(BaseModel):
    pass  # 游客无需任何参数

# 用户信息
class UserInfo(BaseModel):
    id: int
    qq_number: str
    role: str
    nickname: Optional[str] = None
    avatar_url: Optional[str] = None
    created_at: datetime
    
    class Config:
        from_attributes = True

class UserSession(BaseModel):
    user: Optional[UserInfo] = None
    is_guest: bool = False
    guest_ip: Optional[str] = None
    guest_name: Optional[str] = None

# 修改密码
class ChangePassword(BaseModel):
    old_password: str
    new_password: str

# 管理员管理
class AdminCreate(BaseModel):
    qq_number: str

class AdminInfo(BaseModel):
    id: int
    qq_number: str
    role: str
    nickname: Optional[str] = None
    avatar_url: Optional[str] = None
    created_at: datetime
    
    class Config:
        from_attributes = True

# 待审核请求
class PendingRequestInfo(BaseModel):
    id: int
    request_type: str
    status: str
    user_qq: Optional[str] = None
    user_nickname: Optional[str] = None
    user_avatar: Optional[str] = None
    guest_ip: Optional[str] = None
    guest_name: Optional[str] = None
    image_id: Optional[str] = None
    image_data: Optional[dict] = None
    temp_file_path: Optional[str] = None
    original_filename: Optional[str] = None
    group_info: Optional[dict] = None  # 分组信息: {id, name}
    character_names: Optional[list] = None  # 角色名称列表
    character_info: Optional[dict] = None  # 角色信息: {id, name, group_id, group_name, nicknames}
    # 原图信息（edit和delete时显示）
    original_image: Optional[dict] = None  # 原图信息: {image_id, pid, description, character_names, file_path}
    original_group: Optional[dict] = None  # 原分组信息: {id, name, description}
    original_character: Optional[dict] = None  # 原角色信息: {id, name, group_name, nicknames, description}
    pending_image: Optional[dict] = None  # 待审核图片信息: {file_size, width, height, mime_type, format}
    target_info: Optional[dict] = None  # 被操作条目: {type, id, name}
    changes: Optional[List[dict]] = None  # 有效变更字段: [{field, label, before, after}]
    has_changes: Optional[bool] = None
    created_at: datetime
    reviewed_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    
    class Config:
        from_attributes = True

class PendingRequestAction(BaseModel):
    action: str  # approve 或 reject
    reason: Optional[str] = None

class SetNickname(BaseModel):
    nickname: str

# 游客限制信息
class GuestLimitInfo(BaseModel):
    remaining_operations: int
    daily_limit: int


class BotLoginTicketCreate(BaseModel):
    qq_number: str
    purpose: str = "login"
    redirect_path: Optional[str] = "/"
    created_by: Optional[str] = None
    nickname: Optional[str] = None
    avatar_url: Optional[str] = None


class BotLoginTicketResponse(BaseModel):
    ticket: str
    login_url: str
    lan_login_url: Optional[str] = None
    expires_at: datetime
    purpose: str
    qq_number: str


class BotAgeRatingUpdate(BaseModel):
    age_rating: str
    actor_id: str
    actor_role: str
    timestamp: int
    nonce: str
    signature: str


class BotAgeAuthorizationCreate(BaseModel):
    group_id: str
    requested_by: str
    requested_by_name: Optional[str] = None
    source_group_name: Optional[str] = None
    requested_by_role: str
    timestamp: int
    nonce: str
    signature: str


class BotAgeAuthorizationDecision(BaseModel):
    reviewer_id: str
    timestamp: int
    nonce: str
    signature: str


class BotAgeAuthorizationResolve(BaseModel):
    authorization_group_id: str
    message_id: str


class QQTicketLogin(BaseModel):
    ticket: str
    purpose: str = "login"


class SSOExchangeRequest(BaseModel):
    ticket: str


class SSOIdentityResponse(BaseModel):
    qq_number: str
    nickname: Optional[str] = None
    avatar_url: Optional[str] = None
    role: str
