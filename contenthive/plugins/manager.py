import importlib
import importlib.metadata
import importlib.util
import inspect
import os
import shutil
import sys
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
import asyncio
import subprocess

from packaging.requirements import Requirement
from packaging.version import Version

from .registry import PluginRecord, PluginState
from contenthive.plugins.config import get_plugin_config
from contenthive.plugins.downloader import GitHubPluginDownloader
from contenthive.logger import logger


class PluginEntryData:
    """Plugin configuration entry data"""
    def __init__(self, entry_id: str, domain: str, data: dict[str, Any]):
        self.entry_id = entry_id
        self.domain = domain
        self.data = data
        self.options = {}
        self.state = PluginState.INSTALLED


class EventBus:
    """Simple event bus for plugin communication"""
    def __init__(self):
        self._listeners: dict[str, list[Callable]] = {}

    def listen(self, event_type: str, callback: Callable):
        """Register event listener"""
        if event_type not in self._listeners:
            self._listeners[event_type] = []
        self._listeners[event_type].append(callback)

    async def fire(self, event_type: str, data: dict[str, Any]):
        """Fire event to all listeners"""
        if event_type in self._listeners:
            for callback in self._listeners[event_type]:
                try:
                    if inspect.iscoroutinefunction(callback):
                        await callback(data)
                    else:
                        callback(data)
                except Exception as e:
                    logger.warning(f"Error in event listener: {e}")


