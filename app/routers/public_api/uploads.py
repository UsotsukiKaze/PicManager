from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Request
from typing import List, Optional, Union
from pathlib import Path
from io import BytesIO

from ...database import get_db_context
from ...services import GroupService, CharacterService, ImageService
from ...models import User, UserRole, PendingRequest, ImageViewCount, CharacterQueryCount, RequestStatus, Group, Character
from ... import models, schemas
from ...config import settings
from ...logger import log_error
from ...security.permissions import require_admin_user_id
from ..auth import get_current_session, check_guest_limit
from PIL import Image, UnidentifiedImageError
import tempfile
import os
import json
from datetime import datetime

router = APIRouter()

Image.MAX_IMAGE_PIXELS = 50_000_000


def _allowed_image_extensions() -> set[str]:
    return {ext.lower().lstrip(".") for ext in settings.ALLOWED_EXTENSIONS}


async def _read_limited_upload(file: UploadFile) -> bytes:
    chunks = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > settings.MAX_FILE_SIZE:
            raise HTTPException(status_code=413, detail="File too large")
        chunks.append(chunk)
    return b"".join(chunks)


def _verify_image_content(content: bytes) -> None:
    try:
        with Image.open(BytesIO(content)) as image:
            image.verify()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as exc:
        raise HTTPException(status_code=400, detail="Invalid image content") from exc


