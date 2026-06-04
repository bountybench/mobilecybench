#!/usr/bin/env python3
"""Download pre-built APKs from GitHub releases.

Reads the download_link from each app's metadata.json and fetches the APK
(or zip bundle) via the `gh` CLI. Existing files are preserved unless --force
is used.

Usage:
    python download_apk.py <app_name>           # download APK (skip existing)
    python download_apk.py --force <app_name>   # download and overwrite existing
    python download_apk.py --check [app_name]   # validate download_links exist on GitHub
"""

import logging
import sys
from pathlib import Path

from utils.apk_utils import (
    check_releases,
    download_apk,
    get_download_url,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


HELP = """\
Download pre-built APKs from GitHub releases.

Usage:
  {prog} <app_name>                  Download APK (skips existing files)
  {prog} --force <app_name>          Download and overwrite existing files
  {prog} --check [app_name]          Validate download_links against GitHub releases
  {prog} --obfuscated <app_name>     Download the R8-minified APK bundle

Flags (order-insensitive):
  --force         Overwrite existing downloaded files.
  --obfuscated    Use download_link_obfuscated (the R8-minified bundle) instead
                  of the default download_link (the un-minified bundle).
                  If the app's metadata.json does not define
                  download_link_obfuscated, the command fails instead of
                  falling back to the default APK.
  --check         Validate URLs on GitHub instead of downloading. Combine with
                  --obfuscated to validate the obfuscated URLs.

Examples:
  {prog} conversations                       Download conversations APK
  {prog} --force conversations               Re-download conversations APK
  {prog} --obfuscated conversations          Download R8-minified bundle
  {prog} --force --obfuscated conversations  Re-download minified bundle
  {prog} --check                             Check all apps' download_links
  {prog} --check conversations               Check just conversations' download_link
  {prog} --check --obfuscated                Check all apps' obfuscated links
"""


def _check_failures(
    results: dict[str, str],
    *,
    obfuscated: bool = False,
) -> dict[str, str]:
    """Return check results that should make ``--check`` exit non-zero.

    Default checks keep the historical behavior of treating a missing
    ``download_link`` as informational, because not every app has a prebuilt
    default APK. Obfuscated checks are stricter: direct ``--obfuscated``
    downloads refuse to fetch without ``download_link_obfuscated``, so
    ``--check --obfuscated`` must fail on ``no_link`` too.
    """
    allowed_statuses = {"ok"}
    if not obfuscated:
        allowed_statuses.add("no_link")
    return {
        name: status
        for name, status in results.items()
        if status not in allowed_statuses
    }


def main():
    project_root = Path(__file__).resolve().parent
    apps_dir = project_root / "apps"
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    positional = [a for a in sys.argv[1:] if not a.startswith("--")]

    if "--help" in flags or "-h" in flags:
        print(HELP.format(prog=sys.argv[0]))
        sys.exit(0)

    obfuscated = "--obfuscated" in flags

    if "--check" in flags:
        app_names = (
            positional
            if positional
            else sorted(d.name for d in apps_dir.iterdir() if d.is_dir())
        )
        results = check_releases(app_names, project_root, obfuscated=obfuscated)
        for name, status in sorted(results.items()):
            print(f"  {status:<10} {name}")
        failures = _check_failures(results, obfuscated=obfuscated)
        if failures:
            if obfuscated:
                message = (
                    f"\n{len(failures)} app(s) have missing or broken "
                    "download_link_obfuscated values."
                )
            else:
                message = f"\n{len(failures)} app(s) have broken download_links."
            print(message, file=sys.stderr)
        sys.exit(1 if failures else 0)

    if not positional:
        print(HELP.format(prog=sys.argv[0]), file=sys.stderr)
        sys.exit(1)

    app_name = positional[0]
    if not (apps_dir / app_name).exists():
        print(f"Error: apps/{app_name}/ not found", file=sys.stderr)
        sys.exit(1)

    url = get_download_url(app_name, project_root, obfuscated=obfuscated)
    if not url:
        field = "download_link_obfuscated" if obfuscated else "download_link"
        print(f"Error: No {field} in apps/{app_name}/metadata.json", file=sys.stderr)
        print("\nTo fix, build and publish the APK:", file=sys.stderr)
        print(f"  ./build_apk.sh {app_name}", file=sys.stderr)
        print(f"  ./publish_apk_bundle.sh apps/{app_name}", file=sys.stderr)
        sys.exit(1)

    download_apk(
        app_name,
        url,
        project_root,
        force="--force" in flags,
        obfuscated=obfuscated,
    )


if __name__ == "__main__":
    main()
