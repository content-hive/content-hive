# Plugin System Internals

This document describes the internal architecture, lifecycle mechanism, and module design of the Content Hive plugin system. It is intended for maintainers and contributors.

To write a plugin, see the [Plugin Developer Guide](/en/plugins).

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    PluginManager                         │
│           (coordinates the full plugin lifecycle)        │
└──────────────┬──────────────────────────────────────────┘
               │
        ┌──────┴──────┬──────────────┬──────────────┐
        ▼             ▼              ▼              ▼
   PluginRecord  PluginContext   EventBus      Platform
   (plugin record) (plugin ctx)  (event bus)   Registry
        ▲
        │ uses
        │
   ┌────┴────────────────────────────┐
   │                                  │
   ▼                                  ▼
PluginState                manifest.json + Module Code
(state machine)            (plugin metadata + code)

┌──────────────────────────────────────────────────────────┐
│                   PluginService                           │
│   (service layer: install, update, reload, configure,    │
│    enable/disable)                                        │
└───────────────────────┬──────────────────────────────────┘
                        │
              ┌─────────┴─────────┐
              ▼                   ▼
 GitHubPluginDownloader      config.py
 (downloads and installs     (plugins.yaml read/write,
  plugins from GitHub)        persists plugin config)

┌──────────────────────────────────────────────────────────┐
│                   contracts.py                            │
│   (stable interface: PluginConfigSchema, ParserResult,   │
│    etc.)                                                  │
└──────────────────────────────────────────────────────────┘
```

---

## State Machine

```
INSTALLED ──async_setup──> LOADED ──async_setup_entry──> ENABLED
    ▲                         ▲                               │
    │                         └──────── async_unload_entry ──┘
    │                                   (when no other active entries)
    │
    ├── (plugins.yaml: disabled: true)
    │
DISABLED                                                  FAILED
    │                                              (setup or runtime error)
    └── async_setup (via enable API) ──> LOADED ──> ENABLED
