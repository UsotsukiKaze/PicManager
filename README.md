<div align="center">
  <img src="./docs/images/logo.png" width="180" alt="PicManager Logo">

# PicManager

一个用于保存、整理和检索喜欢的图片，并为 [Ubot](https://github.com/UsotsukiKaze/Ubot) 提供图库能力的图片管理系统。

[在线站点](https://pic.usotsuki-kaze.com/) · [Ubot](https://github.com/UsotsukiKaze/Ubot) · [快速开始](#快速开始)

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-6A5ACD)

</div>

## 简介

PicManager 的初衷很简单：把自己喜欢的图片好好保存下来，需要时可以按作品、角色或其他信息快速找到，并让 Ubot 能够方便地调用这些图片。

随着图片数量增加，只依靠文件夹和文件名会越来越难整理。PicManager 为每张图片生成独立编号，并使用分组、角色、特征标签、PID 和年龄分级记录图片信息。网页端负责浏览、搜索、上传和维护，Ubot 则通过专用 API 完成角色抽图、图片上传、安全登录等操作。

项目默认使用本地文件系统和 SQLite，部署简单；图片较多时也可以接入 Cloudflare R2 存储。

## 功能

### Pixiv-ol

- Root 绑定 Pixiv 账号，管理员查看推荐与关注作者的新投稿
- 结合 App 推荐、分组/角色绑定标签搜索、图库特征与喜欢作品的标签偏好，按库存优先补充图片偏少的分组
- 推荐与关注更新连续滚动加载，加入优选夹后缓存原图，确认标签后批量入库
- 多 P 作品支持分 P 独立标签或合并标签，图库 PID 统一为 `作品ID_pN`
- Pixiv 账号与推荐偏好位于设置；标签关联在优选夹和分组、角色、特征管理中完成
- 本机通过 pixiv-cli 与默认浏览器登录，保留手动回调兼容入口
- 支持按 PID 查找，以及无 PID 库图的轻量高相似提示
- 配置与首版限制见 [Pixiv-ol 使用说明](docs/pixiv-ol-usage.md)

### 图片管理

- 网格浏览图库，查看图片详情和原图
- 按分组、角色、特征标签、PID、图片编号搜索
- 支持分组和角色别名、昵称及拼音搜索
- 使用全年龄、R12、R16、R18 标记和筛选内容
- 编辑图片信息、下载图片或随机抽取图片
- 自动生成缩略图和详情预览图，减少直接加载原图

### 分组、角色与标签

- 使用分组管理作品、系列或其他图片分类
- 角色归属于对应分组，一张图片可以关联多个角色
- 使用特征标签补充服装、场景等图片信息
- 分组和角色支持头像、别名与昵称
- 表情包使用独立的情绪标签体系

### 图片上传

- 单张上传：预览图片并填写标签、PID、分级和备注
- 批量上传：一次选择多张图片，再逐张补充信息
- Temp 导入：从 `resource/temp` 读取待整理图片
- 上传队列：查看上传进度、成功和失败状态
- R2 直传：使用预签名地址上传图片，减少服务器中转

上传和图库维护都带有感知哈希查重。发现相似图片时，可以保留已有图片、采用新图片、合并元数据、标记为不同图片，或暂时跳过。

### 表情包库

- 表情包与普通图片分别保存和展示
- 支持 GIF、JPG、PNG、WebP、BMP
- 每个表情包可选一个基础情绪和一个以 `#` 开头的功能标签，两类均可单独使用
- 例如 `#睡觉` 表示纯睡觉功能，`love` + `#摸头` 表示带 love 情绪的摸头表情
- 按分组、角色、基础情绪和功能标签筛选，支持情绪与功能组合查询
- 支持上传、预览、编辑、下载和随机获取

### 用户与审核

- 支持 QQ Ticket 登录和游客模式
- 区分普通用户、管理员与 Root
- 普通用户可以上传和维护图库内容
- 需要审核的修改会进入管理员审核列表
- 个人中心可以查看提交记录、通知和贡献统计
- 首页与榜单展示贡献、热门角色和热门图片

### Ubot 联动

PicManager 是 [Ubot](https://github.com/UsotsukiKaze/Ubot) 的图库服务。Ubot 中的 `ubot-plugin-uso-pic` 会调用 PicManager 完成：

- 从 QQ 侧安全登录 PicManager
- 上传图片并补充角色等信息
- 按分组、角色、特征或年龄分级随机抽图
- 获取随机表情包
- 为图片玩法提供角色和标签数据
- 使用短时签名地址发送受保护的原图

PicManager 也提供群聊年龄分级与授权接口，避免机器人在不合适的场景中返回受限内容。

### 维护工具

- 本地校验统一检查文件、补缩略图、归档缺失记录、整理孤立文件和处理重复图片
- Pixiv 校验补齐投稿页、画师、原始标签与高清信息，旧多 P 作品由用户选择对应页
- 图片只保留本地与 Pixiv 两项校验状态；无 PID 图片生成轻量相似指纹
- 创建 SQLite 数据库快照
- 检查存储吞吐和服务器网络信息

## 快速开始

### 环境要求

- Python 3.10+
- [uv](https://docs.astral.sh/uv/)

### 获取项目

```bash
git clone https://github.com/UsotsukiKaze/PicManager.git
cd PicManager
uv sync
```

### 初始化并启动

```bash
uv run pic init
uv run pic run
```

启动后访问：

- Web 界面：<http://localhost:8000>
- 健康检查：<http://localhost:8000/health>

开发时可以开启热重载：

```bash
uv run pic run --reload
```

或直接运行 Uvicorn：

```bash
uv run uvicorn main:app --reload --no-access-log
```

## 配置

项目会从根目录下的 `.env` 读取配置。常用配置如下：

```dotenv
HOST=0.0.0.0
PORT=8000
DEBUG=false

ROOT_QQ=你的QQ号
SECRET_KEY=至少32位的随机字符串

CORS_ALLOW_ORIGINS=http://127.0.0.1:8000,http://localhost:8000
TRUSTED_HOSTS=localhost,127.0.0.1

BOT_API_TOKEN=Ubot访问PicManager时使用的Token
PUBLIC_BASE_URL=https://your-picmanager.example.com
```

未设置 `SECRET_KEY` 时，PicManager 会在 `data/.secret_key` 自动生成并保存随机密钥。生产环境仍建议显式配置，并妥善备份 `data/` 目录。

### Cloudflare R2

默认存储方式为本地文件系统。如需使用 R2，需要安装 `boto3` 并配置：

```bash
uv add "boto3>=1.35"
```

```dotenv
STORAGE_BACKEND=r2
R2_ACCOUNT_ID=your-account-id
R2_BUCKET=your-bucket
R2_ACCESS_KEY_ID=your-access-key
R2_SECRET_ACCESS_KEY=your-secret-key
R2_PREFIX=images
```

## 命令行工具

```bash
uv run pic run                 # 启动 Web 服务
uv run pic run --reload        # 开启热重载
uv run pic init                # 初始化目录与数据库
uv run pic status              # 查看系统计数和路径
uv run pic audit               # 检查文件、记录和缩略图状态
uv run pic audit --sync        # 检查并写回图片文件状态
uv run pic cleanup             # 归档缺失原图的记录
uv run pic cleanup --mode delete
uv run pic thumbs --limit 500  # 补生成缩略图
uv run pic thumbs --force      # 强制重建缩略图
uv run pic scan-temp           # 将未入库图片移回 Temp
uv run pic snapshot            # 创建数据库快照
uv run pic diagnose            # 检查存储吞吐和网络信息
```

## API

设置 `ENABLE_API_DOCS=true` 后可以访问：

- Swagger UI：`/docs`
- ReDoc：`/redoc`
- OpenAPI：`/openapi.json`

常用接口：

- `GET /api/images/search`：搜索图片
- `GET /api/images/random`：随机图片
- `POST /api/upload/single`：上传图片
- `GET /api/groups/`：获取分组
- `GET /api/characters/`：获取角色
- `GET /api/emojis/random`：随机表情包
- `GET /api/rankings`：获取排行榜
- `GET /api/system/status`：获取系统状态

Ubot 使用的接口位于 `/api/bot/*`，通过 `BOT_API_TOKEN` 的 Bearer 认证保护。Token 只应保存在 PicManager 和 Ubot 的服务端配置中。

表情包的基础情绪和功能标签共用 `/api/emotion-tags/`（机器人端为 `/api/bot/emotion-tags`）。
名称以 `#` 开头的标签返回 `tag_type: "function"`，其他标签返回 `tag_type: "emotion"`；类型由名称决定，别称不改变类型。
上传和编辑继续通过 `emotion_ids` 传入标签 ID，可为空、只包含一类，或包含一个基础情绪和一个功能标签。
重复选择同类的不同标签会返回 400；已有标签改名时，如果变更类型会使表情包的同类标签超限，也会拒绝修改。

`GET /api/emojis/search`、`GET /api/emojis/random` 和 `GET /api/bot/emojis/random` 支持 `function_id`：

- `?function_id=12`：按功能获取，例如 ID 12 是 `#睡觉`，可匹配该功能下所有情绪的表情包，包括仅有功能标签的表情包。
- `?emotion_id=3&function_id=15`：同时匹配基础情绪和功能，例如 `love` + `#摸头`。
- 原有 `emotion_id` 仍支持任意情绪标签 ID（包括 `#` 功能标签），兼容现有调用；专用 `function_id` 只匹配功能标签。

返回的 `emotions` 数组包含两类标签，基础情绪排在功能标签之前。现有表和关联可直接复用，无需迁移历史数据。

## 项目结构

```text
PicManager/
├── app/
│   ├── routers/            # Web API、认证、管理与 Ubot 集成
│   ├── security/           # 会话、权限、签名与 Ticket
│   ├── storage/            # 本地文件系统与 R2 存储
│   ├── cli.py              # 命令行入口
│   ├── database.py         # 数据库、迁移与快照
│   ├── models.py           # 数据模型
│   ├── schemas.py          # API 数据结构
│   └── services.py         # 核心业务逻辑
├── static/                 # Web 页面、样式和脚本
├── resource/
│   ├── store/              # 本地图片
│   ├── temp/               # 待整理图片
│   ├── pending/            # 待审核文件
│   ├── thumbs/             # 缩略图
│   ├── previews/           # 预览图
│   ├── emojis/             # 表情包
│   └── avatars/            # 分组与角色头像
├── data/                   # SQLite 数据库和快照
├── tests/                  # 测试
├── main.py                 # FastAPI 应用入口
└── pyproject.toml
```

## 开发

前端采用 Vue 3 + TypeScript + Vite，入口、导航、首页和图库已使用响应式组件；上传、Pixiv 等业务模块按需接入兼容容器。架构边界、构建和部署说明见 [响应式前端架构](docs/frontend-architecture.md)。仓库包含 `static/app` 产物，生产运行无需安装 Node。

```bash
cd frontend
npm ci
npm run dev
npm test
npm run build
```

```bash
uv sync --extra dev --extra browser
uv run pytest
node --test tests/js/*.test.cjs
```

Python 测试覆盖接口、权限、数据库与入库流程；`tests/js` 中的 Node 烟测覆盖拼音搜索、模块加载、上传队列和表情标签交互，无需真实账号。

Python 的 `browser` 可选依赖仅供旧版 Pixiv `automatic` 登录和对应测试使用。普通部署运行 `uv sync` 即可；默认浏览器、pixiv-cli 和手动授权均不需要 Python Playwright。前端端到端测试使用 `frontend` 内的 Node Playwright。

当前发布版本：**1.0.0**。使用说明见 [Pixiv-ol](docs/pixiv-ol-usage.md)、[图库校验与标签关联](docs/library-validation-and-mappings.md)、[相似提示与 PID 查找](docs/pixiv-visual-similarity.md)。后续事项见 [重构清单](docs/refactoring-roadmap.md)。

主要技术栈：

- FastAPI / SQLAlchemy / Pydantic
- SQLite / Pillow
- Vue 3 / TypeScript / Vite / Pinia / TanStack Vue Query
- 兼容业务模块使用原生 JavaScript / CSS，按需加载
- uv

## 注意事项

1. 图片使用独立的十六进制编号保存和查询。
2. 删除、清理和重复图片合并可能影响图片文件，请先确认数据库快照和文件备份可用。
3. `data/`、`resource/`、`.env`、Cookie 与 Token 不应提交到公开仓库。
4. 开放到公网时，请正确配置 HTTPS、`TRUSTED_HOSTS`、CORS 和安全 Cookie。

## 贡献

欢迎提交 Issue 与 Pull Request。

## License

MIT
