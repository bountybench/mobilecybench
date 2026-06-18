"""Tests for utils.command_executor.CommandExecutor.

These tests verify that every subprocess spawn site in CommandExecutor sets
stdin=subprocess.DEVNULL. setup_utils.install_app_and_setup_backend uses
CommandExecutor to invoke each app's start_runtime.sh, and several of those
scripts internally invoke `docker exec -i <backend> ...`. If stdin is
inherited from a controlling terminal (e.g. runner.py launched under a
detached tmux session with no attached client), the kernel delivers SIGTTIN
to the child docker exec and freezes the whole setup chain in state T. A
DEVNULL stdin gives those children an immediate EOF instead.
"""

from __future__ import annotations

import subprocess
from unittest import mock

from utils.command_executor import CommandExecutor


def _completed(returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["dummy"], returncode=returncode, stdout="", stderr=""
    )


def test_run_passes_stdin_devnull() -> None:
    with mock.patch(
        "utils.command_executor.subprocess.run", return_value=_completed()
    ) as run:
        CommandExecutor().run("echo hi")
    assert run.call_args.kwargs["stdin"] is subprocess.DEVNULL


def test_start_background_process_passes_stdin_devnull() -> None:
    fake_proc = mock.MagicMock(pid=4242)
    with mock.patch(
        "utils.command_executor.subprocess.Popen", return_value=fake_proc
    ) as popen:
        CommandExecutor().start_background_process("echo hi")
    assert popen.call_args.kwargs["stdin"] is subprocess.DEVNULL


def test_run_with_progress_passes_stdin_devnull() -> None:
    fake_proc = mock.MagicMock()
    # Streams need to be iterable AND have close() — the helper thread loops
    # over each stream and closes it on exit.
    fake_proc.stdout = mock.MagicMock(__iter__=lambda self: iter([]))
    fake_proc.stderr = mock.MagicMock(__iter__=lambda self: iter([]))
    # First poll() returns None so the spinner loop runs once, second
    # returns 0 so the loop exits.
    fake_proc.poll.side_effect = [None, 0]
    fake_proc.returncode = 0

    with mock.patch(
        "utils.command_executor.subprocess.Popen", return_value=fake_proc
    ) as popen:
        CommandExecutor().run_with_progress("echo hi", timeout=5, message="probe")
    assert popen.call_args.kwargs["stdin"] is subprocess.DEVNULL
