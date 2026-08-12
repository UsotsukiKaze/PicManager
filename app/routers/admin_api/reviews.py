from fastapi import APIRouter, HTTPException, Request
from typing import List
from datetime import datetime
import json
import os

from ... import schemas
from ...config import settings
from ...database import get_db_context
from ...models import Character, FeatureTag, Group, Image, PendingRequest, RequestStatus, User
from ...review_changes import build_changes, changed_update_data
from ...security.permissions import require_admin_user_id
from ...services import CharacterService, GroupService, ImageService
from ...utils import get_image_info

router = APIRouter()


IMAGE_CHANGE_LABELS = {
    "pid": "PID",
    "description": "描述",
    "character_ids": "角色",
    "group_ids": "分组",
    "feature_tag_ids": "特征标签",
    "age_rating": "年龄分级",
}
GROUP_CHANGE_LABELS = {
    "name": "名称",
    "aliases": "别名",
    "avatar_url": "头像",
    "description": "描述",
}
CHARACTER_CHANGE_LABELS = {
    "name": "名称",
    "group_id": "所属分组",
    "nicknames": "昵称",
    "avatar_url": "头像",
    "description": "描述",
    "feature_tag_ids": "特征标签",
}


def _named_items(db, model, ids):
    ids = list(ids or [])
    if not ids:
        return []
    rows = db.query(model).filter(model.id.in_(ids)).all()
    row_map = {row.id: row.name for row in rows}
    return [{"id": item_id, "name": row_map.get(item_id, f"ID {item_id}")} for item_id in ids]


def _decorate_change_values(db, changes):
    model_by_field = {
        "character_ids": Character,
        "group_ids": Group,
        "feature_tag_ids": FeatureTag,
    }
    for change in changes:
        field = change["field"]
        if field in model_by_field:
            change["before"] = _named_items(db, model_by_field[field], change["before"])
            change["after"] = _named_items(db, model_by_field[field], change["after"])
        elif field == "group_id":
            before = _named_items(db, Group, [change["before"]] if change["before"] else [])
            after = _named_items(db, Group, [change["after"]] if change["after"] else [])
            change["before"] = before[0] if before else None
            change["after"] = after[0] if after else None
    return changes


