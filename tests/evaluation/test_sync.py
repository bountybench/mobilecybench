"""Tests for `evaluation.analysis.sync` (inventory builder only).

The `gsutil` subprocess wrapper is not exercised in unit tests — it requires
a real bucket and is a thin shell-out.
"""

from __future__ import annotations

import json
from pathlib import Path

from evaluation.analysis.sync import build_inventory


def test_inventory_lists_every_dir(runs_dir: Path):
    out = build_inventory(runs_dir)
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    n_dirs = sum(1 for _ in runs_dir.rglob("experiment_*"))
    assert len(rows) == n_dirs


def test_inventory_records_missing_summary(runs_dir: Path):
    out = build_inventory(runs_dir)
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    no_summary = [r for r in rows if r["path"].endswith("experiment_no-summary")]
    assert len(no_summary) == 1
    assert no_summary[0]["validity"] == "incomplete"
    assert no_summary[0]["run_id"] is None
