import json
import logging
import os

import pytest
from jsonschema import ValidationError, validate

logger = logging.getLogger(__name__)

SCHEMA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "zero_day_task_bundle_schema.json"
)


@pytest.fixture(scope="session")
def dirs(request):
    return request.config.getoption("--dirs")


REQUIRED_FIELDS = {
    "schema_version": "Task metadata schema version (currently 1)",
    "task_id": "Stable task identifier (for example location_spoofing)",
    "title": "Short task title",
    "baseline": "Baseline app commit that defines the vulnerable build",
}


def test_zero_day_task_bundle_metadata(dirs: list[str]):
    """Validate metadata.json files in zero-day task bundle directories."""
    with open(SCHEMA_PATH, "r") as f:
        schema = json.load(f)

    metadata_files = _collect_metadata_files(dirs)

    if not metadata_files:
        logger.info("No zero-day task bundle metadata.json files found. Skipping.")
        return

    for metadata_file in metadata_files:
        logger.info(f"Validating {metadata_file}")
        _validate_metadata(metadata_file, schema)


def _collect_metadata_files(dirs):
    metadata_files = []

    if dirs:
        for d in dirs:
            d = d.strip()
            metadata_file = os.path.join(d, "metadata.json")
            if os.path.isfile(metadata_file):
                metadata_files.append(metadata_file)
    else:
        apps_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "apps")
        if os.path.isdir(apps_dir):
            for app in sorted(os.listdir(apps_dir)):
                task_dir = os.path.join(apps_dir, app, "zero_day_vulnerabilities")
                if not os.path.isdir(task_dir):
                    continue
                for task in sorted(os.listdir(task_dir)):
                    metadata_file = os.path.join(task_dir, task, "metadata.json")
                    if os.path.isfile(metadata_file):
                        metadata_files.append(metadata_file)

    return metadata_files


def _validate_metadata(metadata_file, schema):
    with open(metadata_file, "r") as f:
        data = json.load(f)

    try:
        validate(instance=data, schema=schema)
    except ValidationError as ve:
        print(f"Validation error in {metadata_file}: {ve.message}")

        for field, description in REQUIRED_FIELDS.items():
            if field in data:
                print(f"  [PASS] {field}")
            else:
                print(f"  [FAIL] {field} — {description}")

        pytest.fail(f"{metadata_file} does not match schema: {ve.message}")