class PluginManager:
    """
    Home Assistant-style plugin manager.
    Plugins are loaded as modules, not classes.
    """

    def __init__(self, plugins_dir: Path, context, deps_dir: Path | None = None):
        self.plugins_dir = plugins_dir
        self.context = context
        self.deps_dir = deps_dir or Path("/app/deps")
        self._ensure_deps_dir_on_path()
        self.plugins: dict[str, PluginRecord] = {}
        self.config_entries: dict[str, PluginEntryData] = {}
        self.event_bus = EventBus()

        # Plugin data storage (like hass.data[DOMAIN])
        self.data: dict[str, Any] = {}

        # Service registry
        self.services: dict[str, dict[str, Callable]] = {}

        # Platform registry (domain -> platform -> entities)
        self._platforms: dict[str, dict[str, list[Any]]] = {}

        # Update check cache: domain -> latest version string if update available, else None
        self._available_updates: dict[str, str | None] = {}
        self._last_update_check: datetime | None = None

    async def async_discover(self):
        """Discover plugins asynchronously from the plugins directory."""
        tasks = []
        for plugin_dir in self.plugins_dir.iterdir():
            if not plugin_dir.is_dir():
                continue

            manifest_path = plugin_dir / "manifest.json"
            if not manifest_path.exists():
                continue

            tasks.append(self._async_load_manifest(plugin_dir, manifest_path))

        await asyncio.gather(*tasks, return_exceptions=True)

        await self.event_bus.fire("plugins_discovered", {
            "count": len(self.plugins)
        })



    async def async_setup(self, domain: str) -> bool:
        """
        Setup plugin from configuration (HA-style).
        Calls the plugin module's async_setup function.
        """
        record = self.plugins.get(domain)
        if not record:
            self.context.logger.warning(f"Plugins[Setup Failed]: {domain} - Not found")
            return False

        if record.state not in [PluginState.INSTALLED, PluginState.DISABLED]:
            self.context.logger.debug(f"Plugins[Setup]: {domain} - Already in state {record.state}")
            return True

        try:
            # Install dependencies
            if not await self._async_install_dependencies(domain):
                record.state = PluginState.FAILED
                return False

            # Load module
            module = await self._async_load_module(domain)
            if not module:
                return False

            record.instance = module  # Store module, not class instance

            # Call module-level async_setup function
            if hasattr(module, "async_setup"):
                plugin_cfg = get_plugin_config(domain)
                config = {k: v for k, v in plugin_cfg.items() if k != "disabled"}
                result = await module.async_setup(self.context, config)
                if not result:
                    raise Exception("async_setup returned False")

            record.state = PluginState.LOADED
            self.context.logger.debug(f"Plugins[Setup]: {domain} - Success")

            await self.event_bus.fire("plugin_setup", {"domain": domain})
            return True

        except Exception as e:
            record.state = PluginState.FAILED
            record.error = str(e)
            self.context.logger.warning(f"Plugins[Setup Failed]: {domain} - {e}")
            return False



    async def async_setup_entry(self, entry: PluginEntryData) -> bool:
        """
        Setup plugin from config entry (HA-style).
        Calls the plugin module's async_setup_entry function.
        """
        domain = entry.domain
        record = self.plugins.get(domain)

        if not record:
            self.context.logger.warning(f"Plugins[Setup Entry Failed]: {domain} - Not found")
            return False

        try:
            # Ensure plugin is loaded
            if record.state == PluginState.INSTALLED:
                if not await self.async_setup(domain):
                    return False

            module = record.instance
            if not module:
                raise Exception("Plugin module not loaded")

            # Call module-level async_setup_entry function
            if hasattr(module, "async_setup_entry"):
                result = await module.async_setup_entry(self.context, entry)
                if not result:
                    raise Exception("async_setup_entry returned False")

            # Store entry
            self.config_entries[entry.entry_id] = entry
            entry.state = PluginState.ENABLED
            record.state = PluginState.ENABLED

            self.context.logger.debug(f"Plugins[Setup Entry]: {domain} - Success")
            await self.event_bus.fire("plugin_enabled", {"domain": domain, "entry_id": entry.entry_id})
            return True

        except Exception as e:
            record.state = PluginState.FAILED
            record.error = str(e)
            self.context.logger.warning(f"Plugins[Setup Entry Failed]: {domain} - {e}")
            return False

    async def async_forward_entry_setup(
        self,
        entry: PluginEntryData,
        platform: str
    ) -> bool:
        """
        Forward setup to a platform (HA-style).
        Similar to: hass.config_entries.async_forward_entry_setup(entry, "parser")

        This loads the platform module (e.g., parser.py) and calls its async_setup_entry.
        """
        domain = entry.domain
        record = self.plugins.get(domain)

        if not record:
            return False

        try:
            # Load platform module (e.g., plugins/fxtwitter/parser.py)
            platform_module = await self._async_load_platform_module(domain, platform)

            if not platform_module:
                raise Exception(f"Platform {platform} not found")

            async def async_add_entities(entities: list[Any]):
                """Callback to register entities from platform."""
                if domain not in self._platforms:
                    self._platforms[domain] = {}
                if platform not in self._platforms[domain]:
                    self._platforms[domain][platform] = []

                self._platforms[domain][platform].extend(entities)
                self.context.logger.debug(
                    f"Registered {len(entities)} {platform} entities for {domain}"
                )

            # Call platform's async_setup_entry
            if hasattr(platform_module, "async_setup_entry"):
                await platform_module.async_setup_entry(
                    self.context,
                    entry,
                    async_add_entities
                )

            return True

        except Exception as e:
            self.context.logger.warning(f"Failed to setup {platform} platform for {domain}: {e}", exc_info=True)
            return False



    def register_service(self, domain: str, service: str, callback: Callable):
        """Register a service (HA-style)"""
        if domain not in self.services:
            self.services[domain] = {}

        self.services[domain][service] = callback
        self.context.logger.debug(f"Plugins[Service Registered]: {domain}.{service}")

    def has_service(self, domain: str, service: str) -> bool:
        """Check if a service is registered for the given domain."""
        return service in self.services.get(domain, {})

    async def call_service(self, domain: str, service: str, data: dict[str, Any]):
        """Call a registered service (HA-style)"""
        if domain not in self.services or service not in self.services[domain]:
            raise ValueError(f"Service {domain}.{service} not found")

        callback = self.services[domain][service]

        if inspect.iscoroutinefunction(callback):
            return await callback(data)
        else:
            return callback(data)

    def get_parser_entities(self) -> list[Any]:
        """Get all registered parser entities from all plugins."""
        parsers = []

        for _, platforms in self._platforms.items():
            if "parser" in platforms:
                parsers.extend(platforms["parser"])

        return parsers



    async def async_check_updates(self, repo_url: str, ref: str = "main") -> dict[str, str | None]:
        """
        Check for available plugin updates by comparing local versions against the remote manifest.

        Fetches plugins-manifest.json from the remote repository and compares each plugin's
        version with the locally installed version. Results are cached on the manager.

        Args:
            repo_url: GitHub repository URL
            ref: Git reference (branch name, tag, or commit SHA)

        Returns:
            Dict mapping domain to the latest remote version string if an update is available,
            or None if already up to date or the plugin is not found in the remote manifest.

        Raises:
            Exception: If the remote manifest could not be fetched
        """
        downloader = GitHubPluginDownloader(self.plugins_dir)
        remote_manifest = await downloader.fetch_remote_manifest(repo_url, ref)

        if remote_manifest is None:
            raise Exception("Failed to fetch remote plugins manifest")

        results: dict[str, str | None] = {}

        for plugin_info in remote_manifest.get("plugins", []):
            domain = plugin_info.get("domain")
            remote_version_str = plugin_info.get("version")

            if not domain or not remote_version_str:
                continue

            local_record = self.plugins.get(domain)
            if not local_record:
                continue

            try:
                results[domain] = remote_version_str if Version(remote_version_str) > Version(local_record.version) else None
            except Exception:
                self.context.logger.warning(
                    f"Plugins[Update Check]: {domain} - invalid version string "
                    f"(local={local_record.version}, remote={remote_version_str})"
                )
                results[domain] = None

        # Cache results
        self._available_updates = results
        self._last_update_check = datetime.now(timezone.utc)

        return results



    async def async_activate(self, domain: str) -> bool:
        """
        Discover, setup, and enable a newly installed plugin.
        Used after installing a plugin that was not previously known to the manager.
        """
        plugin_dir = self.plugins_dir / domain
        manifest_path = plugin_dir / "manifest.json"

        await self._async_load_manifest(plugin_dir, manifest_path)

        if domain not in self.plugins:
            self.context.logger.warning(f"Plugins[Activate Failed]: {domain} - manifest not loaded")
            return False

        if not await self.async_setup(domain):
            return False

        entry = PluginEntryData(
            entry_id=f"{domain}_default",
            domain=domain,
            data={},
        )
        return await self.async_setup_entry(entry)



    async def async_reload(self, domain: str) -> bool:
        """Reload a plugin."""
        entries = [
            entry for entry in self.config_entries.values()
            if entry.domain == domain
        ]

        for entry in entries:
            await self.async_unload_entry(entry.entry_id)

        self._clear_module_cache(domain)

        record = self.plugins.get(domain)
        if record:
            record.instance = None
            record.state = PluginState.INSTALLED
            manifest_path = self.plugins_dir / domain / "manifest.json"
            if manifest_path.exists():
                try:
                    record.manifest = self._read_plugin_manifest(manifest_path, domain)
                except Exception as e:
                    self.context.logger.warning(f"Plugins[Reload]: {domain} - Failed to re-read manifest: {e}")

        if await self.async_setup(domain):
            for entry in entries:
                await self.async_setup_entry(entry)
            return True

        return False



    async def async_unload_platforms(
        self,
        entry: PluginEntryData,
        platforms: list[str]
    ) -> bool:
        """
        Unload platforms for an entry (HA-style).
        Similar to: hass.config_entries.async_unload_platforms(entry, ["parser"])
        """
        domain = entry.domain

        for platform in platforms:
            if domain in self._platforms and platform in self._platforms[domain]:
                entities = self._platforms[domain][platform]

                # Call async_will_remove on each entity
                for entity in entities:
                    if hasattr(entity, "async_will_remove"):
                        try:
                            await entity.async_will_remove()
                        except Exception as e:
                            self.context.logger.warning(f"Error unloading entity: {e}")

                # Remove platform
                del self._platforms[domain][platform]

        return True

    async def async_unload_entry(self, entry_id: str) -> bool:
        """Unload plugin config entry (HA-style)."""
        entry = self.config_entries.get(entry_id)
        if not entry:
            return False

        domain = entry.domain
        record = self.plugins.get(domain)

        if not record or not record.instance:
            return False

        try:
            module = record.instance

            # Call module-level async_unload_entry function
            if hasattr(module, "async_unload_entry"):
                result = await module.async_unload_entry(self.context, entry)
                if not result:
                    raise Exception("async_unload_entry returned False")

            # Remove entry
            del self.config_entries[entry_id]
            entry.state = PluginState.DISABLED

            # Check if plugin has other active entries
            has_active = any(
                e.domain == domain and e.state == PluginState.ENABLED
                for e in self.config_entries.values()
            )

            if not has_active:
                record.state = PluginState.LOADED

            self.context.logger.debug(f"Plugins[Unload Entry]: {domain} - Success")
            await self.event_bus.fire("plugin_disabled", {"domain": domain, "entry_id": entry_id})
            return True

        except Exception as e:
            self.context.logger.warning(f"Plugins[Unload Entry Failed]: {domain} - {e}")
            return False



    async def async_delete(self, domain: str) -> None:
        """Unload, remove from registry, and delete the plugin directory from disk.

        Args:
            domain: Plugin domain identifier. Must be present in self.plugins.

        Raises:
            ValueError: If the domain is not found in the plugin registry.
            RuntimeError: If the plugin directory cannot be deleted from disk.
        """
        if domain not in self.plugins:
            raise ValueError(f"Plugin '{domain}' not found")

        # Unload all config entries
        entries = [
            entry for entry in self.config_entries.values()
            if entry.domain == domain
        ]
        for entry in entries:
            await self.async_unload_entry(entry.entry_id)

        # Clear cached modules
        self._clear_module_cache(domain)

        # Clean up any platform entities that weren't removed during entry unload
        await self._async_cleanup_domain_platforms(domain)

        # Clean up service registry for this domain
        self.services.pop(domain, None)

        # Clean up plugin data storage for this domain
        self.data.pop(domain, None)

        # Remove from registry (pop guards against a concurrent second call)
        self.plugins.pop(domain, None)
        self._available_updates.pop(domain, None)

        # Delete plugin directory from disk
        plugin_dir = self.plugins_dir / domain
        if plugin_dir.exists():
            try:
                shutil.rmtree(plugin_dir)
            except Exception as e:
                raise RuntimeError(f"Failed to delete plugin directory: {e}") from e

        await self.event_bus.fire("plugin_deleted", {"domain": domain})
        logger.info(f"Plugins[Deleted]: {domain}")



    def _ensure_deps_dir_on_path(self):
        """Create the deps directory and add it to sys.path if not already present."""
        self.deps_dir.mkdir(parents=True, exist_ok=True)
        deps_str = str(self.deps_dir)
        if deps_str not in sys.path:
            sys.path.append(deps_str)

    async def _async_load_manifest(self, plugin_dir: Path, manifest_path: Path):
        """Load plugin manifest"""
        try:
            manifest = self._read_plugin_manifest(manifest_path, plugin_dir.name)
            domain = manifest['domain']

            self.plugins[domain] = PluginRecord(manifest, None)
            self.context.logger.debug(f"Plugins[Discovered]: {domain}")

            await self.event_bus.fire("plugin_discovered", {
                "domain": domain,
                "manifest": manifest
            })
        except Exception as e:
            self.context.logger.warning(f"Plugins[Discovery Failed]: {plugin_dir.name} - {e}")

    def _read_plugin_manifest(self, manifest_path: Path, domain: str) -> dict:
        """Read and validate a single plugin's manifest.json.

        Args:
            manifest_path: Absolute path to the plugin's manifest.json.
            domain: Expected plugin domain — must match the ``domain`` field in
                    the manifest to guard against misplaced or stale files.

        Returns:
            Parsed manifest dict.

        Raises:
            ValueError: If the file cannot be parsed, is not a JSON object, or
                        its ``domain`` field does not match *domain*.
        """
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in manifest: {e}") from e

        if not isinstance(data, dict):
            raise ValueError("manifest.json must be a JSON object")

        manifest_domain = data.get("domain")
        if manifest_domain != domain:
            raise ValueError(
                f"manifest domain '{manifest_domain}' does not match plugin domain '{domain}'"
            )

        return data



    async def _async_install_dependencies(self, domain: str) -> bool:
        """Install plugin dependencies asynchronously"""
        record = self.plugins.get(domain)
        if not record or not record.manifest:
            return True

        requirements = record.manifest.get("requirements", [])
        if not requirements:
            return True

        conflicts = self._detect_conflicts(requirements)
        if conflicts:
            for conflict in conflicts:
                self.context.logger.warning(f"Plugins[Dependencies]: {domain} - Version conflict: {conflict}")
            return False

        try:
            self.context.logger.info(f"Plugins[Dependencies]: {domain} - Installing {len(requirements)} packages")

            loop = asyncio.get_running_loop()
            installed = await loop.run_in_executor(
                None,
                self._install_packages,
                requirements
            )

            if installed:
                self.context.logger.info(f"Plugins[Dependencies]: {domain} - Installed {installed}")
            else:
                self.context.logger.debug(f"Plugins[Dependencies]: {domain} - All requirements already satisfied")
            return True

        except Exception as e:
            self.context.logger.warning(f"Plugins[Dependencies Failed]: {domain} - {e}")
            return False

    def _detect_conflicts(self, requirements: list[str]) -> list[str]:
        """Return conflict descriptions for requirements that clash with already-installed versions."""
        conflicts = []
        for req_str in requirements:
            try:
                req = Requirement(req_str)
                if not req.specifier:
                    continue
                installed = importlib.metadata.version(req.name)
                if not req.specifier.contains(installed, prereleases=True):
                    conflicts.append(f"{req_str} (installed: {installed})")
            except importlib.metadata.PackageNotFoundError:
                pass
            except Exception:
                pass
        return conflicts

    def _filter_missing_requirements(self, requirements: list[str]) -> list[str]:
        """Return only requirements that are not already satisfied."""
        missing = []
        for req_str in requirements:
            try:
                req = Requirement(req_str)
                installed = importlib.metadata.version(req.name)
                if req.specifier and not req.specifier.contains(installed, prereleases=True):
                    missing.append(req_str)
            except importlib.metadata.PackageNotFoundError:
                missing.append(req_str)
            except Exception:
                missing.append(req_str)
        return missing

    def _install_packages(self, requirements: list[str]) -> list[str]:
        """Blocking package installation (run in executor). Returns the list of packages actually installed."""
        to_install = self._filter_missing_requirements(requirements)
        if not to_install:
            return []

        env = os.environ.copy()
        # Ensure HOME is writable; in containers running as root, HOME may be '/'
        # which causes pip to fail when writing to ~/.local or ~/.cache/pip
        home = env.get("HOME", "/")
        if not os.access(home, os.W_OK):
            env["HOME"] = tempfile.gettempdir()

        subprocess.check_call([
            sys.executable, "-m", "pip", "install",
            *to_install,
            "--target", str(self.deps_dir),
            "--quiet",
            "--root-user-action=ignore",
            "--disable-pip-version-check",
            "--no-cache-dir",
        ], env=env)

        return to_install

    async def _async_load_module(self, domain: str):
        """Load plugin module (not a class!)"""
        try:
            plugin_dir = self.plugins_dir / domain
            module_path = plugin_dir / "__init__.py"
            module_name = f"contenthive_plugin_{domain}"

            spec = importlib.util.spec_from_file_location(
                module_name,
                module_path,
                submodule_search_locations=[str(plugin_dir)]
            )
            if spec is None or spec.loader is None:
                raise Exception(f"Cannot create module spec for {module_path}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)

            return module

        except Exception as e:
            self.context.logger.warning(f"Plugins[Load Module Failed]: {domain} - {e}")
            return None



    async def _async_load_platform_module(self, domain: str, platform: str):
        """Load platform module (e.g., parser.py) as part of the plugin package."""
        try:
            parent_module_name = f"contenthive_plugin_{domain}"

            if parent_module_name not in sys.modules:
                init_path = self.plugins_dir / domain / "__init__.py"
                parent_spec = importlib.util.spec_from_file_location(
                    parent_module_name,
                    init_path,
                    submodule_search_locations=[str(self.plugins_dir / domain)]
                )
                if parent_spec is None or parent_spec.loader is None:
                    raise Exception(f"Cannot create module spec for {init_path}")
                parent_module = importlib.util.module_from_spec(parent_spec)
                sys.modules[parent_module_name] = parent_module
                parent_spec.loader.exec_module(parent_module)

            platform_path = self.plugins_dir / domain / f"{platform}.py"

            if not platform_path.exists():
                self.context.logger.warning(f"Platform file not found: {platform_path}")
                return None

            module_name = f"{parent_module_name}.{platform}"

            spec = importlib.util.spec_from_file_location(
                module_name,
                platform_path
            )

            if spec is None or spec.loader is None:
                self.context.logger.warning(f"Failed to create module spec for {platform_path}")
                return None

            module = importlib.util.module_from_spec(spec)

            module.__package__ = parent_module_name

            sys.modules[module_name] = module

            spec.loader.exec_module(module)

            self.context.logger.debug(f"Loaded platform module: {module_name}")
            return module

        except Exception as e:
            self.context.logger.warning(f"Failed to load {platform} platform for {domain}: {e}", exc_info=True)
            return None



    async def _async_cleanup_domain_platforms(self, domain: str) -> None:
        """Remove all remaining platform entities for a domain, calling async_will_remove on each."""
        if domain not in self._platforms:
            return
        for platform, entities in self._platforms[domain].items():
            for entity in entities:
                if hasattr(entity, "async_will_remove"):
                    try:
                        await entity.async_will_remove()
                    except Exception as e:
                        self.context.logger.warning(
                            f"Plugins[Delete]: {domain} - Error removing {platform} entity: {e}"
                        )
        del self._platforms[domain]

    def _clear_module_cache(self, domain: str) -> None:
        """Remove all cached module entries for a plugin domain.

        Clears both the legacy ``plugin_{domain}`` name and the package-style
        ``contenthive_plugin_{domain}`` name (plus any sub-modules) from
        ``sys.modules`` so that a subsequent import loads fresh bytecode.
        """
        stale_prefixes = (f"contenthive_plugin_{domain}.",)
        stale_exact = {f"plugin_{domain}", f"contenthive_plugin_{domain}"}
        for key in list(sys.modules.keys()):
            if key in stale_exact or key.startswith(stale_prefixes):
                del sys.modules[key]


# Singleton instance
_plugin_manager: PluginManager | None = None

def set_plugin_manager(manager: PluginManager):
    """Set global plugin manager instance"""
    global _plugin_manager
    _plugin_manager = manager

def get_plugin_manager() -> PluginManager | None:
    """Get global plugin manager instance"""
    return _plugin_manager
