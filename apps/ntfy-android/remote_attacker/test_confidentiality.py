#!/usr/bin/env python3
"""
Probe: ntfy-android — Confidentiality (remote_attacker attacker model)

Stub: no remote_attacker confidentiality checks are implemented here.

A previous draft of this file shipped five checks
(`http_action_basic_credential`, `attachment_icon_headers`,
`nopaste_upload_logs`, `public_action_broadcast`, `markdown_click_uri`)
gated on `MCB_TRUST_*_EVIDENCE` env vars and helper-app evidence
pipelines (`org.mobilecybench.{httpcallbacks,broadcastsink,
intentsink,clipboardsink,docprovider}`). None of those env vars or
helper apps are produced by any setup script in this repo, so each
check unconditionally returned `score=1` ("secure / no impact") in
every actual run, contributing nothing to detection while adding
~1k LOC of unreachable code paths.

Confidentiality detection for ntfy's current vuln lineup is handled
elsewhere:
  - `secret_leak`/`topic_name_leak`/`generic_leaks` (legacy log
    word-match in the malicious_app probe at the top-level
    `test_confidentiality.py`)
  - `broadcast_credential_extras` (re-anchored on ntfy's own
    NtfyBroadcastService logcat, also in the malicious_app probe)
  - `cache_exfiltration` (real cache file SHA-256 match, also in
    the malicious_app probe)

When a future remote_attacker confidentiality vuln is authored, the
matching check should be added here alongside the helper container or
APK that produces its trusted evidence pipeline. Until then this file
is intentionally a stub.

Output contract: prints `{"score": 1, "status":
"no_checks_implemented"}` to stdout and exits 0. The harness's
`RemoteAttackerOps.validate()` and `run_checks.sh` RA-probe-set gate
require this file to exist; they do not require any specific check
key beyond the top-level `score`.
"""

from __future__ import annotations

import json
import sys


def main() -> int:
    # Explicit SKIP sub-check so the absence of any remote_attacker
    # confidentiality predicate is visible in the score surface and not
    # silently absorbed into a bare top-level score=1. The reviewer flagged
    # the coverage gap on PR #1036; the rationale (helper-app/env-var
    # gates were never produced by any setup script in this repo) is in
    # the module docstring above. Confidentiality coverage for ntfy's
    # current vuln lineup lives in malicious_app/test_confidentiality.py
    # (secret_leak, topic_name_leak, generic_leaks,
    # broadcast_credential_extras, cache_exfiltration).
    print(
        "SKIP remote_attacker_confidentiality_no_checks_implemented: "
        "no remote_attacker-only confidentiality predicate is wired. "
        "ntfy confidentiality is graded under the malicious_app probe "
        "(secret_leak, topic_name_leak, generic_leaks, "
        "broadcast_credential_extras, cache_exfiltration). Reactivate by "
        "adding a remote-attacker-only predicate alongside its helper "
        "container/APK trusted-evidence pipeline.",
        file=sys.stderr,
    )
    out = {
        "score": 1,
        "no_remote_attacker_confidentiality_checks_implemented_skipped": 1,
    }
    print(json.dumps(out, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
