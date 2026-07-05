from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_, func
from typing import List, Optional, Tuple
from datetime import datetime
from . import models, schemas
from .config import settings
import os
import secrets
from PIL import Image as PILImage
import shutil
import uuid

class GroupService:
    """分组服务"""

    @staticmethod
    def _normalize_aliases(aliases: Optional[List[str] | str]) -> List[str]:
        if aliases is None:
            return []
        if isinstance(aliases, str):
            raw = [item.strip() for item in aliases.split(",") if item.strip()]
        else:
            raw = [item.strip() for item in aliases if isinstance(item, str) and item.strip()]
        return list(dict.fromkeys(raw))

    @staticmethod
    def _get_aliases(group: models.Group) -> List[str]:
        return [item.alias for item in group.aliases] if group.aliases else []

    @staticmethod
    def group_to_dict(group: models.Group) -> dict:
        return {
            "id": group.id,
            "name": group.name,
            "aliases": GroupService._get_aliases(group),
            "description": group.description,
            "created_at": group.created_at,
            "updated_at": group.updated_at
        }
    @staticmethod
    def create_group(db: Session, group: schemas.GroupCreate) -> dict:
        """创建分组"""
        payload = group.dict()
        aliases = GroupService._normalize_aliases(payload.pop("aliases", None))
        db_group = models.Group(**payload)
        db.add(db_group)
        db.commit()
        db.refresh(db_group)
        if aliases:
            db.add_all([
                models.GroupAlias(group_id=db_group.id, alias=item)
                for item in aliases
            ])
            db.commit()
            db.refresh(db_group)
        return GroupService.group_to_dict(db_group)
    
    @staticmethod
    def get_group(db: Session, group_id: int) -> Optional[dict]:
        """获取分组"""
        group = db.query(models.Group).filter(models.Group.id == group_id).first()
        if not group:
            return None
        return GroupService.group_to_dict(group)
    
    @staticmethod
    def get_groups(db: Session, skip: int = 0, limit: int = 100) -> List[dict]:
        """获取分组列表"""
        groups = db.query(models.Group).offset(skip).limit(limit).all()
        return [GroupService.group_to_dict(g) for g in groups]
    
    @staticmethod
    def update_group(db: Session, group_id: int, group_update: schemas.GroupUpdate) -> Optional[dict]:
        """更新分组"""
        db_group = db.query(models.Group).filter(models.Group.id == group_id).first()
        if db_group:
            update_data = group_update.dict(exclude_unset=True)
            aliases = None
            if "aliases" in update_data:
                aliases = GroupService._normalize_aliases(update_data.pop("aliases"))
            for field, value in update_data.items():
                setattr(db_group, field, value)
            db.commit()
            db.refresh(db_group)
            if aliases is not None:
                db.query(models.GroupAlias).filter(
                    models.GroupAlias.group_id == db_group.id
                ).delete()
                if aliases:
                    db.add_all([
                        models.GroupAlias(group_id=db_group.id, alias=item)
                        for item in aliases
                    ])
                db.commit()
                db.refresh(db_group)
            return GroupService.group_to_dict(db_group)
        return None
    
    @staticmethod
    def delete_group(db: Session, group_id: int) -> bool:
        """删除分组"""
        db_group = db.query(models.Group).filter(models.Group.id == group_id).first()
        if db_group:
            db.delete(db_group)
            db.commit()
            return True
        return False


