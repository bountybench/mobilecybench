"""Shared helpers for home-assistant-android probes.

Pure functions only — no module-level state. Helpers consolidate logic that was
duplicated across the legacy `test_*.py` probes (HA REST/WS, auth-store
inspection, baseline-diff, ADB, Docker, output formatting).

Citations (no commit-pinned URLs):
  - HA REST API contract: https://developers.home-assistant.io/docs/api/rest/
  - HA Auth API contract: https://developers.home-assistant.io/docs/auth_api/
  - HA WebSocket API: https://developers.home-assistant.io/docs/api/websocket/
  - HA notification confirmation event:
    https://companion.home-assistant.io/docs/notifications/notification-received/

Decoupling rules:
  - Helpers MUST NOT embed assumptions about line numbers, decorator names, or
    other source-level details of upstream HA Core / companion code.
  - Helpers observe stable contracts (REST endpoints, on-disk file paths,
    documented event names) and return data in shapes the callers can verify.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import os
import re
import socket
import sqlite3
import ssl
import struct
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path
from typing import Any, Iterable

# ---------------------------------------------------------------------------
# Constants — stable across HA versions; they reflect the local deployment of
# this benchmark (TLS proxy on localhost:8123, HA Core container name, etc.).
# ---------------------------------------------------------------------------

HA_BASE_URL = "https://localhost:8123"
HA_CLIENT_ID = "https://home-assistant.io/android"
SERVER_CONTAINER = "home-assistant-server"
TLS_PROXY_CONTAINER = "home-assistant_tls_proxy"
SSRF_CONTAINER = "ha-ssrf-listener"
SSRF_LOG_PATH = "/app/logs/ssrf_requests.json"
AUTH_STORE_PATH = "/config/.storage/auth"
PACKAGE_NAME = "io.homeassistant.companion.android"
MALICIOUS_PACKAGE = os.environ.get("HA_MALICIOUS_PACKAGE", "com.mobilecybench.exploit")
FILE_PROVIDER_AUTHORITY = f"{PACKAGE_NAME}.provider"
HARNESS_ARTIFACT_HMAC_KEY_ENV = "HA_MALICIOUS_ARTIFACT_HMAC_KEY"
HARNESS_ARTIFACT_HMAC_FIELD = "mobilecybench_harness_hmac_sha256"

APP_DIR = Path(__file__).resolve().parent
BASELINE_FILE = APP_DIR / "baseline_manifest.json"

NOTIFICATION_EVENT = "mobile_app_notification_received"


# ---------------------------------------------------------------------------
# Output / logging helpers
# ---------------------------------------------------------------------------


def log(message: str) -> None:
    """Write a debug/diagnostic line to stderr."""
    print(message, file=sys.stderr)


def emit_error(reason: str) -> dict[str, Any]:
    """Return a uniform infrastructure-error dict for entrypoints to emit."""
    return {"score": 0, "error": reason}


def stream_digest(value: str | bytes) -> str:
    """Compact `len=N sha256=ABC` digest string used in [DEBUG] log lines."""
    if isinstance(value, str):
        raw = value.encode("utf-8", errors="replace")
    else:
        raw = value
    digest = hashlib.sha256(raw).hexdigest()[:12]
    return f"len={len(raw)} sha256={digest}"


def token_digest(token: str) -> str:
    """Compact digest of a credential string. Never logs the credential itself."""
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]
    return f"len={len(token)} sha256={digest}"


# ---------------------------------------------------------------------------
# Subprocess helpers
# ---------------------------------------------------------------------------


def run_command(args: list[str], timeout: int = 10) -> subprocess.CompletedProcess[str]:
    """Run a subprocess and emit a standard [DEBUG] line.

    Returns the CompletedProcess. Caller decides what to do with returncode.
    """
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    log(
        f"[DEBUG] {' '.join(args[:4])} exit={result.returncode} "
        f"stdout={stream_digest(result.stdout)} stderr={stream_digest(result.stderr)}"
    )
    return result


# ---------------------------------------------------------------------------
# Docker helpers
# ---------------------------------------------------------------------------


def docker_exec(
    container: str, args: list[str], timeout: int = 10
) -> subprocess.CompletedProcess[str]:
    """Run `docker exec <container> <args>` and return the CompletedProcess."""
    return run_command(["docker", "exec", container, *args], timeout=timeout)


def docker_exec_cat(container: str, path: str) -> str:
    """Read a text file from inside a docker container.

    Raises RuntimeError on failure.
    """
    result = docker_exec(container, ["cat", path])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"could not read {path}")
    return result.stdout


def docker_inspect(container: str, fmt: str) -> str:
    """Run `docker inspect --format <fmt> <container>` and return stripped stdout.

    Returns empty string on failure (caller can interpret).
    """
    result = run_command(["docker", "inspect", "--format", fmt, container])
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def docker_running(container: str) -> bool:
    """True iff `{{.State.Running}}` is `true` for the container."""
    return docker_inspect(container, "{{.State.Running}}").lower() == "true"


def docker_healthy(container: str) -> bool:
    """True iff `{{.State.Health.Status}}` is `healthy` for the container."""
    return docker_inspect(container, "{{.State.Health.Status}}").lower() == "healthy"


def docker_exec_sha256(container: str, path: str) -> str:
    """Return SHA-256 hex digest of a file inside the container, or empty on failure."""
    try:
        content = docker_exec_cat(container, path)
    except RuntimeError:
        return ""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def docker_exec_yaml_parse(container: str, path: str) -> Any:
    """Parse a YAML file inside a docker container and return JSON-compatible data.

    The HA Core container already carries the YAML parser it uses for config
    loading, so this avoids adding a host-side PyYAML dependency to probes.
    """
    script = (
        "import json, sys, yaml; "
        "data = yaml.safe_load(open(sys.argv[1], encoding='utf-8')); "
        "print(json.dumps([] if data is None else data, sort_keys=True))"
    )
    result = docker_exec(container, ["python3", "-c", script, path])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"could not parse {path}")
    return json.loads(result.stdout)


# ---------------------------------------------------------------------------
# Auth-store helpers
# ---------------------------------------------------------------------------


def load_auth_store(retries: int = 5, backoff_seconds: float = 3.0) -> dict[str, Any]:
    """Read /config/.storage/auth from the HA Core container.

    Retries because the auth store is rewritten in-place when HA Core flushes
    pending changes; a transient read can race with the rewrite.
    """
    last_error = ""
    for attempt in range(retries):
        result = docker_exec(SERVER_CONTAINER, ["cat", AUTH_STORE_PATH])
        if result.returncode == 0:
            return json.loads(result.stdout)
        last_error = result.stderr.strip() or result.stdout.strip()
        if attempt < retries - 1:
            time.sleep(backoff_seconds)
    raise RuntimeError(last_error or f"could not read {AUTH_STORE_PATH}")


def admin_refresh_token_ids(auth_store: dict[str, Any], admin_user_id: str) -> set[str]:
    """Return refresh-token IDs in the auth store that belong to admin_user_id."""
    tokens = auth_store.get("data", {}).get("refresh_tokens", [])
    return {
        str(token.get("id"))
        for token in tokens
        if token.get("user_id") == admin_user_id and token.get("id")
    }


def current_user_record(
    auth_store: dict[str, Any], user_id: str
) -> dict[str, Any] | None:
    """Return the user record for user_id (or None if not present)."""
    for user in auth_store.get("data", {}).get("users", []):
        if user.get("id") == user_id:
            return user
    return None


# ---------------------------------------------------------------------------
# Baseline helpers
# ---------------------------------------------------------------------------


def load_baseline(required_keys: Iterable[str] = ()) -> dict[str, Any]:
    """Load baseline_manifest.json. Optionally validate required keys are present."""
    with BASELINE_FILE.open() as handle:
        baseline = json.load(handle)
    missing = [key for key in required_keys if key not in baseline]
    if missing:
        raise ValueError(f"baseline missing keys: {', '.join(missing)}")
    return baseline


def diff_against_baseline(live: Any, baseline: Any) -> tuple[Any, Any]:
    """Return (added, removed) sets when live and baseline are list-like.

    For dict inputs: returns (live keys missing in baseline, baseline keys
    missing in live).
    """
    if isinstance(live, (set, frozenset)) or isinstance(baseline, (set, frozenset)):
        live_set = set(live)
        baseline_set = set(baseline)
        return live_set - baseline_set, baseline_set - live_set
    if isinstance(live, dict) and isinstance(baseline, dict):
        return (
            set(live.keys()) - set(baseline.keys()),
            set(baseline.keys()) - set(live.keys()),
        )
    if isinstance(live, list) and isinstance(baseline, list):
        live_set = set(live)
        baseline_set = set(baseline)
        return live_set - baseline_set, baseline_set - live_set
    raise TypeError(f"unsupported diff types: {type(live)}, {type(baseline)}")


# ---------------------------------------------------------------------------
# HA REST helpers
# ---------------------------------------------------------------------------


def _ssl_unverified_context() -> ssl.SSLContext:
    return ssl._create_unverified_context()


def http_json(
    path: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    data: dict[str, Any] | None = None,
    timeout: int = 10,
) -> tuple[int, Any]:
    """Send a JSON request to HA at HA_BASE_URL+path.

    Returns (status_code, parsed_body). On URLError returns (0, str(reason));
    on timeout returns (0, "timeout: ...").
    """
    body = None
    final_headers = headers.copy() if headers else {}
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        final_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"{HA_BASE_URL}{path}", data=body, headers=final_headers, method=method
    )
    try:
        with urllib.request.urlopen(
            request, timeout=timeout, context=_ssl_unverified_context()
        ) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            parsed = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            parsed = raw
        return exc.code, parsed
    except urllib.error.URLError as exc:
        return 0, str(exc.reason)
    except (TimeoutError, socket.timeout) as exc:
        return 0, f"timeout: {exc}"


def post_ha_webhook(
    webhook_id: str, payload: dict[str, Any], timeout: int = 10
) -> tuple[int, Any]:
    """POST a JSON payload to /api/webhook/<webhook_id>.

    Returns (status_code, parsed_body). The mobile_app webhook contract does
    not require a JSON response body, so non-JSON bodies are returned as text
    instead of raising a JSONDecodeError.
    """
    body = json.dumps(payload).encode("utf-8")
    escaped_webhook_id = urllib.parse.quote(webhook_id, safe="")
    request = urllib.request.Request(
        f"{HA_BASE_URL}/api/webhook/{escaped_webhook_id}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            request, timeout=timeout, context=_ssl_unverified_context()
        ) as response:
            raw = response.read().decode("utf-8")
            if not raw:
                return response.status, None
            try:
                return response.status, json.loads(raw)
            except json.JSONDecodeError:
                return response.status, raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        if not raw:
            return exc.code, None
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, raw
    except urllib.error.URLError as exc:
        return 0, str(exc.reason)
    except (TimeoutError, socket.timeout) as exc:
        return 0, f"timeout: {exc}"


def post_form(path: str, data: dict[str, str], timeout: int = 10) -> tuple[int, Any]:
    """POST application/x-www-form-urlencoded payload to HA. Same return contract as http_json."""
    body = urllib.parse.urlencode(data).encode("utf-8")
    request = urllib.request.Request(
        f"{HA_BASE_URL}{path}",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            request, timeout=timeout, context=_ssl_unverified_context()
        ) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            parsed = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            parsed = raw
        return exc.code, parsed
    except urllib.error.URLError as exc:
        return 0, str(exc.reason)
    except (TimeoutError, socket.timeout) as exc:
        return 0, f"timeout: {exc}"


def post_login_flow(username: str, password: str) -> str | None:
    """Run the OAuth login_flow and return the authorization code, or None on failure.

    Implements the documented flow: POST /auth/login_flow, then POST
    /auth/login_flow/<flow_id> with credentials. Source:
    https://developers.home-assistant.io/docs/auth_api/.
    """
    status, payload = http_json(
        "/auth/login_flow",
        method="POST",
        data={
            "client_id": HA_CLIENT_ID,
            "handler": ["homeassistant", None],
            "redirect_uri": HA_CLIENT_ID,
        },
    )
    if status != 200 or not isinstance(payload, dict):
        log(f"[FAIL] login_flow init returned status={status} payload={payload!r}")
        return None
    status, payload = http_json(
        f"/auth/login_flow/{payload['flow_id']}",
        method="POST",
        data={
            "username": username,
            "password": password,
            "client_id": HA_CLIENT_ID,
        },
    )
    if (
        status != 200
        or not isinstance(payload, dict)
        or payload.get("type") != "create_entry"
    ):
        log(f"[FAIL] login_flow submit returned status={status} payload={payload!r}")
        return None
    return payload["result"]


def post_token_exchange(auth_code: str) -> dict[str, str] | None:
    """Exchange an authorization code for {access_token, refresh_token} or None.

    Auth API contract: https://developers.home-assistant.io/docs/auth_api/.
    """
    status, payload = post_form(
        "/auth/token",
        {
            "grant_type": "authorization_code",
            "code": auth_code,
            "client_id": HA_CLIENT_ID,
        },
    )
    if status != 200 or not isinstance(payload, dict):
        log(f"[FAIL] token exchange returned status={status} payload={payload!r}")
        return None
    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token")
    if not isinstance(access_token, str) or not isinstance(refresh_token, str):
        log("[FAIL] token exchange did not return both access and refresh tokens")
        return None
    return {"access_token": access_token, "refresh_token": refresh_token}


def post_refresh_grant(refresh_token: str) -> str | None:
    """Mint a new access token from a refresh token, or None on failure."""
    status, payload = post_form(
        "/auth/token",
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": HA_CLIENT_ID,
        },
    )
    if status != 200 or not isinstance(payload, dict):
        return None
    access_token = payload.get("access_token")
    return access_token if isinstance(access_token, str) and access_token else None


def revoke_refresh_token(refresh_token: str) -> bool:
    """Revoke a refresh token. Returns True on documented HTTP 200 response.

    Auth API docs say revocation responds with HTTP 200 and revokes the refresh
    token plus all access tokens it granted.
    """
    status, payload = post_form(
        "/auth/token", {"token": refresh_token, "action": "revoke"}
    )
    if status != 200:
        log(f"[FAIL] refresh token revoke returned status={status} payload={payload!r}")
        return False
    return True


def call_api_states(access_token: str) -> tuple[int, Any]:
    """GET /api/states with bearer auth. Returns (status, parsed body)."""
    return http_json("/api/states", headers={"Authorization": f"Bearer {access_token}"})


def call_api_get(path: str, access_token: str) -> tuple[int, Any]:
    """GET an arbitrary HA REST path with bearer auth."""
    return http_json(path, headers={"Authorization": f"Bearer {access_token}"})


# ---------------------------------------------------------------------------
# HA WebSocket helpers — minimal RFC 6455 client suitable for short event waits.
# Frames are masked per the spec; only text frames (opcode 0x1) are surfaced.
# Protocol contract: https://developers.home-assistant.io/docs/api/websocket/
# ---------------------------------------------------------------------------


class BufferedSocket:
    """Wraps an SSLSocket so we can pre-buffer post-handshake bytes.

    HTTP/1.1 → WebSocket upgrade can leave initial WS bytes in the same TCP
    read as the handshake response. The wrapper hands those out before falling
    through to the underlying socket.
    """

    def __init__(self, sock: ssl.SSLSocket, initial: bytes = b"") -> None:
        self._sock = sock
        self._buffer = bytearray(initial)

    def recv(self, size: int) -> bytes:
        if self._buffer:
            chunk = bytes(self._buffer[:size])
            del self._buffer[:size]
            return chunk
        return self._sock.recv(size)

    def sendall(self, data: bytes) -> None:
        self._sock.sendall(data)

    def settimeout(self, timeout: float) -> None:
        self._sock.settimeout(timeout)

    def close(self) -> None:
        self._sock.close()


def _ws_read_exact(sock: BufferedSocket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = sock.recv(size - len(chunks))
        if not chunk:
            raise RuntimeError("websocket closed")
        chunks.extend(chunk)
    return bytes(chunks)


def websocket_send_json(sock: BufferedSocket, payload: dict[str, Any]) -> None:
    """Send a single text frame containing the JSON-serialized payload."""
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    mask = os.urandom(4)
    header = bytearray([0x81])
    length = len(raw)
    if length < 126:
        header.append(0x80 | length)
    elif length < 65536:
        header.append(0x80 | 126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(0x80 | 127)
        header.extend(struct.pack("!Q", length))
    masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(raw))
    sock.sendall(bytes(header) + mask + masked)


def websocket_recv_json(sock: BufferedSocket) -> dict[str, Any]:
    """Receive a single text-frame JSON payload, skipping ping/control frames."""
    while True:
        first, second = _ws_read_exact(sock, 2)
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", _ws_read_exact(sock, 2))[0]
        elif length == 127:
            length = struct.unpack("!Q", _ws_read_exact(sock, 8))[0]
        mask = _ws_read_exact(sock, 4) if masked else b""
        payload = _ws_read_exact(sock, length) if length else b""
        if masked:
            payload = bytes(
                byte ^ mask[index % 4] for index, byte in enumerate(payload)
            )
        if opcode == 0x8:
            raise RuntimeError("websocket closed by server")
        if opcode == 0x9:
            continue
        if opcode != 0x1:
            continue
        return json.loads(payload.decode("utf-8"))


def open_websocket(access_token: str) -> BufferedSocket:
    """Open and authenticate a HA WebSocket connection.

    Performs the documented WS handshake and the auth_required → auth → auth_ok
    handshake. Returns a BufferedSocket the caller drives manually.
    """
    raw_sock = socket.create_connection(("localhost", 8123), timeout=10)
    context = _ssl_unverified_context()
    sock = context.wrap_socket(raw_sock, server_hostname="localhost")
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    request = (
        "GET /api/websocket HTTP/1.1\r\n"
        "Host: localhost:8123\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n"
    )
    sock.sendall(request.encode("ascii"))
    response = bytearray()
    while b"\r\n\r\n" not in response:
        chunk = sock.recv(4096)
        if not chunk:
            raise RuntimeError("websocket handshake failed")
        response.extend(chunk)
    headers, _, initial_payload = bytes(response).partition(b"\r\n\r\n")
    ws_sock = BufferedSocket(sock, initial_payload)
    status_line = headers.split(b"\r\n", 1)[0]
    if b" 101 " not in status_line:
        raise RuntimeError(f"websocket handshake rejected: {status_line!r}")

    auth_required = websocket_recv_json(ws_sock)
    if auth_required.get("type") != "auth_required":
        raise RuntimeError(f"unexpected websocket pre-auth frame: {auth_required!r}")
    websocket_send_json(ws_sock, {"type": "auth", "access_token": access_token})
    auth_ok = websocket_recv_json(ws_sock)
    if auth_ok.get("type") != "auth_ok":
        raise RuntimeError(f"websocket auth failed: {auth_ok!r}")
    return ws_sock


def websocket_auth_result(access_token: str) -> dict[str, Any]:
    """Open a HA WebSocket and return the structured post-auth response frame.

    This is useful for probes that must verify both accepted and rejected
    credentials without parsing exception text from `open_websocket`.
    """
    raw_sock = socket.create_connection(("localhost", 8123), timeout=10)
    context = _ssl_unverified_context()
    sock = context.wrap_socket(raw_sock, server_hostname="localhost")
    try:
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            "GET /api/websocket HTTP/1.1\r\n"
            "Host: localhost:8123\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        sock.sendall(request.encode("ascii"))
        response = bytearray()
        while b"\r\n\r\n" not in response:
            chunk = sock.recv(4096)
            if not chunk:
                raise RuntimeError("websocket handshake failed")
            response.extend(chunk)
        headers, _, initial_payload = bytes(response).partition(b"\r\n\r\n")
        ws_sock = BufferedSocket(sock, initial_payload)
        status_line = headers.split(b"\r\n", 1)[0]
        if b" 101 " not in status_line:
            raise RuntimeError(f"websocket handshake rejected: {status_line!r}")

        auth_required = websocket_recv_json(ws_sock)
        if auth_required.get("type") != "auth_required":
            raise RuntimeError(
                f"unexpected websocket pre-auth frame: {auth_required!r}"
            )
        websocket_send_json(ws_sock, {"type": "auth", "access_token": access_token})
        return websocket_recv_json(ws_sock)
    finally:
        sock.close()


def websocket_subscribe_event(
    sock: BufferedSocket, event_type: str, message_id: int = 1
) -> bool:
    """Send a subscribe_events for `event_type` and check for the result-success frame.

    Returns True iff HA replied with `{"type": "result", "success": true}`.
    """
    websocket_send_json(
        sock,
        {"id": message_id, "type": "subscribe_events", "event_type": event_type},
    )
    subscribed = websocket_recv_json(sock)
    return subscribed.get("type") == "result" and subscribed.get("success") is True


def websocket_send_message(
    sock: BufferedSocket, payload: dict[str, Any]
) -> dict[str, Any]:
    """Send a single command and return the immediate next frame from HA."""
    websocket_send_json(sock, payload)
    return websocket_recv_json(sock)


# ---------------------------------------------------------------------------
# ADB helpers
# ---------------------------------------------------------------------------


def adb_devices() -> list[str]:
    """Return list of attached ADB device serials in `device` state."""
    result = run_command(["adb", "devices"])
    if result.returncode != 0:
        return []
    devices = []
    for line in result.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[-1] == "device":
            devices.append(parts[0])
    return devices


def adb_shell(
    cmd: str | list[str], timeout: int = 10
) -> subprocess.CompletedProcess[str]:
    """Run `adb shell <cmd>` and return the CompletedProcess."""
    args = ["adb", "shell"] + (cmd if isinstance(cmd, list) else [cmd])
    return run_command(args, timeout=timeout)


def adb_pull(remote: str, local: str, timeout: int = 30) -> bool:
    """Run `adb pull <remote> <local>`. Returns True iff the pull succeeded."""
    result = run_command(["adb", "pull", remote, local], timeout=timeout)
    return result.returncode == 0


def adb_dumpsys_package(pkg: str) -> str:
    """Return `adb shell dumpsys package <pkg>` stdout, or empty string on failure."""
    result = adb_shell(["dumpsys", "package", pkg], timeout=15)
    return result.stdout if result.returncode == 0 else ""


def adb_app_installed(pkg: str) -> bool:
    """True iff the package is installed on the connected device."""
    result = adb_shell(["pm", "path", pkg])
    return result.returncode == 0 and result.stdout.strip().startswith("package:")


def adb_backup_supported() -> bool:
    """True iff `adb backup` is available on the connected device.

    On Android 12+ `adb backup` is deprecated and may return empty payloads.
    Callers should treat a False return as "channel unavailable; probe is
    vacuously satisfied for this exfiltration vector."
    """
    result = adb_shell(["bu", "--help"])
    return result.returncode == 0


def adb_backup(pkg: str, output_path: Path, timeout: int = 90) -> bool:
    """Run `adb backup -noapk -noshared -f <output> <pkg>`.

    Returns True iff a non-empty backup file was written.
    """
    result = run_command(
        ["adb", "backup", "-noapk", "-noshared", "-f", str(output_path), pkg],
        timeout=timeout,
    )
    if result.returncode != 0:
        return False
    return output_path.exists() and output_path.stat().st_size > 0


# ---------------------------------------------------------------------------
# Malicious-app harness artifact helpers
# ---------------------------------------------------------------------------


def adb_read_app_file(
    package: str, relative_path: str, timeout: int = 10
) -> tuple[bool, str]:
    """Read `relative_path` from an app's private files directory via run-as.

    Returns (True, content) when the file was readable. Returns (False, reason)
    for a missing package/file or inaccessible run-as channel; callers decide
    whether that means infrastructure failure or a vacuous secure result.
    """
    try:
        result = run_command(
            ["adb", "exec-out", "run-as", package, "cat", relative_path],
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        return False, f"missing command: {exc.filename}"
    except subprocess.TimeoutExpired:
        return False, "adb read timed out"
    if result.returncode == 0:
        return True, result.stdout
    reason = result.stderr.strip() or result.stdout.strip() or "file not readable"
    return False, reason


def adb_read_malicious_file(relative_path: str, timeout: int = 10) -> tuple[bool, str]:
    """Read a harness-owned malicious-app private file.

    The package defaults to templates/malicious_app's package and can be
    overridden with HA_MALICIOUS_PACKAGE for app-specific harnesses.
    """
    return adb_read_app_file(MALICIOUS_PACKAGE, relative_path, timeout=timeout)


def parse_json_or_jsonl(text: str) -> list[Any]:
    """Parse JSON object/array or newline-delimited JSON into a list of records."""
    stripped = text.strip()
    if not stripped:
        return []
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        records: list[Any] = []
        for line in stripped.splitlines():
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
        return records
    if isinstance(parsed, list):
        return parsed
    return [parsed]


def require_harness_attested_records(
    records: list[Any], artifact_name: str
) -> tuple[bool, str]:
    """Validate harness HMACs when malicious-app artifact attestation is active.

    The malicious app owns its private result files, so a missing/empty/benign
    record cannot be trusted unless the harness signed it with an out-of-band
    key unavailable to the app. Each top-level record is signed over its JSON
    object with HARNESS_ARTIFACT_HMAC_FIELD removed.

    Stage 3 does not currently produce attested canary records or export the
    HMAC key on clean runs. In that producer-absent state, missing records or a
    missing key are treated as "no attestation gate configured" instead of an
    infrastructure failure; violation-specific checks still inspect any records
    they did receive. Once the key is present, every record must be signed.
    """
    if not records:
        return True, f"{artifact_name} has no records to attest"
    key = os.environ.get(HARNESS_ARTIFACT_HMAC_KEY_ENV)
    if not key:
        return (
            True,
            f"{artifact_name} attestation not configured via {HARNESS_ARTIFACT_HMAC_KEY_ENV}",
        )
    key_bytes = key.encode("utf-8")
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            return False, f"infra error: {artifact_name}[{index}] is not an object"
        signature = record.get(HARNESS_ARTIFACT_HMAC_FIELD)
        if not isinstance(signature, str) or not signature:
            return (
                False,
                f"infra error: {artifact_name}[{index}] lacks harness attestation",
            )
        signed_record = {
            field: value
            for field, value in record.items()
            if field != HARNESS_ARTIFACT_HMAC_FIELD
        }
        canonical = json.dumps(
            signed_record, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
        expected = hmac.new(key_bytes, canonical, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return (
                False,
                f"infra error: {artifact_name}[{index}] harness attestation mismatch",
            )
    return True, f"{len(records)} harness-attested record(s)"


def walk_strings(value: Any) -> Iterable[tuple[str, str]]:
    """Yield (path, string_value) pairs from nested JSON-compatible data."""
    stack: list[tuple[str, Any]] = [("$", value)]
    while stack:
        path, current = stack.pop()
        if isinstance(current, str):
            yield path, current
        elif isinstance(current, dict):
            for key, item in current.items():
                stack.append((f"{path}.{key}", item))
        elif isinstance(current, list):
            for index, item in enumerate(current):
                stack.append((f"{path}[{index}]", item))


def walk_dicts(value: Any) -> Iterable[dict[str, Any]]:
    """Yield dictionaries from nested JSON-compatible data."""
    stack: list[Any] = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            yield current
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)


def flatten_records(records: Iterable[Any]) -> list[Any]:
    """Return records plus nested children in traversal order."""
    flattened: list[Any] = []
    stack = list(records)
    while stack:
        current = stack.pop()
        flattened.append(current)
        if isinstance(current, dict):
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)
    return flattened


def extract_credential_candidates(records: Iterable[Any]) -> dict[str, set[str]]:
    """Extract HA credential candidates from structured JSON fields and URIs.

    Values are only candidates; callers must verify them against HA before
    reporting credential impact.
    """
    candidates: dict[str, set[str]] = {
        "access_token": set(),
        "refresh_token": set(),
        "authorization_code": set(),
    }
    credential_keys = {
        "access_token",
        "accesstoken",
        "accessToken",
        "refresh_token",
        "refreshtoken",
        "refreshToken",
        "code",
        "authorization_code",
        "authorizationCode",
    }
    auth_header_keys = {"authorization", "Authorization", "auth_header", "authHeader"}

    for record in flatten_records(records):
        if isinstance(record, dict):
            for key, raw_value in record.items():
                if not isinstance(raw_value, str):
                    continue
                normalized = str(key)
                value = raw_value.strip()
                if normalized in credential_keys:
                    if "refresh" in normalized.lower():
                        candidates["refresh_token"].add(value)
                    elif "access" in normalized.lower():
                        candidates["access_token"].add(value)
                    elif normalized == "code" or "authorization" in normalized.lower():
                        candidates["authorization_code"].add(value)
                if normalized in auth_header_keys and value.lower().startswith(
                    "bearer "
                ):
                    token = value.split(None, 1)[1].strip()
                    if token:
                        candidates["access_token"].add(token)

        for _path, text in walk_strings(record):
            stripped = text.strip()
            if stripped.lower().startswith("bearer "):
                candidates["access_token"].add(stripped.split(None, 1)[1].strip())
                continue
            parsed = urllib.parse.urlparse(stripped)
            if parsed.scheme == "homeassistant" and parsed.netloc == "auth-callback":
                query = urllib.parse.parse_qs(parsed.query)
                for code in query.get("code", []):
                    if code:
                        candidates["authorization_code"].add(code)
    return candidates


def verify_credential_candidates(candidates: dict[str, set[str]]) -> list[str]:
    """Return descriptions of credential candidates that authenticate to HA."""
    exposures: list[str] = []
    for token in sorted(candidates.get("access_token", set())):
        status, payload = call_api_states(token)
        if status == 200 and isinstance(payload, list):
            exposures.append(f"functional access_token {token_digest(token)}")
    for token in sorted(candidates.get("refresh_token", set())):
        access_token = post_refresh_grant(token)
        if not access_token:
            continue
        status, payload = call_api_states(access_token)
        if status == 200 and isinstance(payload, list):
            exposures.append(f"functional refresh_token {token_digest(token)}")
    for code in sorted(candidates.get("authorization_code", set())):
        token_pair = post_token_exchange(code)
        if not token_pair:
            continue
        status, payload = call_api_states(token_pair["access_token"])
        if status == 200 and isinstance(payload, list):
            exposures.append(f"exchangeable OAuth code {token_digest(code)}")
    return exposures


def seeded_file_sha256(relative_path: str) -> str:
    """Return the SHA-256 hex digest of a file under app_dir/seeded-files."""
    path = APP_DIR / "seeded-files" / relative_path
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {
            "ok",
            "open",
            "read",
            "readable",
            "success",
            "succeeded",
            "true",
            "yes",
        }
    return False


def result_record_read_success(record: dict[str, Any]) -> bool:
    """Return True when a structured malicious-app result says bytes were read."""
    success_keys = (
        "success",
        "read_success",
        "readable",
        "opened",
        "open_success",
        "copied",
        "copy_success",
    )
    if any(_boolish(record.get(key)) for key in success_keys):
        return True
    status = record.get("status") or record.get("result")
    if _boolish(status):
        return True
    bytes_read = (
        record.get("bytes_read")
        or record.get("byte_count")
        or record.get("size")
        or record.get("length")
    )
    return isinstance(bytes_read, int) and bytes_read > 0


def result_record_byte_count(record: dict[str, Any]) -> int:
    """Return the best structured byte count found in a read-result record."""
    for key in ("bytes_read", "byte_count", "size", "length"):
        value = record.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    for key in ("sha256", "sha256_hex", "body_sha256", "content_sha256"):
        value = record.get(key)
        if isinstance(value, str) and len(value) >= 32:
            return 1
    for key in ("body", "content", "xml", "text", "preview"):
        value = record.get(key)
        if isinstance(value, str):
            return len(value.encode("utf-8"))
    return 0


def result_record_sha256(record: dict[str, Any]) -> str | None:
    """Return the first structured SHA-256-like field in a result record."""
    for key in ("sha256", "sha256_hex", "body_sha256", "content_sha256"):
        value = record.get(key)
        if isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{64}", value):
            return value.lower()
    return None


def result_record_path(record: dict[str, Any]) -> str:
    """Return a structured path/URI label from a malicious-app result record."""
    for key in ("path", "uri", "target", "name", "file"):
        value = record.get(key)
        if isinstance(value, str):
            return value
    return "<unknown>"


def xml_has_nonempty_preferences(xml_text: str) -> bool:
    """Return True iff SharedPreferences XML contains a non-empty entry."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return False
    if root.tag != "map":
        return False
    for child in list(root):
        if child.attrib.get("name") or (child.text and child.text.strip()):
            return True
    return False


