"""Egress firewall for the agent container.

The agent runs on ``agent_net`` (``internal: true``) — kernel deny-all
egress. The Squid sidecar (``proxy.py``) is the only outbound path, with
exact-FQDN allowlist baked into the image at ``image/``.
"""

from agent.firewall.proxy import (
    AGENT_NET,
    EGRESS_PROXY_CONTAINER,
    EXTERNAL_BRIDGE,
    SHARED_NET,
    build_no_proxy,
    proxy_url,
    start,
    stop,
)

__all__ = [
    "AGENT_NET",
    "EGRESS_PROXY_CONTAINER",
    "EXTERNAL_BRIDGE",
    "SHARED_NET",
    "build_no_proxy",
    "proxy_url",
    "start",
    "stop",
]
