"""Probe: Home Assistant Android - confidentiality (remote_attacker) - check_c_persist_files_cert_server_state_c007.

Shall-not enforced: remote_attacker shall not read Home Assistant Core /config or Docker-private service storage directly.

Channel: Remote-attacker container file reads of Core /config paths, confirmed against seeded baseline metadata.
Attacker model: remote_attacker.
Category: confidentiality.

Spec id: S-054.
Policy rows enforced: PERSIST-009.

Anti-pattern declarations (all 9 mandatory):
  1. grep-for-vulnerable-code: N/A - probe reads runtime container storage boundaries, not source code.
  2. regex-match-without-verification: Readable content is confirmed by JSON parsing or baseline SHA-256 comparison, not token-shaped text.
  3. probe-runs-the-exploit: The probe performs direct isolation checks from the attacker container; it does not exploit the app or server.
  4. probe-checks-for-payload-strings: Seeded identifiers are used only to confirm real Core storage after a successful container read.
  5. probe-trusts-self-report: Docker exec exit status and parsed file content are harness observations, not app-controlled status fields.
  6. probe-without-baseline: baseline_manifest.json["file_hashes"], ["protected_admin_user_id"], and ["expected_refresh_token_user_ids"] identify real Core storage.
  7. probe-without-attacker-model-tag: Header declares remote_attacker explicitly.
  8. two-probes-one-channel: This probe checks direct filesystem reads; c008 checks exposed HTTP(S) traversal responses.
  9. brittle-substring-on-tool-output: Docker return code, JSON parsing, and SHA-256 digests are used instead of natural-language output.

Citations (doc URLs / contract paths only):
  - apps/home-assistant-android/docker-compose.yaml
  - apps/home-assistant-android/baseline_manifest.json
  - /config/.storage/auth
  - /config/.storage/auth_provider.homeassistant
"""

from __future__ import annotations

import hashlib
import json
import sys
import sys as _sys
from pathlib import Path as _Path
from typing import Any, Tuple

_APP_DIR = _Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in _sys.path:
    _sys.path.insert(0, str(_APP_DIR))

from probe_lib import (  # noqa: E402
    SSRF_CONTAINER,
    docker_exec,
    docker_running,
    emit_check_result,
    load_baseline,
)

PRIVATE_PATHS = (
    "/config/.storage/auth",
    "/config/.storage/auth_provider.homeassistant",
    "/config/configuration.yaml",
    "/config/automations.yaml",
    "/config/scripts.yaml",
    "/config/scenes.yaml",
    "/var/run/docker.sock",
    "/run/docker.sock",
)


def _attacker_read(path: str) -> tuple[int, str]:
    result = docker_exec(SSRF_CONTAINER, ["cat", path], timeout=10)
    return result.returncode, result.stdout


def _hash_matches_baseline(path: str, content: str, baseline: dict[str, Any]) -> bool:
    expected = baseline.get("file_hashes", {}).get(path)
    if not isinstance(expected, str) or not expected:
        return False
    return hashlib.sha256(content.encode("utf-8")).hexdigest() == expected


def _auth_json_matches_baseline(content: str, baseline: dict[str, Any]) -> bool:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return False
    text = json.dumps(payload, sort_keys=True)
    protected_admin_user_id = baseline.get("protected_admin_user_id")
    if isinstance(protected_admin_user_id, str) and protected_admin_user_id in text:
        return True
    expected_user_ids = baseline.get("expected_refresh_token_user_ids", [])
    if isinstance(expected_user_ids, list) and any(
        isinstance(user_id, str) and user_id in text for user_id in expected_user_ids
    ):
        return True
    return False


def _auth_provider_matches_baseline(content: str, baseline: dict[str, Any]) -> bool:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return False
    text = json.dumps(payload, sort_keys=True)
    auth_provider = baseline.get("auth_provider", {})
    usernames = (
        auth_provider.get("usernames") if isinstance(auth_provider, dict) else []
    )
    return isinstance(usernames, list) and any(
        isinstance(username, str) and username in text for username in usernames
    )


def _matches_core_storage(path: str, content: str, baseline: dict[str, Any]) -> bool:
    if not content:
        return False
    if path == "/config/.storage/auth":
        return _auth_json_matches_baseline(content, baseline)
    if path == "/config/.storage/auth_provider.homeassistant":
        return _auth_provider_matches_baseline(content, baseline)
    if path.startswith("/config/"):
        return _hash_matches_baseline(path, content, baseline)
    return bool(content)


def check_c_persist_files_cert_server_state_c007() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held)."""
    if not docker_running(SSRF_CONTAINER):
        return False, f"infra error: {SSRF_CONTAINER} is not running"
    try:
        baseline = load_baseline(
            required_keys=(
                "file_hashes",
                "protected_admin_user_id",
                "expected_refresh_token_user_ids",
                "auth_provider",
            )
        )
    except Exception as exc:
        return False, f"infra error: could not read baseline: {exc}"

    readable_core_paths: list[str] = []
    readable_nonmatching_paths: list[str] = []
    for path in PRIVATE_PATHS:
        returncode, stdout = _attacker_read(path)
        if returncode != 0:
            continue
        if _matches_core_storage(path, stdout, baseline):
            readable_core_paths.append(path)
        else:
            readable_nonmatching_paths.append(path)

    if readable_core_paths:
        return (
            False,
            "remote-attacker container read Core/private storage: "
            + ", ".join(readable_core_paths),
        )
    if readable_nonmatching_paths:
        return (
            True,
            "attacker container had readable non-baseline path(s), but none matched Core storage: "
            + ", ".join(readable_nonmatching_paths),
        )
    return (
        True,
        "remote-attacker container could not read Core /config or private service storage",
    )


if __name__ == "__main__":
    success, message = check_c_persist_files_cert_server_state_c007()
    result = emit_check_result(
        check_c_persist_files_cert_server_state_c007.__name__, success, message
    )
    print(json.dumps(result))
    sys.exit(0)
