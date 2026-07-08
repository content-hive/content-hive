# Quick Start

**Prerequisites:** Docker

Images are published to GitHub Container Registry and Docker Hub on every tagged release.

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

Save as `docker-compose.yml`, then run:

```bash
docker compose up -d
```

On first start, create an admin account:

```bash
BASE_URL="http://localhost:6123"

# 1. Check whether setup is required
curl -s "$BASE_URL/v1/system/health"
# data.setup_required: true

# 2. Create admin (auto-login, returns tokens)
curl -s -X POST "$BASE_URL/v1/setup" \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "YourPassword123!"}'
```

Password requirements: ≥8 characters with uppercase, lowercase, digit, and special character (`!@#$%^&*`).

Access the interactive API docs at: `http://localhost:6123/docs`
