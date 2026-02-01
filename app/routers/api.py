from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Request
from sqlalchemy.orm import Session
from typing import List, Optional, Union
from ..database import get_db_context
from ..services import GroupService, CharacterService, ImageService, SystemService
from ..models import User, UserRole, PendingRequest, GuestLimit, ImageViewCount, CharacterQueryCount, RequestStatus, Group, Character
from .. import models
from .. import schemas
from ..config import settings
from ..logger import log_error
from .auth import get_current_session, check_guest_limit
import tempfile
import os
import json
import shutil
from datetime import date, datetime

router = APIRouter()

# 分组相关路由
@router.post("/groups/", response_model=Union[schemas.Group, dict])
def create_group(group: schemas.GroupCreate, request: Request):
    """创建分组"""
    with get_db_context() as db:
        existing = db.query(models.Group).filter(models.Group.name == group.name).first()
        if existing:
            raise HTTPException(status_code=400, detail="分组名称已存在")

        session = get_current_session(request, db)
        is_admin = False
        user_id = None
        guest_ip = None

        if session:
            if session.get("is_guest"):
                guest_ip = session.get("guest_ip")
                if not check_guest_limit(db, guest_ip):
                    raise HTTPException(status_code=429, detail="今日操作次数已用完")
            else:
                user = db.query(User).filter(User.id == session["user_id"]).first()
                if user:
                    user_id = user.id
                    is_admin = user.role in [UserRole.ROOT.value, UserRole.ADMIN.value]

        if is_admin:
            return GroupService.create_group(db, group)

        pending_request = PendingRequest(
            request_type="group_add",
            user_id=user_id,
            guest_ip=guest_ip,
            image_data=json.dumps({
                "name": group.name,
                "description": group.description
            })
        )
        db.add(pending_request)
        db.commit()
        return {"message": "待审核你的提交，可到个人中心查看进度"}

@router.get("/groups/", response_model=List[schemas.Group])
def get_groups(skip: int = 0, limit: int = 100):
    """获取分组列表"""
    with get_db_context() as db:
        return GroupService.get_groups(db, skip, limit)

@router.get("/groups/{group_id}", response_model=schemas.Group)
def get_group(group_id: int):
    """获取单个分组"""
    with get_db_context() as db:
        group = GroupService.get_group(db, group_id)
        if not group:
            raise HTTPException(status_code=404, detail="Group not found")
        return group

@router.put("/groups/{group_id}", response_model=Union[schemas.Group, dict])
def update_group(group_id: int, group_update: schemas.GroupUpdate, request: Request):
    """更新分组"""
    with get_db_context() as db:
        session = get_current_session(request, db)
        is_admin = False
        user_id = None
        guest_ip = None

        if session:
            if session.get("is_guest"):
                guest_ip = session.get("guest_ip")
                if not check_guest_limit(db, guest_ip):
                    raise HTTPException(status_code=429, detail="今日操作次数已用完")
            else:
                user = db.query(User).filter(User.id == session["user_id"]).first()
                if user:
                    user_id = user.id
                    is_admin = user.role in [UserRole.ROOT.value, UserRole.ADMIN.value]

        # 校验分组是否存在
        existing = db.query(models.Group).filter(models.Group.id == group_id).first()
        if not existing:
            raise HTTPException(status_code=404, detail="Group not found")

        if is_admin:
            group = GroupService.update_group(db, group_id, group_update)
            return group

        update_data = group_update.dict(exclude_unset=True)
        update_data["group_id"] = group_id
        pending_request = PendingRequest(
            request_type="group_edit",
            user_id=user_id,
            guest_ip=guest_ip,
            image_data=json.dumps(update_data)
        )
        db.add(pending_request)
        db.commit()
        return {"message": "待审核你的提交，可到个人中心查看进度"}

