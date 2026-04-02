"""
Plugin management service.
"""

from datetime import datetime

from contenthive.config import settings
from contenthive.logger import logger
from contenthive.models.system import (
    CheckConfigResponse,
    CheckUpdatesResponse,
    HealthPluginInfo,
    HealthResponse,
    PluginUpdateInfo,
    ReloadResponse,
    UpdatePluginsResponse,
)
from contenthive.plugins.manager import PluginManager, get_plugin_manager
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
        from contenthive.plugins.downloader import GitHubPluginDownloader

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

    def get_health(self) -> HealthResponse:
        plugin_manager = get_plugin_manager()

        plugin_status: dict[str, HealthPluginInfo] = {}
        if plugin_manager:
            for domain, record in plugin_manager.plugins.items():
                plugin_status[domain] = HealthPluginInfo(
                    state=record.state.value,
                    version=record.version,
                    name=record.name,
                    error=record.error if record.state == PluginState.FAILED else None,
                    update_available=plugin_manager._available_updates.get(domain),
                )

        return HealthResponse(
            app=settings.app_name,
            version=settings.app_version,
            plugins=plugin_status,
        )


plugin_service = PluginService()
