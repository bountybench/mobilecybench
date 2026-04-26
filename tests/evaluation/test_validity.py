"""Tests for `evaluation.analysis.validity`."""

from __future__ import annotations

from pathlib import Path

from evaluation.analysis import validity


def test_each_validity_class_reachable(runs_dir: Path):
    seen: dict[str, list[str]] = {}
    for exp_dir in sorted(runs_dir.rglob("experiment_*")):
        if not exp_dir.is_dir():
            continue
        v = validity.classify(exp_dir)
        seen.setdefault(v.validity, []).append(exp_dir.name)

    for tag in (
        "valid",
        "incomplete",
        "summary_invalid",
        "gold",
        "dry_run",
        "infra_error",
    ):
        assert tag in seen, f"missing fixture for validity={tag}"
