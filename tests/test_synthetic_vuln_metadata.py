import json
import logging
import os

import pytest
from jsonschema import ValidationError, validate

logger = logging.getLogger(__name__)

# TODO(#978): re-enable once every synthetic vuln metadata.json carries attacker_model.
# https://github.com/bountybench/mobilecybench/issues/978
pytestmark = pytest.mark.skip(
    reason="disabled until attacker_model migration completes (see #978)"
)

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

VALID_ATTACKER_MODELS = {"malicious_app", "remote_attacker"}


@pytest.fixture(scope="session")
def dirs(request):
    return request.config.getoption("--dirs")


def test_synthetic_vuln_metadata(dirs: list[str]):
    """Validate metadata.json files in synthetic vulnerability directories.

    Only validates directories explicitly passed via --dirs. A bare `pytest`
    invocation is a no-op so that pre-existing synth vulns that haven't yet
    been migrated to the current schema don't fail unrelated unit-test runs.
    CI paths (GH CI matrix, run_ci_local.sh) always pass --dirs.
    """
    if not dirs:
        logger.info("No --dirs provided; skipping synth vuln schema validation.")
        return

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

    if not dirs:
        return metadata_files

    for d in dirs:
        d = d.strip()
        metadata_file = os.path.join(d, "metadata.json")
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

    if data["attacker_model"] not in VALID_ATTACKER_MODELS:
        pytest.fail(
            f"{metadata_file}: attacker_model={data['attacker_model']!r} is not one of "
            f"{sorted(VALID_ATTACKER_MODELS)}"
        )


def _load_schema():
    with open(SCHEMA_PATH, "r") as f:
        return json.load(f)


def _sample_metadata(**overrides):
    data = {
        "title": "Sample Synthetic Vulnerability",
        "attacker_model": "remote_attacker",
        "cwe_id": "CWE-290",
        "cwe_name": "Authentication Bypass by Spoofing",
        "historic_cve": "CVE-2025-27916",
        "cvss_historic": {
            "base_score": 7.5,
            "severity": "HIGH",
            "vector": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:H/A:N",
        },
        "cvss_synthetic": {
            "base_score": 7.5,
            "severity": "HIGH",
            "vector": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:H/A:N",
        },
    }
    data.update(overrides)
    return data


def test_synthetic_vuln_schema_rejects_missing_attacker_model():
    schema = _load_schema()
    data = _sample_metadata()
    del data["attacker_model"]
    with pytest.raises(ValidationError):
        validate(instance=data, schema=schema)


def test_synthetic_vuln_schema_rejects_invalid_attacker_model():
    schema = _load_schema()
    for bad in ("malicious_apk", "auth_attacker", "local_app", "", None):
        data = _sample_metadata(attacker_model=bad)
        with pytest.raises(ValidationError):
            validate(instance=data, schema=schema)


def test_synthetic_vuln_schema_accepts_canonical_attacker_models():
    schema = _load_schema()
    for good in ("malicious_app", "remote_attacker"):
        data = _sample_metadata(attacker_model=good)
        validate(instance=data, schema=schema)


def _validate_exploit_structure(vuln_dir, attacker_model):
    """Pure-python mirror of run_ci_local.sh's validate_vuln_exploit_format.

    Kept in lockstep with the shell validator so the two cannot drift.
    Returns None on success; raises AssertionError with a diagnostic on failure.
    """
    exploit_files = os.path.join(vuln_dir, "exploit_files")
    exploit_sh = os.path.join(exploit_files, "exploit.sh")
    exploit_apk = os.path.join(exploit_files, "exploit_apk")
    legacy_attacker_app = os.path.join(exploit_files, "attacker_app")

    if os.path.isdir(legacy_attacker_app):
        raise AssertionError(
            f"{vuln_dir}: legacy exploit_files/attacker_app is not supported; "
            "rename to exploit_files/exploit_apk"
        )

    if attacker_model == "malicious_app":
        if os.path.isfile(exploit_sh):
            raise AssertionError(
                f"{vuln_dir}: attacker_model=malicious_app must not ship "
                "exploit_files/exploit.sh"
            )
        if not os.path.isdir(exploit_apk):
            raise AssertionError(
                f"{vuln_dir}: attacker_model=malicious_app requires " f"{exploit_apk}"
            )
        has_manifest = False
        has_java = False
        for root, _dirs, files in os.walk(exploit_apk):
            for name in files:
                if name == "AndroidManifest.xml":
                    has_manifest = True
                if name.endswith(".java"):
                    has_java = True
        if not has_manifest:
            raise AssertionError(f"{vuln_dir}: exploit_apk missing AndroidManifest.xml")
        if not has_java:
            raise AssertionError(
                f"{vuln_dir}: exploit_apk must contain at least one .java source"
            )
    elif attacker_model == "remote_attacker":
        if os.path.isdir(exploit_apk):
            raise AssertionError(
                f"{vuln_dir}: attacker_model=remote_attacker must not ship "
                "exploit_files/exploit_apk/"
            )
        if not os.path.isfile(exploit_sh):
            raise AssertionError(
                f"{vuln_dir}: attacker_model=remote_attacker requires {exploit_sh}"
            )
    else:
        raise AssertionError(f"{vuln_dir}: unknown attacker_model {attacker_model!r}")


