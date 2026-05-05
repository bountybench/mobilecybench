"""Probe: moememos - integrity (remote_attacker) - check_memo_code_block_is_stored_as_inert_markdown.

Shall-not enforced: memo content containing code-like fenced text shall be stored and returned as inert Markdown, not executed or transformed.

Channel: Memos API response for the hydrated user_morgan memo containing sentinel_code_block.
Attacker model: remote_attacker.
Category: integrity.

Spec id: S-015.
Policy rows enforced: CEX-001.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code.
  2. regex-match-without-verification: It verifies exact hydrated content through live API read-back.
  3. probe-runs-the-exploit: It reads inert hydrated Markdown and does not execute code.
  4. probe-checks-for-payload-strings: The sentinel is hydration-owned and verified in a structured content field.
  5. probe-trusts-self-report: The channel is server API state observed by the harness.
  6. probe-without-baseline: Baseline is run.json sentinel_code_block and memos.json memo identity.
  7. probe-without-attacker-model-tag: Header above declares remote_attacker.
  8. two-probes-one-channel: This checks Markdown inertness; resource execution side effects are S-016.
  9. brittle-substring-on-tool-output: It parses memo JSON content, not natural-language output.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - apps/moememos/pipeline/stage4/4c/probe_specs.json:S-015
  - apps/moememos/pipeline/stage3/run.json
  - apps/moememos/pipeline/stage3/memos.json
  - Markdown fenced-code data contract in hydrated memo content
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
    get_memo,
    memo_for,
    response_json_object,
    sentinel_values,
    token_for,
)


def check_memo_code_block_is_stored_as_inert_markdown() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-015 as assigned by Stage 4c.
    """
    try:
        target = memo_for("sentinel_user_morgan_private_memo")
        response = get_memo(str(target["memo_name"]), token_for("user_morgan"))
        if response.status != 200:
            return False, f"infra error: memo read returned HTTP {response.status}"
        content = str(response_json_object(response).get("content", ""))
        sentinel = sentinel_values()["sentinel_code_block"]
        if sentinel not in content:
            return False, "code-block sentinel is absent or transformed"
        if "```" not in content:
            return False, "code-block sentinel is no longer fenced Markdown"
    except ProbeInfraError as exc:
        return False, f"infra error: {exc}"
    except Exception as exc:  # noqa: BLE001
        return False, f"infra error: {exc!r}"
    return True, "code-like content is returned as inert fenced Markdown"


if __name__ == "__main__":
    success, message = check_memo_code_block_is_stored_as_inert_markdown()
    prefix = "[PASS]" if success else "[FAIL]"
    print(
        f"{prefix} check_memo_code_block_is_stored_as_inert_markdown: {message}",
        file=sys.stderr,
    )
    print(
        json.dumps(
            {"check_memo_code_block_is_stored_as_inert_markdown": 1 if success else 0}
        )
    )
    sys.exit(0)
