# 配置项

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

## 持久化数据

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
