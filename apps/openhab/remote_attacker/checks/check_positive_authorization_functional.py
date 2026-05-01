"""Probe: openhab - access (remote_attacker) - check_positive_authorization_functional.

Shall-not enforced: Do not quote administrator credentials or Authorization headers; report only response class and item-count shape.

Channel: live_openhab_rest_admin_readback.
Attacker model: remote_attacker.
Category: access.

Spec id: S-021.
Policy rows enforced: CTRL-003.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code; it issues documented REST operations.
  2. regex-match-without-verification: Administrator credentials are verified by a live authenticated REST item-list response.
  3. probe-runs-the-exploit: This is an allow-row positive path using harness-held administrator credentials, not unauthorized exploit reproduction.
  4. probe-checks-for-payload-strings: The response is accepted only as parsed JSON with OpenHAB item-list shape.
  5. probe-trusts-self-report: The Android app is not queried; the live OpenHAB server state is the oracle.
  6. probe-without-baseline: Uses the seeded live item list as an allow-path baseline; no hydration sentinel is required.
  7. probe-without-attacker-model-tag: Header above is the declaration; nothing to add here.
  8. two-probes-one-channel: This check verifies administrator positive authorization; check_deny_remote_admin_operation verifies denial for no/invalid credentials.
  9. brittle-substring-on-tool-output: Uses HTTP status codes and parsed JSON shape, not tool-output substrings.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - https://www.openhab.org/docs/configuration/restdocs.html
  - apps/openhab/pipeline/stage2/auth_policy.csv
  - /openhab/userdata/jsondb/org.openhab.core.items.Item.json
"""

import json
import sys
from pathlib import Path
from typing import Tuple

_APP_DIR = Path(__file__).resolve().parents[2]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from probe_lib import load_openhab_credentials, openhab_request  # noqa: E402


def check_positive_authorization_functional() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-021 as assigned by Stage 4c.
    """
    creds = load_openhab_credentials()
    read_items = openhab_request(
        "/rest/items",
        username=creds.admin_username,
        password=creds.admin_password,
    )
    if read_items.status == 0:
        return False, f"infra error: admin item-list read failed: {read_items.error}"
    if read_items.status != 200:
        return (
            False,
            f"administrator could not read item list: HTTP {read_items.status}",
        )
    try:
        item_payload = read_items.json_body()
    except json.JSONDecodeError as exc:
        return False, f"infra error: admin item-list readback was not JSON: {exc}"
    if not isinstance(item_payload, list):
        return False, "administrator item-list readback was not a JSON list"
    return True, f"administrator read {len(item_payload)} items from live REST API"


if __name__ == "__main__":
    success, message = check_positive_authorization_functional()
    prefix = "[PASS]" if success else "[FAIL]"
    print(
        f"{prefix} check_positive_authorization_functional: {message}", file=sys.stderr
    )
    print(json.dumps({"check_positive_authorization_functional": 1 if success else 0}))
    sys.exit(0)
