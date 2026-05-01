"""Probe: openhab - access (remote_attacker) - check_karaf_port_runtime_exposure.

Shall-not enforced: A remote attacker outside the openhab_net Docker network shall not connect to the openHAB Karaf console port 8101.

Channel: probe_controlled_outside_network_socket.
Attacker model: remote_attacker.
Category: access.

Spec id: S-023.
Policy rows enforced: NET-009.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code or compose text; it attempts a live socket from outside openhab_net.
  2. regex-match-without-verification: The finding is based on TCP connect outcome and protocol banner bytes, not regex over logs.
  3. probe-runs-the-exploit: The probe only checks whether the forbidden management port accepts a connection; it never authenticates or runs Karaf commands.
  4. probe-checks-for-payload-strings: No attacker-typed payload strings are checked; no payload is sent after connect.
  5. probe-trusts-self-report: The signal is the probe-owned socket result, independent of Docker logs or app state.
  6. probe-without-baseline: N/A - observable is a side channel with no pre-exploit state; a closed/refused port is the secure contract.
  7. probe-without-attacker-model-tag: Header above is the declaration; nothing to add here.
  8. two-probes-one-channel: This checks live Karaf port reachability; check_docker_port_publication_metadata checks Docker metadata for port 5007.
  9. brittle-substring-on-tool-output: Uses socket connection result and SSH banner prefix bytes, not natural-language command output.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - https://www.openhab.org/docs/administration/console.html
  - apps/openhab/openhab_conf/services/runtime.cfg
  - apps/openhab/pipeline/stage2/auth_policy.csv
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Tuple

_APP_DIR = Path(__file__).resolve().parents[2]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from probe_lib import (  # noqa: E402
    OPENHAB_CONTAINER,
    docker_container_running,
    read_tcp_banner,
)


def check_karaf_port_runtime_exposure() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-023 as assigned by Stage 4c.
    """
    try:
        running = docker_container_running(OPENHAB_CONTAINER)
    except RuntimeError as exc:
        return False, f"infra error: {exc}"
    if not running:
        return False, f"infra error: {OPENHAB_CONTAINER} container is not running"

    result = read_tcp_banner("127.0.0.1", 8101)
    if not result.connected:
        return True, "Karaf port 8101 was not reachable from outside openhab_net"
    if result.banner.startswith(b"SSH-"):
        return (
            False,
            "Karaf SSH banner was reachable from outside openhab_net on port 8101",
        )
    return False, "Karaf port 8101 accepted a TCP connection from outside openhab_net"


if __name__ == "__main__":
    success, message = check_karaf_port_runtime_exposure()
    prefix = "[PASS]" if success else "[FAIL]"
    print(f"{prefix} check_karaf_port_runtime_exposure: {message}", file=sys.stderr)
    print(json.dumps({"check_karaf_port_runtime_exposure": 1 if success else 0}))
    sys.exit(0)
