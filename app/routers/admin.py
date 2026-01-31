from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime
import json
import os
import shutil

from ..database import get_db_context
from ..models import User, UserRole, PendingRequest, RequestStatus, Group, Character, Image
from ..services import ImageService, GroupService, CharacterService
from ..config import settings
from .. import schemas
from .auth import get_current_session, hash_password, ADMIN_DEFAULT_PASSWORD

router = APIRouter()


def require_admin(request: Request) -> int:
    """要求管理员权限，返回用户ID"""
    with get_db_context() as db:
        session = get_current_session(request, db)
        if not session or session["is_guest"]:
            raise HTTPException(status_code=401, detail="需要登录")
        
        user = db.query(User).filter(User.id == session["user_id"]).first()
        if not user:
            raise HTTPException(status_code=401, detail="用户不存在")
        if user.role not in [UserRole.ROOT.value, UserRole.ADMIN.value]:
            raise HTTPException(status_code=403, detail="需要管理员权限")
        return user.id


def require_root(request: Request) -> int:
    """要求root权限，返回用户ID"""
    with get_db_context() as db:
        session = get_current_session(request, db)
        if not session or session["is_guest"]:
            raise HTTPException(status_code=401, detail="需要登录")
        
        user = db.query(User).filter(User.id == session["user_id"]).first()
        if not user:
            raise HTTPException(status_code=401, detail="用户不存在")
        if user.role != UserRole.ROOT.value:
            raise HTTPException(status_code=403, detail="需要root权限")
        return user.id


@router.get("/pending", response_model=List[schemas.PendingRequestInfo])
async def get_pending_requests(request: Request):
    """获取待审核请求列表"""
    require_admin(request)
    
    with get_db_context() as db:
        requests = db.query(PendingRequest).filter(
            PendingRequest.status == RequestStatus.PENDING.value
        ).order_by(PendingRequest.created_at.desc()).all()
        
        result = []
        for req in requests:
            item = {
                "id": req.id,
                "request_type": req.request_type,
                "status": req.status,
                "user_qq": None,
                "user_nickname": None,
                "user_avatar": None,
                "guest_ip": req.guest_ip,
                "image_id": req.image_id,
                "image_data": json.loads(req.image_data) if req.image_data else None,
                "temp_file_path": req.temp_file_path,
                "original_filename": req.original_filename,
                "group_info": None,
                "character_names": None,
                "character_info": None,
                "original_image": None,
                "original_group": None,
                "original_character": None,
                "created_at": req.created_at
            }
            
            if req.user_id:
                user = db.query(User).filter(User.id == req.user_id).first()
                if user:
                    item["user_qq"] = user.qq_number
                    item["user_nickname"] = user.nickname
                    item["user_avatar"] = user.avatar_url
            
            # 获取分组和角色信息
            if item["image_data"]:
                image_data = item["image_data"]
                
                # 处理分组信息（从image_data中的group_id获取）
                if image_data.get("group_id"):
                    group = db.query(Group).filter(Group.id == image_data["group_id"]).first()
                    if group:
                        item["group_info"] = {"id": group.id, "name": group.name}
                
                # 处理角色信息
                if image_data.get("character_ids"):
                    characters = db.query(Character).filter(
                        Character.id.in_(image_data["character_ids"])
                    ).all()
                    if characters:
                        item["character_names"] = [ch.name for ch in characters]

                # 分组/角色审核数据
                if req.request_type.startswith("group_"):
                    if image_data.get("group_id"):
                        group = db.query(Group).filter(Group.id == image_data["group_id"]).first()
                        if group:
                            item["original_group"] = {
                                "id": group.id,
                                "name": group.name,
                                "description": group.description
                            }
                    if image_data.get("name"):
                        item["group_info"] = {
                            "id": image_data.get("group_id"),
                            "name": image_data.get("name")
                        }
                    if not item["group_info"] and item.get("original_group"):
                        item["group_info"] = {
                            "id": item["original_group"]["id"],
                            "name": item["original_group"]["name"]
                        }
                elif req.request_type.startswith("character_"):
                    if image_data.get("character_id"):
                        character = db.query(Character).filter(Character.id == image_data["character_id"]).first()
                        if character:
                            item["original_character"] = {
                                "id": character.id,
                                "name": character.name,
                                "group_name": character.group.name if character.group else "",
                                "nicknames": [n.nickname for n in character.nicknames] if character.nicknames else [],
                                "description": character.description
                            }
                    if any(key in image_data for key in ["name", "group_id", "nicknames", "description", "character_id"]):
                        group = None
                        if image_data.get("group_id"):
                            group = db.query(Group).filter(Group.id == image_data["group_id"]).first()
                        elif item.get("original_character"):
                            group = db.query(Group).filter(Group.name == item["original_character"].get("group_name")).first()
                        item["character_info"] = {
                            "id": image_data.get("character_id"),
                            "name": image_data.get("name"),
                            "group_id": image_data.get("group_id"),
                            "group_name": group.name if group else "",
                            "nicknames": image_data.get("nicknames") or [],
                            "description": image_data.get("description")
                        }
                    if not item["character_info"] and item.get("original_character"):
                        item["character_info"] = {
                            "id": image_data.get("character_id"),
                            "name": item["original_character"].get("name"),
                            "group_id": image_data.get("group_id"),
                            "group_name": item["original_character"].get("group_name"),
                            "nicknames": image_data.get("nicknames") or item["original_character"].get("nicknames") or [],
                            "description": image_data.get("description") or item["original_character"].get("description")
                        }
            
            # 对于 edit 和 delete 请求，获取原图信息
            if req.request_type in ["edit", "delete"] and req.image_id:
                original_img = db.query(Image).filter(Image.image_id == req.image_id).first()
                if original_img:
                    # 获取原图的角色信息
                    original_characters = [ch.name for ch in original_img.characters] if original_img.characters else []
                    item["original_image"] = {
                        "image_id": original_img.image_id,
                        "pid": original_img.pid,
                        "description": original_img.description,
                        "character_names": original_characters,
                        "file_path": original_img.file_path,
                        "file_extension": original_img.file_extension
                    }
            
            result.append(schemas.PendingRequestInfo(**item))
        
        return result


