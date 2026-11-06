# Plugin System

Content Hive uses a Home Assistant-style plugin architecture. Each supported platform (Twitter, YouTube, TikTok, etc.) is an independent plugin that can be installed, updated, configured, and hot-reloaded at runtime without restarting the application.

Each plugin lives in its own GitHub repository and ships as GitHub Releases. Content Hive finds plugins through the [plugin catalog](https://github.com/content-hive/plugins) and manages them through the REST API.

For internal architecture details, see [Plugin System Internals](/en/plugin-system).

---

## Quick Start

A minimal plugin requires three files:

```
plugins/
└── my_parser/
    ├── manifest.json
    ├── __init__.py
    └── parser.py
```

**manifest.json**
```json
{
  "domain": "my_parser",
  "name": "My Parser",
  "version": "1.0.0",
  "requirements": [],
  "author": ["Your Name"]
}
```

**\_\_init\_\_.py**
```python
from contenthive.plugins.context import PluginContext
from contenthive.plugins.manager import PluginEntryData

DOMAIN = "my_parser"

async def async_setup_entry(context: PluginContext, entry: PluginEntryData) -> bool:
    await context.async_forward_entry_setup(entry, "parser")
    return True

async def async_unload_entry(context: PluginContext, entry: PluginEntryData) -> bool:
    return await context.async_unload_platforms(entry, ["parser"])
```

**parser.py**
```python
from typing import Any
from contenthive.plugins.context import PluginContext
from contenthive.plugins.contracts import (
    ParserResult, ParserAuthorInfo, ParserPlatformInfo, ParserResultStatus
)
from contenthive.plugins.manager import PluginEntryData

DOMAIN = "my_parser"

class MyParser:
    def __init__(self, context: PluginContext, entry: PluginEntryData):
        self.context = context

    def can_parse(self, data: dict[str, Any]) -> bool:
        url = data.get("url", "")
        return "example.com" in url

    async def parse(self, data: dict[str, Any]) -> ParserResult:
        url = data.get("url")
        return ParserResult(
            pid="unique-id",
            url=url,
            title="Example Post",
            content="Post text here",
            media=[],
            author=ParserAuthorInfo(uid="123", username="author"),
            platform=ParserPlatformInfo(code="example", name="Example", url="https://example.com"),
            post_time=None,
            parser=DOMAIN,
            state=ParserResultStatus.SUCCESS,
        )

    async def async_will_remove(self):
        pass


async def async_setup_entry(context, entry, async_add_entities):
    parser = MyParser(context, entry)
    await async_add_entities([parser])  # registers parser for cleanup on unload

    # Register services so ContentService can discover and call this parser
    context.register_service(DOMAIN, "can_parse", parser.can_parse)
    context.register_service(DOMAIN, "parse", parser.parse)
```

---

## Plugin Directory Structure

```
plugins/
└── {domain}/
    ├── manifest.json     # Plugin metadata (required)
    ├── __init__.py       # Lifecycle hooks + optional CONFIG_SCHEMA
    ├── parser.py         # Platform module (registered via async_forward_entry_setup)
    └── const.py          # Constants (optional)
```

The `domain` must match the `domain` field in `manifest.json` and must contain only `[a-z0-9_-]` characters.

---

## manifest.json Reference

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `domain` | `string` | Yes | Unique plugin identifier. Alphanumeric, underscores, hyphens only. |
| `name` | `string` | Yes | Human-readable display name |
| `version` | `string` | Yes | Semantic version (e.g. `"1.2.0"`) |
| `requirements` | `list[string]` | No | PyPI packages to install (e.g. `["aiohttp~=3.9"]`) |
| `author` | `list[string]` | No | Author name(s) |
| `description` | `string` | No | Short description |

---

## Plugin Lifecycle

```
INSTALLED ──async_setup──> LOADED ──async_setup_entry──> ENABLED
                              │
                              ├── disabled: true (module stays loaded, no entry)
                              ▼
                           DISABLED                         FAILED
```

| State | Meaning |
|-------|---------|
| `INSTALLED` | `manifest.json` loaded; module not yet imported |
| `LOADED` | Module imported, dependencies installed; no active config entry |
| `ENABLED` | Config entry active; plugin is running |
| `DISABLED` | Marked `disabled: true`. Module stays loaded after setup; no config entry is activated |
| `FAILED` | An error occurred during setup or runtime |

---

## Lifecycle Hooks (`__init__.py`)

### `async_setup(context) -> bool` *(optional)*

Called once when the plugin module is loaded. Use for one-time initialization that does not depend on user configuration.

```python
async def async_setup(context: PluginContext) -> bool:
    context.logger.info("Plugin loaded")
    return True
```

### `async_setup_entry(context, entry) -> bool` *(required)*

Called when the plugin's config entry is activated. This is where you read configuration and register platform modules. Return `False` to abort activation (e.g. missing required config value).

```python
async def async_setup_entry(context: PluginContext, entry: PluginEntryData) -> bool:
    config = context.get_config(DOMAIN)
    if not config.api_key:
        context.logger.warning("api_key is not configured")
        return False
    await context.async_forward_entry_setup(entry, "parser")
    return True
```

### `async_unload_entry(context, entry) -> bool` *(required)*

Called when the plugin is being disabled, reloaded, or the application is shutting down. Unload all registered platforms and release resources.

```python
async def async_unload_entry(context: PluginContext, entry: PluginEntryData) -> bool:
    return await context.async_unload_platforms(entry, ["parser"])
```

---

## Platform Module (`parser.py`)

Platform modules are registered by calling `context.async_forward_entry_setup(entry, "parser")` inside `async_setup_entry`. Content Hive will load the module and call its own `async_setup_entry`.

```python
async def async_setup_entry(context, entry, async_add_entities):
    parser = MyParser(context, entry)
    await parser.async_setup()       # optional initialization

    # Register for lifecycle cleanup (async_will_remove is called on unload)
    await async_add_entities([parser])

    # Register services — required for ContentService to discover and call this parser
    context.register_service(DOMAIN, "can_parse", parser.can_parse)
    context.register_service(DOMAIN, "parse", parser.parse)
```

> `can_parse` and `parse` are the two services ContentService calls to discover and execute parsers. Without registering them, the plugin will load but never receive any URLs.

### Parser interface

Your parser class must implement:

| Method | Signature | Description |
|--------|-----------|-------------|
| `can_parse` | `(data: dict) -> bool` | Return `True` if `data["url"]` is handled by this plugin |
| `parse` | `async (data: dict) -> ParserResult` | Fetch and return parsed content for `data["url"]` |
| `async_will_remove` | `async () -> None` | Clean up resources (close HTTP sessions, etc.) |

---

## Plugin Contracts

Import from `contenthive.plugins.contracts`. Do not import from core internals.

### `ParserResult`

| Field | Type | Description |
|-------|------|-------------|
| `pid` | `str` | Unique content ID on the platform |
| `url` | `str` | Original URL |
| `title` | `str \| None` | Post title |
| `content` | `str \| None` | Post body text |
| `media` | `list[ParserMediaInfo]` | Media attachments |
| `author` | `ParserAuthorInfo` | Author information |
| `platform` | `ParserPlatformInfo` | Platform information |
| `post_time` | `int \| None` | Unix timestamp of the post |
| `parser` | `str` | Parser identifier (usually `DOMAIN`) |
| `state` | `ParserResultStatus` | `SUCCESS` or `ERROR` |

### `ParserMediaInfo`

The media item itself only answers “which attachment is this, and what kind is it”. Remote addresses live on typed `streams`. `source_key` is the stable identity inside a post; do not put rotating signed query parameters in it. `source_key_from_url()` takes the last path component without the query string.

| Field | Type | Description |
|-------|------|-------------|
| `source_key` | `str` | Stable identity within the post. Must stay the same across re-parses. |
| `type` | `MediaType` | `image`, `gif`, `video`, `audio`, `livephoto`, or `link` |
| `title` | `str \| None` | Media title |
| `duration` | `int \| None` | Parser-provided duration in milliseconds (reference until the file is probed) |
| `width` | `int \| None` | Parser-provided width in pixels (reference until the file is probed) |
| `height` | `int \| None` | Parser-provided height in pixels (reference until the file is probed) |
| `streams` | `list[MediaStream]` | Typed streams discriminated by `role` |
| `extra` | `dict[str, Any]` | Platform fields the core does not interpret (for example Bilibili `cid` / `qn`) |

Core rejects a media item whose streams do not match `type`:

| `type` | Required streams | Optional streams |
|--------|------------------|------------------|
| `image`, `gif` | one `ImageStream` | — |
| `video` | one `VideoStream` | one `AudioStream` (DASH), one `CoverStream` |
| `audio` | one `AudioStream` | one `CoverStream` |
| `livephoto` | one `VideoStream` and one `ImageStream` (still frame) | — |
| `link` | one `LinkStream` | one `CoverStream` |

A live-photo still is part of the finished item, so it uses `ImageStream`, not `CoverStream`.

### Stream types

Every stream has `urls: list[str]` (at least one). `urls[0]` is the primary address; later entries are download fallbacks. `role` is the discriminator.

| Class | `role` | Extra fields | Notes |
|-------|--------|--------------|-------|
| `ImageStream` | `image` | `width`, `height` | Still image, GIF, or live-photo still |
| `VideoStream` | `video` | `codec`, `bandwidth`, `width`, `height`, `quality` | |
| `AudioStream` | `audio` | `codec`, `bandwidth`, `quality`, `label` | `label` holds names such as FLAC or Dolby |
| `CoverStream` | `cover` | — | Poster; not part of the finished file |
| `LinkStream` | `link` | — | Stored URL only; never downloaded as a media file |

```python
from contenthive.plugins.contracts import (
    CoverStream,
    ParserMediaInfo,
    VideoStream,
    AudioStream,
    MediaType,
    source_key_from_url,
)

ParserMediaInfo(
    source_key=source_key_from_url(video_url),
    type=MediaType.VIDEO,
    streams=[
        VideoStream(urls=[video_url], width=3840, height=2160, quality="127"),
        AudioStream(urls=[audio_url], label="FLAC"),
        CoverStream(urls=[cover_url]),
    ],
    extra={"cid": 123, "qn": "127"},
)
```

### `ParserAuthorInfo`

| Field | Type | Description |
|-------|------|-------------|
| `uid` | `str` | Platform-specific user ID |
| `username` | `str` | Username / handle |
| `name` | `str \| None` | Display name |
| `avatar` | `str \| None` | Avatar URL |
| `url` | `str \| None` | Profile URL |
| `banner` | `str \| None` | Banner image URL |
| `description` | `str \| None` | Bio / description |

### `ParserPlatformInfo`

| Field | Type | Description |
|-------|------|-------------|
| `code` | `str` | Short platform identifier (e.g. `"twitter"`) |
| `name` | `str` | Display name (e.g. `"Twitter / X"`) |
| `url` | `str` | Platform homepage URL |
| `icon_url` | `str \| None` | Platform icon URL |

---

## Configuration Schema

If your plugin requires user configuration (API keys, cookies, etc.), define a `CONFIG_SCHEMA` in `__init__.py`.

```python
from enum import Enum
from pydantic import Field
from contenthive.plugins.contracts import PluginConfigSchema

class Quality(str, Enum):
    LOW = "low"
    HIGH = "high"

class ConfigSchema(PluginConfigSchema):
    api_key: str = Field(default="", title="API Key",
                         json_schema_extra={"secret": True})
    quality: Quality = Field(default=Quality.HIGH, title="Video Quality")

CONFIG_SCHEMA = ConfigSchema
```

**Rules:**
- All fields **must** declare a default value so the plugin loads on first boot without user configuration.
- For required user input (API keys, cookies), use `default=""` and check the value in `async_setup_entry`, returning `False` with a warning log if empty.
- Mark sensitive fields with `json_schema_extra={"secret": True}` — the API will redact them in responses.
- Supported field types: `str`, `int`, `float`, `bool`, `str`-based `Enum` subclasses.

Configuration is persisted to `plugins.yaml` and exposed via the plugin management API.

---

## Plugin Context

The `PluginContext` object is passed to all lifecycle hooks.

| Attribute | Type | Description |
|-----------|------|-------------|
| `logger` | `logging.Logger` | Plugin-scoped logger |
| `data` | `dict[str, Any]` | In-memory plugin data store |
| `get_config(domain)` | `Callable` | Returns current config as a `PluginConfigSchema` instance |
| `save_config(domain, config)` | `Callable` | Persists config to `plugins.yaml` |
| `async_forward_entry_setup(entry, platform)` | `Callable` | Loads and registers a platform module |
| `async_unload_platforms(entry, platforms)` | `Callable` | Unloads registered platform modules |
| `register_service(domain, service, callback)` | `Callable` | Registers a named service callable |

---

## Services

Plugins can register named services that other components (including the core download pipeline) can call.

```python
import inspect

from contenthive.plugins.contracts import ProgressCallback

# Register a custom download service in async_setup_entry
async def my_download(data: dict):
    media = data["media"]
    on_progress: ProgressCallback | None = data.get("on_progress")
    # Fetch each stream's bytes (signed URLs, session cookies, etc.).
    # Return temporary files keyed by role. Do not mux or archive.
    # on_progress reflects main-stream progress (0-100); cover may download
    # in parallel but should not be counted. Link streams are not downloaded.
    pct = 100  # TODO: compute 0–100 from main stream downloaded/total
    if on_progress is not None:
        result = on_progress(pct)
        if inspect.isawaitable(result):
            await result
    return {"streams": {"video": "/tmp/video.m4s", "audio": "/tmp/audio.m4s"}}

context.register_service(DOMAIN, "download", my_download)
```

The core media pipeline checks for a `download` service before falling back to its built-in HTTP downloader. Registering a `download` service lets your plugin fetch bytes with custom logic (session cookies, signed URLs, etc.). Return `{streams: {role: temp_path}}` for the files you fetched; the core assembles them (including DASH video+audio mux with ffmpeg). Optional progress reporting uses `on_progress`: a `ProgressCallback` imported from `contenthive.plugins.contracts` (may be sync or async; guard for `None` and `await` when needed). Report main-stream percent only; treat task `status` as the source of truth for completion. Live `retry` state on task details (`phase` / `attempt` / etc.) is emitted only by the built-in downloader; plugin `download` services do not receive a retry callback, so `retry` stays `null`.

---

## Distribution

Content Hive reads the built-in catalog at `https://content-hive.github.io/plugins/catalog.json`. To install or update a plugin, it downloads the release tag's source archive from the plugin repository and copies its `plugin/` directory to `PLUGINS_DIR/<domain>`.

To publish a plugin, keep the code in `plugin/`, publish a GitHub Release tagged `v<manifest version>`, and add the repository to the catalog. The catalog repository's README lists the requirements.

Plugins whose catalog `min_core_version` is newer than the running core are not offered. Install also checks `contenthive.json` in the selected release tag, so a beta that needs a newer core is rejected even when the catalog entry was taken from stable.

### Release Tracks

Every plugin follows the stable track by default: the latest GitHub Release that is not a pre-release. To use pre-release (beta) versions for one plugin, set `prerelease: true` in `plugins.yaml`:

```yaml
douyin:
  prerelease: true
```

or call the API:

```bash
curl -s -X PUT "$BASE_URL/v1/plugins/douyin/prerelease" \
  -H "Authorization: Bearer ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}'
```

- With `prerelease: true`, the plugin uses the latest beta when it is newer than stable, otherwise stable.
- The setting works before the plugin is installed. Deleting the plugin removes it along with the rest of that plugin's config.
- Turning it off does not downgrade an installed beta; the plugin updates again once a newer stable is released.
- A plugin that only has beta releases shows `installable: false` in `/v1/plugins/available` until `prerelease` is enabled.

---

## Debugging

| What to inspect | How |
|-----------------|-----|
| Plugin state | `manager.plugins[domain].state` |
| Error details | `manager.plugins[domain].error` |
| Config schema | `manager.plugins[domain].config_schema` |
| Domains with active parsers | `[d for d, s in manager.services.items() if "can_parse" in s]` |
| Available updates cache | `manager._available_updates` |
| Trigger hot-reload | `await manager.async_reload(domain)` |
| Listen for events | `manager.event_bus.listen("plugin_enabled", callback)` |

Logs are written to the `LOGS_DIR` directory with daily rotation. The System API (`GET /v1/system/logs`) provides paginated log access without direct file access.
