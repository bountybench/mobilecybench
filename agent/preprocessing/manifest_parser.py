"""
Parse AndroidManifest.xml to extract components and permissions.

Extracts:
- Package name
- Activities, Services, Receivers, Providers
- Permissions
- Exported components
"""

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional

from utils.logger import logger


def parse_manifest(
    app_path: str, structure: Optional[Dict] = None, package_name: Optional[str] = None
) -> Dict[str, any]:
    """
    Parse AndroidManifest.xml from app directory.

    Args:
        app_path: Path to app directory (e.g., "apps/home-assistant-android")
        structure: Optional structure dict from LLM detection
        package_name: Optional package name (fallback if not in manifest)

    Returns:
        Dict with manifest data:
        {
            "package_name": str,
            "activities": List[str],
            "services": List[str],
            "receivers": List[str],
            "providers": List[str],
            "permissions": List[str],
            "exported_components": List[str]
        }
    """
    # Use LLM-detected path if provided
    if structure and structure.get("manifest_path"):
        manifest_path = Path(app_path) / structure["manifest_path"]
        if not manifest_path.exists():
            logger.warning(f"LLM suggested manifest doesn't exist: {manifest_path}")
            manifest_path = None
    else:
        manifest_path = None

    # Fallback to auto-detection
    if not manifest_path:
        manifest_path = find_manifest(app_path)

    if not manifest_path:
        logger.error(f"AndroidManifest.xml not found in {app_path}")
        return _empty_manifest()

    try:
        tree = ET.parse(manifest_path)
        root = tree.getroot()

        # Extract package name from manifest, use parameter as fallback
        # Modern AGP 7.0+ apps declare namespace in build.gradle instead
        manifest_package = root.get("package")
        resolved_package = manifest_package if manifest_package else (package_name or "unknown")

        # Namespace for Android attributes
        ns = {"android": "http://schemas.android.com/apk/res/android"}

        # Extract components
        activities = extract_components(root, "activity", ns)
        services = extract_components(root, "service", ns)
        receivers = extract_components(root, "receiver", ns)
        providers = extract_components(root, "provider", ns)

        # Extract permissions
        permissions = extract_permissions(root, ns)

        # Find exported components
        exported = find_exported_components(root, ns)

        logger.info(f"Parsed manifest: {resolved_package}")
        logger.info(
            f"  Components: {len(activities)} activities, {len(services)} services, "
            f"{len(receivers)} receivers, {len(providers)} providers"
        )
        logger.info(f"  Permissions: {len(permissions)}")
        logger.info(f"  Exported: {len(exported)}")

        return {
            "package_name": resolved_package,
            "activities": activities,
            "services": services,
            "receivers": receivers,
            "providers": providers,
            "permissions": permissions,
            "exported_components": exported,
        }

    except Exception as e:
        logger.error(f"Error parsing manifest: {e}")
        return _empty_manifest()


def find_manifest(app_path: str) -> Optional[Path]:
    """Find AndroidManifest.xml in app directory."""
    app_path = Path(app_path)

    # Common locations
    candidates = [
        app_path / "AndroidManifest.xml",
        app_path / "app/src/main/AndroidManifest.xml",
        app_path / "*/src/main/AndroidManifest.xml",  # Gradle structure
    ]

    for pattern in candidates:
        if "*" in str(pattern):
            # Glob pattern
            matches = list(app_path.glob(str(pattern).replace(str(app_path) + "/", "")))
            if matches:
                return matches[0]
        elif pattern.exists():
            return pattern

    # Search recursively as fallback
    manifests = list(app_path.rglob("AndroidManifest.xml"))
    if manifests:
        # Prefer main source set
        for m in manifests:
            if "src/main" in str(m):
                return m
        return manifests[0]

    return None


def extract_components(
    root: ET.Element, component_type: str, ns: Dict[str, str]
) -> List[str]:
    """Extract component names from manifest."""
    components = []

    for component in root.iter(component_type):
        name = component.get(f"{{{ns['android']}}}name")
        if name:
            components.append(name)

    return components


def extract_permissions(root: ET.Element, ns: Dict[str, str]) -> List[str]:
    """Extract requested permissions."""
    permissions = []

    for perm in root.iter("uses-permission"):
        name = perm.get(f"{{{ns['android']}}}name")
        if name:
            # Extract just the permission name (e.g., INTERNET from android.permission.INTERNET)
            perm_name = name.split(".")[-1] if "." in name else name
            permissions.append(perm_name)

    return permissions


def find_exported_components(root: ET.Element, ns: Dict[str, str]) -> List[str]:
    """Find components with android:exported='true'."""
    exported = []

    component_types = ["activity", "service", "receiver", "provider"]

    for comp_type in component_types:
        for component in root.iter(comp_type):
            is_exported = component.get(f"{{{ns['android']}}}exported")
            name = component.get(f"{{{ns['android']}}}name")

            # Component is exported if:
            # 1. android:exported="true" explicitly set
            # 2. Has intent-filter (implicit export on Android < 12)
            if is_exported == "true" or (
                is_exported != "false" and component.find("intent-filter") is not None
            ):
                if name:
                    exported.append(f"{comp_type}:{name}")

    return exported


def _empty_manifest() -> Dict[str, any]:
    """Return empty manifest structure."""
    return {
        "package_name": "unknown",
        "activities": [],
        "services": [],
        "receivers": [],
        "providers": [],
        "permissions": [],
        "exported_components": [],
    }