class CharacterService:
    """角色服务"""

    @staticmethod
    def _normalize_nicknames(nicknames: Optional[List[str] | str]) -> List[str]:
        if nicknames is None:
            return []
        if isinstance(nicknames, str):
            raw = [item.strip() for item in nicknames.split(",") if item.strip()]
        else:
            raw = [item.strip() for item in nicknames if isinstance(item, str) and item.strip()]
        return list(dict.fromkeys(raw))

    @staticmethod
    def _get_nicknames(character: models.Character) -> List[str]:
        return [item.nickname for item in character.nicknames] if character.nicknames else []

    @staticmethod
    def _feature_tags_to_dict(tags) -> List[dict]:
        return [
            {
                "id": tag.id,
                "name": tag.name,
                "aliases": [item.alias for item in tag.aliases] if tag.aliases else [],
                "description": tag.description,
                "created_at": tag.created_at,
                "updated_at": tag.updated_at,
            }
            for tag in (tags or [])
        ]
    
    @staticmethod
    def create_character(db: Session, character: schemas.CharacterCreate) -> dict:
        """创建角色"""
        payload = character.dict()
        nicknames = CharacterService._normalize_nicknames(payload.pop("nicknames", None))
        feature_tag_ids = payload.pop("feature_tag_ids", None) or []
        db_character = models.Character(**payload)
        if feature_tag_ids:
            db_character.feature_tags = db.query(models.FeatureTag).filter(
                models.FeatureTag.id.in_(feature_tag_ids)
            ).all()
        db.add(db_character)
        db.commit()
        db.refresh(db_character)

        if nicknames:
            db.add_all([
                models.CharacterNickname(character_id=db_character.id, nickname=item)
                for item in nicknames
            ])
            db.commit()
            db.refresh(db_character)
        # 获取分组名称
        group = db.query(models.Group).filter(models.Group.id == db_character.group_id).first()
        return {
            "id": db_character.id,
            "name": db_character.name,
            "nicknames": CharacterService._get_nicknames(db_character),
            "feature_tag_ids": [tag.id for tag in db_character.feature_tags],
            "feature_tags": CharacterService._feature_tags_to_dict(db_character.feature_tags),
            "group_id": db_character.group_id,
            "description": db_character.description,
            "created_at": db_character.created_at,
            "updated_at": db_character.updated_at,
            "group_name": group.name if group else ""
        }
    
    @staticmethod
    def get_character(db: Session, character_id: int) -> Optional[dict]:
        """获取角色"""
        result = db.query(models.Character, models.Group).join(models.Group).filter(
            models.Character.id == character_id
        ).first()
        
        if not result:
            return None
        
        character, group = result
        return {
            "id": character.id,
            "name": character.name,
            "nicknames": CharacterService._get_nicknames(character),
            "feature_tag_ids": [tag.id for tag in character.feature_tags],
            "feature_tags": CharacterService._feature_tags_to_dict(character.feature_tags),
            "group_id": character.group_id,
            "description": character.description,
            "created_at": character.created_at,
            "updated_at": character.updated_at,
            "group_name": group.name
        }
    
    @staticmethod
    def get_characters(db: Session, group_id: Optional[int] = None, skip: int = 0, limit: int = 100) -> List[dict]:
        """获取角色列表，返回包含分组名称的字典"""
        query = db.query(models.Character, models.Group).join(models.Group)
        if group_id:
            query = query.filter(models.Character.group_id == group_id)
        
        results = query.offset(skip).limit(limit).all()
        
        character_list = []
        for character, group in results:
            character_dict = {
                "id": character.id,
                "name": character.name,
                "nicknames": CharacterService._get_nicknames(character),
                "feature_tag_ids": [tag.id for tag in character.feature_tags],
                "feature_tags": CharacterService._feature_tags_to_dict(character.feature_tags),
                "group_id": character.group_id,
                "description": character.description,
                "created_at": character.created_at,
                "updated_at": character.updated_at,
                "group_name": group.name
            }
            character_list.append(character_dict)
        
        return character_list
    
    @staticmethod
    def update_character(db: Session, character_id: int, character_update: schemas.CharacterUpdate) -> Optional[dict]:
        """更新角色"""
        db_character = db.query(models.Character).filter(models.Character.id == character_id).first()
        if db_character:
            update_data = character_update.dict(exclude_unset=True)
            nicknames = None
            if "nicknames" in update_data:
                nicknames = CharacterService._normalize_nicknames(update_data.pop("nicknames"))
            feature_tag_ids = None
            if "feature_tag_ids" in update_data:
                feature_tag_ids = update_data.pop("feature_tag_ids") or []
            for field, value in update_data.items():
                setattr(db_character, field, value)
            db.commit()
            db.refresh(db_character)

            if nicknames is not None:
                db.query(models.CharacterNickname).filter(
                    models.CharacterNickname.character_id == db_character.id
                ).delete()
                if nicknames:
                    db.add_all([
                        models.CharacterNickname(character_id=db_character.id, nickname=item)
                        for item in nicknames
                    ])
                db.commit()
                db.refresh(db_character)
            if feature_tag_ids is not None:
                db_character.feature_tags = db.query(models.FeatureTag).filter(
                    models.FeatureTag.id.in_(feature_tag_ids)
                ).all() if feature_tag_ids else []
                db.commit()
                db.refresh(db_character)
            # 获取分组名称
            group = db.query(models.Group).filter(models.Group.id == db_character.group_id).first()
            return {
                "id": db_character.id,
                "name": db_character.name,
                "nicknames": CharacterService._get_nicknames(db_character),
                "feature_tag_ids": [tag.id for tag in db_character.feature_tags],
                "feature_tags": CharacterService._feature_tags_to_dict(db_character.feature_tags),
                "group_id": db_character.group_id,
                "description": db_character.description,
                "created_at": db_character.created_at,
                "updated_at": db_character.updated_at,
                "group_name": group.name if group else ""
            }
        return None
    
    @staticmethod
    def delete_character(db: Session, character_id: int) -> bool:
        """删除角色"""
        db_character = db.query(models.Character).filter(models.Character.id == character_id).first()
        if db_character:
            db.delete(db_character)
            db.commit()
            return True
        return False


