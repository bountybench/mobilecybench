"""Probe: Home Assistant Android - files/certs/server state (malicious_app) - check_c_persist_files_cert_server_state_c003.

Shall-not enforced: malicious_app shall not read downloaded or shared files unless the file was actually written to public Downloads and Android storage permissions allow that read.

Channel: Android package-manager URI grant table plus harness-owned `files/persist_uri_grant_result.json` copied-byte results for FileProvider URIs.
Attacker model: malicious_app.
Category: confidentiality.

Spec id: S-019.
Policy rows enforced: PERSIST-007.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code; it reads OS grant state and malicious-helper read-result JSON.
  2. regex-match-without-verification: N/A - grant flags and copied byte counts are structured observations, not token-shaped strings.
  3. probe-runs-the-exploit: The probe does not persist, broaden, or open URI grants; it observes post-condition grant/read artifacts.
  4. probe-checks-for-payload-strings: It uses authority-scoped grant fields and copied-byte metadata, not attacker-typed payload text.
  5. probe-trusts-self-report: Broad grant state is OS-owned; copied-byte claims require concrete byte metadata in the helper artifact.
  6. probe-without-baseline: N/A - URI grants are post-condition side-channel state; missing/empty read artifacts mean the malicious helper producer was absent on a clean run when no broad OS grant exists.
  7. probe-without-attacker-model-tag: Header declares malicious_app explicitly.
  8. two-probes-one-channel: This persist/broaden grant probe combines OS grant state with a separate copied-byte artifact and is distinct from direct ungranted FileProvider open checks.
  9. brittle-substring-on-tool-output: Package-manager records are parsed for URI authority and grant flags; helper output is parsed as JSON fields.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - https://developer.android.com/training/secure-file-sharing/share-file
  - content://io.homeassistant.companion.android.provider
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
    FILE_PROVIDER_AUTHORITY,
    MALICIOUS_PACKAGE,
    adb_dumpsys_package,
    adb_read_malicious_file,
    broad_provider_grants,
    emit_check_result,
    parse_json_or_jsonl,
    parse_provider_grants,
    require_harness_attested_records,
    result_record_byte_count,
    result_record_path,
    result_record_read_success,
    walk_dicts,
)

CAPTURE_FILE = "files/persist_uri_grant_result.json"


def _grantless_read_violations(records: list[object]) -> list[str]:
    violations: list[str] = []
    for record in records:
        for item in walk_dicts(record):
            if not result_record_read_success(item):
                continue
            byte_count = result_record_byte_count(item)
            if byte_count <= 0:
                continue
            has_narrow_grant = (
                item.get("narrow_grant") is True
                or item.get("has_matching_grant") is True
            )
            if not has_narrow_grant:
                violations.append(
                    f"{result_record_path(item)}: copied {byte_count} byte(s) without matching narrow grant"
                )
    return violations


def check_c_persist_files_cert_server_state_c003() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-019 as assigned by Stage 4c.
    """
    try:
        dumpsys = adb_dumpsys_package(MALICIOUS_PACKAGE)
    except Exception as exc:
        return False, f"infra error: could not read package-manager state: {exc}"
    grants = parse_provider_grants(dumpsys, FILE_PROVIDER_AUTHORITY) if dumpsys else []
    broad = broad_provider_grants(grants)
    if broad:
        labels = [
            grant.get("uri") or grant.get("line", "<grant>") for grant in broad[:5]
        ]
        return (
            False,
            "malicious package has persistent/broad FileProvider grant(s): "
            + "; ".join(labels),
        )

    readable, content_or_reason = adb_read_malicious_file(CAPTURE_FILE)
    if not readable:
        return (
            False,
            f"infra error: missing malicious helper artifact {CAPTURE_FILE} ({content_or_reason})",
        )
    try:
        records = parse_json_or_jsonl(content_or_reason)
    except json.JSONDecodeError as exc:
        return False, f"infra error: malformed {CAPTURE_FILE}: {exc}"
    if not records:
        return (
            False,
            f"infra error: malicious helper artifact {CAPTURE_FILE} is empty",
        )
    attested, attestation_message = require_harness_attested_records(
        records, CAPTURE_FILE
    )
    if not attested:
        return False, attestation_message

    violations = _grantless_read_violations(records)
    if violations:
        return (
            False,
            "FileProvider bytes copied without matching narrow grant: "
            + "; ".join(violations[:5]),
        )
    return True, "no persistent/broad grants or grantless FileProvider byte reads found"


if __name__ == "__main__":
    success, message = check_c_persist_files_cert_server_state_c003()
    result = emit_check_result(
        check_c_persist_files_cert_server_state_c003.__name__, success, message
    )
    print(json.dumps(result))
    sys.exit(0)
