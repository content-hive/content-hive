from contenthive.plugins.registry import PluginState
from contenthive.config import settings
from contenthive.plugins.context import PluginContext
from contenthive.plugins.manager import PluginEntryData, PluginManager, get_plugin_manager, set_plugin_manager
from contenthive.plugins.config import load_plugins_config, strip_framework_keys
from contenthive.logger import logger


async def load_plugins_on_startup():
    """
    Load and enable plugins on application startup using HA-style workflow.
    """
    # 1. Create plugin context
    context = PluginContext(logger=logger)

    # 2. Create plugin manager with context
    plugin_manager = PluginManager(settings.plugins_dir, context)
    set_plugin_manager(plugin_manager)

    # 3. Inject HA-style methods into context for plugins to use
    context.async_forward_entry_setup = plugin_manager.async_forward_entry_setup
    context.async_unload_platforms = plugin_manager.async_unload_platforms
    context.register_service = plugin_manager.register_service

    # 4. Discover locally installed plugins
    await plugin_manager.async_discover()

    # 5. Fetch remote manifest and compare — no archive download, lightweight check only
    try:
        check_results = await plugin_manager.async_check_updates(
            repo_url=settings.plugins_repo_url,
            ref=settings.plugins_repo_ref,
        )
        installed_domains = set(plugin_manager.plugins)
        new_plugins = {d: v for d, v in check_results.items() if d not in installed_domains and v}
        available_updates = {d: v for d, v in check_results.items() if d in installed_domains and v}

        if new_plugins:
            logger.info(
                "New plugins available: "
                + ", ".join(f"{d} ({v})" for d, v in new_plugins.items())
            )
        if available_updates:
            logger.info(
                "Plugin updates available: "
                + ", ".join(f"{d} ({plugin_manager.plugins[d].version} → {v})" for d, v in available_updates.items())
            )
        if not new_plugins and not available_updates:
            logger.debug("All plugins are up to date")
    except Exception:
        logger.warning("Failed to check for plugin updates from remote manifest")

    # 6. Setup and enable plugins
    plugins_config = load_plugins_config()
    for domain in plugin_manager.plugins:
        plugin_cfg = plugins_config.get(domain, {})

        if plugin_cfg.get("disabled", False):
            plugin_manager.plugins[domain].state = PluginState.DISABLED
            logger.info(f"Plugin skipped (disabled): {domain}")
            continue

        # Setup plugin (load module, install dependencies)
        success = await plugin_manager.async_setup(domain)

        if not success:
            logger.warning(f"Plugin setup failed: {domain}")
            continue

        # Create config entry
        config = strip_framework_keys(plugin_cfg)
        entry = PluginEntryData(
            entry_id=f"{domain}_default",
            domain=domain,
            data=config,
        )

        # Setup entry (enable plugin)
        success = await plugin_manager.async_setup_entry(entry)

        if success:
            logger.debug(f"Plugin enabled: {domain}")
        else:
            logger.warning(f"Plugin enable failed: {domain}")

    # 7. Log summary
    enabled_count = sum(
        1 for record in plugin_manager.plugins.values()
        if record.state == PluginState.ENABLED
    )
    logger.info(f"Plugin loading complete: {enabled_count}/{len(plugin_manager.plugins)} enabled")


async def shutdown_plugins():
    """
    Gracefully shutdown all plugins.
    """
    plugin_manager = get_plugin_manager()
    if not plugin_manager:
        return
    
    entries_to_unload = list(plugin_manager.config_entries.keys())
    for entry_id in entries_to_unload:
        await plugin_manager.async_unload_entry(entry_id)