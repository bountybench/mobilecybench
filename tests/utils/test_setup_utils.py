from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from utils import setup_utils


def _runtime_app(tmp_path):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "start_runtime.sh").write_text("#!/usr/bin/env bash\n")
    project_root = tmp_path / "repo"
    project_root.mkdir()
    emulator = SimpleNamespace(check_status=lambda: True)
    return app_dir, project_root, emulator


def test_install_waits_for_adb_before_flag_injection(tmp_path):
    app_dir, project_root, emulator = _runtime_app(tmp_path)
    executor = MagicMock()

    with (
        patch("utils.command_executor.CommandExecutor", return_value=executor),
        patch("utils.setup_utils._wait_for_adb_ready", return_value=True) as wait_adb,
    ):
        setup_utils.install_app_and_setup_backend(
            app_dir,
            emulator,
            project_root,
            build_command_timeout=30,
            inject_flags=True,
        )

    wait_adb.assert_called_once_with()
    executor.run.assert_called_once_with(
        f"bash {project_root / 'inject_flags.sh'}",
        cwd=app_dir,
        timeout=setup_utils._INJECT_FLAGS_TIMEOUT_SECONDS,
    )


def test_install_fails_before_flag_injection_when_adb_not_ready(tmp_path):
    app_dir, project_root, emulator = _runtime_app(tmp_path)
    executor = MagicMock()

    with (
        patch("utils.command_executor.CommandExecutor", return_value=executor),
        patch("utils.setup_utils._wait_for_adb_ready", return_value=False),
        pytest.raises(RuntimeError, match="ADB did not become ready"),
    ):
        setup_utils.install_app_and_setup_backend(
            app_dir,
            emulator,
            project_root,
            build_command_timeout=30,
            inject_flags=True,
        )

    executor.run.assert_not_called()
