"""
Plugin management service.
"""

from datetime import datetime

from contenthive.config import settings
from contenthive.logger import logger
from contenthive.models.api import OperationResult
from contenthive.models.enumerates import OperationType
from contenthive.models.plugin import (
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

    async def reload_all(self) -> ReloadResponse:
        plugin_manager = _get_plugin_manager()

        results: dict[str, str] = {}
        for domain in list(plugin_manager.plugins.keys()):
            try:
                success = await plugin_manager.async_reload(domain)
                results[domain] = "reloaded" if success else "failed"
            except Exception as e:
                results[domain] = f"error: {str(e)}"
                logger.error(f"Failed to reload {domain}: {e}")

        return ReloadResponse(message="Configuration reloaded", plugins=results)

    def check_config(self) -> CheckConfigResponse:
        plugin_manager = _get_plugin_manager()

        errors: list[str] = []
        warnings: list[str] = []

        for domain, record in plugin_manager.plugins.items():
            manifest = record.manifest

            for field in ("domain", "name", "version"):
                if field not in manifest:
                    errors.append(f"{domain}: Missing required field '{field}'")

            for dep in manifest.get("requirements", []):
                if dep not in plugin_manager.plugins:
                    warnings.append(f"{domain}: Dependency '{dep}' not found")

        is_valid = len(errors) == 0
        return CheckConfigResponse(
            valid=is_valid,
            errors=errors,
            warnings=warnings,
            message="Configuration is valid" if is_valid else "Configuration has errors",
        )

    async def check_updates(self) -> CheckUpdatesResponse:
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
            checked_at=plugin_manager._last_update_check or datetime.now(),
            plugins=plugins_info,
        )

    async def update_plugins(self, domains: list[str]) -> UpdatePluginsResponse:
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
                logger.error(f"Failed to activate plugin {domain} after update: {e}")
                failed.append(domain)

        return UpdatePluginsResponse(updated=updated, failed=failed)

    def list_plugins(self) -> PluginListResponse:
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
                    description=record.manifest.get("description"),
                    author=record.manifest.get("author"),
                    requirements=record.manifest.get("requirements"),
                )

        return PluginListResponse(plugins=plugin_status)


    async def disable(self, domain: str) -> OperationResult:
        plugin_manager = _get_plugin_manager()
        if domain not in plugin_manager.plugins:
            raise ValueError(f"Plugin '{domain}' not found")

        entry_id = f"{domain}_default"
        if entry_id in plugin_manager.config_entries:
            await plugin_manager.async_unload_entry(entry_id)

        plugin_manager.plugins[domain].state = PluginState.DISABLED
        set_plugin_field(domain, "disabled", True)

        return OperationResult(operation=OperationType.DISABLE, id=domain, success=True, message=f"Plugin '{domain}' disabled")

    async def enable(self, domain: str) -> OperationResult:
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
