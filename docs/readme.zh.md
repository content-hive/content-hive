# Content Hive

自托管的插件化内容解析与媒体下载服务，支持多个社交平台。

## 项目简介

Content Hive 是一个自托管服务，用于从社交媒体平台解析内容并下载相关媒体文件。它采用插件化架构——每个受支持的平台是一个独立插件，可以在不重启应用的情况下安装、更新、启用或禁用。

---

## 功能特性

### 插件化架构
每个平台（Twitter、YouTube、TikTok、小红书等）都是独立插件。插件通过 GitHub 仓库统一分发，支持通过 API 进行安装、更新和热重载，无需重启服务。

### 任务去重机制
当多个用户同时提交同一 URL 时，Content Hive 通过共享执行机制避免重复工作：
- **PRIMARY**（主任务）— 第一个提交，负责实际解析和下载
- **LINKED**（关联任务）— PRIMARY 运行期间提交的相同 URL，等待 PRIMARY 完成后共享结果

任务模型中也保留了 **REUSED**（复用任务）类型用于缓存复用场景，但在线去重主路径目前以 PRIMARY/LINKED 为主。

这套机制确保同一 URL 无论被多少用户提交，实际网络请求和解析工作只执行一次。

### 异步任务队列
任务基于优先级队列并发执行，同优先级按 FIFO 顺序处理，最大并发数可通过配置调整。未开始执行的任务支持取消。

### 媒体文件管理
解析结果可包含多个媒体项（图片、视频等）。Content Hive 自动下载每一个媒体文件，按结构化路径存储：
```
/config/data/media/{平台}/{作者}/{内容ID}/{序号}.{扩展名}
```
MIME 类型自动检测，视频封面图自动提取。

### 多用户支持
每个用户的内容、任务历史、平台和作者订阅均独立隔离。认证采用短期 access token + 长期 refresh token 双令牌机制。

### 插件管理
管理员可通过 REST API 列出、安装、更新、启用/禁用、配置和删除插件。版本检查是轻量操作——只拉取远端 manifest 文件（几 KB），不下载完整包。

---

## 快速开始

**前置条件：** Docker

每次打 tag 发布时，镜像会同步推送到 GitHub Container Registry 和 Docker Hub。

```yaml
services:
  content-hive:
    image: ghcr.io/content-hive/content-hive:latest
    container_name: content-hive
    ports:
      - "6123:6123"
    volumes:
      - ./data:/config
    environment:
      - TZ=Asia/Shanghai
      - ADMIN_PASSWORD=YourPassword123!
    restart: unless-stopped
```

保存为 `docker-compose.yml`，然后运行：

```bash
docker compose up -d
```

首次启动时，系统自动创建管理员账号：
- 用户名：`admin`
- 密码：`ADMIN_PASSWORD` 的值；若未设置，则随机生成并写入 `/config/data/.admin_credentials`（权限 600），日志中会记录该文件路径。记录密码后请删除此文件。

访问交互式 API 文档：`http://localhost:6123/docs`

---

## 配置项

所有配置通过环境变量设置。

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `HOST` | `0.0.0.0` | 服务器绑定地址 |
| `PORT` | `6123` | 服务器端口 |
| `TZ` | `Asia/Shanghai` | 容器时区 |
| `ENVIRONMENT` | `production` | 运行环境（`production` / `development`）|
| `DEBUG` | `false` | 开启调试日志 |
| `ADMIN_PASSWORD` | *(自动生成)* | 首次启动时创建管理员账号的密码。要求：≥8 位，包含大小写字母、数字和特殊字符 |
| `DATA_DIR` | `/config/data` | 数据库和媒体文件目录 |
| `LOGS_DIR` | `/config/logs` | 日志文件目录 |
| `PLUGINS_DIR` | `/config/plugins` | 插件安装目录 |
| `PLUGINS_DEPS_DIR` | `/app/deps` | 插件依赖安装目录 |
| `PLUGINS_REPO_URL` | `https://github.com/content-hive/plugins.git` | 插件分发仓库地址 |
| `PLUGINS_REPO_REF_TYPE` | `branch` | 仓库 ref 类型：`branch`、`tag` 或 `commit` |
| `PLUGINS_REPO_REF` | `main` | 仓库 ref 值 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `60` | Access token 有效期（分钟）|
| `REFRESH_TOKEN_EXPIRE_DAYS` | `30` | Refresh token 有效期（天）|
| `DOWNLOAD_MAX_RETRIES` | `3` | 媒体下载失败最大重试次数 |
| `DOWNLOAD_USER_AGENT` | 内置浏览器 UA 字符串 | 媒体下载请求使用的 HTTP User-Agent |

### 持久化数据

`/config` 卷包含所有持久化数据：

```
/config/
  data/
    contenthive.db      # SQLite 数据库
    media/              # 已下载的媒体文件
  logs/                 # 滚动日志文件
  plugins/              # 已安装的插件目录
    plugins.yaml        # 插件启用状态和配置
```

---

## API 文档

交互式 API 文档（Swagger UI）访问地址：`http://localhost:6123/docs`

| 路由前缀 | 说明 |
|----------|------|
| `/v1/task` | 提交 URL 解析任务、查询任务状态、取消任务 |
| `/v1/content` | 查询已解析的内容，列出平台和作者 |
| `/v1/plugins` | 插件管理：安装、更新、配置、启用/禁用 |
| `/v1/user` | 用户登录、令牌刷新、个人资料、修改密码 |
| `/v1/admin` | 管理员专属：用户管理 |
| `/v1/system` | 健康检查、存储状态、日志查看、应用重启 |

说明：`/v1/user/token` 是 OAuth2 兼容端点，直接返回 `{ "access_token": "...", "token_type": "bearer" }`，不使用统一 `APIResponse` 包装。

---

## 插件系统

插件用于添加对新平台的支持。每个插件是一个标准化接口的 Python 包。

详细的插件参考文档请参阅：[docs/plugins.zh.md](plugins.zh.md)

---

## 技术栈

| 组件 | 库 |
|------|----|
| Web 框架 | FastAPI 0.128 |
| ORM | SQLAlchemy 2.0 |
| 数据库 | SQLite（同步 SQLAlchemy 引擎）|
| 数据库迁移 | Alembic |
| 数据校验 | Pydantic / pydantic-settings |
| 认证 | python-jose（JWT）+ pwdlib（Argon2）|
| HTTP 客户端 | aiohttp |
| 包管理 | uv |
| 运行时 | Python 3.13 |

---

## 开源协议

MIT
