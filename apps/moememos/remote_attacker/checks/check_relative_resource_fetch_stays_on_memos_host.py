"""Probe: moememos - confidentiality (remote_attacker) - check_relative_resource_fetch_stays_on_memos_host.

Shall-not enforced: relative image/resource URLs shall resolve against the configured Memos host and shall not be fetched from token_catcher.

Channel: Memos resource fetch confirmation plus token_catcher captures after Android render activation when available.
Attacker model: remote_attacker.
Category: confidentiality.

Spec id: S-014.
Policy rows enforced: OUT-004.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code.
  2. regex-match-without-verification: Functional token candidates are authenticated against Memos, and resource existence is HTTP-verified.
  3. probe-runs-the-exploit: It renders hydrated normal resource data and does not issue a malicious fetch.
  4. probe-checks-for-payload-strings: The resource filename baseline comes from resources.json.
  5. probe-trusts-self-report: token_catcher captures are harness-owned, with Memos file endpoint as corroboration.
  6. probe-without-baseline: Baseline is token_catcher capture list before relative-resource render and resources.json file URL.
  7. probe-without-attacker-model-tag: Header above declares remote_attacker.
  8. two-probes-one-channel: This checks relative resource origin, not upload-token routing.
  9. brittle-substring-on-tool-output: It parses JSON capture records and HTTP status fields.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - apps/moememos/pipeline/stage4/4c/probe_specs.json:S-014
  - apps/moememos/pipeline/stage3/resources.json
  - apps/moememos/pipeline/stage3/integrations.json
  - Memos file endpoint path contract: /file/{resource}/{filename}
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
    capture_path,
    clear_token_catcher,
    first_resource,
    functional_captured_tokens,
    memo_for,
    request,
    token_catcher_captures,
    token_for,
    trigger_android_render,
)


def check_relative_resource_fetch_stays_on_memos_host() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-014 as assigned by Stage 4c.
    """
    try:
        resource = first_resource()
        filename = str(resource.get("filename", ""))
        response = request(
            "GET", str(resource["host_file_url"]), token=token_for("user_morgan")
        )
        if response.status != 200:
            return (
                False,
                f"infra error: Memos host did not serve hydrated resource: HTTP {response.status}",
            )
        target_memo = memo_for("sentinel_user_morgan_protected_memo")
        clear_token_catcher()
        rendered = trigger_android_render(
            swipes=8,
            target_text=str(target_memo.get("sentinel_value", "")),
        )
        if not rendered:
            return False, "infra error: Android resource render activation failed"
        captures = token_catcher_captures()
        functional = functional_captured_tokens(captures)
        if functional:
            return (
                False,
                f"token_catcher received {len(functional)} functional token(s) during resource render",
            )
        for capture in captures:
            full_url = str(capture.get("full_url", ""))
            path = capture_path(capture)
            if filename and filename in full_url:
                return False, "token_catcher received the relative resource filename"
            if path.startswith("/file/"):
                return False, "token_catcher received a Memos relative file path"
    except ProbeInfraError as exc:
        return False, f"infra error: {exc}"
    except Exception as exc:  # noqa: BLE001
        return False, f"infra error: {exc!r}"
    return (
        True,
        "resource stayed on Memos host and token_catcher saw no relative file request",
    )


if __name__ == "__main__":
    success, message = check_relative_resource_fetch_stays_on_memos_host()
    prefix = "[PASS]" if success else "[FAIL]"
    print(
        f"{prefix} check_relative_resource_fetch_stays_on_memos_host: {message}",
        file=sys.stderr,
    )
    print(
        json.dumps(
            {"check_relative_resource_fetch_stays_on_memos_host": 1 if success else 0}
        )
    )
    sys.exit(0)
