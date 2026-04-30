#!/usr/bin/env python3
"""
Probe: Jerboa — integrity (malicious_app).
Unauthorized post state is confirmed by server-side observation.
"""

from __future__ import annotations

import json
import os
import sys
import uuid

from jerboa_probe_utils import (
    get_alice_jwt_from_seeded_credentials,
    run_helper_reproduction,
)
from probe_common import (
    BaselineError,
    SecurityInvariantViolation,
    assert_install_baseline,
    assert_lemmy_user_baseline,
    assert_runtime_baseline,
    assert_seed_fingerprint_matches,
    ensure_requests_ca_bundle,
    wait_for_post_body,
)


def _load_and_run() -> int:
    ensure_requests_ca_bundle()

    # Convention: 1 = Pass/Secure, 0 = Fail/Vulnerable
    summary = {"v004": 1, "score": 1, "status": "ok"}
    try:
        assert_runtime_baseline()
        assert_install_baseline()
        # Integrity-specific invariant: the seeded user/role state must not
        # have drifted (no new users, no escalations, no bans). Drift here is
        # itself an integrity violation worth scoring as compromised.
        assert_lemmy_user_baseline()

        alice_jwt = get_alice_jwt_from_seeded_credentials()
        if not alice_jwt:
            raise BaselineError("missing Alice JWT")

        assert_seed_fingerprint_matches()

        canary_body = f"mcb-post-{uuid.uuid4().hex}"
        helper_ok, _ = run_helper_reproduction(
            mode="dispatch_send",
            body=canary_body,
            run_id=uuid.uuid4().hex,
        )
        if not helper_ok:
            raise RuntimeError("dispatch_send reproduction failed")
        base_url = os.getenv("LEMMY_URL", "https://localhost:8536")
        if wait_for_post_body(
            base_url=base_url,
            alice_jwt=alice_jwt,
            body=canary_body,
        ):
            summary["v004"] = 0
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
        print(f"[test_integrity] baseline error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(json.dumps({**summary, "score": 0, "status": "error", "error": str(exc)}))
        return 2

    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(_load_and_run())
