
import json
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List

from utils.logger import logger


def get_manifests(app_path: str) -> Dict[str, any]:
    """
    Deterministically discover Android manifests.
    
    Logic:
    1. Parse metadata.json for package_name (Source of Truth).
    2. Search for ALL AndroidManifest.xml files (depth=6).
    3. Identify PRIMARY manifest (contains LAUNCHER activity).
    4. Return structured manifest info.

    Args:
        app_path: Path to apps/<app-name> (NOT codebase root yet)

    Returns:
        Dict: {
            "package_name": "com.example",
            "primary_manifest": "/path/to/main/AndroidManifest.xml",
            "library_manifests": ["/path/to/lib1/AndroidManifest.xml", ...],
            "manifest_data": {Parsed Primary Manifest Data}
        }
    """
    app_path = Path(app_path)
    codebase_path = app_path / "codebase"
    
    # 1. Get Package Name from Metadata
    package_name = _get_package_from_metadata(app_path)
    
    # 2. Find All Manifests
    all_manifests = _find_all_manifests(codebase_path)
    if not all_manifests:
        logger.error(f"No AndroidManifest.xml found in {codebase_path}")
        return {
            "package_name": package_name,
            "primary_manifest": None,
            "library_manifests": [],
            "manifest_data": {}
        }

    # 3. Identify Primary vs Library
    primary_manifest = None
    library_manifests = []
    
    for manifest in all_manifests:
        if _is_primary_manifest(manifest):
            if primary_manifest:
                logger.warning(f"Multiple primary manifests found! Using first: {primary_manifest}, Ignoring: {manifest}")
                library_manifests.append(str(manifest))
            else:
                primary_manifest = str(manifest)
        else:
            library_manifests.append(str(manifest))
            
    # Fallback: If no launcher found, try heuristic (app/src/main)
    if not primary_manifest and all_manifests:
        logger.warning("No LAUNCHER activity found. Using heuristic for Primary Manifest.")
        primary_manifest = _heuristic_primary(all_manifests)
        # Remove from libs if it was added
        if primary_manifest in library_manifests:
            library_manifests.remove(primary_manifest)
            
    logger.info(f"Manifest Discovery:\n  Primary: {primary_manifest}\n  Libraries: {len(library_manifests)}")

    # 4. Parse Primary Manifest Data
    manifest_data = {}
    if primary_manifest:
        try:
           manifest_data = _parse_manifest_xml(primary_manifest)
        except Exception as e:
            logger.error(f"Failed to parse primary manifest {primary_manifest}: {e}")

    # Validate Package Name Consistency
    if manifest_data.get("package") and manifest_data["package"] != package_name:
         logger.warning(f"Metadata package ({package_name}) != Manifest package ({manifest_data['package']}). Trusting Metadata.")

    return {
        "package_name": package_name,
        "primary_manifest": primary_manifest,
        "library_manifests": library_manifests,
        "manifest_data": manifest_data
    }

def _get_package_from_metadata(app_path: Path) -> str:
    """Read package_name from metadata.json."""
    meta_path = app_path / "metadata.json"
    if meta_path.exists():
        try:
            with open(meta_path) as f:
                data = json.load(f)
                return data.get("package_name", "unknown.package")
        except Exception as e:
            logger.error(f"Error reading metadata.json: {e}")
    return "unknown.package"

def _find_all_manifests(root_path: Path, max_depth: int = 6) -> List[Path]:
    """Recursive search for AndroidManifest.xml, excluding build dirs."""
    manifests = []
    skip_dirs = {"build", "bin", "generated", ".gradle", ".git", "test", "androidTest"}
    
    # Efficient walk with depth limit
    root_path_len = len(root_path.parts)
    
    for root, dirs, files in os.walk(root_path):
        # Depth check
        current_depth = len(Path(root).parts) - root_path_len
        if current_depth > max_depth:
            # Clear dirs to stop recursion
            dirs[:] = []
            continue
            
        # Prune skip dirs
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        
        if "AndroidManifest.xml" in files:
            manifests.append(Path(root) / "AndroidManifest.xml")
            
    return manifests

def _is_primary_manifest(manifest_path: Path) -> bool:
    """Check if manifest has LAUNCHER activity."""
    try:
        tree = ET.parse(manifest_path)
        root = tree.getroot()
        
        # Namespace handling is annoying in ElementTree, ignore it for simple check
        # Convert entire file sting to check for string
        with open(manifest_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
            return 'android.intent.category.LAUNCHER' in content
            
    except Exception:
        return False

def _heuristic_primary(manifests: List[Path]) -> str:
    """Guess primary manifest based on path."""
    # Preference list
    priorities = [
        "app/src/main/AndroidManifest.xml",
        "src/main/AndroidManifest.xml",
        "mobile/src/main/AndroidManifest.xml"
    ]
    
    for p in priorities:
        for m in manifests:
            if str(m).endswith(p):
                return str(m)
                
    # Default to first one
    return str(manifests[0])

def _parse_manifest_xml(manifest_path: str) -> Dict:
    """
    Parse essential components from manifest.
    Does NOT do full extraction (done by agent tools later), 
    just gets components to seed the Code Index.
    """
    import xml.etree.ElementTree as ET
    
    data = {
        "package": "",
        "activities": [],
        "services": [],
        "receivers": [],
        "providers": [],
        "permissions": [],
        "exported_components": []
    }
    
    try:
        # Register namespaces
        namespaces = {'android': 'http://schemas.android.com/apk/res/android'}
        for prefix, uri in namespaces.items():
            ET.register_namespace(prefix, uri)
            
        tree = ET.parse(manifest_path)
        root = tree.getroot()
        
        data["package"] = root.get("package", "")
        
        application = root.find("application")
        if application is None:
            return data
            
        def get_name(elem):
            return elem.get(f"{{{namespaces['android']}}}name")
            
        def is_exported(elem):
            exported = elem.get(f"{{{namespaces['android']}}}exported")
            return exported == "true"

        # Activities
        for comp in application.findall("activity"):
            name = get_name(comp)
            if name:
                data["activities"].append(name)
                if is_exported(comp):
                    data["exported_components"].append(f"activity:{name}")
                    
        # Services
        for comp in application.findall("service"):
            name = get_name(comp)
            if name:
                data["services"].append(name)
                if is_exported(comp):
                    data["exported_components"].append(f"service:{name}")

        # Receivers
        for comp in application.findall("receiver"):
            name = get_name(comp)
            if name:
                data["receivers"].append(name)
                if is_exported(comp):
                    data["exported_components"].append(f"receiver:{name}")

        # Providers
        for comp in application.findall("provider"):
            name = get_name(comp)
            if name:
                data["providers"].append(name)
                if is_exported(comp):
                    data["exported_components"].append(f"provider:{name}")
                    
    except Exception as e:
        logger.error(f"Error detailed parsing manifest {manifest_path}: {e}")
        
    return data
