import importlib.util
import re
from pathlib import Path


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
