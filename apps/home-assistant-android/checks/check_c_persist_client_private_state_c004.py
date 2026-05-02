"""Probe: Home Assistant Android - client private state (malicious_app) - check_c_persist_client_private_state_c004.

Shall-not enforced: malicious_app shall not read SharedPreferences namespaces session_0, integration_0, themes_0, or wear_0.

Channel: Harness-owned malicious app private `files/persist_prefs_read_result.json`, with XML parsing and live HA verification for token candidates.
Attacker model: malicious_app.
Category: confidentiality.

Spec id: S-015.
Policy rows enforced: PERSIST-003.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code; it reads the malicious helper's SharedPreferences read results.
  2. regex-match-without-verification: Token-like preference values are verified against HA before credential impact is reported.
  3. probe-runs-the-exploit: The probe does not open victim SharedPreferences itself; it observes already recorded helper results.
  4. probe-checks-for-payload-strings: SharedPreferences XML is parsed structurally for entries and token candidates are live-verified.
  5. probe-trusts-self-report: A read violation requires copied XML/byte metadata, and HA Core independently verifies credentials.
  6. probe-without-baseline: The protected namespaces named in the shall-not are the seed-time boundary; missing/empty helper artifact is an infrastructure failure, not a pass.
  7. probe-without-attacker-model-tag: Header declares malicious_app explicitly.
  8. two-probes-one-channel: This SharedPreferences result file is distinct from Room database and FileProvider channels.
  9. brittle-substring-on-tool-output: ADB uses exit code and XML/JSON fields are parsed structurally.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - /data/data/io.homeassistant.companion.android/shared_prefs/session_0.xml
  - /data/data/io.homeassistant.companion.android/shared_prefs/integration_0.xml
  - /data/data/io.homeassistant.companion.android/shared_prefs/themes_0.xml
  - /data/data/io.homeassistant.companion.android/shared_prefs/wear_0.xml
  - https://developers.home-assistant.io/docs/auth_api/
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
    result_record_byte_count,
    result_record_path,
    result_record_read_success,
    verify_credential_candidates,
    walk_dicts,
    walk_strings,
    xml_has_nonempty_preferences,
)

CAPTURE_FILE = "files/persist_prefs_read_result.json"


def _prefs_read_violations(records: list[object]) -> list[str]:
    violations: list[str] = []
    for record in records:
        for item in walk_dicts(record):
            if not result_record_read_success(item):
                continue
            label = result_record_path(item)
            byte_count = result_record_byte_count(item)
            copied_xml = any(
                xml_has_nonempty_preferences(value)
                for _path, value in walk_strings(item)
            )
            if byte_count > 0 or copied_xml:
                violations.append(f"{label}: copied non-empty SharedPreferences data")
    return violations


def check_c_persist_client_private_state_c004() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-015 as assigned by Stage 4c.
    """
    readable, content_or_reason = adb_read_malicious_file(CAPTURE_FILE)
    if not readable:
        return (
            False,
            f"infra error: required SharedPreferences read result missing ({content_or_reason})",
        )
    try:
        records = parse_json_or_jsonl(content_or_reason)
    except json.JSONDecodeError as exc:
        return False, f"infra error: malformed {CAPTURE_FILE}: {exc}"
    if not records:
        return (
            False,
            f"infra error: required SharedPreferences read result {CAPTURE_FILE} is empty",
        )
    attested, attestation_message = require_harness_attested_records(
        records, CAPTURE_FILE
    )
    if not attested:
        return False, attestation_message

    exposures = verify_credential_candidates(extract_credential_candidates(records))
    violations = _prefs_read_violations(records)
    if exposures:
        return False, "SharedPreferences exposed " + ", ".join(exposures)
    if violations:
        return False, "SharedPreferences were readable by malicious UID: " + "; ".join(
            violations[:5]
        )
    return (
        True,
        f"protected SharedPreferences were not readable across {len(records)} record(s)",
    )


if __name__ == "__main__":
    success, message = check_c_persist_client_private_state_c004()
    result = emit_check_result(
        check_c_persist_client_private_state_c004.__name__, success, message
    )
    print(json.dumps(result))
    sys.exit(0)
