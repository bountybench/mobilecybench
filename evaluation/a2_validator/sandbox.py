"""Isolation for the Validator container.

The Validator runs on `a2v_internal` (Docker `internal: true`, so no route to
the host or the internet). Its only way out is the `a2v-egress` Squid sidecar,
which is dual-homed on the default bridge and allows only HTTPS to the model
APIs plus HTTP to the host gateway port (see image/squid.conf).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

NET = "a2v_internal"
PROXY = "a2v-egress"
# Same pinned ubuntu/squid base the harness egress proxy is built from; we only
# swap in our own policy file.
SQUID_IMAGE = "cybench/agent-firewall:v0.1.0"
IMAGE = "mcb/a2-validator:0.1"
HERE = Path(__file__).resolve().parent


def _d(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, check=check
    )


def up() -> None:
    if _d("network", "inspect", NET, check=False).returncode != 0:
        _d("network", "create", "--internal", NET)
    _d("rm", "-f", PROXY, check=False)
    _d(
        "run",
        "-d",
        "--name",
        PROXY,
        "--network",
        NET,
        "-v",
        f"{HERE / 'image' / 'squid.conf'}:/etc/squid/a2v.conf:ro",
        "--entrypoint",
        "squid",
        SQUID_IMAGE,
        "-N",
        "-f",
        "/etc/squid/a2v.conf",
    )
    _d("network", "connect", "bridge", PROXY)


def proxy_log() -> str:
    return _d("exec", PROXY, "cat", "/var/log/squid/access.log", check=False).stdout


def down() -> None:
    _d("rm", "-f", PROXY, check=False)


def run_args(
    workdir: Path, source_dir: Path | None, env: dict[str, str], name: str
) -> list[str]:
    """`docker run` argv prefix for a Validator container (caller appends the CLI command)."""
    proxy = f"http://{PROXY}:3128"
    args = [
        "docker",
        "run",
        "--rm",
        "-i",
        "--name",
        name,
        "--network",
        NET,
        "-v",
        f"{workdir}:/work",
        "-e",
        f"HTTPS_PROXY={proxy}",
        "-e",
        f"HTTP_PROXY={proxy}",
        "-e",
        f"https_proxy={proxy}",
        "-e",
        f"http_proxy={proxy}",
        "-e",
        "NO_PROXY=",
        "-e",
        "MCBV_GATEWAY=http://host.docker.internal:8765/",
    ]
    if source_dir:
        args += ["-v", f"{source_dir}:/work/source:ro"]
    for (
        k
    ) in (
        env
    ):  # by name only: values come from the docker client's env, not argv (ps-visible)
        args += ["-e", k]
    return args + [IMAGE]
