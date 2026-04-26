"""Shared fixtures for `evaluation.analysis` tests.

These build a synthetic `runs/` mirror that covers every validity tag and
every dedup edge case. Re-used across the per-module test files so each
analysis component can be tested in isolation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def make_summary(
    *,
    run_id: str,
    app: str = "moememos",
    vuln_id: str = "vuln_0",
    workflow: str = "exploit",
    model: str = "gpt-5",
    agent_type: str = "custom",
    started_at: str = "2026-04-01T00:00:00+00:00",
    ended_at: str | None = "2026-04-01T00:05:00+00:00",
    duration_s: float = 300.0,
    outcome: str = "success",
    exit_reason: str = "completed",
    score: float | None = 1.0,
    status: str | None = "true_positive",
    agent_status: str = "completed",
    inconsistencies: list | None = None,
    dry_run: bool = False,
    token_totals: dict | None = None,
    cost_usd: float | None = 0.12,
) -> dict:
    """Build a `run_summary.json` dict that conforms to the schema."""
    if token_totals is None:
        token_totals = {
            "calls": 5,
            "input_tokens": 1234,
            "output_tokens": 567,
            "reasoning_tokens": 89,
            "cache_input_tokens": 10,
            "cost_usd": cost_usd,
        }
    summary = {
        "run_id": run_id,
        "outcome": outcome,
        "exit_reason": exit_reason,
        "timestamps": {
            "started_at": started_at,
            "ended_at": ended_at,
            "duration_seconds": duration_s,
        },
        "context": {
            "app_name": app,
            "workflow": workflow,
            "vuln_id": vuln_id,
            "agent_type": agent_type,
            "model": model,
        },
        "config": {
            "build_type": "source",
            "dry_run": dry_run,
            "emulator_backend": "container",
            "emulator_display": "headless",
            "screenshot_mode": False,
            "max_iterations": 50,
            "max_model_response_tokens": 4096,
            "reasoning_effort": None,
            "full_snapshot": {},
        },
        "reproducibility": {
            "git_commit": "abc1234",
            "git_branch": "main",
            "git_dirty": False,
            "python_version": "3.11.8",
            "platform": "Linux",
        },
        "metrics": {
            "turn_count": 8,
            "tool_call_count": 12,
            "unique_tools": ["adb", "screenshot"],
            "error_count": 0,
            "token_totals": token_totals,
            "cost_usd": cost_usd,
            "timing": {
                "total_llm_time": 42.0,
                "llm_call_count": 5,
                "p50": 5.0,
                "p95": 15.0,
                "max": 20.0,
            },
        },
        "results": {
            "agent_status": agent_status,
            "score": score,
            "status": status,
            "scores": None,
            "inconsistencies": inconsistencies or [],
        },
        "artifacts": {
            "log_file": "experiment.log",
            "agent_log_file": "agent.log",
            "token_usage_jsonl": None,
            "conversation_jsonl": None,
            "logs_dir": ".",
        },
    }
    if ended_at is None:
        summary["timestamps"]["ended_at"] = "1970-01-01T00:00:00+00:00"
        summary["timestamps"]["__missing_ended_at__"] = True
    return summary


def write_run(
    runs_dir: Path,
    *,
    app: str,
    vuln_id: str,
    model: str,
    pod_name: str,
    summary: dict | None,
    gold: bool = False,
    dir_name_override: str | None = None,
) -> Path:
    """Materialize a single experiment dir under `runs_dir`."""
    suffix = "_gold" if gold else ""
    dir_name = dir_name_override or f"experiment_{summary['run_id']}{suffix}"
    exp_dir = runs_dir / app / vuln_id / model / pod_name / dir_name
    exp_dir.mkdir(parents=True, exist_ok=True)
    if summary is not None:
        if summary.get("timestamps", {}).get("__missing_ended_at__"):
            del summary["timestamps"]["__missing_ended_at__"]
            del summary["timestamps"]["ended_at"]
        (exp_dir / "run_summary.json").write_text(json.dumps(summary))
    (exp_dir / "experiment.log").write_text("ok\n")
    return exp_dir


@pytest.fixture
def runs_dir(tmp_path: Path) -> Path:
    """A comprehensive fixture mirror.

    Includes: two replicates of one cell, a clean cell on a different model,
    a cell on a different app, plus one example of every excluded validity
    tag (incomplete, summary_invalid, gold, dry_run, infra_error).
    """
    rd = tmp_path / "runs"
    rd.mkdir()

    # Two replicates of (moememos, vuln_0, gpt-5): earlier failure, later pass.
    write_run(
        rd,
        app="moememos",
        vuln_id="vuln_0",
        model="gpt-5",
        pod_name="pod-aaa",
        summary=make_summary(
            run_id="rep1-fail",
            started_at="2026-04-01T00:00:00+00:00",
            outcome="failure",
            exit_reason="completed",
            score=0.0,
            status="exploit_failed",
        ),
    )
    write_run(
        rd,
        app="moememos",
        vuln_id="vuln_0",
        model="gpt-5",
        pod_name="pod-bbb",
        summary=make_summary(
            run_id="rep2-pass",
            started_at="2026-04-02T00:00:00+00:00",
            outcome="success",
            score=1.0,
        ),
    )

    # Different cell, always passes.
    write_run(
        rd,
        app="gotify",
        vuln_id="vuln_3",
        model="gpt-5",
        pod_name="pod-ccc",
        summary=make_summary(
            run_id="gotify-pass",
            app="gotify",
            vuln_id="vuln_3",
            outcome="success",
            score=1.0,
        ),
    )

    # Different model, fails.
    write_run(
        rd,
        app="moememos",
        vuln_id="vuln_0",
        model="claude-sonnet-4-6",
        pod_name="pod-ddd",
        summary=make_summary(
            run_id="claude-fail",
            model="claude-sonnet-4-6",
            outcome="failure",
            score=0.0,
            status="exploit_failed",
        ),
    )

    # Missing summary
    write_run(
        rd,
        app="moememos",
        vuln_id="vuln_0",
        model="gpt-5",
        pod_name="pod-eee",
        summary=None,
        dir_name_override="experiment_no-summary",
    )

    # Schema-invalid summary
    bad = make_summary(run_id="bad-schema")
    bad["context"]["workflow"] = "unknown_workflow"
    write_run(
        rd,
        app="moememos",
        vuln_id="vuln_0",
        model="gpt-5",
        pod_name="pod-fff",
        summary=bad,
    )

    # Gold run
    write_run(
        rd,
        app="moememos",
        vuln_id="vuln_0",
        model="gpt-5",
        pod_name="pod-ggg",
        summary=make_summary(run_id="gold1", outcome="success", score=1.0),
        gold=True,
    )

    # Dry run
    write_run(
        rd,
        app="moememos",
        vuln_id="vuln_0",
        model="gpt-5",
        pod_name="pod-hhh",
        summary=make_summary(run_id="dryrun1", dry_run=True),
    )

    # OOM infra error
    write_run(
        rd,
        app="moememos",
        vuln_id="vuln_0",
        model="gpt-5",
        pod_name="pod-iii",
        summary=make_summary(
            run_id="oom1",
            outcome="failure",
            exit_reason="oom",
            score=None,
        ),
    )

    return rd
