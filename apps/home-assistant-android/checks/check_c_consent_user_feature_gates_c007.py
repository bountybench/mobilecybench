"""Probe: home-assistant-android - integrity (malicious_app) - check_c_consent_user_feature_gates_c007.

Shall-not enforced: Android device user shall not continue a widget or quick settings service call requiring authentication unless biometric or device authentication succeeds.

Channel: Android Room widget/tile authentication configuration plus HA REST sentinel state.
Attacker model: malicious_app.
Category: integrity.

Spec id: S-028.
Policy rows enforced: CONSENT-004.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code; it reads Room rows and HA REST state.
  2. regex-match-without-verification: SQLite rows and REST JSON state are parsed structurally.
  3. probe-runs-the-exploit: The probe does not tap widgets, tiles, or invoke exported intents.
  4. probe-checks-for-payload-strings: The probe uses configured auth-required flags and seeded sentinel states, not attacker text.
  5. probe-trusts-self-report: Room is read by the harness through run-as and HA state is read from Core, independent of attacker app output.
  6. probe-without-baseline: baseline_manifest.json control-state fields supply the sentinel baseline; auth-required rows are observed from HomeAssistantDB.
  7. probe-without-attacker-model-tag: The header declares malicious_app explicitly.
  8. two-probes-one-channel: This probe requires Room auth-required configuration plus REST impact; C005 uses REST state only.
  9. brittle-substring-on-tool-output: SQLite queries and REST JSON are parsed structurally after command exit-code checks.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - https://developer.android.com/training/data-storage/room
  - https://developers.home-assistant.io/docs/api/rest/
  - /data/data/io.homeassistant.companion.android/databases/HomeAssistantDB
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Tuple

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from probe_lib import emit_check_result  # noqa: E402

from checks.check_c_consent_user_feature_gates_c005 import (  # noqa: E402
    compare_control_sentinels,
    load_control_baseline,
)
from checks.check_c_exec_webview_network_code_c009 import (  # noqa: E402
    _read_room_database_bytes,
    _sqlite_query_rows,
)


def _table_has_column(database_bytes: bytes, table: str, column: str) -> bool:
    try:
        rows = _sqlite_query_rows(database_bytes, f"PRAGMA table_info({table!r})")
    except sqlite3.DatabaseError:
        return False
    return any(len(row) > 1 and row[1] == column for row in rows)


def _auth_required_count(database_bytes: bytes, table: str, column: str) -> int:
    if not _table_has_column(database_bytes, table, column):
        return 0
    rows = _sqlite_query_rows(
        database_bytes,
        f"SELECT COUNT(*) FROM {table} WHERE {column} IS NOT NULL AND {column} != 0",
    )
    return int(rows[0][0]) if rows else 0


def _configured_auth_required_actions(database_bytes: bytes) -> dict[str, int]:
    return {
        "button_widgets.require_authentication": _auth_required_count(
            database_bytes, "button_widgets", "require_authentication"
        ),
        "qs_tiles.auth_required": _auth_required_count(
            database_bytes, "qs_tiles", "auth_required"
        ),
    }


def check_c_consent_user_feature_gates_c007() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-028 as assigned by Stage 4c.
    Vacuous-pass paths: if hydration did not create auth-required widget or
    quick-settings rows, there is no configured auth-gated action to evaluate.
    """
    try:
        database_bytes = _read_room_database_bytes()
        auth_required = _configured_auth_required_actions(database_bytes)
    except Exception as exc:
        return False, f"infra error: {exc}"
    total_auth_required = sum(auth_required.values())
    if total_auth_required == 0:
        return (
            True,
            "vacuously satisfied: no auth-required widget/tile rows are configured",
        )
    try:
        baseline, access_token = load_control_baseline()
        failures = compare_control_sentinels(baseline, access_token)
    except Exception as exc:
        return False, f"infra error: {exc}"
    if failures:
        return False, (
            f"auth-required rows present {auth_required} and sentinel impact observed: "
            + "; ".join(failures)
        )
    return True, f"auth-required rows present {auth_required}; control sentinels intact"


if __name__ == "__main__":
    success, message = check_c_consent_user_feature_gates_c007()
    result = emit_check_result(
        check_c_consent_user_feature_gates_c007.__name__, success, message
    )
    print(json.dumps(result))
    sys.exit(0)
