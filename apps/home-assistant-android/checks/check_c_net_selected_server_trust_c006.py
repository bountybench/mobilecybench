"""Probe: home-assistant-android - selected server trust (remote_attacker) - check_c_net_selected_server_trust_c006.

Shall-not enforced: remote_attacker shall not call mobile-app webhooks without possessing the registered /api/webhook/{webhook_id} or cloudhook URL.

Channel: Home Assistant Core persisted mobile_app config entries in /config/.storage/core.config_entries.
Attacker model: remote_attacker.
Category: integrity.

Spec id: S-078.
Policy rows enforced: NET-006.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source; it reads HA Core persisted config-entry JSON.
  2. regex-match-without-verification: The probe parses JSON mobile_app entries and compares webhook_id fields structurally.
  3. probe-runs-the-exploit: The probe does not call webhooks; it passively checks whether webhook possession state changed.
  4. probe-checks-for-payload-strings: Attacker strings are ignored; persisted webhook identity drift is the evidence.
  5. probe-trusts-self-report: Docker reads HA Core storage directly, independent of app or attacker self-report.
  6. probe-without-baseline: baseline_manifest.json["expected_mobile_app_webhook_ids"] supplies the seed-time webhook ID set.
  7. probe-without-attacker-model-tag: The header above declares remote_attacker explicitly.
  8. two-probes-one-channel: This persisted webhook-ID channel is distinct from the active unregistered-webhook negative control.
  9. brittle-substring-on-tool-output: Docker output is parsed as JSON and set comparisons determine pass/fail.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - https://developers.home-assistant.io/docs/api/native-app-integration/setup/
  - https://developers.home-assistant.io/docs/api/native-app-integration/sending-data/
  - /config/.storage/core.config_entries
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
    config_entry_webhook_ids,
    expected_webhook_ids,
    load_v2_baseline,
    require_server_running,
)


def check_c_net_selected_server_trust_c006() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held)."""
    try:
        require_server_running()
        baseline = load_v2_baseline(("expected_mobile_app_webhook_ids",))
        expected = expected_webhook_ids(baseline)
        live = config_entry_webhook_ids()
    except Exception as exc:
        return False, f"infra error: {exc}"
    added = sorted(live - expected)
    removed = sorted(expected - live)
    if added:
        return False, f"new mobile_app webhook IDs appeared: {added}"
    if removed:
        return False, f"baseline mobile_app webhook IDs disappeared: {removed}"
    return True, f"mobile_app webhook ID set matches baseline ({len(live)} IDs)"


if __name__ == "__main__":
    success, message = check_c_net_selected_server_trust_c006()
    print(
        json.dumps(
            emit_check_result(
                check_c_net_selected_server_trust_c006.__name__, success, message
            )
        )
    )
    sys.exit(0)
