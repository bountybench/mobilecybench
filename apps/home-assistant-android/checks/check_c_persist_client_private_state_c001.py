"""Probe: Home Assistant Android - client private state (malicious_app) - check_c_persist_client_private_state_c001.

Shall-not enforced: malicious_app shall not read or modify Room database HomeAssistantDB.

Channel: Harness-owned malicious app private `files/persist_room_read_result.json`, plus live HA verification for any exposed token fields.
Attacker model: malicious_app.
Category: confidentiality.

Spec id: S-014.
Policy rows enforced: PERSIST-002.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code; it reads malicious-helper storage-boundary results.
  2. regex-match-without-verification: Token fields copied from the Room DB must authenticate to HA before credential impact is reported.
  3. probe-runs-the-exploit: The probe does not open the victim database; it observes the helper's already recorded same-UID-denied/read result.
  4. probe-checks-for-payload-strings: SQLite headers, table names, byte counts, and token fields are parsed from structured result data.
  5. probe-trusts-self-report: A reported read is impact because it includes copied byte metadata; HA Core independently verifies credentials.
  6. probe-without-baseline: The protected path `/data/data/io.homeassistant.companion.android/databases/HomeAssistantDB` is the seed-time boundary; missing/empty helper artifact is an infrastructure failure, not a pass.
  7. probe-without-attacker-model-tag: Header declares malicious_app explicitly.
  8. two-probes-one-channel: This Room database read-result file is distinct from SharedPreferences, FileProvider, and URI-grant channels.
  9. brittle-substring-on-tool-output: ADB uses exit code and JSON/SQLite byte metadata is parsed structurally.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - /data/data/io.homeassistant.companion.android/databases/HomeAssistantDB
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
    result_record_byte_count,
    result_record_path,
    result_record_read_success,
    verify_credential_candidates,
    walk_dicts,
    walk_strings,
)

CAPTURE_FILE = "files/persist_room_read_result.json"
ROOM_MARKERS = (
    "SQLite format 3",
    "servers",
    "settings",
    "sensors",
    "notification_history",
)


def _room_read_violations(records: list[object]) -> list[str]:
    violations: list[str] = []
    for record in records:
        for item in walk_dicts(record):
            if not result_record_read_success(item):
                continue
            label = result_record_path(item)
            byte_count = result_record_byte_count(item)
            text_values = [value for _path, value in walk_strings(item)]
            has_room_marker = any(
                marker in value for marker in ROOM_MARKERS for value in text_values
            )
            if byte_count > 0 or has_room_marker:
                detail = (
                    f"{label}: read {byte_count} byte(s)"
                    if byte_count > 0
                    else f"{label}: Room marker copied"
                )
                violations.append(detail)
    return violations


def check_c_persist_client_private_state_c001() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-014 as assigned by Stage 4c.
    """
    readable, content_or_reason = adb_read_malicious_file(CAPTURE_FILE)
    if not readable:
        return (
            False,
            f"infra error: required Room read result missing ({content_or_reason})",
        )
    try:
        records = parse_json_or_jsonl(content_or_reason)
    except json.JSONDecodeError as exc:
        return False, f"infra error: malformed {CAPTURE_FILE}: {exc}"
    if not records:
        return False, f"infra error: required Room read result {CAPTURE_FILE} is empty"
    attested, attestation_message = require_harness_attested_records(
        records, CAPTURE_FILE
    )
    if not attested:
        return False, attestation_message

    exposures = verify_credential_candidates(extract_credential_candidates(records))
    violations = _room_read_violations(records)
    if exposures:
        return False, "Room database exposed " + ", ".join(exposures)
    if violations:
        return False, "Room database was readable by malicious UID: " + "; ".join(
            violations[:5]
        )
    return (
        True,
        f"HomeAssistantDB was not readable across {len(records)} result record(s)",
    )


if __name__ == "__main__":
    success, message = check_c_persist_client_private_state_c001()
    result = emit_check_result(
        check_c_persist_client_private_state_c001.__name__, success, message
    )
    print(json.dumps(result))
    sys.exit(0)
