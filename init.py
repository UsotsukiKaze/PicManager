#!/usr/bin/env python3
"""
PicManager 初始化脚本
用于初始化项目环境和创建示例数据
"""

import os
import sys
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from app.database import init_database, get_db_context
from app.config import settings
from app.logger import log_info, log_success, log_error
from app.services import GroupService, CharacterService
from app.schemas import GroupCreate, CharacterCreate
from app.utils import ensure_directories

def create_sample_data():
    """创建示例数据"""
    log_info("正在创建示例数据...")
    
    try:
        with get_db_context() as db:
            # 创建示例分组
            sample_groups = [
                {"name": "原神", "description": "miHoYo开发的开放世界冒险游戏"},
                {"name": "明日方舟", "description": "鹰角网络开发的塔防游戏"},
                {"name": "碧蓝航线", "description": "舰船拟人化游戏"},
                {"name": "其他", "description": "其他来源的图片"}
            ]
            
            group_ids = {}
            for group_data in sample_groups:
                try:
                    group = GroupService.create_group(db, GroupCreate(**group_data))
                    group_ids[group.name] = group.id
                    log_success(f"创建分组: {group.name}")
                except Exception as e:
                    log_error(f"创建分组失败 {group_data['name']}: {e}")
            
            # 创建示例角色
            sample_characters = [
                # 原神角色
                {"name": "甘雨", "group_name": "原神", "description": "璃月七星秘书"},
                {"name": "胡桃", "group_name": "原神", "description": "往生堂堂主"},
                {"name": "雷电将军", "group_name": "原神", "description": "稻妻雷神"},
                {"name": "钟离", "group_name": "原神", "description": "璃月岩王帝君"},
                
                # 明日方舟角色
                {"name": "阿米娅", "group_name": "明日方舟", "description": "罗德岛公开领导人"},
                {"name": "陈", "group_name": "明日方舟", "description": "龙门近卫局高级督察"},
                {"name": "银灰", "group_name": "明日方舟", "description": "喀兰贸易CEO"},
                
                # 碧蓝航线角色
                {"name": "企业", "group_name": "碧蓝航线", "description": "白鹰阵营航空母舰"},
                {"name": "俾斯麦", "group_name": "碧蓝航线", "description": "铁血阵营战列舰"},
                {"name": "赤城", "group_name": "碧蓝航线", "description": "重樱阵营航空母舰"},
            ]
            
            for char_data in sample_characters:
                try:
                    group_name = char_data.pop("group_name")
                    if group_name in group_ids:
                        char_data["group_id"] = group_ids[group_name]
                        character = CharacterService.create_character(db, CharacterCreate(**char_data))
                        log_success(f"创建角色: {character.name} ({group_name})")
                except Exception as e:
                    log_error(f"创建角色失败 {char_data.get('name', '未知')}: {e}")
                    
        log_success("示例数据创建完成!")
        
    except Exception as e:
        log_error(f"创建示例数据时发生错误: {e}")

def create_placeholder_image():
    """创建占位符图片"""
    try:
        from PIL import Image, ImageDraw, ImageFont
        
        placeholder_path = os.path.join(settings.BASE_DIR, "static", "images", "placeholder.png")
        os.makedirs(os.path.dirname(placeholder_path), exist_ok=True)
        
        # 创建200x200的占位符图片
        img = Image.new('RGB', (200, 200), color=(240, 240, 240))
        draw = ImageDraw.Draw(img)
        
        # 绘制边框
        draw.rectangle([0, 0, 199, 199], outline=(200, 200, 200))
        
        # 添加文字
        try:
            # 尝试使用默认字体
            font = ImageFont.load_default()
        except:
            font = None
        
        text = "No Image"
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        x = (200 - text_width) // 2
        y = (200 - text_height) // 2
        
        draw.text((x, y), text, fill=(150, 150, 150), font=font)
        
        img.save(placeholder_path, 'PNG')
        log_success(f"占位符图片已创建: {placeholder_path}")
        
    except Exception as e:
        log_error(f"创建占位符图片失败: {e}")

def main():
    """主初始化函数"""
    log_info(" PicManager 项目初始化")
    log_info("=" * 50)
    
    # 1. 确保目录存在
    log_info("1. 检查目录结构...")
    ensure_directories()
    
    # 2. 初始化数据库
    log_info("\n2. 初始化数据库...")
    init_database()
    
    # 3. 创建示例数据
    log_info("\n3. 创建示例数据...")
    create_sample_data()
    
    # 4. 创建占位符图片
    log_info("\n4. 创建占位符图片...")
    create_placeholder_image()
    
    log_info("\n" + "=" * 50)
    log_success("🎉 初始化完成!")
    log_info("\n接下来你可以:")
    log_info("1. 运行 'uv run main.py' 启动服务器")
    log_info(f"2. 在浏览器中访问 http://{settings.HOST}:{settings.PORT}")
    log_info("3. 开始管理你的图片!")

if __name__ == "__main__":
    main()