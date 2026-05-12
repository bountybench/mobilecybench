from argparse import Namespace
from unittest.mock import MagicMock, patch

import emulator


def test_start_preserves_startup_error_when_cleanup_fails(capsys):
    manager = MagicMock()
    manager.start_in_background.side_effect = RuntimeError("boot failed")
    manager.stop.side_effect = RuntimeError("ADB reset failed")

    with patch("emulator._discover_emulators", return_value=[]), patch(
        "emulator.EmulatorManager", return_value=manager
    ):
        exit_code = emulator.cmd_start(Namespace(sdk="35", headless=True))

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Error: boot failed" in captured.out
    assert "ADB reset failed" in captured.err
