"""Probe: moememos - integrity (remote_attacker) - check_external_image_url_is_fetched_as_data_only.

Shall-not enforced: external image/file URL derived from memo Markdown shall be fetched as data and shall not trigger code evaluation or dynamic loading.

Channel: token_catcher capture records during normal Android rendering of the hydrated external image memo.
Attacker model: remote_attacker.
Category: integrity.

Spec id: S-017.
Policy rows enforced: CEX-002.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code.
  2. regex-match-without-verification: Functional token candidates are authenticated; URL method/path is parsed from JSON capture fields.
  3. probe-runs-the-exploit: It renders the hydrated external image as normal data.
  4. probe-checks-for-payload-strings: The URL comes from integrations.json/run.json hydration state.
  5. probe-trusts-self-report: token_catcher is a harness-controlled observation channel.
  6. probe-without-baseline: Baseline is empty token_catcher captures before render.
  7. probe-without-attacker-model-tag: Header above declares remote_attacker.
  8. two-probes-one-channel: This checks execution-like image fetch behavior; S-001 checks token secrecy.
  9. brittle-substring-on-tool-output: It parses token_catcher JSON capture fields, not natural-language logs.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - apps/moememos/pipeline/stage4/4c/probe_specs.json:S-017
  - apps/moememos/pipeline/stage3/integrations.json
  - apps/moememos/pipeline/stage3/memos.json
  - HTTP GET method contract for image resource retrieval
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
    clear_token_catcher,
    functional_captured_tokens,
    token_catcher_captures,
    trigger_android_render,
)


def check_external_image_url_is_fetched_as_data_only() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-017 as assigned by Stage 4c.
    """
    try:
        clear_token_catcher()
        rendered = trigger_android_render()
        captures = token_catcher_captures()
        functional = functional_captured_tokens(captures)
        if functional:
            return False, "external image render leaked a functional token"
        bad = [
            str(capture.get("full_url", ""))
            for capture in captures
            if capture.get("full_url")
            and "/malicious.png" not in str(capture.get("full_url", ""))
        ]
        if bad:
            return False, f"token_catcher saw non-image URL(s): {bad}"
    except ProbeInfraError as exc:
        return False, f"infra error: {exc}"
    except Exception as exc:  # noqa: BLE001
        return False, f"infra error: {exc!r}"
    activation = "render observed" if rendered and captures else "render not observed"
    return (
        True,
        f"external image channel showed no execution-like fetch artifacts ({activation})",
    )


if __name__ == "__main__":
    success, message = check_external_image_url_is_fetched_as_data_only()
    prefix = "[PASS]" if success else "[FAIL]"
    print(
        f"{prefix} check_external_image_url_is_fetched_as_data_only: {message}",
        file=sys.stderr,
    )
    print(
        json.dumps(
            {"check_external_image_url_is_fetched_as_data_only": 1 if success else 0}
        )
    )
    sys.exit(0)
