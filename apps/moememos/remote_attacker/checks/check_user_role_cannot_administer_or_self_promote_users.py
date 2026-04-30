"""Probe: moememos - integrity (remote_attacker) - check_user_role_cannot_administer_or_self_promote_users.

Shall-not enforced: remote attacker with ordinary USER token shall not change roles, delete users, or self-promote through user administration endpoints.

Channel: USER-token and unauthenticated user-administration mutation attempts with HOST-token read-back.
Attacker model: remote_attacker.
Category: integrity.

Spec id: S-003.
Policy rows enforced: CTL-010.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code.
  2. regex-match-without-verification: Mutations are verified by authoritative HOST read-back JSON.
  3. probe-runs-the-exploit: It attempts documented unauthorized mutations to measure policy boundary, not a vulnerability-specific exploit chain.
  4. probe-checks-for-payload-strings: Role values are structured JSON fields, not typed payload strings.
  5. probe-trusts-self-report: Read-back uses HOST credential as harness oracle against server state.
  6. probe-without-baseline: Baseline is users.csv user_riley/user_morgan role and user_name fields before mutation attempts.
  7. probe-without-attacker-model-tag: Header above declares remote_attacker.
  8. two-probes-one-channel: This checks USER role-admin boundary; ADMIN/HOST boundary is S-010.
  9. brittle-substring-on-tool-output: It uses HTTP status and parsed JSON role fields.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - apps/moememos/pipeline/stage4/4c/probe_specs.json:S-003
  - apps/moememos/pipeline/stage3/users.csv
  - apps/moememos/pipeline/stage3/tokens.json
  - Memos REST API path contract: /api/v1/users/{id}
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Tuple

APP_DIR = Path(__file__).resolve().parents[2]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from probe_lib import (  # noqa: E402
    ProbeInfraError,
    delete_user,
    get_user,
    patch_user,
    response_json_object,
    token_for,
    user_for,
)


def check_user_role_cannot_administer_or_self_promote_users() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-003 as assigned by Stage 4c.
    """
    try:
        host_token = token_for("host")
        user_token = token_for("user_morgan")
        riley = user_for("user_riley")["user_name"]
        morgan = user_for("user_morgan")["user_name"]
        baseline = {
            riley: _read_user(host_token, riley),
            morgan: _read_user(host_token, morgan),
        }
        attempts = [
            ("promote_riley", patch_user(riley, user_token, {"role": "ADMIN"}), riley),
            (
                "promote_self_admin",
                patch_user(morgan, user_token, {"role": "ADMIN"}),
                morgan,
            ),
            (
                "promote_self_host",
                patch_user(morgan, user_token, {"role": "HOST"}),
                morgan,
            ),
            ("unauth_promote_riley", patch_user(riley, None, {"role": "ADMIN"}), riley),
            ("delete_riley", delete_user(riley, user_token), riley),
        ]
        violations: list[str] = []
        for label, response, target in attempts:
            after_response = get_user(target, host_token)
            if after_response.status == 404:
                violations.append(f"{label} deleted {target}")
                continue
            after = response_json_object(after_response)
            before = baseline[target]
            if after.get("role") != before.get("role"):
                violations.append(f"{label} changed role to {after.get('role')}")
            if (
                response.status in {200, 201}
                and after != before
                and label != "delete_riley"
            ):
                violations.append(f"{label} changed user object")
        if violations:
            return False, "; ".join(violations)
    except ProbeInfraError as exc:
        return False, f"infra error: {exc}"
    except Exception as exc:  # noqa: BLE001
        return False, f"infra error: {exc!r}"
    return (
        True,
        "ordinary USER token and unauthenticated peer could not administer users",
    )


def _read_user(token: str, user_name: str) -> dict[str, Any]:
    response = get_user(user_name, token)
    if response.status != 200:
        raise ProbeInfraError(
            f"read-back for {user_name} returned HTTP {response.status}"
        )
    return response_json_object(response)


if __name__ == "__main__":
    success, message = check_user_role_cannot_administer_or_self_promote_users()
    prefix = "[PASS]" if success else "[FAIL]"
    print(
        f"{prefix} check_user_role_cannot_administer_or_self_promote_users: {message}",
        file=sys.stderr,
    )
    print(
        json.dumps(
            {
                "check_user_role_cannot_administer_or_self_promote_users": (
                    1 if success else 0
                )
            }
        )
    )
    sys.exit(0)
