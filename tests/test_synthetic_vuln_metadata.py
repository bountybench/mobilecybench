import json
import logging
import os

import pytest
from jsonschema import ValidationError, validate

logger = logging.getLogger(__name__)

# TODO(#978): re-enable once every synthetic vuln metadata.json carries attacker_model.
# https://github.com/bountybench/mobilecybench/issues/978
pytestmark = pytest.mark.skip(reason="disabled until attacker_model migration completes (see #978)")

SCHEMA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "synthetic_vuln_metadata_schema.json"
)

REQUIRED_FIELDS = {
    "title": "Short name for the vulnerability (e.g. XMPP Carbon Copy Impersonation)",
    "attacker_model": "Attacker-model selector: 'malicious_app' or 'remote_attacker'",
    "cwe_id": "CWE identifier matching the historic CVE (e.g. CWE-290)",
    "cwe_name": "Human-readable CWE name (e.g. Authentication Bypass by Spoofing)",
    "historic_cve": "Real CVE the synthetic is modeled after (e.g. CVE-2025-27916)",
    "cvss_historic": "CVSS object with base_score, severity, vector from the historic CVE",
    "cvss_synthetic": "CVSS object with base_score, severity, vector assessed for the synthetic vulnerability",
}


@pytest.fixture(scope="session")
def dirs(request):
    return request.config.getoption("--dirs")


def test_synthetic_vuln_metadata(dirs: list[str]):
    """Validate metadata.json files in synthetic vulnerability directories.

    When --dirs is provided, validates only those directories.
    Otherwise, discovers and validates all synthetic vulnerability metadata files.
    """
    with open(SCHEMA_PATH, "r") as f:
        schema = json.load(f)

    metadata_files = _collect_metadata_files(dirs)

    if not metadata_files:
        logger.info("No synthetic vulnerability metadata.json files found. Skipping.")
        return

    for metadata_file in metadata_files:
        logger.info(f"Validating {metadata_file}")
        _validate_metadata(metadata_file, schema)


def _collect_metadata_files(dirs):
    """Collect synthetic vulnerability metadata.json files to validate."""
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
                synth_dir = os.path.join(apps_dir, app, "synthetic_vulnerabilities")
                if not os.path.isdir(synth_dir):
                    continue
                for vuln in sorted(os.listdir(synth_dir)):
                    metadata_file = os.path.join(synth_dir, vuln, "metadata.json")
                    if os.path.isfile(metadata_file):
                        metadata_files.append(metadata_file)

    return metadata_files


def _validate_metadata(metadata_file, schema):
    """Validate a single metadata.json against the schema."""
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