def _safe_temp_image_path(filename: str) -> Path:
    if not filename or "/" in filename or "\\" in filename or "\x00" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    temp_root = Path(settings.TEMP_PATH).resolve()
    image_path = (temp_root / filename).resolve()
    try:
        image_path.relative_to(temp_root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid filename") from exc
    return image_path


# 上传相关路由
@router.post("/upload/single", response_model=schemas.UploadImageResponse)
async def upload_single_image(
    request: Request,
    file: UploadFile = File(...),
    character_ids: str = Form(...),  # JSON字符串形式的角色ID列表
    group_id: Optional[str] = Form(None),
    group_ids: Optional[str] = Form(None),
    feature_tag_ids: Optional[str] = Form(None),
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

    try:
        group_id_list = json.loads(group_ids) if group_ids else []
        if group_id:
            group_id_list.append(int(group_id))
        if not isinstance(group_id_list, list):
            group_id_list = [group_id_list]
        group_id_list = list(dict.fromkeys([int(gid) for gid in group_id_list]))
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid group_ids format: {str(e)}")

    try:
        feature_tag_id_list = json.loads(feature_tag_ids) if feature_tag_ids else []
        if not isinstance(feature_tag_id_list, list):
            feature_tag_id_list = [feature_tag_id_list]
        feature_tag_id_list = list(dict.fromkeys([int(tid) for tid in feature_tag_id_list]))
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid feature_tag_ids format: {str(e)}")
    
    # 验证文件类型
    file_extension = (file.filename or "").split('.')[-1].lower()
    if file_extension not in _allowed_image_extensions():
        raise HTTPException(status_code=400, detail="Unsupported file type")

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
        content = await _read_limited_upload(file)
        _verify_image_content(content)

        if is_admin:
            # 管理员直接上传
            with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{file_extension}') as temp_file:
                temp_file.write(content)
                temp_file_path = temp_file.name
            
            try:
                store_path = settings.STORE_PATH
                image_create = schemas.ImageCreate(
                    character_ids=character_id_list,
                    group_ids=group_id_list,
                    feature_tag_ids=feature_tag_id_list,
                    pid=pid,
                    description=description
                )
                
                image = ImageService.create_image(
                    db, image_create, temp_file_path, file.filename, file_extension, store_path
                )

                # 记录贡献度（直接通过）
                if user_id:
                    pending_request = PendingRequest(
                        request_type="add",
                        user_id=user_id,
                        status=RequestStatus.APPROVED.value,
                        image_id=image.image_id,
                        image_data=json.dumps({
                            "character_ids": character_id_list,
                            "group_id": group_id_list[0] if group_id_list else None,
                            "group_ids": group_id_list,
                            "feature_tag_ids": feature_tag_id_list,
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
                    message="图片上传成功"
                )
            finally:
                try:
                    os.unlink(temp_file_path)
                except:
                    pass

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

        if not validation_error and group_id_list:
            existing_groups = db.query(models.Group).filter(
                models.Group.id.in_(group_id_list)
            ).all()
            if len(existing_groups) != len(group_id_list):
                missing_ids = set(group_id_list) - set(g.id for g in existing_groups)
                validation_error = f"Selected groups do not exist: {missing_ids}"

        if not validation_error and feature_tag_id_list:
            existing_tags = db.query(models.FeatureTag).filter(
                models.FeatureTag.id.in_(feature_tag_id_list)
            ).all()
            if len(existing_tags) != len(feature_tag_id_list):
                missing_ids = set(feature_tag_id_list) - set(t.id for t in existing_tags)
                validation_error = f"Selected feature tags do not exist: {missing_ids}"

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
                    "group_id": group_id_list[0] if group_id_list else None,
                    "group_ids": group_id_list,
                    "feature_tag_ids": feature_tag_id_list,
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
                message="提交成功，等待管理员审核"
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
def get_temp_images_count(request: Request):
    """Return temp image count for admins."""
    require_admin_user_id(request)
    temp_path = settings.TEMP_PATH
    if not os.path.exists(temp_path):
        return {"count": 0}
    allowed_extensions = {f".{ext}" for ext in _allowed_image_extensions()}
    count = len([f for f in os.listdir(temp_path) if any(f.lower().endswith(ext) for ext in allowed_extensions)])
    return {"count": count}


@router.get("/upload/temp-images")
def get_temp_images(request: Request):
    """Return temp image filenames for admins."""
    require_admin_user_id(request)
    temp_path = settings.TEMP_PATH
    if not os.path.exists(temp_path):
        return {"images": []}
    allowed_extensions = {f".{ext}" for ext in _allowed_image_extensions()}
    images = [f for f in os.listdir(temp_path) if any(f.lower().endswith(ext) for ext in allowed_extensions)]
    return {"images": images}


@router.post("/upload/temp", response_model=schemas.UploadImageResponse)
def upload_temp_image(temp_upload: schemas.TempImageUpload, request: Request):
    """Import an existing temp image into the managed store. Admin only."""
    require_admin_user_id(request)
    image_path = _safe_temp_image_path(temp_upload.filename)
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Image not found in temp directory")

    file_extension = temp_upload.filename.split('.')[-1].lower()
    if file_extension not in _allowed_image_extensions():
        raise HTTPException(status_code=400, detail="Unsupported file type")
    _verify_image_content(image_path.read_bytes())

    with get_db_context() as db:
        session = get_current_session(request, db)
        user_id = None
        is_admin = False
        if session and not session.get("is_guest"):
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if user:
                user_id = user.id
                is_admin = user.role in [UserRole.ROOT.value, UserRole.ADMIN.value]
        if not is_admin:
            raise HTTPException(status_code=403, detail="Admin permission required")

        if temp_upload.character_ids:
            existing_characters = db.query(models.Character).filter(models.Character.id.in_(temp_upload.character_ids)).all()
            if len(existing_characters) != len(temp_upload.character_ids):
                missing_ids = set(temp_upload.character_ids) - set(c.id for c in existing_characters)
                raise HTTPException(status_code=400, detail=f"Selected characters do not exist: {missing_ids}")
        if temp_upload.group_ids:
            existing_groups = db.query(models.Group).filter(models.Group.id.in_(temp_upload.group_ids)).all()
            if len(existing_groups) != len(temp_upload.group_ids):
                missing_ids = set(temp_upload.group_ids) - set(g.id for g in existing_groups)
                raise HTTPException(status_code=400, detail=f"Selected groups do not exist: {missing_ids}")
        if temp_upload.feature_tag_ids:
            existing_tags = db.query(models.FeatureTag).filter(models.FeatureTag.id.in_(temp_upload.feature_tag_ids)).all()
            if len(existing_tags) != len(temp_upload.feature_tag_ids):
                missing_ids = set(temp_upload.feature_tag_ids) - set(t.id for t in existing_tags)
                raise HTTPException(status_code=400, detail=f"Selected feature tags do not exist: {missing_ids}")

        image_create = schemas.ImageCreate(
            character_ids=temp_upload.character_ids,
            group_ids=temp_upload.group_ids,
            feature_tag_ids=temp_upload.feature_tag_ids,
            pid=temp_upload.pid,
            description=temp_upload.description
        )
        image = ImageService.create_image(db, image_create, str(image_path), temp_upload.filename, file_extension, settings.STORE_PATH)

        if is_admin and user_id:
            pending_request = PendingRequest(
                request_type="add",
                user_id=user_id,
                status=RequestStatus.APPROVED.value,
                image_id=image.image_id,
                image_data=json.dumps({
                    "character_ids": temp_upload.character_ids,
                    "group_id": temp_upload.group_ids[0] if temp_upload.group_ids else None,
                    "group_ids": temp_upload.group_ids,
                    "feature_tag_ids": temp_upload.feature_tag_ids,
                    "pid": temp_upload.pid,
                    "description": temp_upload.description
                }),
                reviewed_at=datetime.utcnow(),
                reviewed_by=user_id
            )
            db.add(pending_request)
            db.commit()

        try:
            image_path.unlink()
        except Exception as e:
            log_error(f"Failed to delete temp file: {e}")
        return schemas.UploadImageResponse(image_id=image.image_id, message="Imported temp image successfully")


@router.delete("/upload/temp/{filename}")
def delete_temp_image(filename: str, request: Request):
    """Delete a temp image. Admin only."""
    require_admin_user_id(request)
    image_path = _safe_temp_image_path(filename)
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Image not found in temp directory")

    file_extension = filename.split('.')[-1].lower() if '.' in filename else ''
    if file_extension not in _allowed_image_extensions():
        raise HTTPException(status_code=400, detail="File is not an image")
    try:
        image_path.unlink()
        return {"message": f"Temp image {filename} deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete image: {str(e)}")
