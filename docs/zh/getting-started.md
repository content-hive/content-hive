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
