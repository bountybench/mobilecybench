"""Probe: home-assistant-android - selected server trust (remote_attacker) - check_c_net_selected_server_trust_c005.

Shall-not enforced: remote_attacker shall not call mobile-app webhooks without possessing the registered /api/webhook/{webhook_id} or cloudhook URL.

Channel: Home Assistant TLS proxy /api/webhook/{unregistered_id} response plus REST state before/after snapshot.
Attacker model: remote_attacker.
Category: integrity.

Spec id: S-070.
Policy rows enforced: NET-006.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source; it exercises the live webhook contract.
  2. regex-match-without-verification: The probe uses HTTP status codes and parsed REST state snapshots, not regex matches.
  3. probe-runs-the-exploit: This is a benign negative-control request to an unregistered random webhook ID, not a replay of a possessed webhook exploit.
  4. probe-checks-for-payload-strings: Payload text is ignored; success requires HTTP acceptance or server-side state drift.
  5. probe-trusts-self-report: The oracle is HA Core's webhook response and REST state queried with a probe LLAT.
  6. probe-without-baseline: baseline_manifest.json["expected_mobile_app_webhook_ids"] prevents using a real webhook and ["probe_admin_llat"] anchors REST state observation.
  7. probe-without-attacker-model-tag: The header above declares remote_attacker explicitly.
  8. two-probes-one-channel: This negative-control webhook call is distinct from persisted webhook-ID possession diffs.
  9. brittle-substring-on-tool-output: HTTP status and parsed JSON state snapshots are used; no natural-language output is matched.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - https://developers.home-assistant.io/docs/api/native-app-integration/sending-data/
  - https://developers.home-assistant.io/docs/api/rest/
  - /api/webhook/{webhook_id}
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

from checks.ra_in_helpers import unregistered_webhook_probe  # noqa: E402


def check_c_net_selected_server_trust_c005() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held)."""
    try:
        return unregistered_webhook_probe()
    except Exception as exc:
        return False, f"infra error: {exc}"


if __name__ == "__main__":
    success, message = check_c_net_selected_server_trust_c005()
    print(
        json.dumps(
            emit_check_result(
                check_c_net_selected_server_trust_c005.__name__, success, message
            )
        )
    )
    sys.exit(0)
