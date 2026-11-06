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
 catalog.py +                config.py
 GitHubPluginDownloader      (plugins.yaml read/write,
 (reads the plugin catalog,   persists plugin config)
  installs GitHub Releases)

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
                              │            ▲                  │
                              │            └─ async_unload_entry
                              │               (module stays loaded)
                              ▼
                           DISABLED ── enable: async_setup + async_setup_entry ──> ENABLED

FAILED  (setup or runtime error)
```

| State | Meaning | Module loaded |
|-------|---------|---------------|
| `INSTALLED` | `manifest.json` loaded; module not yet imported | No |
| `LOADED` | Module imported, dependencies installed; no active config entry | Yes |
| `ENABLED` | Config entry active; plugin is running | Yes |
| `DISABLED` | Marked `disabled: true`. Module is loaded after setup; no config entry is activated | Yes |
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
| `async_setup(domain)` | Installs dependencies and imports the module → writes missing schema defaults → calls `async_setup(context)` → state=LOADED |
| `async_setup_entry(entry)` | Calls the plugin's `async_setup_entry(context, entry)` → stores entry → state=ENABLED |
| `async_forward_entry_setup(entry, platform)` | Loads the platform submodule (e.g. `parser.py`), injects it into `sys.modules` as `contenthive_plugin_{domain}.{platform}`, calls the platform's `async_setup_entry` |
| `async_unload_entry(entry_id)` | Calls the plugin's `async_unload_entry` → removes entry → state reverts to LOADED if no other active entries remain |
| `async_delete(domain)` | Unloads all entries → removes from registry → deletes the plugin directory from disk. Aborts before dropping the module or deleting the directory if unload fails |
| `async_reload(domain)` | Unloads → clears `sys.modules` cache → resets to INSTALLED → re-runs setup, then `setup_entry` with data reloaded from `plugins.yaml`. Aborts before clearing the module if unload fails |
| `async_reload_domain(domain)` | Reloads one in-memory plugin. DISABLED is set up again and left DISABLED even if setup fails, with no entry. Otherwise a missing entry gets a default entry from the saved config |
| `async_discover_domain(domain)` | Reads one installed plugin's `manifest.json` and registers it as INSTALLED. Does not set up the module |
| `unload_disabled_module(domain)` | Drops the imported module and re-reads the manifest. State stays DISABLED; setup is not run |
| `async_check_updates(catalog=None)` | Fetches only the plugin catalog, picks each plugin's release on its track (stable or beta), compares versions, caches update offers (including `release_notes`) |
| `has_installed_plugin_updates()` | Whether any installed plugin is behind the catalog version on its track. Health `plugin_updates_available` reflects only this; uninstalled plugins are listed via `/v1/plugins/available` |
| `register_service(domain, service, callback)` | Registers a named service callable |
| `call_service(domain, service, data)` | Calls a registered service |

**Hot-reload implementation** (`async_reload`):

```
1. async_unload_entry  (unload all active entries). Returns false if any unload fails, without clearing the module
2. Clear sys.modules entries for plugin_{domain} and contenthive_plugin_{domain}.*
3. Reset PluginRecord state to INSTALLED
4. async_setup
5. Refresh each entry's data from plugins.yaml (framework keys removed) and async_setup_entry.
   One entry failure does not skip the remaining entries. Returns false if setup or any entry fails.
```

---

### `catalog.py` — Plugin Catalog Client

Reads the plugin catalog published by [content-hive/plugins](https://github.com/content-hive/plugins) at the built-in `CATALOG_URL` (`https://content-hive.github.io/plugins/catalog.json`). The catalog lists every plugin repository with its latest stable and pre-release GitHub Releases.

```python
async fetch_catalog() -> dict[str, CatalogPlugin]   # keyed by domain; raises CatalogError
CatalogPlugin.select_release(prerelease: bool) -> CatalogRelease | None
```

- Only catalog `schema` 1 is accepted
- Malformed entries and duplicate domains are skipped with a warning
- Plugins whose `min_core_version` is newer than the running Content Hive are skipped
- `select_release(False)` returns `stable`; `select_release(True)` returns `beta` when present, otherwise `stable`

---

### `downloader.py` — GitHub Plugin Downloader

`GitHubPluginDownloader` safely downloads, extracts, and installs a single plugin release from the plugin's own GitHub repository.

