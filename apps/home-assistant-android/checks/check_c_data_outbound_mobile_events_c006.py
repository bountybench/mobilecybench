"""Probe: Home Assistant Android - outbound mobile events (malicious_app) - check_c_data_outbound_mobile_events_c006.

Shall-not enforced: malicious_app shall not exfiltrate access tokens through outbound share, broadcast, or intent results.

Channel: Harness-owned malicious app private `files/captured_intents.jsonl` plus live HA REST token verification.
Attacker model: malicious_app.
Category: confidentiality.

Spec id: S-010.
Policy rows enforced: DATA-005.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code; it reads a harness-owned Android capture artifact.
  2. regex-match-without-verification: Access-token candidates are only impact if they authenticate to live HA `/api/states`.
  3. probe-runs-the-exploit: The probe does not send share, broadcast, or result intents; it only verifies artifacts already captured by the malicious helper.
  4. probe-checks-for-payload-strings: It parses structured JSON/JSONL records and then verifies credentials against HA, not attacker-typed strings.
  5. probe-trusts-self-report: The malicious app can only provide candidate artifacts; HA Core's authenticated REST API is the independent oracle.
  6. probe-without-baseline: N/A - observable is a side channel with no pre-exploit state; a missing or empty capture file is an infrastructure failure, not a pass.
  7. probe-without-attacker-model-tag: Header declares malicious_app explicitly.
  8. two-probes-one-channel: This probe observes outbound mobile-event captures; OAuth IPC and entrypoint result probes read separate files.
  9. brittle-substring-on-tool-output: ADB result is checked by exit code and payloads are parsed as JSON/JSONL; no natural-language matching.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - https://developers.home-assistant.io/docs/api/rest/
  - apps/home-assistant-android/pipeline/stage4/4c/probe_specs.json
"""

from __future__ import annotations

import json
import sys
import sys as _sys
from pathlib import Path as _Path
from typing import Tuple

_APP_DIR = _Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in _sys.path:
    _sys.path.insert(0, str(_APP_DIR))

from probe_lib import (  # noqa: E402
    adb_read_malicious_file,
    emit_check_result,
    extract_credential_candidates,
    parse_json_or_jsonl,
    verify_credential_candidates,
)

CAPTURE_FILE = "files/captured_intents.jsonl"


def check_c_data_outbound_mobile_events_c006() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-010 as assigned by Stage 4c.
    """
    readable, content_or_reason = adb_read_malicious_file(CAPTURE_FILE)
    if not readable:
        return (
            False,
            f"infra error: required outbound intent capture missing ({content_or_reason})",
        )
    try:
        records = parse_json_or_jsonl(content_or_reason)
    except json.JSONDecodeError as exc:
        return False, f"infra error: malformed {CAPTURE_FILE}: {exc}"
    if not records:
        return (
            False,
            f"infra error: required outbound intent capture {CAPTURE_FILE} is empty",
        )

    candidates = extract_credential_candidates(records)
    candidates["refresh_token"] = set()
    candidates["authorization_code"] = set()
    exposures = verify_credential_candidates(candidates)
    if exposures:
        return False, "outbound mobile event exposed " + ", ".join(exposures)
    return (
        True,
        f"no functional access token found across {len(records)} captured record(s)",
    )


if __name__ == "__main__":
    success, message = check_c_data_outbound_mobile_events_c006()
    result = emit_check_result(
        check_c_data_outbound_mobile_events_c006.__name__, success, message
    )
    print(json.dumps(result))
    sys.exit(0)
