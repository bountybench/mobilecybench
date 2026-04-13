import importlib
import sys
from unittest.mock import Mock, patch


def _import_flag_injection_utils():
    sys.modules.pop("utils.flag_injection_utils", None)
    with patch(
        "utils.uuid_flags_utils.load_flags",
        return_value={"APP_FILES_FLAG_CONTENT": "flag", "CONTAINER_FLAGS": {}},
    ):
        return importlib.import_module("utils.flag_injection_utils")


def test_ensure_root_accepts_transient_adb_restart(monkeypatch):
    flag_injection_utils = _import_flag_injection_utils()
    calls = []

    def fake_run(cmd, log_errors=True):
        calls.append(cmd)
        if cmd == ["adb", "root"]:
            return Mock(
                returncode=1,
                stdout="",
                stderr="adb: unable to connect for root: closed\n",
            )
        if cmd == ["adb", "shell", "id"]:
            return Mock(returncode=0, stdout="uid=0(root) gid=0(root)\n", stderr="")
        return Mock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(flag_injection_utils, "_run", fake_run)
    monkeypatch.setattr(flag_injection_utils, "_wait_for_shell", lambda: None)

    assert flag_injection_utils._ensure_root() is True
    assert ["adb", "root"] in calls
    assert ["adb", "shell", "id"] in calls


def test_ensure_root_requires_root_shell(monkeypatch):
    flag_injection_utils = _import_flag_injection_utils()

    def fake_run(cmd, log_errors=True):
        if cmd == ["adb", "shell", "id"]:
            return Mock(
                returncode=0, stdout="uid=2000(shell) gid=2000(shell)\n", stderr=""
            )
        return Mock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(flag_injection_utils, "_run", fake_run)
    monkeypatch.setattr(flag_injection_utils, "_wait_for_shell", lambda: None)

    assert flag_injection_utils._ensure_root() is False
