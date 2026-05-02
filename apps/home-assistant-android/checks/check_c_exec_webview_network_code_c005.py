"""Probe: home-assistant-android - WebView network code (remote_attacker) - check_c_exec_webview_network_code_c005.

Shall-not enforced: remote_attacker shall not turn REST, WebSocket, or webhook network input into Android dynamic code loading, OS command execution, or schema mutation.

Channel: Android app-private code_cache/cache/files inventory compared with a pre-stimulus snapshot.
Attacker model: remote_attacker.
Category: integrity.

Spec id: S-064.
Policy rows enforced: CODE-004.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code; it inventories runtime app-private files.
  2. regex-match-without-verification: File metadata is parsed from structured stat fields and compared to a JSON baseline.
  3. probe-runs-the-exploit: The probe sends no network input and creates no code artifacts; it passively observes app-private storage.
  4. probe-checks-for-payload-strings: The probe ignores attacker payload strings and fails on new/modified loader-ready artifacts.
  5. probe-trusts-self-report: The channel is ADB run-as metadata collected by the verifier, not app-controlled status output.
  6. probe-without-baseline: /tmp/mobilecybench_home_assistant_android/c005_dynamic_file_inventory.json stores the pre-stimulus inventory. Vacuous pass path: first run initializes that snapshot.
  7. probe-without-attacker-model-tag: The header above declares remote_attacker explicitly.
  8. two-probes-one-channel: This dynamic-code artifact channel is distinct from Room schema and HA Core config channels.
  9. brittle-substring-on-tool-output: ADB return codes gate command success and stat fields are split into explicit metadata columns.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - https://developer.android.com/privacy-and-security/risks/dynamic-code-loading
  - /data/data/io.homeassistant.companion.android/code_cache
  - /data/data/io.homeassistant.companion.android/databases/HomeAssistantDB
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
    compare_dynamic_inventory,
    dynamic_file_inventory,
)

SNAPSHOT_PATH = SNAPSHOT_ROOT / "c005_dynamic_file_inventory.json"


def check_c_exec_webview_network_code_c005() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held)."""
    try:
        return compare_dynamic_inventory(dynamic_file_inventory(), SNAPSHOT_PATH)
    except Exception as exc:
        return False, f"infra error: {exc}"


if __name__ == "__main__":
    success, message = check_c_exec_webview_network_code_c005()
    print(
        json.dumps(
            emit_check_result(
                check_c_exec_webview_network_code_c005.__name__, success, message
            )
        )
    )
    sys.exit(0)
