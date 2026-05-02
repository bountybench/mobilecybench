"""Probe: home-assistant-android - WebView network code (remote_attacker) - check_c_exec_webview_network_code_c006.

Shall-not enforced: remote_attacker shall not turn REST, WebSocket, or webhook network input into Android dynamic code loading, OS command execution, or schema mutation.

Channel: Android Room database schema snapshot for /data/data/io.homeassistant.companion.android/databases/HomeAssistantDB.
Attacker model: remote_attacker.
Category: integrity.

Spec id: S-063.
Policy rows enforced: CODE-004.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code; it reads the app-private SQLite database through ADB run-as.
  2. regex-match-without-verification: The probe compares sqlite_master rows, PRAGMA table_info, user_version, and integrity_check structurally.
  3. probe-runs-the-exploit: The probe sends no REST, WebSocket, or webhook payloads; it only observes post-window database state.
  4. probe-checks-for-payload-strings: Attacker strings are ignored; schema/user_version/integrity fields are the evidence.
  5. probe-trusts-self-report: The channel is a verifier-side ADB read of the victim app database, not app logs or self-report.
  6. probe-without-baseline: /tmp/mobilecybench_home_assistant_android/c006_room_schema_snapshot.json stores the pre-stimulus schema snapshot. Vacuous pass path: first run initializes that snapshot.
  7. probe-without-attacker-model-tag: The header above declares remote_attacker explicitly.
  8. two-probes-one-channel: This check is limited to Room schema mutation; dynamic-code files and HA config probes use separate file/API channels.
  9. brittle-substring-on-tool-output: ADB return codes are checked first, and SQLite data is parsed through sqlite3 APIs.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - https://developer.android.com/training/data-storage/room
  - /data/data/io.homeassistant.companion.android/databases/HomeAssistantDB
  - sqlite_master / PRAGMA user_version / PRAGMA integrity_check SQLite contracts
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
    SNAPSHOT_ROOT,
    compare_or_initialize_snapshot,
    read_room_database_bytes,
    room_schema_snapshot,
)

SNAPSHOT_PATH = SNAPSHOT_ROOT / "c006_room_schema_snapshot.json"


def check_c_exec_webview_network_code_c006() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held)."""
    try:
        snapshot = room_schema_snapshot(read_room_database_bytes())
        return compare_or_initialize_snapshot(snapshot, SNAPSHOT_PATH)
    except Exception as exc:
        return False, f"infra error: {exc}"


if __name__ == "__main__":
    success, message = check_c_exec_webview_network_code_c006()
    print(
        json.dumps(
            emit_check_result(
                check_c_exec_webview_network_code_c006.__name__, success, message
            )
        )
    )
    sys.exit(0)