@router.get("/pending", response_model=List[schemas.PendingRequestInfo])
async def get_pending_requests(request: Request):
    """获取待审核请求列表"""
    require_admin_user_id(request)
    
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
                "guest_name": req.guest_name,
                "image_id": req.image_id,
                "image_data": json.loads(req.image_data) if req.image_data else None,
                "temp_file_path": req.temp_file_path,
                "original_filename": req.original_filename,
                "rejection_reason": req.rejection_reason,
                "group_info": None,
                "character_names": None,
                "character_info": None,
                "original_image": None,
                "original_group": None,
                "original_character": None,
                "pending_image": None,
                "target_info": None,
                "changes": None,
                "has_changes": None,
                "created_at": req.created_at,
                "reviewed_at": req.reviewed_at
            }

            if req.request_type == "add" and req.temp_file_path and os.path.isfile(req.temp_file_path):
                item["pending_image"] = get_image_info(req.temp_file_path)
            
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
                                "aliases": [alias.alias for alias in group.aliases] if group.aliases else [],
                                "avatar_url": group.avatar_url or "/favicon.ico",
                                "description": group.description
                            }
                            item["target_info"] = {"type": "group", "id": group.id, "name": group.name}
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
                    if req.request_type == "group_edit" and item.get("original_group"):
                        proposed = {
                            key: image_data[key]
                            for key in GROUP_CHANGE_LABELS
                            if key in image_data
                        }
                        original = {
                            key: item["original_group"].get(key)
                            for key in GROUP_CHANGE_LABELS
                        }
                        item["changes"] = build_changes(proposed, original, GROUP_CHANGE_LABELS)
                        item["has_changes"] = bool(item["changes"])
                elif req.request_type.startswith("character_"):
                    if image_data.get("character_id"):
                        character = db.query(Character).filter(Character.id == image_data["character_id"]).first()
                        if character:
                            item["original_character"] = {
                                "id": character.id,
                                "name": character.name,
                                "group_id": character.group_id,
                                "group_name": character.group.name if character.group else "",
                                "nicknames": [n.nickname for n in character.nicknames] if character.nicknames else [],
                                "feature_tag_ids": [tag.id for tag in character.feature_tags] if character.feature_tags else [],
                                "avatar_url": character.avatar_url or "/favicon.ico",
                                "description": character.description
                            }
                            item["target_info"] = {"type": "character", "id": character.id, "name": character.name}
                    if any(key in image_data for key in ["name", "group_id", "nicknames", "avatar_url", "description", "character_id"]):
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
                            "avatar_url": image_data.get("avatar_url") or "/favicon.ico",
                            "description": image_data.get("description")
                        }
                    if not item["character_info"] and item.get("original_character"):
                        item["character_info"] = {
                            "id": image_data.get("character_id"),
                            "name": item["original_character"].get("name"),
                            "group_id": image_data.get("group_id"),
                            "group_name": item["original_character"].get("group_name"),
                            "nicknames": image_data.get("nicknames") or item["original_character"].get("nicknames") or [],
                            "avatar_url": image_data.get("avatar_url") or item["original_character"].get("avatar_url") or "/favicon.ico",
                            "description": image_data.get("description") or item["original_character"].get("description")
                        }
                    if req.request_type == "character_edit" and item.get("original_character"):
                        proposed = {
                            key: image_data[key]
                            for key in CHARACTER_CHANGE_LABELS
                            if key in image_data
                        }
                        original = {
                            key: item["original_character"].get(key)
                            for key in CHARACTER_CHANGE_LABELS
                        }
                        item["changes"] = _decorate_change_values(
                            db,
                            build_changes(proposed, original, CHARACTER_CHANGE_LABELS),
                        )
                        item["has_changes"] = bool(item["changes"])
            
            # 对于 edit 和 delete 请求，获取原图信息
            if req.request_type in ["edit", "delete"] and req.image_id:
                original_img = db.query(Image).filter(Image.image_id == req.image_id).first()
                if original_img:
                    # 获取原图的角色信息
                    original_file_info = {
                        "file_size": original_img.file_size,
                        "width": original_img.width,
                        "height": original_img.height,
                    }
                    if any(value is None for value in original_file_info.values()):
                        original_path = ImageService.image_full_path(original_img)
                        if os.path.isfile(original_path):
                            detected_info = get_image_info(original_path)
                            for key in original_file_info:
                                if original_file_info[key] is None:
                                    original_file_info[key] = detected_info.get(key)
                    original_characters = [ch.name for ch in original_img.characters] if original_img.characters else []
                    original_character_ids = [ch.id for ch in original_img.characters] if original_img.characters else []
                    original_group_ids = [group.id for group in original_img.groups] if original_img.groups else []
                    original_feature_tag_ids = [tag.id for tag in original_img.feature_tags] if original_img.feature_tags else []
                    item["original_image"] = {
                        "image_id": original_img.image_id,
                        "pid": original_img.pid,
                        "description": original_img.description,
                        "character_ids": original_character_ids,
                        "character_names": original_characters,
                        "group_ids": original_group_ids,
                        "group_names": [group.name for group in original_img.groups] if original_img.groups else [],
                        "feature_tag_ids": original_feature_tag_ids,
                        "age_rating": original_img.age_rating or "all",
                        "file_path": original_img.file_path,
                        "file_extension": original_img.file_extension,
                        **original_file_info,
                    }
                    item["target_info"] = {"type": "image", "id": original_img.image_id, "name": original_img.original_filename}
                    if req.request_type == "edit" and item["image_data"]:
                        proposed = {
                            key: item["image_data"][key]
                            for key in IMAGE_CHANGE_LABELS
                            if key in item["image_data"]
                        }
                        original = {
                            "pid": original_img.pid,
                            "description": original_img.description,
                            "character_ids": original_character_ids,
                            "group_ids": original_group_ids,
                            "feature_tag_ids": original_feature_tag_ids,
                            "age_rating": original_img.age_rating or "all",
                        }
                        item["changes"] = _decorate_change_values(
                            db,
                            build_changes(proposed, original, IMAGE_CHANGE_LABELS),
                        )
                        item["has_changes"] = bool(item["changes"])
            
            result.append(schemas.PendingRequestInfo(**item))
        
        return result


