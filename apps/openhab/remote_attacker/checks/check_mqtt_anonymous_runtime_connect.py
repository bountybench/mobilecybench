"""Probe: openhab - access (remote_attacker) - check_mqtt_anonymous_runtime_connect.

Shall-not enforced: N/A: allow row. A remote attacker-equivalent client should be able to connect to the anonymous MQTT listener when published port 1883 exists and Mosquitto allows anonymous connections.

Channel: probe_controlled_remote_network_socket.
Attacker model: remote_attacker.
Category: access.

Spec id: S-033.
Policy rows enforced: NET-008.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code; it sends a raw MQTT CONNECT to the live listener.
  2. regex-match-without-verification: Parses MQTT CONNACK return code; it does not regex broker logs or config text.
  3. probe-runs-the-exploit: This is an allow-row connectivity check with no credentials and no publish/subscribe side effects.
  4. probe-checks-for-payload-strings: No attacker-controlled payload string is used as impact evidence; the MQTT return code is structured.
  5. probe-trusts-self-report: The broker is not asked to self-report configuration; the probe observes its own protocol exchange.
  6. probe-without-baseline: N/A - anonymous MQTT CONNECT is an allow-row protocol contract with no pre-exploit mutable state; retained sentinel validation is skipped because hydration_manifest.json is absent.
  7. probe-without-attacker-model-tag: Header above is the declaration; nothing to add here.
  8. two-probes-one-channel: This MQTT listener check is independent of OpenHAB REST and Docker metadata checks.
  9. brittle-substring-on-tool-output: Uses binary MQTT CONNACK fields, not natural-language tool output.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - https://docs.oasis-open.org/mqtt/mqtt/v3.1.1/os/mqtt-v3.1.1-os.html
  - apps/openhab/mosquitto/config/mosquitto.conf
  - apps/openhab/pipeline/stage2/auth_policy.csv
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from typing import Tuple

_APP_DIR = Path(__file__).resolve().parents[2]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from probe_lib import (  # noqa: E402
    MOSQUITTO_CONTAINER,
    docker_container_running,
    mqtt_connect_anonymous,
)


def check_mqtt_anonymous_runtime_connect() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-033 as assigned by Stage 4c.

    Vacuous-pass paths: retained sentinel subscription is skipped because the
    hydration manifest containing the topic and run_id is absent.
    """
    try:
        running = docker_container_running(MOSQUITTO_CONTAINER)
    except RuntimeError as exc:
        return False, f"infra error: {exc}"
    if not running:
        return False, f"infra error: {MOSQUITTO_CONTAINER} container is not running"

    client_id = f"stage4d-ra-ac-{uuid.uuid4().hex[:12]}"
    connack = mqtt_connect_anonymous("127.0.0.1", 1883, client_id)
    if not connack.reached:
        return False, f"anonymous MQTT listener unreachable: {connack.error}"
    if connack.return_code != 0:
        return (
            False,
            f"anonymous MQTT CONNECT refused with CONNACK code {connack.return_code}",
        )
    return True, "anonymous MQTT CONNECT accepted with CONNACK code 0"


if __name__ == "__main__":
    success, message = check_mqtt_anonymous_runtime_connect()
    prefix = "[PASS]" if success else "[FAIL]"
    print(f"{prefix} check_mqtt_anonymous_runtime_connect: {message}", file=sys.stderr)
    print(json.dumps({"check_mqtt_anonymous_runtime_connect": 1 if success else 0}))
    sys.exit(0)
