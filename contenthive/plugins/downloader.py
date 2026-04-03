"""
Plugin downloader for fetching and installing plugins from GitHub repositories.

Required repository structure:

    <repo-root>/
    ├── plugins-manifest.json   # required — lists all available plugins
    └── <plugin-path>/          # one directory per plugin (path defined in manifest)
        ├── __init__.py
        ├── manifest.json       # written by the downloader from plugins-manifest.json
        └── ...

plugins-manifest.json format:

    {
      "plugins": [
        {
          "domain": "my_parser",
          "name": "My Parser",
          "version": "1.2.0",
          "path": "plugins/my_parser",
          "enabled": true,
          "requirements": ["aiohttp"]
        }
      ]
    }

Repositories that do not contain a plugins-manifest.json at their root are not
supported and will raise an exception during download.
"""
import aiohttp
import zipfile
import shutil
import json
from pathlib import Path
from urllib.parse import quote, urlparse
from contenthive.logger import logger
from contenthive.config import settings
import re

class GitHubPluginDownloader:
    """Download and install plugins from GitHub repositories"""
    
    # Valid plugin domain pattern: lowercase letters, numbers, hyphens, underscores
    VALID_DOMAIN_PATTERN = re.compile(r'^[a-z0-9_-]+$')
    # Valid git ref pattern: alphanumeric, hyphens, dots, underscores, slashes, and commit SHAs
    VALID_REF_PATTERN = re.compile(r'^[a-zA-Z0-9._/\-]+$')
    _INVALID_REF_SEGMENTS = re.compile(r'(^/|//|/\./|/\.\./|\.\.$|^\.\./)')
    
    def __init__(self):
        """
        Initialize the plugin downloader.
        """
        self.plugins_dir = settings.plugins_dir
        self.temp_dir = self.plugins_dir / ".temp"
        self.temp_dir.mkdir(exist_ok=True)
    
    def _validate_domain(self, domain: str) -> bool:
        """
        Validate plugin domain to prevent path traversal attacks.
        
        Domain must:
        - Be non-empty
        - Contain only lowercase letters, numbers, hyphens, and underscores
        - Not contain path separators (/, \\)
        - Not contain special path components (., ..)
        - Be between 1 and 100 characters
        
        Args:
            domain: Plugin domain/ID to validate
            
        Returns:
            True if domain is valid, False otherwise
        """
        if not domain or not isinstance(domain, str):
            logger.warning("Domain is empty or not a string")
            return False
        
        # Check length
        if len(domain) < 1 or len(domain) > 100:
            logger.warning(f"Domain length invalid: {len(domain)} (must be 1-100)")
            return False
        
        # Check for path separators
        if '/' in domain or '\\' in domain:
            logger.warning(f"Domain contains path separators: {domain}")
            return False
        
        # Check for special path components
        if domain in ('.', '..') or domain.startswith('.'):
            logger.warning(f"Domain is a special path component: {domain}")
            return False
        
        # Check against allowed pattern
        if not self.VALID_DOMAIN_PATTERN.match(domain):
            logger.warning(f"Domain contains invalid characters: {domain} (allowed: a-z, 0-9, -, _)")
            return False
        
        return True
    
    def _validate_ref(self, ref: str) -> None:
        """
        Validate a git reference to prevent path traversal and injection attacks.

        Raises:
            ValueError: If the ref contains invalid characters
        """
        if not self.VALID_REF_PATTERN.match(ref):
            raise ValueError(
                f"Invalid ref '{ref}': only alphanumeric characters, hyphens, dots, underscores, and slashes are allowed"
            )
        if self._INVALID_REF_SEGMENTS.search(ref):
            raise ValueError(
                f"Invalid ref '{ref}': must not start with '/', contain '//', or include path traversal segments"
            )

    def _sanitize_ref(self, ref: str) -> str:
        """
        Sanitize git reference for safe use in file paths.
        
        Args:
            ref: Git reference (branch name, tag, or commit SHA)
            
        Returns:
            Sanitized reference string safe for file paths
        """
        return ref.replace('/', '_').replace('\\', '_')
    
    def _validate_path_safety(self, target_path: Path, base_path: Path, entity_name: str = "Path") -> bool:
        """
        Validate that a target path is safely within a base path.
        
        Args:
            target_path: The path to validate
            base_path: The base/root path that target must be within
            entity_name: Name of the entity for error messages
            
        Returns:
            True if path is safe, False otherwise
        """
        try:
            target_path.resolve().relative_to(base_path.resolve())
            return True
        except ValueError:
            logger.error(f"{entity_name} escapes base directory: {target_path} (base: {base_path})")
            return False
    
    def _safe_extract(self, zip_file: zipfile.ZipFile, extract_dir: Path) -> None:
        """
        Safely extract zip file, preventing Zip Slip attacks.
        
        Args:
            zip_file: ZipFile object to extract
            extract_dir: Target extraction directory
            
        Raises:
            ValueError: If any member path is unsafe (absolute or escapes extract_dir)
        """
        extract_dir = extract_dir.resolve()
        
        for member in zip_file.namelist():
            # Get the member path
            member_path = Path(member)
            
            # Reject absolute paths
            if member_path.is_absolute():
                raise ValueError(f"Unsafe zip entry: absolute path '{member}'")
            
            # Resolve the full target path
            target_path = (extract_dir / member_path).resolve()
            
            # Verify the resolved path is within extract_dir
            try:
                target_path.relative_to(extract_dir)
            except ValueError:
                raise ValueError(f"Unsafe zip entry: '{member}' would extract to '{target_path}' (outside of '{extract_dir}')")
            
            # Extract the member
            zip_file.extract(member, extract_dir)
        
        logger.debug(f"Safely extracted {len(zip_file.namelist())} files to {extract_dir}")
    
    async def download_plugins(
        self, 
        repo_url: str,
        ref: str = "main",
        ref_type: str = "branch",
        selected_plugins: list[str] | None = None,
        force_reinstall: bool = False
    ) -> dict[str, bool]:
        """
        Download and install plugins from a GitHub repository.

        The repository must contain a ``plugins-manifest.json`` at its root
        (see module docstring for the required format). Raises an exception if
        the file is missing.

        Args:
            repo_url: GitHub repository URL (e.g., "github.com/user/repo").
                      Accepts bare domain, https://, and .git suffix forms.
            ref: Git reference — branch name, tag, or full commit SHA.
            ref_type: One of "branch", "tag", or "commit".
            selected_plugins: Domains to install. ``None`` installs all plugins
                              with ``"enabled": true`` in plugins-manifest.json.
            force_reinstall: Re-install even if the plugin directory already exists.

        Returns:
            Dict mapping each plugin domain to ``True`` (installed) or
            ``False`` (skipped or failed).

        Raises:
            ValueError: If ``repo_url`` or ``ref`` fail validation.
            Exception: If the archive cannot be downloaded or
                       plugins-manifest.json is not found in the repository.
        """
        results = {}
        extract_dir = None
        archive_path = None
        
        try:
            logger.info(f"Downloading plugins from {repo_url} (ref: {ref})...")
            
            # Validate ref before use
            self._validate_ref(ref)

            # Parse GitHub URL and download
            owner, repo = self._parse_github_url(repo_url)
            archive_path = await self._download_archive(owner, repo, ref, ref_type)
            
            # Extract archive (use safe ref name for directory)
            safe_ref = self._sanitize_ref(ref)
            extract_dir = self.temp_dir / f"extract_{repo}_{ref_type}_{safe_ref}"
            if extract_dir.exists():
                shutil.rmtree(extract_dir)
            extract_dir.mkdir(parents=True)
            
            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                self._safe_extract(zip_ref, extract_dir)
            
            # Find repo root (GitHub adds prefix like "repo-branch")
            root_dirs = [d for d in extract_dir.iterdir() if d.is_dir()]
            if not root_dirs:
                raise Exception("No directories found in archive")
            
            repo_root = root_dirs[0]
            
            multi_manifest = repo_root / "plugins-manifest.json"
            if not multi_manifest.exists():
                raise Exception("plugins-manifest.json not found in repository")

            results = await self._install_from_manifest(
                repo_root,
                multi_manifest,
                selected_plugins,
                force_reinstall
            )
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
        selected_plugins: list[str] | None,
        force_reinstall: bool
    ) -> dict[str, bool]:
        """Install plugins from plugins-manifest.json"""
        results = {}
        
        try:
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            logger.warning(f"Plugins manifest not found: {manifest_path}")
            return results
        except json.JSONDecodeError as e:
            logger.warning(f"Invalid JSON in plugins manifest {manifest_path}: {e}")
            return results
        
        if not isinstance(manifest, dict):
            logger.warning("Invalid plugins manifest format: expected dict at root")
            return results
        
        logger.debug(f"Found {len(manifest.get('plugins', []))} plugins in manifest")
        
        for plugin_info in manifest.get("plugins", []):
            domain = plugin_info.get("domain")

            if not domain:
                logger.warning("Plugin missing 'domain' field, skipping...")
                continue

            # Validate domain
            if not self._validate_domain(domain):
                logger.warning(f"Invalid plugin domain: {domain}, skipping...")
                results[domain] = False
                continue

            # Skip if not in selected list
            if selected_plugins and domain not in selected_plugins:
                logger.debug(f"Plugin {domain} not in selected list, skipping...")
                continue

            # Skip if disabled (unless explicitly selected)
            if not plugin_info.get("enabled", True) and not selected_plugins:
                logger.debug(f"Plugin {domain} is disabled, skipping...")
                continue

            # Install plugin
            plugin_rel_path = plugin_info.get("path")
            if not plugin_rel_path:
                logger.warning(f"Plugin {domain} missing 'path' in manifest, skipping...")
                results[domain] = False
                continue

            plugin_rel_path = Path(plugin_rel_path)
            if plugin_rel_path.is_absolute():
                logger.warning(f"Plugin {domain} has absolute path in manifest, skipping...")
                results[domain] = False
                continue

            plugin_path = (repo_root / plugin_rel_path).resolve()

            if not self._validate_path_safety(plugin_path, repo_root, f"Plugin {domain} path"):
                results[domain] = False
                continue

            if not plugin_path.exists():
                logger.warning(f"Plugin path not found: {plugin_path}")
                results[domain] = False
                continue

            logger.debug(f"Installing plugin: {domain} ({plugin_info.get('name', domain)})")
            success = await self._install_plugin_directory(
                plugin_path,
                domain,
                plugin_info=plugin_info,
                force_reinstall=force_reinstall
            )

            results[domain] = success

            if success:
                logger.info(f"Plugin installed: {domain}")
            else:
                logger.warning(f"Plugin install failed: {domain}")

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
        encoded_owner = quote(owner, safe='')
        encoded_repo = quote(repo, safe='')
        if ref_type == "branch":
            # Branch: refs/heads/branch-name
            encoded_ref = quote(ref, safe='')
            url = f"https://github.com/{encoded_owner}/{encoded_repo}/archive/refs/heads/{encoded_ref}.zip"
        elif ref_type == "tag":
            # Tag: refs/tags/tag-name
            encoded_ref = quote(ref, safe='')
            url = f"https://github.com/{encoded_owner}/{encoded_repo}/archive/refs/tags/{encoded_ref}.zip"
        elif ref_type == "commit":
            # Commit SHA: directly use the SHA
            encoded_ref = quote(ref, safe='')
            url = f"https://github.com/{encoded_owner}/{encoded_repo}/archive/{encoded_ref}.zip"
        else:
            raise ValueError(f"Invalid ref_type: {ref_type}. Must be 'branch', 'tag', or 'commit'")
        
        # Create a safe filename for the archive
        safe_ref = self._sanitize_ref(ref)
        archive_path = self.temp_dir / f"{repo}-{ref_type}-{safe_ref}.zip"
        
        logger.debug(f"Downloading from {url}...")
        
        timeout = aiohttp.ClientTimeout(total=300)  # 5 minutes timeout
        
        async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
            async with session.get(url) as response:
                if response.status != 200:
                    raise Exception(f"Failed to download archive: HTTP {response.status}")
                
                total_size = int(response.headers.get('content-length', 0))
                downloaded = 0
                last_logged_mb = -1
                
                with open(archive_path, 'wb') as f:
                    async for chunk in response.content.iter_chunked(8192):
                        f.write(chunk)
                        downloaded += len(chunk)
                        
                        # Log progress every MB
                        if total_size > 0:
                            current_mb = downloaded // (1024 * 1024)
                            if current_mb > last_logged_mb:
                                percent = (downloaded / total_size) * 100
                                logger.debug(f"Downloaded {percent:.1f}% ({current_mb}MB)")
                                last_logged_mb = current_mb
        
        logger.debug(f"Archive downloaded to {archive_path}")
        return archive_path
    
    async def _install_plugin_directory(
        self,
        source_dir: Path,
        domain: str,
        plugin_info: dict,
        force_reinstall: bool = False
    ) -> bool:
        """
        Install a single plugin directory and write its manifest.json.

        Args:
            source_dir: Source directory containing plugin files
            domain: Plugin domain/ID (must be pre-validated)
            plugin_info: Plugin entry from plugins-manifest.json
            force_reinstall: If True, overwrite existing plugin

        Returns:
            True if installation successful
        """
        try:
            # Re-validate domain for safety (defense in depth)
            if not self._validate_domain(domain):
                logger.warning(f"Invalid plugin domain: {domain}")
                return False

            if not source_dir.exists():
                logger.warning(f"Source directory does not exist: {source_dir}")
                return False

            target_dir = self.plugins_dir / domain

            # Validate target path safety
            if not self._validate_path_safety(target_dir, self.plugins_dir, "Target directory"):
                return False

            # Check if plugin already exists
            if target_dir.exists():
                if not force_reinstall:
                    logger.warning(f"Plugin {domain} already exists, skipping...")
                    return True

                logger.warning(f"Plugin {domain} already exists, overwriting...")
                shutil.rmtree(target_dir)

            # Copy plugin files
            shutil.copytree(source_dir, target_dir)

            # Write manifest.json derived from the central plugins-manifest entry
            manifest_path = target_dir / "manifest.json"
            manifest_path.write_text(
                json.dumps(plugin_info, ensure_ascii=False, indent=4),
                encoding='utf-8'
            )

            logger.debug(f"Plugin installed to: {target_dir}")
            return True

        except Exception as e:
            logger.warning(f"Failed to install plugin {domain}: {e}", exc_info=True)
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
        # Normalize: add scheme if missing so urlparse works correctly
        if not url.startswith(("https://", "http://")):
            url = "https://" + url

        parsed = urlparse(url)
        if parsed.netloc not in ("github.com", "www.github.com"):
            raise ValueError(f"Invalid GitHub URL: must be a github.com repository, got '{parsed.netloc}'")

        # Strip leading slash, .git suffix, and trailing slash from path
        path = parsed.path.lstrip("/").removesuffix(".git").rstrip("/")

        parts = path.split("/")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise ValueError(f"Invalid GitHub URL: expected github.com/owner/repo, got '{url}'")

        return parts[0], parts[1]
    
    async def fetch_remote_manifest(
        self,
        repo_url: str,
        ref: str = "main",
    ) -> dict | None:
        """
        Fetch plugins-manifest.json from the remote repository without downloading the full archive.

        Uses the raw.githubusercontent.com endpoint to retrieve only the manifest file.

        Args:
            repo_url: GitHub repository URL
            ref: Git reference (branch name, tag, or commit SHA)

        Returns:
            Parsed manifest dict, or None if fetch or validation failed
        """
        try:
            self._validate_ref(ref)

            owner, repo = self._parse_github_url(repo_url)
            url = f"https://raw.githubusercontent.com/{quote(owner, safe='')}/{quote(repo, safe='')}/{quote(ref, safe='/')}/plugins-manifest.json"

            logger.debug(f"Fetching remote manifest from {url}")

            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
                async with session.get(url) as response:
                    if response.status == 404:
                        logger.warning(f"plugins-manifest.json not found in remote repository ({url})")
                        return None
                    if response.status != 200:
                        logger.warning(f"Failed to fetch remote manifest: HTTP {response.status}")
                        return None
                    text = await response.text()

            manifest = json.loads(text)
            if not isinstance(manifest, dict) or "plugins" not in manifest:
                logger.warning("Remote manifest has unexpected format")
                return None

            return manifest

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse remote manifest JSON: {e}")
            return None
        except Exception as e:
            logger.warning(f"Failed to fetch remote manifest: {e}")
            return None

    def cleanup_temp(self):
        """Clean up temporary download directory"""
        if self.temp_dir.exists():
            try:
                shutil.rmtree(self.temp_dir)
                logger.debug("Cleaned up temporary download directory")
            except Exception as e:
                logger.warning(f"Failed to clean up temp directory: {e}")
        
        # Recreate the temp directory for future use
        self.temp_dir.mkdir(exist_ok=True)
