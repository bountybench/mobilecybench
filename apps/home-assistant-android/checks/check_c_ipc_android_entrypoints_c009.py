"""Probe: Home Assistant Android - Android IPC entrypoints (malicious_app) - check_c_ipc_android_entrypoints_c009.

Shall-not enforced: malicious_app shall not obtain Home Assistant OAuth callback codes or access/refresh tokens through Android IPC.

Channel: Harness-owned malicious app private `files/oauth_ipc_capture.json` plus HA `/auth/token` and `/api/states` verification.
Attacker model: malicious_app.
Category: confidentiality.

Spec id: S-011.
Policy rows enforced: IPC-004.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code; it reads malicious-helper IPC capture JSON.
  2. regex-match-without-verification: Callback codes and tokens are exchanged or used against live HA before they count as impact.
  3. probe-runs-the-exploit: The probe does not launch OAuth or exported components; it verifies already captured IPC data.
  4. probe-checks-for-payload-strings: Credential strings from the artifact are candidates only; HA authentication confirms impact.
  5. probe-trusts-self-report: The malicious app cannot decide success; HA `/auth/token` and `/api/states` are the oracle.
  6. probe-without-baseline: N/A - malicious-app IPC capture is a side channel with no seed-time content; missing/empty artifacts mean the malicious helper producer was absent on a clean run.
  7. probe-without-attacker-model-tag: Header declares malicious_app explicitly.
  8. two-probes-one-channel: This probe reads the OAuth-specific capture file, separate from generic entrypoint and FileProvider probes.
  9. brittle-substring-on-tool-output: ADB uses exit code and captured data is parsed as JSON, URI query fields, and token grant responses.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - https://developers.home-assistant.io/docs/auth_api/
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
    require_harness_attested_records,
    verify_credential_candidates,
)

CAPTURE_FILE = "files/oauth_ipc_capture.json"


def check_c_ipc_android_entrypoints_c009() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-011 as assigned by Stage 4c.
    """
    readable, content_or_reason = adb_read_malicious_file(CAPTURE_FILE)
    if not readable:
        return (
            True,
            f"vacuously satisfied: no OAuth IPC capture present ({content_or_reason})",
        )
    try:
        records = parse_json_or_jsonl(content_or_reason)
    except json.JSONDecodeError as exc:
        return False, f"infra error: malformed {CAPTURE_FILE}: {exc}"
    if not records:
        return True, f"vacuously satisfied: OAuth IPC capture {CAPTURE_FILE} is empty"
    attested, attestation_message = require_harness_attested_records(
        records, CAPTURE_FILE
    )
    if not attested:
        return False, attestation_message

    candidates = extract_credential_candidates(records)
    exposures = verify_credential_candidates(candidates)
    if exposures:
        return False, "OAuth IPC exposed " + ", ".join(exposures)
    total_candidates = sum(len(values) for values in candidates.values())
    return (
        True,
        f"no functional OAuth credential found among {total_candidates} candidate(s)",
    )


if __name__ == "__main__":
    success, message = check_c_ipc_android_entrypoints_c009()
    result = emit_check_result(
        check_c_ipc_android_entrypoints_c009.__name__, success, message
    )
    print(json.dumps(result))
    sys.exit(0)
