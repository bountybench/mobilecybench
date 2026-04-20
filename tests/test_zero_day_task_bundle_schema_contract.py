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


@pytest.mark.parametrize("value", ["malicious_app", "remote_attacker"])
def test_accepts_canonical_attacker_model(value):
    metadata = {**BASE_METADATA, "attacker_model": value}
    validate(instance=metadata, schema=SCHEMA)


def test_rejects_missing_attacker_model():
    with pytest.raises(ValidationError):
        validate(instance=BASE_METADATA, schema=SCHEMA)


def test_rejects_legacy_attack_model_field():
    metadata = {**BASE_METADATA, "attack_model": "malicious_app"}
    with pytest.raises(ValidationError):
        validate(instance=metadata, schema=SCHEMA)


def test_rejects_legacy_malicious_apk_value():
    metadata = {**BASE_METADATA, "attacker_model": "malicious_apk"}
    with pytest.raises(ValidationError):
        validate(instance=metadata, schema=SCHEMA)


def test_rejects_unknown_attacker_model():
    metadata = {**BASE_METADATA, "attacker_model": "bogus"}
    with pytest.raises(ValidationError):
        validate(instance=metadata, schema=SCHEMA)
