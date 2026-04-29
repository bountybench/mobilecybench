"""Regression tests for `utils.logger` import-time behavior.

These tests pin the contract:
- a bare `import utils.logger` must not touch the filesystem,
- when `MOBILECYBENCH_LOGS_DIR` / `MOBILECYBENCH_SESSION_ID` are set, the
  manager initializes fully (the runner / GKE path), and
- an explicit `configure()` call upgrades a minimal manager to a full one.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_python(code: str, *, env_extra: dict[str, str] | None = None) -> str:
    """Run a Python snippet in a fresh interpreter and return stdout (stripped)."""
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(REPO_ROOT),
        "HOME": os.environ.get("HOME", ""),
    }
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def test_bare_import_does_not_create_logs_dir(tmp_path: Path) -> None:
    cwd = tmp_path / "scratch"
    cwd.mkdir()
    code = (
        "import os, sys\n"
        f"sys.path.insert(0, {str(REPO_ROOT)!r})\n"
        "import utils.logger  # noqa: F401\n"
        "from utils.logger import logger_manager\n"
        "print(logger_manager.get_logs_dir())\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(cwd),
        env={
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
        },
        capture_output=True,
        text=True,
        check=True,
    )
    assert proc.stdout.strip() == "None"
    # No `logs/` directory should have been created in cwd.
    assert not (cwd / "logs").exists()


def test_env_hint_triggers_full_configure(tmp_path: Path) -> None:
    logs_dir = tmp_path / "envlogs"
    out = _run_python(
        "from utils.logger import logger_manager\n"
        "print(logger_manager.get_logs_dir())\n",
        env_extra={
            "MOBILECYBENCH_LOGS_DIR": str(logs_dir),
            "MOBILECYBENCH_SESSION_ID": "test_env_session",
        },
    )
    expected = logs_dir / "experiment_test_env_session"
    assert out == str(expected)
    assert expected.is_dir()
    assert (expected / "experiment.log").exists()


def test_explicit_configure_upgrades_minimal(tmp_path: Path) -> None:
    logs_dir = tmp_path / "explicitlogs"
    out = _run_python(
        "import os\n"
        "from utils.logger import logger_manager\n"
        "assert logger_manager.get_logs_dir() is None\n"
        f"os.environ['MOBILECYBENCH_LOGS_DIR'] = {str(logs_dir)!r}\n"
        "os.environ['MOBILECYBENCH_SESSION_ID'] = 'explicit_session'\n"
        "logger_manager.configure(logger_manager._default_config(), announce=False)\n"
        "print(logger_manager.get_logs_dir())\n",
    )
    expected = logs_dir / "experiment_explicit_session"
    assert out == str(expected)
    assert expected.is_dir()


def test_first_log_call_materializes_dir_and_persists_record(tmp_path: Path) -> None:
    """Bootstrap path: the very first log line must land on disk.

    This is the case that protects overnight GKE runs — even if the runner
    fails before its explicit configure() reaches line 514 (e.g. config
    load failure on line 498), the error must still end up in a real
    file on disk.

    The env vars are set *after* import (so __init__ takes the minimal
    path) but *before* the first log call (so bootstrap's configure()
    routes the dir to the env-pinned location, matching how runner.py
    reads its config and then logs).
    """
    logs_dir = tmp_path / "lazylogs"
    out = _run_python(
        "import os\n"
        "from utils.logger import logger, logger_manager\n"
        "assert logger_manager.get_logs_dir() is None  # pre-emit: minimal\n"
        f"os.environ['MOBILECYBENCH_LOGS_DIR'] = {str(logs_dir)!r}\n"
        "os.environ['MOBILECYBENCH_SESSION_ID'] = 'lazy_session'\n"
        "logger.error('config load exploded: bad path')\n"
        "d = logger_manager.get_logs_dir()\n"
        "assert d is not None and d.is_dir()\n"
        "print('LOGS_DIR=' + str(d))\n",
    )
    expected = logs_dir / "experiment_lazy_session"
    # Console handler writes to stdout too (existing behavior), so parse the marker.
    last = [ln for ln in out.splitlines() if ln.startswith("LOGS_DIR=")][-1]
    assert last == f"LOGS_DIR={expected}"
    # Bootstrap fired during `logger.error(...)` and configure() created
    # the same four file artifacts as eager-mode init. The error message
    # must be in errors.log (which only captures WARNING+).
    errors_log = expected / "errors.log"
    assert errors_log.exists()
    assert "config load exploded: bad path" in errors_log.read_text()


def test_agent_logger_first_emit_also_bootstraps(tmp_path: Path) -> None:
    """The agent logger shares the same bootstrap filter as the parent.

    Without this, an agent-only emission path (custom_agent code logs
    via `agent_logger`, not `logger`) would skip materialization.
    """
    logs_dir = tmp_path / "agentlogs"
    out = _run_python(
        "import os\n"
        "from utils.logger import agent_logger, logger_manager\n"
        "assert logger_manager.get_logs_dir() is None\n"
        f"os.environ['MOBILECYBENCH_LOGS_DIR'] = {str(logs_dir)!r}\n"
        "os.environ['MOBILECYBENCH_SESSION_ID'] = 'agent_session'\n"
        "agent_logger.info('agent woke up')\n"
        "print('LOGS_DIR=' + str(logger_manager.get_logs_dir()))\n",
    )
    expected = logs_dir / "experiment_agent_session"
    last = [ln for ln in out.splitlines() if ln.startswith("LOGS_DIR=")][-1]
    assert last == f"LOGS_DIR={expected}"
    assert (expected / "agent.log").exists()
