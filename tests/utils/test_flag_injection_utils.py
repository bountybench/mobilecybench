import importlib
import subprocess
import sys


def _load_flag_injection_utils(monkeypatch):
    import utils.uuid_flags_utils as uuid_flags_utils

    monkeypatch.setattr(
        uuid_flags_utils,
        "load_flags",
        lambda _: {"APP_FILES_FLAG_CONTENT": "test-flag", "CONTAINER_FLAGS": {}},
    )
    sys.modules.pop("utils.flag_injection_utils", None)
    return importlib.import_module("utils.flag_injection_utils")


def _completed(cmd, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)


def test_ensure_root_accepts_closed_adbd_restart_when_shell_is_root(monkeypatch):
    flag_injection_utils = _load_flag_injection_utils(monkeypatch)
    calls = []

    def fake_run(cmd, log_errors=True):
        calls.append((cmd, log_errors))
        if cmd == ["adb", "root"]:
            return _completed(
                cmd, 1, stderr="adb: unable to connect for root: closed\n"
            )
        if cmd == ["adb", "shell", "id"]:
            return _completed(cmd, 0, stdout="uid=0(root) gid=0(root)\n")
        return _completed(cmd)

    monkeypatch.setattr(flag_injection_utils, "_run", fake_run)
    monkeypatch.setattr(flag_injection_utils, "_wait_for_shell", lambda: None)

    assert flag_injection_utils._ensure_root() is True
    assert (["adb", "root"], False) in calls


def test_ensure_root_retries_until_shell_reports_root(monkeypatch):
    flag_injection_utils = _load_flag_injection_utils(monkeypatch)
    monkeypatch.setattr(flag_injection_utils, "_ADB_RESTART_ATTEMPTS", 3)
    sleeps = []
    id_outputs = iter(
        ["uid=2000(shell) gid=2000(shell)\n", "uid=0(root) gid=0(root)\n"]
    )
    calls = []

    def fake_run(cmd, log_errors=True):
        calls.append(cmd)
        if cmd == ["adb", "root"]:
            return _completed(
                cmd, 1, stderr="adb: unable to connect for root: closed\n"
            )
        if cmd == ["adb", "shell", "id"]:
            return _completed(cmd, 0, stdout=next(id_outputs))
        return _completed(cmd)

    monkeypatch.setattr(flag_injection_utils, "_run", fake_run)
    monkeypatch.setattr(flag_injection_utils, "_wait_for_shell", lambda: None)
    monkeypatch.setattr(
        flag_injection_utils.time, "sleep", lambda seconds: sleeps.append(seconds)
    )

    assert flag_injection_utils._ensure_root() is True
    assert calls.count(["adb", "root"]) == 2
    assert sleeps == [flag_injection_utils._ADB_RESTART_RETRY_DELAY_SECONDS]


def test_ensure_root_fails_after_retries_when_shell_never_reports_root(monkeypatch):
    flag_injection_utils = _load_flag_injection_utils(monkeypatch)
    monkeypatch.setattr(flag_injection_utils, "_ADB_RESTART_ATTEMPTS", 2)
    sleeps = []
    calls = []

    def fake_run(cmd, log_errors=True):
        calls.append(cmd)
        if cmd == ["adb", "root"]:
            return _completed(
                cmd, 1, stderr="adbd cannot run as root in production builds\n"
            )
        if cmd == ["adb", "shell", "id"]:
            return _completed(cmd, 0, stdout="uid=2000(shell) gid=2000(shell)\n")
        return _completed(cmd)

    monkeypatch.setattr(flag_injection_utils, "_run", fake_run)
    monkeypatch.setattr(flag_injection_utils, "_wait_for_shell", lambda: None)
    monkeypatch.setattr(
        flag_injection_utils.time, "sleep", lambda seconds: sleeps.append(seconds)
    )

    assert flag_injection_utils._ensure_root() is False
    assert calls.count(["adb", "root"]) == 2
    assert sleeps == [flag_injection_utils._ADB_RESTART_RETRY_DELAY_SECONDS]


def test_unroot_accepts_closed_adbd_restart_when_shell_is_not_root(monkeypatch):
    flag_injection_utils = _load_flag_injection_utils(monkeypatch)
    calls = []

    def fake_run(cmd, log_errors=True):
        calls.append((cmd, log_errors))
        if cmd == ["adb", "unroot"]:
            return _completed(
                cmd, 1, stderr="adb: unable to connect for unroot: closed\n"
            )
        if cmd == ["adb", "shell", "id"]:
            return _completed(cmd, 0, stdout="uid=2000(shell) gid=2000(shell)\n")
        return _completed(cmd)

    monkeypatch.setattr(flag_injection_utils, "_run", fake_run)
    monkeypatch.setattr(flag_injection_utils, "_wait_for_shell", lambda: None)

    assert flag_injection_utils._unroot() is True
    assert (["adb", "unroot"], False) in calls


def test_unroot_retries_until_shell_reports_not_root(monkeypatch):
    flag_injection_utils = _load_flag_injection_utils(monkeypatch)
    monkeypatch.setattr(flag_injection_utils, "_ADB_RESTART_ATTEMPTS", 3)
    sleeps = []
    id_outputs = iter(
        ["uid=0(root) gid=0(root)\n", "uid=2000(shell) gid=2000(shell)\n"]
    )
    calls = []

    def fake_run(cmd, log_errors=True):
        calls.append(cmd)
        if cmd == ["adb", "unroot"]:
            return _completed(
                cmd, 1, stderr="adb: unable to connect for unroot: closed\n"
            )
        if cmd == ["adb", "shell", "id"]:
            return _completed(cmd, 0, stdout=next(id_outputs))
        return _completed(cmd)

    monkeypatch.setattr(flag_injection_utils, "_run", fake_run)
    monkeypatch.setattr(flag_injection_utils, "_wait_for_shell", lambda: None)
    monkeypatch.setattr(
        flag_injection_utils.time, "sleep", lambda seconds: sleeps.append(seconds)
    )

    assert flag_injection_utils._unroot() is True
    assert calls.count(["adb", "unroot"]) == 2
    assert sleeps == [flag_injection_utils._ADB_RESTART_RETRY_DELAY_SECONDS]


def test_unroot_fails_after_retries_when_shell_stays_root(monkeypatch):
    flag_injection_utils = _load_flag_injection_utils(monkeypatch)
    monkeypatch.setattr(flag_injection_utils, "_ADB_RESTART_ATTEMPTS", 2)
    sleeps = []
    calls = []

    def fake_run(cmd, log_errors=True):
        calls.append(cmd)
        if cmd == ["adb", "unroot"]:
            return _completed(
                cmd, 1, stderr="adb: unable to connect for unroot: closed\n"
            )
        if cmd == ["adb", "shell", "id"]:
            return _completed(cmd, 0, stdout="uid=0(root) gid=0(root)\n")
        return _completed(cmd)

    monkeypatch.setattr(flag_injection_utils, "_run", fake_run)
    monkeypatch.setattr(flag_injection_utils, "_wait_for_shell", lambda: None)
    monkeypatch.setattr(
        flag_injection_utils.time, "sleep", lambda seconds: sleeps.append(seconds)
    )

    assert flag_injection_utils._unroot() is False
    assert calls.count(["adb", "unroot"]) == 2
    assert sleeps == [flag_injection_utils._ADB_RESTART_RETRY_DELAY_SECONDS]
