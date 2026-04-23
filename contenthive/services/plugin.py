"""
Plugin management service.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import TypeAdapter, ValidationError

from contenthive.config import settings
from contenthive.logger import logger
from contenthive.models.api import OperationResult
from contenthive.models.enumerates import OperationType
from contenthive.models.plugin import (
    AvailablePluginInfo,
    AvailablePluginsResponse,
    CheckConfigResponse,
    CheckUpdatesResponse,
    PluginConfigResponse,
    PluginInfo,
    PluginListResponse,
    PluginUpdateInfo,
    ReloadResponse,
    SettingFieldType,
    SettingItem,
    UpdatePluginConfigRequest,
    UpdatePluginConfigResponse,
    UpdatePluginsResponse,
)
from contenthive.plugins.config import FRAMEWORK_KEYS, plugin_get_config, plugin_save_config, remove_plugin_config, set_plugin_field
from contenthive.plugins.contracts import PluginConfigSchema
from contenthive.plugins.downloader import GitHubPluginDownloader
from packaging.version import InvalidVersion
from contenthive.plugins.manager import PluginEntryData, PluginManager, get_plugin_manager, is_plugin_update_available
from contenthive.plugins.registry import PluginState

_PYTHON_TYPE_TO_FIELD_TYPE: dict[type, SettingFieldType] = {
    str: SettingFieldType.STRING,
    int: SettingFieldType.INTEGER,
    float: SettingFieldType.FLOAT,
    bool: SettingFieldType.BOOLEAN,
}


class ConfigValidationError(Exception):
    """Raised when plugin config fails schema validation."""
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def _schema_class_to_setting_items(schema_cls: type, config_obj: PluginConfigSchema) -> list[SettingItem]:
    """Convert a PluginConfigSchema class + current config object into SettingItem list."""
    items: list[SettingItem] = []
    for field_name, field_info in schema_cls.model_fields.items():
        annotation = field_info.annotation

        # Determine type and options
        if isinstance(annotation, type) and issubclass(annotation, Enum):
            field_type = SettingFieldType.ENUM
            options = [e.value for e in annotation]
        else:
            field_type = _PYTHON_TYPE_TO_FIELD_TYPE.get(annotation, SettingFieldType.STRING)
            options = None

        # label: use title if set, fallback to field name
        label = field_info.title or field_name

        # secret: from json_schema_extra
        extra = field_info.json_schema_extra or {}
        secret = bool(extra.get("secret", False))

        required = field_info.is_required()

        # default value: None for required fields or factory-based defaults
        default = None if required or field_info.default_factory is not None else field_info.default
        if isinstance(default, Enum):
            default = default.value

        # Current value from config object
        raw_value = getattr(config_obj, field_name, None)
        if isinstance(raw_value, Enum):
            raw_value = raw_value.value

        items.append(SettingItem(
            key=field_name,
            type=field_type,
            label=label,
            description=field_info.description,
            required=required,
            secret=secret,
            default=default,
            options=options,
            value=raw_value,
        ))
    return items


def _validate_partial_config(
    schema_cls: type,
    incoming: dict[str, Any],
    stored: dict[str, Any] | None = None,
) -> list[str]:
    """
    Validate a partial config dict against a PluginConfigSchema class.

    Rules:
    - Framework-reserved keys are always rejected.
    - Keys not declared in the schema are silently ignored (not validated).
    - Declared keys present in `incoming` are type-checked with strict=True.
    - Required fields must be present in `incoming` OR already covered by `stored`
      (the currently persisted config). This allows true partial updates where only
      a subset of fields is sent.

    Args:
        schema_cls: The PluginConfigSchema subclass to validate against.
        incoming: The raw dict from the request body.
        stored: Optional dict of the currently persisted config values. When
            provided, required fields already present there are not re-required
            in `incoming`.

    Returns a list of error strings. Empty list means valid.
    """
    errors: list[str] = []

    # 1. Reject framework-reserved keys
    for key in incoming:
        if key in FRAMEWORK_KEYS:
            errors.append(f"Key '{key}' is reserved by the framework and cannot be set via API")

    declared_fields = schema_cls.model_fields

    # 2. Type-check declared keys that are present in incoming
    for key, value in incoming.items():
        if key in FRAMEWORK_KEYS or key not in declared_fields:
            continue
        field_info = declared_fields[key]
        annotation = field_info.annotation
        if isinstance(annotation, type) and issubclass(annotation, Enum):
            # Enum: check that value is a string matching one of the enum member values
            valid_values = [e.value for e in annotation]
            if value not in valid_values:
                errors.append(
                    f"Key '{key}': '{value}' is not a valid option, must be one of {valid_values}"
                )
        else:
            try:
                TypeAdapter(annotation).validate_python(value, strict=True)
            except Exception:
                expected = getattr(annotation, '__name__', str(annotation))
                actual = type(value).__name__
                errors.append(f"Key '{key}': expected {expected}, got {actual} ({value!r})")

    # 3. Check required fields: satisfied when present in incoming OR in stored config
    satisfied = {k for k in incoming if k in declared_fields}
    if stored:
        satisfied |= {k for k in stored if k in declared_fields}
    for field_name, field_info in declared_fields.items():
        if field_info.is_required() and field_name not in satisfied:
            errors.append(f"Required field '{field_name}' is missing")

    return errors


def _get_plugin_manager() -> PluginManager:
    plugin_manager = get_plugin_manager()
    if not plugin_manager:
        raise RuntimeError("Plugin manager not initialized")
    return plugin_manager


class PluginService:
    """Service layer for plugin lifecycle management.

    Wraps PluginManager operations and exposes them as high-level methods
    consumed by the HTTP router layer. All state mutations go through this
    service to keep routing code free of business logic.
    """

    async def reload_all(self) -> ReloadResponse:
        """Hot-reload all discovered plugins without restarting the application.

        Each plugin is unloaded, its module cache cleared, and then re-setup
        and re-enabled. Failures are captured per-domain and do not abort the
        remaining reloads.

        Returns:
            ReloadResponse with per-domain reload outcome ("reloaded" / "failed" / "error: ...").
        """
        plugin_manager = _get_plugin_manager()

        results: dict[str, str] = {}
        for domain in list(plugin_manager.plugins.keys()):
            try:
                success = await plugin_manager.async_reload(domain)
                results[domain] = "reloaded" if success else "failed"
            except Exception as e:
                results[domain] = f"error: {str(e)}"
                logger.exception(f"Failed to reload {domain}: {e}")

        return ReloadResponse(message="Configuration reloaded", plugins=results)

    def check_config(self) -> CheckConfigResponse:
        """Validate manifest fields for all discovered plugins.

        Checks that each plugin manifest contains the required fields
        (domain, name, version). Does not perform network calls or load modules.

        Returns:
            CheckConfigResponse with validation status, error list, and warning list.
        """
        plugin_manager = _get_plugin_manager()

        errors: list[str] = []
        warnings: list[str] = []

        for domain, record in plugin_manager.plugins.items():
            manifest = record.manifest

            for field in ("domain", "name", "version"):
                if field not in manifest:
                    errors.append(f"{domain}: Missing required field '{field}'")

        is_valid = len(errors) == 0
        return CheckConfigResponse(
            valid=is_valid,
            errors=errors,
            warnings=warnings,
            message="Configuration is valid" if is_valid else "Configuration has errors",
        )

    async def check_updates(self) -> CheckUpdatesResponse:
        """Fetch the remote plugins-manifest.json and compare versions.

        Performs a lightweight fetch (no full download) against the configured
        GitHub repository. Results are cached on the PluginManager instance.

        Returns:
            CheckUpdatesResponse with per-plugin current/latest version and
            update_available flag, plus the UTC timestamp of the check.
        """
        plugin_manager = _get_plugin_manager()

        update_results = await plugin_manager.async_check_updates(
            repo_url=settings.plugins_repo_url,
            ref=settings.plugins_repo_ref,
        )

        plugins_info: dict[str, PluginUpdateInfo] = {}
        for domain, record in plugin_manager.plugins.items():
            latest = update_results.get(domain)
            try:
                update_available = is_plugin_update_available(latest, record.version)
            except InvalidVersion:
                logger.warning(
                    "Plugin %s: invalid version string (local=%s, remote=%s)",
                    domain, record.version, latest,
                )
                update_available = False
            plugins_info[domain] = PluginUpdateInfo(
                current_version=record.version,
                latest_version=latest,
                update_available=update_available,
            )

        return CheckUpdatesResponse(
            checked_at=plugin_manager._last_update_check or datetime.now(timezone.utc),
            plugins=plugins_info,
        )

    async def update_plugins(self, domains: list[str]) -> UpdatePluginsResponse:
        """Download and install plugins from the remote repository.

        Downloads the repository archive, extracts the selected plugins, and
        then either hot-reloads existing plugins or activates newly installed ones.

        Args:
            domains: Plugin domains to update. An empty list updates all enabled
                     plugins listed in the remote plugins-manifest.json.

        Returns:
            UpdatePluginsResponse with lists of successfully updated and failed domains.
        """
        plugin_manager = _get_plugin_manager()
        selected = domains if domains else None

        downloader = GitHubPluginDownloader(settings.plugins_dir)
        download_results = await downloader.download_plugins(
            repo_url=settings.plugins_repo_url,
            ref=settings.plugins_repo_ref,
            ref_type=settings.plugins_repo_ref_type,
            selected_plugins=selected,
            force_reinstall=True,
        )

        updated: list[str] = []
        failed: list[str] = []

        for domain, success in download_results.items():
            if not success:
                failed.append(domain)
                continue

            try:
                if domain in plugin_manager.plugins:
                    # Existing plugin: reload to pick up new files
                    reloaded = await plugin_manager.async_reload(domain)
                    if reloaded:
                        updated.append(domain)
                        plugin_manager._available_updates.pop(domain, None)
                    else:
                        failed.append(domain)
                else:
                    # New plugin: discover → setup → enable
                    activated = await plugin_manager.async_activate(domain)
                    if activated:
                        updated.append(domain)
                        plugin_manager._available_updates.pop(domain, None)
                    else:
                        failed.append(domain)
            except Exception as e:
                logger.exception(f"Failed to activate plugin {domain} after update: {e}")
                failed.append(domain)

        return UpdatePluginsResponse(updated=updated, failed=failed)

    async def list_available(self) -> AvailablePluginsResponse:
        """Fetch remote plugins-manifest.json and merge with local installation state.

        Returns all plugins known to the remote repository, annotated with
        whether each is installed locally and what version is installed.

        Returns:
            AvailablePluginsResponse with a list of AvailablePluginInfo entries,
            each carrying domain, name, version, description, author, installed
            flag, and installed_version (None if not installed locally).

        Raises:
            RuntimeError: If the remote manifest cannot be fetched.
        """
        plugin_manager = get_plugin_manager()

        downloader = GitHubPluginDownloader(settings.plugins_dir)
        remote_manifest = await downloader.fetch_remote_manifest(
            repo_url=settings.plugins_repo_url,
            ref=settings.plugins_repo_ref,
        )
        if remote_manifest is None:
            raise RuntimeError("Failed to fetch remote plugins manifest")

        installed = plugin_manager.plugins if plugin_manager else {}

        result: list[AvailablePluginInfo] = []
        for plugin in remote_manifest.get("plugins", []):
            domain = plugin.get("domain")
            version = plugin.get("version")
            if not domain or not version:
                continue
            local = installed.get(domain)
            result.append(AvailablePluginInfo(
                domain=domain,
                name=plugin.get("name", domain),
                version=version,
                description=plugin.get("description"),
                author=plugin.get("author"),
                disclaimer=plugin.get("disclaimer"),
                installed=local is not None,
                installed_version=local.version if local else None,
            ))

        return AvailablePluginsResponse(plugins=result)

    def list_plugins(self) -> PluginListResponse:
        """Return metadata and runtime state for all discovered plugins.

        Returns:
            PluginListResponse mapping each domain to a PluginInfo snapshot
            (state, version, name, description, author, error, update_available).
            Returns an empty dict if the plugin manager is not yet initialized.
        """
        plugin_manager = get_plugin_manager()

        plugin_status: dict[str, PluginInfo] = {}
        if plugin_manager:
            for domain, record in plugin_manager.plugins.items():
                plugin_status[domain] = PluginInfo(
                    state=record.state,
                    version=record.version,
                    name=record.name,
                    error=record.error if record.state == PluginState.FAILED else None,
                    update_available=plugin_manager._available_updates.get(domain),
                    description=record.description,
                    author=record.author,
                )

        return PluginListResponse(plugins=plugin_status)


    async def disable(self, domain: str) -> OperationResult:
        """Unload all active config entries for a plugin and mark it disabled.

        Persists ``disabled: true`` to plugins.yaml so the plugin is skipped
        on next application startup.

        Args:
            domain: Plugin domain identifier.

        Returns:
            OperationResult indicating success.

        Raises:
            ValueError: If the domain is not found.
        """
        plugin_manager = _get_plugin_manager()
        if domain not in plugin_manager.plugins:
            raise ValueError(f"Plugin '{domain}' not found")

        entries = [
            entry for entry in plugin_manager.config_entries.values()
            if entry.domain == domain
        ]
        for entry in entries:
            await plugin_manager.async_unload_entry(entry.entry_id)

        plugin_manager.plugins[domain].state = PluginState.DISABLED
        set_plugin_field(domain, "disabled", True)

        return OperationResult(operation=OperationType.DISABLE, id=domain, success=True, message=f"Plugin '{domain}' disabled")

    async def enable(self, domain: str) -> OperationResult:
        """Set up and activate a previously disabled plugin.

        Clears the ``disabled`` flag in plugins.yaml, runs async_setup, and
        creates a default config entry via async_setup_entry. If the plugin
        already has an active entry, returns success immediately.

        Args:
            domain: Plugin domain identifier.

        Returns:
            OperationResult indicating success.

        Raises:
            ValueError: If the domain is not found.
            RuntimeError: If setup or entry activation fails.
        """
        plugin_manager = _get_plugin_manager()
        if domain not in plugin_manager.plugins:
            raise ValueError(f"Plugin '{domain}' not found")

        entry_id = f"{domain}_default"
        if entry_id in plugin_manager.config_entries:
            record = plugin_manager.plugins[domain]
            if record.state == PluginState.ENABLED:
                set_plugin_field(domain, "disabled", False)
                return OperationResult(operation=OperationType.ENABLE, id=domain, success=True, message=f"Plugin '{domain}' is already enabled")

        set_plugin_field(domain, "disabled", False)

        if not await plugin_manager.async_setup(domain):
            raise RuntimeError(f"Plugin '{domain}' setup failed")
        
        entry = PluginEntryData(entry_id=entry_id, domain=domain, data={})
        if not await plugin_manager.async_setup_entry(entry):
            raise RuntimeError(f"Plugin '{domain}' enable failed")

        return OperationResult(operation=OperationType.ENABLE, id=domain, success=True, message=f"Plugin '{domain}' enabled")

    async def delete(self, domain: str) -> OperationResult:
        """Unload, remove from registry, and delete the plugin directory from disk.

        Args:
            domain: Plugin domain identifier.

        Returns:
            OperationResult indicating success.

        Raises:
            ValueError: If the domain is not found.
            RuntimeError: If the plugin directory cannot be deleted.
        """
        plugin_manager = _get_plugin_manager()
        if domain not in plugin_manager.plugins:
            raise ValueError(f"Plugin '{domain}' not found")

        await plugin_manager.async_delete(domain)

        try:
            remove_plugin_config(domain)
        except Exception as e:
            raise RuntimeError(f"Plugin '{domain}' deleted but failed to update plugins.yaml: {e}") from e

        return OperationResult(operation=OperationType.DELETE, id=domain, success=True, message=f"Plugin '{domain}' deleted")


    def get_plugin_settings(self, domain: str) -> PluginConfigResponse:
        """Return the settings schema with current config values for a plugin.

        If the plugin has no CONFIG_SCHEMA, returns an empty settings list.

        Args:
            domain: Plugin domain identifier.

        Returns:
            PluginConfigResponse with schema fields and their current values.

        Raises:
            ValueError: If the domain is not found.
            RuntimeError: If the plugin manager is not initialized.
        """
        plugin_manager = _get_plugin_manager()
        if domain not in plugin_manager.plugins:
            raise ValueError(f"Plugin '{domain}' not found")

        record = plugin_manager.plugins[domain]
        schema_cls = record.config_schema
        if schema_cls is None:
            return PluginConfigResponse(domain=domain, settings=[])

        try:
            config_obj = plugin_get_config(domain, schema_cls)
        except ValidationError as e:
            raise ConfigValidationError(
                [f"Persisted config is invalid: {err['loc'][0] if err['loc'] else 'root'}: {err['msg']}" for err in e.errors()]
            ) from e
        return PluginConfigResponse(
            domain=domain,
            settings=_schema_class_to_setting_items(schema_cls, config_obj),
        )

    def update_plugin_settings(self, domain: str, body: UpdatePluginConfigRequest) -> UpdatePluginConfigResponse:
        """Validate and persist plugin config fields declared in CONFIG_SCHEMA.

        If the plugin has no CONFIG_SCHEMA, all incoming keys are ignored and an
        empty settings list is returned.

        Validation rules (when schema exists):
        - Framework-reserved keys ('disabled') are rejected with 400.
        - Keys not declared in the schema are silently ignored.
        - Type checking is performed with strict=True for each declared key.
        - Required fields must be present.

        Args:
            domain: Plugin domain identifier.
            body: UpdatePluginConfigRequest with config dict.

        Returns:
            UpdatePluginConfigResponse with settings list reflecting updated values.

        Raises:
            ValueError: If the domain is not found.
            ConfigValidationError: If validation fails.
            RuntimeError: If the plugin manager is not initialized.
        """
        plugin_manager = _get_plugin_manager()
        if domain not in plugin_manager.plugins:
            raise ValueError(f"Plugin '{domain}' not found")

        record = plugin_manager.plugins[domain]
        schema_cls = record.config_schema
        if schema_cls is None:
            return UpdatePluginConfigResponse(domain=domain, settings=[])

        # Load current config first so required-field validation can account for
        # values that are already persisted (enables true partial updates).
        declared_keys = set(schema_cls.model_fields)
        try:
            current = plugin_get_config(domain, schema_cls)
        except ValidationError as e:
            raise ConfigValidationError(
                [f"Persisted config is invalid: {err['loc'][0] if err['loc'] else 'root'}: {err['msg']}" for err in e.errors()]
            ) from e
        errors = _validate_partial_config(schema_cls, body.config, stored=current.model_dump())
        if errors:
            raise ConfigValidationError(errors)

        # Apply partial update over current config, then persist atomically
        partial = {k: v for k, v in body.config.items() if k in declared_keys}
        updated = schema_cls.model_validate({**current.model_dump(), **partial})
        plugin_save_config(domain, updated)

        return UpdatePluginConfigResponse(
            domain=domain,
            settings=_schema_class_to_setting_items(schema_cls, updated),
        )


plugin_service = PluginService()