**Plugin repository format**: the plugin code lives in `plugin/` at the release tag; `plugin/manifest.json` declares the same `domain` as the catalog and the release `version`; `contenthive.json` at the tag root declares the minimum Content Hive version for that release.

```python
async install_release(
    plugin: CatalogPlugin,
    release: CatalogRelease,
    force_reinstall: bool = True,
) -> bool
```

Downloads `https://github.com/{owner}/{repo}/archive/refs/tags/{tag}.zip`, extracts it, checks `contenthive.json` and `plugin/manifest.json`, and copies `plugin/` to `PLUGINS_DIR/{domain}`.

**Security measures**:

| Mechanism | Description |
|-----------|-------------|
| Domain validation | Only `[a-z0-9_-]` allowed; prevents path traversal |
| Repository and tag validation | Repository must be `owner/repo`; tag only allows `[a-zA-Z0-9._/\-]`; prevents injection |
| Manifest check | `plugin/manifest.json` must match the catalog domain and release version |
| Core compatibility | The selected tag's `contenthive.json` must not require a newer Content Hive than is running |
| Zip Slip protection | Each extracted path is verified to remain within the target directory |
| Path safety check | `_validate_path_safety()` ensures the destination is inside `plugins_dir` |

---

### `config.py` — Plugin Configuration Utilities

Reads and writes `PLUGINS_DIR/plugins.yaml`, persisting each plugin's configuration including its enabled/disabled state and release track.

```yaml
fxtwitter:
  disabled: true

youtube_parser:
  disabled: false
  prerelease: true
  api_key: "xxx"
  quality: "high"
```

- `disabled` and `prerelease` are framework-reserved fields (`FRAMEWORK_KEYS`); all other fields are plugin-owned config
- `prerelease: true` makes the plugin install and update to beta releases; it can be set before the plugin is installed. Deleting the plugin removes the whole config block, including `prerelease`
- **Atomic writes**: `tempfile.mkstemp` + `Path.replace`, executed inside `_config_lock` thread lock for concurrency safety

| Function | Description |
|----------|-------------|
| `load_plugins_config()` | Loads full config; returns `{}` if file is missing or malformed |
| `save_plugins_config(config)` | Atomically writes back to `plugins.yaml` |
| `get_plugin_config(domain)` | Returns a single plugin's config block |
| `set_plugin_field(domain, key, value)` | Sets a single field under lock and persists |
| `remove_plugin_config(domain)` | Removes a plugin's entire config block, including `prerelease` (called on plugin deletion) |
| `get_prerelease_domains()` | Returns domains that track pre-release versions |
| `strip_framework_keys(cfg)` | Filters out framework-reserved keys |
| `plugin_entry_data(domain)` | Saved settings for a config entry, without framework keys |
| `plugin_get_config(domain, schema_cls)` | Fetches config and deserializes into a `PluginConfigSchema` subclass instance |
| `plugin_save_config(domain, config)` | Serializes a `PluginConfigSchema` instance and atomically writes it |

---

### `startup.py` — Startup and Shutdown

#### `load_plugins_on_startup()`

