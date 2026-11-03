"""
Plugin catalog client.

The catalog is published by https://github.com/content-hive/plugins and lists every
plugin repository with its latest stable and pre-release GitHub Releases:

    {
      "schema": 1,
      "generated_at": "...",
      "plugins": [
        {
          "repository": "content-hive/plugin-douyin",
          "domain": "douyin",
          "name": "抖音",
          "description": "...",
          "license": "MIT",
          "min_core_version": "0.1.0",
          "requirements": ["gmssl>=3.2.2"],
          "disclaimer": "...",
          "stable": {"version": "0.1.10", "tag": "v0.1.10", "release_notes": "...", "published_at": "..."},
          "beta": null
        }
      ],
      "removed": []
    }
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any

import aiohttp
from packaging.version import InvalidVersion, Version

from contenthive.const import APP_VERSION
from contenthive.logger import logger

CATALOG_URL = "https://content-hive.github.io/plugins/catalog.json"
CATALOG_SCHEMA = 1

REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")
DOMAIN_PATTERN = re.compile(r"^[a-z0-9_-]{1,100}$")


class CatalogError(Exception):
    """Raised when the plugin catalog cannot be fetched or parsed."""


@dataclass(frozen=True)
class CatalogRelease:
    version: str
    tag: str
    release_notes: str | None = None
    published_at: str | None = None


@dataclass(frozen=True)
class CatalogPlugin:
    repository: str
    domain: str
    name: str
    stable: CatalogRelease | None
    beta: CatalogRelease | None
    description: str | None = None
    license: str | None = None
    min_core_version: str | None = None
    requirements: list[str] = field(default_factory=list)
    disclaimer: str | None = None

    def select_release(self, prerelease: bool) -> CatalogRelease | None:
        """Return the release this plugin should install, or None if the chosen track has none."""
        if prerelease and self.beta is not None:
            return self.beta
        return self.stable

    def display_release(self, prerelease: bool) -> CatalogRelease:
        """Return the selected release, falling back to the other track for display only."""
        release = self.select_release(prerelease) or self.beta or self.stable
        assert release is not None  # _parse_plugin guarantees at least one release
        return release


def _optional_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _parse_release(data: Any) -> CatalogRelease | None:
    if not isinstance(data, dict):
        return None
    version, tag = data.get("version"), data.get("tag")
    if not isinstance(version, str) or not isinstance(tag, str) or tag != f"v{version}":
        raise ValueError(f"invalid release {data!r}")
    Version(version)
    return CatalogRelease(
        version=version,
        tag=tag,
        release_notes=_optional_str(data.get("release_notes")),
        published_at=_optional_str(data.get("published_at")),
    )


def _parse_plugin(data: Any) -> CatalogPlugin:
    if not isinstance(data, dict):
        raise ValueError("entry is not an object")
    repository, domain, name = data.get("repository"), data.get("domain"), data.get("name")
    if not isinstance(repository, str) or not REPOSITORY_PATTERN.match(repository):
        raise ValueError(f"invalid repository {repository!r}")
    if not isinstance(domain, str) or not DOMAIN_PATTERN.match(domain):
        raise ValueError(f"invalid domain {domain!r}")
    if not isinstance(name, str) or not name:
        raise ValueError("missing name")

    stable = _parse_release(data.get("stable"))
    beta = _parse_release(data.get("beta"))
    if stable is None and beta is None:
        raise ValueError("no stable or beta release")

    requirements = data.get("requirements") or []
    if not isinstance(requirements, list) or not all(isinstance(r, str) for r in requirements):
        raise ValueError("requirements must be a list of strings")

    return CatalogPlugin(
        repository=repository,
        domain=domain,
        name=name,
        stable=stable,
        beta=beta,
        description=_optional_str(data.get("description")),
        license=_optional_str(data.get("license")),
        min_core_version=_optional_str(data.get("min_core_version")),
        requirements=requirements,
        disclaimer=_optional_str(data.get("disclaimer")),
    )


def _is_core_supported(plugin: CatalogPlugin) -> bool:
    if plugin.min_core_version is None:
        return True
    try:
        return Version(APP_VERSION) >= Version(plugin.min_core_version)
    except InvalidVersion:
        logger.warning(
            "Plugin %s: cannot compare min_core_version %r with core %r",
            plugin.domain,
            plugin.min_core_version,
            APP_VERSION,
        )
        return False


def parse_catalog(data: Any) -> dict[str, CatalogPlugin]:
    """Validate catalog JSON and return supported plugins keyed by domain.

    Malformed entries and plugins that need a newer core are skipped with a log message.
    """
    if not isinstance(data, dict) or data.get("schema") != CATALOG_SCHEMA or not isinstance(data.get("plugins"), list):
        raise CatalogError(f"Unsupported plugin catalog format (expected schema {CATALOG_SCHEMA})")

    plugins: dict[str, CatalogPlugin] = {}
    for entry in data["plugins"]:
        try:
            plugin = _parse_plugin(entry)
        except (ValueError, InvalidVersion) as e:
            logger.warning("Skipping invalid plugin catalog entry: %s", e)
            continue
        if plugin.domain in plugins:
            logger.warning("Skipping duplicate plugin domain in catalog: %s", plugin.domain)
            continue
        if not _is_core_supported(plugin):
            logger.info(
                "Skipping plugin %s: requires Content Hive %s (current %s)",
                plugin.domain,
                plugin.min_core_version,
                APP_VERSION,
            )
            continue
        plugins[plugin.domain] = plugin
    return plugins


async def fetch_catalog() -> dict[str, CatalogPlugin]:
    """Download the plugin catalog and return supported plugins keyed by domain.

    Raises:
        CatalogError: If the catalog cannot be downloaded or has an unsupported format.
    """
    logger.debug(f"Fetching plugin catalog from {CATALOG_URL}")
    timeout = aiohttp.ClientTimeout(total=30)
    try:
        async with (
            aiohttp.ClientSession(timeout=timeout, trust_env=True) as session,
            session.get(CATALOG_URL) as response,
        ):
            if response.status != 200:
                raise CatalogError(f"Failed to fetch plugin catalog: HTTP {response.status}")
            text = await response.text()
    except (aiohttp.ClientError, TimeoutError) as e:
        raise CatalogError(f"Failed to fetch plugin catalog: {e}") from e

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise CatalogError(f"Plugin catalog is not valid JSON: {e}") from e
    return parse_catalog(data)
