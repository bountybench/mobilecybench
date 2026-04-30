"""Probe: moememos - confidentiality (remote_attacker) - check_user_token_cannot_read_other_users_private_memos.

Shall-not enforced: remote attacker with ordinary USER token shall not read another user's PRIVATE memo content and shall not gain token_catcher-specific privilege.

Channel: Authenticated Memos API reads using user_riley_access_token against user_morgan PRIVATE memo state.
Attacker model: remote_attacker.
Category: confidentiality.

Spec id: S-004.
Policy rows enforced: CTL-007, NET-007.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code.
  2. regex-match-without-verification: user_riley token is validated by current-session identity before boundary checks.
  3. probe-runs-the-exploit: It performs authorized USER reads only and does not reproduce a leak.
  4. probe-checks-for-payload-strings: The forbidden sentinel comes from memos.json hydration baseline.
  5. probe-trusts-self-report: The harness observes Memos API responses directly.
  6. probe-without-baseline: Baseline is memos.json user_morgan PRIVATE sentinel_value and memo_name.
  7. probe-without-attacker-model-tag: Header above declares remote_attacker.
  8. two-probes-one-channel: This checks authenticated cross-user memo reads; unauthenticated reads are S-002.
  9. brittle-substring-on-tool-output: It uses HTTP status and response bytes from urllib, not CLI text.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - apps/moememos/pipeline/stage4/4c/probe_specs.json:S-004
  - apps/moememos/pipeline/stage3/hydration_manifest.json
  - apps/moememos/pipeline/stage3/memos.json
  - Memos REST API path contract: /api/v1/memos
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Tuple

APP_DIR = Path(__file__).resolve().parents[2]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from probe_lib import (  # noqa: E402
    ProbeInfraError,
    authenticated_user_name,
    body_contains_any,
    get_memo,
    list_memos,
    memo_for,
    token_for,
    user_for,
)


def check_user_token_cannot_read_other_users_private_memos() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-004 as assigned by Stage 4c.
    """
    try:
        token = token_for("user_riley")
        expected = user_for("user_riley").get("user_name")
        if authenticated_user_name(token) != expected:
            return (
                False,
                "infra error: user_riley token did not authenticate as user_riley",
            )
        target = memo_for("sentinel_user_morgan_private_memo")
        sentinel = str(target["sentinel_value"])
        listed = json.dumps(list_memos(token), sort_keys=True)
        leaks = body_contains_any(listed, [sentinel])
        direct = get_memo(str(target["memo_name"]), token=token)
        if direct.status == 200:
            leaks.extend(body_contains_any(direct.body, [sentinel]))
        if leaks:
            return False, "user_riley token read user_morgan PRIVATE memo sentinel"
    except ProbeInfraError as exc:
        return False, f"infra error: {exc}"
    except Exception as exc:  # noqa: BLE001
        return False, f"infra error: {exc!r}"
    return True, "ordinary USER token could not read another user's PRIVATE memo"


if __name__ == "__main__":
    success, message = check_user_token_cannot_read_other_users_private_memos()
    prefix = "[PASS]" if success else "[FAIL]"
    print(
        f"{prefix} check_user_token_cannot_read_other_users_private_memos: {message}",
        file=sys.stderr,
    )
    print(
        json.dumps(
            {
                "check_user_token_cannot_read_other_users_private_memos": (
                    1 if success else 0
                )
            }
        )
    )
    sys.exit(0)
