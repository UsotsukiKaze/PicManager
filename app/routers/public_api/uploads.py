from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Request
from typing import List, Optional, Union
from pathlib import Path

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
import base64
import hashlib
import hmac
import time
import uuid

router = APIRouter()

Image.MAX_IMAGE_PIXELS = 50_000_000


def _allowed_image_extensions() -> set[str]:
    return {ext.lower().lstrip(".") for ext in settings.ALLOWED_EXTENSIONS}


def _save_limited_upload(file: UploadFile, suffix: str) -> str:
    total = 0
    temp_file_path = ""
    try:
        os.makedirs(settings.TEMP_PATH, exist_ok=True)
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=settings.TEMP_PATH) as temp_file:
            temp_file_path = temp_file.name
            while True:
                chunk = file.file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > settings.MAX_FILE_SIZE:
                    raise HTTPException(status_code=413, detail="File too large")
                temp_file.write(chunk)
        return temp_file_path
    except Exception:
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.unlink(temp_file_path)
            except OSError:
                pass
        raise


def _verify_image_file(path: str) -> None:
    try:
        with Image.open(path) as image:
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


def _validate_upload_tags(db, character_ids: List[int], group_ids: List[int], feature_tag_ids: List[int]) -> None:
    checks = (
        (models.Character, character_ids, "characters"),
        (models.Group, group_ids, "groups"),
        (models.FeatureTag, feature_tag_ids, "feature tags"),
    )
    for model, selected_ids, label in checks:
        if not selected_ids:
            continue
        existing_ids = {row[0] for row in db.query(model.id).filter(model.id.in_(selected_ids)).all()}
        missing_ids = set(selected_ids) - existing_ids
        if missing_ids:
            raise HTTPException(status_code=400, detail=f"Selected {label} do not exist: {missing_ids}")


def _duplicate_upload_scan(
    db,
    file_path: str,
    character_ids: List[int],
    upload_hash: Optional[str] = None,
):
    upload_hash, matches = ImageService.find_perceptual_duplicates(
        db,
        file_path,
        character_ids,
        upload_hash=upload_hash,
    )
    return upload_hash, matches


def _duplicate_owner(request: Request) -> str:
    session_id = str(request.cookies.get("session_id") or "")
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()


def _encode_duplicate_token(payload: dict) -> str:
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).rstrip(b"=")
    signature = hmac.new(settings.SECRET_KEY.encode("utf-8"), encoded, hashlib.sha256).hexdigest()
    return f"{encoded.decode('ascii')}.{signature}"