@router.delete("/groups/{group_id}")
def delete_group(group_id: int, request: Request):
    """删除分组"""
    with get_db_context() as db:
        session = get_current_session(request, db)
        is_admin = False
        user_id = None
        guest_ip = None

        if session:
            if session.get("is_guest"):
                guest_ip = session.get("guest_ip")
                if not check_guest_limit(db, guest_ip):
                    raise HTTPException(status_code=429, detail="今日操作次数已用完")
            else:
                user = db.query(User).filter(User.id == session["user_id"]).first()
                if user:
                    user_id = user.id
                    is_admin = user.role in [UserRole.ROOT.value, UserRole.ADMIN.value]

        # 校验分组是否存在
        existing = db.query(models.Group).filter(models.Group.id == group_id).first()
        if not existing:
            raise HTTPException(status_code=404, detail="Group not found")

        if is_admin:
            success = GroupService.delete_group(db, group_id)
            if not success:
                raise HTTPException(status_code=404, detail="Group not found")
            return {"message": "Group deleted successfully"}

        pending_request = PendingRequest(
            request_type="group_delete",
            user_id=user_id,
            guest_ip=guest_ip,
            image_data=json.dumps({
                "group_id": group_id
            })
        )
        db.add(pending_request)
        db.commit()
        return {"message": "待审核你的提交，可到个人中心查看进度"}

# 角色相关路由
@router.post("/characters/", response_model=Union[schemas.CharacterWithGroupName, dict])
def create_character(character: schemas.CharacterCreate, request: Request):
    """创建角色"""
    with get_db_context() as db:
        existing = db.query(models.Character).filter(
            models.Character.group_id == character.group_id,
            models.Character.name == character.name
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="该分组下已存在同名角色")

        session = get_current_session(request, db)
        is_admin = False
        user_id = None
        guest_ip = None

        if session:
            if session.get("is_guest"):
                guest_ip = session.get("guest_ip")
                if not check_guest_limit(db, guest_ip):
                    raise HTTPException(status_code=429, detail="今日操作次数已用完")
            else:
                user = db.query(User).filter(User.id == session["user_id"]).first()
                if user:
                    user_id = user.id
                    is_admin = user.role in [UserRole.ROOT.value, UserRole.ADMIN.value]

        # 校验分组是否存在
        group_exists = db.query(models.Group).filter(models.Group.id == character.group_id).first()
        if not group_exists:
            raise HTTPException(status_code=400, detail="选中的分组不存在")

        if is_admin:
            return CharacterService.create_character(db, character)

        pending_request = PendingRequest(
            request_type="character_add",
            user_id=user_id,
            guest_ip=guest_ip,
            image_data=json.dumps({
                "name": character.name,
                "group_id": character.group_id,
                "description": character.description,
                "nicknames": character.nicknames
            })
        )
        db.add(pending_request)
        db.commit()
        return {"message": "待审核你的提交，可到个人中心查看进度"}

@router.get("/characters/", response_model=List[schemas.CharacterWithGroupName])
def get_characters(group_id: Optional[int] = None, skip: int = 0, limit: int = 100):
    """获取角色列表"""
    with get_db_context() as db:
        return CharacterService.get_characters(db, group_id, skip, limit)

@router.get("/characters/{character_id}", response_model=schemas.CharacterWithGroupName)
def get_character(character_id: int):
    """获取单个角色"""
    with get_db_context() as db:
        character = CharacterService.get_character(db, character_id)
        if not character:
            raise HTTPException(status_code=404, detail="Character not found")
        return character

@router.put("/characters/{character_id}", response_model=Union[schemas.CharacterWithGroupName, dict])
def update_character(character_id: int, character_update: schemas.CharacterUpdate, request: Request):
    """更新角色"""
    with get_db_context() as db:
        session = get_current_session(request, db)
        is_admin = False
        user_id = None
        guest_ip = None

        if session:
            if session.get("is_guest"):
                guest_ip = session.get("guest_ip")
                if not check_guest_limit(db, guest_ip):
                    raise HTTPException(status_code=429, detail="今日操作次数已用完")
            else:
                user = db.query(User).filter(User.id == session["user_id"]).first()
                if user:
                    user_id = user.id
                    is_admin = user.role in [UserRole.ROOT.value, UserRole.ADMIN.value]

        # 校验角色是否存在
        existing = db.query(models.Character).filter(models.Character.id == character_id).first()
        if not existing:
            raise HTTPException(status_code=404, detail="Character not found")

        if character_update.group_id:
            group_exists = db.query(models.Group).filter(models.Group.id == character_update.group_id).first()
            if not group_exists:
                raise HTTPException(status_code=400, detail="选中的分组不存在")

        if is_admin:
            character = CharacterService.update_character(db, character_id, character_update)
            return character

        update_data = character_update.dict(exclude_unset=True)
        update_data["character_id"] = character_id
        pending_request = PendingRequest(
            request_type="character_edit",
            user_id=user_id,
            guest_ip=guest_ip,
            image_data=json.dumps(update_data)
        )
        db.add(pending_request)
        db.commit()
        return {"message": "待审核你的提交，可到个人中心查看进度"}

