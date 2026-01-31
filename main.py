from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import time
import os
import uvicorn
from app.database import init_database
from app.config import settings
from app.logger import log_info, log_success, log_error
from app.routers.api import router as api_router
from app.routers.auth import router as auth_router
from app.routers.admin import router as admin_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时执行
    log_info("正在初始化数据库...")
    init_database()
    log_success("数据库初始化完成!")
    yield
    # 关闭时执行（如果需要的话）

# 创建FastAPI应用
app = FastAPI(
    title="PicManager",
    description="图片编号管理系统 - 基于标签的图片元数据管理工具",
    version="0.1.0",
    lifespan=lifespan
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    client = request.client.host if request.client else "unknown"
    log_info(f"请求开始 {request.method} {request.url.path} from {client}")

    try:
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000
        if response.status_code >= 400:
            log_error(f"请求结束 {request.method} {request.url.path} {response.status_code} {duration_ms:.2f}ms")
        else:
            log_success(f"请求结束 {request.method} {request.url.path} {response.status_code} {duration_ms:.2f}ms")
        return response
    except Exception as exc:
        duration_ms = (time.perf_counter() - start) * 1000
        log_error(f"请求异常 {request.method} {request.url.path} 500 {duration_ms:.2f}ms: {exc}")
        raise

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 在生产环境中应该设置具体的域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态文件
app.mount("/static", StaticFiles(directory=os.path.join(settings.BASE_DIR, "static")), name="static")

# 确保resource目录存在
os.makedirs(settings.STORE_PATH, exist_ok=True)
os.makedirs(settings.TEMP_PATH, exist_ok=True)
os.makedirs(settings.PENDING_PATH, exist_ok=True)  # 待审核文件目录

# 提供resource目录的静态文件服务
app.mount("/resource", StaticFiles(directory=settings.RESOURCE_PATH), name="resource")

# 注册API路由
app.include_router(api_router, prefix="/api")
app.include_router(auth_router, prefix="/auth")
app.include_router(admin_router, prefix="/admin")

@app.get("/", response_class=HTMLResponse)
async def root():
    """主页路由 - 返回静态HTML文件"""
    return FileResponse(os.path.join(settings.BASE_DIR, "static", "index.html"))

@app.get("/login", response_class=HTMLResponse)
async def login_page():
    """登录页路由"""
    return FileResponse(os.path.join(settings.BASE_DIR, "static", "login.html"))

@app.get("/profile", response_class=HTMLResponse)
async def profile_page():
    """个人中心页路由"""
    return FileResponse(os.path.join(settings.BASE_DIR, "static", "profile.html"))

@app.get("/favicon.ico")
async def favicon():
    """网站图标"""
    return FileResponse(os.path.join(settings.BASE_DIR, "static", "icon", "Pic.ico"))

@app.get("/health")
async def health_check():
    """健康检查接口"""
    return {"status": "healthy", "message": "PicManager is running"}

def main():
    """主函数"""
    log_info("正在启动 PicManager 图片管理系统...")
    log_info(f"工作目录: {settings.BASE_DIR}")
    log_info(f"数据存储: {settings.DATA_PATH}")
    log_info(f"图片存储: {settings.STORE_PATH}")
    log_info(f"临时目录: {settings.TEMP_PATH}")
    log_info(f"Web界面: http://{settings.HOST}:{settings.PORT}")
    log_info(f"API文档: http://{settings.HOST}:{settings.PORT}/docs")
    
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=True,
        reload_dirs=["app", "static"],
        log_level="info"
    )

if __name__ == "__main__":
    main()