def _decode_duplicate_token(token: str) -> dict:
    try:
        encoded_text, signature = token.rsplit(".", 1)
        encoded = encoded_text.encode("ascii")
        expected = hmac.new(settings.SECRET_KEY.encode("utf-8"), encoded, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        padded = encoded + b"=" * (-len(encoded) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        if int(payload.get("expires_at") or 0) < int(time.time()):
            raise HTTPException(status_code=410, detail="Duplicate decision expired; submit the image again")
        return payload
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid duplicate decision token") from exc


def _incoming_duplicate_match(db, file_path: str, metadata: dict, original_filename: str) -> dict:
    character_ids = ImageService._unique_ints(metadata.get("character_ids"))
    group_ids = ImageService._unique_ints(metadata.get("group_ids"))
    feature_tag_ids = ImageService._unique_ints(metadata.get("feature_tag_ids"))
    characters = db.query(models.Character).filter(models.Character.id.in_(character_ids)).all() if character_ids else []
    groups = db.query(models.Group).filter(models.Group.id.in_(group_ids)).all() if group_ids else []
    tags = db.query(models.FeatureTag).filter(models.FeatureTag.id.in_(feature_tag_ids)).all() if feature_tag_ids else []
    width = height = None
    try:
        with Image.open(file_path) as image:
            width, height = image.size
    except OSError:
        pass
    return {
        "image_id": "new",
        "distance": 0,
        "thumbnail_url": "",
        "character_ids": [item.id for item in characters],
        "character_names": [item.name for item in characters],
        "group_ids": [item.id for item in groups],
        "group_names": [item.name for item in groups],
        "feature_tag_ids": [item.id for item in tags],
        "feature_tag_names": [item.name for item in tags],
        "pid": metadata.get("pid"),
        "description": metadata.get("description"),
        "age_rating": metadata.get("age_rating") or "all",
        "original_filename": original_filename,
        "file_size": os.path.getsize(file_path),
        "width": width,
        "height": height,
    }


def _duplicate_response(db, matches: List[dict], token: str, file_path: str, metadata: dict, original_filename: str) -> schemas.UploadImageResponse:
    return schemas.UploadImageResponse(
        image_id="duplicate",
        message=f"Found {len(matches)} visually similar image(s)",
        status="duplicate",
        duplicates=matches[:1],
        incoming=_incoming_duplicate_match(db, file_path, metadata, original_filename),
        duplicate_algorithm="dhash64",
        duplicate_threshold=min(64, max(0, settings.DUPLICATE_DHASH_DISTANCE)),
        duplicate_token=token,
    )


def _staged_duplicate_path(filename: str) -> Path:
    if not filename.startswith("duplicate-"):
        raise HTTPException(status_code=400, detail="Invalid staged duplicate")
    pending_root = Path(settings.PENDING_PATH).resolve()
    path = (pending_root / filename).resolve()
    try:
        path.relative_to(pending_root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid staged duplicate") from exc
    return path


def _cleanup_expired_duplicate_staging() -> None:
    pending_root = Path(settings.PENDING_PATH)
    if not pending_root.is_dir():
        return
    cutoff = time.time() - max(60, settings.DUPLICATE_DECISION_TTL_SECONDS)
    for path in pending_root.glob("duplicate-*"):
        try:
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            continue


def _make_duplicate_token(
    request: Request,
    source: str,
    filename: str,
    original_filename: str,
    file_extension: str,
    metadata: dict,
    upload_hash: str,
    matches: List[dict],
) -> str:
    _cleanup_expired_duplicate_staging()
    return _encode_duplicate_token({
        "version": 1,
        "owner": _duplicate_owner(request),
        "source": source,
        "filename": filename,
        "original_filename": original_filename,
        "file_extension": file_extension,
        "metadata": metadata,
        "upload_hash": upload_hash,
        "match_ids": [match["image_id"] for match in matches],
        "expires_at": int(time.time()) + max(60, settings.DUPLICATE_DECISION_TTL_SECONDS),
    })


# 上传相关路由
@router.post("/upload/single", response_model=schemas.UploadImageResponse)
def upload_single_image(
    request: Request,
    file: UploadFile = File(...),
    character_ids: str = Form(...),  # JSON字符串形式的角色ID列表
    group_id: Optional[str] = Form(None),
    group_ids: Optional[str] = Form(None),
    feature_tag_ids: Optional[str] = Form(None),
    emotion_ids: Optional[str] = Form(None),
    pid: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    age_rating: str = Form("all"),
):
    """单张图片上传"""
    # 解析角色ID列表
    _cleanup_expired_duplicate_staging()
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

    try:
        emotion_id_list = json.loads(emotion_ids) if emotion_ids else []
        if not isinstance(emotion_id_list, list):
            emotion_id_list = [emotion_id_list]
        emotion_id_list = list(dict.fromkeys([int(eid) for eid in emotion_id_list]))
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid emotion_ids format: {str(e)}")
    
    # 验证文件类型
    file_extension = (file.filename or "").split('.')[-1].lower()
    if file_extension not in _allowed_image_extensions():
        raise HTTPException(status_code=400, detail="Unsupported file type")

    with get_db_context() as db:
        session = get_current_session(request, db)
        if not session:
            raise HTTPException(status_code=401, detail="Login required")
        is_admin = False
        user_id = None
        guest_ip = None
        guest_name = None
        
        if session:
            if session.get("is_guest"):
                guest_ip = session.get("guest_ip")
                guest_name = session.get("guest_name")
                # 检查游客操作限制
            else:
                user = db.query(User).filter(User.id == session["user_id"]).first()
                if not user:
                    raise HTTPException(status_code=401, detail="Invalid session")
                user_id = user.id
                is_admin = user.role in [UserRole.ROOT.value, UserRole.ADMIN.value]
        
        # Stream the upload to disk so large images do not sit in memory.
        # This endpoint is deliberately synchronous. FastAPI executes the
        # entire upload, Pillow validation, file copy, thumbnail generation,
        # and SQLAlchemy unit of work in one worker thread. That keeps blocking
        # image/filesystem work off the event loop without sharing a Session
        # across threads.
        temp_file_path = _save_limited_upload(file, suffix=f'.{file_extension}')
        _verify_image_file(temp_file_path)
        metadata = {
            "character_ids": character_id_list,
            "group_id": group_id_list[0] if group_id_list else None,
            "group_ids": group_id_list,
            "feature_tag_ids": feature_tag_id_list,
            "pid": pid,
            "description": description,
            "age_rating": age_rating,
        }

        try:
            _validate_upload_tags(db, character_id_list, group_id_list, feature_tag_id_list)
            upload_hash, duplicate_matches = _duplicate_upload_scan(
                db, temp_file_path, character_id_list
            )
        except Exception:
            try:
                os.unlink(temp_file_path)
            except OSError:
                pass
            raise

        if duplicate_matches:
            os.makedirs(settings.PENDING_PATH, exist_ok=True)
            staged_filename = f"duplicate-{uuid.uuid4().hex}.{file_extension}"
            staged_path = _staged_duplicate_path(staged_filename)
            os.replace(temp_file_path, staged_path)
            token = _make_duplicate_token(
                request,
                "upload",
                staged_filename,
                file.filename or f"upload.{file_extension}",
                file_extension,
                metadata,
                upload_hash,
                duplicate_matches,
            )
            return _duplicate_response(db, duplicate_matches, token, str(staged_path), metadata, file.filename or f"upload.{file_extension}")

        if guest_ip and not check_guest_limit(db, guest_ip):
            try:
                os.unlink(temp_file_path)
            except OSError:
                pass
            raise HTTPException(status_code=429, detail="今日操作次数已用完")

        if is_admin:
            # 管理员直接上传
            try:
                store_path = settings.STORE_PATH
                image_create = schemas.ImageCreate(
                    character_ids=character_id_list,
                    group_ids=group_id_list,
                    feature_tag_ids=feature_tag_id_list,
                    pid=pid,
                    description=description,
                    age_rating=age_rating,
                )

                with ImageService.DUPLICATE_WRITE_LOCK:
                    upload_hash, concurrent_matches = _duplicate_upload_scan(
                        db, temp_file_path, character_id_list, upload_hash
                    )
                    if concurrent_matches:
                        staged_filename = f"duplicate-{uuid.uuid4().hex}.{file_extension}"
                        staged_path = _staged_duplicate_path(staged_filename)
                        os.replace(temp_file_path, staged_path)
                        token = _make_duplicate_token(
                            request,
                            "upload",
                            staged_filename,
                            file.filename or f"upload.{file_extension}",
                            file_extension,
                            metadata,
                            upload_hash,
                            concurrent_matches,
                        )
                        return _duplicate_response(db, concurrent_matches, token, str(staged_path), metadata, file.filename or f"upload.{file_extension}")
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
                            "description": description,
                            "age_rating": age_rating,
                        }),
                        reviewed_at=datetime.utcnow(),
                        reviewed_by=user_id
                    )
                    db.add(pending_request)
                    db.commit()
                
                return schemas.UploadImageResponse(
                    image_id=image.image_id,
                    message="图片上传成功",
                    status="success",
                )
            finally:
                try:
                    os.unlink(temp_file_path)
                except OSError:
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
            try:
                os.unlink(temp_file_path)
            except OSError:
                pass
            raise HTTPException(status_code=400, detail=validation_error)

        # 生成唯一文件名
        unique_filename = f"{uuid.uuid4().hex}.{file_extension}"
        pending_file_path = os.path.join(pending_path, unique_filename)

        with ImageService.DUPLICATE_WRITE_LOCK:
            upload_hash, concurrent_matches = _duplicate_upload_scan(
                db, temp_file_path, character_id_list, upload_hash
            )
            if concurrent_matches:
                staged_filename = f"duplicate-{uuid.uuid4().hex}.{file_extension}"
                staged_path = _staged_duplicate_path(staged_filename)
                os.replace(temp_file_path, staged_path)
                token = _make_duplicate_token(
                    request,
                    "upload",
                    staged_filename,
                    file.filename or f"upload.{file_extension}",
                    file_extension,
                    metadata,
                    upload_hash,
                    concurrent_matches,
                )
                return _duplicate_response(db, concurrent_matches, token, str(staged_path), metadata, file.filename or f"upload.{file_extension}")
            os.replace(temp_file_path, pending_file_path)

        # 创建待审核记录
        try:
            pending_request = PendingRequest(
                request_type="add",
                user_id=user_id,
                guest_ip=guest_ip,
                guest_name=guest_name,
                image_data=json.dumps({
                    "character_ids": character_id_list,
                    "group_id": group_id_list[0] if group_id_list else None,
                    "group_ids": group_id_list,
                    "feature_tag_ids": feature_tag_id_list,
                    "pid": pid,
                    "description": description,
                    "age_rating": age_rating,
                    "perceptual_hash": upload_hash,
                }),
                temp_file_path=pending_file_path,
                original_filename=file.filename
            )
            db.add(pending_request)
            db.commit()

            return schemas.UploadImageResponse(
                image_id="pending",
                message="提交成功，等待管理员审核",
                status="pending",
            )
        except Exception as e:
            # 如果数据库操作失败，清理临时文件
            try:
                if os.path.exists(pending_file_path):
                    os.unlink(pending_file_path)
                elif os.path.exists(temp_file_path):
                    os.unlink(temp_file_path)
            except OSError:
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
    _verify_image_file(str(image_path))

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
            description=temp_upload.description,
            age_rating=temp_upload.age_rating,
        )
        with ImageService.DUPLICATE_WRITE_LOCK:
            upload_hash, duplicate_matches = _duplicate_upload_scan(
                db, str(image_path), temp_upload.character_ids
            )
            if duplicate_matches:
                metadata = temp_upload.model_dump()
                token = _make_duplicate_token(
                    request,
                    "temp",
                    temp_upload.filename,
                    temp_upload.filename,
                    file_extension,
                    metadata,
                    upload_hash,
                    duplicate_matches,
                )
                return _duplicate_response(db, duplicate_matches, token, str(image_path), metadata, temp_upload.filename)
            image = ImageService.create_image(
                db, image_create, str(image_path), temp_upload.filename, file_extension, settings.STORE_PATH
            )

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
                    "description": temp_upload.description,
                    "age_rating": temp_upload.age_rating,
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
        return schemas.UploadImageResponse(
            image_id=image.image_id,
            message="Imported temp image successfully",
            status="success",
        )


