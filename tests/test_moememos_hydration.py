import importlib.util
import re
from pathlib import Path
from types import SimpleNamespace


def _load_hydrate_module():
    path = (
        Path(__file__).resolve().parents[1]
        / "apps"
        / "moememos"
        / "scripts"
        / "hydration"
        / "hydrate.py"
    )
    spec = importlib.util.spec_from_file_location("moememos_hydrate", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_user_plan_uses_short_memos_safe_usernames():
    hydrate = _load_hydrate_module()

    rows = hydrate.user_plan("20260501010203-deadbeef")

    assert [row["username"] for row in rows] == [
        "mh-deadbeef",
        "ma-deadbeef",
        "mr-deadbeef",
        "mm-deadbeef",
    ]
    assert all(re.fullmatch(r"[a-z0-9-]{3,32}", row["username"]) for row in rows)


def test_create_user_posts_only_supported_fields(monkeypatch):
    hydrate = _load_hydrate_module()
    observed = {}

    def fake_api_json(method, path, data=None, **kwargs):
        observed.update({"method": method, "path": path, "data": data})
        return {"name": "users/test"}

    monkeypatch.setattr(hydrate, "api_json", fake_api_json)

    assert hydrate.create_user("mh-deadbeef", "password", "ignored@example.test")
    assert observed == {
        "method": "POST",
        "path": "/api/v1/users",
        "data": {"username": "mh-deadbeef", "password": "password"},
    }


def test_device_sha256_falls_back_to_root_for_target_package(monkeypatch):
    hydrate = _load_hydrate_module()
    digest = "a" * 64
    calls = []

    def fake_run_cmd(args, check=True):
        calls.append(args)
        if args[:4] == ["adb", "shell", "run-as", hydrate.PACKAGE_NAME]:
            return SimpleNamespace(
                returncode=1,
                stdout="",
                stderr="run-as: package not debuggable",
            )
        if args == [
            "adb",
            "shell",
            "sha256sum",
            f"/data/data/{hydrate.PACKAGE_NAME}/files/images/payload.jpg",
        ]:
            return SimpleNamespace(
                returncode=0,
                stdout=f"{digest}  /data/data/{hydrate.PACKAGE_NAME}/files/images/payload.jpg\n",
                stderr="",
            )
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(hydrate, "run_cmd", fake_run_cmd)

    assert (
        hydrate.device_sha256(
            "files/images/payload.jpg",
            run_as_package=hydrate.PACKAGE_NAME,
        )
        == digest
    )
    assert calls[0][:4] == ["adb", "shell", "run-as", hydrate.PACKAGE_NAME]
    assert calls[1][:3] == ["adb", "shell", "sha256sum"]


def test_copy_to_target_private_uses_root_and_restores_app_ownership(monkeypatch):
    hydrate = _load_hydrate_module()
    observed = []

    def fake_root_cmd(args, check=True):
        observed.append(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(hydrate, "root_cmd", fake_root_cmd)

    hydrate.copy_to_target_private(
        "/sdcard/fixture.jpg",
        "cache/images/fixture.jpg",
        "12345",
    )

    assert observed == [
        [
            "cp",
            "/sdcard/fixture.jpg",
            f"/data/data/{hydrate.PACKAGE_NAME}/cache/images/fixture.jpg",
        ],
        [
            "chown",
            "12345:12345",
            f"/data/data/{hydrate.PACKAGE_NAME}/cache/images/fixture.jpg",
        ],
        ["chmod", "600", f"/data/data/{hydrate.PACKAGE_NAME}/cache/images/fixture.jpg"],
    ]
