import json
import os


def get_metadata():
    # Retrieve metadata object
    metadata_path = "metadata.json"

    if not os.path.exists(metadata_path):
        raise FileNotFoundError(f"metadata.json not found: {metadata_path}")

    try:
        with open(metadata_path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        raise e
