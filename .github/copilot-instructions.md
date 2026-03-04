# Content Hive - Copilot Instructions

## Project Overview

Content Hive is a content parsing service built on **FastAPI + Python 3.12**, using SQLite as the database, Playwright for browser automation, and a extensible plugin system. The service runs on port `6123` by default and is deployed via Docker.

---

## Tech Stack

- **Web Framework**: FastAPI + Uvicorn
- **Database**: SQLite + SQLAlchemy (ORM)
- **Data Validation**: Pydantic v2 / pydantic-settings
- **Browser Automation**: Playwright (Chromium)
- **Containerization**: Docker + GitHub Actions CI/CD (push to GHCR and Docker Hub)
- **Python Version**: 3.12

---

## Architecture Layers

```
Router → Service → DAO (Data Access Object) → ORM Model
```

- `contenthive/routers/`: FastAPI routes — responsible only for request parsing and auth; delegates business logic to Services
- `contenthive/services/`: Business logic layer — calls DAOs for DB operations, invokes plugins, manages tasks
- `contenthive/database/`: Data Access Objects (DAOs) and ORM models
- `contenthive/models/`: Pydantic API request/response models and database entity Dataclasses
- `contenthive/plugins/`: Plugin management system
- `contenthive/config.py`: Centralized configuration injected via environment variables

---

## Coding Conventions

### API Models

- All API request/response models must inherit from `APIBaseModel` (in `contenthive/models/api.py`)
- All endpoints must return the unified `APIResponse` model:
  ```python
  class APIResponse(APIBaseModel):
      status: Literal["success", "error"]
      data: Optional[Any]
      error: Optional[ErrorDetail]
      timestamp: datetime
  ```
- Errors must be raised using `DetailedHTTPException` with an `ErrorDetail` object (containing `code`, `message`, `details`)

### Database Models

- All ORM table models must inherit from both `Base` and `TimestampMixin` (which automatically adds `created_at`, `updated_at`, `deleted_at`)
- All datetime fields must use the custom `AwareDatetime` type to ensure timezone-awareness (stored as UTC)
- Database entities use Python `@dataclass`; API models use Pydantic

### DAO Usage

- DAO classes must be used via context managers — never instantiate directly:
  ```python
  # Correct
  with TaskDAO() as dao:
      result = dao.get_main_task_by_id(id)

  # Wrong
  dao = TaskDAO()
  dao.get_main_task_by_id(id)
  ```

### Configuration (Settings)

- All configuration is accessed via the `settings` singleton in `contenthive/config.py`
- Config values are overridable via environment variables, following pydantic-settings conventions
- Path-type config fields must use `pathlib.Path`

### Type Annotations

- **All functions and methods must have complete type annotations** (parameters and return values)
- Use the Python standard `typing` module (`Optional`, `List`, `Dict`, `Any`, etc.)

### Docstrings

- **All classes and public methods must have docstrings** covering at minimum: purpose, Args, and Returns

### Logging

- Use the project-wide logger: `from contenthive.logger import logger`
- Never use `print` as a substitute for logging

### Async Conventions

- Route handlers and service methods involving I/O must use `async def`
- Pure database DAO operations (SQLAlchemy synchronous Session) use regular `def`

---

## Plugin System

Plugins live under `PLUGINS_DIR` (default: `/config/plugins`). Each plugin is a Python package and must contain:

| File | Description |
|---|---|
| `manifest.json` | Plugin metadata (id, name, version, description) |
| `__init__.py` | Plugin lifecycle callbacks |

### Plugin Lifecycle Functions (`__init__.py`)

```python
async def async_setup(context: PluginContext, config: dict) -> bool:
    """Called once on plugin initialization."""
    ...

async def async_setup_entry(context: PluginContext, entry: PluginEntryData) -> bool:
    """Called when a config entry is activated; responsible for loading platforms."""
    await context.async_forward_entry_setup(entry, "parser")
    return True

async def async_unload_entry(context: PluginContext, entry: PluginEntryData) -> bool:
    """Called when an entry is unloaded; responsible for cleanup."""
    return await context.async_unload_platforms(entry, ["parser"])
```

- The platform parser is implemented in `parser.py` inside the plugin package, defining a Parser class that inherits from the base class.

---

## Docker & CI/CD

- Image builds are triggered by pushing a Git tag matching `v*` (e.g., `v1.2.3`)
- The version is extracted from the tag and passed into the image via the `APP_VERSION` build-arg
- Non-`dev`/`beta` versions also push the `:latest` tag
- Images are pushed to both **GHCR** (`ghcr.io`) and **Docker Hub**
- Playwright/Chromium browsers are automatically installed to `/config/ms-playwright` on the first container startup

---

## Directory Conventions

| Path | Description |
|---|---|
| `/config/data/` | Database and media files |
| `/config/logs/` | Log files |
| `/config/plugins/` | User-installed plugins |
| `/config/ms-playwright/` | Playwright browser binaries |
