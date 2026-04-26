"""Tests for the `pass_rate` analyzer."""

from __future__ import annotations

import csv
from pathlib import Path

from evaluation.analysis import curate
from evaluation.analysis.analyzers import pass_rate


def test_pass_rate_end_to_end(runs_dir: Path, tmp_path: Path):
    cohort = tmp_path / "cohort_pr"
    curate.main(["--runs", str(runs_dir), "--out", str(cohort)])
    rc = pass_rate.main(["--cohort", str(cohort)])
    assert rc == 0

    csv_path = cohort / "results" / "pass_rate.csv"
    rows = list(csv.DictReader(csv_path.open()))
    assert {r["model"] for r in rows} == {"gpt-5", "claude-sonnet-4-6"}

    by_key = {(r["model"], r["app"]): r for r in rows}
    assert by_key[("gpt-5", "gotify")]["n"] == "1"
    assert by_key[("gpt-5", "gotify")]["passes"] == "1"
    # dedup=latest selects rep2-pass over rep1-fail
    assert by_key[("gpt-5", "moememos")]["passes"] == "1"
    assert by_key[("claude-sonnet-4-6", "moememos")]["passes"] == "0"


def test_pass_rate_groupby_workflow(runs_dir: Path, tmp_path: Path):
    cohort = tmp_path / "cohort_pr_wf"
    curate.main(["--runs", str(runs_dir), "--out", str(cohort)])
    pass_rate.main(["--cohort", str(cohort), "--groupby", "workflow"])
    rows = list(csv.DictReader((cohort / "results" / "pass_rate.csv").open()))
    assert len(rows) == 1
    assert rows[0]["workflow"] == "exploit"