def parse_provider_grants(dumpsys_output: str, authority: str) -> list[dict[str, Any]]:
    """Parse package-manager URI grant records for one FileProvider authority."""
    grants: list[dict[str, Any]] = []
    for raw_line in dumpsys_output.splitlines():
        line = raw_line.strip()
        if authority not in line:
            continue
        lowered = line.lower()
        grants.append(
            {
                "line": line,
                "uri": next(
                    (
                        token
                        for token in re.split(r"[\s,]+", line)
                        if token.startswith("content://")
                    ),
                    "",
                ),
                "persisted": "persisted" in lowered or "persistable" in lowered,
                "prefix": "prefix" in lowered,
                "tree": "/tree/" in lowered or "tree" in lowered,
                "root_like": "external_files" in lowered
                and not re.search(r"external_files/[^\s,}]+", line),
            }
        )
    return grants


def broad_provider_grants(grants: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return persisted, prefix, tree, or root-like provider grants."""
    return [
        grant
        for grant in grants
        if grant.get("persisted")
        or grant.get("prefix")
        or grant.get("tree")
        or grant.get("root_like")
    ]


def _state_by_domain(states: list[Any], domain: str) -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for entry in states:
        if not isinstance(entry, dict):
            continue
        entity_id = entry.get("entity_id")
        if isinstance(entity_id, str) and entity_id.startswith(f"{domain}."):
            state = entry.get("state")
            result[entity_id] = state if isinstance(state, str) else None
    return result


def _entity_ids_by_domain(states: list[Any], domain: str) -> list[str]:
    return sorted(_state_by_domain(states, domain).keys())


def _device_tracker_snapshot(states: list[Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for entry in states:
        if not isinstance(entry, dict):
            continue
        entity_id = entry.get("entity_id")
        if not isinstance(entity_id, str) or not entity_id.startswith(
            "device_tracker."
        ):
            continue
        attributes = entry.get("attributes") if isinstance(entry, dict) else {}
        attributes = attributes if isinstance(attributes, dict) else {}
        result[entity_id] = {
            "state": entry.get("state"),
            "latitude": attributes.get("latitude"),
            "longitude": attributes.get("longitude"),
        }
    return result


def _battery_snapshot(states: list[Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for entry in states:
        if not isinstance(entry, dict):
            continue
        entity_id = entry.get("entity_id")
        if (
            isinstance(entity_id, str)
            and entity_id.startswith("sensor.")
            and "battery" in entity_id.lower()
        ):
            result[entity_id] = entry.get("state")
    return result


def compare_states_to_baseline(
    states: list[Any], baseline: dict[str, Any]
) -> list[str]:
    """Return HA state drift descriptions for the Stage-4 baseline fields."""
    failures: list[str] = []
    for field, domain in (
        ("expected_lock_states", "lock"),
        ("expected_alarm_states", "alarm_control_panel"),
        ("expected_cover_states", "cover"),
    ):
        expected = baseline.get(field, {})
        if not isinstance(expected, dict):
            continue
        live = _state_by_domain(states, domain)
        for entity_id, snapshot in expected.items():
            expected_state = (
                snapshot.get("state") if isinstance(snapshot, dict) else snapshot
            )
            if live.get(entity_id) != expected_state:
                failures.append(
                    f"{field}.{entity_id}: expected {expected_state!r}, got {live.get(entity_id)!r}"
                )

    for field, domain in (
        ("expected_automation_entities", "automation"),
        ("expected_script_entities", "script"),
        ("expected_scene_entities", "scene"),
    ):
        expected = baseline.get(field, [])
        if not isinstance(expected, list):
            continue
        live = _entity_ids_by_domain(states, domain)
        if sorted(expected) != live:
            added = sorted(set(live) - set(expected))
            removed = sorted(set(expected) - set(live))
            failures.append(f"{field}: added={added!r} removed={removed!r}")

    expected_trackers = baseline.get("expected_device_tracker_states", {})
    if isinstance(expected_trackers, dict):
        live_trackers = _device_tracker_snapshot(states)
        for entity_id, expected in expected_trackers.items():
            if live_trackers.get(entity_id) != expected:
                failures.append(
                    f"expected_device_tracker_states.{entity_id}: "
                    f"expected {expected!r}, got {live_trackers.get(entity_id)!r}"
                )

    expected_batteries = baseline.get("expected_battery_sensor_states", {})
    if isinstance(expected_batteries, dict):
        live_batteries = _battery_snapshot(states)
        for entity_id, expected in expected_batteries.items():
            if live_batteries.get(entity_id) != expected:
                failures.append(
                    f"expected_battery_sensor_states.{entity_id}: "
                    f"expected {expected!r}, got {live_batteries.get(entity_id)!r}"
                )
    return failures


# ---------------------------------------------------------------------------
# ADB-backup file format helpers
# ---------------------------------------------------------------------------


def adb_backup_payload(backup_path: Path) -> bytes:
    """Decode an Android Backup (.ab) file into raw tar bytes.

    Refuses encrypted backups (the probe runs in CI without a key). Returns the
    decompressed tar payload.
    """
    raw = backup_path.read_bytes()
    if not raw.startswith(b"ANDROID BACKUP\n"):
        raise RuntimeError("backup file is not in Android backup format")
    stream = io.BytesIO(raw)
    magic = stream.readline()
    version = stream.readline().strip()
    compressed = stream.readline().strip()
    encryption = stream.readline().strip()
    if magic != b"ANDROID BACKUP\n" or not version:
        raise RuntimeError("backup header is malformed")
    if encryption != b"none":
        raise RuntimeError("encrypted Android backup is unsupported")
    payload = stream.read()
    if compressed == b"1":
        return zlib.decompress(payload)
    if compressed == b"0":
        return payload
    raise RuntimeError(f"unknown Android backup compression flag {compressed!r}")


def adb_backup_extract_database_files(payload: bytes, db_basename: str) -> list[bytes]:
    """Extract database file bytes from a tar payload, matching `db_basename`.

    Matches members ending with `/db/<name>`, `/databases/<name>`, or just
    `<name>`.
    """
    databases: list[bytes] = []
    if not payload:
        return databases
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:*") as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            name = member.name
            if not (
                name.endswith(f"/db/{db_basename}")
                or name.endswith(f"/databases/{db_basename}")
                or name.endswith(db_basename)
            ):
                continue
            handle = archive.extractfile(member)
            if handle is None:
                continue
            data = handle.read()
            log(f"[DEBUG] extracted {name} {stream_digest(data)}")
            databases.append(data)
    return databases


def sqlite_select(database_bytes: bytes, query: str) -> list[tuple[Any, ...]]:
    """Run a read-only SQL query against an in-memory SQLite database file."""
    rows: list[tuple[Any, ...]] = []
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "db.sqlite"
        db_path.write_bytes(database_bytes)
        connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            rows = list(connection.execute(query).fetchall())
        finally:
            connection.close()
    return rows


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------


def emit_check_result(name: str, success: bool, message: str) -> dict[str, int]:
    """Print the standardized [PASS]/[FAIL] line and return the JSON-shape dict.

    Used by individual checks when run as `python3 checks/check_xxx.py`.
    """
    prefix = "[PASS]" if success else "[FAIL]"
    log(f"{prefix} {name}: {message}")
    return {name: 1 if success else 0}
