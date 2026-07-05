"""Command line entry points for PicManager."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if is_dataclass(value):
        return asdict(value)
    return str(value)


def _print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=_json_default))


def _ensure_runtime_dirs(settings: Any) -> None:
    for path in (
        settings.DATA_PATH,
        settings.RESOURCE_PATH,
        settings.STORE_PATH,
        settings.TEMP_PATH,
        settings.PENDING_PATH,
        settings.THUMB_PATH,
    ):
        Path(path).mkdir(parents=True, exist_ok=True)


def cmd_run(args: argparse.Namespace) -> None:
    import uvicorn
    from .config import settings
    from .logger import log_info

    settings.HOST = args.host or settings.HOST
    settings.PORT = args.port or settings.PORT

    log_info("正在启动 PicManager...")
    log_info(f"工作目录: {settings.BASE_DIR}")
    log_info(f"数据目录: {settings.DATA_PATH}")
    log_info(f"图片目录: {settings.STORE_PATH}")
    log_info(f"Web: http://{settings.HOST}:{settings.PORT}")
    log_info(f"API docs: http://{settings.HOST}:{settings.PORT}/docs")

    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=args.reload,
        reload_dirs=["app", "static"] if args.reload else None,
        log_level=args.log_level,
    )


def cmd_init(_: argparse.Namespace) -> None:
    from .config import settings
    from .database import init_database
    from .logger import log_success

    _ensure_runtime_dirs(settings)
    init_database()
    log_success("PicManager 初始化完成")


def cmd_status(_: argparse.Namespace) -> None:
    from .config import settings
    from .database import get_db_context
    from .services import SystemService

    with get_db_context() as db:
        status = SystemService.get_system_status(db, settings.STORE_PATH, settings.TEMP_PATH)
        _print_json(status.model_dump() if hasattr(status, "model_dump") else status.dict())


def cmd_audit(args: argparse.Namespace) -> None:
    from .config import settings
    from .database import get_db_context
    from .services import ImageService

    with get_db_context() as db:
        _print_json(ImageService.storage_audit(db, settings.STORE_PATH, update_status=args.sync))


def cmd_cleanup(args: argparse.Namespace) -> None:
    from .config import settings
    from .database import get_db_context
    from .services import ImageService

    with get_db_context() as db:
        count = ImageService.cleanup_orphaned_records(db, settings.STORE_PATH, mode=args.mode)
    action = "Deleted" if args.mode == "delete" else "Archived"
    _print_json({"message": f"{action} {count} missing image records", "count": count, "mode": args.mode})


def cmd_thumbs(args: argparse.Namespace) -> None:
    from .database import get_db_context
    from .services import ImageService

    with get_db_context() as db:
        _print_json(ImageService.rebuild_missing_thumbnails(db, limit=args.limit, force=args.force))


def cmd_scan_temp(_: argparse.Namespace) -> None:
    from .config import settings
    from .database import get_db_context
    from .services import ImageService

    with get_db_context() as db:
        moved = ImageService.move_orphaned_files_to_temp(db, settings.STORE_PATH, settings.TEMP_PATH)
    _print_json({"message": f"Moved {moved} orphaned files to temp", "moved": moved})


def cmd_snapshot(_: argparse.Namespace) -> None:
    from .database import create_db_snapshot
    from .logger import log_success

    create_db_snapshot()
    log_success("数据库快照已创建")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pic", description="PicManager command line tools")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="启动 Web 服务")
    run.add_argument("--host", help="覆盖监听地址")
    run.add_argument("--port", type=int, help="覆盖监听端口")
    run.add_argument("--reload", dest="reload", action="store_true", default=True, help="开启热重载")
    run.add_argument("--no-reload", dest="reload", action="store_false", help="关闭热重载")
    run.add_argument("--log-level", default="info", choices=["critical", "error", "warning", "info", "debug", "trace"])
    run.set_defaults(func=cmd_run)

    init = subparsers.add_parser("init", help="初始化目录和数据库")
    init.set_defaults(func=cmd_init)

    status = subparsers.add_parser("status", help="输出系统计数和路径")
    status.set_defaults(func=cmd_status)

    audit = subparsers.add_parser("audit", help="检查缺失文件、孤儿文件和缩略图状态")
    audit.add_argument("--sync", action="store_true", help="将文件状态检查结果写回数据库")
    audit.set_defaults(func=cmd_audit)

    cleanup = subparsers.add_parser("cleanup", help="处理缺失原图的数据库记录")
    cleanup.add_argument("--mode", choices=["archive", "delete"], default="archive")
    cleanup.set_defaults(func=cmd_cleanup)

    thumbs = subparsers.add_parser("thumbs", help="补生成缩略图")
    thumbs.add_argument("--limit", type=int, default=200)
    thumbs.add_argument("--force", action="store_true", help="强制重建已有缩略图")
    thumbs.set_defaults(func=cmd_thumbs)

    scan_temp = subparsers.add_parser("scan-temp", help="把 store 中未入库图片移回 temp")
    scan_temp.set_defaults(func=cmd_scan_temp)

    snapshot = subparsers.add_parser("snapshot", help="创建数据库快照")
    snapshot.set_defaults(func=cmd_snapshot)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