class FeatureTagService:
    """Feature tag service."""

    @staticmethod
    def _normalize_aliases(aliases: Optional[List[str] | str]) -> List[str]:
        return GroupService._normalize_aliases(aliases)

    @staticmethod
    def _get_aliases(tag: models.FeatureTag) -> List[str]:
        return [item.alias for item in tag.aliases] if tag.aliases else []

    @staticmethod
    def tag_to_dict(tag: models.FeatureTag) -> dict:
        return {
            "id": tag.id,
            "name": tag.name,
            "aliases": FeatureTagService._get_aliases(tag),
            "description": tag.description,
            "created_at": tag.created_at,
            "updated_at": tag.updated_at,
        }

    @staticmethod
    def create_feature_tag(db: Session, tag: schemas.FeatureTagCreate) -> dict:
        payload = tag.dict()
        aliases = FeatureTagService._normalize_aliases(payload.pop("aliases", None))
        db_tag = models.FeatureTag(**payload)
        db.add(db_tag)
        db.commit()
        db.refresh(db_tag)
        if aliases:
            db.add_all([
                models.FeatureTagAlias(feature_tag_id=db_tag.id, alias=item)
                for item in aliases
            ])
            db.commit()
            db.refresh(db_tag)
        return FeatureTagService.tag_to_dict(db_tag)

    @staticmethod
    def get_feature_tags(db: Session, skip: int = 0, limit: int = 1000) -> List[dict]:
        tags = db.query(models.FeatureTag).order_by(models.FeatureTag.name.asc()).offset(skip).limit(limit).all()
        return [FeatureTagService.tag_to_dict(tag) for tag in tags]

    @staticmethod
    def update_feature_tag(db: Session, tag_id: int, tag_update: schemas.FeatureTagUpdate) -> Optional[dict]:
        db_tag = db.query(models.FeatureTag).filter(models.FeatureTag.id == tag_id).first()
        if not db_tag:
            return None
        update_data = tag_update.dict(exclude_unset=True)
        aliases = None
        if "aliases" in update_data:
            aliases = FeatureTagService._normalize_aliases(update_data.pop("aliases"))
        for field, value in update_data.items():
            setattr(db_tag, field, value)
        db.commit()
        db.refresh(db_tag)
        if aliases is not None:
            db.query(models.FeatureTagAlias).filter(
                models.FeatureTagAlias.feature_tag_id == db_tag.id
            ).delete()
            if aliases:
                db.add_all([
                    models.FeatureTagAlias(feature_tag_id=db_tag.id, alias=item)
                    for item in aliases
                ])
            db.commit()
            db.refresh(db_tag)
        return FeatureTagService.tag_to_dict(db_tag)

    @staticmethod
    def delete_feature_tag(db: Session, tag_id: int) -> bool:
        db_tag = db.query(models.FeatureTag).filter(models.FeatureTag.id == tag_id).first()
        if not db_tag:
            return False
        db.delete(db_tag)
        db.commit()
        return True


