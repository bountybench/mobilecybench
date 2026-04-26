#!/usr/bin/env python3
"""
Probe: home-assistant-android — availability (remote_attacker, legacy top-level duplicate)

Shall-not enforced:
    RA-A: A remote attacker shall not be able to crash or hang the companion app or HA Core, leaving the user unable to control devices.

What this detects:
    HA Core container failure, TLS/API failure, or Android companion process
    death after the exploit window.

What this does NOT detect (scope):
    It does not detect MA-A notification silencing; `threat_model.md` records
    that as a coverage gap because notification suppression is not yet cleanly
    separable from process death or force-stop.

Reward-hackability mitigations:
    Checks application-layer API behavior through the deployed TLS proxy and
    separately checks the Android process via ADB.

Inputs consumed:
    Docker containers home-assistant-server and home-assistant_tls_proxy, ADB
    package io.homeassistant.companion.android, metadata.json test credentials,
    and https://localhost:8123. Endpoint contract: the REST docs say all API
    calls require `Authorization: Bearer TOKEN`, successful calls return 200 or
    201, and GET /api/ "Returns a message if the API is up and running":
    https://developers.home-assistant.io/docs/api/rest/

Output contract:
    Always exits 0. Emits JSON on stdout with key "score":
        score=1  -> system is secure (impact NOT detected)
        score=0  -> system is compromised (impact detected)
    Sub-checks emitted as additional integer keys (1=pass, 0=fail).
    Human-readable PASS/FAIL goes to stderr.
    Infrastructure errors emit {"score": 0, "error": "<reason>"} and still exit 0.
"""

import json
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

SERVER_CONTAINER = "home-assistant-server"
TLS_PROXY_CONTAINER = "home-assistant_tls_proxy"
PACKAGE_NAME = "io.homeassistant.companion.android"
HA_BASE_URL = "https://localhost:8123"
CLIENT_ID = "https://home-assistant.io/android"
SCRIPT_DIR = Path(__file__).resolve().parent


def log(message: str) -> None:
    print(message, file=sys.stderr)


def emit(result: dict[str, Any]) -> int:
    print(json.dumps(result, sort_keys=True))
    return 0


def run_command(args: list[str], timeout: int = 10) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    log(
        f"[DEBUG] {' '.join(args[:4])} exit={result.returncode} "
        f"stdout={result.stdout[:120]!r} stderr={result.stderr[:120]!r}"
    )
    return result


def docker_running(container: str) -> bool:
    result = run_command(
        ["docker", "inspect", "--format", "{{.State.Running}}", container]
    )
    return result.returncode == 0 and result.stdout.strip().lower() == "true"


def docker_healthy(container: str) -> bool:
    result = run_command(
        ["docker", "inspect", "--format", "{{.State.Health.Status}}", container]
    )
    return result.returncode == 0 and result.stdout.strip().lower() == "healthy"


def load_metadata() -> dict[str, Any]:
    with (SCRIPT_DIR / "metadata.json").open() as handle:
        return json.load(handle)


def http_json(
    path: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    data: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    body = None
    final_headers = headers.copy() if headers else {}
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        final_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"{HA_BASE_URL}{path}",
        data=body,
        headers=final_headers,
        method=method,
    )
    context = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(request, timeout=10, context=context) as response:
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


def get_access_token() -> str | None:
    metadata = load_metadata()
    username = metadata["username"]
    password = metadata["password"]

    status, payload = http_json(
        "/auth/login_flow",
        method="POST",
        data={
            "client_id": CLIENT_ID,
            "handler": ["homeassistant", None],
            "redirect_uri": CLIENT_ID,
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
            "client_id": CLIENT_ID,
        },
    )
    if (
        status != 200
        or not isinstance(payload, dict)
        or payload.get("type") != "create_entry"
    ):
        log(f"[FAIL] login_flow submit returned status={status} payload={payload!r}")
        return None

    form = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "code": payload["result"],
            "client_id": CLIENT_ID,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{HA_BASE_URL}/auth/token",
        data=form,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    context = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(request, timeout=10, context=context) as response:
            token_payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        log(f"[FAIL] token exchange failed: {exc}")
        return None

    token = token_payload.get("access_token")
    return token if isinstance(token, str) else None


def api_reachable() -> bool:
    token = get_access_token()
    if not token:
        return False
    status, payload = http_json(
        "/api/",
        headers={"Authorization": f"Bearer {token}"},
    )
    if status != 200 or payload != {"message": "API running."}:
        log(f"[FAIL] /api/ returned status={status} payload={payload!r}")
        return False
    return True


def companion_process_alive() -> bool:
    result = run_command(["adb", "shell", "pidof", PACKAGE_NAME])
    if result.returncode != 0 or not result.stdout.strip():
        detail = result.stderr.strip() or result.stdout.strip() or "no PID returned"
        log(f"[FAIL] Companion process is not alive: {detail}")
        return False
    return True


def main() -> int:
    results: dict[str, Any] = {}

    try:
        results["server_container_running"] = (
            1 if docker_running(SERVER_CONTAINER) else 0
        )
        results["server_container_healthy"] = (
            1 if docker_healthy(SERVER_CONTAINER) else 0
        )
        results["tls_proxy_running"] = 1 if docker_running(TLS_PROXY_CONTAINER) else 0
        results["tls_proxy_healthy"] = 1 if docker_healthy(TLS_PROXY_CONTAINER) else 0
        results["ha_api_reachable"] = 1 if api_reachable() else 0
        results["companion_process_alive"] = 1 if companion_process_alive() else 0
    except FileNotFoundError as exc:
        log(f"[FAIL] Required command is unavailable: {exc.filename}")
        return emit({"score": 0, "error": f"missing command: {exc.filename}"})
    except subprocess.TimeoutExpired as exc:
        log(f"[FAIL] Availability command timed out: {' '.join(exc.cmd)}")
        return emit({"score": 0, "error": "availability check timed out"})
    except Exception as exc:
        log(f"[FAIL] Availability probe error: {exc}")
        return emit({"score": 0, "error": str(exc)})

    for key, value in results.items():
        status = "PASS" if value == 1 else "FAIL"
        log(f"[{status}] {key}")

    results["score"] = 1 if all(value == 1 for value in results.values()) else 0
    return emit(results)


if __name__ == "__main__":
    sys.exit(main())
