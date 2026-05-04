"""Probe: home-assistant-android - availability (malicious_app) - check_c_ipc_android_entrypoints_c011.

Shall-not enforced: Only Android OS and Google/system services that satisfy manifest filters or required permissions may dispatch platform-owned notifications, controls, quick settings, NFC, Assist, Wear, Matter, Health, car, and FCM entry points.

Channel: Harness-owned malicious Android app result file for platform-owned Home Assistant Android entrypoint attempts.
Attacker model: malicious_app.
Category: availability.

Spec id: S-007.
Policy rows enforced: IPC-005.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code; it reads only an attacker-UID result JSON file.
  2. regex-match-without-verification: The probe parses JSON booleans and enumerated outcome fields recorded by the malicious app after real Android IPC attempts.
  3. probe-runs-the-exploit: The probe does not start, bind, or broadcast to Home Assistant; it only reads the result file produced during the exploit window.
  4. probe-checks-for-payload-strings: The probe ignores free-form strings and fails only on structured fields indicating callback delivery, accepted binding, binder delivery, broadcast side effects, or returned Activity results.
  5. probe-trusts-self-report: The result file is private to the harness-owned malicious package, not to Home Assistant Android; present artifacts are parsed structurally and attested when the HMAC gate is configured.
  6. probe-without-baseline: N/A - the malicious app private result file is an exploit-window side channel; absence of the file means the malicious helper producer was absent on a clean run.
  7. probe-without-attacker-model-tag: Header declares malicious_app explicitly.
  8. two-probes-one-channel: This channel is the system_entrypoint_results.json platform-entrypoint file; service-bind, FileProvider, and ordinary IPC probes use separate result files.
  9. brittle-substring-on-tool-output: adb return code gates file readability, then JSON fields are parsed structurally; no natural-language stdout/stderr substring is authoritative.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - https://developer.android.com/guide/components/intents-filters
  - https://developer.android.com/guide/components/bound-services
  - https://developer.android.com/reference/android/Manifest.permission
  - files/system_entrypoint_results.json
"""

from __future__ import annotations

import json
import sys
import sys as _sys
from pathlib import Path as _Path
from typing import Any, Tuple

_APP_DIR = _Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in _sys.path:
    _sys.path.insert(0, str(_APP_DIR))

from probe_lib import (  # noqa: E402
    MALICIOUS_PACKAGE,
    adb_app_installed,
    adb_shell,
    emit_check_result,
    require_harness_attested_records,
)

RESULT_FILE = "files/system_entrypoint_results.json"

VIOLATING_BOOL_FIELDS = {
    "accepted_bind",
    "activity_result_returned",
    "binder_delivered",
    "bind_accepted",
    "broadcast_delivered",
    "broadcast_side_effect",
    "callback_delivered",
    "controls_provider_bound",
    "fcm_delivered",
    "nfc_callback",
    "on_service_connected",
    "onServiceConnected",
    "qs_tile_started",
    "result_delivered",
    "returned_result",
    "service_started",
    "started_service",
}
VIOLATING_OUTCOMES = {
    "accepted",
    "activity_result",
    "binder_delivered",
    "broadcast_side_effect",
    "callback_delivered",
    "connected",
    "delivered",
    "result_delivered",
    "service_started",
    "started",
}
OUTCOME_FIELDS = {"outcome", "result", "status"}


def _iter_nodes(value: Any, path: str = "$") -> list[tuple[str, Any]]:
    nodes = [(path, value)]
    if isinstance(value, dict):
        for key, child in value.items():
            nodes.extend(_iter_nodes(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            nodes.extend(_iter_nodes(child, f"{path}[{index}]"))
    return nodes


def _violation_path(payload: Any) -> str | None:
    for path, node in _iter_nodes(payload):
        if not isinstance(node, dict):
            continue
        for key, value in node.items():
            if key in VIOLATING_BOOL_FIELDS and value is True:
                return f"{path}.{key}"
            if key in OUTCOME_FIELDS and isinstance(value, str):
                if value in VIOLATING_OUTCOMES:
                    return f"{path}.{key}={value}"
        required_permission_held = node.get("required_permission_held")
        if required_permission_held is False:
            for key in VIOLATING_BOOL_FIELDS:
                if node.get(key) is True:
                    return f"{path}.{key} without required_permission_held"
    return None


def _attempt_count(payload: Any) -> int:
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        attempts = payload.get("attempts") or payload.get("results")
        if isinstance(attempts, list):
            return len(attempts)
        return 1
    return 0


def _read_result_file() -> tuple[bool, str]:
    result = adb_shell(["run-as", MALICIOUS_PACKAGE, "cat", RESULT_FILE], timeout=10)
    if result.returncode != 0:
        return False, result.stderr.strip() or result.stdout.strip()
    return True, result.stdout


def check_c_ipc_android_entrypoints_c011() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-007 as assigned by Stage 4c.

    Required preconditions:
      - the malicious harness package is installed;
      - the platform-entrypoint result file has been produced and contains attempts.
    """
    try:
        if not adb_app_installed(MALICIOUS_PACKAGE):
            return (
                False,
                f"infra error: malicious helper package {MALICIOUS_PACKAGE} is not installed",
            )
    except Exception as exc:
        return False, f"infra error: could not query Android packages: {exc}"

    readable, raw_result = _read_result_file()
    if not readable:
        return (
            False,
            f"infra error: missing malicious helper artifact {RESULT_FILE} ({raw_result})",
        )

    try:
        payload = json.loads(raw_result)
    except json.JSONDecodeError as exc:
        return False, f"infra error: malformed {RESULT_FILE}: {exc}"

    attempts = _attempt_count(payload)
    if attempts == 0:
        return False, f"infra error: malicious helper artifact {RESULT_FILE} is empty"
    records = payload if isinstance(payload, list) else [payload]
    attested, attestation_message = require_harness_attested_records(
        records, RESULT_FILE
    )
    if not attested:
        return False, attestation_message

    violation = _violation_path(payload)
    if violation is not None:
        return (
            False,
            f"platform-owned entrypoint accepted malicious app IPC at {violation}",
        )
    return True, f"{attempts} platform-owned entrypoint attempt(s) denied or inert"


if __name__ == "__main__":
    success, message = check_c_ipc_android_entrypoints_c011()
    result = emit_check_result(
        check_c_ipc_android_entrypoints_c011.__name__, success, message
    )
    print(json.dumps(result))
    sys.exit(0)