@router.post("/pending/{request_id}")
async def handle_pending_request(
    request_id: int,
    action: schemas.PendingRequestAction,
    request: Request
):
    """处理待审核请求"""
    admin_user_id = require_admin_user_id(request)
    
    with get_db_context() as db:
        pending_req = db.query(PendingRequest).filter(PendingRequest.id == request_id).first()
        if not pending_req:
            raise HTTPException(status_code=404, detail="请求不存在")
        
        if pending_req.status != RequestStatus.PENDING.value:
            raise HTTPException(status_code=400, detail="请求已处理")
        
        if action.action == "approve":
            # 批准请求
            pending_req.rejection_reason = None
            unchanged = False
            if pending_req.request_type == "add":
                # 处理添加图片请求
                image_data = json.loads(pending_req.image_data) if pending_req.image_data else {}
                
                if pending_req.temp_file_path and os.path.exists(pending_req.temp_file_path):
                    # 从pending目录移动到store
                    store_path = settings.STORE_PATH
                    file_extension = pending_req.original_filename.split('.')[-1].lower()
                    
                    image_create = schemas.ImageCreate(
                        character_ids=image_data.get("character_ids", []),
                        group_ids=image_data.get("group_ids") or ([image_data.get("group_id")] if image_data.get("group_id") else []),
                        feature_tag_ids=image_data.get("feature_tag_ids", []),
                        pid=image_data.get("pid"),
                        description=image_data.get("description"),
                        age_rating=image_data.get("age_rating", "all"),
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
                    except OSError:
                        pass
                else:
                    raise HTTPException(status_code=400, detail="临时文件不存在")
            
            elif pending_req.request_type == "edit":
                # 处理编辑图片请求
                image_data = json.loads(pending_req.image_data) if pending_req.image_data else {}
                image = db.query(Image).filter(Image.image_id == pending_req.image_id).first()
                if not image:
                    raise HTTPException(status_code=404, detail="图片不存在")
                proposed = {key: image_data[key] for key in IMAGE_CHANGE_LABELS if key in image_data}
                original = {
                    "pid": image.pid,
                    "description": image.description,
                    "character_ids": [character.id for character in image.characters],
                    "group_ids": [group.id for group in image.groups],
                    "feature_tag_ids": [tag.id for tag in image.feature_tags],
                    "age_rating": image.age_rating or "all",
                }
                update_data = changed_update_data(proposed, original)
                if update_data:
                    ImageService.update_image(db, pending_req.image_id, schemas.ImageUpdate(**update_data))
                else:
                    unchanged = True
            
            elif pending_req.request_type == "group_add":
                group_data = json.loads(pending_req.image_data) if pending_req.image_data else {}
                exists = db.query(Group).filter(Group.name == group_data.get("name")).first()
                if exists:
                    raise HTTPException(status_code=400, detail="分组名称已存在")
                group_create = schemas.GroupCreate(
                    name=group_data.get("name"),
                    aliases=group_data.get("aliases") or [],
                    avatar_url=group_data.get("avatar_url"),
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
                update_data = {k: group_data[k] for k in ["name", "aliases", "avatar_url", "description"] if k in group_data}
                group = db.query(Group).filter(Group.id == group_id).first()
                if not group:
                    raise HTTPException(status_code=404, detail="分组不存在")
                original = {
                    "name": group.name,
                    "aliases": [alias.alias for alias in group.aliases] if group.aliases else [],
                    "avatar_url": group.avatar_url,
                    "description": group.description,
                }
                update_data = changed_update_data(update_data, original)
                if update_data:
                    GroupService.update_group(db, group_id, schemas.GroupUpdate(**update_data))
                else:
                    unchanged = True

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
                    nicknames=char_data.get("nicknames"),
                    feature_tag_ids=char_data.get("feature_tag_ids"),
                    avatar_url=char_data.get("avatar_url")
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
                update_data = {k: char_data[k] for k in ["name", "group_id", "description", "nicknames", "feature_tag_ids", "avatar_url"] if k in char_data}
                character = db.query(Character).filter(Character.id == char_id).first()
                if not character:
                    raise HTTPException(status_code=404, detail="角色不存在")
                original = {
                    "name": character.name,
                    "group_id": character.group_id,
                    "description": character.description,
                    "nicknames": [nickname.nickname for nickname in character.nicknames] if character.nicknames else [],
                    "feature_tag_ids": [tag.id for tag in character.feature_tags] if character.feature_tags else [],
                    "avatar_url": character.avatar_url,
                }
                update_data = changed_update_data(update_data, original)
                if update_data:
                    CharacterService.update_character(db, char_id, schemas.CharacterUpdate(**update_data))
                else:
                    unchanged = True

            elif pending_req.request_type == "character_delete":
                char_data = json.loads(pending_req.image_data) if pending_req.image_data else {}
                char_id = char_data.get("character_id")
                if not char_id:
                    raise HTTPException(status_code=400, detail="缺少角色ID")
                success = CharacterService.delete_character(db, char_id)
                if not success:
                    raise HTTPException(status_code=404, detail="角色不存在")

            # delete类型不需要在批准时处理，管理员手动删除
            
            pending_req.status = (
                RequestStatus.UNCHANGED.value
                if unchanged
                else RequestStatus.APPROVED.value
            )
        
        elif action.action == "reject":
            # 拒绝请求
            pending_req.status = RequestStatus.REJECTED.value
            pending_req.rejection_reason = action.reason.strip() if action.reason else None
            
            # 如果是添加请求，删除临时文件
            if pending_req.request_type == "add" and pending_req.temp_file_path:
                try:
                    if os.path.exists(pending_req.temp_file_path):
                        os.unlink(pending_req.temp_file_path)
                except OSError:
                    pass
        
        else:
            raise HTTPException(status_code=400, detail="无效的操作")
        
        pending_req.reviewed_at = datetime.utcnow()
        pending_req.reviewed_by = admin_user_id
        db.commit()
        
        if pending_req.status == RequestStatus.UNCHANGED.value:
            return {"message": "请求内容与当前条目相同，已判定为未修改"}
        return {"message": f"请求已{('批准' if action.action == 'approve' else '拒绝')}"}
