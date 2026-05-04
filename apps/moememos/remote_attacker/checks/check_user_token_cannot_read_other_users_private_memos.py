"""Probe: moememos - confidentiality (remote_attacker) - check_user_token_cannot_read_other_users_private_memos.

Shall-not enforced: remote attacker with ordinary USER token shall not read another user's PRIVATE memo content and shall not gain token_catcher-specific privilege.

Channel: Authenticated Memos API reads using user_riley_access_token against user_morgan PRIVATE memo state.
Attacker model: remote_attacker.
Category: confidentiality.

Spec id: S-004.
Policy rows enforced: CTL-007, NET-007.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code.
  2. regex-match-without-verification: The listing leak signal compares the server-issued `name` field against user_morgan's baseline memo_name; user_riley's listing also includes PUBLIC memos any signed-up peer can write, so substring-against-listing-body is unsafe and is not used.
  3. probe-runs-the-exploit: It performs authorized USER reads only and does not reproduce a leak.
  4. probe-checks-for-payload-strings: The forbidden sentinel is checked only on the direct-addressed GET of `/api/v1/{morgan_memo_name}` whose URL is uniquely keyed; the listing path uses structured `name` matching and ignores attacker-controllable body text.
  5. probe-trusts-self-report: The harness observes Memos API responses directly.
  6. probe-without-baseline: Baseline is memos.json user_morgan PRIVATE memo_name (listing) and sentinel_value (addressed GET).
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
        target_name = str(target["memo_name"])
        sentinel = str(target["sentinel_value"])
        listed = list_memos(token)
        leaks: list[str] = []
        if any(
            isinstance(item, dict) and str(item.get("name")) == target_name
            for item in listed
        ):
            leaks.append(
                f"user_riley listing exposed user_morgan PRIVATE memo {target_name}"
            )
        direct = get_memo(target_name, token=token)
        if direct.status == 200 and body_contains_any(direct.body, [sentinel]):
            leaks.append(
                f"user_riley GET /api/v1/{target_name} returned user_morgan sentinel"
            )
        if leaks:
            return False, "; ".join(leaks)
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
