"""Inject the discovery-mode honeypot activity into the agent-visible codebase."""

import xml.etree.ElementTree as ET
from pathlib import Path

from utils.honeypot_spec import (
    activity_name,
    get_activity_class,
    java_source,
    manifest_activity_tag,
)
from utils.logger import logger


def inject_discovery_honeypot(codebase_dir: Path, package_name: str) -> None:
    """Mirror the repackaged APK's honeypot activity into the agent codebase."""
    if not package_name:
        raise ValueError("package_name is required to inject the discovery honeypot")

    manifest_path, source_root = _find_injection_points(codebase_dir, package_name)
    full_activity_name = activity_name(package_name)

    _inject_manifest_activity(manifest_path, full_activity_name, package_name)
    _inject_activity_source(source_root, package_name)

    logger.info(
        "Injected discovery honeypot into agent codebase: manifest=%s activity=%s",
        manifest_path,
        full_activity_name,
    )


def _find_injection_points(codebase_dir: Path, package_name: str) -> tuple[Path, Path]:
    package_path = Path(*package_name.split("."))

    # Find all possible source roots
    source_roots = sorted(
        [
            *codebase_dir.glob("**/src/main/java"),
            *codebase_dir.glob("**/src/main/kotlin"),
        ],
        key=lambda p: (len(p.parts), str(p)),
    )

    # Prioritize roots that actually contain the package directory
    package_matches = [root for root in source_roots if (root / package_path).exists()]

    # Critical Review Improvement: Prioritize 'app' module in multi-module projects
    def is_app_module(p: Path) -> bool:
        return "app" in p.parts or p.name == "app"

    package_matches.sort(key=lambda p: (not is_app_module(p), len(p.parts)))

    if package_matches:
        for source_root in package_matches:
            manifest_path = source_root.parent / "AndroidManifest.xml"
            if manifest_path.exists():
                return manifest_path, source_root

    # Fallback to any manifest that looks like a main app manifest
    manifest_candidates = sorted(
        codebase_dir.glob("**/src/main/AndroidManifest.xml"),
        key=lambda p: (not is_app_module(p), len(p.parts), str(p)),
    )
    for manifest_path in manifest_candidates:
        source_root = _preferred_source_root(manifest_path.parent, package_path)
        if source_root is not None:
            return manifest_path, source_root

    raise RuntimeError(
        f"Could not find an Android src/main manifest/source root in {codebase_dir}"
    )


def _preferred_source_root(src_main_dir: Path, package_path: Path) -> Path | None:
    candidates = [
        src_main_dir / "java",
        src_main_dir / "kotlin",
    ]

    for candidate in candidates:
        if (candidate / package_path.parent).exists() or (
            candidate / package_path
        ).exists():
            return candidate

    for candidate in candidates:
        if candidate.exists():
            return candidate

    return None


def _inject_manifest_activity(
    manifest_path: Path, full_activity_name: str, package_name: str
) -> None:
    ET.register_namespace("android", "http://schemas.android.com/apk/res/android")
    try:
        tree = ET.parse(manifest_path)
        root = tree.getroot()
        application = root.find("application")
        if application is None:
            raise RuntimeError(f"<application> tag not found in {manifest_path}")

        # Check if already present
        activity_tag = manifest_activity_tag(package_name)
        # Wrap in a root element with namespace declaration to avoid 'unbound prefix' error
        wrapped_tag = f'<root xmlns:android="http://schemas.android.com/apk/res/android">{activity_tag}</root>'
        new_activity_el = ET.fromstring(wrapped_tag)[0]
        activity_name_val = new_activity_el.get(
            "{http://schemas.android.com/apk/res/android}name"
        )

        for activity in application.findall("activity"):
            if (
                activity.get("{http://schemas.android.com/apk/res/android}name")
                == activity_name_val
            ):
                logger.info("Discovery honeypot already present in %s", manifest_path)
                return

        application.append(new_activity_el)
        tree.write(manifest_path, encoding="utf-8", xml_declaration=True)

    except Exception as e:
        raise RuntimeError(f"Failed to inject honeypot into {manifest_path}: {e}")


def _inject_activity_source(source_root: Path, package_name: str) -> None:
    activity_dir = source_root / Path(*package_name.split(".")) / "internal"
    activity_dir.mkdir(parents=True, exist_ok=True)

    cls_name = get_activity_class(package_name)
    activity_path = activity_dir / f"{cls_name}.java"
    if activity_path.exists():
        logger.info("Discovery honeypot source already present at %s", activity_path)
        return

    activity_path.write_text(java_source(package_name), encoding="utf-8")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Inject discovery honeypot into codebase or manifest."
    )
    parser.add_argument(
        "path", help="Path to codebase directory or AndroidManifest.xml"
    )
    parser.add_argument("--package", required=True, help="App package name")
    parser.add_argument(
        "--mode",
        choices=["source", "manifest"],
        default="source",
        help="Injection mode (source: codebase directory, manifest: single XML file)",
    )

    args = parser.parse_args()
    path = Path(args.path)

    if args.mode == "source":
        inject_discovery_honeypot(path, args.package)
    else:
        # For manifest mode, we need the full activity name
        full_activity_name = activity_name(args.package)
        _inject_manifest_activity(path, full_activity_name, args.package)

    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
