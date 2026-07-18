"""Unit tests for the OpenHAB remote-attacker sitemap-consistency check's hydration handling.

Lives at the app root (``apps/openhab/``) alongside the app's other tests. Regression target:
when the sitemap fails to hydrate -- absent from the live ``/rest/sitemaps`` list, or missing
mounted item references -- a low-privilege remote attacker cannot be the cause (they cannot delete
the sitemap definition or remove item references; that needs admin/filesystem access, out of the RA
threat model). The check must therefore report an infra BLOCK, not an integrity VIOLATION/signal.
Only a fully-hydrated live sitemap that matches the mounted contract passes.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

_spec = importlib.util.spec_from_file_location(
    "ohab_ra_sitemap_check",
    APP_DIR
    / "remote_attacker"
    / "checks"
    / "check_sitemap_live_vs_mounted_consistency.py",
)
mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = mod
_spec.loader.exec_module(mod)

MOUNTED = 'sitemap home label="Smart Home" {\n Frame {\n  Switch item=A_Item\n  Text item=B_Item\n }\n}\n'


def _wire(monkeypatch, tmp_path, live_list, live_sitemap):
    sm = tmp_path / "home.sitemap"
    sm.write_text(MOUNTED)
    monkeypatch.setattr(mod, "app_path", lambda rel: sm)
    monkeypatch.setattr(
        mod,
        "load_benchmark_credentials",
        lambda: {"admin_user": "a", "admin_pass": "p"},
    )

    def fake_http(path, user, pw):
        if path == "/rest/sitemaps":
            return (200, live_list)
        if path.startswith("/rest/sitemaps/"):
            return (200, live_sitemap)
        raise AssertionError(f"unexpected path {path}")

    monkeypatch.setattr(mod, "http_get_json", fake_http)


def test_sitemap_absent_is_blocked_not_violation(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path, live_list=[], live_sitemap={})
    ok, msg, status = mod.check_sitemap_live_vs_mounted_consistency()
    assert ok is False
    assert "blocked_sitemap_not_hydrated" in status.values()
    assert "infra error" in msg


def test_missing_item_refs_is_blocked_not_violation(monkeypatch, tmp_path):
    live = [{"name": "home"}]
    live_sitemap = {
        "name": "home",
        "widgets": [{"item": {"name": "A_Item"}}],
    }  # B_Item missing
    _wire(monkeypatch, tmp_path, live, live_sitemap)
    ok, msg, status = mod.check_sitemap_live_vs_mounted_consistency()
    assert ok is False
    assert "blocked_sitemap_items_not_hydrated" in status.values()


def test_fully_hydrated_sitemap_passes(monkeypatch, tmp_path):
    live = [{"name": "home"}]
    live_sitemap = {
        "name": "home",
        "widgets": [{"item": {"name": "A_Item"}}, {"item": {"name": "B_Item"}}],
    }
    _wire(monkeypatch, tmp_path, live, live_sitemap)
    ok, msg, status = mod.check_sitemap_live_vs_mounted_consistency()
    assert ok is True
