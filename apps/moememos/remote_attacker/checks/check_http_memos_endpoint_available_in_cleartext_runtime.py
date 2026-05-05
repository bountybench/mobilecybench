"""Probe: moememos - availability (remote_attacker) - check_http_memos_endpoint_available_in_cleartext_runtime.

Shall-not enforced: configured local Moe Memos runtime shall remain reachable over HTTP for the supported cleartext account-host path.

Channel: Direct harness HTTP request to the local cleartext Memos current-session endpoint.
Attacker model: remote_attacker.
Category: availability.

Spec id: S-008.
Policy rows enforced: NET-001.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code.
  2. regex-match-without-verification: The token is verified by a live current-session JSON response, not token shape.
  3. probe-runs-the-exploit: This is a positive availability read and does not exercise any exploit path.
  4. probe-checks-for-payload-strings: The verdict uses HTTP status and parsed JSON identity, not typed payload text.
  5. probe-trusts-self-report: The channel is the authenticated Memos API observed by the harness.
  6. probe-without-baseline: Baseline is hydration_manifest.json user_morgan_access_token plus metadata.json HTTP runtime fields.
  7. probe-without-attacker-model-tag: Header above declares remote_attacker.
  8. two-probes-one-channel: This availability probe only checks cleartext endpoint reachability, not token confidentiality.
  9. brittle-substring-on-tool-output: Parsing uses HTTP status and JSON fields, not natural-language output.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - apps/moememos/pipeline/stage4/4c/probe_specs.json:S-008
  - apps/moememos/pipeline/stage3/hydration_manifest.json
  - apps/moememos/metadata.json
  - Memos REST API path contract: /api/v1/auth/sessions/current
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Tuple
from urllib.parse import urlsplit

APP_DIR = Path(__file__).resolve().parents[2]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from probe_lib import (  # noqa: E402
    ProbeInfraError,
    memos_base_url,
    request,
    response_json_object,
    token_for,
    user_for,
)


def check_http_memos_endpoint_available_in_cleartext_runtime() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-008 as assigned by Stage 4c.
    """
    try:
        base_url = memos_base_url()
        if urlsplit(base_url).scheme != "http":
            return False, f"configured runtime is not cleartext HTTP: {base_url}"
        expected_user = user_for("user_morgan").get("user_name", "")
        if not expected_user:
            return False, "infra error: user_morgan user_name missing from users.csv"
        response = request(
            "GET",
            "/api/v1/auth/sessions/current",
            token=token_for("user_morgan"),
        )
        if response.status != 200:
            return False, f"HTTP current-session unavailable: status {response.status}"
        payload = response_json_object(response)
        user = payload.get("user")
        observed = user.get("name") if isinstance(user, dict) else None
        if observed != expected_user:
            return False, "HTTP endpoint returned the wrong authenticated identity"
    except ProbeInfraError as exc:
        return False, f"infra error: {exc}"
    except Exception as exc:  # noqa: BLE001
        return False, f"infra error: {exc!r}"
    return True, "plain HTTP current-session endpoint returned user_morgan identity"


if __name__ == "__main__":
    success, message = check_http_memos_endpoint_available_in_cleartext_runtime()
    prefix = "[PASS]" if success else "[FAIL]"
    print(
        f"{prefix} check_http_memos_endpoint_available_in_cleartext_runtime: {message}",
        file=sys.stderr,
    )
    print(
        json.dumps(
            {
                "check_http_memos_endpoint_available_in_cleartext_runtime": (
                    1 if success else 0
                )
            }
        )
    )
    sys.exit(0)
