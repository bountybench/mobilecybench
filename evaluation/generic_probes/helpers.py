import json
import os
import sys
from functools import lru_cache
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.generic_probe_config import GENERIC_PROBE_KEYS, load_generic_probe_config


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


@lru_cache(maxsize=1)
def get_generic_probe_applicability():
    metadata = get_metadata()
    config_path = Path("generic_probe_config.json")

    if not config_path.exists():
        return {key: True for key in GENERIC_PROBE_KEYS}

    config = load_generic_probe_config(
        config_path,
        container_names=metadata.get("container_names", []),
        app_server=metadata.get("app_server", ""),
    )
    return dict(config.get("generic_probe_applicability", {}))


def is_generic_probe_applicable(key: str) -> bool:
    return bool(get_generic_probe_applicability().get(key, False))


def compute_generic_probe_score(results_summary: dict[str, int | None]) -> int | None:
    applicable = [val for val in results_summary.values() if val is not None]
    if not applicable:
        return None
    return 1 if all(val == 1 for val in applicable) else 0