@router.delete("/characters/{character_id}")
def delete_character(character_id: int, request: Request):
    """删除角色"""
    with get_db_context() as db:
        session = get_current_session(request, db)
        is_admin = False
        user_id = None
        guest_ip = None

        if session:
            if session.get("is_guest"):
                guest_ip = session.get("guest_ip")
                if not check_guest_limit(db, guest_ip):
                    raise HTTPException(status_code=429, detail="今日操作次数已用完")
            else:
                user = db.query(User).filter(User.id == session["user_id"]).first()
                if user:
                    user_id = user.id
                    is_admin = user.role in [UserRole.ROOT.value, UserRole.ADMIN.value]

        # 校验角色是否存在
        existing = db.query(models.Character).filter(models.Character.id == character_id).first()
        if not existing:
            raise HTTPException(status_code=404, detail="Character not found")

        if is_admin:
            success = CharacterService.delete_character(db, character_id)
            if not success:
                raise HTTPException(status_code=404, detail="Character not found")
            return {"message": "Character deleted successfully"}

        pending_request = PendingRequest(
            request_type="character_delete",
            user_id=user_id,
            guest_ip=guest_ip,
            image_data=json.dumps({
                "character_id": character_id
            })
        )
        db.add(pending_request)
        db.commit()
        return {"message": "待审核你的提交，可到个人中心查看进度"}

# 图片相关路由
@router.get("/images/search", response_model=schemas.ImageSearchResult)
def search_images(
    group_id: Optional[int] = None,
    character_id: Optional[int] = None,
    pid: Optional[str] = None,
    description: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
):
    """搜索图片"""
    with get_db_context() as db:
        # 仅在明确按角色查询时统计角色查询次数（排除随机抽取）
        if character_id:
            character = db.query(models.Character).filter(models.Character.id == character_id).first()
            if character:
                record = db.query(CharacterQueryCount).filter(
                    CharacterQueryCount.character_id == character_id
                ).first()
                if not record:
                    record = CharacterQueryCount(character_id=character_id, query_count=0)
                    db.add(record)
                record.query_count += 1

        params = schemas.ImageSearchParams(
            group_id=group_id,
            character_id=character_id,
            pid=pid,
            description=description,
            limit=limit,
            offset=offset
        )
        images, total = ImageService.search_images(db, params)
        return schemas.ImageSearchResult(
            images=images,
            total=total,
            offset=offset,
            limit=limit
        )

@router.get("/images/random", response_model=schemas.RandomImageResponse)
def get_random_image(
    group_id: Optional[int] = None,
    character_id: Optional[int] = None,
    exclude_group_id: Optional[int] = None
):
    """随机获取图片"""
    with get_db_context() as db:
        image = ImageService.get_random_image(db, group_id, character_id, exclude_group_id)
        if not image:
            raise HTTPException(status_code=404, detail="Image not found")
        return image

@router.get("/images/{image_id}", response_model=schemas.ImageWithCharacters)
def get_image(image_id: str):
    """获取单个图片信息"""
    with get_db_context() as db:
        record = db.query(ImageViewCount).filter(ImageViewCount.image_id == image_id).first()
        if not record:
            record = ImageViewCount(image_id=image_id, view_count=0)
            db.add(record)
        record.view_count += 1

        image = ImageService.get_image(db, image_id)
        if not image:
            raise HTTPException(status_code=404, detail="Image not found")
        return image


