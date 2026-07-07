# 配置项

部署级配置通过环境变量设置；可在运行时修改的应用设置保存在 `/config/settings.yaml`，也可通过 `GET/PUT /v1/system/settings` API 管理（需管理员权限）。

## 环境变量

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `HOST` | `0.0.0.0` | 服务器绑定地址 |
| `PORT` | `6123` | 服务器端口 |
| `TZ` | `Asia/Shanghai` | 容器时区 |
| `ADMIN_PASSWORD` | *(自动生成)* | 首次启动时创建管理员账号的密码。要求：≥8 位，包含大小写字母、数字和特殊字符 |
| `DATA_DIR` | `/config/data` | 数据库和媒体文件目录 |
| `LOGS_DIR` | `/config/logs` | 日志文件目录 |
| `PLUGINS_DIR` | `/config/plugins` | 插件安装目录 |
| `PLUGINS_DEPS_DIR` | `/app/deps` | 插件依赖安装目录 |

## 运行时配置（settings.yaml）

首次启动时自动在 `/config/settings.yaml` 生成默认配置。

**通过 API 修改**（`PUT /v1/system/settings`）：无需重启容器；修改会立即写入文件并更新内存缓存。部分设置在实际使用时生效（如下次下载、下次签发 token）。

**直接编辑文件**：`GET /v1/system/settings` 每次从磁盘读取，可立即看到文件内容。但服务内部（下载、token、插件源等）使用启动时加载的内存缓存，直接改文件后需**重启容器**才能在这些路径生效。建议优先使用 API 修改。

```yaml
plugins:
  repo_url: https://github.com/content-hive/plugins.git
  repo_ref_type: branch   # branch | tag | commit
  repo_ref: main

auth:
  access_token_expire_minutes: 60
  refresh_token_expire_days: 30

download:
  max_retries: 3
  user_agent: >-
    Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36
    (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36 Edg/143.0.0.0
```

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `plugins.repo_url` | `https://github.com/content-hive/plugins.git` | 插件分发仓库地址。修改前请确认仓库可信度 |
| `plugins.repo_ref_type` | `branch` | 仓库 ref 类型：`branch`、`tag` 或 `commit` |
| `plugins.repo_ref` | `main` | 仓库 ref 值 |
| `auth.access_token_expire_minutes` | `60` | Access token 有效期（分钟）|
| `auth.refresh_token_expire_days` | `30` | Refresh token 有效期（天）|
| `download.max_retries` | `3` | 媒体下载失败最大重试次数 |
| `download.user_agent` | *(见上方)* | 媒体下载使用的 HTTP User-Agent |

### API 示例

```bash
# 读取当前配置
curl -s "$BASE_URL/v1/system/settings" -H "Authorization: Bearer ACCESS_TOKEN"

# 部分更新（嵌套结构）
curl -s -X PUT "$BASE_URL/v1/system/settings" \
  -H "Authorization: Bearer ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "download": { "max_retries": 5 },
    "auth": { "access_token_expire_minutes": 120 }
  }'
```

响应 `data` 字段为完整的嵌套配置对象（`plugins` / `auth` / `download`）。

### 从旧版本迁移

若你此前通过环境变量 `PLUGINS_REPO_REF`、`PLUGINS_REPO_REF_TYPE`、`ACCESS_TOKEN_EXPIRE_MINUTES` 等自定义过这些值，升级后请手动写入 `/config/settings.yaml`。这些环境变量已不再读取。

## 持久化数据

`/config` 卷包含所有持久化数据：

```
/config/
  settings.yaml         # 应用运行时配置
  data/
    contenthive.db      # SQLite 数据库
    media/              # 已下载的媒体文件
  logs/                 # 滚动日志文件
  plugins/              # 已安装的插件目录
    plugins.yaml        # 插件启用状态和配置
```
