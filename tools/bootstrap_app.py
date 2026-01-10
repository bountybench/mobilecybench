#!/usr/bin/env python3
"""
Bootstrap a new app entry under apps/<app_name> by creating metadata.json
and wiring the codebase as a git submodule.

Usage example:
  python3 tools/bootstrap_app.py conversations \
    --gh-link https://github.com/cy-suite/conversations.git \
    --package-name eu.siacs.conversations \
    --app-server http://conversations-app:8080 \
    --commit-version 60a32b1 \
    --container-names conversations-app,conversations-db

The script will:
  1) Create apps/<app_name>/metadata.json (overwrites with --force).
  2) Add git submodule at apps/<app_name>/codebase.
  3) Clone and checkout the requested commit/branch/tag in the submodule.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str], *, cwd: Path | None = None) -> None:
    """Run a shell command with error reporting."""
    try:
        subprocess.run(cmd, cwd=cwd, check=True)
    except subprocess.CalledProcessError as exc:
        sys.exit(f"Command failed ({' '.join(cmd)}): {exc}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap a new app directory")
    parser.add_argument("app_name", help="Name of the app folder to create under apps/")
    parser.add_argument(
        "--gh-link", required=True, help="GitHub URL of the cy-suite fork"
    )
    parser.add_argument(
        "--commit-version",
        default="main",
        help="Commit/branch/tag to checkout inside the submodule (default: main)",
    )
    parser.add_argument(
        "--package-name",
        help=(
            "Android applicationId/namespace. If omitted, the script will attempt to "
            "infer it from the codebase (build.gradle/AndroidManifest.xml)."
        ),
    )
    parser.add_argument(
        "--app-server",
        required=True,
        help="Container URL the app will talk to (matches metadata schema)",
    )
    parser.add_argument(
        "--sdk",
        default="35",
        help="Target/compile SDK version to record in metadata (default: 35)",
    )
    parser.add_argument(
        "--java",
        default="17",
        help="Java version needed to build the app (default: 17)",
    )
    parser.add_argument(
        "--emulator-server",
        default="http://10.0.2.2:8080",
        help="Server URL reachable from the emulator (default: http://10.0.2.2:8080)",
    )
    parser.add_argument("--download-link", help="Direct APK download URL (optional)")
    parser.add_argument("--username", default="", help="App login username (optional)")
    parser.add_argument("--password", default="", help="App login password (optional)")
    parser.add_argument(
        "--container-names",
        default="",
        help="Comma-separated docker container names to record in metadata",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing metadata and re-link submodule if present",
    )
    return parser.parse_args()


def ensure_paths(app_dir: Path, force: bool) -> None:
    if app_dir.exists() and any(app_dir.iterdir()) and not force:
        sys.exit(
            f"App directory already exists and is not empty: {app_dir}. "
            "Use --force to overwrite metadata and re-link the submodule."
        )
    app_dir.mkdir(parents=True, exist_ok=True)


def write_metadata(app_dir: Path, args: argparse.Namespace) -> Path:
    containers = [c.strip() for c in args.container_names.split(",") if c.strip()]
    metadata = {
        "gh_link": args.gh_link,
        "commit_version": args.commit_version,
        "sdk": args.sdk,
        "java": args.java,
        "emulator_server": args.emulator_server,
        "app_server": args.app_server,
        "username": args.username,
        "password": args.password,
        "package_name": args.package_name,
        "container_names": containers,
    }
    if args.download_link:
        metadata["download_link"] = args.download_link

    metadata_path = app_dir / "metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return metadata_path


def configure_submodule(
    project_root: Path, app_dir: Path, args: argparse.Namespace
) -> None:
    submodule_path = app_dir / "codebase"
    relative_submodule = submodule_path.relative_to(project_root)

    # If submodule already exists and force not set, abort to avoid clobbering worktree.
    git_dir = submodule_path / ".git"
    if git_dir.exists() and not args.force:
        sys.exit(
            f"Submodule already exists at {relative_submodule}. "
            "Use --force to re-link if you want to reset it."
        )

    add_cmd = ["git", "submodule", "add"]
    if args.force:
        add_cmd.append("--force")
    add_cmd.extend([args.gh_link, str(relative_submodule)])

    run(add_cmd, cwd=project_root)
    run(
        [
            "git",
            "submodule",
            "update",
            "--init",
            "--recursive",
            str(relative_submodule),
        ],
        cwd=project_root,
    )
    run(
        ["git", "-C", str(submodule_path), "fetch", "--all", "--tags"], cwd=project_root
    )
    if args.commit_version:
        run(
            ["git", "-C", str(submodule_path), "checkout", args.commit_version],
            cwd=project_root,
        )


def infer_package_name(submodule_path: Path) -> str:
    """Infer applicationId/namespace from Gradle or AndroidManifest."""
    gradle_files = sorted(submodule_path.glob("**/build.gradle*"))

    def _search_gradle(pattern: str) -> str | None:
        best: tuple[int, str] | None = None

        def priority(path: Path) -> int:
            posix = path.as_posix()
            if "app/build.gradle" in posix:
                return 0
            if "android/app/build.gradle" in posix:
                return 0
            if "app" in path.parts:
                return 1
            return 2

        for gf in gradle_files:
            if "node_modules" in gf.parts:
                continue
            try:
                text = gf.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            match = re.search(pattern, text, flags=re.MULTILINE)
            if match:
                candidate = (priority(gf), match.group(1))
                if best is None or candidate[0] < best[0]:
                    best = candidate
        return best[1] if best else None

    # Prefer explicit applicationId
    app_id = _search_gradle(r"^\s*applicationId\s*[:=]?\s*\(?\s*[\"']([^\"']+)")
    if app_id:
        return app_id

    # Fallback to namespace (commonly equals applicationId)
    ns = _search_gradle(r"^\s*namespace\s*[:=]?\s*\(?\s*[\"']([^\"']+)")
    if ns:
        return ns

    # Last resort: AndroidManifest package attribute
    for manifest in sorted(submodule_path.glob("**/AndroidManifest.xml")):
        if "node_modules" in manifest.parts:
            continue
        try:
            text = manifest.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        pkg_match = re.search(r"package=\"([^\"]+)\"", text)
        if pkg_match:
            return pkg_match.group(1)

    raise RuntimeError(
        "Unable to infer applicationId/namespace; please pass --package-name explicitly"
    )


def main() -> None:
    args = parse_args()
    project_root = Path(__file__).resolve().parent.parent

    if not (project_root / ".git").exists():
        sys.exit("This script must be run from within the git repository root")

    app_dir = project_root / "apps" / args.app_name
    ensure_paths(app_dir, args.force)

    configure_submodule(project_root, app_dir, args)

    if not args.package_name:
        inferred = infer_package_name(app_dir / "codebase")
        args.package_name = inferred

    metadata_path = write_metadata(app_dir, args)

    print(f"✓ metadata.json written to {metadata_path.relative_to(project_root)}")
    print(
        "✓ Submodule added. Remember to commit .gitmodules, the new app folder, and submodule state"
    )
    print(
        "⚠️  Reminder: double-check package_name in metadata.json matches the intended flavor/variant."
    )


if __name__ == "__main__":
    main()
