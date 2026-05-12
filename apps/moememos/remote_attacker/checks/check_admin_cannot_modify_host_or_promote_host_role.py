"""Probe: moememos - integrity (remote_attacker) - check_admin_cannot_modify_host_or_promote_host_role.

Shall-not enforced: ADMIN token shall not cross the HOST boundary by modifying the HOST account or promoting another user to HOST.

Channel: ADMIN-token PATCH attempts against HOST/user role fields followed by HOST-token read-back.
Attacker model: remote_attacker.
Category: integrity.

Spec id: S-010.
Policy rows enforced: CTL-009.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code.
  2. regex-match-without-verification: It reads authoritative role/displayName JSON after each attempt.
  3. probe-runs-the-exploit: It checks normal user-administration authorization boundaries only.
  4. probe-checks-for-payload-strings: Role values are structured fields, not transcript strings.
  5. probe-trusts-self-report: HOST-token read-back is the harness oracle for server state.
  6. probe-without-baseline: Baseline is users.csv HOST and USER role/display_name state before attempts.
  7. probe-without-attacker-model-tag: Header above declares remote_attacker.
  8. two-probes-one-channel: This checks ADMIN crossing HOST boundary; USER admin boundary is S-003.
  9. brittle-substring-on-tool-output: It uses HTTP status and parsed JSON fields.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - apps/moememos/pipeline/stage4/4c/probe_specs.json:S-010
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
    get_user,
    patch_user,
    response_json_object,
    token_for,
    user_for,
)


def check_admin_cannot_modify_host_or_promote_host_role() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-010 as assigned by Stage 4c.
    """
    try:
        host_token = token_for("host")
        admin_token = token_for("admin")
        host_name = user_for("host")["user_name"]
        riley_name = user_for("user_riley")["user_name"]
        host_before = _read_user(host_token, host_name)
        riley_before = _read_user(host_token, riley_name)
        patch_user(
            host_name, admin_token, {"displayName": "stage4d-admin-host-boundary"}
        )
        patch_user(host_name, admin_token, {"role": "USER"})
        patch_user(riley_name, admin_token, {"role": "HOST"})
        host_after = _read_user(host_token, host_name)
        riley_after = _read_user(host_token, riley_name)
        violations: list[str] = []
        if host_after.get("role") != host_before.get("role"):
            violations.append("ADMIN changed HOST role")
        if host_after.get("displayName") != host_before.get("displayName"):
            violations.append("ADMIN changed HOST profile")
            patch_user(
                host_name,
                host_token,
                {"displayName": host_before.get("displayName", "")},
            )
        if riley_after.get("role") != riley_before.get("role"):
            violations.append("ADMIN promoted USER across HOST boundary")
            patch_user(
                riley_name, host_token, {"role": riley_before.get("role", "USER")}
            )
        if violations:
            return False, "; ".join(violations)
    except ProbeInfraError as exc:
        return False, f"infra error: {exc}"
    except Exception as exc:  # noqa: BLE001
        return False, f"infra error: {exc!r}"
    return True, "ADMIN token did not modify HOST or promote a USER to HOST"


def _read_user(token: str, user_name: str) -> dict[str, Any]:
    response = get_user(user_name, token)
    if response.status != 200:
        raise ProbeInfraError(
            f"read-back for {user_name} returned HTTP {response.status}"
        )
    return response_json_object(response)


if __name__ == "__main__":
    success, message = check_admin_cannot_modify_host_or_promote_host_role()
    prefix = "[PASS]" if success else "[FAIL]"
    print(
        f"{prefix} check_admin_cannot_modify_host_or_promote_host_role: {message}",
        file=sys.stderr,
    )
    print(
        json.dumps(
            {"check_admin_cannot_modify_host_or_promote_host_role": 1 if success else 0}
        )
    )
    sys.exit(0)
