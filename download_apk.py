#!/usr/bin/env python3
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


def check_directory():
    """Check that we're running from the repository root"""
    cwd = Path.cwd()
    apps_dir = cwd / "apps"
    if not apps_dir.exists() or not apps_dir.is_dir():
        print(
            "This script must be run from the repository root (apps/ directory not found)",
            file=sys.stderr,
        )
        sys.exit(1)


def download_apk(app_name, url):
    """Download APK from GitHub release. Supports single APKs and zip bundles.

    Only extracts files that don't already exist locally (fill gaps, never overwrite).
    """
    apk_dir = Path(f"apps/{app_name}/apk")
    apk_dir.mkdir(parents=True, exist_ok=True)

    # Parse GitHub release URL
    match = re.match(
        r"https://github\.com/([^/]+)/([^/]+)/releases/download/([^/]+)/(.+)", url
    )
    if not match:
        print(f"Invalid GitHub release URL: {url}", file=sys.stderr)
        sys.exit(1)

    owner, repo, tag, filename = match.groups()

    with tempfile.TemporaryDirectory() as tmpdir:
        subprocess.run(
            [
                "gh",
                "release",
                "download",
                tag,
                "--repo",
                f"{owner}/{repo}",
                "--pattern",
                filename,
                "--dir",
                tmpdir,
                "--clobber",
            ],
            check=True,
        )
        tmp_path = Path(tmpdir) / filename

        # Handle zip bundles vs single APKs
        try:
            with zipfile.ZipFile(tmp_path, "r") as zf:
                if any(n.endswith(".apk") for n in zf.namelist()):
                    _extract_zip_no_overwrite(zf, apk_dir)
                    print(f"Extracted APK bundle to {apk_dir} (skipped existing files)")
                    return
        except zipfile.BadZipFile:
            pass

        # Single APK file - only copy if doesn't exist
        apk_path = apk_dir / f"{app_name}.apk"
        if not apk_path.exists():
            shutil.move(str(tmp_path), str(apk_path))
            print(f"Downloaded APK to {apk_path}")
        else:
            print(f"APK already exists at {apk_path}, skipping")


def _extract_zip_no_overwrite(zf: zipfile.ZipFile, apk_dir: Path):
    """Extract zip contents without overwriting existing files."""
    # Check if zip has apk/ prefix
    has_prefix = any(n.startswith("apk/") for n in zf.namelist())
    prefix = "apk/" if has_prefix else ""

    for member in zf.namelist():
        # Strip apk/ prefix if present
        if prefix and member.startswith(prefix):
            relative = member[len(prefix) :]
        else:
            relative = member

        if not relative:
            continue

        dest = apk_dir / relative

        if member.endswith("/"):
            dest.mkdir(parents=True, exist_ok=True)
        elif not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(dest, "wb") as dst:
                dst.write(src.read())
            print(f"  Extracted: {relative}")
        else:
            print(f"  Skipped (exists): {relative}")


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <app_name>", file=sys.stderr)
        sys.exit(1)

    check_directory()

    app_name = sys.argv[1]
    app_dir = Path(f"apps/{app_name}")

    if not app_dir.exists():
        print(f"App directory not found: {app_dir}", file=sys.stderr)
        sys.exit(1)

    metadata_file = app_dir / "metadata.json"
    if not metadata_file.exists():
        print(f"Metadata file not found: {metadata_file}", file=sys.stderr)
        sys.exit(1)

    with open(metadata_file) as f:
        metadata = json.load(f)

    apk_url = metadata.get("download_link")
    if not apk_url:
        print(f"No download_link in {metadata_file}", file=sys.stderr)
        print("To fix: build APKs and publish:", file=sys.stderr)
        print(f"  ./build_apk.sh {app_name}", file=sys.stderr)
        print(f"  ./publish_apk_bundle.sh apps/{app_name}", file=sys.stderr)
        sys.exit(1)

    download_apk(app_name, apk_url)


if __name__ == "__main__":
    main()
