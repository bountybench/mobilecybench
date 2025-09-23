import json
import os
from typing import Any, Dict


def get_app_metadata(app_name: str) -> Dict[str, Any]:
    """
    Load metadata.json for a given app name.

    Args:
        app_name: The name of the app (e.g., 'conversations')

    Returns:
        Dictionary containing the metadata

    Raises:
        FileNotFoundError: If metadata.json doesn't exist
        json.JSONDecodeError: If metadata.json contains invalid JSON
        IOError: If there's an error reading the file
    """
    # Get the project root directory
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)

    # Construct path to the app's metadata.json
    metadata_path = os.path.join(project_root, "apps", app_name, "metadata.json")

    if not os.path.exists(metadata_path):
        raise FileNotFoundError(f"metadata.json not found: {metadata_path}")

    try:
        with open(metadata_path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        raise e
