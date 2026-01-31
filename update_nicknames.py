#!/usr/bin/env python3
"""
更新所有用户的QQ昵称
"""
import asyncio
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(__file__))

from app.database import get_db_context
from app.logger import log_info, log_success, log_error
from app.models import User
from app.routers.auth import fetch_qq_info


async def update_all_nicknames():
    """更新所有用户的昵称"""
    with get_db_context() as db:
        users = db.query(User).all()
        
        log_info(f"找到 {len(users)} 个用户，开始更新昵称...")
        
        for i, user in enumerate(users, 1):
            log_info(f"[{i}/{len(users)}] 正在更新 {user.qq_number}...")
            
            try:
                qq_info = await fetch_qq_info(user.qq_number)
                
                old_nickname = user.nickname
                user.nickname = qq_info["nickname"]
                user.avatar_url = qq_info["avatar_url"]
                db.commit()
                
                log_success(f"{old_nickname} → {user.nickname}")
            except Exception as e:
                log_error(f"失败: {e}")
        
        log_info("=" * 50)
        log_success("昵称更新完成！")
        log_info("=" * 50)
        
        # 显示更新后的用户列表
        db.expunge_all()
        users = db.query(User).all()
        log_info("更新后的用户列表:")
        for user in users:
            log_info(f"- {user.qq_number}: {user.nickname}")


if __name__ == "__main__":
    asyncio.run(update_all_nicknames())