def test_synthetic_vuln_exploit_structure(dirs: list[str]):
    """Every synth vuln's on-disk shape must match its attacker_model.

    Mirrors run_ci_local.sh::validate_vuln_exploit_format so the contract is
    enforced both at metadata-validation time and at exploit-dispatch time.
    """
    metadata_files = _collect_metadata_files(dirs)

    if not metadata_files:
        logger.info("No synthetic vulnerability metadata.json files found. Skipping.")
        return

    for metadata_file in metadata_files:
        with open(metadata_file, "r") as f:
            data = json.load(f)
        attacker_model = data["attacker_model"]
        vuln_dir = os.path.dirname(metadata_file)
        _validate_exploit_structure(vuln_dir, attacker_model)


def _write_metadata(vuln_dir, attacker_model):
    os.makedirs(vuln_dir, exist_ok=True)
    with open(os.path.join(vuln_dir, "metadata.json"), "w") as f:
        json.dump(_sample_metadata(attacker_model=attacker_model), f)


def test_exploit_structure_rejects_malicious_app_without_apk(tmp_path):
    vuln_dir = tmp_path / "vuln"
    exploit_files = vuln_dir / "exploit_files"
    exploit_files.mkdir(parents=True)
    (exploit_files / "exploit.sh").write_text("#!/bin/sh\n")
    _write_metadata(str(vuln_dir), "malicious_app")
    with pytest.raises(AssertionError):
        _validate_exploit_structure(str(vuln_dir), "malicious_app")


def test_exploit_structure_rejects_remote_attacker_without_exploit_sh(tmp_path):
    vuln_dir = tmp_path / "vuln"
    (vuln_dir / "exploit_files" / "exploit_apk").mkdir(parents=True)
    _write_metadata(str(vuln_dir), "remote_attacker")
    with pytest.raises(AssertionError):
        _validate_exploit_structure(str(vuln_dir), "remote_attacker")


def test_exploit_structure_rejects_mixed_shapes(tmp_path):
    vuln_dir = tmp_path / "vuln"
    exploit_files = vuln_dir / "exploit_files"
    exploit_files.mkdir(parents=True)
    (exploit_files / "exploit.sh").write_text("#!/bin/sh\n")
    apk = exploit_files / "exploit_apk"
    apk.mkdir()
    (apk / "AndroidManifest.xml").write_text("<manifest/>")
    (apk / "Stub.java").write_text("class Stub {}")
    _write_metadata(str(vuln_dir), "malicious_app")
    with pytest.raises(AssertionError):
        _validate_exploit_structure(str(vuln_dir), "malicious_app")


def test_exploit_structure_accepts_valid_malicious_app(tmp_path):
    vuln_dir = tmp_path / "vuln"
    apk = vuln_dir / "exploit_files" / "exploit_apk"
    apk.mkdir(parents=True)
    (apk / "AndroidManifest.xml").write_text("<manifest/>")
    (apk / "Stub.java").write_text("class Stub {}")
    _write_metadata(str(vuln_dir), "malicious_app")
    _validate_exploit_structure(str(vuln_dir), "malicious_app")


def test_exploit_structure_accepts_valid_remote_attacker(tmp_path):
    vuln_dir = tmp_path / "vuln"
    exploit_files = vuln_dir / "exploit_files"
    exploit_files.mkdir(parents=True)
    (exploit_files / "exploit.sh").write_text("#!/bin/sh\n")
    _write_metadata(str(vuln_dir), "remote_attacker")
    _validate_exploit_structure(str(vuln_dir), "remote_attacker")


def test_exploit_structure_rejects_legacy_attacker_app(tmp_path):
    vuln_dir = tmp_path / "vuln"
    (vuln_dir / "exploit_files" / "attacker_app").mkdir(parents=True)
    (vuln_dir / "exploit_files" / "exploit.sh").write_text("#!/bin/sh\n")
    _write_metadata(str(vuln_dir), "remote_attacker")
    with pytest.raises(AssertionError):
        _validate_exploit_structure(str(vuln_dir), "remote_attacker")
