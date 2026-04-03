"""
Plugin management service.
"""

from datetime import datetime, timezone

from contenthive.config import settings
from contenthive.logger import logger
from contenthive.models.api import OperationResult
from contenthive.models.enumerates import OperationType
from contenthive.models.plugin import (
    AvailablePluginInfo,
    AvailablePluginsResponse,
    CheckConfigResponse,
    CheckUpdatesResponse,
    PluginInfo,
    PluginListResponse,
    PluginUpdateInfo,
    ReloadResponse,
    UpdatePluginsResponse,
)
from contenthive.plugins.config import get_plugin_config, set_plugin_field
from contenthive.plugins.downloader import GitHubPluginDownloader
from contenthive.plugins.manager import PluginEntryData, PluginManager, get_plugin_manager
from contenthive.plugins.registry import PluginState


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
            plugins_info[domain] = PluginUpdateInfo(
                current_version=record.version,
                latest_version=latest,
                update_available=latest is not None,
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

        downloader = GitHubPluginDownloader()
        try:
            download_results = await downloader.download_plugins(
                repo_url=settings.plugins_repo_url,
                ref=settings.plugins_repo_ref,
                ref_type=settings.plugins_repo_ref_type,
                selected_plugins=selected,
                force_reinstall=True,
            )
        finally:
            downloader.cleanup_temp()

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
                    else:
                        failed.append(domain)
                else:
                    # New plugin: discover → setup → enable
                    success = await plugin_manager.async_activate(domain)
                    if success:
                        updated.append(domain)
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

        Raises:
            Exception: If the remote manifest cannot be fetched.
        """
        plugin_manager = get_plugin_manager()

        downloader = GitHubPluginDownloader()
        remote_manifest = await downloader.fetch_remote_manifest(
            repo_url=settings.plugins_repo_url,
            ref=settings.plugins_repo_ref,
        )
        if remote_manifest is None:
            raise Exception("Failed to fetch remote plugins manifest")

        installed = {domain: record for domain, record in plugin_manager.plugins.items()} if plugin_manager else {}

        result: list[AvailablePluginInfo] = []
        for plugin in remote_manifest.get("plugins", []):
            domain = plugin.get("domain")
            if not domain:
                continue
            local = installed.get(domain)
            result.append(AvailablePluginInfo(
                domain=domain,
                name=plugin.get("name", domain),
                version=plugin.get("version", ""),
                description=plugin.get("description"),
                author=plugin.get("author"),
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
            set_plugin_field(domain, "disabled", False)
            return OperationResult(operation=OperationType.ENABLE, id=domain, success=True, message=f"Plugin '{domain}' is already enabled")

        set_plugin_field(domain, "disabled", False)

        if not await plugin_manager.async_setup(domain):
            raise RuntimeError(f"Plugin '{domain}' setup failed")
        
        plugin_cfg = get_plugin_config(domain)
        config = {k: v for k, v in plugin_cfg.items() if k != "disabled"}
        entry = PluginEntryData(entry_id=entry_id, domain=domain, data=config)
        if not await plugin_manager.async_setup_entry(entry):
            raise RuntimeError(f"Plugin '{domain}' enable failed")

        return OperationResult(operation=OperationType.ENABLE, id=domain, success=True, message=f"Plugin '{domain}' enabled")


plugin_service = PluginService()
