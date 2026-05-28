# Content Hive

Self-hosted content parser and media downloader for social platforms, powered by plugins.

## Overview

Content Hive is a self-hosted service that parses content from social media platforms and downloads associated media files. It uses a plugin architecture — each supported platform is an independent plugin that can be installed, updated, enabled, or disabled at runtime without restarting the application.

## Features

### Plugin-driven Architecture
Each platform (Twitter, YouTube, TikTok, etc.) is implemented as an independent plugin. Plugins are distributed via a GitHub repository and can be installed, updated, and hot-reloaded through the API.

### Task Deduplication
When the same URL is submitted by multiple users simultaneously, Content Hive avoids redundant work with a shared-execution mechanism:
- **PRIMARY** — the first submission; executes parse and download
- **LINKED** — subsequent submissions of the same URL while PRIMARY is running; waits for PRIMARY and shares its result

The task model also includes **REUSED** as a task type for cache-reuse workflows, but the online dedup path primarily relies on PRIMARY/LINKED.

### Async Task Queue
Tasks are executed concurrently with configurable limits and priority scheduling (FIFO within the same priority level). Tasks can be cancelled before execution starts.

### Media Download
Parsed content may contain multiple media items (images, videos, etc.). Content Hive downloads each one and stores it locally under a structured path: `/config/data/media/{platform}/{author}/{content_id}/`. MIME types are detected automatically.

### Multi-user Support
Each user has isolated content, task history, and platform/author subscriptions. Authentication uses short-lived access tokens and long-lived refresh tokens.

### Plugin Management API
Plugins can be listed, installed from a remote repository, enabled/disabled, configured, and deleted through a REST API. Version checks are lightweight — only the remote manifest is fetched, not the full package.

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
