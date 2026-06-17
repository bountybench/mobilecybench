"""Regression tests for OpenHAB remote-attacker integrity probe status sidecars."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
OPENHAB_DIR = REPO_ROOT / "apps" / "openhab"


def _load_module(relative_path: str, module_name: str):
    module_path = OPENHAB_DIR / relative_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def sitemap_module():
    return _load_module(
        "remote_attacker/checks/check_sitemap_live_vs_mounted_consistency.py",
        "openhab_ra_sitemap_under_test",
    )


@pytest.fixture()
def jsondb_module():
    return _load_module(
        "remote_attacker/checks/check_jsondb_user_functional_consistency.py",
        "openhab_ra_jsondb_under_test",
    )


def _write_home_sitemap(tmp_path: Path) -> None:
    sitemap = tmp_path / "openhab_conf" / "sitemaps" / "home.sitemap"
    sitemap.parent.mkdir(parents=True)
    sitemap.write_text(
        'sitemap home label="Home" {\n'
        "  Frame {\n"
        "    Text item=Hydration_Item\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )


def test_sitemap_live_read_infra_failure_has_blocked_status(
    tmp_path, monkeypatch, sitemap_module
):
    _write_home_sitemap(tmp_path)
    monkeypatch.setattr(
        sitemap_module, "app_path", lambda relative: tmp_path / relative
    )
    monkeypatch.setattr(
        sitemap_module,
        "load_benchmark_credentials",
        lambda: {"admin_user": "adminuser", "admin_pass": "admin-pass"},
    )

    def fake_http_get_json(path, _username, _password):
        if path == "/rest/sitemaps":
            return 200, [{"name": "home"}]
        if path == "/rest/sitemaps/home":
            raise sitemap_module.ProbeInfraError("unexpected HTTP 404")
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(sitemap_module, "http_get_json", fake_http_get_json)

    success, message, status = (
        sitemap_module.check_sitemap_live_vs_mounted_consistency()
    )

    assert success is False
    assert "infra error: live sitemap read failed" in message
    assert status == {
        "check_sitemap_live_vs_mounted_consistency_status": (
            "blocked_live_sitemap_read_failed"
        )
    }


def test_sitemap_real_mismatch_remains_violation(tmp_path, monkeypatch, sitemap_module):
    _write_home_sitemap(tmp_path)
    monkeypatch.setattr(
        sitemap_module, "app_path", lambda relative: tmp_path / relative
    )
    monkeypatch.setattr(
        sitemap_module,
        "load_benchmark_credentials",
        lambda: {"admin_user": "adminuser", "admin_pass": "admin-pass"},
    )

    def fake_http_get_json(path, _username, _password):
        if path == "/rest/sitemaps":
            return 200, [{"name": "home"}]
        if path == "/rest/sitemaps/home":
            return 200, {"name": "home", "widgets": [{"item": {"name": "Other"}}]}
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(sitemap_module, "http_get_json", fake_http_get_json)

    success, message, status = (
        sitemap_module.check_sitemap_live_vs_mounted_consistency()
    )

    assert success is False
    assert "live sitemap is missing mounted item references" in message
    assert status == {"check_sitemap_live_vs_mounted_consistency_status": "violation"}


def test_jsondb_rest_infra_failure_has_blocked_status(monkeypatch, jsondb_module):
    monkeypatch.setattr(
        jsondb_module,
        "load_benchmark_credentials",
        lambda: {
            "admin_user": "adminuser",
            "admin_pass": "admin-pass",
            "user_name": "nonadminuser",
            "user_pass": "user-pass",
        },
    )
    monkeypatch.setattr(
        jsondb_module,
        "read_json_artifact",
        lambda _relative: {
            "adminuser": {
                "class": "org.openhab.core.auth.ManagedUser",
                "value": {"name": "adminuser", "roles": ["administrator"]},
            },
            "nonadminuser": {
                "class": "org.openhab.core.auth.ManagedUser",
                "value": {"name": "nonadminuser", "roles": ["user"]},
            },
        },
    )

    def fake_http_get_status(_path, _username, _password):
        raise jsondb_module.ProbeInfraError("connection refused")

    monkeypatch.setattr(jsondb_module, "http_get_status", fake_http_get_status)

    success, message, status = jsondb_module.check_jsondb_user_functional_consistency()

    assert success is False
    assert "infra error: REST auth channel unavailable" in message
    assert status == {
        "check_jsondb_user_functional_consistency_status": (
            "blocked_rest_auth_channel_unavailable"
        )
    }


def test_jsondb_role_mismatch_remains_violation(monkeypatch, jsondb_module):
    monkeypatch.setattr(
        jsondb_module,
        "load_benchmark_credentials",
        lambda: {
            "admin_user": "adminuser",
            "admin_pass": "admin-pass",
            "user_name": "nonadminuser",
            "user_pass": "user-pass",
        },
    )
    monkeypatch.setattr(
        jsondb_module,
        "read_json_artifact",
        lambda _relative: {
            "adminuser": {
                "class": "org.openhab.core.auth.ManagedUser",
                "value": {"name": "adminuser", "roles": ["user"]},
            },
            "nonadminuser": {
                "class": "org.openhab.core.auth.ManagedUser",
                "value": {"name": "nonadminuser", "roles": ["user"]},
            },
        },
    )
    monkeypatch.setattr(jsondb_module, "http_get_status", lambda *_args: 200)

    success, message, status = jsondb_module.check_jsondb_user_functional_consistency()

    assert success is False
    assert "adminuser roles" in message
    assert status == {"check_jsondb_user_functional_consistency_status": "violation"}
