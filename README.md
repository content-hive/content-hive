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
    image: ghcr.io/content-hive/content-hive:latest  # or docker.io/DOCKERHUB_USER/content-hive:latest
    container_name: content-hive
    ports:
      - "6123:6123"
    volumes:
      - ./data:/config
    environment:
      - TZ=Asia/Shanghai
    restart: unless-stopped
```

On first start, create an admin account via `POST /v1/system/setup`. See the [documentation](https://content-hive.github.io/content-hive/en/getting-started) for details.

## Documentation

- [English](https://content-hive.github.io/content-hive/en/intro)
- [中文](https://content-hive.github.io/content-hive/zh/intro)

## License

MIT
