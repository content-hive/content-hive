#!/usr/bin/env python3
import argparse
import re
from pathlib import Path

def write_version(version: str) -> None:
    const_path = Path("contenthive/const.py")
    content = const_path.read_text()

    content = re.sub(
        "APP_VERSION: Final = .*\n",
        f'APP_VERSION: Final = "{version}"\n',
        content
    )

    const_path.write_text(content)

def main():
    parser = argparse.ArgumentParser(description="Update the version of content hive")
    parser.add_argument("version", help="The new version to set")
    arguments = parser.parse_args()
    write_version(arguments.version)

if __name__ == "__main__":
    main()
