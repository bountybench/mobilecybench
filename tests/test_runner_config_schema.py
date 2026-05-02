"""CI parity test for the runner-config JSON Schema.

The committed ``schemas/runner_config.schema.json`` is the contract
editors and external tooling read for autocomplete + hover-docs and
sweep-config validation. It is generated from
``models.config.RunnerConfig``; when the model is edited, the schema
must be regenerated and committed.

This test fails the build on drift, with a one-liner remediation
pointing at the canonical generator.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from models.config import RunnerConfig

SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent / "schemas" / "runner_config.schema.json"
)


def _read_committed_schema() -> str:
    return SCHEMA_PATH.read_text(encoding="utf-8")


def test_committed_schema_matches_runner_config_model():
    expected = RunnerConfig.render_json_schema()
    actual = _read_committed_schema()
    if actual == expected:
        return

    pytest.fail(
        "schemas/runner_config.schema.json is out of sync with "
        "models/config.py:RunnerConfig. Regenerate with:\n\n"
        "    python scripts/generate_runner_config_schema.py\n"
    )


def test_committed_schema_is_valid_json():
    """Cheap structural sanity — the schema parses and carries the
    fixed metadata the generator stamps on."""
    payload = json.loads(_read_committed_schema())
    assert payload["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert payload["$id"].endswith("runner_config.schema.json")
    assert payload["title"] == "Runner Config"
    assert "properties" in payload and isinstance(payload["properties"], dict)


@pytest.mark.parametrize(
    "config_path",
    [
        Path("runner_config.json"),
        Path("runner_config_dryrun.json"),
        Path("infra/gke/runner_config_container_dryrun.json"),
    ],
)
def test_committed_configs_validate_against_schema(config_path):
    """Every checked-in runner config should validate against the
    committed schema. Catches accidental field drift in the JSON
    samples without needing a runner."""
    jsonschema = pytest.importorskip("jsonschema")
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    schema = json.loads(_read_committed_schema())
    # `$schema` in the config is a tooling pointer, not a model field —
    # strip before validating so our schema does not need to declare it.
    payload.pop("$schema", None)
    jsonschema.validate(payload, schema)


def test_explain_config_emits_committed_schema():
    """`python runner.py --explain-config` must print the same JSON
    Schema we ship under ``schemas/``. Anchors the CLI surface to the
    same single source of truth as the file."""
    import subprocess

    project_root = SCHEMA_PATH.parent.parent
    proc = subprocess.run(
        ["python3", "runner.py", "--explain-config"],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == _read_committed_schema()
