import json
import os
from typing import Any, Dict, Optional


def get_app_metadata(app_name: str) -> Optional[Dict[str, Any]]:
    """
    Load metadata.json for a given app name.

    Args:
        app_name: The name of the app (e.g., 'conversations')

    Returns:
        Dictionary containing the metadata, or None if not found
    """
    # Get the project root directory
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)

    # Construct path to the app's metadata.json
    metadata_path = os.path.join(project_root, "apps", app_name, "metadata.json")

    if not os.path.exists(metadata_path):
        return None

    try:
        with open(metadata_path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def get_app_server_from_metadata(app_name: str) -> Optional[str]:
    """
    Get the app_server value from an app's metadata.json.

    Args:
        app_name: The name of the app (e.g., 'conversations')

    Returns:
        The app_server string if found, None otherwise
    """
    metadata = get_app_metadata(app_name)
    if metadata:
        return metadata.get("app_server")
    return None
