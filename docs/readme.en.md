# Content Hive

Self-hosted content parser and media downloader for social platforms, powered by plugins.

## Overview

Content Hive is a self-hosted service that parses content from social media platforms and downloads associated media files. It uses a plugin architecture — each supported platform is an independent plugin that can be installed, updated, enabled, or disabled at runtime without restarting the application.

## Features

### Plugin-driven Architecture
Each platform (Twitter, YouTube, TikTok, etc.) is implemented as an independent plugin. Plugins are distributed via a GitHub repository and can be installed, updated, and hot-reloaded through the API.

### Task Deduplication
When the same URL is submitted by multiple users simultaneously, Content Hive uses a three-role mechanism to avoid redundant work:
- **PRIMARY** — the first submission; executes the parse and download
- **LINKED** — subsequent submissions of the same URL while PRIMARY is running; waits for PRIMARY to complete
- **REUSED** — submissions of a URL that has already been processed; returns the cached result immediately

### Async Task Queue
Tasks are executed concurrently with configurable limits and priority scheduling (FIFO within the same priority level). Tasks can be cancelled before execution starts.

### Media Download
Parsed content may contain multiple media items (images, videos, etc.). Content Hive downloads each one and stores it locally under a structured path: `/config/data/media/{platform}/{author}/{content_id}/`. MIME types are detected automatically.

### Multi-user Support
Each user has isolated content, task history, and platform/author subscriptions. Authentication uses short-lived access tokens and long-lived refresh tokens.

### Plugin Management API
Plugins can be listed, installed from a remote repository, enabled/disabled, configured, and deleted through a REST API. Version checks are lightweight — only the remote manifest is fetched, not the full package.

---

## Quick Start

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

---

## Configuration

All settings are configured via environment variables.

| Variable | Default | Description |
|----------|---------|-------------|
| `HOST` | `0.0.0.0` | Server bind address |
| `PORT` | `6123` | Server port |
| `TZ` | `Asia/Shanghai` | Container timezone |
| `ENVIRONMENT` | `production` | Runtime environment (`production` / `development`) |
| `DEBUG` | `false` | Enable debug logging |
| `ADMIN_PASSWORD` | *(auto-generated)* | Admin account password on first start. Must be ≥8 chars with uppercase, lowercase, digit, and special character. |
| `DATA_DIR` | `/config/data` | Directory for database and media files |
| `LOGS_DIR` | `/config/logs` | Directory for log files |
| `PLUGINS_DIR` | `/config/plugins` | Directory for installed plugins |
| `PLUGINS_REPO_URL` | `https://github.com/content-hive/plugins.git` | Plugin distribution repository |
| `PLUGINS_REPO_REF_TYPE` | `branch` | Repository ref type: `branch`, `tag`, or `commit` |
| `PLUGINS_REPO_REF` | `main` | Repository ref value |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `60` | Access token validity in minutes |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `30` | Refresh token validity in days |
| `DOWNLOAD_MAX_RETRIES` | `3` | Maximum retries for media download failures |

### Persistent Data

The `/config` volume contains all persistent data:

```
/config/
  data/
    contenthive.db      # SQLite database
    media/              # Downloaded media files
  logs/                 # Rotating log files
  plugins/              # Installed plugin directories
    plugins.yaml        # Plugin enable/disable state and configuration
```

---

## API

Interactive API documentation is available at `http://localhost:6123/docs` (Swagger UI).

| Prefix | Description |
|--------|-------------|
| `/v1/task` | Submit URLs for parsing, check task status, cancel tasks |
| `/v1/content` | Query parsed content, list platforms and authors |
| `/v1/plugins` | Manage plugins (install, update, configure, enable/disable) |
| `/v1/users` | User registration, login, token refresh, password change |
| `/v1/admin` | Admin-only: user management |
| `/v1/system` | Health check, storage stats, log viewer, application restart |

---

## Plugin System

Plugins add support for new content platforms. Each plugin is a Python package that implements a standard interface.

See [docs/plugins.en.md](plugins.en.md) for the plugin development guide.

---

## Tech Stack

| Component | Library |
|-----------|---------|
| Web framework | FastAPI 0.128 |
| ORM | SQLAlchemy 2.0 |
| Database | SQLite (synchronous SQLAlchemy engine) |
| Migrations | Alembic |
| Data validation | Pydantic / pydantic-settings |
| Authentication | python-jose (JWT) + pwdlib (Argon2) |
| HTTP client | aiohttp |
| Package manager | uv |
| Runtime | Python 3.13 |

---

## License

MIT
