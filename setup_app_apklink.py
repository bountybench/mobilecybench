#!/usr/bin/env python3
import json
import os
import re
import subprocess
import sys
from pathlib import Path


def check_directory():
    """Check that we're running from within the mobilecybench directory"""
    cwd = os.getcwd()
    if "mobilecybench" not in cwd:
        print(
            "This script must be run from within the mobilecybench directory",
            file=sys.stderr,
        )
        sys.exit(1)


def download_apk(app_name, url):
    """Download APK from the given URL"""
    apk_dir = Path(f"apps/{app_name}/apk")
    apk_dir.mkdir(parents=True, exist_ok=True)
    apk_path = apk_dir / f"{app_name}.apk"

    # Use gh CLI for GitHub releases
    if url.startswith("https://github.com/"):
        # Parse GitHub release URL
        # Format: https://github.com/{owner}/{repo}/releases/download/{tag}/{filename}
        match = re.match(
            r"https://github\.com/([^/]+)/([^/]+)/releases/download/([^/]+)/(.+)", url
        )
        if not match:
            print(f"Invalid GitHub release URL format: {url}", file=sys.stderr)
            sys.exit(1)

        owner, repo, tag, filename = match.groups()
        repo_full = f"{owner}/{repo}"

        # Download using gh CLI
        gh_args = [
            "gh",
            "release",
            "download",
            tag,
            "--repo",
            repo_full,
            "--pattern",
            filename,
            "--dir",
            str(apk_dir),
            "--clobber",
        ]
        subprocess.run(gh_args, check=True)

        # Rename to expected filename if different
        downloaded_file = apk_dir / filename
        if downloaded_file != apk_path:
            downloaded_file.rename(apk_path)
    else:
        # Use curl for non-GitHub URLs
        curl_args = [
            "curl",
            "-L",
            "--fail",
            "--retry",
            "3",
            "--retry-connrefused",
            "-o",
            str(apk_path),
            url,
        ]
        subprocess.run(curl_args, check=True)


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <app_name>", file=sys.stderr)
        sys.exit(1)

    check_directory()

    app_name = sys.argv[1]
    metadata_file = Path(f"apps/{app_name}/metadata.json")

    if not metadata_file.exists():
        print(f"Metadata file not found: {metadata_file}", file=sys.stderr)
        sys.exit(1)

    with open(metadata_file) as f:
        metadata = json.load(f)

    apk_url = metadata.get("download_link")
    if not apk_url:
        print(f"Could not find download_link in {metadata_file}", file=sys.stderr)
        sys.exit(1)

    download_apk(app_name, apk_url)


if __name__ == "__main__":
    main()
