"""Regression tests for `utils.logger` import-time behavior.

These tests pin the contract:
- a bare `import utils.logger` must not touch the filesystem,
- when `MOBILECYBENCH_LOGS_DIR` / `MOBILECYBENCH_SESSION_ID` are set, the
  manager initializes fully (the runner / GKE path), and
- an explicit `configure()` call upgrades a minimal manager to a full one.
"""

from __future__ import annotations

import os
import re
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
    # No app_name passed → bare UUID fallback (see LoggerManager._compute_dirname).
    expected = logs_dir / "test_env_session"
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
    expected = logs_dir / "explicit_session"
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
    expected = logs_dir / "lazy_session"
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
    expected = logs_dir / "agent_session"
    last = [ln for ln in out.splitlines() if ln.startswith("LOGS_DIR=")][-1]
    assert last == f"LOGS_DIR={expected}"
    assert (expected / "agent_run" / "agent.log").exists()


# ────────────────────────────────────────────────────────────────────────
# Tests for the new <app>_<workflow>_<model>_<ts>_<short> naming scheme.
# Naming is computed in LoggerManager._compute_dirname() with a 3-tier
# fallback (full → app+ts+short → bare run_id) so unconfigured/legacy
# call sites keep working.
# ────────────────────────────────────────────────────────────────────────

NAMING_TIMESTAMP_RE = r"\d{8}-\d{6}"
NAMING_SHORT_UUID_RE = r"[0-9a-f]{8}"


def _last_marker(out: str, prefix: str) -> str:
    """Pull the last `prefix...` line from stdout (handles announce noise)."""
    matches = [ln[len(prefix) :] for ln in out.splitlines() if ln.startswith(prefix)]
    assert matches, f"no {prefix!r} marker in stdout: {out!r}"
    return matches[-1]


def test_full_naming_when_app_workflow_model_provided(tmp_path: Path) -> None:
    """Full format: <app>_<workflow>_<model>_<YYYYMMDD-HHMMSS>_<short-uuid>."""
    logs_dir = tmp_path / "fulllogs"
    out = _run_python(
        "from utils.logger import get_logger_manager\n"
        "lm = get_logger_manager(\n"
        "    config={'workflow': 'redteam', 'model': 'claude-opus-4-7'},\n"
        "    app_name='ntfy-android',\n"
        ")\n"
        "print('NAME=' + lm.get_logs_dir().name)\n",
        env_extra={
            "MOBILECYBENCH_LOGS_DIR": str(logs_dir),
            "MOBILECYBENCH_SESSION_ID": "abc12345-def0-1111-2222-333333333333",
        },
    )
    name = _last_marker(out, "NAME=")
    pattern = rf"^ntfy-android_redteam_claude-opus-4-7_{NAMING_TIMESTAMP_RE}_abc12345$"
    assert re.match(pattern, name), f"got {name!r}; expected pattern {pattern!r}"


def test_partial_naming_when_workflow_or_model_missing(tmp_path: Path) -> None:
    """Partial fallback: <app>_<ts>_<short> when workflow/model unavailable."""
    logs_dir = tmp_path / "partiallogs"
    out = _run_python(
        "from utils.logger import get_logger_manager\n"
        "lm = get_logger_manager(config={'log_level': 'info'}, app_name='termux')\n"
        "print('NAME=' + lm.get_logs_dir().name)\n",
        env_extra={
            "MOBILECYBENCH_LOGS_DIR": str(logs_dir),
            "MOBILECYBENCH_SESSION_ID": "feedbeef-1234-5678-9abc-def012345678",
        },
    )
    name = _last_marker(out, "NAME=")
    pattern = rf"^termux_{NAMING_TIMESTAMP_RE}_feedbeef$"
    assert re.match(pattern, name), f"got {name!r}; expected pattern {pattern!r}"


def test_bare_uuid_when_no_app_name(tmp_path: Path) -> None:
    """Bare fallback: just the run_id when no app_name supplied."""
    logs_dir = tmp_path / "barelogs"
    out = _run_python(
        "from utils.logger import get_logger_manager\n"
        "lm = get_logger_manager(\n"
        "    config={'workflow': 'redteam', 'model': 'claude-opus-4-7'},\n"
        ")\n"
        "print('NAME=' + lm.get_logs_dir().name)\n",
        env_extra={
            "MOBILECYBENCH_LOGS_DIR": str(logs_dir),
            "MOBILECYBENCH_SESSION_ID": "deadbeef-1111-2222-3333-444444444444",
        },
    )
    assert _last_marker(out, "NAME=") == ("deadbeef-1111-2222-3333-444444444444")


def test_app_name_preserved_across_reconfigure(tmp_path: Path) -> None:
    """A reconfigure() call without app_name keeps the previously-set value.

    Protects test/agent code paths that reconfigure with just a config dict.
    """
    logs_dir = tmp_path / "reconfiglogs"
    out = _run_python(
        "from utils.logger import get_logger_manager\n"
        "lm = get_logger_manager(\n"
        "    config={'workflow': 'redteam', 'model': 'claude-opus-4-7'},\n"
        "    app_name='wallabag',\n"
        ")\n"
        "# Reconfigure without app_name; should preserve 'wallabag'.\n"
        "lm.configure(\n"
        "    {'workflow': 'redteam', 'model': 'gpt-5.5'},\n"
        "    announce=False,\n"
        ")\n"
        "print('NAME=' + lm.get_logs_dir().name)\n",
        env_extra={
            "MOBILECYBENCH_LOGS_DIR": str(logs_dir),
            "MOBILECYBENCH_SESSION_ID": "aaaaaaaa-1111-2222-3333-444444444444",
        },
    )
    name = _last_marker(out, "NAME=")
    pattern = rf"^wallabag_redteam_gpt-5\.5_{NAMING_TIMESTAMP_RE}_aaaaaaaa$"
    assert re.match(pattern, name), f"got {name!r}; expected pattern {pattern!r}"


