# Content Hive

Self-hosted content parser and media downloader for social platforms, powered by plugins.

## Features

- **Plugin-driven** — each platform is a plugin; install, update, and hot-reload without restarting
- **Task deduplication** — same URL submitted by multiple users shares one execution
- **Async task queue** — concurrent processing with priority scheduling
- **Media download** — automatically downloads and stores media files from parsed content
- **Multi-user** — user-isolated content and tasks with JWT authentication
- **Online updates** — install and update plugins directly from a GitHub repository

## Quick Start

```yaml
services:
  content-hive:
    image: content-hive:latest
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

On first start, an admin account is created automatically. If `ADMIN_PASSWORD` is not set, a random password is generated and printed to the logs.

## Documentation

- [English](docs/readme.en.md)
- [中文](docs/readme.zh.md)

## License

MIT
