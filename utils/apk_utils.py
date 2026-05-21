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

# Process-lifetime cache for resolve_apk_path's first-call-per-decision log
# dedupe. Module-level (not a mutable default arg) so the scope is explicit
# and there's no temptation to thread a per-call cache through internal APIs.
_RESOLVE_APK_PATH_LOG_CACHE: dict = {}

# Matches: https://github.com/<owner>/<repo>/releases/download/<tag>/<filename>
_RELEASE_URL_RE = re.compile(
    r"https://github\.com/([^/]+)/([^/]+)/releases/download/([^/]+)/(.+)"
)


def get_download_url(
    app_name: str,
    project_root: Path,
    *,
    obfuscated: bool = False,
) -> Optional[str]:
    """Read download_link (or download_link_obfuscated) from an app's metadata.json.

    Returns None if missing. When ``obfuscated=True`` and the app doesn't have
    a ``download_link_obfuscated`` field, falls back to the default
    ``download_link`` and logs a warning — the caller's request for the
    obfuscated variant cannot be honored.
    """
    metadata_file = project_root / "apps" / app_name / "metadata.json"
    if not metadata_file.exists():
        return None
    with open(metadata_file) as f:
        meta = json.load(f)
    if obfuscated:
        url = meta.get("download_link_obfuscated")
        if url:
            return url
        logger.warning(
            "%s: obfuscated APK requested but download_link_obfuscated not set "
            "in metadata.json; falling back to default download_link. The "
            "two-commit publish protocol may be mid-flight (PR A flips "
            "apk_obfuscation, PR B adds the URL), or this app is not on the "
            "toggle.",
            app_name,
        )
    return meta.get("download_link")


def resolve_apk_path(
    *,
    app_name: str,
    runner_obfuscation: str,
    app_metadata: dict,
    vuln_id: Optional[str] = None,
) -> Path:
    """Return the APK path under ``apps/<app>/apk/`` honoring the obfuscation
    toggle, resolved against the app's metadata.

    Returns a Path RELATIVE to ``apps/<app>/`` (matching the existing call-site
    convention in workflows/exploit.py and workflows/redteam.py). Callers
    typically prefix with ``self.app_dir`` to get an absolute path.

    Path layout (mirrors ``build_apk.sh`` output paths):
      off, no vuln:  Path("apk") / "<app>.apk"
      off, vuln_id:  Path("apk") / "<vuln_id>" / "<app>.apk"
      on,  no vuln:  Path("apk") / "obfuscated" / "<app>.apk"
      on,  vuln_id:  Path("apk") / "obfuscated" / "<vuln_id>" / "<app>.apk"

    The first call per (app, decision) emits the resolver's log message at
    its specified level; subsequent calls in the same process are silent to
    avoid log spam from repeated path resolutions during a single experiment.
    """
    from utils.obfuscation_resolver import resolve_obfuscation

    decision = resolve_obfuscation(
        runner_obfuscation,
        app_metadata.get("apk_obfuscation"),
    )
    cache_key = (app_name, decision.effective, decision.log_message)
    if cache_key not in _RESOLVE_APK_PATH_LOG_CACHE:
        log_fn = getattr(logger, decision.log_level)
        log_fn("%s: %s", app_name, decision.log_message)
        _RESOLVE_APK_PATH_LOG_CACHE[cache_key] = True

    base = Path("apk")
    if decision.effective == "on":
        base = base / "obfuscated"
    if vuln_id:
        base = base / vuln_id
    return base / f"{app_name}.apk"


def download_apk(
    app_name: str,
    url: str,
    project_root: Path,
    *,
    force: bool = False,
    obfuscated: bool = False,
) -> Path:
    """Download APK from GitHub release URL into apps/<app>/apk/.

    Supports single APKs and zip bundles.
    Without force, skips files that already exist locally (fill gaps, never overwrite).
    With force, overwrites all existing files.
    When ``obfuscated=True``, downloads into apps/<app>/apk/obfuscated/ so the
    obfuscated bundle never overwrites or commingles with the default bundle.
    Returns the apk directory path that was written to.
    """
    apk_dir = project_root / "apps" / app_name / "apk"
    if obfuscated:
        apk_dir = apk_dir / "obfuscated"
    apk_dir.mkdir(parents=True, exist_ok=True)

    match = _RELEASE_URL_RE.match(url)
    if not match:
        raise ValueError(f"Invalid GitHub release URL: {url}")

    owner, repo, tag, filename = match.groups()

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
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
                timeout=timeout_s,
            )
        except FileNotFoundError as e:
            raise FileNotFoundError(
                "GitHub CLI ('gh') is required by build_type='download-apk' but was "
                "not found on PATH. Install it from https://cli.github.com/ and run "
                "'gh auth login', or switch to build_type='source' / 'skip-apk' in "
                "runner_config.json."
            ) from e
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

        # Filter the bare "." directory entry that `zip -r foo.zip .`
        # produces. Otherwise it lands in `skipped` and prints a misleading
        # "Skipped 1 existing file(s) ... ." warning on every extraction.
        if not relative or relative in (".", "./"):
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


def check_releases(
    app_names: list[str],
    project_root: Path,
    *,
    obfuscated: bool = False,
) -> dict[str, str]:
    """Validate download_links exist on GitHub for the given apps.

    Returns a dict of {app_name: status} where status is 'ok', 'missing',
    'no_link', or 'error: <message>'. When ``obfuscated=True``, validates
    the ``download_link_obfuscated`` URL instead (falling back to
    ``download_link`` with a warning, per ``get_download_url``).
    """
    results = {}
    for name in app_names:
        url = get_download_url(name, project_root, obfuscated=obfuscated)
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
                timeout=timeout_s,
            )
            results[name] = "ok" if result.returncode == 0 else "missing"
        except FileNotFoundError:
            results[name] = "error: gh CLI not found"
            break
    return results