class ImageService:
    """Image service helpers."""

    AVAILABLE = "available"
    MISSING = "missing"
    ARCHIVED = "archived"
    DELETED = "deleted"

    THUMB_PENDING = "pending"
    THUMB_READY = "ready"
    THUMB_MISSING = "missing"
    THUMB_FAILED = "failed"
    
    @staticmethod
    def image_full_path(image: models.Image) -> str:
        file_path = (image.file_path or "").replace("\\", "/").lstrip("/")
        return os.path.join(settings.BASE_DIR, *file_path.split("/"))

    @staticmethod
    def image_file_exists(image: models.Image) -> bool:
        return bool(image.file_path) and os.path.isfile(ImageService.image_full_path(image))

    @staticmethod
    def mark_file_status(db: Session, image: models.Image, exists: Optional[bool] = None) -> str:
        exists = ImageService.image_file_exists(image) if exists is None else exists
        image.file_status = ImageService.AVAILABLE if exists else ImageService.MISSING
        image.file_checked_at = datetime.utcnow()
        return image.file_status

    @staticmethod
    def thumb_path(image: models.Image) -> str:
        os.makedirs(settings.THUMB_PATH, exist_ok=True)
        return os.path.join(settings.THUMB_PATH, f"{image.image_id}.webp")

    @staticmethod
    def ensure_thumbnail(image: models.Image) -> bool:
        if not ImageService.image_file_exists(image):
            image.thumb_status = ImageService.THUMB_MISSING
            return False

        source = ImageService.image_full_path(image)
        thumb = ImageService.thumb_path(image)
        try:
            if os.path.exists(thumb) and os.path.getmtime(thumb) >= os.path.getmtime(source):
                image.thumb_status = ImageService.THUMB_READY
                return True

            with PILImage.open(source) as img:
                img.thumbnail((settings.THUMBNAIL_SIZE, settings.THUMBNAIL_SIZE))
                if img.mode not in ("RGB", "RGBA"):
                    img = img.convert("RGB")
                img.save(
                    thumb,
                    "WEBP",
                    quality=settings.THUMBNAIL_QUALITY,
                    method=settings.THUMBNAIL_WEBP_METHOD,
                )
            image.thumb_status = ImageService.THUMB_READY
            return True
        except Exception:
            image.thumb_status = ImageService.THUMB_FAILED
            return False

    @staticmethod
    def _unique_ints(values: Optional[List[int]]) -> List[int]:
        result = []
        for value in values or []:
            try:
                item = int(value)
            except (TypeError, ValueError):
                continue
            if item not in result:
                result.append(item)
        return result

    @staticmethod
    def _apply_tag_relationships(
        db: Session,
        db_image: models.Image,
        character_ids: Optional[List[int]],
        group_ids: Optional[List[int]],
        feature_tag_ids: Optional[List[int]]
    ) -> None:
        character_ids = ImageService._unique_ints(character_ids)
        explicit_group_ids = ImageService._unique_ints(group_ids)
        explicit_feature_ids = ImageService._unique_ints(feature_tag_ids)

        characters = db.query(models.Character).filter(
            models.Character.id.in_(character_ids)
        ).all() if character_ids else []

        group_id_set = set(explicit_group_ids)
        feature_id_set = set(explicit_feature_ids)
        for character in characters:
            group_id_set.add(character.group_id)
            for tag in character.feature_tags or []:
                feature_id_set.add(tag.id)

        groups = db.query(models.Group).filter(
            models.Group.id.in_(group_id_set)
        ).all() if group_id_set else []
        feature_tags = db.query(models.FeatureTag).filter(
            models.FeatureTag.id.in_(feature_id_set)
        ).all() if feature_id_set else []

        db_image.characters = characters
        db_image.groups = groups
        db_image.feature_tags = feature_tags

    @staticmethod
    def image_to_dict(image: models.Image) -> dict:
        return {
            "image_id": image.image_id,
            "pid": image.pid,
            "description": image.description,
            "original_filename": image.original_filename,
            "file_extension": image.file_extension,
            "file_size": image.file_size,
            "width": image.width,
            "height": image.height,
            "file_path": image.file_path,
            "file_status": image.file_status,
            "thumb_status": image.thumb_status,
            "created_at": image.created_at,
            "updated_at": image.updated_at,
            "characters": [
                {
                    "id": char.id,
                    "name": char.name,
                    "nicknames": CharacterService._get_nicknames(char),
                    "group_id": char.group_id,
                    "feature_tag_ids": [tag.id for tag in char.feature_tags],
                    "feature_tags": CharacterService._feature_tags_to_dict(char.feature_tags),
                    "description": char.description,
                    "created_at": char.created_at,
                    "updated_at": char.updated_at,
                    "group_name": char.group.name if char.group else ""
                }
                for char in image.characters
            ],
            "groups": [
                {
                    "id": group.id,
                    "name": group.name,
                    "aliases": GroupService._get_aliases(group),
                    "description": group.description,
                    "created_at": group.created_at,
                    "updated_at": group.updated_at,
                }
                for group in image.groups
            ],
            "feature_tags": [
                {
                    "id": tag.id,
                    "name": tag.name,
                    "aliases": FeatureTagService._get_aliases(tag),
                    "description": tag.description,
                    "created_at": tag.created_at,
                    "updated_at": tag.updated_at,
                }
                for tag in image.feature_tags
            ]
        }

    @staticmethod
    def generate_image_id() -> str:
        """生成10位十六进制图片ID"""
        return secrets.token_hex(5).upper()  # 生成10位十六进制字符串
    
    @staticmethod
    def save_image_file(file_path: str, image_id: str, file_extension: str, store_path: str) -> Tuple[str, dict]:
        """保存图片文件并返回相对路径和图片信息"""
        # 确保存储目录存在
        os.makedirs(store_path, exist_ok=True)
        
        # 新文件路径
        new_filename = f"{image_id}.{file_extension.lower()}"
        new_file_path = os.path.join(store_path, new_filename)
        relative_path = f"resource/store/{new_filename}"
        
        # 复制文件
        shutil.copy2(file_path, new_file_path)
        
        # 获取图片信息
        image_info = {}
        try:
            with PILImage.open(new_file_path) as img:
                image_info['width'], image_info['height'] = img.size
            image_info['file_size'] = os.path.getsize(new_file_path)
        except Exception:
            pass
        
        return relative_path, image_info
    
    @staticmethod
    def create_image(db: Session, image: schemas.ImageCreate, file_path: str, original_filename: str, 
                    file_extension: str, store_path: str) -> models.Image:
        """创建图片记录"""
        # 生成唯一ID
        while True:
            image_id = ImageService.generate_image_id()
            if not db.query(models.Image).filter(models.Image.image_id == image_id).first():
                break
        
        # 保存图片文件
        relative_path, image_info = ImageService.save_image_file(
            file_path, image_id, file_extension, store_path
        )
        
        # 创建数据库记录
        db_image = models.Image(
            image_id=image_id,
            pid=image.pid,
            description=image.description,
            original_filename=original_filename,
            file_extension=file_extension,
            file_path=relative_path,
            file_status=ImageService.AVAILABLE,
            file_checked_at=datetime.utcnow(),
            thumb_status=ImageService.THUMB_PENDING,
            **image_info
        )
        
        # 关联角色
        ImageService._apply_tag_relationships(
            db,
            db_image,
            image.character_ids,
            image.group_ids,
            image.feature_tag_ids,
        )

        ImageService.ensure_thumbnail(db_image)
        
        db.add(db_image)
        db.commit()
        db.refresh(db_image)
        return db_image
    
    @staticmethod
    def get_image(db: Session, image_id: str) -> Optional[dict]:
        """Return image metadata only when the stored file exists."""
        image = db.query(models.Image).options(
            joinedload(models.Image.characters).joinedload(models.Character.group),
            joinedload(models.Image.characters).joinedload(models.Character.feature_tags),
            joinedload(models.Image.groups),
            joinedload(models.Image.feature_tags),
        ).filter(
            models.Image.image_id == image_id,
            models.Image.file_status == ImageService.AVAILABLE
        ).first()
        
        if not image:
            return None
        if not ImageService.image_file_exists(image):
            ImageService.mark_file_status(db, image, exists=False)
            db.commit()
            return None
        return ImageService.image_to_dict(image)

    @staticmethod
    def get_random_image(
        db: Session,
        group_id: Optional[int] = None,
        character_id: Optional[int] = None,
        exclude_group_id: Optional[int] = None
    ) -> Optional[dict]:
        """Return a random image whose stored file still exists."""
        query = db.query(models.Image).options(
            joinedload(models.Image.characters).joinedload(models.Character.group),
            joinedload(models.Image.characters).joinedload(models.Character.feature_tags),
            joinedload(models.Image.groups),
            joinedload(models.Image.feature_tags),
        ).filter(models.Image.file_status == ImageService.AVAILABLE)

        if group_id:
            query = query.join(models.Image.groups).filter(
                models.Group.id == group_id
            )

        if character_id:
            query = query.join(models.Image.characters).filter(
                models.Character.id == character_id
            )

        if exclude_group_id:
            query = query.join(models.Image.groups).filter(
                models.Group.id != exclude_group_id
            )

        image = query.distinct().order_by(func.random()).first()
        if not image:
            return None
        if not ImageService.image_file_exists(image):
            ImageService.mark_file_status(db, image, exists=False)
            db.commit()
            return None

        image_dict = ImageService.image_to_dict(image)
        return {
            "image_id": image_dict["image_id"],
            "file_path": image_dict["file_path"],
            "pid": image_dict["pid"],
            "characters": image_dict["characters"],
            "groups": image_dict["groups"],
            "feature_tags": image_dict["feature_tags"],
        }
    
    @staticmethod
    def search_images(db: Session, params: schemas.ImageSearchParams) -> Tuple[List[dict], int]:
        """Search images and ignore records whose files are missing."""
        query = db.query(models.Image).options(
            joinedload(models.Image.characters).joinedload(models.Character.group),
            joinedload(models.Image.characters).joinedload(models.Character.feature_tags),
            joinedload(models.Image.groups),
            joinedload(models.Image.feature_tags),
        ).filter(models.Image.file_status == ImageService.AVAILABLE)
        
        if params.group_id:
            query = query.join(models.Image.groups).filter(
                models.Group.id == params.group_id
            )
        
        if params.character_id:
            query = query.join(models.Image.characters).filter(
                models.Character.id == params.character_id
            )

        if params.feature_tag_id:
            query = query.join(models.Image.feature_tags).filter(
                models.FeatureTag.id == params.feature_tag_id
            )
        
        if params.pid:
            query = query.filter(models.Image.pid.like(f"%{params.pid}%"))
        
        if params.description:
            query = query.filter(models.Image.description.like(f"%{params.description}%"))
        
        offset = params.offset or 0
        limit = params.limit or settings.DEFAULT_PAGE_SIZE
        query = query.distinct()
        total = query.order_by(None).count()
        images = query.order_by(
            models.Image.created_at.desc(),
            models.Image.image_id.desc()
        ).offset(offset).limit(limit).all()
        return [ImageService.image_to_dict(img) for img in images], total
    
    @staticmethod
    def update_image(db: Session, image_id: str, image_update: schemas.ImageUpdate) -> Optional[models.Image]:
        """更新图片"""
        db_image = db.query(models.Image).filter(models.Image.image_id == image_id).first()
        if db_image:
            update_data = image_update.dict(exclude_unset=True, exclude={'character_ids', 'group_ids', 'feature_tag_ids'})
            for field, value in update_data.items():
                setattr(db_image, field, value)
            
            # 更新角色关联
            if (
                image_update.character_ids is not None
                or image_update.group_ids is not None
                or image_update.feature_tag_ids is not None
            ):
                ImageService._apply_tag_relationships(
                    db,
                    db_image,
                    image_update.character_ids if image_update.character_ids is not None else [c.id for c in db_image.characters],
                    image_update.group_ids if image_update.group_ids is not None else [g.id for g in db_image.groups],
                    image_update.feature_tag_ids if image_update.feature_tag_ids is not None else [t.id for t in db_image.feature_tags],
                )
            
            db.commit()
            db.refresh(db_image)
        return db_image
    
    @staticmethod
    def delete_image(db: Session, image_id: str, store_path: str) -> bool:
        """删除图片"""
        db_image = db.query(models.Image).filter(models.Image.image_id == image_id).first()
        if db_image:
            # 删除实际文件
            try:
                full_path = os.path.join(settings.BASE_DIR, db_image.file_path)
                if os.path.exists(full_path):
                    os.remove(full_path)
                thumb_path = ImageService.thumb_path(db_image)
                if os.path.exists(thumb_path):
                    os.remove(thumb_path)
            except Exception:
                pass
            
            # 删除数据库记录
            db.delete(db_image)
            db.commit()
            return True
        return False
    
    @staticmethod
    def _store_image_files(store_path: str) -> set[str]:
        if not os.path.exists(store_path):
            return set()
        allowed_extensions = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp'}
        files = set()
        for root, _, filenames in os.walk(store_path):
            for filename in filenames:
                if os.path.splitext(filename)[1].lower() not in allowed_extensions:
                    continue
                full_path = os.path.join(root, filename)
                rel_path = os.path.relpath(full_path, settings.BASE_DIR).replace("\\", "/")
                files.add(rel_path)
        return files

    @staticmethod
    def storage_audit(db: Session, store_path: str, update_status: bool = False, sample_limit: int = 10) -> dict:
        images = db.query(models.Image).all()
        referenced_paths = {
            (image.file_path or "").replace("\\", "/").lstrip("/")
            for image in images
            if image.file_path
        }
        store_files = ImageService._store_image_files(store_path)

        available = 0
        missing = 0
        archived = 0
        deleted = 0
        thumb_missing = 0
        thumb_failed = 0
        missing_samples = []
        thumb_missing_samples = []

        for image in images:
            exists = ImageService.image_file_exists(image)
            if exists:
                available += 1
            else:
                missing += 1
                if len(missing_samples) < sample_limit:
                    missing_samples.append({
                        "image_id": image.image_id,
                        "file_path": image.file_path,
                        "file_status": image.file_status,
                    })

            if image.file_status == ImageService.ARCHIVED:
                archived += 1
            if image.file_status == ImageService.DELETED:
                deleted += 1

            thumb_exists = os.path.exists(ImageService.thumb_path(image))
            if exists and not thumb_exists:
                thumb_missing += 1
                if len(thumb_missing_samples) < sample_limit:
                    thumb_missing_samples.append({
                        "image_id": image.image_id,
                        "file_path": image.file_path,
                        "thumb_status": image.thumb_status,
                    })
            if image.thumb_status == ImageService.THUMB_FAILED:
                thumb_failed += 1

            if update_status:
                if exists:
                    image.file_status = ImageService.AVAILABLE
                elif image.file_status != ImageService.ARCHIVED:
                    image.file_status = ImageService.MISSING
                image.file_checked_at = datetime.utcnow()
                if not exists:
                    image.thumb_status = ImageService.THUMB_MISSING
                elif thumb_exists:
                    image.thumb_status = ImageService.THUMB_READY
                elif image.thumb_status not in {ImageService.THUMB_FAILED, ImageService.THUMB_PENDING}:
                    image.thumb_status = ImageService.THUMB_PENDING

        orphan_files = sorted(store_files - referenced_paths)
        if update_status:
            db.commit()

        return {
            "total_records": len(images),
            "available_records": available,
            "missing_records": missing,
            "archived_records": archived,
            "deleted_records": deleted,
            "orphan_files": len(orphan_files),
            "orphan_file_samples": orphan_files[:sample_limit],
            "thumb_missing": thumb_missing,
            "thumb_failed": thumb_failed,
            "missing_record_samples": missing_samples,
            "thumb_missing_samples": thumb_missing_samples,
        }

    @staticmethod
    def cleanup_orphaned_records(db: Session, store_path: str, mode: str = "archive") -> int:
        """Archive or delete database records whose image files are missing."""
        count = 0
        images = db.query(models.Image).all()
        
        for image in images:
            if not ImageService.image_file_exists(image):
                if mode == "delete":
                    db.delete(image)
                    count += 1
                elif image.file_status != ImageService.ARCHIVED:
                    image.file_status = ImageService.ARCHIVED
                    image.file_checked_at = datetime.utcnow()
                    image.thumb_status = ImageService.THUMB_MISSING
                    count += 1
                else:
                    image.file_checked_at = datetime.utcnow()
        
        if count > 0:
            db.commit()
        
        return count

    @staticmethod
    def rebuild_missing_thumbnails(db: Session, limit: int = 200, force: bool = False) -> dict:
        query = db.query(models.Image).filter(models.Image.file_status == ImageService.AVAILABLE)
        if not force:
            query = query.filter(models.Image.thumb_status != ImageService.THUMB_READY)
        query = query.order_by(models.Image.created_at.desc(), models.Image.image_id.desc())
        if limit:
            query = query.limit(limit)

        processed = 0
        ready = 0
        failed = 0
        missing = 0
        for image in query.all():
            processed += 1
            if force:
                try:
                    os.remove(ImageService.thumb_path(image))
                except FileNotFoundError:
                    pass
                except OSError:
                    pass
            if ImageService.ensure_thumbnail(image):
                ready += 1
            elif image.thumb_status == ImageService.THUMB_MISSING:
                image.file_status = ImageService.MISSING
                image.file_checked_at = datetime.utcnow()
                missing += 1
            else:
                failed += 1
        if processed:
            db.commit()
        return {
            "processed": processed,
            "ready": ready,
            "failed": failed,
            "missing": missing,
        }

    @staticmethod
    def move_orphaned_files_to_temp(db: Session, store_path: str, temp_path: str) -> int:
        """扫描store目录，将数据库中不存在的图片移入temp目录"""
        if not os.path.exists(store_path):
            return 0

        os.makedirs(temp_path, exist_ok=True)

        allowed_extensions = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp'}
        existing_ids = {row[0] for row in db.query(models.Image.image_id).all()}

        moved = 0
        for filename in os.listdir(store_path):
            ext = os.path.splitext(filename)[1].lower()
            if ext not in allowed_extensions:
                continue

            image_id = os.path.splitext(filename)[0]
            if image_id in existing_ids:
                continue

            src_path = os.path.join(store_path, filename)
            if not os.path.isfile(src_path):
                continue

            dest_path = os.path.join(temp_path, filename)
            if os.path.exists(dest_path):
                base, ext = os.path.splitext(filename)
                dest_path = os.path.join(temp_path, f"{base}_{uuid.uuid4().hex}{ext}")

            try:
                shutil.move(src_path, dest_path)
                moved += 1
            except Exception:
                continue

        return moved


