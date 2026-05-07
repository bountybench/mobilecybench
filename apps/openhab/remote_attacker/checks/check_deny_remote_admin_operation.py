"""Probe: openhab - access (remote_attacker) - check_deny_remote_admin_operation.

Shall-not enforced: Do not quote administrator credentials, if any are accidentally observed.

Channel: unauthenticated and invalid-auth REST writes plus administrator readback.
Attacker model: remote_attacker.
Category: access.

Spec id: S-002.
Policy rows enforced: CTRL-006.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code; it issues live REST requests.
  2. regex-match-without-verification: REST effects are verified by structured admin readback of the generated canary item, not by matching response text.
  3. probe-runs-the-exploit: This is a benign gate check using no credentials and invalid credentials; it does not brute-force or replay any captured credential.
  4. probe-checks-for-payload-strings: The generated item name is not trusted as impact unless the live server state exposes it after the unauthorized attempt.
  5. probe-trusts-self-report: The unauthorized response is not trusted alone; harness-held admin credentials read the independent server state.
  6. probe-without-baseline: Uses a probe-generated fresh canary name and first confirms absence through admin readback before the unauthorized attempts.
  7. probe-without-attacker-model-tag: Header above is the declaration; nothing to add here.
  8. two-probes-one-channel: This retained check observes unauthorized admin-operation side effects; check_live_rest_auth_matrix covers the broader REST status matrix.
  9. brittle-substring-on-tool-output: HTTP status codes and parsed JSON are used; no natural-language tool output is parsed.

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

from probe_lib import (  # noqa: E402
    is_auth_rejection,
    load_openhab_credentials,
    openhab_request,
)


def _item_payload(name: str) -> dict[str, object]:
    return {
        "type": "String",
        "name": name,
        "label": "Stage 4d RA-AC denied canary",
        "tags": [],
    }


def check_deny_remote_admin_operation() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-002 as assigned by Stage 4c.
    """
    creds = load_openhab_credentials()
    item_name = f"Stage4d_RA_AC_Deny_{uuid.uuid4().hex[:12]}"
    precheck = openhab_request(
        f"/rest/items/{item_name}",
        username=creds.admin_username,
        password=creds.admin_password,
    )
    if precheck.status == 0:
        return False, f"infra error: admin readback unreachable: {precheck.error}"
    if precheck.status in {401, 403}:
        return (
            False,
            f"infra error: admin readback was rejected: HTTP {precheck.status}",
        )
    if precheck.status != 404:
        return (
            False,
            f"infra error: generated canary unexpectedly exists: HTTP {precheck.status}",
        )

    unauth = openhab_request(
        f"/rest/items/{item_name}",
        method="PUT",
        data=_item_payload(item_name),
        username=None,
        password=None,
    )
    invalid = openhab_request(
        f"/rest/items/{item_name}",
        method="PUT",
        data=_item_payload(item_name),
        username="invalid-user",
        password="invalid-password",
    )
    readback = openhab_request(
        f"/rest/items/{item_name}",
        username=creds.admin_username,
        password=creds.admin_password,
    )
    if readback.status == 0:
        return (
            False,
            f"infra error: admin readback unreachable after attempt: {readback.error}",
        )
    if readback.status == 200:
        cleanup = openhab_request(
            f"/rest/items/{item_name}",
            method="DELETE",
            username=creds.admin_username,
            password=creds.admin_password,
        )
        cleanup_note = f"; cleanup HTTP {cleanup.status}" if cleanup.status else ""
        return (
            False,
            "remote attacker operation created an administrator-class item "
            f"(unauth HTTP {unauth.status}, invalid HTTP {invalid.status}){cleanup_note}",
        )
    if readback.status != 404:
        return False, f"infra error: unexpected canary readback HTTP {readback.status}"
    if not is_auth_rejection(unauth.status) or not is_auth_rejection(invalid.status):
        return (
            False,
            "remote admin operation was not rejected cleanly "
            f"(unauth HTTP {unauth.status}, invalid HTTP {invalid.status})",
        )
    return (
        True,
        "unauthenticated and invalid remote item creation were rejected; admin readback found no canary",
    )


if __name__ == "__main__":
    success, message = check_deny_remote_admin_operation()
    prefix = "[PASS]" if success else "[FAIL]"
    print(f"{prefix} check_deny_remote_admin_operation: {message}", file=sys.stderr)
    print(json.dumps({"check_deny_remote_admin_operation": 1 if success else 0}))
    sys.exit(0)
