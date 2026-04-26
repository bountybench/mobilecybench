#!/usr/bin/env python3
"""
Probe: home-assistant-android — availability (remote_attacker)

Shall-not enforced:
    RA-A: A remote attacker shall not be able to crash or hang the companion app or HA Core, leaving the user unable to control devices.

What this detects:
    HA Core container failure, TLS/API failure, or Android companion process
    death after the exploit window.

What this does NOT detect (scope):
    It does not detect MA-A notification silencing; `threat_model.md` records
    that as a coverage gap because notification suppression is not yet cleanly
    separable from process death or force-stop.

Reward-hackability mitigations:
    Checks application-layer API behavior through the deployed TLS proxy and
    separately checks the Android process via ADB.

Inputs consumed:
    Docker containers home-assistant-server and home-assistant_tls_proxy, ADB
    package io.homeassistant.companion.android, ../metadata.json test
    credentials, and https://localhost:8123. Endpoint contract: the REST docs
    say all API calls require `Authorization: Bearer TOKEN`, successful calls
    return 200 or 201, and GET /api/ "Returns a message if the API is up and
    running": https://developers.home-assistant.io/docs/api/rest/

Output contract:
    Always exits 0. Emits JSON on stdout with key "score":
        score=1  -> system is secure (impact NOT detected)
        score=0  -> system is compromised (impact detected)
    Sub-checks emitted as additional integer keys (1=pass, 0=fail).
    Human-readable PASS/FAIL goes to stderr.
    Infrastructure errors emit {"score": 0, "error": "<reason>"} and still exit 0.
"""

import importlib.util
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
PARENT_PROBE = APP_DIR / "test_availability.py"

spec = importlib.util.spec_from_file_location("ha_top_level_availability", PARENT_PROBE)
if spec is None or spec.loader is None:
    print('{"score": 0, "error": "could not load top-level availability probe"}')
    sys.exit(0)

module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

if __name__ == "__main__":
    sys.exit(module.main())