```

| State | Meaning | Module loaded |
|-------|---------|---------------|
| `INSTALLED` | `manifest.json` loaded; module not yet imported | No |
| `LOADED` | Module imported, dependencies installed; no active config entry | Yes |
| `ENABLED` | Config entry active; plugin is running | Yes |
| `DISABLED` | Marked `disabled: true` in `plugins.yaml`; skipped at startup | No |
| `FAILED` | An error occurred during setup or runtime | Maybe |

State transitions are strictly controlled by `PluginManager`. External callers can only trigger them via API (enable / disable / reload / delete).

---

## Module Reference

### `registry.py` — Plugin Registry and State Management

Defines the `PluginState` enum and `PluginRecord` class.

**`PluginRecord`** stores all information about a single plugin:

```python
PluginRecord {
    domain: str              # unique plugin identifier
    manifest: dict           # plugin metadata
    instance: Any | None     # loaded plugin module object (a module, not a class instance)
    state: PluginState       # current state
    error: str | None        # error message when state is FAILED

    # computed properties (derived from manifest / instance)
    name: str
    version: str
    description: str | None
    author: list[str] | None
    config_schema: type[PluginConfigSchema] | None  # reads CONFIG_SCHEMA from module
    is_loaded: bool
    is_enabled: bool
}
```

> `config_schema` reads the `CONFIG_SCHEMA` attribute from the loaded module. Returns `None` if the module is not loaded or the attribute is not defined.

---

### `contracts.py` — Plugin Interface Contracts

Defines the **stable boundary** between Content Hive and its plugins. Plugins must only import from `contenthive.plugins.*` and must not reference core internals, ensuring compatibility across version upgrades.

Contains: `PluginConfigSchema`, `ParserResult`, `ParserMediaInfo`, `ParserAuthorInfo`, `ParserPlatformInfo`.

`PluginConfigSchema` uses `model_config = ConfigDict(extra="ignore")` to silently ignore unknown keys in the config file (such as the framework's own `disabled` field), preventing validation errors.

---

### `context.py` — Plugin Execution Context

`PluginContext` is the interface layer between plugins and the application. It is created at startup by `PluginManager`, which injects the callable methods.

```python
PluginContext {
    logger: Logger
    data: dict[str, Any]                  # per-plugin in-memory data store

    # injected by PluginManager at startup
    async_forward_entry_setup: Callable
    async_unload_platforms: Callable
    register_service: Callable
    get_config: Callable                   # returns a PluginConfigSchema instance
    save_config: Callable                  # persists a PluginConfigSchema instance
}
```

Design principle: `PluginContext` does not hold a database connection or application instance. Plugins obtain such resources via `settings` or dependency injection.

---

### `manager.py` — Core Plugin Manager

`PluginManager` is the heart of the plugin system. It coordinates discovery, loading, activation, unloading, version checking, and hot-reload.

#### `PluginEntryData` — Config Entry

```python
PluginEntryData {
    entry_id: str        # typically "{domain}_default"
    domain: str
    data: dict           # entry configuration data
    options: dict
    state: PluginState
}
```

#### `EventBus` — Event Bus

A lightweight inter-plugin communication mechanism that supports both sync and async listeners.

| Event | Fired when | Payload fields |
|-------|-----------|----------------|
| `plugins_discovered` | All plugins have been discovered | `count` |
| `plugin_discovered` | A single plugin is discovered | `domain`, `manifest` |
| `plugin_setup` | Plugin setup completes | `domain` |
| `plugin_enabled` | Plugin entry is activated | `domain`, `entry_id` |
| `plugin_disabled` | Plugin entry is unloaded | `domain`, `entry_id` |

#### Core Methods

| Method | Description |
|--------|-------------|
| `async_discover()` | Concurrently scans `plugins/` directory, reads all `manifest.json` files, creates `PluginRecord` objects (state=INSTALLED) |
| `async_setup(domain)` | Installs dependencies (runs `uv pip install` in a thread pool) → dynamically imports module → calls `async_setup(context)` → state=LOADED |
| `async_setup_entry(entry)` | Calls the plugin's `async_setup_entry(context, entry)` → stores entry → state=ENABLED |
| `async_forward_entry_setup(entry, platform)` | Loads the platform submodule (e.g. `parser.py`), injects it into `sys.modules` as `contenthive_plugin_{domain}.{platform}`, calls the platform's `async_setup_entry` |
| `async_unload_entry(entry_id)` | Calls the plugin's `async_unload_entry` → removes entry → state reverts to LOADED if no other active entries remain |
| `async_delete(domain)` | Unloads all entries → removes from registry → deletes the plugin directory from disk |
| `async_reload(domain)` | Unloads → clears `sys.modules` cache → resets to INSTALLED → re-runs setup + setup_entry |
| `async_activate(domain)` | First-time activation of a newly installed plugin: discover → setup → setup_entry |
| `async_check_updates(repo_url, ref)` | Fetches only the remote `plugins-manifest.json`, performs semantic version comparison, caches results |
| `register_service(domain, service, callback)` | Registers a named service callable |
| `call_service(domain, service, data)` | Calls a registered service |

**Hot-reload implementation** (`async_reload`):

```
1. async_unload_entry  (unload all active entries)
2. Clear sys.modules entries for plugin_{domain} and contenthive_plugin_{domain}.*
3. Reset PluginRecord state to INSTALLED
4. async_setup(config) + async_setup_entry
```

---

### `downloader.py` — GitHub Plugin Downloader

`GitHubPluginDownloader` safely downloads, extracts, and installs plugins from a GitHub repository.

**Remote repository format**: the repository root must contain a `plugins-manifest.json` that describes all available plugins and their paths.

**Key methods**:

```python
async download_plugins(
    repo_url: str,
    ref: str = "main",
    ref_type: str = "branch",        # "branch" | "tag" | "commit"
    selected_plugins: list[str] | None = None,
    force_reinstall: bool = False
) -> dict[str, bool]
```

```python
async fetch_remote_manifest(repo_url: str, ref: str = "main") -> dict | None
# fetches only plugins-manifest.json, does not download the full package
```

**Supported URL formats**: bare domain, HTTPS, and `.git` suffix are all accepted.

**Security measures**:

| Mechanism | Description |
|-----------|-------------|
| Domain validation | Only `[a-z0-9_-]` allowed; prevents path traversal |
| Ref validation | Only `[a-zA-Z0-9._/\-]` allowed; prevents injection |
| Zip Slip protection | Each extracted path is verified to remain within the target directory |
| Path safety check | `_validate_path_safety()` ensures the destination is inside `plugins_dir` |

---

### `config.py` — Plugin Configuration Utilities

Reads and writes `PLUGINS_DIR/plugins.yaml`, persisting each plugin's configuration including its enabled/disabled state.

```yaml
fxtwitter:
  disabled: true

youtube_parser:
  disabled: false
  api_key: "xxx"
  quality: "high"
```

- `disabled` is a framework-reserved field (`_FRAMEWORK_KEYS`); all other fields are plugin-owned config
- **Atomic writes**: `tempfile.mkstemp` + `Path.replace`, executed inside `_config_lock` thread lock for concurrency safety

| Function | Description |
|----------|-------------|
| `load_plugins_config()` | Loads full config; returns `{}` if file is missing or malformed |
| `save_plugins_config(config)` | Atomically writes back to `plugins.yaml` |
| `get_plugin_config(domain)` | Returns a single plugin's config block |
| `set_plugin_field(domain, key, value)` | Sets a single field under lock and persists |
| `remove_plugin_config(domain)` | Removes a plugin's entire config block (called on plugin deletion) |
| `strip_framework_keys(cfg)` | Filters out framework-reserved keys |
| `plugin_get_config(domain, schema_cls)` | Fetches config and deserializes into a `PluginConfigSchema` subclass instance |
| `plugin_save_config(domain, config)` | Serializes a `PluginConfigSchema` instance and atomically writes it |

---

### `startup.py` — Startup and Shutdown

#### `load_plugins_on_startup()`

```
1. Create PluginContext and PluginManager; inject HA-style methods
2. async_discover()        concurrently scans the local plugins/ directory
3. async_check_updates()   lightweight remote version check; logs available updates (no auto-install)
4. Load plugins.yaml
5. For each plugin:
   ├── [disabled: true] → state = DISABLED, skip
   └── async_setup(config) + async_setup_entry
