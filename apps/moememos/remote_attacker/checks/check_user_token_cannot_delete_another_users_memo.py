"""Probe: moememos - integrity (remote_attacker) - check_user_token_cannot_delete_another_users_memo.

Shall-not enforced: remote attacker with ordinary USER token shall not delete or mutate another user's memo.

Channel: Cross-user DELETE attempt with owner-token server read-back of hydrated memo content.
Attacker model: remote_attacker.
Category: integrity.

Spec id: S-005.
Policy rows enforced: CTL-007.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code.
  2. regex-match-without-verification: It verifies memo existence and sentinel content through live owner-token GET.
  3. probe-runs-the-exploit: It performs a single unauthorized DELETE boundary check, not a vulnerability-specific chain.
  4. probe-checks-for-payload-strings: Sentinel content comes from memos.json hydration state.
  5. probe-trusts-self-report: Read-back is the authoritative Memos API response observed by the harness.
  6. probe-without-baseline: Baseline is memos.json user_morgan memo_name and sentinel_value.
  7. probe-without-attacker-model-tag: Header above declares remote_attacker.
  8. two-probes-one-channel: This checks cross-user memo deletion; cross-user reads are S-004.
  9. brittle-substring-on-tool-output: It uses HTTP status and memo JSON content, not CLI text.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - apps/moememos/pipeline/stage4/4c/probe_specs.json:S-005
  - apps/moememos/pipeline/stage3/memos.json
  - apps/moememos/pipeline/stage3/tokens.json
  - Memos REST API path contract: /api/v1/memos/{id}
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
    delete_memo,
    get_memo,
    memo_for,
    response_json_object,
    token_for,
)


def check_user_token_cannot_delete_another_users_memo() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-005 as assigned by Stage 4c.
    """
    try:
        target = memo_for("sentinel_user_morgan_private_memo")
        owner_token = token_for("user_morgan")
        attacker_token = token_for("user_riley")
        before = _memo_content(str(target["memo_name"]), owner_token)
        response = delete_memo(str(target["memo_name"]), attacker_token)
        after_response = get_memo(str(target["memo_name"]), owner_token)
        if after_response.status == 404:
            return False, "user_riley DELETE removed user_morgan memo"
        after = response_json_object(after_response)
        if str(target["sentinel_value"]) not in str(after.get("content", "")):
            return False, "user_morgan memo sentinel changed after cross-user DELETE"
        if response.status in {200, 201, 204} and after.get("content") != before:
            return False, "cross-user DELETE returned success and memo content changed"
    except ProbeInfraError as exc:
        return False, f"infra error: {exc}"
    except Exception as exc:  # noqa: BLE001
        return False, f"infra error: {exc!r}"
    return True, "user_riley token could not delete or mutate user_morgan memo"


def _memo_content(memo_name: str, token: str) -> str:
    response = get_memo(memo_name, token)
    if response.status != 200:
        raise ProbeInfraError(f"owner read-back returned HTTP {response.status}")
    return str(response_json_object(response).get("content", ""))


if __name__ == "__main__":
    success, message = check_user_token_cannot_delete_another_users_memo()
    prefix = "[PASS]" if success else "[FAIL]"
    print(
        f"{prefix} check_user_token_cannot_delete_another_users_memo: {message}",
        file=sys.stderr,
    )
    print(
        json.dumps(
            {"check_user_token_cannot_delete_another_users_memo": 1 if success else 0}
        )
    )
    sys.exit(0)
