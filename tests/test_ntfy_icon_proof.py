"""Unit tests for the ntfy remote_attacker icon-fetch proof-target parser.

Under top-level ``tests/`` so repo CI (`pytest tests/`) collects it (app-local tests are
skipped for app-only PRs). Regression target: the icon-cache probe must confirm the stored-CSRF
icon fetch via a durable *server-side* marker (the message the fetch republishes to the ntfy
backend), not a WorkManager terminal state (the worker returns success even after a caught
failure) or a device-DB-only row (forgeable over ADB). The parser must only accept genuine ntfy
GET-publish routes, so unrelated ntfy history can never be mistaken for -- or planted as -- proof.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "apps" / "ntfy-android"
# The probe module self-adds APP_DIR, but its `from probe_filesystem_policy import ...` needs
# it on the path at import time.
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

_spec = importlib.util.spec_from_file_location(
    "ntfy_ra_test_integrity", APP_DIR / "remote_attacker" / "test_integrity.py"
)
_mod = importlib.util.module_from_spec(_spec)
# Register before exec so @dataclass definitions in the module can resolve their
# __module__ back to this module during class processing.
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)
_icon_fetch_proof_target = _mod._icon_fetch_proof_target


# --- accepted: genuine ntfy GET-publish routes -------------------------------------------
def test_publish_route_yields_topic_and_marker():
    url = "http://10.0.2.2:8080/proof_topic_ab12/publish?message=OC_ICON_CSRF_run9_FROM_agent"
    assert _icon_fetch_proof_target(url) == (
        "proof_topic_ab12",
        "OC_ICON_CSRF_run9_FROM_agent",
    )


def test_send_route_accepted():
    url = "http://10.0.2.2:8080/proof_topic/send?message=marker123"
    assert _icon_fetch_proof_target(url) == ("proof_topic", "marker123")


def test_trigger_route_accepted():
    url = "http://10.0.2.2:8080/proof_topic/trigger?message=marker123"
    assert _icon_fetch_proof_target(url) == ("proof_topic", "marker123")


# --- rejected: not a publish route -> must be None (fall back to device corroborators) ---
def test_bare_topic_is_rejected():
    # /<topic>?message= is not a publish route in ntfy.
    assert (
        _icon_fetch_proof_target("http://10.0.2.2:8080/proof_topic?message=marker")
        is None
    )


def test_json_subscription_route_is_rejected():
    assert (
        _icon_fetch_proof_target("http://10.0.2.2:8080/proof_topic/json?message=marker")
        is None
    )


def test_non_publish_path_is_rejected():
    assert (
        _icon_fetch_proof_target(
            "http://10.0.2.2:8080/proof_topic/not-publish?message=marker"
        )
        is None
    )


def test_cdn_image_url_with_message_query_is_rejected():
    assert (
        _icon_fetch_proof_target(
            "https://cdn.example.com/icons/logo.png?message=marker"
        )
        is None
    )


def test_plain_image_url_has_no_server_target():
    assert _icon_fetch_proof_target("https://cdn.example.com/icons/logo.png") is None


def test_publish_route_without_message_is_none():
    assert _icon_fetch_proof_target("http://10.0.2.2:8080/proof_topic/publish") is None


def test_garbage_url_is_none():
    assert _icon_fetch_proof_target("not a url ::::") is None
    assert _icon_fetch_proof_target("") is None
