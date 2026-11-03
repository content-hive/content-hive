"""
Plugin downloader for installing plugin releases from their GitHub repositories.

Each plugin lives in its own repository, listed in the plugin catalog
(see ``contenthive.plugins.catalog``). A release is installed from the
source archive of its tag:

    <repo>-<tag>/
    ├── contenthive.json
    └── plugin/                 # copied to PLUGINS_DIR/<domain>
        ├── __init__.py
        ├── manifest.json       # domain and version must match the catalog release
        └── ...
"""

import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import quote

import aiohttp

from contenthive.logger import logger
from contenthive.plugins.catalog import REPOSITORY_PATTERN, CatalogPlugin, CatalogRelease
from contenthive.utils.path_safety import is_path_within_base, sanitize_path_separators

PLUGIN_SOURCE_DIR = "plugin"


class GitHubPluginDownloader:
    """Download and install plugin releases from GitHub repositories"""

    # Valid plugin domain pattern: lowercase letters, numbers, hyphens, underscores
    VALID_DOMAIN_PATTERN = re.compile(r"^[a-z0-9_-]+$")
    # Valid git ref pattern: alphanumeric, hyphens, dots, underscores, slashes
    VALID_REF_PATTERN = re.compile(r"^[a-zA-Z0-9._/\-]+$")
    _INVALID_REF_SEGMENTS = re.compile(r"(^/|//|/\./|/\.\./|\.\.$|^\.\./)")

    def __init__(self, plugins_dir: Path):
        """
        Initialize the plugin downloader.

        Args:
            plugins_dir: Directory where plugins are installed.
        """
        self.plugins_dir = plugins_dir

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
        if "/" in domain or "\\" in domain:
            logger.warning(f"Domain contains path separators: {domain}")
            return False

        # Check for special path components
        if domain in (".", "..") or domain.startswith("."):
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
                f"Invalid ref '{ref}': only alphanumeric characters, hyphens, dots, underscores,"
                " and slashes are allowed"
            )
        if self._INVALID_REF_SEGMENTS.search(ref):
            raise ValueError(
                f"Invalid ref '{ref}': must not start with '/', contain '//', or include path traversal segments"
            )

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
        if is_path_within_base(target_path, base_path):
            return True
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
            if not is_path_within_base(target_path, extract_dir):
                raise ValueError(
                    f"Unsafe zip entry: '{member}' would extract to '{target_path}' (outside of '{extract_dir}')"
                )

            # Extract the member
            zip_file.extract(member, extract_dir)

        logger.debug(f"Safely extracted {len(zip_file.namelist())} files to {extract_dir}")

    async def install_release(
        self,
        plugin: CatalogPlugin,
        release: CatalogRelease,
        force_reinstall: bool = True,
    ) -> bool:
        """
        Download a plugin release from its repository and install it into the plugins directory.

        The release's ``plugin/manifest.json`` must declare the catalog domain and the
        release version; otherwise the install is rejected.

        Args:
            plugin: Catalog entry of the plugin to install.
            release: Release (stable or beta) selected for this plugin.
            force_reinstall: Re-install even if the plugin directory already exists.

        Returns:
            True if the plugin was installed, False otherwise.
        """
        domain = plugin.domain
        try:
            if not self._validate_domain(domain):
                return False
            if not REPOSITORY_PATTERN.match(plugin.repository):
                logger.warning(f"Invalid plugin repository for {domain}: {plugin.repository}")
                return False
            self._validate_ref(release.tag)

            logger.info(f"Downloading plugin {domain} {release.version} from {plugin.repository} ({release.tag})...")

            with tempfile.TemporaryDirectory(prefix="contenthive_plugin_") as tmp:
                tmp_path = Path(tmp)
                archive_path = await self._download_archive(plugin.repository, release.tag, tmp_path)

                extract_dir = tmp_path / "extract"
                extract_dir.mkdir()
                with zipfile.ZipFile(archive_path, "r") as zip_ref:
                    self._safe_extract(zip_ref, extract_dir)

                # GitHub archives contain a single top-level directory like "<repo>-<tag>"
                root_dirs = [d for d in extract_dir.iterdir() if d.is_dir()]
                if len(root_dirs) != 1:
                    raise ValueError(f"Expected one top-level directory in archive, found {len(root_dirs)}")

                source_dir = root_dirs[0] / PLUGIN_SOURCE_DIR
                if not source_dir.is_dir():
                    raise ValueError(f"'{PLUGIN_SOURCE_DIR}/' directory not found in {release.tag}")

                self._check_source_manifest(source_dir, domain, release.version)
                installed = self._install_plugin_directory(source_dir, domain, force_reinstall)

            if installed:
                logger.info(f"Plugin installed: {domain} {release.version}")
            return installed

        except Exception as e:
            logger.warning(f"Plugin install failed: {domain} ({e})", exc_info=True)
            return False

    def _check_source_manifest(self, source_dir: Path, domain: str, version: str) -> None:
        """Raise ValueError unless plugin/manifest.json matches the catalog domain and release version."""
        manifest_path = source_dir / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except FileNotFoundError as e:
            raise ValueError(f"{PLUGIN_SOURCE_DIR}/manifest.json not found") from e
        except json.JSONDecodeError as e:
            raise ValueError(f"{PLUGIN_SOURCE_DIR}/manifest.json is not valid JSON: {e}") from e

        if not isinstance(manifest, dict):
            raise ValueError(f"{PLUGIN_SOURCE_DIR}/manifest.json must be a JSON object")
        if manifest.get("domain") != domain:
            raise ValueError(f"manifest domain {manifest.get('domain')!r} does not match catalog domain {domain!r}")
        if manifest.get("version") != version:
            raise ValueError(f"manifest version {manifest.get('version')!r} does not match release {version!r}")

    async def _download_archive(self, repository: str, tag: str, tmp_dir: Path) -> Path:
        """
        Download the source archive of a release tag from GitHub.

        Args:
            repository: Repository as ``owner/repo``
            tag: Release tag
            tmp_dir: Directory for the downloaded archive

        Returns:
            Path to downloaded archive file
        """
        owner, repo = repository.split("/", 1)
        url = (
            f"https://github.com/{quote(owner, safe='')}/{quote(repo, safe='')}"
            f"/archive/refs/tags/{quote(tag, safe='')}.zip"
        )
        archive_path = tmp_dir / f"{repo}-{sanitize_path_separators(tag)}.zip"

        logger.debug(f"Downloading from {url}...")

        timeout = aiohttp.ClientTimeout(total=300)  # 5 minutes timeout

        async with (
            aiohttp.ClientSession(timeout=timeout, trust_env=True) as session,
            session.get(url) as response,
        ):
            if response.status != 200:
                raise Exception(f"Failed to download archive: HTTP {response.status}")

            total_size = int(response.headers.get("content-length", 0))
            downloaded = 0
            last_logged_mb = -1

            with open(archive_path, "wb") as f:
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

    def _install_plugin_directory(self, source_dir: Path, domain: str, force_reinstall: bool) -> bool:
        """
        Copy a validated plugin directory to PLUGINS_DIR/<domain>.

        Args:
            source_dir: Source directory containing plugin files and manifest.json
            domain: Plugin domain/ID (must be pre-validated)
            force_reinstall: If True, overwrite existing plugin

        Returns:
            True if installation successful
        """
        # Re-validate domain for safety (defense in depth)
        if not self._validate_domain(domain):
            return False

        target_dir = self.plugins_dir / domain
        if not self._validate_path_safety(target_dir, self.plugins_dir, "Target directory"):
            return False

        if target_dir.exists():
            if not force_reinstall:
                logger.warning(f"Plugin {domain} already exists, skipping...")
                return True
            logger.warning(f"Plugin {domain} already exists, overwriting...")
            shutil.rmtree(target_dir)

        shutil.copytree(source_dir, target_dir)
        logger.debug(f"Plugin installed to: {target_dir}")
        return True
