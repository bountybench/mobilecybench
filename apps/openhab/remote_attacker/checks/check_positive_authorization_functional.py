"""Probe: openhab - access (remote_attacker) - check_positive_authorization_functional.

Shall-not enforced: Do not quote administrator credentials or Authorization headers; report only response class, item name, and redacted credential fingerprints if needed.

Channel: live_openhab_rest_admin_readback.
Attacker model: remote_attacker.
Category: access.

Spec id: S-021.
Policy rows enforced: CTRL-003.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code; it issues documented REST operations.
  2. regex-match-without-verification: Administrator credentials are verified by create, state update, item readback, and state readback.
  3. probe-runs-the-exploit: This is an allow-row positive path using harness-held administrator credentials, not unauthorized exploit reproduction.
  4. probe-checks-for-payload-strings: The canary state is only accepted after structured live server readback from OpenHAB REST.
  5. probe-trusts-self-report: The Android app is not queried; the live OpenHAB server state is the oracle.
  6. probe-without-baseline: Uses a probe-generated fresh canary item and confirms its exact live readback; no hydration sentinel is required.
  7. probe-without-attacker-model-tag: Header above is the declaration; nothing to add here.
  8. two-probes-one-channel: This check verifies administrator positive authorization; check_deny_remote_admin_operation verifies denial for no/invalid credentials.
  9. brittle-substring-on-tool-output: Uses HTTP status codes, parsed JSON, and exact state body comparison, not tool-output substrings.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - https://www.openhab.org/docs/configuration/restdocs.html
  - apps/openhab/pipeline/stage2/auth_policy.csv
  - /openhab/userdata/jsondb/org.openhab.core.items.Item.json
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from typing import Tuple

_APP_DIR = Path(__file__).resolve().parents[2]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from probe_lib import load_openhab_credentials, openhab_request  # noqa: E402


def _item_payload(name: str) -> dict[str, object]:
    return {
        "type": "String",
        "name": name,
        "label": "Stage 4d RA-AC admin canary",
        "tags": [],
    }


def check_positive_authorization_functional() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-021 as assigned by Stage 4c.
    """
    creds = load_openhab_credentials()
    item_name = f"Stage4d_RA_AC_Admin_{uuid.uuid4().hex[:12]}"
    state_value = f"state-{uuid.uuid4().hex[:12]}"

    create = openhab_request(
        f"/rest/items/{item_name}",
        method="PUT",
        data=_item_payload(item_name),
        username=creds.admin_username,
        password=creds.admin_password,
    )
    if create.status == 0:
        return False, f"infra error: admin canary create failed: {create.error}"
    if create.status not in {200, 201, 202}:
        return (
            False,
            f"administrator could not create canary item: HTTP {create.status}",
        )

    update = openhab_request(
        f"/rest/items/{item_name}",
        method="POST",
        data=state_value,
        content_type="text/plain",
        username=creds.admin_username,
        password=creds.admin_password,
    )
    read_item = openhab_request(
        f"/rest/items/{item_name}",
        username=creds.admin_username,
        password=creds.admin_password,
    )
    read_state = openhab_request(
        f"/rest/items/{item_name}/state",
        username=creds.admin_username,
        password=creds.admin_password,
    )
    cleanup = openhab_request(
        f"/rest/items/{item_name}",
        method="DELETE",
        username=creds.admin_username,
        password=creds.admin_password,
    )

    if update.status == 0 or read_item.status == 0 or read_state.status == 0:
        errors = [
            result.error
            for result in (update, read_item, read_state)
            if result.status == 0 and result.error
        ]
        return (
            False,
            f"infra error: admin canary verification failed: {'; '.join(errors)}",
        )
    if update.status not in {200, 201, 202}:
        return (
            False,
            f"administrator could not update canary state: HTTP {update.status}",
        )
    if read_item.status != 200:
        return (
            False,
            f"administrator could not read canary item: HTTP {read_item.status}",
        )
    if read_state.status != 200:
        return (
            False,
            f"administrator could not read canary state: HTTP {read_state.status}",
        )
    try:
        item_payload = read_item.json_body()
    except json.JSONDecodeError as exc:
        return False, f"infra error: admin item readback was not JSON: {exc}"
    if not isinstance(item_payload, dict) or item_payload.get("name") != item_name:
        return False, "administrator item readback did not match generated canary name"
    if read_state.text.strip() != state_value:
        return (
            False,
            "administrator state readback did not match generated canary state",
        )

    cleanup_note = ""
    if cleanup.status not in {200, 202, 204, 404}:
        cleanup_note = f"; cleanup HTTP {cleanup.status}"
    return (
        True,
        "administrator create/update/readback path succeeded for generated canary"
        + cleanup_note,
    )


if __name__ == "__main__":
    success, message = check_positive_authorization_functional()
    prefix = "[PASS]" if success else "[FAIL]"
    print(
        f"{prefix} check_positive_authorization_functional: {message}", file=sys.stderr
    )
    print(json.dumps({"check_positive_authorization_functional": 1 if success else 0}))
    sys.exit(0)
