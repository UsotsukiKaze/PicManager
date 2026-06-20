from __future__ import annotations

from http import HTTPStatus
from time import perf_counter
from typing import Any, Awaitable, Callable
import sys

LogHook = Callable[[str, str], None]
CallNext = Callable[[Any], Awaitable[Any]]

_COLOR_RESET = "\033[0m"
_COLOR_INFO = "\033[94m"
_COLOR_SUCCESS = "\033[92m"
_COLOR_ERROR = "\033[91m"


def _default_log_hook(level: str, message: str) -> None:
    color = _COLOR_INFO
    if level == "SUCCESS":
        color = _COLOR_SUCCESS
    elif level == "ERROR":
        color = _COLOR_ERROR

    formatted = f"[{level}] {message}"
    sys.stdout.write(f"{color}{formatted}{_COLOR_RESET}\n")


_log_hook: LogHook = _default_log_hook


def set_log_hook(hook: LogHook) -> None:
    """设置日志hook，方便外部替换输出方式。"""
    global _log_hook
    _log_hook = hook


def _log(level: str, message: str) -> None:
    _log_hook(level, message)


def log_info(message: str) -> None:
    _log("INFO", message)


def log_success(message: str) -> None:
    _log("SUCCESS", message)


def log_error(message: str) -> None:
    _log("ERROR", message)


def _path_value(path: str, prefix: str) -> str:
    value = path.removeprefix(prefix).strip("/")
    return value or "unknown"


def _request_actor(request: Any) -> str:
    path = request.url.path
    if path.startswith("/api/bot"):
        return "[bot]"

    session_id = request.cookies.get("session_id")
    if not session_id:
        return "[anonymous]"

    # Local imports avoid a logger -> database -> logger circular import at app startup.
    try:
        from .database import SessionLocal
        from .models import User, UserSession
    except Exception:
        return "[unknown]"

    db = SessionLocal()
    try:
        session = db.query(UserSession).filter(UserSession.session_id == session_id).first()
        if not session:
            return "[anonymous]"
        if session.is_guest == "true":
            return f"[guest:{session.guest_ip or 'unknown'}]"

        user = db.query(User).filter(User.id == session.user_id).first()
        if not user:
            return "[anonymous]"
        return f"[{user.qq_number}]"
    except Exception:
        return "[unknown]"
    finally:
        db.close()


def _log_domain(path: str) -> str:
    if path == "/login" or path.startswith("/auth"):
        return "PicLogin"
    if path.startswith("/api/bot"):
        return "PicBot"
    if path.startswith("/api/admin") or path.startswith("/admin"):
        return "PicAdmin"
    return "PicManager"


