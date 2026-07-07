# API 文档

交互式 API 文档（Swagger UI）访问地址：`http://localhost:6123/docs`

| 路由前缀 | 说明 |
|----------|------|
| `/v1/task` | 提交 URL 解析任务、查询任务状态、取消任务 |
| `/v1/content` | 查询已解析的内容，列出平台和作者 |
| `/v1/plugins` | 插件管理：安装、更新、配置、启用/禁用 |
| `/v1/user` | 用户登录、令牌刷新、个人资料、修改密码 |
| `/v1/admin` | 管理员专属：用户管理 |
| `/v1/system` | 健康检查、存储状态、日志查看、应用设置、应用重启 |

说明：`/v1/user/token` 是 OAuth2 兼容端点，直接返回 `{ "access_token": "...", "token_type": "bearer" }`，不使用统一 `APIResponse` 包装。

## 最小 API 调用流程示例

先设置基础地址：

```bash
BASE_URL="http://localhost:6123"
```

1) 登录并获取令牌：

```bash
curl -s -X POST "$BASE_URL/v1/user/login" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "password": "YourPassword123!"
  }'
```

2) 提交解析任务（将 `ACCESS_TOKEN` 替换为真实值）：

```bash
curl -s -X POST "$BASE_URL/v1/task/parser" \
  -H "Authorization: Bearer ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://x.com/example/status/1234567890"
  }'
```

3) 按任务 ID 查询任务（将 `TASK_ID` 替换为真实值）：

```bash
curl -s -X GET "$BASE_URL/v1/task/parser/TASK_ID" \
  -H "Authorization: Bearer ACCESS_TOKEN"
```

4) 健康检查：

```bash
curl -s "$BASE_URL/v1/system/health"
```

## 错误码速查表

| 错误码 | 常见 HTTP 状态码 | 位置 | 含义 / 处理建议 |
|--------|------------------|------|-----------------|
| `AUTHENTICATION_FAILED` | `401` | `/v1/user/login` | 用户名或密码错误；检查凭据与账号状态 |
| `INVALID_CREDENTIALS` | `401` | 鉴权依赖 | 令牌无效或过期；重新登录并刷新令牌 |
| `TASK_NOT_FOUND` | `404` | `/v1/task/*` | 任务 ID 不存在，或当前用户无权访问 |
| `TASK_CREATION_FAILED` | `500` | `/v1/task/parser` | 服务端创建任务失败；检查日志 |
| `INVALID_CURSOR` | `400` | `/v1/task/parser/cursor`、`/v1/system/logs` | 游标格式错误或已失效；从第一页重新开始 |
| `PLUGIN_NOT_FOUND` | `404` | `/v1/plugins/{domain}/*` | 指定插件未安装 |
| `CONFIG_VALIDATION_FAILED` | `400` | `/v1/plugins/{domain}/config` | 提交的插件配置不符合 Schema |
| `STORAGE_STATUS_FAILED` | `500` | `/v1/system/storage` | 存储统计采集失败；检查文件系统与日志 |
| `INVALID_TIME_RANGE` | `400` | `/v1/system/logs` | `from` 必须早于 `to` |
| `LOG_READ_FAILED` | `500` | `/v1/system/logs` | 日志文件读取或解析失败 |
| `SETTINGS_VALIDATION_FAILED` | `400` | `/v1/system/settings` | 提交的应用设置不符合 schema |
| `PERSISTED_SETTINGS_INVALID` | `422` | `/v1/system/settings` | 已存储的应用设置无效，无法读取 |
| `USER_CREATION_FAILED` | `400` | `/v1/admin/users` | 创建用户请求不合法（重名、密码策略等） |
| `ADMIN_PRIVILEGES_REQUIRED` | `403` | 管理员受保护接口 | 当前用户不是管理员 |
