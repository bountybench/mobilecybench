"""Emulator certificate management for local HTTPS backends."""

import subprocess
from pathlib import Path

from utils.logger import logger

# API 34+ CA injection can legitimately take longer on cold boots while zygote
# PIDs stabilize and mount namespaces are verified across retries.
INJECT_CA_TIMEOUT = 180


def inject_system_ca(project_root: Path) -> None:
    """Add shared CA cert to emulator trust store so apps trust local HTTPS backends."""
    script = project_root / "utils" / "inject_system_ca.sh"
    if not script.exists():
        logger.warning(f"CA injection script not found: {script}")
        return

    logger.info("Injecting system CA certificate...")
    try:
        result = subprocess.run(
            ["bash", str(script)],
            capture_output=True,
            text=True,
            timeout=INJECT_CA_TIMEOUT,
        )
    except subprocess.TimeoutExpired as e:
        logger.error(f"CA injection timed out after {INJECT_CA_TIMEOUT}s")
        if e.stdout:
            logger.error(f"stdout before timeout:\n{e.stdout}")
        if e.stderr:
            logger.error(f"stderr before timeout:\n{e.stderr}")
        raise
    if result.returncode != 0:
        logger.error(f"CA injection failed (exit {result.returncode})")
        logger.error(f"stdout: {result.stdout}")
        logger.error(f"stderr: {result.stderr}")
        raise RuntimeError("System CA injection failed")
    logger.info("System CA injected successfully")
