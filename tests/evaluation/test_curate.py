"""Tests for `evaluation.analysis.curate`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.analysis import curate


def test_parse_filter_basic():
    clauses = curate.parse_filter("workflow=exploit, model=a|b, app!=bitwarden")
    assert len(clauses) == 3
    assert clauses[0].key == "workflow" and clauses[0].op == "in"
    assert clauses[1].values == ("a", "b")
    assert clauses[2].op == "not_in"


def test_parse_filter_rejects_bad_key():
    with pytest.raises(ValueError):
        curate.parse_filter("nonsense=1")


def test_curate_latest_dedup_picks_newer(runs_dir: Path, tmp_path: Path):
    out = tmp_path / "cohort"
    rc = curate.main(
        [
            "--runs",
            str(runs_dir),
            "--out",
            str(out),
            "--policy",
            "latest",
            "--validity",
            "valid",
        ]
    )
    assert rc == 0

    manifest_lines = (out / "manifest.jsonl").read_text().splitlines()
    canonical_ids = sorted(json.loads(line)["run_id"] for line in manifest_lines)
    # 3 valid cells: (moememos, gpt-5) → rep2-pass; (gotify, gpt-5) → gotify-pass;
    # (moememos, claude) → claude-fail.
    assert canonical_ids == ["claude-fail", "gotify-pass", "rep2-pass"]

    excluded = [
        json.loads(line) for line in (out / "excluded.jsonl").read_text().splitlines()
    ]
    reasons = {(e["run_id"], e["excluded_reason"]) for e in excluded}
    assert ("rep1-fail", "dedup:non_canonical") in reasons


def test_curate_filter_workflow_and_model(runs_dir: Path, tmp_path: Path):
    out = tmp_path / "cohort_filter"
    rc = curate.main(
        [
            "--runs",
            str(runs_dir),
            "--out",
            str(out),
            "--filter",
            "workflow=exploit, model=gpt-5",
            "--policy",
            "latest",
        ]
    )
    assert rc == 0
    ids = sorted(
        json.loads(line)["run_id"]
        for line in (out / "manifest.jsonl").read_text().splitlines()
    )
    assert ids == ["gotify-pass", "rep2-pass"]


def test_curate_all_replicates_keeps_both(runs_dir: Path, tmp_path: Path):
    out = tmp_path / "cohort_all"
    rc = curate.main(
        [
            "--runs",
            str(runs_dir),
            "--out",
            str(out),
            "--filter",
            "model=gpt-5, app=moememos",
            "--policy",
            "all-replicates",
        ]
    )
    assert rc == 0
    ids = sorted(
        json.loads(line)["run_id"]
        for line in (out / "manifest.jsonl").read_text().splitlines()
    )
    assert ids == ["rep1-fail", "rep2-pass"]


def test_curate_creates_relative_symlinks(runs_dir: Path, tmp_path: Path):
    out = tmp_path / "cohort_links"
    curate.main(
        [
            "--runs",
            str(runs_dir),
            "--out",
            str(out),
            "--filter",
            "model=gpt-5, app=gotify",
        ]
    )
    link = out / "runs" / "gotify-pass"
    assert link.is_symlink()
    assert (link / "run_summary.json").exists()
    target = link.readlink()
    assert not str(target).startswith("/")


def test_curate_excludes_gold_and_dry_run_and_infra_error(
    runs_dir: Path, tmp_path: Path
):
    out = tmp_path / "cohort_clean"
    curate.main(["--runs", str(runs_dir), "--out", str(out), "--validity", "valid"])
    ids = {
        json.loads(line)["run_id"]
        for line in (out / "manifest.jsonl").read_text().splitlines()
    }
    assert "gold1" not in ids
    assert "dryrun1" not in ids
    assert "oom1" not in ids


def test_curate_writes_cohort_yaml(runs_dir: Path, tmp_path: Path):
    out = tmp_path / "cohort_yaml"
    curate.main(
        [
            "--runs",
            str(runs_dir),
            "--out",
            str(out),
            "--filter",
            "model=gpt-5",
            "--note",
            "hello",
        ]
    )
    text = (out / "cohort.yaml").read_text()
    assert "policy: latest" in text
    assert 'note: "hello"' in text
    assert "filter_clauses:" in text
    assert "key: model" in text
