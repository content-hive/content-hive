"""
Plugin management service.
"""

from datetime import UTC, datetime

from packaging.version import InvalidVersion
from pydantic import ValidationError

from contenthive.config import settings
from contenthive.core.setting_schema import schema_class_to_setting_items, validate_partial_config
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
    SetPrereleaseResponse,
    UpdatePluginConfigRequest,
    UpdatePluginConfigResponse,
    UpdatePluginsResponse,
)
from contenthive.plugins.catalog import DOMAIN_PATTERN, CatalogError, fetch_catalog
from contenthive.plugins.config import (
    FRAMEWORK_KEYS,
    PRERELEASE_KEY,
    get_prerelease_domains,
    plugin_get_config,
    plugin_save_config,
    remove_plugin_config,
    set_plugin_field,
)
from contenthive.plugins.downloader import GitHubPluginDownloader
from contenthive.plugins.manager import (
    PluginEntryData,
    PluginManager,
    get_plugin_manager,
    is_plugin_update_available,
)
from contenthive.plugins.registry import PluginState


class ConfigValidationError(Exception):
    """Raised when plugin config fails schema validation."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


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
                results[domain] = f"error: {e!s}"
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
        """Fetch the plugin catalog and compare versions.

        Performs a lightweight fetch (no archive download). Each plugin is compared
        against the release on its track (stable, or beta when prerelease is enabled).
        Results are cached on the PluginManager instance.

        Returns:
            CheckUpdatesResponse with per-plugin current/latest version,
            update_available flag, optional release_notes, plus the UTC timestamp.
        """
        plugin_manager = _get_plugin_manager()

        update_results = await plugin_manager.async_check_updates()

        plugins_info: dict[str, PluginUpdateInfo] = {}
        for domain, record in plugin_manager.plugins.items():
            offer = update_results.get(domain)
            latest = offer.latest_version if offer else None
            try:
                update_available = is_plugin_update_available(latest, record.version)
            except InvalidVersion:
                logger.warning(
                    "Plugin %s: invalid version string (local=%s, remote=%s)",
                    domain,
                    record.version,
                    latest,
                )
                update_available = False
            plugins_info[domain] = PluginUpdateInfo(
                current_version=record.version,
                latest_version=latest,
                update_available=update_available,
                release_notes=offer.release_notes if offer and update_available else None,
            )

        return CheckUpdatesResponse(
            checked_at=plugin_manager._last_update_check or datetime.now(UTC),
            plugins=plugins_info,
        )

    async def update_plugins(self, domains: list[str]) -> UpdatePluginsResponse:
        """Install or update plugins from their repositories' GitHub Releases.

        For each plugin, downloads the release on its track (stable, or beta when
        prerelease is enabled), installs its ``plugin/`` directory, and then either
        hot-reloads an existing plugin or activates a newly installed one.

        Args:
            domains: Plugin domains to install or update. An empty list means every
                     catalog plugin that has a release on its track.

        Returns:
            UpdatePluginsResponse with lists of successfully updated and failed domains.

        Raises:
            CatalogError: If the plugin catalog cannot be fetched.
        """
        plugin_manager = _get_plugin_manager()
        catalog = await fetch_catalog()
        prerelease_domains = get_prerelease_domains()
        downloader = GitHubPluginDownloader(settings.plugins_dir)

        updated: list[str] = []
        failed: list[str] = []

        for domain in dict.fromkeys(domains or catalog):
            plugin = catalog.get(domain)
            release = plugin.select_release(domain in prerelease_domains) if plugin else None
            if plugin is None or release is None:
                if domains:
                    logger.warning(f"Plugin {domain} has no installable release in the plugin catalog")
                    failed.append(domain)
                continue

            if not await downloader.install_release(plugin, release):
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
        """Fetch the plugin catalog and merge it with local installation state.

        Returns every catalog plugin supported by this core version, with the version
        on its release track and whether it is installed locally.

        Returns:
            AvailablePluginsResponse with a list of AvailablePluginInfo entries.

        Raises:
            CatalogError: If the plugin catalog cannot be fetched.
        """
        plugin_manager = get_plugin_manager()
        catalog = await fetch_catalog()
        prerelease_domains = get_prerelease_domains()
        installed = plugin_manager.plugins if plugin_manager else {}

        result: list[AvailablePluginInfo] = []
        for domain, plugin in catalog.items():
            prerelease = domain in prerelease_domains
            release = plugin.display_release(prerelease)
            local = installed.get(domain)
            result.append(
                AvailablePluginInfo(
                    domain=domain,
                    name=plugin.name,
                    version=release.version,
                    description=plugin.description,
                    disclaimer=plugin.disclaimer,
                    release_notes=release.release_notes,
                    repository=plugin.repository,
                    prerelease=prerelease,
                    installable=plugin.select_release(prerelease) is not None,
                    installed=local is not None,
                    installed_version=local.version if local else None,
                )
            )

        return AvailablePluginsResponse(plugins=result)

    async def set_prerelease(self, domain: str, enabled: bool) -> SetPrereleaseResponse:
        """Choose whether a plugin tracks pre-release (beta) versions.

        The choice is stored in plugins.yaml and may be set before the plugin is
        installed. Cached update offers are refreshed from the catalog when possible.

        Args:
            domain: Plugin domain identifier.
            enabled: True to track beta releases, False for stable only.

        Returns:
            SetPrereleaseResponse with the stored choice. The selected version is
            available from the catalog endpoints after the cached offers are refreshed.

        Raises:
            ValueError: If the domain is not a valid plugin domain.
        """
        if not DOMAIN_PATTERN.match(domain):
            raise ValueError(f"Invalid plugin domain '{domain}'")

        set_plugin_field(domain, PRERELEASE_KEY, enabled)

        try:
            catalog = await fetch_catalog()
        except CatalogError as e:
            logger.warning(f"Saved prerelease={enabled} for {domain}, but could not refresh the catalog: {e}")
        else:
            if plugin_manager := get_plugin_manager():
                await plugin_manager.async_check_updates(catalog)

        return SetPrereleaseResponse(domain=domain, prerelease=enabled)

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
            prerelease_domains = get_prerelease_domains()
            for domain, record in plugin_manager.plugins.items():
                plugin_status[domain] = PluginInfo(
                    state=record.state,
                    version=record.version,
                    name=record.name,
                    error=record.error if record.state == PluginState.FAILED else None,
                    update_available=(
                        offer.latest_version
                        if (offer := plugin_manager._available_updates.get(domain)) is not None
                        else None
                    ),
                    description=record.description,
                    author=record.author,
                    prerelease=domain in prerelease_domains,
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

        entries = [entry for entry in plugin_manager.config_entries.values() if entry.domain == domain]
        for entry in entries:
            await plugin_manager.async_unload_entry(entry.entry_id)

        plugin_manager.plugins[domain].state = PluginState.DISABLED
        set_plugin_field(domain, "disabled", True)

        return OperationResult(
            operation=OperationType.DISABLE,
            id=domain,
            success=True,
            message=f"Plugin '{domain}' disabled",
        )

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
                return OperationResult(
                    operation=OperationType.ENABLE,
                    id=domain,
                    success=True,
                    message=f"Plugin '{domain}' is already enabled",
                )

        set_plugin_field(domain, "disabled", False)

        if not await plugin_manager.async_setup(domain):
            raise RuntimeError(f"Plugin '{domain}' setup failed")

        entry = PluginEntryData(entry_id=entry_id, domain=domain, data={})
        if not await plugin_manager.async_setup_entry(entry):
            raise RuntimeError(f"Plugin '{domain}' enable failed")

        return OperationResult(
            operation=OperationType.ENABLE,
            id=domain,
            success=True,
            message=f"Plugin '{domain}' enabled",
        )

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

        return OperationResult(
            operation=OperationType.DELETE,
            id=domain,
            success=True,
            message=f"Plugin '{domain}' deleted",
        )

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
                [
                    f"Persisted config is invalid: {err['loc'][0] if err['loc'] else 'root'}: {err['msg']}"
                    for err in e.errors()
                ]
            ) from e
        return PluginConfigResponse(
            domain=domain,
            settings=schema_class_to_setting_items(schema_cls, config_obj),
        )

    def update_plugin_settings(self, domain: str, body: UpdatePluginConfigRequest) -> UpdatePluginConfigResponse:
        """Validate and persist plugin config fields declared in CONFIG_SCHEMA.

        If the plugin has no CONFIG_SCHEMA, all incoming keys are ignored and an
        empty settings list is returned.

        Validation rules (when schema exists):
        - Framework-reserved keys ('disabled', 'prerelease') are rejected with 400.
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
                [
                    f"Persisted config is invalid: {err['loc'][0] if err['loc'] else 'root'}: {err['msg']}"
                    for err in e.errors()
                ]
            ) from e
        errors = validate_partial_config(
            schema_cls, body.config, stored=current.model_dump(), reserved_keys=FRAMEWORK_KEYS
        )
        if errors:
            raise ConfigValidationError(errors)

        # Apply partial update over current config, then persist atomically
        partial = {k: v for k, v in body.config.items() if k in declared_keys}
        updated = schema_cls.model_validate({**current.model_dump(), **partial})
        plugin_save_config(domain, updated)

        return UpdatePluginConfigResponse(
            domain=domain,
            settings=schema_class_to_setting_items(schema_cls, updated),
        )


plugin_service = PluginService()
