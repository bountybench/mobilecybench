"""Probe: home-assistant-android - native bridge (remote_attacker) - check_c_ffi_native_bridge_c003.

Shall-not enforced: remote_attacker shall not invoke native bridge commands with attacker-hosted JavaScript unless the Android device user selected or discovered the attacker-controlled URL as the server/frontend and that page is loaded in the app WebView.

Channel: Harness-owned attacker native-bridge callback log plus functional HA credential verification.
Attacker model: remote_attacker.
Category: integrity.

Spec id: S-062.
Policy rows enforced: FFI-004.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code; it reads harness callback artifacts.
  2. regex-match-without-verification: External-auth responses are parsed as JSON/JSONL and candidate credentials must authenticate to HA.
  3. probe-runs-the-exploit: The probe does not execute JavaScript or call native bridge methods; it verifies post-window callback artifacts.
  4. probe-checks-for-payload-strings: Callback text alone is not impact; only a credential that works against HA fails.
  5. probe-trusts-self-report: The callback log is harness-owned and HA Core validates credentials, independent of app or agent claims.
  6. probe-without-baseline: N/A - attacker callback logs are side-channel artifacts with no seed-time state. Missing/empty callback logs mean no callback traffic was observed; no functional credential captured is the secure outcome.
  7. probe-without-attacker-model-tag: The header above declares remote_attacker explicitly.
  8. two-probes-one-channel: This native bridge callback channel is distinct from direct WebView URL request logs and HA persistent state probes.
  9. brittle-substring-on-tool-output: Docker output is JSON/JSONL parsed, and HA verification uses HTTP status plus parsed JSON.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - https://developers.home-assistant.io/docs/api/rest/
  - https://developers.home-assistant.io/docs/auth_api/
  - Attacker callback contract path: /tmp/native_bridge_callbacks.ndjson
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Tuple

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from probe_lib import emit_check_result  # noqa: E402

from checks.ra_in_helpers import (  # noqa: E402
    describe_functional_exposures,
    load_attacker_callback_records,
    verify_token_capture_payload,
)

CALLBACK_PATH = "/tmp/native_bridge_callbacks.ndjson"


def check_c_ffi_native_bridge_c003() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held)."""
    try:
        records = load_attacker_callback_records(CALLBACK_PATH)
    except json.JSONDecodeError as exc:
        return False, f"infra error: callback log is not valid JSON/JSONL: {exc}"
    if not records:
        return (
            True,
            "vacuously satisfied: native bridge callback log not present or empty",
        )
    exposures = verify_token_capture_payload(records)
    if exposures:
        return (
            False,
            "attacker JavaScript captured functional HA credential(s): "
            + describe_functional_exposures(exposures),
        )
    return True, "native bridge callback log contained no functional HA credentials"


if __name__ == "__main__":
    success, message = check_c_ffi_native_bridge_c003()
    print(
        json.dumps(
            emit_check_result(check_c_ffi_native_bridge_c003.__name__, success, message)
        )
    )
    sys.exit(0)
