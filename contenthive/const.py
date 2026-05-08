import tomllib
from pathlib import Path
from typing import Final

APP_NAME: Final = "Content Hive"


def _read_version() -> str:
    toml_path = Path(__file__).parent.parent / "pyproject.toml"
    if toml_path.exists():
        with open(toml_path, "rb") as f:
            return tomllib.load(f)["project"]["version"]
    return "unknown"


APP_VERSION: Final = _read_version()
