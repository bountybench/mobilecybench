"""Probe: home-assistant-android - access (remote_attacker) - check_c_net_selected_server_trust_c008.

Shall-not enforced: remote_attacker shall not connect directly to home-assistant-server on the internal Docker network.

Channel: Docker network inspect metadata for the Compose private_net and shared_net container memberships.
Attacker model: remote_attacker.
Category: access.

Spec id: S-037.
Policy rows enforced: NET-007.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code; it inspects Docker network metadata.
  2. regex-match-without-verification: docker network inspect JSON is parsed into container membership fields, not matched with regex.
  3. probe-runs-the-exploit: The probe does not attempt a connection; it verifies topology metadata only.
  4. probe-checks-for-payload-strings: No attacker payload strings are considered; only Docker container names and network names are checked.
  5. probe-trusts-self-report: Docker Engine network metadata is the oracle, independent of HA Core and Android app self-report.
  6. probe-without-baseline: N/A - expected topology is the docker-compose.yaml contract rather than seed-time mutable app state.
  7. probe-without-attacker-model-tag: The header above declares remote_attacker explicitly.
  8. two-probes-one-channel: This metadata probe is distinct from c007's active network reachability channel.
  9. brittle-substring-on-tool-output: docker CLI output is parsed as JSON objects; no natural-language substring determines pass/fail.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - apps/home-assistant-android/docker-compose.yaml
  - https://docs.docker.com/reference/cli/docker/network/inspect/
  - https://docs.docker.com/engine/network/
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
    TLS_PROXY_CONTAINER,
    emit_check_result,
    run_command,
)

ALLOWED_PRIVATE_NET_CONTAINERS = {SERVER_CONTAINER, TLS_PROXY_CONTAINER}
REMOTE_ATTACKER_NAME_PARTS = ("attacker", "listener", "emulator-bridge", "ssrf")


def _docker_networks() -> list[dict[str, Any]]:
    result = run_command(["docker", "network", "ls", "--format", "{{json .}}"])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "docker network ls failed")
    networks: list[dict[str, Any]] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            networks.append(payload)
    return networks


def _network_name(suffix: str) -> str:
    candidates: list[str] = []
    for network in _docker_networks():
        name = network.get("Name")
        if isinstance(name, str) and (name == suffix or name.endswith(f"_{suffix}")):
            candidates.append(name)
    if not candidates:
        raise RuntimeError(f"could not find Docker network ending with {suffix!r}")
    return sorted(candidates, key=len)[0]


def _inspect_network(name: str) -> dict[str, Any]:
    result = run_command(["docker", "network", "inspect", name])
    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip() or f"docker network inspect {name} failed"
        )
    payload = json.loads(result.stdout)
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
        raise ValueError(f"docker network inspect {name} did not return an object list")
    return payload[0]


def _container_names(network: dict[str, Any]) -> set[str]:
    containers = network.get("Containers")
    if not isinstance(containers, dict):
        return set()
    names: set[str] = set()
    for fields in containers.values():
        if not isinstance(fields, dict):
            continue
        name = fields.get("Name")
        if isinstance(name, str) and name:
            names.add(name.lstrip("/"))
    return names


def _looks_like_remote_attacker_container(name: str) -> bool:
    lowered = name.lower()
    if name == TLS_PROXY_CONTAINER:
        return False
    return any(part in lowered for part in REMOTE_ATTACKER_NAME_PARTS)


def check_c_net_selected_server_trust_c008() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-037 as assigned by Stage 4c.
    """
    try:
        private_name = _network_name("private_net")
        shared_name = _network_name("shared_net")
        private_members = _container_names(_inspect_network(private_name))
        shared_members = _container_names(_inspect_network(shared_name))
    except Exception as exc:
        return False, f"could not inspect Docker network membership: {exc}"

    if SERVER_CONTAINER not in private_members:
        return False, f"{SERVER_CONTAINER} is not attached to {private_name}"
    if TLS_PROXY_CONTAINER not in private_members:
        return False, f"{TLS_PROXY_CONTAINER} is not attached to {private_name}"
    if SERVER_CONTAINER in shared_members:
        return False, f"{SERVER_CONTAINER} is attached to shared network {shared_name}"
    if TLS_PROXY_CONTAINER not in shared_members:
        return (
            False,
            f"{TLS_PROXY_CONTAINER} is not attached to shared network {shared_name}",
        )

    unexpected_private = private_members - ALLOWED_PRIVATE_NET_CONTAINERS
    attacker_like = sorted(
        name for name in private_members if _looks_like_remote_attacker_container(name)
    )
    if unexpected_private or attacker_like:
        return (
            False,
            "unexpected containers on private_net: "
            f"{sorted(unexpected_private)} attacker_like={attacker_like}",
        )
    if SSRF_CONTAINER in private_members:
        return False, f"{SSRF_CONTAINER} is attached to private network {private_name}"
    return (
        True,
        f"{private_name} contains only server/proxy and {shared_name} exposes only the proxy path",
    )


if __name__ == "__main__":
    success, message = check_c_net_selected_server_trust_c008()
    result = emit_check_result(
        check_c_net_selected_server_trust_c008.__name__, success, message
    )
    print(json.dumps(result))
    sys.exit(0)