```
1. Create PluginContext and PluginManager; inject HA-style methods
2. async_discover()        concurrently scans the local plugins/ directory
3. async_check_updates()   lightweight catalog check; logs available updates (no auto-install)
4. Load plugins.yaml
5. For each plugin:
   ├── async_setup
   ├── [setup failed] → state stays FAILED
   ├── [disabled: true] → state = DISABLED, module stays loaded, no entry
   └── async_setup_entry
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
| `list_available()` | Fetches the catalog, merges with local install state and release tracks, returns all catalog plugins |
| `check_updates()` | Queries catalog versions on each plugin's track; returns current vs. latest for each plugin |
| `update_plugins(domains)` | Installs or updates plugins from their GitHub Releases, then reloads each one. A disabled plugin stays disabled. A new plugin is registered from its manifest first |
| `set_prerelease(domain, enabled)` | Writes `prerelease` to `plugins.yaml` and refreshes cached update offers |
| `enable(domain)` | Clears disabled flag, dynamically loads and activates the plugin |
| `disable(domain)` | Unloads entries and writes `disabled: true`. The module stays loaded. State stays DISABLED. Aborts without changing the disabled state or dropping the module if unload fails |
| `delete(domain)` | Unloads the module + removes from registry + deletes from disk + removes the whole `plugins.yaml` block, including `prerelease`. Aborts without dropping the module or deleting the directory if unload fails |
| `reload_all()` | Reloads every plugin. A disabled plugin is set up again, left DISABLED even if setup fails, with no entry, and reported as `disabled` |
| `reload(domain)` | Reloads one plugin. Memory state DISABLED stays DISABLED even if setup fails, creates no entry, and returns 409 `PLUGIN_NOT_ENABLED`. Existing entries reload with the saved config. A plugin with no entry gets a default entry from the saved config. An unload failure aborts before dropping the module. Failure returns 500 `PLUGIN_RELOAD_FAILED` |
| `get_plugin_settings(domain)` | Reads `CONFIG_SCHEMA`; returns field list and current config values |
| `update_plugin_settings(domain, body)` | Validates and persists plugin config (supports partial updates with strict type checking) |

**`update_plugin_settings` validation rules**:
- Framework-reserved keys (`disabled`, `prerelease`) are rejected with HTTP 400
- Undeclared keys are silently ignored
- Declared keys are type-checked with `strict=True`
- True partial updates are supported — only supplied fields are validated

---

## HTTP Management API

All endpoints require admin privileges (Bearer Token). Route prefix: `/v1/plugins`.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/plugins/` | List all locally discovered plugins and their state |
| `GET` | `/v1/plugins/available` | List all plugins in the plugin catalog (including uninstalled), with `prerelease` and `installable` |
| `POST` | `/v1/plugins/reload` | Hot-reload all plugins |
| `POST` | `/v1/plugins/{domain}/reload` | Hot-reload one plugin. A disabled plugin returns 409 `PLUGIN_NOT_ENABLED`; a failed reload returns 500 `PLUGIN_RELOAD_FAILED` |
| `POST` | `/v1/plugins/check-config` | Validate all plugin manifests for required fields |
| `GET` | `/v1/plugins/check-updates` | Check whether newer versions are available |
| `POST` | `/v1/plugins/update` | Install/update plugins from their GitHub Releases |
| `PUT` | `/v1/plugins/{domain}/prerelease` | Body `{ "enabled": true }`. Response is `{ "domain", "prerelease" }` with the stored choice. The plugin does not need to be installed |
| `POST` | `/v1/plugins/{domain}/enable` | Enable a plugin |
| `POST` | `/v1/plugins/{domain}/disable` | Disable a plugin |
| `GET` | `/v1/plugins/{domain}` | Get one installed plugin's status. The response includes `domain` and the same status fields as the list: `state`, `version`, `name`, `error`, `update_available`, `description`, `author`, `prerelease`. Returns 404 `PLUGIN_NOT_FOUND` when it is not installed |
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
      ├── fetch_catalog() + plugins.yaml prerelease → release per plugin
      ├── GitHubPluginDownloader.install_release()  (per plugin)
      │   ├── Download the tag's zip from the plugin repository
      │   ├── Safely extract (Zip Slip protection)
      │   ├── Check plugin/manifest.json domain and version
      │   └── Copy plugin/ to PLUGINS_DIR/{domain}
      │
      ├── Existing or newly registered plugin → manager.async_reload_domain(domain)
      │   ├── Memory state DISABLED → async_setup, stay DISABLED even if setup fails, no entry
      │   └── Otherwise → async_reload; create a default entry when none exists
      │
      └── New plugin, before reload → async_discover_domain(domain)
          └── Copy plugins.yaml disabled into memory, then async_reload_domain
```

---

## Design Principles

1. **Module-level loading** — plugins are loaded as Python modules via `importlib`, not as class instances; platform submodules are registered independently
2. **Strict state machine** — all transitions go through `PluginManager`; invalid operations are blocked and error states are recoverable
3. **Home Assistant-style architecture** — `async_forward_entry_setup` / `async_unload_platforms` pattern decouples plugins from platforms for easy horizontal extension
4. **Secure remote distribution** — multi-layer protection: domain validation, repository and tag sanitization, manifest checks, Zip Slip prevention, and path boundary checks
5. **Zero-downtime hot reload** — fully clears the module cache (including all submodule entries in `sys.modules`) before re-importing
6. **Lightweight version checks** — at startup, only the plugin catalog (a few KB) is fetched; no plugin archive download
7. **Atomic config writes** — `tempfile` + `rename` + thread lock prevents config corruption from interrupted writes
8. **Type-driven config schema** — `CONFIG_SCHEMA` drives config read, write, validation, and API exposure; no extra boilerplate needed in plugins
9. **Stable interface contract** — plugins depend only on `contenthive.plugins.*`; core refactors do not break existing plugins
