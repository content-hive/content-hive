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
      - ADMIN_PASSWORD=YourPassword123!
    restart: unless-stopped
```

Save as `docker-compose.yml`, then run:

```bash
docker compose up -d
```

On first start, an admin account is created automatically:
- Username: `admin`
- Password: value of `ADMIN_PASSWORD`, or a randomly generated password written to `/config/data/.admin_credentials` (permissions 600) if not set — the log will show the file path. Delete the file after recording the credentials.

Access the interactive API docs at: `http://localhost:6123/docs`
