# PicManager

一个面向「分组/角色」标签体系的图片元数据管理系统，提供上传、检索、批量处理与可视化管理。

## 特性

- 分组/角色层级标签管理
- 多条件检索（分组、角色、PID）
- 单张、批量、temp 目录导入
- 自动生成 10 位十六进制图片 ID
- SQLite 持久化与可备份数据目录

## 环境要求

- Python 3.10+
- uv

## 快速开始

1) 初始化

```bash
uv run init.py
```

2) 启动

```bash
uv run main.py
```

3) 访问

- Web 界面: http://localhost:8000
- API 文档: http://localhost:8000/docs

## 使用概览

### 图片管理

- 浏览：图片管理页查看全部图片
- 搜索：按分组/角色/PID 过滤
- 详情：点击图片查看完整元信息
- 编辑/删除：支持修改或删除（会同步文件）

### 分组与角色

- 分组：用于承载具体作品/IP
- 角色：隶属于分组，禁止跨分组

### 上传方式

- 单张上传：选择分组/角色并填写信息
- 批量上传：多图一次提交，逐图设置
- Temp 导入：从 resource/temp 扫描导入

## API

文档位于 `/docs`。常用端点：

- `GET /api/images/search` 搜索图片
- `POST /api/upload/single` 单张上传
- `GET /api/groups/` 获取分组
- `GET /api/characters/` 获取角色
- `GET /api/system/status` 系统状态

## 开发与运行

### 安装依赖

```bash
uv sync
```

### 开发模式

```bash
uv run main.py
```

或：

```bash
uv run uvicorn main:app --reload
```

## 配置

位于 `app/config.py`：

- `STORE_PATH` 图片存储路径
- `TEMP_PATH` 临时图片路径
- `MAX_FILE_SIZE` 最大上传大小
- `ALLOWED_EXTENSIONS` 允许的文件后缀

## 目录结构

```
PicManager/
├── app/                    核心代码
│   ├── models.py           数据库模型
│   ├── schemas.py          Pydantic 模式
│   ├── services.py         业务逻辑
│   ├── database.py         数据库配置
│   ├── config.py           应用配置
│   ├── utils.py            工具函数
│   └── routers/            API 路由
├── static/                 静态资源
├── resource/               资源目录
│   ├── store/              图片存储
│   └── temp/               临时导入
├── data/                   数据库文件
├── main.py                 应用入口
├── init.py                 初始化脚本
└── pyproject.toml          项目配置
```

## 注意事项

1. 图片文件名使用 10 位十六进制 ID
2. 删除图片会同步删除磁盘文件
3. 建议定期备份 data 目录
4. 确保 resource 目录具备读写权限

## 技术栈

- FastAPI / SQLAlchemy / Pydantic
- 原生 JavaScript / CSS3
- SQLite / Pillow
- uv

## License

MIT

## 贡献

欢迎提交 Issue 与 PR