@router.post("/pending/{request_id}")
async def handle_pending_request(
    request_id: int,
    action: schemas.PendingRequestAction,
    request: Request
):
    """处理待审核请求"""
    admin_user_id = require_admin(request)
    
    with get_db_context() as db:
        pending_req = db.query(PendingRequest).filter(PendingRequest.id == request_id).first()
        if not pending_req:
            raise HTTPException(status_code=404, detail="请求不存在")
        
        if pending_req.status != RequestStatus.PENDING.value:
            raise HTTPException(status_code=400, detail="请求已处理")
        
        if action.action == "approve":
            # 批准请求
            if pending_req.request_type == "add":
                # 处理添加图片请求
                image_data = json.loads(pending_req.image_data) if pending_req.image_data else {}
                
                if pending_req.temp_file_path and os.path.exists(pending_req.temp_file_path):
                    # 从pending目录移动到store
                    store_path = settings.STORE_PATH
                    file_extension = pending_req.original_filename.split('.')[-1].lower()
                    
                    image_create = schemas.ImageCreate(
                        character_ids=image_data.get("character_ids", []),
                        pid=image_data.get("pid"),
                        description=image_data.get("description")
                    )
                    
                    image = ImageService.create_image(
                        db, image_create, 
                        pending_req.temp_file_path, 
                        pending_req.original_filename, 
                        file_extension, 
                        store_path
                    )
                    
                    # 删除临时文件
                    try:
                        os.unlink(pending_req.temp_file_path)
                    except:
                        pass
                else:
                    raise HTTPException(status_code=400, detail="临时文件不存在")
            
            elif pending_req.request_type == "edit":
                # 处理编辑图片请求
                image_data = json.loads(pending_req.image_data) if pending_req.image_data else {}
                
                image_update = schemas.ImageUpdate(
                    pid=image_data.get("pid"),
                    description=image_data.get("description"),
                    character_ids=image_data.get("character_ids")
                )
                
                image = ImageService.update_image(db, pending_req.image_id, image_update)
                if not image:
                    raise HTTPException(status_code=404, detail="图片不存在")
            
            elif pending_req.request_type == "group_add":
                group_data = json.loads(pending_req.image_data) if pending_req.image_data else {}
                exists = db.query(Group).filter(Group.name == group_data.get("name")).first()
                if exists:
                    raise HTTPException(status_code=400, detail="分组名称已存在")
                group_create = schemas.GroupCreate(
                    name=group_data.get("name"),
                    description=group_data.get("description")
                )
                GroupService.create_group(db, group_create)

            elif pending_req.request_type == "group_edit":
                group_data = json.loads(pending_req.image_data) if pending_req.image_data else {}
                group_id = group_data.get("group_id")
                if not group_id:
                    raise HTTPException(status_code=400, detail="缺少分组ID")
                if "name" in group_data and group_data.get("name"):
                    exists = db.query(Group).filter(
                        Group.name == group_data.get("name"),
                        Group.id != group_id
                    ).first()
                    if exists:
                        raise HTTPException(status_code=400, detail="分组名称已存在")
                update_data = {k: group_data[k] for k in ["name", "description"] if k in group_data}
                group_update = schemas.GroupUpdate(**update_data)
                updated = GroupService.update_group(db, group_id, group_update)
                if not updated:
                    raise HTTPException(status_code=404, detail="分组不存在")

            elif pending_req.request_type == "group_delete":
                group_data = json.loads(pending_req.image_data) if pending_req.image_data else {}
                group_id = group_data.get("group_id")
                if not group_id:
                    raise HTTPException(status_code=400, detail="缺少分组ID")
                success = GroupService.delete_group(db, group_id)
                if not success:
                    raise HTTPException(status_code=404, detail="分组不存在")

            elif pending_req.request_type == "character_add":
                char_data = json.loads(pending_req.image_data) if pending_req.image_data else {}
                exists = db.query(Character).filter(
                    Character.group_id == char_data.get("group_id"),
                    Character.name == char_data.get("name")
                ).first()
                if exists:
                    raise HTTPException(status_code=400, detail="该分组下已存在同名角色")
                char_create = schemas.CharacterCreate(
                    name=char_data.get("name"),
                    group_id=char_data.get("group_id"),
                    description=char_data.get("description"),
                    nicknames=char_data.get("nicknames")
                )
                CharacterService.create_character(db, char_create)

            elif pending_req.request_type == "character_edit":
                char_data = json.loads(pending_req.image_data) if pending_req.image_data else {}
                char_id = char_data.get("character_id")
                if not char_id:
                    raise HTTPException(status_code=400, detail="缺少角色ID")
                if "name" in char_data and char_data.get("name"):
                    group_id = char_data.get("group_id")
                    if not group_id:
                        existing = db.query(Character).filter(Character.id == char_id).first()
                        group_id = existing.group_id if existing else None
                    if group_id:
                        exists = db.query(Character).filter(
                            Character.group_id == group_id,
                            Character.name == char_data.get("name"),
                            Character.id != char_id
                        ).first()
                        if exists:
                            raise HTTPException(status_code=400, detail="该分组下已存在同名角色")
                update_data = {k: char_data[k] for k in ["name", "group_id", "description", "nicknames"] if k in char_data}
                char_update = schemas.CharacterUpdate(**update_data)
                updated = CharacterService.update_character(db, char_id, char_update)
                if not updated:
                    raise HTTPException(status_code=404, detail="角色不存在")

            elif pending_req.request_type == "character_delete":
                char_data = json.loads(pending_req.image_data) if pending_req.image_data else {}
                char_id = char_data.get("character_id")
                if not char_id:
                    raise HTTPException(status_code=400, detail="缺少角色ID")
                success = CharacterService.delete_character(db, char_id)
                if not success:
                    raise HTTPException(status_code=404, detail="角色不存在")

            # delete类型不需要在批准时处理，管理员手动删除
            
            pending_req.status = RequestStatus.APPROVED.value
        
        elif action.action == "reject":
            # 拒绝请求
            pending_req.status = RequestStatus.REJECTED.value
            
            # 如果是添加请求，删除临时文件
            if pending_req.request_type == "add" and pending_req.temp_file_path:
                try:
                    if os.path.exists(pending_req.temp_file_path):
                        os.unlink(pending_req.temp_file_path)
                except:
                    pass
        
        else:
            raise HTTPException(status_code=400, detail="无效的操作")
        
        pending_req.reviewed_at = datetime.utcnow()
        pending_req.reviewed_by = admin_user_id
        db.commit()
        
        return {"message": f"请求已{('批准' if action.action == 'approve' else '拒绝')}"}


