import os
import secrets
import hashlib
from PIL import Image
from typing import Tuple, Optional
import mimetypes
from .config import settings
from .logger import log_info, log_error

def generate_image_id() -> str:
    """生成唯一的10位十六进制图片ID"""
    return secrets.token_hex(5).upper()

def get_image_info(file_path: str) -> dict:
    """获取图片的基本信息"""
    info = {}
    
    try:
        # 获取文件大小
        info['file_size'] = os.path.getsize(file_path)
        
        # 获取MIME类型
        mime_type, _ = mimetypes.guess_type(file_path)
        info['mime_type'] = mime_type
        
        # 使用PIL获取图片尺寸
        with Image.open(file_path) as img:
            info['width'], info['height'] = img.size
            info['format'] = img.format.lower()
            
    except Exception as e:
        log_error(f"获取图片信息失败: {e}")
        
    return info

def calculate_file_hash(file_path: str, algorithm: str = 'md5') -> str:
    """计算文件哈希值"""
    hash_obj = hashlib.new(algorithm)
    
    try:
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_obj.update(chunk)
        return hash_obj.hexdigest()
    except Exception as e:
        log_error(f"计算文件哈希失败: {e}")
        return ""

def ensure_directories():
    """确保所有必要的目录存在"""
    directories = [
        settings.DATA_PATH,
        settings.RESOURCE_PATH,
        settings.STORE_PATH,
        settings.TEMP_PATH,
        settings.PENDING_PATH,
        os.path.join(settings.BASE_DIR, "static", "images")
    ]
    
    for directory in directories:
        os.makedirs(directory, exist_ok=True)
        log_info(f"目录已创建/确认: {directory}")

def validate_image_file(file_path: str) -> Tuple[bool, Optional[str]]:
    """验证图片文件是否有效"""
    if not os.path.exists(file_path):
        return False, "文件不存在"
    
    # 检查文件扩展名
    allowed_extensions = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp'}
    _, ext = os.path.splitext(file_path.lower())
    
    if ext not in allowed_extensions:
        return False, f"不支持的文件格式: {ext}"
    
    # 尝试使用PIL打开图片
    try:
        with Image.open(file_path) as img:
            img.verify()  # 验证图片完整性
        return True, None
    except Exception as e:
        return False, f"图片文件损坏: {str(e)}"

def format_file_size(size_bytes: int) -> str:
    """格式化文件大小显示"""
    if size_bytes == 0:
        return "0 B"
    
    size_names = ["B", "KB", "MB", "GB"]
    i = 0
    size = float(size_bytes)
    
    while size >= 1024.0 and i < len(size_names) - 1:
        size /= 1024.0
        i += 1
    
    return f"{size:.2f} {size_names[i]}"

def clean_filename(filename: str) -> str:
    """清理文件名，移除非法字符"""
    import re
    # 移除或替换非法字符
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    # 移除多余的空格
    filename = re.sub(r'\s+', ' ', filename).strip()
    return filename

def get_unique_filename(directory: str, base_name: str, extension: str) -> str:
    """生成唯一的文件名"""
    counter = 1
    original_name = f"{base_name}{extension}"
    file_path = os.path.join(directory, original_name)
    
    while os.path.exists(file_path):
        new_name = f"{base_name}_{counter}{extension}"
        file_path = os.path.join(directory, new_name)
        counter += 1
    
    return os.path.basename(file_path)

class ImageProcessor:
    """图片处理工具类"""
    
    @staticmethod
    def resize_image(input_path: str, output_path: str, max_size: Tuple[int, int] = (1920, 1920), quality: int = 85):
        """调整图片大小并保持比例"""
        try:
            with Image.open(input_path) as img:
                # 转换为RGB模式（如果是RGBA或其他模式）
                if img.mode in ('RGBA', 'LA', 'P'):
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                    img = background
                
                # 调整大小
                img.thumbnail(max_size, Image.Resampling.LANCZOS)
                
                # 保存
                img.save(output_path, 'JPEG', quality=quality, optimize=True)
                
        except Exception as e:
            raise Exception(f"图片处理失败: {str(e)}")
    
    @staticmethod
    def create_thumbnail(input_path: str, output_path: str, size: Tuple[int, int] = (200, 200)):
        """创建缩略图"""
        try:
            with Image.open(input_path) as img:
                img.thumbnail(size, Image.Resampling.LANCZOS)
                img.save(output_path, 'JPEG', quality=80, optimize=True)
        except Exception as e:
            raise Exception(f"创建缩略图失败: {str(e)}")