def _status_text(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return "Unknown Error"


def _describe_operation(method: str, path: str) -> str:
    if path == "/":
        return "打开主页面"
    if path == "/login":
        return "打开登录页"
    if path == "/profile":
        return "打开个人中心"
    if path == "/health":
        return "检查服务健康状态"
    if path == "/favicon.ico":
        return "加载站点图标"

    if path.startswith("/static/"):
        return f"加载静态资源 {_path_value(path, '/static/')}"
    if path.startswith("/resource/thumbs/"):
        return f"加载缩略图 {_path_value(path, '/resource/thumbs/')}"
    if path.startswith("/resource/store/"):
        return f"查看原图 {_path_value(path, '/resource/store/')}"
    if path.startswith("/resource/temp/"):
        return f"访问临时图片 {_path_value(path, '/resource/temp/')}"
    if path.startswith("/resource/pending/"):
        return f"访问待审核图片 {_path_value(path, '/resource/pending/')}"

    auth_actions = {
        ("POST", "/auth/login"): "尝试旧登录入口",
        ("POST", "/auth/qq-ticket"): "使用 QQ ticket 登录",
        ("POST", "/auth/guest"): "以游客身份登录",
        ("GET", "/auth/me"): "检查当前登录状态",
        ("POST", "/auth/logout"): "退出登录",
        ("PUT", "/auth/password"): "尝试修改密码",
        ("GET", "/auth/check-admin"): "检查旧管理员登录状态",
        ("GET", "/auth/guest-limit"): "查询游客操作额度",
        ("GET", "/auth/my-requests"): "查看自己的审核请求",
        ("GET", "/auth/notifications"): "查看通知",
        ("GET", "/auth/profile-stats"): "查看个人统计",
        ("POST", "/auth/set-nickname"): "更新昵称",
    }
    if (method, path) in auth_actions:
        return auth_actions[(method, path)]
    if method == "DELETE" and path.startswith("/auth/pending/"):
        return f"撤销审核请求 {_path_value(path, '/auth/pending/')}"

    bot_actions = {
        ("GET", "/api/bot/groups"): "机器人读取分组列表",
        ("GET", "/api/bot/characters"): "机器人读取角色列表",
        ("GET", "/api/bot/resolve"): "机器人解析图片条件",
        ("GET", "/api/bot/random"): "机器人随机抽取图片",
        ("POST", "/api/bot/tickets"): "机器人签发 QQ ticket",
    }
    if (method, path) in bot_actions:
        return bot_actions[(method, path)]

    admin_actions = {
        ("GET", "/api/admin/stats"): "查看管理统计",
        ("GET", "/api/admin/pending"): "查看待审核列表",
        ("GET", "/api/admin/admins"): "查看管理员列表",
        ("POST", "/api/admin/admins"): "添加管理员",
        ("POST", "/api/system/cleanup"): "清理孤儿数据",
        ("POST", "/api/system/scan-store-orphans"): "扫描未入库图片",
        ("GET", "/api/system/status"): "查看系统状态",
    }
    if (method, path) in admin_actions:
        return admin_actions[(method, path)]
    if method == "POST" and path.startswith("/api/admin/pending/"):
        return f"处理审核请求 {_path_value(path, '/api/admin/pending/')}"
    if method == "DELETE" and path.startswith("/api/admin/admins/"):
        return f"移除管理员 {_path_value(path, '/api/admin/admins/')}"

    if path == "/api/images/search":
        return "查询图片列表"
    if path == "/api/images/random":
        return "随机抽取图片"
    if path.startswith("/api/images/"):
        image_id = _path_value(path, "/api/images/")
        return {
            "GET": f"查看图片 {image_id}",
            "PUT": f"更新图片 {image_id}",
            "DELETE": f"删除图片 {image_id}",
        }.get(method, f"操作图片 {image_id}")

    if path in ("/api/groups", "/api/groups/"):
        return {"GET": "查看分组列表", "POST": "创建分组"}.get(method, "操作分组")
    if path.startswith("/api/groups/"):
        group_id = _path_value(path, "/api/groups/")
        return {
            "GET": f"查看分组 {group_id}",
            "PUT": f"更新分组 {group_id}",
            "DELETE": f"删除分组 {group_id}",
        }.get(method, f"操作分组 {group_id}")

    if path in ("/api/characters", "/api/characters/"):
        return {"GET": "查看角色列表", "POST": "创建角色"}.get(method, "操作角色")
    if path.startswith("/api/characters/"):
        character_id = _path_value(path, "/api/characters/")
        return {
            "GET": f"查看角色 {character_id}",
            "PUT": f"更新角色 {character_id}",
            "DELETE": f"删除角色 {character_id}",
        }.get(method, f"操作角色 {character_id}")

    upload_actions = {
        ("POST", "/api/upload/single"): "上传单张图片",
        ("GET", "/api/upload/temp-count"): "查看临时图片数量",
        ("GET", "/api/upload/temp-images"): "查看临时图片列表",
        ("POST", "/api/upload/temp"): "导入临时图片",
    }
    if (method, path) in upload_actions:
        return upload_actions[(method, path)]
    if method == "DELETE" and path.startswith("/api/upload/temp/"):
        return f"删除临时图片 {_path_value(path, '/api/upload/temp/')}"

    if path == "/api/rankings":
        return "查看排行榜"

    return f"访问 {path}"


def _should_skip_success_log(path: str) -> bool:
    return (
        path.startswith("/static/")
        or path.startswith("/resource/thumbs/")
        or path == "/favicon.ico"
    )


async def log_http_request(request: Any, call_next: CallNext) -> Any:
    start = perf_counter()
    path = request.url.path
    method = request.method
    actor = _request_actor(request)
    domain = _log_domain(path)
    action = _describe_operation(method, path)

    try:
        response = await call_next(request)
        duration_ms = (perf_counter() - start) * 1000
        if response.status_code >= 400:
            log_error(
                f"{response.status_code} {domain} {actor} {action}失败："
                f"{_status_text(response.status_code)}，用时 {duration_ms:.0f}ms"
            )
        elif not _should_skip_success_log(path):
            message = f"{domain} {actor} {action}，用时 {duration_ms:.0f}ms"
            if method in {"GET", "HEAD", "OPTIONS"}:
                log_info(message)
            else:
                log_success(message)
        return response
    except Exception as exc:
        duration_ms = (perf_counter() - start) * 1000
        log_error(f"500 {domain} {actor} {action}异常：{exc}，用时 {duration_ms:.0f}ms")
        raise
