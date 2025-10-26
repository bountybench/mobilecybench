import json
import os

from utils.uuid_flags_utils import extract_container_names_from_compose


def get_metadata():
    # Retrieve metadata object
    metadata_path = "metadata.json"

    if not os.path.exists(metadata_path):
        raise FileNotFoundError(f"metadata.json not found: {metadata_path}")

    try:
        with open(metadata_path, "r") as f:
            metadata = json.load(f)

        # Extract container names from docker-compose.yml if not in metadata
        if "container_names" not in metadata:
            # Look for docker-compose.yml in the current directory or parent
            docker_compose_paths = [
                "docker-compose.yml",
                "docker-compose.yaml",
                os.path.join(os.path.dirname(metadata_path), "docker-compose.yml"),
                os.path.join(os.path.dirname(metadata_path), "docker-compose.yaml"),
            ]

            for dc_path in docker_compose_paths:
                if os.path.exists(dc_path):
                    container_names = extract_container_names_from_compose(dc_path)
                    if container_names:
                        metadata["container_names"] = container_names
                        break

        return metadata
    except (json.JSONDecodeError, IOError) as e:
        raise e
