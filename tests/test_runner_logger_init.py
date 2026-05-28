"""End-to-end smoke test for runner.py → LoggerManager dir-naming integration.

Pins the contract that `python runner.py <app> --config <cfg>` actually
threads `args.app_name` and `config.{workflow,model}` into the logger so
the on-disk experiment dir uses the new format
``<app>_<workflow>_<model>_<YYYYMMDD-HHMMSS>_<short-uuid>``.

We subprocess a real runner.py invocation (no mocks) but use a fake app
name so the runner fails at ``ensure_app_submodule`` before touching the
emulator or Docker. That keeps the test ~1s without needing those
external dependencies on the dev machine.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
NAMING_TIMESTAMP_RE = r"\d{8}-\d{6}"
NAMING_SHORT_UUID_RE = r"[0-9a-f]{8}"


def _write_minimal_config(path: Path) -> None:
    """Write a config that passes RunnerConfig validation but exercises the naming.

    Mirrors the fields used in the GCP campaign: redteam + claude-opus-4-7.
    """
    path.write_text(
        json.dumps(
            {
                "workflow": "redteam",
                "probe_only": True,
                "attacker_model": "malicious_app",
                "model": "claude-opus-4-7",
                "agent_image": "cybench/mobilecybench:latest",
                "build_type": "download-apk",
                "emulator_display": "headless",
                "network_mode": "permissive",
                "max_iterations": 10,
                "max_model_response_tokens": 1000,
                "dry_run": False,
                "gold_run": False,
            }
        )
    )


def test_runner_creates_dir_with_full_naming(tmp_path: Path) -> None:
    """python runner.py <app> --config <cfg> creates a dir matching the new format."""
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    cfg = tmp_path / "config.json"
    _write_minimal_config(cfg)

    # Fake app name so the runner fails fast at ensure_app_submodule (no
    # apps/<fake>/ on disk) AFTER get_logger_manager has created the dir.
    fake_app = "fake-smoke-app"

    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "PYTHONPATH": str(REPO_ROOT),
        "MOBILECYBENCH_LOGS_DIR": str(logs_dir),
        # No SESSION_ID set → fresh UUID generated.
    }

    # The runner will exit non-zero because ensure_app_submodule fails for
    # a nonexistent app; that's expected. check=False.
    proc = subprocess.run(
        [sys.executable, "runner.py", fake_app, "--config", str(cfg)],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    # Discover the created dir under logs_dir. The new naming has no
    # `experiment_` prefix, so we glob by the fake app name.
    created = sorted(logs_dir.glob(f"{fake_app}_*"))
    assert created, (
        f"runner.py did not create a logs dir under {logs_dir}; "
        f"stdout={proc.stdout!r}; stderr={proc.stderr!r}"
    )
    assert len(created) == 1, f"unexpected multiple dirs: {[p.name for p in created]}"

    name = created[0].name
    # Full format: <fake_app>_redteam_claude-opus-4-7_<ts>_<short_uuid>
    pattern = (
        rf"^{re.escape(fake_app)}_redteam_claude-opus-4-7_"
        rf"{NAMING_TIMESTAMP_RE}_{NAMING_SHORT_UUID_RE}$"
    )
    assert re.match(pattern, name), (
        f"dir name {name!r} doesn't match expected pattern {pattern!r}; "
        f"stderr={proc.stderr!r}"
    )

    # Sanity: the dir should have the experiment.log handler attached
    # (created by _ensure_handlers during configure()).
    assert (
        created[0] / "experiment.log"
    ).exists(), f"experiment.log missing in {created[0]}"


def test_runner_logger_init_announces_correct_path(tmp_path: Path) -> None:
    """The 'Logging initialized (logs_dir=...)' announce line matches the on-disk dir."""
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    cfg = tmp_path / "config.json"
    _write_minimal_config(cfg)

    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "PYTHONPATH": str(REPO_ROOT),
        "MOBILECYBENCH_LOGS_DIR": str(logs_dir),
    }
    proc = subprocess.run(
        [sys.executable, "runner.py", "fake-smoke-app", "--config", str(cfg)],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    # The announce log line is emitted via the console handler, which
    # writes to stderr by default in Python's logging. Look in both.
    combined = (proc.stdout or "") + (proc.stderr or "")
    match = re.search(r"logs_dir=(\S+)", combined)
    assert match, (
        f"no 'Logging initialized (logs_dir=...)' line found; "
        f"stdout={proc.stdout!r}; stderr={proc.stderr!r}"
    )
    announced = Path(match.group(1).rstrip(")"))

    created = sorted(logs_dir.glob("fake-smoke-app_*"))
    assert created, f"no dir created; stderr={proc.stderr!r}"

    assert (
        announced == created[0]
    ), f"announced path {announced} != on-disk dir {created[0]}"
