"""Tests for agent.backend.ui_connection helpers."""

from unittest.mock import patch

from agent.custom.backend import ui_connection


def test_run_adb_shell_uses_safe_default_start_dir():
    """Default start_dir must be /app, not /app/codebase. Under no_codebase=True
    the codebase mount is omitted and only /app/apk exists; a hard-coded
    /app/codebase would make the wrapping `cd ... && adb shell ...` fail and
    silently swallow the UI dump output.
    """
    with patch.object(
        ui_connection, "execute_adb_command_with_retry", return_value=(0, "", "")
    ) as spy:
        ui_connection.run_adb_shell("uiautomator dump /sdcard/window_dump.xml")

    spy.assert_called_once()
    _, start_dir = spy.call_args.args
    assert start_dir == "/app"


def test_run_adb_pull_uses_safe_default_start_dir():
    with patch.object(
        ui_connection, "execute_adb_command_with_retry", return_value=(0, "x", "")
    ) as spy, patch("builtins.open"):
        ui_connection.run_adb_pull("/sdcard/window_dump.xml", "window_dump.xml")

    spy.assert_called_once()
    _, start_dir = spy.call_args.args
    assert start_dir == "/app"


def test_start_dir_env_override(monkeypatch):
    """START_DIR env var overrides the default — same convention as
    docker_ops.execute_command_internal."""
    monkeypatch.setenv("START_DIR", "/custom")
    with patch.object(
        ui_connection, "execute_adb_command_with_retry", return_value=(0, "", "")
    ) as spy:
        ui_connection.run_adb_shell("noop")

    _, start_dir = spy.call_args.args
    assert start_dir == "/custom"
