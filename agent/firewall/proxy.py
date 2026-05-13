"""Egress-proxy (Squid) sidecar lifecycle.

The agent's only L3 path off ``agent_net`` (which is ``internal: true``) is
this sidecar. Combined with the kernel firewall on agent_net, it is the
single egress chokepoint for the agent.

Squid policy lives in ``agent/firewall/image/``; the ``mode`` argument to
:func:`start` selects the conf the image's entrypoint loads.
"""

from pathlib import Path
from typing import Iterable
from urllib.parse import urlsplit

import docker
import docker.errors

from utils.logger import logger

AGENT_NET = "agent_net"
SHARED_NET = "shared_net"
EXTERNAL_BRIDGE = "bridge"  # Docker's default bridge — the sidecar's path to internet

EGRESS_PROXY_CONTAINER = "egress-proxy"
EGRESS_PROXY_IMAGE = "cybench/squid-firewall:latest"
EGRESS_PROXY_PORT = 3128
VALID_NETWORK_MODES = ("restricted", "permissive")

_IMAGE_BUILD_CONTEXT = Path(__file__).parent / "image"


def _ensure_image(client) -> None:
    """Build the image locally if absent."""
    try:
        client.images.get(EGRESS_PROXY_IMAGE)
        return
    except docker.errors.ImageNotFound:
        pass
    logger.info(f"Building {EGRESS_PROXY_IMAGE} from {_IMAGE_BUILD_CONTEXT}")
    client.images.build(path=str(_IMAGE_BUILD_CONTEXT), tag=EGRESS_PROXY_IMAGE, rm=True)


def start(mode: str) -> None:
    """Start Squid dual-homed on agent_net + Docker's default bridge.

    ``mode`` (one of :data:`VALID_NETWORK_MODES`) is passed to the entrypoint
    as ``SQUID_MODE``; the entrypoint loads ``squid_<mode>.conf``.
    """
    if mode not in VALID_NETWORK_MODES:
        raise ValueError(f"network_mode={mode!r} not in {VALID_NETWORK_MODES}")

    client = docker.from_env()
    _ensure_image(client)
    stop()

    container = client.containers.run(
        image=EGRESS_PROXY_IMAGE,
        name=EGRESS_PROXY_CONTAINER,
        environment={"SQUID_MODE": mode},
        detach=True,
        network=AGENT_NET,
    )
    client.networks.get(EXTERNAL_BRIDGE).connect(container)
    logger.info(f"Egress proxy started (mode={mode}, :{EGRESS_PROXY_PORT})")


def stop() -> None:
    """Stop and remove the sidecar if present."""
    client = docker.from_env()
    try:
        container = client.containers.get(EGRESS_PROXY_CONTAINER)
    except docker.errors.NotFound:
        return
    container.stop(timeout=5)
    container.remove(force=True)
    logger.info("Egress proxy stopped")


def proxy_url() -> str:
    return f"http://{EGRESS_PROXY_CONTAINER}:{EGRESS_PROXY_PORT}"


def build_no_proxy(metadata: dict, extra_aliases: Iterable[str] = ()) -> str:
    """Compose ``NO_PROXY``: in-cluster targets the agent reaches DIRECTLY.

    Python HTTP clients match by hostname suffix; CIDR isn't supported.
    Always includes loopback and the proxy hostname (so clients don't
    tunnel proxy→proxy). The app host is parsed from
    ``metadata['app_server']``; callers append other in-cluster sidecars
    via ``extra_aliases``.
    """
    parts = ["localhost", "127.0.0.1", EGRESS_PROXY_CONTAINER, *extra_aliases]
    app_host = _parse_host(metadata.get("app_server"))
    if app_host:
        parts.append(app_host)
    return ",".join(parts)


def _parse_host(app_server: str | None) -> str:
    """Extract bare hostname from a server string.

    Accepts ``scheme://host[:port][/path]`` or ``host[:port][/path]``.
    Returns "" for missing/unparseable inputs.
    """
    if not app_server:
        return ""
    # urlsplit needs a scheme to recognise the netloc; prepend a dummy if absent.
    raw = app_server if "://" in app_server else f"//{app_server}"
    return urlsplit(raw).hostname or ""