def test_bootstrap_filter_does_not_re_enter_configure(tmp_path: Path) -> None:
    """Regression: bootstrap filter must not fire during/after explicit configure().

    The bug: `_configure_minimal()` arms a one-shot `_BootstrapFilter` so the
    first log emit triggers full configure() lazily. If that filter persists
    into a later explicit `configure(full_config)`, the "Logging initialized"
    announce line fires the filter, which re-enters configure() with
    `_default_config()` (no workflow/model). That wipes the rich config and
    causes the experiment dir to be renamed from full format to partial
    format (the very same `prev_logs_dir.rename(self._logs_dir)` path that
    promotes bootstrap dirs to final names misfires here).

    This test exercises the real runner sequence: bare `import utils.logger`
    (no env hint → minimal mode + bootstrap filter armed), THEN explicit
    `get_logger_manager(config=..., app_name=...)`. The on-disk dir must
    keep the full-format name from the explicit configure call.
    """
    logs_dir = tmp_path / "bootstrap_then_configure"
    out = _run_python(
        "import os\n"
        "import utils.logger  # minimal init, bootstrap filter armed\n"
        f"os.environ['MOBILECYBENCH_LOGS_DIR'] = {str(logs_dir)!r}\n"
        "os.environ['MOBILECYBENCH_SESSION_ID'] = "
        "'feedface-1111-2222-3333-444444444444'\n"
        "from utils.logger import get_logger_manager, logger_manager\n"
        # Explicit configure with full info.
        "get_logger_manager(\n"
        "    config={'workflow': 'redteam', 'model': 'claude-opus-4-7'},\n"
        "    app_name='ntfy-android',\n"
        ")\n"
        # Trigger another log emit AFTER explicit configure. Without the fix
        # this would re-enter configure() with default_config and rename
        # the dir to partial format.
        "from utils.logger import logger\n"
        "logger.info('post-configure emit; must not re-enter configure')\n"
        "print('NAME=' + logger_manager.get_logs_dir().name)\n",
    )
    name = _last_marker(out, "NAME=")
    pattern = rf"^ntfy-android_redteam_claude-opus-4-7_{NAMING_TIMESTAMP_RE}_feedface$"
    assert re.match(
        pattern, name
    ), f"dir renamed away from full format: {name!r}; expected {pattern!r}"
    # And exactly one dir on disk — no orphaned full-or-partial sibling.
    on_disk = sorted(p.name for p in logs_dir.iterdir() if p.is_dir())
    assert on_disk == [name], f"unexpected sibling dirs: {on_disk}"


def test_reconfigure_renames_bootstrap_dir_to_full_name(tmp_path: Path) -> None:
    """Bootstrap-time minimal dir (bare UUID) is renamed to full name on configure().

    Protects the runner flow: `import utils.logger` triggers bootstrap with
    bare UUID dir, then runner's explicit `get_logger_manager(config=..., app_name=...)`
    upgrades it. The existing `prev_logs_dir.rename(self._logs_dir)` path in
    configure() handles this transparently when the name changes.
    """
    logs_dir = tmp_path / "renamelogs"
    out = _run_python(
        "import os\n"
        "from utils.logger import logger, logger_manager, get_logger_manager\n"
        # Force minimal init by emitting before configure().
        f"os.environ['MOBILECYBENCH_LOGS_DIR'] = {str(logs_dir)!r}\n"
        "os.environ['MOBILECYBENCH_SESSION_ID'] = 'cafebabe-1111-2222-3333-444444444444'\n"
        "logger.info('first emit creates bare-UUID dir')\n"
        "pre = logger_manager.get_logs_dir().name\n"
        "print('PRE=' + pre)\n"
        # Now reconfigure with full app/workflow/model — should rename.
        "get_logger_manager(\n"
        "    config={'workflow': 'redteam', 'model': 'claude-opus-4-7'},\n"
        "    app_name='openhab',\n"
        ")\n"
        "post = logger_manager.get_logs_dir().name\n"
        "print('POST=' + post)\n",
    )
    lines = out.splitlines()
    pre = next(ln for ln in lines if ln.startswith("PRE="))[4:]
    post = next(ln for ln in lines if ln.startswith("POST="))[5:]
    # Pre: bare UUID
    assert pre == "cafebabe-1111-2222-3333-444444444444", f"pre={pre!r}"
    # Post: full format with same short_uuid suffix
    pattern = rf"^openhab_redteam_claude-opus-4-7_{NAMING_TIMESTAMP_RE}_cafebabe$"
    assert re.match(pattern, post), f"post={post!r}; expected pattern {pattern!r}"
    # Verify the rename actually moved the dir on disk (not duplicated).
    assert (logs_dir / post).is_dir(), f"new dir missing: {logs_dir / post}"
    assert not (logs_dir / pre).exists(), f"old dir should be gone: {logs_dir / pre}"
