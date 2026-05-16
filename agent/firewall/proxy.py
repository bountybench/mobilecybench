"""Egress-proxy (Squid) sidecar lifecycle.

The agent's only L3 path off ``agent_net`` (which is ``internal: true``) is
this sidecar. Combined with the kernel firewall on agent_net, it is the
single egress chokepoint for the agent.

Squid policy lives in ``agent/firewall/image/``; the ``mode`` argument to
:func:`start` selects the conf the image's entrypoint loads.
"""

import io
import shutil
import tarfile
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
EGRESS_PROXY_REPO = "cybench/agent-firewall"
EGRESS_PROXY_TAG = "v0.1.0"
EGRESS_PROXY_PORT = 3128
VALID_NETWORK_MODES = ("restricted", "permissive")
SQUID_LOG_ARTIFACTS = (
    ("/var/log/squid/access.log", "squid_access.log"),
    ("/var/log/squid/cache.log", "squid_cache.log"),
)

_IMAGE_BUILD_CONTEXT = Path(__file__).parent / "image"


def _ensure_image(client) -> str:
    """Cascade: local cache → registry pull → in-tree build."""
    tag = f"{EGRESS_PROXY_REPO}:{EGRESS_PROXY_TAG}"
    try:
        client.images.get(tag)
        return tag
    except docker.errors.ImageNotFound:
        pass
    try:
        logger.info(f"Pulling {tag}")
        client.images.pull(EGRESS_PROXY_REPO, tag=EGRESS_PROXY_TAG)
        return tag
    except (docker.errors.ImageNotFound, docker.errors.APIError) as e:
        logger.info(f"Pull failed ({e}); building {tag} from {_IMAGE_BUILD_CONTEXT}")
    client.images.build(path=str(_IMAGE_BUILD_CONTEXT), tag=tag, rm=True)
    return tag


def start(mode: str) -> None:
    """Start Squid dual-homed on agent_net + Docker's default bridge.

    ``mode`` (one of :data:`VALID_NETWORK_MODES`) is passed to the entrypoint
    as ``SQUID_MODE``; the entrypoint loads ``squid_<mode>.conf``.
    """
    if mode not in VALID_NETWORK_MODES:
        raise ValueError(f"network_mode={mode!r} not in {VALID_NETWORK_MODES}")

    client = docker.from_env()
    tag = _ensure_image(client)
    stop()

    container = client.containers.run(
        image=tag,
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


def save_logs(dest_dir: Path) -> dict[str, Path]:
    """Copy Squid logs from the live sidecar into ``dest_dir``.

    Must run before :func:`stop`; removing the sidecar also removes Squid's
    in-container access/cache logs.
    """
    try:
        client = docker.from_env()
        container = client.containers.get(EGRESS_PROXY_CONTAINER)
    except docker.errors.NotFound:
        logger.info("No egress proxy container found; skipping Squid log capture")
        return {}
    except Exception as e:
        logger.warning("Failed to access egress proxy for log capture: %s", e)
        return {}

    captured: dict[str, Path] = {}
    dest_dir.mkdir(parents=True, exist_ok=True)

    for container_path, artifact_name in SQUID_LOG_ARTIFACTS:
        try:
            exists = container.exec_run(["test", "-f", container_path])
            if exists.exit_code != 0:
                logger.info("No Squid log found at %s", container_path)
                continue

            bits, _ = container.get_archive(container_path)
            stream = io.BytesIO()
            for chunk in bits:
                stream.write(chunk)
            stream.seek(0)

            artifact_path = dest_dir / artifact_name
            with tarfile.open(fileobj=stream) as tar:
                member = next(
                    (item for item in tar.getmembers() if item.isfile()), None
                )
                if member is None:
                    logger.warning(
                        "Squid log archive for %s had no file", container_path
                    )
                    continue
                src = tar.extractfile(member)
                if src is None:
                    logger.warning(
                        "Could not extract Squid log archive member %s", member.name
                    )
                    continue
                with open(artifact_path, "wb") as dst:
                    shutil.copyfileobj(src, dst)

            captured[artifact_name] = artifact_path
            logger.info("Saved Squid log %s to %s", container_path, artifact_path)
        except Exception as e:
            logger.warning("Failed to save Squid log %s: %s", container_path, e)

    return captured


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
