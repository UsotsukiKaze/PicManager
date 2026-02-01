from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_, func
from typing import List, Optional, Tuple
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
    def create_group(db: Session, group: schemas.GroupCreate) -> dict:
        """创建分组"""
        db_group = models.Group(**group.dict())
        db.add(db_group)
        db.commit()
        db.refresh(db_group)
        return {
            "id": db_group.id,
            "name": db_group.name,
            "description": db_group.description,
            "created_at": db_group.created_at,
            "updated_at": db_group.updated_at
        }
    
    @staticmethod
    def get_group(db: Session, group_id: int) -> Optional[dict]:
        """获取分组"""
        group = db.query(models.Group).filter(models.Group.id == group_id).first()
        if not group:
            return None
        return {
            "id": group.id,
            "name": group.name,
            "description": group.description,
            "created_at": group.created_at,
            "updated_at": group.updated_at
        }
    
    @staticmethod
    def get_groups(db: Session, skip: int = 0, limit: int = 100) -> List[dict]:
        """获取分组列表"""
        groups = db.query(models.Group).offset(skip).limit(limit).all()
        return [
            {
                "id": g.id,
                "name": g.name,
                "description": g.description,
                "created_at": g.created_at,
                "updated_at": g.updated_at
            }
            for g in groups
        ]
    
    @staticmethod
    def update_group(db: Session, group_id: int, group_update: schemas.GroupUpdate) -> Optional[dict]:
        """更新分组"""
        db_group = db.query(models.Group).filter(models.Group.id == group_id).first()
        if db_group:
            update_data = group_update.dict(exclude_unset=True)
            for field, value in update_data.items():
                setattr(db_group, field, value)
            db.commit()
            db.refresh(db_group)
            return {
                "id": db_group.id,
                "name": db_group.name,
                "description": db_group.description,
                "created_at": db_group.created_at,
                "updated_at": db_group.updated_at
            }
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
    def create_character(db: Session, character: schemas.CharacterCreate) -> dict:
        """创建角色"""
        payload = character.dict()
        nicknames = CharacterService._normalize_nicknames(payload.pop("nicknames", None))
        db_character = models.Character(**payload)
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
            # 获取分组名称
            group = db.query(models.Group).filter(models.Group.id == db_character.group_id).first()
            return {
                "id": db_character.id,
                "name": db_character.name,
                "nicknames": CharacterService._get_nicknames(db_character),
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


class ImageService:
    """图片服务"""
    
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
            **image_info
        )
        
        # 关联角色
        if image.character_ids:
            characters = db.query(models.Character).filter(
                models.Character.id.in_(image.character_ids)
            ).all()
            db_image.characters = characters
        
        db.add(db_image)
        db.commit()
        db.refresh(db_image)
        return db_image
    
    @staticmethod
    def get_image(db: Session, image_id: str) -> Optional[dict]:
        """获取图片"""
        image = db.query(models.Image).options(
            joinedload(models.Image.characters).joinedload(models.Character.group)
        ).filter(models.Image.image_id == image_id).first()
        
        if not image:
            return None
        
        # 转换为字典格式
        image_dict = {
            "image_id": image.image_id,
            "pid": image.pid,
            "description": image.description,
            "original_filename": image.original_filename,
            "file_extension": image.file_extension,
            "file_size": image.file_size,
            "width": image.width,
            "height": image.height,
            "file_path": image.file_path,
            "created_at": image.created_at,
            "updated_at": image.updated_at,
            "characters": [
                {
                    "id": char.id,
                    "name": char.name,
                    "nicknames": CharacterService._get_nicknames(char),
                    "group_id": char.group_id,
                    "description": char.description,
                    "created_at": char.created_at,
                    "updated_at": char.updated_at,
                    "group_name": char.group.name if char.group else ""
                }
                for char in image.characters
            ]
        }
        
        return image_dict

    @staticmethod
    def get_random_image(
        db: Session,
        group_id: Optional[int] = None,
        character_id: Optional[int] = None,
        exclude_group_id: Optional[int] = None
    ) -> Optional[dict]:
        """获取随机图片"""
        query = db.query(models.Image).options(
            joinedload(models.Image.characters).joinedload(models.Character.group)
        )

        if group_id:
            query = query.join(models.Image.characters).join(models.Character.group).filter(
                models.Group.id == group_id
            )

        if character_id:
            query = query.join(models.Image.characters).filter(
                models.Character.id == character_id
            )

        if exclude_group_id:
            query = query.join(models.Image.characters).join(models.Character.group).filter(
                models.Group.id != exclude_group_id
            )

        image = query.distinct(models.Image.image_id).order_by(func.random()).first()
        if not image:
            return None

        return {
            "image_id": image.image_id,
            "file_path": image.file_path,
            "pid": image.pid,
            "characters": [
                {
                    "id": char.id,
                    "name": char.name,
                    "nicknames": CharacterService._get_nicknames(char),
                    "group_id": char.group_id,
                    "description": char.description,
                    "created_at": char.created_at,
                    "updated_at": char.updated_at,
                    "group_name": char.group.name if char.group else ""
                }
                for char in image.characters
            ]
        }
    
    @staticmethod
    def search_images(db: Session, params: schemas.ImageSearchParams) -> Tuple[List[dict], int]:
        """搜索图片"""
        query = db.query(models.Image).options(
            joinedload(models.Image.characters).joinedload(models.Character.group)
        )
        
        # 构建查询条件
        if params.group_id:
            query = query.join(models.Image.characters).join(models.Character.group).filter(
                models.Group.id == params.group_id
            )
        
        if params.character_id:
            query = query.join(models.Image.characters).filter(
                models.Character.id == params.character_id
            )
        
        if params.pid:
            query = query.filter(models.Image.pid.like(f"%{params.pid}%"))
        
        if params.description:
            query = query.filter(models.Image.description.like(f"%{params.description}%"))
        
        # 去重并获取总数
        query = query.distinct(models.Image.image_id)
        total = query.count()
        
        # 分页
        images = query.offset(params.offset).limit(params.limit).all()
        
        # 转换为字典列表
        images_dict = [
            {
                "image_id": img.image_id,
                "pid": img.pid,
                "description": img.description,
                "original_filename": img.original_filename,
                "file_extension": img.file_extension,
                "file_size": img.file_size,
                "width": img.width,
                "height": img.height,
                "file_path": img.file_path,
                "created_at": img.created_at,
                "updated_at": img.updated_at,
                "characters": [
                    {
                        "id": char.id,
                        "name": char.name,
                        "nicknames": CharacterService._get_nicknames(char),
                        "group_id": char.group_id,
                        "description": char.description,
                        "created_at": char.created_at,
                        "updated_at": char.updated_at,
                        "group_name": char.group.name if char.group else ""
                    }
                    for char in img.characters
                ]
            }
            for img in images
        ]
        
        return images_dict, total
    
    @staticmethod
    def update_image(db: Session, image_id: str, image_update: schemas.ImageUpdate) -> Optional[models.Image]:
        """更新图片"""
        db_image = db.query(models.Image).filter(models.Image.image_id == image_id).first()
        if db_image:
            update_data = image_update.dict(exclude_unset=True, exclude={'character_ids'})
            for field, value in update_data.items():
                setattr(db_image, field, value)
            
            # 更新角色关联
            if image_update.character_ids is not None:
                characters = db.query(models.Character).filter(
                    models.Character.id.in_(image_update.character_ids)
                ).all()
                db_image.characters = characters
            
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
            except Exception:
                pass
            
            # 删除数据库记录
            db.delete(db_image)
            db.commit()
            return True
        return False
    
    @staticmethod
    def cleanup_orphaned_records(db: Session, store_path: str) -> int:
        """清理孤儿记录（数据库中存在但文件不存在的记录）"""
        count = 0
        images = db.query(models.Image).all()
        base_path = os.path.dirname(os.path.dirname(store_path))
        
        for image in images:
            full_path = os.path.join(base_path, image.file_path)
            if not os.path.exists(full_path):
                db.delete(image)
                count += 1
        
        if count > 0:
            db.commit()
        
        return count

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
            total_groups=total_groups,
            total_characters=total_characters,
            temp_images_count=temp_images_count,
            store_path=store_path,
            temp_path=temp_path
        )