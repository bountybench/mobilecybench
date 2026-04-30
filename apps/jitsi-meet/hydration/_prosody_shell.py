"""Shared helper: prosodyctl shell command runner.

`apps/jitsi-meet/start_runtime.sh:inject_admin_modules_into_defaults`
enables admin_socket and admin_shell. We drive Prosody admin operations
through `docker exec <container> prosodyctl shell` fed via stdin.
"""

from __future__ import annotations

import os
import subprocess

DEFAULT_CONTAINER = os.environ.get("PROSODY_CONTAINER", "jitsi-latest-prosody-1")


def shell(
    commands: list[str], container: str = DEFAULT_CONTAINER, timeout: int = 30
) -> tuple[int, str]:
    """Run a list of admin_shell commands and return (returncode, output).

    Each command is sent as one line. We append `quit` so prosodyctl
    shell exits cleanly rather than waiting on stdin.
    """
    payload = "\n".join([*commands, "quit", ""])
    cp = subprocess.run(
        ["docker", "exec", "-i", container, "prosodyctl", "shell"],
        input=payload,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return cp.returncode, (cp.stdout or "") + (cp.stderr or "")


def container_exists(container: str = DEFAULT_CONTAINER) -> bool:
    cp = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return container in (cp.stdout or "")
