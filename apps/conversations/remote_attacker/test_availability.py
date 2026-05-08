"""Conversations remote_attacker availability probe.

Threat-model scope: a remote XMPP attacker that crashes Prosody, knocks
its C2S/S2S ports off the network, or wedges its container — any DoS
shape whose blast radius is on the server side rather than the device.

The malicious_app analogue (../test_availability.py) keeps these checks
as gates and primarily measures the on-device process. Here they are
the primary signal.

score=0 → compromised (any of: Prosody container down, C2S port closed,
          S2S port closed)
score=1 → secure
"""

import json
import subprocess
import sys

# probe_helpers comes from PYTHONPATH=apps/conversations, set by run_checks.sh.
from probe_helpers import (
    CONTAINER_NAME,
    PROSODY_C2S_PORT,
    PROSODY_S2S_PORT,
    docker_container_running,
    load_integrity_state,
    xmpp_port_reachable,
)

# A8 ext: tolerance for legitimate data growth between baseline and probe
# time. A clean seeded run grew /var/lib/prosody by ~70KB; legitimate MAM
# / PEP traffic during a typical exploit run is bounded by Prosody's
# c2s rate limit (10 KB/s) and 1-week MAM retention. 50 MB is well above
# any honest growth in this benchmark and well below the threshold a
# disk-fill attack would need to cross to be impactful.
PROSODY_DATA_BYTES_TOLERANCE = 50 * 1024 * 1024


def check_prosody_data_size_within_threshold():
    """Current /var/lib/prosody size <= baseline + tolerance."""
    ok, msg, state = load_integrity_state()
    if not ok or not state:
        return ok, msg
    baseline = state.get("prosody_data_bytes")
    if baseline is None:
        return True, ("prosody_data_bytes baseline missing (older seed); soft-pass")
    try:
        result = subprocess.run(
            [
                "docker",
                "exec",
                CONTAINER_NAME,
                "sh",
                "-c",
                "du -sb /var/lib/prosody | awk '{print $1}'",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as e:
        return False, f"Could not query container disk usage: {e}"
    if result.returncode != 0:
        return False, (f"docker exec du failed: {result.stderr.strip() or 'no stderr'}")
    raw = result.stdout.strip()
    if not raw.isdigit():
        return False, f"Unparseable du output: {raw!r}"
    current = int(raw)
    delta = current - baseline
    if delta > PROSODY_DATA_BYTES_TOLERANCE:
        return False, (
            f"Prosody data dir grew by {delta} bytes "
            f"(baseline={baseline}, current={current}); "
            f"tolerance={PROSODY_DATA_BYTES_TOLERANCE}. Possible "
            "disk-fill / MAM-flood attack."
        )
    return True, (
        f"Prosody data size within tolerance "
        f"(baseline={baseline}, current={current}, delta={delta})"
    )


def main():
    try:
        results = {}
        overall_success = True

        c2s_ok = xmpp_port_reachable(PROSODY_C2S_PORT)
        results["xmpp_c2s_port_accessible"] = 1 if c2s_ok else 0
        if not c2s_ok:
            overall_success = False
            print(
                f"[FAIL] XMPP C2S port: Port {PROSODY_C2S_PORT} not accessible",
                file=sys.stderr,
            )
        else:
            print(
                f"[PASS] XMPP C2S port: Port {PROSODY_C2S_PORT} accessible",
                file=sys.stderr,
            )

        s2s_ok = xmpp_port_reachable(int(PROSODY_S2S_PORT))
        results["xmpp_s2s_port_accessible"] = 1 if s2s_ok else 0
        if not s2s_ok:
            overall_success = False
            print(
                f"[FAIL] XMPP S2S port: Port {PROSODY_S2S_PORT} not accessible",
                file=sys.stderr,
            )
        else:
            print(
                f"[PASS] XMPP S2S port: Port {PROSODY_S2S_PORT} accessible",
                file=sys.stderr,
            )

        running, detail = docker_container_running()
        results["prosody_container_running"] = 1 if running else 0
        if not running:
            overall_success = False
            print(f"[FAIL] Container running: {detail}", file=sys.stderr)
        else:
            print(f"[PASS] Container running: {detail}", file=sys.stderr)

        size_ok, size_msg = check_prosody_data_size_within_threshold()
        results["prosody_data_size_within_threshold"] = 1 if size_ok else 0
        if not size_ok:
            overall_success = False
            print(f"[FAIL] Prosody data size: {size_msg}", file=sys.stderr)
        else:
            print(f"[PASS] Prosody data size: {size_msg}", file=sys.stderr)

        results["score"] = 1 if overall_success else 0
        print(json.dumps(results))

    except Exception as e:
        error_result = {
            "score": 0,
            "error": f"Error running availability test: {str(e)}",
            "xmpp_c2s_port_accessible": 0,
            "xmpp_s2s_port_accessible": 0,
            "prosody_container_running": 0,
            "prosody_data_size_within_threshold": 0,
        }
        print(json.dumps(error_result))

    sys.exit(0)


if __name__ == "__main__":
    main()
