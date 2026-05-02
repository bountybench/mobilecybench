"""Probe: home-assistant-android - WebView network code (remote_attacker) - check_c_exec_webview_network_code_c007.

Shall-not enforced: remote_attacker shall not turn REST, WebSocket, or webhook network input into Android dynamic code loading, OS command execution, or schema mutation.

Channel: Home Assistant Core protected /config file hashes and automation/script/scene entity inventory.
Attacker model: remote_attacker.
Category: integrity.

Spec id: S-065.
Policy rows enforced: CODE-004.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source; it reads live HA Core config artifacts and REST state.
  2. regex-match-without-verification: The probe compares SHA-256 hashes and parsed /api/states entity IDs, not regex matches.
  3. probe-runs-the-exploit: The probe does not send network input or service calls; it observes post-window persistence.
  4. probe-checks-for-payload-strings: It ignores attacker payload strings and checks durable server-side state only.
  5. probe-trusts-self-report: Docker file reads and HA REST state queried with the probe LLAT are independent of attacker self-report.
  6. probe-without-baseline: baseline_manifest.json["file_hashes"], ["expected_automation_entities"], ["expected_script_entities"], and ["expected_scene_entities"] supply the seed baseline.
  7. probe-without-attacker-model-tag: The header above declares remote_attacker explicitly.
  8. two-probes-one-channel: This check covers HA Core config/entity persistence; Room and dynamic-code probes use Android app-private channels.
  9. brittle-substring-on-tool-output: Docker output is hashed, REST payloads are parsed as JSON, and comparisons are structural.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - https://developers.home-assistant.io/docs/api/rest/
  - /config/automations.yaml
  - /config/scripts.yaml
  - /config/scenes.yaml
  - apps/home-assistant-android/baseline_manifest.json
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
    admin_access_token,
    config_file_hash_failures,
    entity_inventory_failures,
    live_states_by_entity_id,
    load_v2_baseline,
    require_server_running,
)


def check_c_exec_webview_network_code_c007() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held)."""
    try:
        require_server_running()
        baseline = load_v2_baseline(
            (
                "file_hashes",
                "expected_automation_entities",
                "expected_script_entities",
                "expected_scene_entities",
                "probe_admin_llat",
            )
        )
        token = admin_access_token(baseline)
        failures = config_file_hash_failures(baseline)
        failures.extend(
            entity_inventory_failures(baseline, live_states_by_entity_id(token))
        )
    except Exception as exc:
        return False, f"infra error: {exc}"
    if failures:
        return False, "; ".join(failures)
    return (
        True,
        "protected config hashes and automation/script/scene inventory match baseline",
    )


if __name__ == "__main__":
    success, message = check_c_exec_webview_network_code_c007()
    print(
        json.dumps(
            emit_check_result(
                check_c_exec_webview_network_code_c007.__name__, success, message
            )
        )
    )
    sys.exit(0)
