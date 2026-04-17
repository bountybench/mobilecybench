import json
from pathlib import Path

import pytest
from jsonschema import ValidationError, validate

SCHEMA = json.loads(
    (
        Path(__file__).resolve().parents[1] / "zero_day_task_bundle_schema.json"
    ).read_text()
)

BASE_METADATA = {
    "schema_version": 1,
    "task_id": "demo_task",
    "title": "Demo task",
    "baseline": {"commit": "deadbeef"},
}


def test_accepts_canonical_attack_model():
    metadata = {**BASE_METADATA, "attack_model": "malicious_apk"}
    validate(instance=metadata, schema=SCHEMA)


@pytest.mark.parametrize(
    "legacy_value", ["malicious_apk", "auth_attacker", "malicious_app"]
)
def test_accepts_legacy_attacker_model_alias(legacy_value):
    metadata = {**BASE_METADATA, "attacker_model": legacy_value}
    validate(instance=metadata, schema=SCHEMA)


def test_rejects_missing_attack_model_selector():
    with pytest.raises(ValidationError):
        validate(instance=BASE_METADATA, schema=SCHEMA)


def test_rejects_unknown_attack_model():
    metadata = {**BASE_METADATA, "attack_model": "bogus"}
    with pytest.raises(ValidationError):
        validate(instance=metadata, schema=SCHEMA)