@router.post("/upload/duplicates/resolve", response_model=schemas.UploadImageResponse)
def resolve_duplicate_image(choice: schemas.DuplicateImageResolveRequest, request: Request):
    payload = _decode_duplicate_token(choice.token)
    if payload.get("owner") != _duplicate_owner(request):
        raise HTTPException(status_code=403, detail="Duplicate decision belongs to another session")

    source = payload.get("source")
    if source == "upload":
        source_path = _staged_duplicate_path(str(payload.get("filename") or ""))
    elif source == "temp":
        source_path = _safe_temp_image_path(str(payload.get("filename") or ""))
    else:
        raise HTTPException(status_code=400, detail="Invalid duplicate source")
    if not source_path.is_file():
        raise HTTPException(status_code=410, detail="Staged upload no longer exists")

    with get_db_context() as db:
        session = get_current_session(request, db)
        if not session:
            raise HTTPException(status_code=401, detail="Login required")
        user_id = None
        is_admin = False
        guest_ip = None
        guest_name = None
        if session.get("is_guest"):
            guest_ip = session.get("guest_ip")
            guest_name = session.get("guest_name")
        else:
            user = db.query(User).filter(User.id == session["user_id"]).first()
            if not user:
                raise HTTPException(status_code=401, detail="Invalid session")
            user_id = user.id
            is_admin = user.role in [UserRole.ROOT.value, UserRole.ADMIN.value]

        metadata = dict(payload.get("metadata") or {})
        character_ids = [int(item) for item in metadata.get("character_ids") or []]
        group_ids = [int(item) for item in metadata.get("group_ids") or []]
        feature_tag_ids = [int(item) for item in metadata.get("feature_tag_ids") or []]
        _validate_upload_tags(db, character_ids, group_ids, feature_tag_ids)
        expected_ids = set((payload.get("match_ids") or [])[:1])

        if choice.keep == "cancel":
            if source == "upload":
                source_path.unlink(missing_ok=True)
            return schemas.UploadImageResponse(
                image_id="cancelled",
                message="Upload cancelled",
                status="cancelled",
            )

        current_hash, current_matches = _duplicate_upload_scan(db, str(source_path), character_ids)
        if current_hash != payload.get("upload_hash"):
            raise HTTPException(status_code=409, detail="Staged image changed; submit the image again")
        current_ids = {match["image_id"] for match in current_matches[:1]}
        if not current_ids or current_ids != expected_ids:
            raise HTTPException(status_code=409, detail="Duplicate set changed; submit the image again")

        if choice.keep.startswith("merge-existing:"):
            selected_id = choice.keep.partition(":")[2]
            if selected_id not in expected_ids or selected_id not in current_ids:
                raise HTTPException(status_code=409, detail="Selected image was not offered as a duplicate")
            if guest_ip and not check_guest_limit(db, guest_ip):
                raise HTTPException(status_code=429, detail="今日操作次数已用完")
            with ImageService.DUPLICATE_WRITE_LOCK:
                locked_hash, locked_matches = _duplicate_upload_scan(
                    db, str(source_path), character_ids, current_hash,
                )
                locked_ids = {match["image_id"] for match in locked_matches[:1]}
                if locked_hash != payload.get("upload_hash") or locked_ids != current_ids:
                    raise HTTPException(status_code=409, detail="Duplicate set changed; submit the image again")
                if not is_admin:
                    if source != "upload":
                        raise HTTPException(status_code=403, detail="Admin permission required")
                    pending_filename = f"{uuid.uuid4().hex}.{payload.get('file_extension')}"
                    pending_path = Path(settings.PENDING_PATH) / pending_filename
                    os.replace(source_path, pending_path)
                    db.add(PendingRequest(
                        request_type="add",
                        user_id=user_id,
                        guest_ip=guest_ip,
                        guest_name=guest_name,
                        image_data=json.dumps({
                            **metadata,
                            "duplicate_keep": "merge-existing",
                            "duplicate_image_ids": [selected_id],
                            "duplicate_metadata_sources": choice.metadata_sources,
                            "perceptual_hash": payload.get("upload_hash"),
                        }),
                        temp_file_path=str(pending_path),
                        original_filename=str(payload.get("original_filename") or pending_path.name),
                    ))
                    db.commit()
                    return schemas.UploadImageResponse(
                        image_id="pending",
                        message="已提交信息合并请求，等待管理员审核",
                        status="pending_review",
                    )
                existing = db.query(models.Image).filter(
                    models.Image.image_id == selected_id,
                    models.Image.file_status == ImageService.AVAILABLE,
                ).first()
                if not existing:
                    raise HTTPException(status_code=409, detail="Selected existing image is no longer available")
                if not ImageService.image_file_exists(existing):
                    ImageService.mark_file_status(db, existing, exists=False)
                    raise HTTPException(status_code=409, detail="Selected existing image file is missing")
                ImageService.merge_incoming_image_metadata(db, selected_id, metadata, choice.metadata_sources)
                source_path.unlink(missing_ok=True)
                db.commit()
            return schemas.UploadImageResponse(
                image_id=selected_id,
                message="已保留现有图片文件，并同步所选信息",
                status="merged_existing",
            )

        if choice.keep not in {"merge-new", "distinct", "later"}:
            raise HTTPException(status_code=400, detail="Invalid duplicate choice")
        if guest_ip and not check_guest_limit(db, guest_ip):
            raise HTTPException(status_code=429, detail="今日操作次数已用完")

        with ImageService.DUPLICATE_WRITE_LOCK:
            locked_hash, locked_matches = _duplicate_upload_scan(
                db, str(source_path), character_ids, current_hash,
            )
            locked_ids = {match["image_id"] for match in locked_matches[:1]}
            if locked_hash != payload.get("upload_hash") or locked_ids != current_ids:
                raise HTTPException(status_code=409, detail="Duplicate set changed; submit the image again")
            confirmed_ids = sorted(expected_ids & locked_ids)
            if not confirmed_ids or current_ids - expected_ids:
                raise HTTPException(status_code=409, detail="Duplicate set changed; submit the image again")

            if is_admin:
                image = ImageService.create_image(
                    db,
                    schemas.ImageCreate(
                        character_ids=character_ids,
                        group_ids=group_ids,
                        feature_tag_ids=feature_tag_ids,
                        pid=metadata.get("pid"),
                        description=metadata.get("description"),
                        age_rating=metadata.get("age_rating", "all"),
                    ),
                    str(source_path),
                    str(payload.get("original_filename") or source_path.name),
                    str(payload.get("file_extension") or source_path.suffix.lstrip(".")),
                    settings.STORE_PATH,
                )
                if choice.keep == "merge-new":
                    ImageService.merge_duplicate_image_metadata(
                        db, image.image_id, confirmed_ids[0], choice.metadata_sources,
                    )
                elif choice.keep == "distinct":
                    ImageService.remember_distinct_duplicate_pair(
                        db, image.image_id, confirmed_ids[0], decided_by=user_id,
                    )
                if user_id:
                    db.add(PendingRequest(
                        request_type="add",
                        user_id=user_id,
                        status=RequestStatus.APPROVED.value,
                        image_id=image.image_id,
                        image_data=json.dumps({
                            **metadata,
                            **(
                                {"replaced_duplicate_ids": confirmed_ids}
                                if choice.keep == "merge-new" else
                                {"kept_duplicate_ids": confirmed_ids, "duplicate_decision": choice.keep}
                            ),
                        }),
                        reviewed_at=datetime.utcnow(),
                        reviewed_by=user_id,
                    ))
                    db.commit()
                if source == "upload":
                    source_path.unlink(missing_ok=True)
                elif source == "temp":
                    source_path.unlink(missing_ok=True)
                return schemas.UploadImageResponse(
                    image_id=image.image_id,
                    message=(
                        "已保留新图片文件，合并信息并删除现有重复文件"
                        if choice.keep == "merge-new" else
                        "两张图片均已保留" + ("，后续不再提示这一对" if choice.keep == "distinct" else "，下次仍可处理")
                    ),
                    status="merged_new" if choice.keep == "merge-new" else "kept_distinct" if choice.keep == "distinct" else "deferred",
                )

            if source != "upload":
                raise HTTPException(status_code=403, detail="Admin permission required")
            pending_filename = f"{uuid.uuid4().hex}.{payload.get('file_extension')}"
            pending_path = Path(settings.PENDING_PATH) / pending_filename
            os.replace(source_path, pending_path)
            db.add(PendingRequest(
                request_type="add",
                user_id=user_id,
                guest_ip=guest_ip,
                guest_name=guest_name,
                image_data=json.dumps({
                    **metadata,
                    "duplicate_keep": choice.keep,
                    "duplicate_image_ids": confirmed_ids,
                    "duplicate_metadata_sources": choice.metadata_sources,
                    "perceptual_hash": payload.get("upload_hash"),
                }),
                temp_file_path=str(pending_path),
                original_filename=str(payload.get("original_filename") or pending_path.name),
            ))
            db.commit()
            return schemas.UploadImageResponse(
                image_id="pending",
                message=(
                    "已提交图片，等待管理员审核"
                ),
                status="pending_review",
            )


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
