# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Content Hive is a FastAPI-based content parsing service (port 6123) with a plugin-driven architecture. It runs on Python 3.13, uses SQLite via SQLAlchemy ORM, and is deployed via Docker.

## Commands

**Development (Docker):**
```bash
make up       # Build and start the service
make down     # Stop the service
```

**Dependencies:**
```bash
uv sync       # Install dependencies into .venv
uv lock       # Update lock file
```

**Lint / Format:**
```bash
ruff check .       # Lint
ruff format .      # Format
ruff check --fix . # Auto-fix lint issues
```

There is no configured test suite in this project.

**Run locally (without Docker):**
```bash
uv run uvicorn contenthive.main:app --host 0.0.0.0 --port 6123
```

## Architecture

```
Router → Service → DAO (context manager) → ORM Model → SQLite
```

- `contenthive/routers/` — Request parsing and auth only; delegates to Services
- `contenthive/services/` — Business logic; calls DAOs and plugins
- `contenthive/database/` — DAOs and ORM models (all ORM table classes are in `orm_models.py`)
- `contenthive/models/` — Pydantic API models (request/response) and `@dataclass` DB entities
- `contenthive/plugins/` — Plugin lifecycle, context, registry, config, and GitHub downloader
- `contenthive/config.py` — Pydantic Settings singleton; all config accessed here
- `contenthive/logger.py` — Project-wide async-safe logger with file rotation

**Task system:** `services/task_queue.py` runs an async deque-based queue (default concurrency: 3) with priority scheduling. `services/task.py` handles task lifecycle and deduplication.

**Plugin system:** Plugins live under `PLUGINS_DIR` (`/config/plugins`). Each plugin is a Python package with `manifest.json` and `__init__.py` defining `async_setup`, `async_setup_entry`, and `async_unload_entry`.

## Coding Conventions

### API Models
- Inherit from `APIBaseModel` (`contenthive/models/api.py`)
- Endpoints return `APIResponse[T]` (status, data, error, timestamp)
- Raise errors via `DetailedHTTPException` with `ErrorDetail(code, message, details)`

### Database
- ORM models inherit from `Base` and `TimestampMixin` (auto-adds `created_at`, `updated_at`, `deleted_at`)
- All datetime fields use `AwareDatetime` (stored as UTC)
- **DAOs must be used as context managers only:**
  ```python
  with TaskDAO() as dao:
      result = dao.get_main_task_by_id(id)
  ```

### Async
- Route handlers and service methods with I/O: `async def`
- Pure SQLAlchemy DAO operations: regular `def`

### Logging
- Always `from contenthive.logger import logger` — never use `print`
- `DEBUG`: internal flow (file only); `INFO`: lifecycle events (console + file); `WARNING`: recoverable failures; `ERROR`: unrecoverable — use `logger.exception()` inside `except` blocks
- No Unicode symbols in log messages; no per-item `INFO` inside loops (use `DEBUG` + one summary `INFO`)

### Imports
- All imports at top of file: standard library → third-party → internal
- No inline imports except for circular dependency resolution or optional/heavy dependencies

### Docstrings & Types
- All classes and public methods must have docstrings (purpose, Args, Returns)
- All functions and methods must have complete type annotations using `typing` module

### Method Ordering
- Public methods before private methods (prefixed `_`)
- No comment divider lines between groups

## Docker & CI/CD

- Port: `6123`; persistent volume: `/config` (data, logs, plugins)
- Image builds triggered by `v*` Git tags; pushes to GHCR and Docker Hub
- Non-`dev`/`beta` versions also push `:latest`
