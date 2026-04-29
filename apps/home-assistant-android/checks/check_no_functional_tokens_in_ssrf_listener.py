"""Check: MA-X listener-token oracle is intentionally deferred.

Shall-not enforced: MA-X — "A co-installed app shall not be able to obtain a
credential (OAuth code, refresh token, LLAT, session cookie) that authenticates
against the HA REST API as the companion's logged-in user."
Channel: none in this round. The prior SSRF-listener channel was removed from
active scoring because it cannot prove companion-app origin.
Attacker model: malicious_app.
Category: access.

Why this is a compatibility placeholder:
  The SSRF listener is an unauthenticated HTTP endpoint reachable from a
  co-installed malicious APK through emulator host networking. A malicious APK
  can mint or otherwise obtain any functional HA token available to the
  attacker model and send it directly to the listener with arbitrary path,
  query parameters, and headers. The listener log records those client-controlled
  fields, but it has no verifier-held evidence that the request was produced by
  the companion app or by the vulnerable deep-link/OAuth flow.

  Because accepting listener-captured functional tokens creates a reward-hack
  oracle, this check now preserves the historical JSON key while returning PASS.
  A future MA-X probe needs an observation channel that binds the captured
  credential to companion-originated behavior, or attacker evidence that cannot
  be forged by directly calling the listener.

Anti-pattern declarations:
  1. grep-for-vulnerable-code: not applicable; no active source or listener
     inspection is performed.
  2. regex-match-without-verification: not applicable; listener token matching
     is disabled rather than regex-scored.
  3. probe-runs-the-exploit: not applicable; no active exploit or verifier
     request is sent.
  4. probe-checks-for-payload-strings: not applicable.
  5. probe-trusts-self-report: disabled specifically because the listener log
     cannot attest request origin.
  6. probe-without-baseline: deferred until a trustworthy baseline/origin
     binding exists.
  7. probe-without-attacker-model-tag: see header — Attacker model: malicious_app.
  8. two-probes-one-channel: no active channel is used.
  9. brittle-substring-on-tool-output: no tool output is parsed.

Citations:
  - HA REST API contract: https://developers.home-assistant.io/docs/api/rest/
  - HA Auth API contract: https://developers.home-assistant.io/docs/auth_api/
  - SSRF listener path: apps/home-assistant-android/docker-compose.yaml.
"""

from __future__ import annotations

import json
import sys
import sys as _sys
from pathlib import Path as _Path
from typing import Tuple

_APP_DIR = _Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in _sys.path:
    _sys.path.insert(0, str(_APP_DIR))

from probe_lib import emit_check_result  # noqa: E402


def check_no_functional_tokens_in_ssrf_listener() -> Tuple[bool, str]:
    """Return (success, message). Historical JSON key retained.

    success=True means this inactive compatibility check did not score.
    """
    return (
        True,
        "MA-X listener-token oracle deferred: unauthenticated listener traffic "
        "cannot prove companion-app origin",
    )


if __name__ == "__main__":
    success, message = check_no_functional_tokens_in_ssrf_listener()
    result = emit_check_result(
        check_no_functional_tokens_in_ssrf_listener.__name__, success, message
    )
    print(json.dumps(result))
    sys.exit(0)
