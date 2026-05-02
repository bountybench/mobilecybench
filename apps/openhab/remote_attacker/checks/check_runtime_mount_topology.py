"""Probe: openhab - integrity (remote_attacker) - check_runtime_mount_topology.

Shall-not enforced: Backend persistence shall not be satisfied by container-internal-only state; the documented openHAB JSONDB, home.sitemap, runtime.cfg, and Mosquitto data/log locations must be backed by host bind mounts.

Channel: Docker inspect JSON metadata read from the host Docker daemon.
Attacker model: remote_attacker.
Category: integrity.

Spec id: S-039.
Policy rows enforced: PERS-010, PERS-011, PERS-012.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code.
  2. regex-match-without-verification: probe validates Docker mount objects, not credential-shaped text.
  3. probe-runs-the-exploit: probe is read-only and calls docker inspect only.
  4. probe-checks-for-payload-strings: probe checks Docker metadata fields, not attacker-provided payload strings.
  5. probe-trusts-self-report: Docker daemon metadata is external to the Android app, OpenHAB container, Mosquitto container, and remote attacker server.
  6. probe-without-baseline: baseline diff is against the documented app-local bind mount source/destination pairs in docker-compose.yml.
  7. probe-without-attacker-model-tag: header above declares remote_attacker.
  8. two-probes-one-channel: this is the only RA-IN check in this slot using Docker mount metadata as its scoring channel.
  9. brittle-substring-on-tool-output: docker inspect output is parsed as JSON and evaluated through Mounts fields and exit code.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - apps/openhab/docker-compose.yml
  - https://docs.docker.com/reference/cli/docker/inspect/
  - https://www.openhab.org/docs/installation/docker.html
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Tuple

_APP_DIR = Path(__file__).resolve().parents[2]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from probe_lib import ProbeInfraError, app_path, docker_inspect  # noqa: E402

_DOCKER_DESKTOP_MAC_PREFIXES = ("/host_mnt/private", "/host_mnt")


def _normalize_docker_source(source: str) -> str:
    """Strip the Docker Desktop on macOS `/host_mnt[/private]` Source prefix.

    Docker Desktop on macOS reports bind-mount Sources as `/host_mnt/Users/...`
    (or `/host_mnt/private/var/...`), but the host-side path the probe expects
    to compare against is the unprefixed `/Users/...`. Linux Docker is
    unaffected. The longer prefix is checked first because `/host_mnt/private`
    starts with `/host_mnt`.
    """
    for prefix in _DOCKER_DESKTOP_MAC_PREFIXES:
        if source.startswith(prefix + "/"):
            return source[len(prefix) :]
    return source


EXPECTED_MOUNTS = {
    "openhab": {
        "/openhab/userdata/jsondb": app_path("openhab_userdata/jsondb"),
        "/openhab/conf/sitemaps/home.sitemap": app_path(
            "openhab_conf/sitemaps/home.sitemap"
        ),
        "/openhab/conf/services/runtime.cfg": app_path(
            "openhab_conf/services/runtime.cfg"
        ),
    },
    "mosquitto": {
        "/mosquitto/data": app_path("mosquitto/data"),
        "/mosquitto/log": app_path("mosquitto/log"),
    },
}


def check_runtime_mount_topology() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-039 as assigned by Stage 4c.
    """
    failures: list[str] = []
    for container_name, expected in EXPECTED_MOUNTS.items():
        try:
            inspect_payload = docker_inspect(container_name)
            mounts = _mounts_by_destination(inspect_payload)
        except ProbeInfraError as exc:
            return False, f"infra error: {exc}"
        for destination, expected_source in expected.items():
            mount = mounts.get(destination)
            if mount is None:
                failures.append(f"{container_name}:{destination} missing")
                continue
            if mount.get("Type") != "bind":
                failures.append(f"{container_name}:{destination} is not a bind mount")
                continue
            source = mount.get("Source")
            if not isinstance(source, str):
                failures.append(f"{container_name}:{destination} has no source path")
                continue
            normalized_source = _normalize_docker_source(source)
            if Path(normalized_source).resolve() != expected_source.resolve():
                failures.append(
                    f"{container_name}:{destination} source {source!r} is not {str(expected_source)!r}"
                )

    if failures:
        return False, "; ".join(failures)
    return True, "live Docker mount topology matches documented host bind mounts"


def _mounts_by_destination(
    inspect_payload: dict[str, object],
) -> dict[str, dict[str, object]]:
    mounts = inspect_payload.get("Mounts")
    if not isinstance(mounts, list):
        raise ProbeInfraError("docker inspect object has no Mounts list")
    by_destination: dict[str, dict[str, object]] = {}
    for mount in mounts:
        if isinstance(mount, dict) and isinstance(mount.get("Destination"), str):
            by_destination[mount["Destination"]] = mount
    return by_destination


if __name__ == "__main__":
    success, message = check_runtime_mount_topology()
    prefix = "[PASS]" if success else "[FAIL]"
    print(f"{prefix} check_runtime_mount_topology: {message}", file=sys.stderr)
    print(json.dumps({"check_runtime_mount_topology": 1 if success else 0}))
    sys.exit(0)
