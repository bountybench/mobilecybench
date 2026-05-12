import importlib
import logging
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


def test_ensure_root_retries_when_adb_root_times_out(monkeypatch, caplog):
    flag_injection_utils = _load_flag_injection_utils(monkeypatch)
    monkeypatch.setattr(flag_injection_utils, "_ADB_RESTART_ATTEMPTS", 2)
    # _run rewrites cmd[0] from "adb" to an absolute path via _tool_bin to
    # block PATH-hijack reward hacks; stub the resolver here so the test
    # doesn't depend on a real adb binary being installed.
    monkeypatch.setattr(flag_injection_utils, "_tool_bin", lambda name: f"/usr/bin/{name}")
    sleeps = []
    calls = []
    expected_timeout = flag_injection_utils._ADB_CMD_TIMEOUT_SECONDS

    def fake_subprocess_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if cmd[-2:] == ["adb", "root"] or cmd == ["/usr/bin/adb", "root"]:
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs["timeout"])
        if cmd[-3:] == ["adb", "shell", "id"] or cmd == ["/usr/bin/adb", "shell", "id"]:
            return _completed(cmd, 0, stdout="uid=2000(shell) gid=2000(shell)\n")
        return _completed(cmd)

    monkeypatch.setattr(flag_injection_utils.subprocess, "run", fake_subprocess_run)
    monkeypatch.setattr(flag_injection_utils, "_wait_for_shell", lambda: None)
    monkeypatch.setattr(
        flag_injection_utils.time, "sleep", lambda seconds: sleeps.append(seconds)
    )

    with caplog.at_level(logging.ERROR, logger=flag_injection_utils.logger.name):
        assert flag_injection_utils._ensure_root() is False

    root_timeouts = [
        kwargs["timeout"] for cmd, kwargs in calls if cmd == ["/usr/bin/adb", "root"]
    ]
    assert root_timeouts == [expected_timeout, expected_timeout]
    assert sleeps == [flag_injection_utils._ADB_RESTART_RETRY_DELAY_SECONDS]
    assert "Failed to obtain adb root after 2 attempts" in caplog.text
    assert f"command timed out after {expected_timeout}s" in caplog.text
    assert "TimeoutExpired" not in caplog.text


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
