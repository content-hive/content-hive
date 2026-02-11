"""
Plugin downloader for fetching and installing plugins from GitHub repositories.
Supports both standalone plugin repos and multi-plugin repositories.
"""
import aiohttp
import zipfile
import shutil
import json
from pathlib import Path
from typing import Optional, List, Dict
from urllib.parse import quote
from contenthive.logger import logger
from contenthive.config import settings

class GitHubPluginDownloader:
    """Download and install plugins from GitHub repositories"""
    
    def __init__(self):
        """
        Initialize the plugin downloader.
        """
        self.plugins_dir = settings.plugins_dir
        self.temp_dir = self.plugins_dir / ".temp"
        self.temp_dir.mkdir(exist_ok=True)
    
    async def download_plugins(
        self, 
        repo_url: str,
        ref: str = "main",
        ref_type: str = "branch",
        selected_plugins: Optional[List[str]] = None,
        force_reinstall: bool = False
    ) -> Dict[str, bool]:
        """
        Download and install plugins from any GitHub repository.
        
        Supports multiple repository structures:
        - Single plugin: manifest.json in root
        - Multi-plugin: plugins-manifest.json in root
        - Legacy: plugins/ directory with individual manifests
        
        Args:
            repo_url: GitHub repository URL (e.g., "github.com/user/repo")
            ref: Git reference (branch name, tag, or commit SHA)
            ref_type: Type of reference: "branch", "tag", or "commit"
            selected_plugins: List of plugin IDs to install (None = all enabled)
            force_reinstall: If True, reinstall even if plugin exists
        
        Returns:
            Dict mapping plugin ID to installation success status
        """
        results = {}
        extract_dir = None
        archive_path = None
        
        try:
            logger.info(f"Downloading plugins from {repo_url} (ref: {ref})...")
            
            # Parse GitHub URL and download
            owner, repo = self._parse_github_url(repo_url)
            archive_path = await self._download_archive(owner, repo, ref, ref_type)
            
            # Extract archive (use safe ref name for directory)
            safe_ref = ref.replace('/', '_').replace('\\', '_')
            extract_dir = self.temp_dir / f"extract_{repo}_{ref_type}_{safe_ref}"
            if extract_dir.exists():
                shutil.rmtree(extract_dir)
            extract_dir.mkdir(parents=True)
            
            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
            
            # Find repo root (GitHub adds prefix like "repo-branch")
            root_dirs = [d for d in extract_dir.iterdir() if d.is_dir()]
            if not root_dirs:
                raise Exception("No directories found in archive")
            
            repo_root = root_dirs[0]
            
            # Try different repository structures
            
            # 1. Check for plugins-manifest.json (multi-plugin repo)
            multi_manifest = repo_root / "plugins-manifest.json"
            if multi_manifest.exists():
                results = await self._install_from_manifest(
                    repo_root,
                    multi_manifest,
                    selected_plugins,
                    force_reinstall
                )
                return results
            
            # 2. Check for manifest.json (single plugin)
            single_manifest = repo_root / "manifest.json"
            if single_manifest.exists():
                manifest = json.loads(single_manifest.read_text(encoding='utf-8'))
                domain = manifest.get("domain")
                
                if not domain:
                    raise Exception("Plugin manifest missing 'domain' field")
                
                # Skip if not in selected list
                if selected_plugins and domain not in selected_plugins:
                    logger.info(f"Plugin {domain} not in selected list, skipping...")
                    return results
                
                logger.info(f"Found standalone plugin: {domain}")
                success = await self._install_plugin_directory(
                    repo_root,
                    domain,
                    force_reinstall=force_reinstall
                )
                results[domain] = success
                return results
            
            # 3. Check plugins/ directory (legacy structure)
            plugins_dir = repo_root / "plugins"
            if plugins_dir.exists() and plugins_dir.is_dir():
                for plugin_path in plugins_dir.iterdir():
                    if not plugin_path.is_dir():
                        continue
                    
                    manifest_file = plugin_path / "manifest.json"
                    if not manifest_file.exists():
                        continue
                    
                    manifest = json.loads(manifest_file.read_text(encoding='utf-8'))
                    domain = manifest.get("domain", plugin_path.name)
                    
                    # Skip if not in selected list
                    if selected_plugins and domain not in selected_plugins:
                        logger.debug(f"Skipping unselected plugin: {domain}")
                        continue
                    
                    # Check if already installed
                    if not force_reinstall and (self.plugins_dir / domain).exists():
                        logger.info(f"Plugin {domain} already installed, skipping...")
                        results[domain] = True
                        continue
                    
                    logger.info(f"Installing plugin: {domain}")
                    success = await self._install_plugin_directory(
                        plugin_path,
                        domain,
                        force_reinstall=force_reinstall
                    )
                    results[domain] = success
                
                return results
            
            logger.warning("No valid plugin structure found in repository (missing manifest.json or plugins-manifest.json)")
            return results
            
        except Exception as e:
            logger.error(f"Failed to download plugins: {e}", exc_info=True)
            return results
        
        finally:
            # Cleanup
            if archive_path and archive_path.exists():
                archive_path.unlink()
            if extract_dir and extract_dir.exists():
                shutil.rmtree(extract_dir, ignore_errors=True)
    
    async def _install_from_manifest(
        self,
        repo_root: Path,
        manifest_path: Path,
        selected_plugins: Optional[List[str]],
        force_reinstall: bool
    ) -> Dict[str, bool]:
        """Install plugins from plugins-manifest.json"""
        results = {}
        
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        logger.info(f"Found {len(manifest.get('plugins', []))} plugins in manifest")
        
        for plugin_info in manifest.get("plugins", []):
            domain = plugin_info.get("domain")
            
            if not domain:
                logger.error("Plugin missing 'domain' field, skipping...")
                continue
            
            # Skip if not in selected list
            if selected_plugins and domain not in selected_plugins:
                logger.info(f"Plugin {domain} not in selected list, skipping...")
                continue
            
            # Skip if disabled (unless explicitly selected)
            if not plugin_info.get("enabled", True) and not selected_plugins:
                logger.info(f"Plugin {domain} is disabled, skipping...")
                continue
            
            # Install plugin
            plugin_path = repo_root / plugin_info["path"]
            if not plugin_path.exists():
                logger.error(f"Plugin path not found: {plugin_path}")
                results[domain] = False
                continue
            
            logger.info(f"Installing plugin: {domain} ({plugin_info.get('name', domain)})")
            success = await self._install_plugin_directory(
                plugin_path,
                domain,
                force_reinstall=force_reinstall
            )
            
            results[domain] = success
            
            if success:
                logger.info(f"✓ Successfully installed: {domain}")
            else:
                logger.error(f"✗ Failed to install: {domain}")
        
        return results
    
    async def _download_archive(
        self, 
        owner: str, 
        repo: str, 
        ref: str,
        ref_type: str = "branch"
    ) -> Path:
        """
        Download repository as zip archive from GitHub.
        
        Args:
            owner: GitHub repository owner
            repo: Repository name
            ref: Git reference (branch name, tag, or commit SHA)
            ref_type: Type of reference: "branch", "tag", or "commit"
        
        Returns:
            Path to downloaded archive file
        """
        # Build URL based on reference type
        if ref_type == "branch":
            # Branch: refs/heads/branch-name
            encoded_ref = quote(ref, safe='')
            url = f"https://github.com/{owner}/{repo}/archive/refs/heads/{encoded_ref}.zip"
        elif ref_type == "tag":
            # Tag: refs/tags/tag-name
            encoded_ref = quote(ref, safe='')
            url = f"https://github.com/{owner}/{repo}/archive/refs/tags/{encoded_ref}.zip"
        elif ref_type == "commit":
            # Commit SHA: directly use the SHA
            url = f"https://github.com/{owner}/{repo}/archive/{ref}.zip"
        else:
            raise ValueError(f"Invalid ref_type: {ref_type}. Must be 'branch', 'tag', or 'commit'")
        
        # Create a safe filename for the archive
        safe_ref = ref.replace('/', '_').replace('\\', '_')
        archive_path = self.temp_dir / f"{repo}-{ref_type}-{safe_ref}.zip"
        
        logger.debug(f"Downloading from {url}...")
        
        timeout = aiohttp.ClientTimeout(total=300)  # 5 minutes timeout
        
        async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
            async with session.get(url) as response:
                if response.status != 200:
                    raise Exception(f"Failed to download archive: HTTP {response.status}")
                
                total_size = int(response.headers.get('content-length', 0))
                downloaded = 0
                
                with open(archive_path, 'wb') as f:
                    async for chunk in response.content.iter_chunked(8192):
                        f.write(chunk)
                        downloaded += len(chunk)
                        
                        if total_size > 0:
                            percent = (downloaded / total_size) * 100
                            if downloaded % (512 * 1024) == 0:  # Log every 512KB
                                logger.debug(f"Downloaded {percent:.1f}%")
        
        logger.debug(f"Archive downloaded to {archive_path}")
        return archive_path
    
    async def _install_plugin_directory(
        self, 
        source_dir: Path, 
        domain: str,
        force_reinstall: bool = False
    ) -> bool:
        """
        Install a single plugin directory.
        
        Args:
            source_dir: Source directory containing plugin files
            domain: Plugin domain/ID
            force_reinstall: If True, overwrite existing plugin
        
        Returns:
            True if installation successful
        """
        try:
            if not source_dir.exists():
                logger.error(f"Source directory does not exist: {source_dir}")
                return False
            
            target_dir = self.plugins_dir / domain
            
            # Check if plugin already exists
            if target_dir.exists():
                if not force_reinstall:
                    logger.warning(f"Plugin {domain} already exists, skipping...")
                    return True
                
                logger.warning(f"Plugin {domain} already exists, overwriting...")
                shutil.rmtree(target_dir)
            
            # Verify manifest.json exists
            manifest_path = source_dir / "manifest.json"
            if not manifest_path.exists():
                logger.error(f"manifest.json not found in {source_dir}")
                return False
            
            # Validate manifest
            try:
                manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
                if not manifest.get("domain"):
                    logger.error(f"Invalid manifest: missing 'domain' field")
                    return False
            except json.JSONDecodeError as e:
                logger.error(f"Invalid manifest.json: {e}")
                return False
            
            # Copy plugin files
            shutil.copytree(source_dir, target_dir)
            
            logger.info(f"Plugin installed to: {target_dir}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to install plugin {domain}: {e}", exc_info=True)
            return False
    
    def _parse_github_url(self, url: str) -> tuple[str, str]:
        """
        Parse GitHub URL to extract owner and repo.
        
        Supports formats:
        - github.com/owner/repo
        - https://github.com/owner/repo
        - https://github.com/owner/repo.git
        
        Args:
            url: GitHub repository URL
        
        Returns:
            Tuple of (owner, repo)
        """
        # Remove protocol
        url = url.replace("https://", "").replace("http://", "")
        
        # Remove github.com prefix
        url = url.replace("github.com/", "")
        
        # Remove .git suffix
        url = url.replace(".git", "")
        
        # Remove trailing slash
        url = url.rstrip("/")
        
        # Split into parts
        parts = url.split("/")
        if len(parts) < 2:
            raise ValueError(f"Invalid GitHub URL: {url}. Expected format: github.com/owner/repo")
        
        return parts[0], parts[1]
    
    def cleanup_temp(self):
        """Clean up temporary download directory"""
        if self.temp_dir.exists():
            try:
                shutil.rmtree(self.temp_dir)
                logger.debug("Cleaned up temporary download directory")
            except Exception as e:
                logger.warning(f"Failed to clean up temp directory: {e}")