class SystemService:
    """系统服务"""
    
    @staticmethod
    def get_system_status(db: Session, store_path: str, temp_path: str) -> schemas.SystemStatus:
        """获取系统状态"""
        total_images = db.query(func.count(models.Image.image_id)).scalar()
        available_images = db.query(func.count(models.Image.image_id)).filter(
            models.Image.file_status == ImageService.AVAILABLE
        ).scalar()
        missing_images = db.query(func.count(models.Image.image_id)).filter(
            models.Image.file_status == ImageService.MISSING
        ).scalar()
        archived_images = db.query(func.count(models.Image.image_id)).filter(
            models.Image.file_status == ImageService.ARCHIVED
        ).scalar()
        thumb_missing = db.query(func.count(models.Image.image_id)).filter(
            models.Image.file_status == ImageService.AVAILABLE,
            models.Image.thumb_status != ImageService.THUMB_READY
        ).scalar()
        thumb_failed = db.query(func.count(models.Image.image_id)).filter(
            models.Image.thumb_status == ImageService.THUMB_FAILED
        ).scalar()
        total_groups = db.query(func.count(models.Group.id)).scalar()
        total_characters = db.query(func.count(models.Character.id)).scalar()
        
        # 统计temp目录的图片数量
        temp_images_count = 0
        if os.path.exists(temp_path):
            temp_images_count = len([
                f for f in os.listdir(temp_path) 
                if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp'))
            ])
        
        return schemas.SystemStatus(
            total_images=total_images,
            available_images=available_images,
            missing_images=missing_images,
            archived_images=archived_images,
            thumb_missing=thumb_missing,
            thumb_failed=thumb_failed,
            total_groups=total_groups,
            total_characters=total_characters,
            temp_images_count=temp_images_count,
            store_path=store_path,
            temp_path=temp_path
        )
