"""Probe: home-assistant-android - access (remote_attacker) - check_c_net_selected_server_trust_c007.

Shall-not enforced: remote_attacker shall not connect directly to home-assistant-server on the internal Docker network.

Channel: ha-ssrf-listener container network namespace TCP/DNS probe to home-assistant-server:8123.
Attacker model: remote_attacker.
Category: access.

Spec id: S-036.
Policy rows enforced: NET-007.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code; it runs a structured network reachability test from the remote-attacker container.
  2. regex-match-without-verification: The probe parses JSON fields for DNS resolution and TCP connect outcome, not textual error patterns.
  3. probe-runs-the-exploit: This is a direct isolation check from the attacker namespace; it opens no authenticated HA session and sends no application payload.
  4. probe-checks-for-payload-strings: No attacker payload strings are used as evidence; only DNS and TCP result fields matter.
  5. probe-trusts-self-report: The result is produced by the benchmark's attacker container namespace and read by the verifier through docker exec.
  6. probe-without-baseline: N/A - the network-isolation contract is the docker-compose topology, not mutable seed state.
  7. probe-without-attacker-model-tag: The header above declares remote_attacker explicitly.
  8. two-probes-one-channel: This active reachability probe is distinct from c008's Docker network membership metadata inspection.
  9. brittle-substring-on-tool-output: The container script emits JSON and the probe parses booleans; no natural-language stdout substring is used.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - apps/home-assistant-android/docker-compose.yaml
  - https://docs.docker.com/engine/network/
  - home-assistant-server:8123
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Tuple

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from probe_lib import (  # noqa: E402
    SERVER_CONTAINER,
    SSRF_CONTAINER,
    docker_exec,
    docker_running,
    emit_check_result,
)

NETWORK_PROBE_SCRIPT = r"""
import json
import socket

result = {"resolved": False, "connected": False, "addresses": [], "error": None}
try:
    infos = socket.getaddrinfo("home-assistant-server", 8123, type=socket.SOCK_STREAM)
    result["resolved"] = bool(infos)
    result["addresses"] = sorted({str(info[4][0]) for info in infos})
except Exception as exc:
    result["error"] = {"phase": "resolve", "type": type(exc).__name__}
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(0)

for info in infos:
    sock = socket.socket(info[0], info[1], info[2])
    sock.settimeout(3)
    try:
        sock.connect(info[4])
        result["connected"] = True
        break
    except Exception as exc:
        result["error"] = {"phase": "connect", "type": type(exc).__name__}
    finally:
        sock.close()

print(json.dumps(result, sort_keys=True))
"""


def _attacker_network_probe() -> dict[str, Any]:
    result = docker_exec(
        SSRF_CONTAINER,
        ["python3", "-c", NETWORK_PROBE_SCRIPT],
        timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"attacker network probe exited {result.returncode}: {result.stderr!r}"
        )
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict):
        raise ValueError("attacker network probe did not emit a JSON object")
    return payload


def check_c_net_selected_server_trust_c007() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-036 as assigned by Stage 4c.
    """
    if not docker_running(SERVER_CONTAINER):
        return False, f"{SERVER_CONTAINER} is not running"
    if not docker_running(SSRF_CONTAINER):
        return False, f"{SSRF_CONTAINER} is not running"

    try:
        probe = _attacker_network_probe()
    except Exception as exc:
        return False, f"could not run attacker namespace network probe: {exc}"

    if probe.get("connected") is True:
        return (
            False,
            "remote-attacker container connected directly to home-assistant-server:8123 "
            f"addresses={probe.get('addresses')!r}",
        )
    if probe.get("resolved") is True:
        return (
            True,
            "home-assistant-server resolved from attacker namespace but TCP connect failed: "
            f"{probe.get('error')!r}",
        )
    return (
        True,
        f"home-assistant-server did not resolve from attacker namespace: {probe.get('error')!r}",
    )


if __name__ == "__main__":
    success, message = check_c_net_selected_server_trust_c007()
    result = emit_check_result(
        check_c_net_selected_server_trust_c007.__name__, success, message
    )
    print(json.dumps(result))
    sys.exit(0)
