"""Tests for the emulator pidfile reaper introduced for R2.21.

Covers:
  - `_emulator_pidfile`: pure path computation, no I/O side effects
  - `_pid_is_emulator`: discriminating emulator-shaped vs other PIDs
  - `_reap_emulator_pidfile`: every observable branch (no file, garbage,
    dead PID, alive non-emulator, alive emulator, TOCTOU re-check
    before SIGKILL)
  - Integration: EmulatorManager start writes pidfile + stop reaps it

The "alive emulator" tests use real subprocesses with `exec -a` to fake
the cmdline, which is portable across macOS bash and Linux bash. Each
test cleans up its own subprocess in a try/finally so a test failure
never leaks a process onto the host.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from unittest.mock import MagicMock, patch

import pytest

from utils.emulator_manager import (
    EmulatorManager,
    EmulatorState,
    _emulator_pidfile,
    _pid_is_emulator,
    _reap_emulator_pidfile,
)

# ---------------------------------------------------------------------------
# Process-spawn helpers
# ---------------------------------------------------------------------------


def _spawn_named(name: str, lifetime_s: int = 30) -> subprocess.Popen:
    """Spawn a long-running process with the given argv[0].

    `exec -a NAME COMMAND` overrides argv[0] so `ps -p <pid> -o command=`
    reports NAME instead of the underlying binary. Used to simulate a
    process that pretends to be (or pretends not to be) an emulator.

    NOTE: ``exec -a`` is a bash builtin extension; `/bin/sh` on Ubuntu
    points at dash which does not support it (silent exit 127 in CI),
    so we invoke bash explicitly. Tests skip if bash isn't installed,
    rather than emit a confusing failure.
    """
    return subprocess.Popen(
        ["bash", "-c", f"exec -a '{name}' sleep {lifetime_s}"],
    )


_BASH_AVAILABLE = (
    subprocess.run(["bash", "-c", "exit 0"], capture_output=True).returncode == 0
)
_NEEDS_BASH = pytest.mark.skipif(
    not _BASH_AVAILABLE,
    reason="bash is required for `exec -a` argv override (dash doesn't support it)",
)


def _terminate(proc: subprocess.Popen, *, timeout: float = 5.0) -> None:
    """Best-effort kill + reap of a test subprocess."""
    if proc.poll() is None:
        proc.kill()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        pass


def _plant_pidfile(tmp_path, content: str):
    """Mirror what `start_in_background` does on a real spawn: mkdir parent
    (since `_emulator_pidfile` is now a pure path helper), then write."""
    pidfile = _emulator_pidfile(tmp_path)
    pidfile.parent.mkdir(parents=True, exist_ok=True)
    pidfile.write_text(content)
    return pidfile


# ---------------------------------------------------------------------------
# _emulator_pidfile
# ---------------------------------------------------------------------------


def test_emulator_pidfile_returns_path_without_io(tmp_path):
    """`_emulator_pidfile` is a pure path computation — no directory creation.

    The directory is created lazily by the writer in `start_in_background`.
    Callers that only want the path (e.g. the reaper checking
    ``pidfile.exists()``) must not materialise ``.runtime_state/`` on disk.
    """
    pidfile = _emulator_pidfile(tmp_path)
    assert pidfile == tmp_path / ".runtime_state" / "emulator.pid"
    assert not (tmp_path / ".runtime_state").exists()


# ---------------------------------------------------------------------------
# _pid_is_emulator
# ---------------------------------------------------------------------------


def test_pid_is_emulator_dead_pid_returns_false():
    """A PID that has already exited is not 'an emulator'."""
    proc = subprocess.Popen(["sleep", "0.01"])
    proc.wait()
    # PID may be recycled by now in theory, but in practice there's a >>1s
    # delay before the kernel reuses it on Linux/macOS. 0 = not-emulator.
    assert _pid_is_emulator(proc.pid) is False


@_NEEDS_BASH
def test_pid_is_emulator_recognises_emulator_argv():
    proc = _spawn_named("emulator -avd test")
    try:
        # `exec -a` takes a beat to apply.
        time.sleep(0.2)
        assert _pid_is_emulator(proc.pid) is True
    finally:
        _terminate(proc)


@_NEEDS_BASH
def test_pid_is_emulator_recognises_qemu_system_argv():
    proc = _spawn_named("qemu-system-aarch64-headless -avd MobileCybenchEmulator")
    try:
        time.sleep(0.2)
        assert _pid_is_emulator(proc.pid) is True
    finally:
        _terminate(proc)


def test_pid_is_emulator_rejects_unrelated_argv():
    """A `sleep` (or anything else) must NOT be classified as emulator."""
    proc = subprocess.Popen(["sleep", "30"])
    try:
        time.sleep(0.2)
        assert _pid_is_emulator(proc.pid) is False
    finally:
        _terminate(proc)


def test_pid_is_emulator_handles_ps_subprocess_failure(monkeypatch):
    """If `ps` itself fails (FileNotFoundError, timeout), return False — never crash."""
    # Force os.kill(pid, 0) to succeed (simulate alive PID), then ps to fail.
    monkeypatch.setattr(os, "kill", lambda pid, sig: None)

    def boom_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="ps", timeout=5)

    monkeypatch.setattr(subprocess, "run", boom_run)
    assert _pid_is_emulator(99999) is False


def test_pid_is_emulator_handles_permission_error():
    """A PID owned by a different user (PermissionError on os.kill) is treated as not-our-emulator."""
    with patch("utils.emulator_manager.os.kill", side_effect=PermissionError):
        assert _pid_is_emulator(1) is False


# ---------------------------------------------------------------------------
# _reap_emulator_pidfile
# ---------------------------------------------------------------------------


def test_reap_no_pidfile_is_noop(tmp_path):
    """If the pidfile doesn't exist, the function returns silently and does
    not materialise `.runtime_state/` as a side effect."""
    _reap_emulator_pidfile(tmp_path)
    assert not (tmp_path / ".runtime_state").exists()


def test_reap_garbage_pidfile_logs_and_removes(tmp_path, caplog):
    pidfile = _plant_pidfile(tmp_path, "not-an-int\n")
    _reap_emulator_pidfile(tmp_path)
    assert not pidfile.exists()
    assert any("Stale emulator pidfile" in m for m in caplog.messages)


def test_reap_dead_pid_removes_pidfile(tmp_path):
    """A pidfile whose PID has already exited gets cleaned up; nothing is killed."""
    proc = subprocess.Popen(["sleep", "0.01"])
    proc.wait()
    pidfile = _plant_pidfile(tmp_path, f"{proc.pid}\n")
    _reap_emulator_pidfile(tmp_path)
    assert not pidfile.exists()


def test_reap_refuses_to_kill_non_emulator_pid(tmp_path):
    """The safety case: pidfile points at a live `sleep` (not emulator-shaped).

    The reaper must remove the pidfile BUT NOT signal the process. This is
    the central invariant — we never kill a recycled or unrelated PID.
    """
    proc = subprocess.Popen(["sleep", "30"])
    try:
        pidfile = _plant_pidfile(tmp_path, f"{proc.pid}\n")
        _reap_emulator_pidfile(tmp_path)
        assert not pidfile.exists()
        # The unrelated process must still be running.
        assert proc.poll() is None, "reaper killed an unrelated PID — safety violation"
    finally:
        _terminate(proc)


@_NEEDS_BASH
def test_reap_kills_emulator_shaped_pid(tmp_path):
    """The happy path: pidfile points at a long-running emulator-shaped process.

    The reaper SIGTERMs it, waits for graceful exit, and removes the pidfile.
    Exit code -SIGTERM (negative on POSIX) confirms the kill came from us.
    """
    proc = _spawn_named("qemu-system-aarch64 -avd MobileCybenchEmulatorAPI35")
    try:
        time.sleep(0.2)
        pidfile = _plant_pidfile(tmp_path, f"{proc.pid}\n")
        _reap_emulator_pidfile(tmp_path, term_grace_seconds=2.0)
        proc.wait(timeout=5)
        assert not pidfile.exists()
        assert proc.returncode == -signal.SIGTERM
    finally:
        _terminate(proc)


@_NEEDS_BASH
def test_reap_sigkill_when_process_ignores_sigterm(tmp_path, monkeypatch):
    """If SIGTERM is ignored and the process survives the grace period, reaper
    re-verifies emulator-shape and sends SIGKILL.

    Emulating "ignore SIGTERM" portably is tricky (sleep handles it); we mock
    os.kill so SIGTERM is a no-op while letting SIGKILL through.
    """
    proc = _spawn_named("emulator-test-ignore-sigterm")
    try:
        time.sleep(0.2)
        original_kill = os.kill
        sent_signals: list[int] = []

        def fake_kill(pid: int, sig: int) -> None:
            sent_signals.append(sig)
            if sig == signal.SIGTERM:
                # Pretend SIGTERM was delivered but the process ignored it.
                return
            # All other signals (including SIGKILL and the liveness probe
            # signal 0) go through unchanged.
            original_kill(pid, sig)

        monkeypatch.setattr(os, "kill", fake_kill)

        pidfile = _plant_pidfile(tmp_path, f"{proc.pid}\n")
        _reap_emulator_pidfile(tmp_path, term_grace_seconds=0.5)

        proc.wait(timeout=5)
        assert not pidfile.exists()
        # Both SIGTERM (no-op) and SIGKILL (real) were sent.
        assert signal.SIGTERM in sent_signals
        assert signal.SIGKILL in sent_signals
        # SIGKILL terminated the process.
        assert proc.returncode == -signal.SIGKILL
    finally:
        _terminate(proc)


@_NEEDS_BASH
def test_reap_skips_sigkill_if_pid_recycled_during_grace(tmp_path, monkeypatch):
    """TOCTOU defence: if `_pid_is_emulator` returns False during the grace
    loop (simulating "process exited and PID was recycled to something else"),
    the reaper bails out instead of SIGKILLing the recycled PID.
    """
    proc = _spawn_named("emulator-test-recycle")
    try:
        time.sleep(0.2)
        pidfile = _plant_pidfile(tmp_path, f"{proc.pid}\n")

        # First call (the upfront check) returns True (real cmdline).
        # Second call (inside the wait loop) returns False (simulating
        # the original emulator exited and PID got recycled).
        call_count = {"n": 0}

        def fake_is_emulator(pid: int) -> bool:
            call_count["n"] += 1
            return call_count["n"] == 1

        monkeypatch.setattr("utils.emulator_manager._pid_is_emulator", fake_is_emulator)

        sigterm_sent = {"yes": False}
        sigkill_sent = {"yes": False}
        original_kill = os.kill

        def fake_kill(pid: int, sig: int) -> None:
            if sig == signal.SIGTERM:
                sigterm_sent["yes"] = True
                return  # don't actually kill the test process
            if sig == signal.SIGKILL:
                sigkill_sent["yes"] = True
                return
            original_kill(pid, sig)

        monkeypatch.setattr(os, "kill", fake_kill)

        _reap_emulator_pidfile(tmp_path, term_grace_seconds=0.5)

        # SIGTERM was sent (the upfront check passed); SIGKILL must NOT
        # have been sent because _pid_is_emulator returned False during
        # the grace loop.
        assert sigterm_sent["yes"] is True
        assert sigkill_sent["yes"] is False, (
            "reaper sent SIGKILL despite pid-shape re-check returning False — "
            "TOCTOU race not closed"
        )
        assert not pidfile.exists()
    finally:
        _terminate(proc)


def test_reap_pidfile_with_trailing_whitespace(tmp_path):
    """Pidfiles written with a trailing newline must still parse."""
    proc = subprocess.Popen(["sleep", "0.01"])
    proc.wait()
    pidfile = _plant_pidfile(tmp_path, f"  {proc.pid}\n")  # leading + trailing whitespace
    _reap_emulator_pidfile(tmp_path)
    assert not pidfile.exists()


# ---------------------------------------------------------------------------
# Integration with EmulatorManager
# ---------------------------------------------------------------------------


@patch("utils.emulator_manager.subprocess.Popen")
@patch("utils.emulator_manager.subprocess.run")
def test_start_in_background_writes_pidfile(mock_run, mock_popen, tmp_path):
    """When EmulatorManager spawns the native emulator, it persists the spawned PID."""
    with patch.dict("os.environ", {"ANDROID_HOME": str(tmp_path / "android")}):
        with patch("utils.emulator_manager.Path.exists", return_value=True):
            mgr = EmulatorManager(
                project_root=tmp_path,
                sdk_version="35",
                app_name="conversations",
                emulator_display="headed",
                emulator_backend="native",
            )
            mgr._verify_avd_exists = MagicMock()
            mock_popen.return_value = MagicMock(
                pid=42424, poll=MagicMock(return_value=None)
            )
            mock_run.return_value = MagicMock(
                returncode=0, stdout="List of devices attached\n", stderr=""
            )
            mgr.start_in_background()

    pidfile = tmp_path / ".runtime_state" / "emulator.pid"
    assert pidfile.exists()
    assert pidfile.read_text().strip() == "42424"


@patch("utils.emulator_manager.subprocess.Popen")
@patch("utils.emulator_manager.subprocess.run")
def test_start_in_background_reaps_orphan_first(mock_run, mock_popen, tmp_path):
    """Pre-existing pidfile from a crashed prior run is reaped before the new
    emulator starts. Otherwise the current run would race with the orphan.
    """
    # Plant a pidfile pointing at an already-exited PID so reaping is a no-op
    # kill-wise but still exercises the cleanup path before spawn.
    proc = subprocess.Popen(["sleep", "0.01"])
    proc.wait()
    pidfile = _plant_pidfile(tmp_path, f"{proc.pid}\n")

    with patch.dict("os.environ", {"ANDROID_HOME": str(tmp_path / "android")}):
        with patch("utils.emulator_manager.Path.exists", return_value=True):
            mgr = EmulatorManager(
                project_root=tmp_path,
                sdk_version="35",
                app_name="conversations",
                emulator_display="headed",
                emulator_backend="native",
            )
            mgr._verify_avd_exists = MagicMock()
            mock_popen.return_value = MagicMock(
                pid=98765, poll=MagicMock(return_value=None)
            )
            mock_run.return_value = MagicMock(
                returncode=0, stdout="List of devices attached\n", stderr=""
            )
            mgr.start_in_background()

    # New PID was written, replacing the orphan's.
    assert pidfile.exists()
    assert pidfile.read_text().strip() == "98765"


@patch("utils.emulator_manager.subprocess.run")
def test_stop_native_emulator_removes_pidfile(mock_run, tmp_path):
    """EmulatorManager.stop()'s native path runs the reaper in its finally block."""
    with patch.dict("os.environ", {"ANDROID_HOME": str(tmp_path / "android")}):
        with patch("utils.emulator_manager.Path.exists", return_value=True):
            mgr = EmulatorManager(
                project_root=tmp_path,
                sdk_version="35",
                app_name="conversations",
                emulator_display="headed",
                emulator_backend="native",
            )

    # Plant a pidfile pointing at a dead PID so reaping is a no-op kill-wise.
    proc = subprocess.Popen(["sleep", "0.01"])
    proc.wait()
    pidfile = _plant_pidfile(tmp_path, f"{proc.pid}\n")

    mgr.state = EmulatorState.RUNNING
    mgr.device_id = "emulator-5554"
    mgr.process = MagicMock()
    mgr.process.poll.return_value = None
    mgr.process.wait.return_value = None
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    mgr.stop()

    assert (
        not pidfile.exists()
    ), "stop() must remove the pidfile via _reap_emulator_pidfile"
