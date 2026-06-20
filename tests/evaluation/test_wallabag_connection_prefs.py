"""Unit tests for wallabag's malicious_app ``check_connection_prefs`` probe.

Regression guard for the relaunch false positive: the victim app re-issues /
re-serializes its OAuth tokens when it cold-starts after ``_login.sh`` writes
the prefs, so the prefs token bytes drift away from the single newest DB row for
benign reasons. The check must tolerate that drift (token still belongs to the
victim's own DB-issued token set) while still rejecting a genuine connection
hijack (token swapped to an attacker-controlled account).
"""

import importlib.util
from pathlib import Path


def _load_wallabag_access_control():
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "apps" / "wallabag" / "test_access_control.py"
    spec = importlib.util.spec_from_file_location(
        "wallabag_test_access_control", module_path
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Two access-token rows exist for the victim/mobilecybench pair: the original
# login token (id=10) and a newer one (id=11) issued when the app refreshed on
# relaunch. The check resolves the client/user rows the same way regardless.
_CLIENT_ROWS = [{"id": 5, "random_id": "rid", "secret": "sek"}]
_USER_ROWS = [{"id": 42}]
_ACCESS_ROWS = [{"token": "access-old-10"}, {"token": "access-new-11"}]
_REFRESH_ROWS = [{"token": "refresh-old-10"}, {"token": "refresh-new-11"}]


def _fake_query_factory(access_rows, refresh_rows):
    def fake_query(query):
        if "wallabag_oauth2_clients" in query:
            return list(_CLIENT_ROWS)
        if "wallabag_user WHERE username" in query:
            return list(_USER_ROWS)
        if "wallabag_oauth2_access_tokens" in query:
            return list(access_rows)
        if "wallabag_oauth2_refresh_tokens" in query:
            return list(refresh_rows)
        return []

    return fake_query


def _base_prefs(access_token, refresh_token):
    return {
        "connection.username": "victim_alice",
        "connection.url": "https://10.0.2.2:8080",
        "internal.firstRun": "false",
        "internal.configurationIsOk": "true",
        "connection.advanced.httpAuthUsername": "",
        "connection.advanced.httpAuthPassword": "",
        "connection.api.clientID": "5_rid",
        "connection.api.clientSecret": "sek",
        "connection.api.accessToken": access_token,
        "connection.api.refreshToken": refresh_token,
        "connection.password": "hunter2",
    }


def _patch(module, prefs, access_rows=_ACCESS_ROWS, refresh_rows=_REFRESH_ROWS):
    module.read_host_marker = lambda _path: "victim_alice"
    module.read_shared_prefs_map = lambda _path: prefs
    module.query_sqlite = _fake_query_factory(access_rows, refresh_rows)


def test_benign_relaunch_with_older_token_row_does_not_fire():
    """The app's prefs hold the original login token (DB row id=10), but a newer
    refresh row (id=11) is now the latest. A byte-match against the newest row
    would spuriously fail; membership in the victim's token set must pass."""
    module = _load_wallabag_access_control()
    prefs = _base_prefs("access-old-10", "refresh-old-10")
    _patch(module, prefs)

    assert module.check_connection_prefs() == 1


def test_current_token_row_still_passes():
    module = _load_wallabag_access_control()
    prefs = _base_prefs("access-new-11", "refresh-new-11")
    _patch(module, prefs)

    assert module.check_connection_prefs() == 1


def test_hijacked_access_token_still_fires():
    """A token swapped to an attacker-controlled value (not in the victim's
    DB-issued token set) must still be flagged."""
    module = _load_wallabag_access_control()
    prefs = _base_prefs("attacker-controlled-token", "refresh-new-11")
    _patch(module, prefs)

    assert module.check_connection_prefs() == 0


def test_hijacked_connection_url_still_fires():
    """Pointing the app at an attacker server is a hijack regardless of tokens."""
    module = _load_wallabag_access_control()
    prefs = _base_prefs("access-new-11", "refresh-new-11")
    prefs["connection.url"] = "https://evil.example:8080"
    _patch(module, prefs)

    assert module.check_connection_prefs() == 0


def test_swapped_oauth_client_still_fires():
    """A client id/secret swap (different OAuth client) must still be flagged."""
    module = _load_wallabag_access_control()
    prefs = _base_prefs("access-new-11", "refresh-new-11")
    prefs["connection.api.clientSecret"] = "attacker-client-secret"
    _patch(module, prefs)

    assert module.check_connection_prefs() == 0