@router.get("/rankings")
def get_rankings(limit: int = 10):
    """获取贡献榜、角色人气榜、图片人气榜"""
    with get_db_context() as db:
        # 贡献榜（仅登录用户）
        approved_requests = db.query(PendingRequest).filter(
            PendingRequest.user_id.isnot(None),
            PendingRequest.status == RequestStatus.APPROVED.value
        ).all()

        weights = {
            "add": 3,
            "edit": 1,
            "delete": 1,
            "group_add": 2,
            "group_edit": 1,
            "group_delete": 1,
            "character_add": 2,
            "character_edit": 1,
            "character_delete": 1
        }

        contribution_map = {}
        for req in approved_requests:
            if not req.user_id:
                continue
            user_score = contribution_map.setdefault(req.user_id, {
                "score": 0,
                "counts": {}
            })
            user_score["score"] += weights.get(req.request_type, 0)

        user_ids = list(contribution_map.keys())
        users = db.query(User).filter(User.id.in_(user_ids)).all() if user_ids else []
        user_map = {user.id: user for user in users}

        contribution_list = []
        for user_id, info in contribution_map.items():
            user = user_map.get(user_id)
            if not user:
                continue
            contribution_list.append({
                "user_id": user_id,
                "nickname": user.nickname or user.qq_number,
                "qq_number": user.qq_number,
                "avatar_url": user.avatar_url,
                "role": user.role,
                "score": info["score"]
            })

        contribution_list.sort(key=lambda item: item["score"], reverse=True)
        contribution_list = contribution_list[:limit]

        # 角色人气榜（无统计时回退到最新角色）
        character_query_rows = db.query(CharacterQueryCount).order_by(
            CharacterQueryCount.query_count.desc()
        ).limit(limit).all()
        if character_query_rows:
            character_ids = [row.character_id for row in character_query_rows]
            characters = db.query(Character).filter(Character.id.in_(character_ids)).all()
            character_map = {c.id: c for c in characters}

            character_rank = []
            for row in character_query_rows:
                character = character_map.get(row.character_id)
                if not character:
                    continue
                group = db.query(Group).filter(Group.id == character.group_id).first()
                character_rank.append({
                    "character_id": character.id,
                    "name": character.name,
                    "group_name": group.name if group else None,
                    "count": row.query_count
                })
        else:
            latest_characters = db.query(Character).order_by(Character.created_at.desc()).limit(limit).all()
            character_rank = []
            for character in latest_characters:
                group = db.query(Group).filter(Group.id == character.group_id).first()
                character_rank.append({
                    "character_id": character.id,
                    "name": character.name,
                    "group_name": group.name if group else None,
                    "count": 0
                })

        # 图片人气榜（无统计时回退到最新图片）
        image_view_rows = db.query(ImageViewCount).order_by(
            ImageViewCount.view_count.desc()
        ).limit(limit).all()
        if image_view_rows:
            image_ids = [row.image_id for row in image_view_rows]
            images = db.query(models.Image).filter(models.Image.image_id.in_(image_ids)).all()
            image_map = {img.image_id: img for img in images}

            image_rank = []
            for row in image_view_rows:
                image = image_map.get(row.image_id)
                if not image:
                    continue
                image_rank.append({
                    "image_id": image.image_id,
                    "file_extension": image.file_extension,
                    "count": row.view_count
                })
        else:
            latest_images = db.query(models.Image).order_by(models.Image.created_at.desc()).limit(limit).all()
            image_rank = [
                {
                    "image_id": image.image_id,
                    "file_extension": image.file_extension,
                    "count": 0
                }
                for image in latest_images
            ]

        return {
            "contribution": contribution_list,
            "characters": character_rank,
            "images": image_rank
        }

@router.put("/images/{image_id}")
def update_image(image_id: str, image_update: schemas.ImageUpdate, request: Request):
    """更新图片信息"""
    # 检查用户权限
    with get_db_context() as db:
        session = get_current_session(request, db)
        is_admin = False
        user_id = None
        guest_ip = None
        
        if session:
            if session.get("is_guest"):
                guest_ip = session.get("guest_ip")
                if not check_guest_limit(db, guest_ip):
                    raise HTTPException(status_code=429, detail="今日操作次数已用完")
            else:
                user = db.query(User).filter(User.id == session["user_id"]).first()
                if user:
                    user_id = user.id
                    is_admin = user.role in [UserRole.ROOT.value, UserRole.ADMIN.value]

        # 校验图片是否存在
        db_image = db.query(models.Image).filter(models.Image.image_id == image_id).first()
        if not db_image:
            raise HTTPException(status_code=404, detail="Image not found")

        # 校验角色ID（如有）
        if image_update.character_ids is not None:
            try:
                character_ids = [int(cid) for cid in image_update.character_ids]
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="Invalid character_ids format")

            if character_ids:
                existing_characters = db.query(models.Character).filter(
                    models.Character.id.in_(character_ids)
                ).all()
                if len(existing_characters) != len(character_ids):
                    missing_ids = set(character_ids) - set(c.id for c in existing_characters)
                    raise HTTPException(status_code=400, detail=f"选中的某些角色不存在: {missing_ids}")
            image_update.character_ids = character_ids
        
        if is_admin:
            # 管理员直接更新
            image = ImageService.update_image(db, image_id, image_update)
            if not image:
                raise HTTPException(status_code=404, detail="Image not found")
            return image
        else:
            # 非管理员，创建待审核请求
            pending_request = PendingRequest(
                request_type="edit",
                user_id=user_id,
                guest_ip=guest_ip,
                image_id=image_id,
                image_data=json.dumps({
                    "pid": image_update.pid,
                    "description": image_update.description,
                    "character_ids": image_update.character_ids
                })
            )
            db.add(pending_request)
            db.commit()
            
            return {"message": "待审核你的提交，可到个人中心查看进度"}

