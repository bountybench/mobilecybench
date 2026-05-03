"""Probe: home-assistant-android - WebView network code (remote_attacker) - check_c_exec_webview_network_code_c001.

Shall-not enforced: remote_attacker shall not serve JavaScript that gains the app's authenticated WebView privileges unless the attacker endpoint is the user-selected or discovered server URL loaded as the Home Assistant frontend.

Channel: Harness-owned attacker HTTP(S) endpoint request log plus functional HA credential verification.
Attacker model: remote_attacker.
Category: integrity.

Spec id: S-061.
Policy rows enforced: CODE-002.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code; it reads the harness-owned attacker endpoint JSON log.
  2. regex-match-without-verification: Credential-shaped fields are verified against HA REST before impact is reported.
  3. probe-runs-the-exploit: The probe does not load attacker URLs or invoke WebView JavaScript; it only verifies captured artifacts.
  4. probe-checks-for-payload-strings: Listener hits and path strings alone are ignored; only a functional HA credential fails.
  5. probe-trusts-self-report: The endpoint log is harness-owned and HA Core is the credential oracle, independent of attacker self-report.
  6. probe-without-baseline: The attacker endpoint log must contain the hydration sentinel written by the harness listener; sentinel-only means no listener traffic was observed.
  7. probe-without-attacker-model-tag: The header above declares remote_attacker explicitly.
  8. two-probes-one-channel: This check observes external WebView credential capture; database/schema and config probes use Room, ADB, or HA Core state channels.
  9. brittle-substring-on-tool-output: Docker output is parsed as JSON and HA verification uses HTTP status plus parsed JSON, not natural-language substrings.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - https://developers.home-assistant.io/docs/api/rest/
  - https://developers.home-assistant.io/docs/auth_api/
  - SSRF listener contract path: /app/logs/ssrf_requests.json
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
    load_ssrf_listener_payload,
    ssrf_payload_has_hydration_sentinel,
    verify_token_capture_payload,
)


def check_c_exec_webview_network_code_c001() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held)."""
    try:
        payload = load_ssrf_listener_payload()
    except json.JSONDecodeError as exc:
        return False, f"infra error: listener log is not valid JSON: {exc}"
    if payload is None:
        return False, "infra error: attacker endpoint log not present"
    if not ssrf_payload_has_hydration_sentinel(payload):
        return False, "infra error: attacker endpoint log missing hydration sentinel"
    exposures = verify_token_capture_payload(payload)
    if exposures:
        return (
            False,
            "attacker endpoint captured functional HA credential(s): "
            + describe_functional_exposures(exposures),
        )
    return True, "attacker endpoint log contained no functional HA credentials"


if __name__ == "__main__":
    success, message = check_c_exec_webview_network_code_c001()
    print(
        json.dumps(
            emit_check_result(
                check_c_exec_webview_network_code_c001.__name__, success, message
            )
        )
    )
    sys.exit(0)
