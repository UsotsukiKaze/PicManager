from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

# 分组相关模型
class GroupBase(BaseModel):
    name: str
    description: Optional[str] = None

class GroupCreate(GroupBase):
    pass

class GroupUpdate(BaseModel):
    name: Optional[str] = None
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
    description: Optional[str] = None

class CharacterCreate(CharacterBase):
    pass

class CharacterUpdate(BaseModel):
    name: Optional[str] = None
    nicknames: Optional[List[str]] = None
    group_id: Optional[int] = None
    description: Optional[str] = None

class Character(CharacterBase):
    id: int
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

class CharacterWithGroupName(Character):
    group_name: str = ""

# 图片相关模型
class ImageBase(BaseModel):
    pid: Optional[str] = None
    description: Optional[str] = None

class ImageCreate(ImageBase):
    character_ids: List[int] = []

class ImageUpdate(BaseModel):
    pid: Optional[str] = None
    description: Optional[str] = None
    character_ids: Optional[List[int]] = None

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

class RandomImageResponse(BaseModel):
    image_id: str
    file_path: str
    pid: Optional[str] = None
    characters: List[CharacterWithGroupName] = []

# 搜索和查询模型
class ImageSearchParams(BaseModel):
    group_id: Optional[int] = None
    character_id: Optional[int] = None
    pid: Optional[str] = None
    description: Optional[str] = None
    limit: Optional[int] = 50
    offset: Optional[int] = 0

class ImageSearchResult(BaseModel):
    images: List[ImageWithCharacters]
    total: int
    offset: int
    limit: int

# 上传相关模型
class UploadImageRequest(BaseModel):
    character_ids: List[int]
    pid: Optional[str] = None
    description: Optional[str] = None

class UploadImageResponse(BaseModel):
    image_id: str
    message: str

# Temp目录上传
class TempImageUpload(BaseModel):
    filename: str
    character_ids: List[int]
    pid: Optional[str] = None
    description: Optional[str] = None

# 批量上传
class BatchUploadImageRequest(BaseModel):
    uploads: List[UploadImageRequest]

class BatchUploadImageResponse(BaseModel):
    success_count: int
    failed_count: int
    results: List[UploadImageResponse]

# 系统状态
class SystemStatus(BaseModel):
    total_images: int
    total_groups: int
    total_characters: int
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