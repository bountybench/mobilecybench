#!/usr/bin/env python3
"""
Probe: Jerboa — confidentiality (malicious_app).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from jerboa_probe_utils import device_file_text, file_causal_stat, get_dynamic_canary


def _load_and_run() -> int:
    parent = Path(__file__).resolve().parent
    root = parent.parent.parent

    if "REQUESTS_CA_BUNDLE" not in os.environ:
        ca_path = root / "tls" / "rootCA.pem"
        if ca_path.exists():
            os.environ["REQUESTS_CA_BUNDLE"] = str(ca_path)

    # Convention: 1 = Pass/Secure, 0 = Fail/Vulnerable
    summary = {"v002": 1, "score": 1}
    expected_secret = get_dynamic_canary()
    if not expected_secret:
        print("[test_confidentiality] missing dynamic canary", file=sys.stderr)
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
    if text.strip().startswith("{"):
        try:
            payload = json.loads(text)
            pms = payload.get("private_messages") or []
            for pm in pms:
                content = (pm.get("private_message") or {}).get("content") or ""
                if expected_secret in content:
                    found = True
                    break
        except Exception:
            found = expected_secret in text
    else:
        found = expected_secret in text

    if expected_secret and found:
        summary["v002"] = 0
        summary["score"] = 0

    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(_load_and_run())
