"""Check a GitHub Release tag against its pre-release checkbox.

Reads ``RELEASE_TAG`` and ``RELEASE_PRERELEASE`` from the environment and appends
``VERSION`` and ``CHANNEL`` to ``GITHUB_OUTPUT``. Dev versions and versions that
are not valid Docker tags are rejected.
"""

import os
import re
import sys

from packaging.version import InvalidVersion, Version

# Docker tag: ASCII letter, digit, or underscore, then up to 127 of those plus "." and "-".
_DOCKER_TAG = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}\Z")


def main() -> None:
    tag = os.environ["RELEASE_TAG"]
    if not tag.startswith("v") or len(tag) == 1:
        sys.exit(f"release tag must look like vX.Y.Z, got {tag!r}")

    raw = tag[1:]
    prerelease = os.environ["RELEASE_PRERELEASE"].lower() == "true"
    try:
        parsed = Version(raw)
    except InvalidVersion as exc:
        sys.exit(f"invalid version {raw!r}: {exc}")

    if parsed.is_devrelease:
        sys.exit(f"dev versions stay local and are not published: {raw}")

    if prerelease != parsed.is_prerelease:
        if prerelease:
            sys.exit(f"pre-release checkbox is set, but {raw} is a final version")
        sys.exit(f"pre-release checkbox is unset, but {raw} is a pre-release version")

    if _DOCKER_TAG.fullmatch(raw) is None:
        sys.exit(f"version {raw!r} is not a valid Docker tag")

    channel = "beta" if parsed.is_prerelease else "latest"
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as fh:
        fh.write(f"VERSION={raw}\n")
        fh.write(f"CHANNEL={channel}\n")
    print(f"version={raw} channel={channel}")


if __name__ == "__main__":
    main()