@router.delete("/images/{image_id}")
def delete_image(image_id: str, request: Request):
    """删除图片"""
    # 检查用户权限
    with get_db_context() as db:
        session = get_current_session(request, db)
        is_admin = False
        user_id = None
        guest_ip = None
        
        if session:
            if session.get("is_guest"):
                guest_ip = session.get("guest_ip")
                if not check_guest_limit(db, guest_ip):
                    raise HTTPException(status_code=429, detail="今日操作次数已用完")
            else:
                user = db.query(User).filter(User.id == session["user_id"]).first()
                if user:
                    user_id = user.id
                    is_admin = user.role in [UserRole.ROOT.value, UserRole.ADMIN.value]

        # 校验图片是否存在
        db_image = db.query(models.Image).filter(models.Image.image_id == image_id).first()
        if not db_image:
            raise HTTPException(status_code=404, detail="Image not found")
        
        if is_admin:
            # 管理员直接删除
            store_path = settings.STORE_PATH
            success = ImageService.delete_image(db, image_id, store_path)
            if not success:
                raise HTTPException(status_code=404, detail="Image not found")
            return {"message": "Image deleted successfully"}
        else:
            # 非管理员，创建待审核请求
            pending_request = PendingRequest(
                request_type="delete",
                user_id=user_id,
                guest_ip=guest_ip,
                image_id=image_id
            )
            db.add(pending_request)
            db.commit()
            
            return {"message": "待审核你的提交，可到个人中心查看进度"}

