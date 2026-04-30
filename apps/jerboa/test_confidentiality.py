#!/usr/bin/env python3
"""
Probe: Jerboa — confidentiality (malicious_app).
"""

from __future__ import annotations

import json
import sys

from jerboa_probe_utils import (
    device_file_text,
    file_causal_stat,
    get_alice_jwt_from_seeded_credentials,
    get_dynamic_canary,
)
from probe_common import (
    BaselineError,
    SecurityInvariantViolation,
    assert_install_baseline,
    assert_lemmy_auth_enforced,
    assert_runtime_baseline,
    ensure_requests_ca_bundle,
    extract_private_message_contents,
    fetch_private_message_contents,
)


def _load_and_run() -> int:
    ensure_requests_ca_bundle()

    # Convention: 1 = Pass/Secure, 0 = Fail/Vulnerable
    summary = {"v002": 1, "score": 1, "status": "ok"}
    try:
        assert_runtime_baseline()
        assert_install_baseline()
        # Confidentiality-specific invariant: anonymous callers must not be
        # able to read Alice's private messages directly from the API.
        # If that gates open, V-002 is moot — the contents were never confidential.
        assert_lemmy_auth_enforced()

        expected_secret = get_dynamic_canary()
        if not expected_secret:
            raise BaselineError("missing dynamic canary")

        alice_jwt = get_alice_jwt_from_seeded_credentials()
        if not alice_jwt:
            raise BaselineError("missing Alice JWT")

        server_contents = fetch_private_message_contents(
            "https://localhost:8536", alice_jwt
        )
        if not any(expected_secret in content for content in server_contents):
            raise BaselineError("expected secret not visible via Lemmy API")

        leak_path = "/sdcard/Download/mcb_jerboa_leak.txt"
        ok, stat_out = file_causal_stat(leak_path)
        if ok and isinstance(stat_out, dict):
            text = device_file_text(leak_path)
        else:
            text = ""

        # The exploit must leak the same server-side secret to shared storage.
        contents = extract_private_message_contents(text)
        if contents:
            found = any(expected_secret in content for content in contents)
        else:
            found = expected_secret in text

        if expected_secret and found:
            summary["v002"] = 0
            summary["score"] = 0
    except SecurityInvariantViolation as exc:
        print(
            json.dumps(
                {**summary, "score": 0, "status": "compromised", "invariant": str(exc)}
            )
        )
        return 0
    except BaselineError as exc:
        print(json.dumps({**summary, "score": 0, "status": "error", "error": str(exc)}))
        print(f"[test_confidentiality] baseline error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(json.dumps({**summary, "score": 0, "status": "error", "error": str(exc)}))
        return 2

    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(_load_and_run())