6. Summary log: X/Y enabled
```

#### `shutdown_plugins()`

Iterates all active entries and calls `async_unload_entry` on each to release resources.

---

### `services/plugin.py` — Plugin Management Service Layer

Encapsulates plugin management operations for the HTTP router layer.

| Method | Description |
|--------|-------------|
| `list_plugins()` | Returns state, version, errors, and update availability for all discovered plugins |
| `list_available()` | Fetches remote manifest, merges with local install state, returns all available plugins |
| `check_updates()` | Queries remote versions; returns current vs. latest for each plugin |
| `update_plugins(domains)` | Downloads and installs/updates plugins; hot-reloads existing ones, activates new ones |
| `enable(domain)` | Clears disabled flag, dynamically loads and activates the plugin |
| `disable(domain)` | Unloads plugin and writes `disabled: true` to `plugins.yaml` |
| `delete(domain)` | Unloads + removes from registry + deletes from disk + cleans up `plugins.yaml` |
| `reload_all()` | Hot-reloads all plugins |
| `get_plugin_settings(domain)` | Reads `CONFIG_SCHEMA`; returns field list and current config values |
| `update_plugin_settings(domain, body)` | Validates and persists plugin config (supports partial updates with strict type checking) |

**`update_plugin_settings` validation rules**:
- Framework-reserved keys (e.g. `disabled`) are rejected with HTTP 400
- Undeclared keys are silently ignored
- Declared keys are type-checked with `strict=True`
- True partial updates are supported — only supplied fields are validated

---

## HTTP Management API

All endpoints require admin privileges (Bearer Token). Route prefix: `/v1/plugins`.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/plugins/` | List all locally discovered plugins and their state |
| `GET` | `/v1/plugins/available` | List all plugins available in the remote repository (including uninstalled) |
| `POST` | `/v1/plugins/reload` | Hot-reload all plugins |
| `POST` | `/v1/plugins/check-config` | Validate all plugin manifests for required fields |
| `GET` | `/v1/plugins/check-updates` | Check whether newer versions are available |
| `POST` | `/v1/plugins/update` | Download and install/update plugins from the remote repository |
| `POST` | `/v1/plugins/{domain}/enable` | Enable a plugin |
| `POST` | `/v1/plugins/{domain}/disable` | Disable a plugin |
| `DELETE` | `/v1/plugins/{domain}` | Delete a plugin (unload + remove files) |
| `GET` | `/v1/plugins/{domain}/config` | Get plugin config schema and current values |
| `PUT` | `/v1/plugins/{domain}/config` | Update plugin config fields |

---

## End-to-End Flows

### URL Parse Flow

```
POST /v1/task/parser { "url": "..." }
  │
  └── task_service.create_parser_task()
      ├── Look for a running PRIMARY task for this URL
      │   ├── None found       → create PRIMARY, enqueue for execution
      │   ├── Found, same user → return existing task
      │   └── Found, diff user → create LINKED (waits for PRIMARY to finish)
      │
      └── task_queue.enqueue(task.id)  [async execution]
          │
          └── content_service.parser_content(url)
              ├── manager.call_service(domain, "can_parse", {"url": url})
              └── manager.call_service(domain, "parse", {"url": url}) → ParserResult
```

### Online Update Flow

```
POST /v1/plugins/update
  │
  └── PluginService.update_plugins(domains)
      ├── GitHubPluginDownloader.download_plugins()
      │   ├── Download GitHub zip archive
      │   ├── Safely extract (Zip Slip protection)
      │   └── Overwrite plugin directories per plugins-manifest.json
      │
      ├── Existing plugin → manager.async_reload(domain)
      │   ├── async_unload_entry
      │   ├── Clear sys.modules cache
      │   └── Re-run async_setup + async_setup_entry
      │
      └── New plugin → manager.async_activate(domain)
          └── discover → setup → setup_entry
```

---

## Design Principles

1. **Module-level loading** — plugins are loaded as Python modules via `importlib`, not as class instances; platform submodules are registered independently
2. **Strict state machine** — all transitions go through `PluginManager`; invalid operations are blocked and error states are recoverable
3. **Home Assistant-style architecture** — `async_forward_entry_setup` / `async_unload_platforms` pattern decouples plugins from platforms for easy horizontal extension
4. **Secure remote distribution** — multi-layer protection: domain validation, ref sanitization, Zip Slip prevention, and path boundary checks
5. **Zero-downtime hot reload** — fully clears the module cache (including all submodule entries in `sys.modules`) before re-importing
6. **Lightweight version checks** — at startup, only the remote `plugins-manifest.json` (a few KB) is fetched; no full package download
7. **Atomic config writes** — `tempfile` + `rename` + thread lock prevents config corruption from interrupted writes
8. **Type-driven config schema** — `CONFIG_SCHEMA` drives config read, write, validation, and API exposure; no extra boilerplate needed in plugins
9. **Stable interface contract** — plugins depend only on `contenthive.plugins.*`; core refactors do not break existing plugins