@router.get("/admins", response_model=List[schemas.AdminInfo])
async def get_admins(request: Request):
    """获取管理员列表（仅root）"""
    require_root(request)
    
    with get_db_context() as db:
        admins = db.query(User).filter(
            User.role.in_([UserRole.ROOT.value, UserRole.ADMIN.value])
        ).all()
        
        return [schemas.AdminInfo.model_validate(admin) for admin in admins]


@router.post("/admins")
async def add_admin(admin_data: schemas.AdminCreate, request: Request):
    """添加管理员（仅root）"""
    require_root(request)
    
    with get_db_context() as db:
        # 检查是否已存在
        existing = db.query(User).filter(User.qq_number == admin_data.qq_number).first()
        
        if existing:
            if existing.role in [UserRole.ROOT.value, UserRole.ADMIN.value]:
                raise HTTPException(status_code=400, detail="该用户已经是管理员")
            
            # 升级为管理员
            existing.role = UserRole.ADMIN.value
            existing.password_hash = hash_password(ADMIN_DEFAULT_PASSWORD)
            db.commit()
            return {"message": f"用户 {admin_data.qq_number} 已升级为管理员，默认密码为: admin"}
        else:
            # 创建新管理员
            new_admin = User(
                qq_number=admin_data.qq_number,
                role=UserRole.ADMIN.value,
                password_hash=hash_password(ADMIN_DEFAULT_PASSWORD),
                nickname=f"管理员{admin_data.qq_number[-4:]}"
            )
            db.add(new_admin)
            db.commit()
            return {"message": f"管理员 {admin_data.qq_number} 创建成功，默认密码为: admin"}


@router.delete("/admins/{qq_number}")
async def remove_admin(qq_number: str, request: Request):
    """移除管理员（仅root）"""
    require_root(request)
    
    with get_db_context() as db:
        user = db.query(User).filter(User.qq_number == qq_number).first()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        
        if user.role == UserRole.ROOT.value:
            raise HTTPException(status_code=400, detail="不能移除root用户")
        
        if user.role != UserRole.ADMIN.value:
            raise HTTPException(status_code=400, detail="该用户不是管理员")
        
        # 降级为普通用户
        user.role = UserRole.USER.value
        user.password_hash = None
        db.commit()
        
        return {"message": f"用户 {qq_number} 已被移除管理员权限"}


@router.get("/stats")
async def get_admin_stats(request: Request):
    """获取管理统计信息"""
    require_admin(request)
    
    with get_db_context() as db:
        pending_count = db.query(PendingRequest).filter(
            PendingRequest.status == RequestStatus.PENDING.value
        ).count()
        
        total_users = db.query(User).count()
        admin_count = db.query(User).filter(
            User.role.in_([UserRole.ROOT.value, UserRole.ADMIN.value])
        ).count()
        
        return {
            "pending_requests": pending_count,
            "total_users": total_users,
            "admin_count": admin_count
        }
