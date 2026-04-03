"""APK building, downloading, and handling utilities."""

import json
import logging
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Optional
from utils.command_executor import CommandExecutor

logger = logging.getLogger("MobileCyBench.apk_utils")
timeout_s = 600

# Matches: https://github.com/<owner>/<repo>/releases/download/<tag>/<filename>
_RELEASE_URL_RE = re.compile(
    r"https://github\.com/([^/]+)/([^/]+)/releases/download/([^/]+)/(.+)"
)


def get_download_url(app_name: str, project_root: Path) -> Optional[str]:
    """Read download_link from an app's metadata.json. Returns None if missing."""
    metadata_file = project_root / "apps" / app_name / "metadata.json"
    if not metadata_file.exists():
        return None
    with open(metadata_file) as f:
        return json.load(f).get("download_link")


def download_apk(
    app_name: str, url: str, project_root: Path, *, force: bool = False
) -> Path:
    """Download APK from GitHub release URL into apps/<app>/apk/.

    Supports single APKs and zip bundles.
    Without force, skips files that already exist locally (fill gaps, never overwrite).
    With force, overwrites all existing files.
    Returns the apk directory path.
    """
    apk_dir = project_root / "apps" / app_name / "apk"
    apk_dir.mkdir(parents=True, exist_ok=True)

    match = _RELEASE_URL_RE.match(url)
    if not match:
        raise ValueError(f"Invalid GitHub release URL: {url}")

    owner, repo, tag, filename = match.groups()

    with tempfile.TemporaryDirectory() as tmpdir:
        CommandExecutor().run(
            f"gh release download {tag} --repo {owner}/{repo} --pattern {filename} --dir {tmpdir} --clobber",
            check=True,
            timeout=timeout_s
        )
        tmp_path = Path(tmpdir) / filename
        if not tmp_path.exists():
            raise FileNotFoundError(
                f"gh release download succeeded but {filename} not found in output. "
                f"Asset may have been renamed in release {tag}."
            )

        # APK files are themselves zip files, so check extension first
        is_bundle = not filename.endswith(".apk") and zipfile.is_zipfile(tmp_path)

        if is_bundle:
            with zipfile.ZipFile(tmp_path, "r") as zf:
                apk_entries = [n for n in zf.namelist() if n.endswith(".apk")]
                if not apk_entries:
                    raise ValueError(
                        f"Zip bundle {filename} contains no .apk files: {zf.namelist()}"
                    )
                _extract_zip(zf, apk_dir, force=force)
            return apk_dir

        # Single APK file
        apk_path = apk_dir / f"{app_name}.apk"
        if not apk_path.exists() or force:
            shutil.move(str(tmp_path), str(apk_path))
            logger.info("Downloaded APK to %s", apk_path)
        elif apk_path.stat().st_size == 0:
            logger.warning(
                "Replacing empty file at %s (likely interrupted download)", apk_path
            )
            shutil.move(str(tmp_path), str(apk_path))
        else:
            logger.warning(
                "APK already exists at %s, skipping download (use --force to overwrite)",
                apk_path,
            )

    return apk_dir


def _extract_zip(zf: zipfile.ZipFile, apk_dir: Path, *, force: bool = False) -> None:
    """Extract zip contents into apk_dir.

    Without force, skips existing files and logs a warning.
    With force, overwrites everything.
    """
    has_prefix = any(n.startswith("apk/") for n in zf.namelist())
    prefix = "apk/" if has_prefix else ""

    extracted, skipped = [], []
    for member in zf.namelist():
        if prefix and member.startswith(prefix):
            relative = member[len(prefix) :]
        else:
            relative = member

        if not relative:
            continue

        dest = apk_dir / relative

        if member.endswith("/"):
            dest.mkdir(parents=True, exist_ok=True)
        elif not dest.exists() or force or dest.stat().st_size == 0:
            if dest.exists() and dest.stat().st_size == 0:
                logger.warning("Replacing empty file: %s", relative)
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(dest, "wb") as dst:
                dst.write(src.read())
            extracted.append(relative)
        else:
            skipped.append(relative)

    if extracted:
        logger.info("Extracted %d file(s) to %s", len(extracted), apk_dir)
    if skipped:
        logger.warning(
            "Skipped %d existing file(s) in %s: %s (use --force to overwrite)",
            len(skipped),
            apk_dir,
            ", ".join(skipped),
        )


def check_releases(app_names: list[str], project_root: Path) -> dict[str, str]:
    """Validate download_links exist on GitHub for the given apps.

    Returns a dict of {app_name: status} where status is 'ok', 'missing',
    'no_link', or 'error: <message>'.
    """
    results = {}
    for name in app_names:
        url = get_download_url(name, project_root)
        if not url:
            results[name] = "no_link"
            continue
        match = _RELEASE_URL_RE.match(url)
        if not match:
            results[name] = f"error: invalid URL {url}"
            continue
        owner, repo, tag, _ = match.groups()
        try:
            result = CommandExecutor().run(
                f"gh release view {tag} --repo {owner}/{repo}",
                capture_output=True,
                timeout=timeout_s
            )
            results[name] = "ok" if result.returncode == 0 else "missing"
        except FileNotFoundError:
            results[name] = "error: gh CLI not found"
            break
    return results
