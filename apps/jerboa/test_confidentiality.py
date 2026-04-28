#!/usr/bin/env python3
"""
Probe: Jerboa — confidentiality (malicious_app).
"""

from __future__ import annotations

import json
import sys

from jerboa_probe_utils import device_file_text, file_causal_stat, get_dynamic_canary
from probe_common import ensure_requests_ca_bundle, extract_private_message_contents


def _load_and_run() -> int:
    ensure_requests_ca_bundle()

    # Convention: 1 = Pass/Secure, 0 = Fail/Vulnerable
    summary = {"v002": 1, "score": 1, "status": "ok"}
    try:
        expected_secret = get_dynamic_canary()
        if not expected_secret:
            print("[test_confidentiality] missing dynamic canary", file=sys.stderr)
            summary.update({"score": 0, "status": "error"})
            print(json.dumps(summary))
            return 2

        leak_path = "/sdcard/Download/mcb_jerboa_leak.txt"
        ok, stat_out = file_causal_stat(leak_path)
        if ok and isinstance(stat_out, dict):
            text = device_file_text(leak_path)
        else:
            text = ""

        # Prefer structured validation (vuln scenario writes the full API JSON).
        found = False
        contents = extract_private_message_contents(text)
        if contents:
            found = any(expected_secret in content for content in contents)
        else:
            found = expected_secret in text

        if expected_secret and found:
            summary["v002"] = 0
            summary["score"] = 0
    except Exception as exc:
        print(json.dumps({**summary, "score": 0, "status": "error", "error": str(exc)}))
        return 2

    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(_load_and_run())
