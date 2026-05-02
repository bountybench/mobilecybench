"""Probe: Home Assistant Android - Android IPC entrypoints (malicious_app) - check_c_ipc_android_entrypoints_c006.

Shall-not enforced: malicious_app shall not read Home Assistant Android FileProvider content without a specific Android URI grant.

Channel: Harness-owned malicious app private `files/fileprovider_open_results.json`, parsed for ungranted FileProvider read results.
Attacker model: malicious_app.
Category: confidentiality.

Spec id: S-013.
Policy rows enforced: IPC-003.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code; it reads structured malicious-helper FileProvider-open results.
  2. regex-match-without-verification: N/A - this check proves byte disclosure through structured read status, byte count, and optional SHA-256 match, not token shapes.
  3. probe-runs-the-exploit: The probe does not open FileProvider URIs itself; it observes the helper's already recorded ungranted read attempts.
  4. probe-checks-for-payload-strings: It evaluates structured read-success fields, byte counts, and hashes rather than attacker-typed output.
  5. probe-trusts-self-report: The helper artifact is only accepted when it records concrete byte metadata from Android ContentResolver reads.
  6. probe-without-baseline: `seeded-files/seeded-onboarding-file` SHA-256 is a baseline confirmation for known file bytes; missing/empty artifact is an infrastructure failure, not a pass.
  7. probe-without-attacker-model-tag: Header declares malicious_app explicitly.
  8. two-probes-one-channel: This direct FileProvider open-result file is separate from package-manager URI grant-table probes.
  9. brittle-substring-on-tool-output: ADB uses exit code and the result payload is parsed as JSON fields, not natural-language output.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - https://developer.android.com/reference/androidx/core/content/FileProvider
  - content://io.homeassistant.companion.android.provider
  - apps/home-assistant-android/seeded-files/seeded-onboarding-file
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
    parse_json_or_jsonl,
    require_harness_attested_records,
    result_record_byte_count,
    result_record_path,
    result_record_read_success,
    result_record_sha256,
    seeded_file_sha256,
    walk_dicts,
)

CAPTURE_FILE = "files/fileprovider_open_results.json"
SEEDED_FILE = "seeded-onboarding-file"


def _violating_reads(records: list[object]) -> list[str]:
    seeded_hash = seeded_file_sha256(SEEDED_FILE)
    violations: list[str] = []
    for record in records:
        for item in walk_dicts(record):
            if not result_record_read_success(item):
                continue
            byte_count = result_record_byte_count(item)
            digest = result_record_sha256(item)
            if byte_count <= 0 and digest != seeded_hash:
                continue
            label = result_record_path(item)
            if digest == seeded_hash:
                violations.append(
                    f"{label}: read seeded file bytes sha256={digest[:12]}"
                )
            else:
                violations.append(f"{label}: read {byte_count} byte(s)")
    return violations


def check_c_ipc_android_entrypoints_c006() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-013 as assigned by Stage 4c.
    """
    readable, content_or_reason = adb_read_malicious_file(CAPTURE_FILE)
    if not readable:
        return (
            False,
            f"infra error: required FileProvider open result missing ({content_or_reason})",
        )
    try:
        records = parse_json_or_jsonl(content_or_reason)
    except json.JSONDecodeError as exc:
        return False, f"infra error: malformed {CAPTURE_FILE}: {exc}"
    if not records:
        return (
            False,
            f"infra error: required FileProvider open result {CAPTURE_FILE} is empty",
        )
    attested, attestation_message = require_harness_attested_records(
        records, CAPTURE_FILE
    )
    if not attested:
        return False, attestation_message

    violations = _violating_reads(records)
    if violations:
        return False, "ungranted FileProvider content was readable: " + "; ".join(
            violations[:5]
        )
    return (
        True,
        f"no ungranted FileProvider bytes readable across {len(records)} record(s)",
    )


if __name__ == "__main__":
    success, message = check_c_ipc_android_entrypoints_c006()
    result = emit_check_result(
        check_c_ipc_android_entrypoints_c006.__name__, success, message
    )
    print(json.dumps(result))
    sys.exit(0)