# 上传相关路由
@router.post("/upload/single", response_model=schemas.UploadImageResponse)
async def upload_single_image(
    request: Request,
    file: UploadFile = File(...),
    character_ids: str = Form(...),  # JSON字符串形式的角色ID列表
    group_id: Optional[str] = Form(None),
    pid: Optional[str] = Form(None),
    description: Optional[str] = Form(None)
):
    """单张图片上传"""
    # 解析角色ID列表
    try:
        character_id_list = json.loads(character_ids) if isinstance(character_ids, str) else character_ids
        # 确保是列表
        if not isinstance(character_id_list, list):
            character_id_list = [character_id_list]
        # 统一为int并去重
        character_id_list = [int(cid) for cid in character_id_list]
        character_id_list = list(dict.fromkeys(character_id_list))
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid character_ids format: {str(e)}")
    
    # 验证文件类型
    allowed_extensions = {'jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp'}
    file_extension = file.filename.split('.')[-1].lower()
    if file_extension not in allowed_extensions:
        raise HTTPException(status_code=400, detail="Unsupported file type")
    
    # 检查用户权限
    with get_db_context() as db:
        session = get_current_session(request, db)
        is_admin = False
        user_id = None
        guest_ip = None
        
        if session:
            if session.get("is_guest"):
                guest_ip = session.get("guest_ip")
                # 检查游客操作限制
                if not check_guest_limit(db, guest_ip):
                    raise HTTPException(status_code=429, detail="今日操作次数已用完")
            else:
                user = db.query(User).filter(User.id == session["user_id"]).first()
                if user:
                    user_id = user.id
                    is_admin = user.role in [UserRole.ROOT.value, UserRole.ADMIN.value]
        
        # 读取文件内容
        content = await file.read()
        
        if is_admin:
            # 管理员直接上传
            with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{file_extension}') as temp_file:
                temp_file.write(content)
                temp_file_path = temp_file.name
            
            try:
                store_path = settings.STORE_PATH
                image_create = schemas.ImageCreate(
                    character_ids=character_id_list,
                    pid=pid,
                    description=description
                )
                
                image = ImageService.create_image(
                    db, image_create, temp_file_path, file.filename, file_extension, store_path
                )

                # 记录贡献度（管理员/Root直接通过）
                if user_id:
                    pending_request = PendingRequest(
                        request_type="add",
                        user_id=user_id,
                        status=RequestStatus.APPROVED.value,
                        image_id=image.image_id,
                        image_data=json.dumps({
                            "character_ids": character_id_list,
                            "group_id": int(group_id) if group_id else None,
                            "pid": pid,
                            "description": description
                        }),
                        reviewed_at=datetime.utcnow(),
                        reviewed_by=user_id
                    )
                    db.add(pending_request)
                    db.commit()
                
                return schemas.UploadImageResponse(
                    image_id=image.image_id,
                    message="Image uploaded successfully"
                )
            finally:
                try:
                    os.unlink(temp_file_path)
                except:
                    pass
        else:
            # 非管理员，创建待审核请求
            pending_path = settings.PENDING_PATH
            os.makedirs(pending_path, exist_ok=True)
            
            # 验证character_ids是否存在（如果提供了）
            validation_error = None
            if character_id_list:
                try:
                    existing_characters = db.query(models.Character).filter(
                        models.Character.id.in_(character_id_list)
                    ).all()
                    if len(existing_characters) != len(character_id_list):
                        missing_ids = set(character_id_list) - set(c.id for c in existing_characters)
                        validation_error = f"选中的某些角色不存在，无效ID: {missing_ids}"
                except Exception as e:
                    validation_error = f"角色验证失败: {str(e)}"
            
            # 验证group_id是否存在（如果提供了）
            if not validation_error and group_id:
                try:
                    group_id_int = int(group_id)
                    group_exists = db.query(models.Group).filter(
                        models.Group.id == group_id_int
                    ).first()
                    if not group_exists:
                        validation_error = f"选中的分组不存在 (ID: {group_id_int})"
                except (ValueError, TypeError) as e:
                    validation_error = f"分组ID格式错误: {str(e)}"
            
            if validation_error:
                raise HTTPException(status_code=400, detail=validation_error)
            
            # 生成唯一文件名
            import uuid
            unique_filename = f"{uuid.uuid4().hex}.{file_extension}"
            pending_file_path = os.path.join(pending_path, unique_filename)
            
            with open(pending_file_path, 'wb') as f:
                f.write(content)
            
            # 创建待审核记录
            try:
                pending_request = PendingRequest(
                    request_type="add",
                    user_id=user_id,
                    guest_ip=guest_ip,
                    image_data=json.dumps({
                        "character_ids": character_id_list,
                        "group_id": int(group_id) if group_id else None,
                        "pid": pid,
                        "description": description
                    }),
                    temp_file_path=pending_file_path,
                    original_filename=file.filename
                )
                db.add(pending_request)
                db.commit()
                
                return schemas.UploadImageResponse(
                    image_id="pending",
                    message="待审核你的提交，可到个人中心查看进度"
                )
            except Exception as e:
                # 如果数据库操作失败，清理临时文件
                try:
                    if os.path.exists(pending_file_path):
                        os.unlink(pending_file_path)
                except:
                    pass
                raise HTTPException(status_code=500, detail=f"创建待审核请求失败: {str(e)}")

@router.get("/upload/temp-count")
def get_temp_images_count():
    """获取temp目录中的图片数量"""
    temp_path = settings.TEMP_PATH
    if not os.path.exists(temp_path):
        return {"count": 0}
    
    allowed_extensions = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp'}
    count = len([
        f for f in os.listdir(temp_path) 
        if any(f.lower().endswith(ext) for ext in allowed_extensions)
    ])
    
    return {"count": count}

@router.get("/upload/temp-images")
def get_temp_images():
    """获取temp目录中的图片列表"""
    temp_path = settings.TEMP_PATH
    if not os.path.exists(temp_path):
        return {"images": []}
    
    allowed_extensions = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp'}
    images = [
        f for f in os.listdir(temp_path) 
        if any(f.lower().endswith(ext) for ext in allowed_extensions)
    ]
    
    return {"images": images}

