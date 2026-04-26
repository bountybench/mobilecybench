"""Validity classifier for individual experiment directories.

A run is tagged with one of:
- `valid`            — schema-checks, ended cleanly, has a real outcome.
- `incomplete`       — no `run_summary.json`, or no `ended_at`.
- `summary_invalid`  — JSON parse or schema validation failed.
- `infra_error`      — exit_reason indicates infra failure (oom etc.).
- `gold` / `dry_run` — explicitly excluded from headline cohorts.

The `invalid_config` tag from the plan is intentionally not implemented yet —
it depends on policy decisions (what counts as a "non-sandbox commit") that
haven't been made.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import jsonschema

from evaluation.analysis.normalize import load_run_summary

INFRA_ERROR_REASONS = {"setup_failed", "emulator_error", "oom", "timeout_infra"}


@dataclass(frozen=True)
class ValidityResult:
    validity: str
    reason: str


@lru_cache(maxsize=1)
def _default_schema() -> dict | None:
    """Load the project's run_summary schema, or None if not findable."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "schemas" / "run_summary.schema.json"
        if candidate.exists():
            return json.loads(candidate.read_text())
    return None


def classify(exp_dir: Path, schema: dict | None | object = ...) -> ValidityResult:
    """Classify a single `experiment_<uuid>/` directory.

    `schema=...` (default) loads the project schema lazily.
    Pass `schema=None` to skip schema validation.
    """
    if schema is ...:
        schema = _default_schema()

    if exp_dir.name.endswith("_gold"):
        # Gold runs short-circuit: by construction they have score=1.
        return ValidityResult("gold", "directory suffix _gold")

    summary, err = load_run_summary(exp_dir)
    if err == "missing":
        return ValidityResult("incomplete", "no run_summary.json")
    if summary is None:
        return ValidityResult("summary_invalid", err or "unknown parse error")

    if (summary.get("config") or {}).get("dry_run"):
        return ValidityResult("dry_run", "config.dry_run=true")

    if schema is not None:
        try:
            jsonschema.validate(summary, schema)
        except jsonschema.ValidationError as e:
            return ValidityResult("summary_invalid", f"schema: {e.message}")

    if not (summary.get("timestamps") or {}).get("ended_at"):
        return ValidityResult("incomplete", "no ended_at")

    exit_reason = summary.get("exit_reason", "")
    if exit_reason in INFRA_ERROR_REASONS:
        return ValidityResult("infra_error", f"exit_reason={exit_reason}")

    outcome = summary.get("outcome")
    if outcome not in ("success", "failure"):
        return ValidityResult("incomplete", f"unexpected outcome={outcome!r}")

    return ValidityResult("valid", "")
