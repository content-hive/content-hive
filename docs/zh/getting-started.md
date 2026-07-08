# 快速开始

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
    restart: unless-stopped
```

保存为 `docker-compose.yml`，然后运行：

```bash
docker compose up -d
```

首次启动后，需要创建管理员账号：

```bash
BASE_URL="http://localhost:6123"

# 1. 检查是否需要初始化
curl -s "$BASE_URL/v1/system/health"
# data.setup_required: true

# 2. 创建管理员（自动登录，返回 token）
curl -s -X POST "$BASE_URL/v1/setup" \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "YourPassword123!"}'
```

密码要求：≥8 位，包含大小写字母、数字和特殊字符（`!@#$%^&*`）。

访问交互式 API 文档：`http://localhost:6123/docs`