@router.post("/upload/temp", response_model=schemas.UploadImageResponse)
def upload_temp_image(temp_upload: schemas.TempImageUpload, request: Request):
    """从temp目录上传图片到系统"""
    temp_path = settings.TEMP_PATH
    image_path = os.path.join(temp_path, temp_upload.filename)
    
    # 验证文件是否存在
    if not os.path.exists(image_path):
        raise HTTPException(status_code=404, detail="Image not found in temp directory")
    
    # 获取文件扩展名
    file_extension = temp_upload.filename.split('.')[-1].lower()
    allowed_extensions = {'jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp'}
    if file_extension not in allowed_extensions:
        raise HTTPException(status_code=400, detail="Unsupported file type")
    
    with get_db_context() as db:
        # 获取当前用户（用于管理员贡献度记录）
        session = get_current_session(request, db)
        user_id = None
        is_admin = False
        if session and not session.get("is_guest"):
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if user:
                user_id = user.id
                is_admin = user.role in [UserRole.ROOT.value, UserRole.ADMIN.value]

        # 验证character_ids是否存在
        if temp_upload.character_ids:
            existing_characters = db.query(models.Character).filter(
                models.Character.id.in_(temp_upload.character_ids)
            ).all()
            if len(existing_characters) != len(temp_upload.character_ids):
                missing_ids = set(temp_upload.character_ids) - set(c.id for c in existing_characters)
                raise HTTPException(status_code=400, detail=f"选中的某些角色不存在: {missing_ids}")
        
        store_path = settings.STORE_PATH
        image_create = schemas.ImageCreate(
            character_ids=temp_upload.character_ids,
            pid=temp_upload.pid,
            description=temp_upload.description
        )
        
        # 使用temp目录中的文件创建图片记录
        image = ImageService.create_image(
            db, image_create, image_path, temp_upload.filename, file_extension, store_path
        )

        # 记录贡献度（管理员/Root直接通过）
        if is_admin and user_id:
            pending_request = PendingRequest(
                request_type="add",
                user_id=user_id,
                status=RequestStatus.APPROVED.value,
                image_id=image.image_id,
                image_data=json.dumps({
                    "character_ids": temp_upload.character_ids,
                    "group_id": None,
                    "pid": temp_upload.pid,
                    "description": temp_upload.description
                }),
                reviewed_at=datetime.utcnow(),
                reviewed_by=user_id
            )
            db.add(pending_request)
            db.commit()
        
        # 成功后删除temp目录中的原文件
        try:
            os.unlink(image_path)
        except Exception as e:
            log_error(f"Failed to delete temp file: {e}")
        
        return schemas.UploadImageResponse(
            image_id=image.image_id,
            message="Image uploaded successfully from temp directory"
        )

@router.delete("/upload/temp/{filename}")
def delete_temp_image(filename: str):
    """删除temp目录中的图片文件"""
    temp_path = settings.TEMP_PATH
    image_path = os.path.join(temp_path, filename)
    
    # 验证文件是否存在
    if not os.path.exists(image_path):
        raise HTTPException(status_code=404, detail="Image not found in temp directory")
    
    # 验证文件扩展名
    file_extension = filename.split('.')[-1].lower() if '.' in filename else ''
    allowed_extensions = {'jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp'}
    if file_extension not in allowed_extensions:
        raise HTTPException(status_code=400, detail="File is not an image")
    
    try:
        os.unlink(image_path)
        return {"message": f"Image {filename} deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete image: {str(e)}")

# 系统相关路由
@router.get("/system/status", response_model=schemas.SystemStatus)
def get_system_status():
    """获取系统状态"""
    with get_db_context() as db:
        store_path = settings.STORE_PATH
        temp_path = settings.TEMP_PATH
        return SystemService.get_system_status(db, store_path, temp_path)

@router.post("/system/cleanup")
def cleanup_orphaned_records():
    """清理孤儿记录"""
    with get_db_context() as db:
        store_path = settings.STORE_PATH
        count = ImageService.cleanup_orphaned_records(db, store_path)
        return {"message": f"Cleaned up {count} orphaned records"}

@router.post("/system/scan-store-orphans")
def scan_store_orphans():
    """扫描store目录，将数据库不存在的图片移动到temp目录"""
    with get_db_context() as db:
        store_path = settings.STORE_PATH
        temp_path = settings.TEMP_PATH
        moved = ImageService.move_orphaned_files_to_temp(db, store_path, temp_path)
        return {"message": f"Moved {moved} orphaned files to temp", "moved": moved}