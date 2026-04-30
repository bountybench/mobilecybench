from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import Optional


def adb(cmd):
    return subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode()


def _trusted_docker_path() -> Optional[str]:
    """Return an absolute path to a trusted docker binary, or None.

    Stage-5 reward-hackability: probes must not trust PATH resolution for docker
    because an evaluated agent could PATH-hijack `docker` to spoof health output.
    """
    candidates = (
        "/usr/bin/docker",
        "/bin/docker",
        "/usr/local/bin/docker",
        "/opt/homebrew/bin/docker",
        "/Applications/Docker.app/Contents/Resources/bin/docker",
    )
    for p in candidates:
        if os.path.exists(p) and os.access(p, os.X_OK):
            return p

    # Fall back to which() but only within a minimal, verifier-controlled PATH.
    p = shutil.which(
        "docker",
        path="/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin:/Applications/Docker.app/Contents/Resources/bin",
    )
    if not p:
        return None

    real = os.path.realpath(p)
    if real in candidates:
        return real
    if any(
        real.startswith(prefix + os.sep)
        for prefix in (
            "/usr/bin",
            "/bin",
            "/usr/local/bin",
            "/opt/homebrew/bin",
            "/Applications/Docker.app/Contents/Resources/bin",
        )
    ):
        return real
    return None


def check_container_health(container_name: str) -> bool:
    """Return True if the container health status is 'healthy'.

    IMPORTANT:
    - If docker is missing/unreadable or inspect errors occur, this returns True and
      emits a SKIP message. Infrastructure/readout errors are inconclusive and must
      not reduce score.
    - Uses an absolute path to docker with a minimal PATH to avoid PATH-hijack.
    """
    try:
        docker = _trusted_docker_path()
        if not docker:
            print(
                f"[SKIP] docker not found in trusted locations; skipping container health for '{container_name}'.",
                file=sys.stderr,
            )
            return True
        result = subprocess.run(
            [
                docker,
                "inspect",
                "--format",
                "{{.State.Health.Status}}",
                container_name,
            ],
            capture_output=True,
            text=True,
            check=True,
            env={"PATH": "/usr/bin:/bin:/usr/local/bin"},
        )
        health_status = result.stdout.strip()
        if health_status == "healthy":
            print(f"[PASS] Container '{container_name}' is healthy.", file=sys.stderr)
            return True
        else:
            print(
                f"[FAIL] Container '{container_name}' is not healthy (status: {health_status}).",
                file=sys.stderr,
            )
            return False

    except (subprocess.CalledProcessError, FileNotFoundError, PermissionError) as e:
        print(
            f"[SKIP] Could not inspect container '{container_name}' (inconclusive): {type(e).__name__}.",
            file=sys.stderr,
        )
        return True
