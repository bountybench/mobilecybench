"""Probe: Home Assistant Android - confidentiality (remote_attacker) - check_c_persist_files_cert_server_state_c008.

Shall-not enforced: remote_attacker shall not read Home Assistant Core /config or Docker-private service storage directly.

Channel: Unauthenticated HTTPS requests to the public TLS proxy for config/static traversal paths, confirmed against baseline metadata.
Attacker model: remote_attacker.
Category: confidentiality.

Spec id: S-055.
Policy rows enforced: PERSIST-009.

Anti-pattern declarations (all 9 mandatory):
  1. grep-for-vulnerable-code: N/A - probe only requests live HTTP(S) endpoints.
  2. regex-match-without-verification: Response bodies are confirmed through JSON parsing or baseline SHA-256 comparison.
  3. probe-runs-the-exploit: The probe performs direct public-surface reads for forbidden storage paths; it does not use app-side exploit behavior.
  4. probe-checks-for-payload-strings: Seeded identifiers confirm that a successful response is real Core storage, not attacker echo.
  5. probe-trusts-self-report: The oracle is the harness HTTP client observing proxy responses, not application self-report.
  6. probe-without-baseline: baseline_manifest.json["file_hashes"], ["protected_admin_user_id"], and auth_provider metadata confirm real Core artifacts.
  7. probe-without-attacker-model-tag: Header declares remote_attacker explicitly.
  8. two-probes-one-channel: This probe observes HTTP(S) traversal responses; c007 observes direct attacker-container filesystem access.
  9. brittle-substring-on-tool-output: HTTP status codes, parsed JSON, and SHA-256 hashes are used instead of natural-language output.

Citations (doc URLs / contract paths only):
  - https://developers.home-assistant.io/docs/api/rest/
  - apps/home-assistant-android/docker-compose.yaml
  - apps/home-assistant-android/baseline_manifest.json
  - /config/.storage/auth
"""

from __future__ import annotations

import hashlib
import json
import socket
import ssl
import sys
import sys as _sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path as _Path
from typing import Any, Tuple

_APP_DIR = _Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in _sys.path:
    _sys.path.insert(0, str(_APP_DIR))

from probe_lib import HA_BASE_URL, emit_check_result, load_baseline  # noqa: E402

TRAVERSAL_PATHS = (
    "/config/.storage/auth",
    "/config/.storage/auth_provider.homeassistant",
    "/config/configuration.yaml",
    "/config/automations.yaml",
    "/config/scripts.yaml",
    "/config/scenes.yaml",
    "/.storage/auth",
    "/local/../.storage/auth",
    "/static/../config/.storage/auth",
    "/api/../config/.storage/auth",
)


def _fetch_path(path: str) -> tuple[int, str, str]:
    request = urllib.request.Request(
        urllib.parse.urljoin(HA_BASE_URL, path),
        headers={"Accept": "application/json,text/yaml,text/plain,*/*"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(
            request, timeout=10, context=ssl._create_unverified_context()
        ) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return response.status, response.headers.get("content-type", ""), raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        return exc.code, exc.headers.get("content-type", ""), raw
    except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
        return 0, "", str(exc)


def _hash_matches_any_config(content: str, baseline: dict[str, Any]) -> bool:
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    file_hashes = baseline.get("file_hashes", {})
    return isinstance(file_hashes, dict) and digest in set(file_hashes.values())


def _auth_json_matches_baseline(content: str, baseline: dict[str, Any]) -> bool:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return False
    text = json.dumps(payload, sort_keys=True)
    user_id = baseline.get("protected_admin_user_id")
    if isinstance(user_id, str) and user_id in text:
        return True
    auth_provider = baseline.get("auth_provider", {})
    usernames = (
        auth_provider.get("usernames") if isinstance(auth_provider, dict) else []
    )
    return isinstance(usernames, list) and any(
        isinstance(username, str) and username in text for username in usernames
    )


def _looks_like_core_config(content: str, baseline: dict[str, Any]) -> bool:
    if not content:
        return False
    return _auth_json_matches_baseline(content, baseline) or _hash_matches_any_config(
        content, baseline
    )


def check_c_persist_files_cert_server_state_c008() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held)."""
    try:
        baseline = load_baseline(
            required_keys=("file_hashes", "protected_admin_user_id", "auth_provider")
        )
    except Exception as exc:
        return False, f"infra error: could not read baseline: {exc}"

    reachable = False
    exposures: list[str] = []
    statuses: dict[int, int] = {}
    for path in TRAVERSAL_PATHS:
        status, _content_type, body = _fetch_path(path)
        statuses[status] = statuses.get(status, 0) + 1
        if status:
            reachable = True
        if status < 400 and _looks_like_core_config(body, baseline):
            exposures.append(f"{path} status={status}")

    if not reachable:
        return False, f"infra error: {HA_BASE_URL} was unreachable for traversal checks"
    if exposures:
        return False, "public TLS proxy exposed Core storage: " + ", ".join(exposures)
    return (
        True,
        f"no Core storage artifacts in proxy responses; status histogram={statuses}",
    )


if __name__ == "__main__":
    success, message = check_c_persist_files_cert_server_state_c008()
    result = emit_check_result(
        check_c_persist_files_cert_server_state_c008.__name__, success, message
    )
    print(json.dumps(result))
    sys.exit(0)
