import importlib.util
import json
from pathlib import Path

MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "apps"
    / "home-assistant-android"
    / "access_control_helpers"
    / "get_llat_from_token.py"
)
SPEC = importlib.util.spec_from_file_location("ha_get_llat_from_token", MODULE_PATH)
get_llat_from_token = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(get_llat_from_token)


class _FakeWebSocket:
    def __init__(self):
        self.sent = []
        self._responses = iter(
            [
                json.dumps({"type": "auth_required"}),
                json.dumps({"type": "auth_ok"}),
                json.dumps({"success": True, "result": "llat-token"}),
            ]
        )

    def recv(self):
        return next(self._responses)

    def send(self, payload):
        self.sent.append(json.loads(payload))

    def close(self):
        pass


def test_login_with_llat_uses_unique_client_names(monkeypatch):
    sockets = []

    def fake_create_connection(*args, **kwargs):
        ws = _FakeWebSocket()
        sockets.append(ws)
        return ws

    uuids = iter(
        [
            type("FakeUuid", (), {"hex": "aaaaaaaa11111111"})(),
            type("FakeUuid", (), {"hex": "bbbbbbbb22222222"})(),
        ]
    )

    monkeypatch.setattr(
        get_llat_from_token, "create_connection", fake_create_connection
    )
    monkeypatch.setattr(get_llat_from_token.time, "time", lambda: 1234567890)
    monkeypatch.setattr(get_llat_from_token.uuid, "uuid4", lambda: next(uuids))

    assert (
        get_llat_from_token.login_with_llat("localhost", "access-token") == "llat-token"
    )
    assert (
        get_llat_from_token.login_with_llat("localhost", "access-token") == "llat-token"
    )

    first_name = sockets[0].sent[1]["client_name"]
    second_name = sockets[1].sent[1]["client_name"]

    assert first_name == "pentest-script-1234567890-aaaaaaaa"
    assert second_name == "pentest-script-1234567890-bbbbbbbb"
    assert first_name != second_name
