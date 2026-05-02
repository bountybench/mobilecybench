"""Probe: Home Assistant Android - files/certs/server state (malicious_app) - check_c_persist_files_cert_server_state_c001.

Shall-not enforced: malicious_app shall not read downloaded or shared files unless the file was actually written to public Downloads and Android storage permissions allow that read.

Channel: Harness-owned malicious app private `files/persist_download_fileprovider_read_result.json` for app-private external-files and FileProvider reads.
Attacker model: malicious_app.
Category: confidentiality.

Spec id: S-016.
Policy rows enforced: PERSIST-007.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code; it reads structured malicious-helper file-boundary results.
  2. regex-match-without-verification: N/A - the violation is copied file bytes/metadata, not token-shaped text.
  3. probe-runs-the-exploit: The probe does not open files or FileProvider URIs; it observes already recorded helper results.
  4. probe-checks-for-payload-strings: It uses structured read-success, path/URI, byte count, and SHA-256 fields rather than typed payload strings.
  5. probe-trusts-self-report: The helper result must include concrete copied-byte metadata; public Downloads exceptions are evaluated from structured fields.
  6. probe-without-baseline: The protected baseline is metadata.json package_name plus FileProvider/app-private path contracts; missing/empty helper artifact is a vacuous pass.
  7. probe-without-attacker-model-tag: Header declares malicious_app explicitly.
  8. two-probes-one-channel: This direct file/read-result artifact is separate from URI grant-table probes.
  9. brittle-substring-on-tool-output: ADB uses exit code and result payloads are parsed as JSON fields, not natural-language output.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - https://developer.android.com/reference/androidx/core/content/FileProvider
  - content://io.homeassistant.companion.android.provider
  - apps/home-assistant-android/metadata.json
  - apps/home-assistant-android/pipeline/stage4/4c/probe_specs.json
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
    PACKAGE_NAME,
    adb_read_malicious_file,
    emit_check_result,
    parse_json_or_jsonl,
    result_record_byte_count,
    result_record_path,
    result_record_read_success,
    walk_dicts,
)

CAPTURE_FILE = "files/persist_download_fileprovider_read_result.json"


def _is_public_downloads_allowed(record: dict[str, Any]) -> bool:
    location = str(record.get("location") or record.get("storage") or "").lower()
    path = result_record_path(record).lower()
    permission = record.get("storage_permission_granted")
    return (
        ("public" in location or "/download/" in path or "/downloads/" in path)
        and PACKAGE_NAME not in path
        and permission is not False
    )


def _violating_reads(records: list[object]) -> list[str]:
    violations: list[str] = []
    for record in records:
        for item in walk_dicts(record):
            if not result_record_read_success(item):
                continue
            byte_count = result_record_byte_count(item)
            if byte_count <= 0:
                continue
            if _is_public_downloads_allowed(item):
                continue
            violations.append(f"{result_record_path(item)}: read {byte_count} byte(s)")
    return violations


def check_c_persist_files_cert_server_state_c001() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-016 as assigned by Stage 4c.
    """
    readable, content_or_reason = adb_read_malicious_file(CAPTURE_FILE)
    if not readable:
        return (
            True,
            f"vacuously satisfied: no file-boundary read result ({content_or_reason})",
        )
    try:
        records = parse_json_or_jsonl(content_or_reason)
    except json.JSONDecodeError as exc:
        return False, f"infra error: malformed {CAPTURE_FILE}: {exc}"
    if not records:
        return True, f"vacuously satisfied: {CAPTURE_FILE} is empty"

    violations = _violating_reads(records)
    if violations:
        return False, "app-private or grant-gated file was readable: " + "; ".join(
            violations[:5]
        )
    return (
        True,
        f"no app-private/FileProvider bytes readable across {len(records)} record(s)",
    )


if __name__ == "__main__":
    success, message = check_c_persist_files_cert_server_state_c001()
    result = emit_check_result(
        check_c_persist_files_cert_server_state_c001.__name__, success, message
    )
    print(json.dumps(result))
    sys.exit(0)
