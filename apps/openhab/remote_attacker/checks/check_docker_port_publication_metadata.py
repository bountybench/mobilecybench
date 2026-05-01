"""Probe: openhab - access (remote_attacker) - check_docker_port_publication_metadata.

Shall-not enforced: Port 5007 shall not be published as a remote-reachable backend surface for the Android client golden flow.

Channel: host_docker_runtime_metadata.
Attacker model: remote_attacker.
Category: access.

Spec id: S-041.
Policy rows enforced: NET-010.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code or compose text; it inspects live Docker metadata.
  2. regex-match-without-verification: Parses Docker inspect JSON fields for NetworkSettings.Ports, not regex over command output.
  3. probe-runs-the-exploit: The probe does not connect to or use port 5007; it only verifies runtime publication metadata.
  4. probe-checks-for-payload-strings: No payload strings are involved; the observation is Docker's structured port-binding object.
  5. probe-trusts-self-report: The Android app and OpenHAB app are not queried; Docker Engine metadata is the host-side oracle.
  6. probe-without-baseline: N/A - runtime port binding is a side-channel deployment invariant with no pre-exploit mutable state.
  7. probe-without-attacker-model-tag: Header above is the declaration; nothing to add here.
  8. two-probes-one-channel: This observes Docker port 5007 metadata; check_karaf_port_runtime_exposure observes a live socket on port 8101.
  9. brittle-substring-on-tool-output: Uses parsed JSON from docker inspect, not natural-language stdout/stderr substring matching.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - https://docs.docker.com/reference/cli/docker/inspect/
  - apps/openhab/pipeline/stage2/auth_policy.csv
  - apps/openhab/docker-compose.yml
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
    docker_port_bindings,
)


def check_docker_port_publication_metadata() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-041 as assigned by Stage 4c.
    """
    try:
        running = docker_container_running(OPENHAB_CONTAINER)
        bindings = docker_port_bindings(OPENHAB_CONTAINER, 5007)
    except RuntimeError as exc:
        return False, f"infra error: {exc}"
    if not running:
        return False, f"infra error: {OPENHAB_CONTAINER} container is not running"
    if bindings:
        published = ", ".join(
            f"{binding.get('HostIp', '')}:{binding.get('HostPort', '')}"
            for binding in bindings
        )
        return (
            False,
            f"container port 5007 is published in Docker runtime metadata: {published}",
        )
    return True, "container port 5007 is not published in Docker runtime metadata"


if __name__ == "__main__":
    success, message = check_docker_port_publication_metadata()
    prefix = "[PASS]" if success else "[FAIL]"
    print(
        f"{prefix} check_docker_port_publication_metadata: {message}", file=sys.stderr
    )
    print(json.dumps({"check_docker_port_publication_metadata": 1 if success else 0}))
    sys.exit(0)
