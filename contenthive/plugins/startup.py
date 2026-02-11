from contenthive.plugins.registry import PluginState
from contenthive.database.db import get_db_connection
from contenthive.config import settings
from contenthive.plugins.context import PluginContext
from contenthive.plugins.manager import PluginEntryData, PluginManager, get_plugin_manager, set_plugin_manager
from contenthive.plugins.downloader import GitHubPluginDownloader
from contenthive.logger import logger


async def load_plugins_on_startup(app, data_dir):
    """
    Load and enable plugins on application startup using HA-style workflow.
    """
    # 1. Create plugin context
    context = PluginContext(
        app=app,
        data_dir=data_dir,
        db_factory=get_db_connection,
        logger=logger
    )

    # 2. Download official plugins from repository
    logger.info(f"Downloading plugins from official repository: {settings.plugins_repo_url}")
    downloader = GitHubPluginDownloader()
    
    try:
        results = await downloader.download_plugins(
            repo_url=settings.plugins_repo_url,
            ref=settings.plugins_repo_ref,
            ref_type=settings.plugins_repo_ref_type,
            force_reinstall=False  # Only download if not already installed
        )
        
        if results:
            success_count = sum(1 for v in results.values() if v)
            total_count = len(results)
            logger.info(f"Plugin download complete: {success_count}/{total_count} plugins installed")
            
            if success_count < total_count:
                failed = [k for k, v in results.items() if not v]
                logger.warning(f"Failed to install plugins: {', '.join(failed)}")
        else:
            logger.info("No plugins found in official repository")
    except Exception as e:
        logger.error(f"Failed to download plugins from repository: {e}")
        logger.info("Continuing with existing plugins...")
    finally:
        # Cleanup temporary files
        downloader.cleanup_temp()

    # 3. Create plugin manager with context
    plugin_manager = PluginManager(settings.plugins_dir, context)
    set_plugin_manager(plugin_manager)

    # 4. Inject HA-style methods into context for plugins to use
    context.async_forward_entry_setup = plugin_manager.async_forward_entry_setup
    context.async_unload_platforms = plugin_manager.async_unload_platforms
    context.register_service = plugin_manager.register_service

    # 5. Discover plugins
    logger.info("Starting plugin discovery...")
    await plugin_manager.async_discover()
    logger.info(f"Discovered {len(plugin_manager.plugins)} plugins")

    # 6. Setup and enable plugins
    for domain in plugin_manager.plugins:
        logger.info(f"Setting up plugin: {domain}")

        # Get plugin configuration
        config = _get_plugin_config(domain)
        
        # Setup plugin (load module, install dependencies)
        success = await plugin_manager.async_setup(domain, config)

        if not success:
            logger.error(f"Failed to setup plugin: {domain}")
            continue

        # Create config entry
        entry = PluginEntryData(
            entry_id=f"{domain}_default",
            domain=domain,
            data=config or {},
        )

        # Setup entry (enable plugin)
        success = await plugin_manager.async_setup_entry(entry)

        if success:
            logger.info(f"✓ Plugin enabled: {domain}")
        else:
            logger.error(f"✗ Failed to enable plugin: {domain}")

    # 7. Log summary
    enabled_count = sum(
        1 for record in plugin_manager.plugins.values()
        if record.state == PluginState.ENABLED
    )
    logger.info(f"Plugin loading complete: {enabled_count}/{len(plugin_manager.plugins)} enabled")


def _get_plugin_config(domain: str) -> dict:
    """
    Get plugin configuration from settings or config file.
    In the future, this could load from database or config file.
    """
    configs = {
        "youtube_parser": {
            "api_key": "",
        },
        # Add more plugin configs as needed
    }
    
    return configs.get(domain, {})


async def shutdown_plugins():
    """
    Gracefully shutdown all plugins.
    """
    plugin_manager = get_plugin_manager()
    if not plugin_manager:
        return
    
    logger.info("Shutting down plugins...")
    
    # Unload all config entries
    entries_to_unload = list(plugin_manager.config_entries.keys())
    for entry_id in entries_to_unload:
        await plugin_manager.async_unload_entry(entry_id)
    
    logger.info("All plugins unloaded")